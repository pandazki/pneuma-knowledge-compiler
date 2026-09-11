"""The probe and the unattended launcher, against harnesses that are not one.

Keyless and subscription-free: `tests/fake_harness/` holds a `codex` and a `claude` that
accept the flags our manifests emit, read stdin, and print the shape each backend really
prints. Putting them first on `PATH` is the whole fixture, and it exercises everything §8
puts around a harness — the liveness probe, the argv, the prompt travelling in a file, the
wall clock, the reaping, the backoff, and reading usage out of the harness's own report.

What is deliberately NOT faked is our side: the manifests, `render_argv`, `launch_round` and
`probe` are the shipped code, called exactly as the worker calls them.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from pneuma_knowledge_service.coding_agent import backends
from pneuma_knowledge_service.coding_agent.backends import CLAUDE_CODE, CODEX
from pneuma_knowledge_service.coding_agent.harness_output import (
    read_claude_output,
    read_codex_output,
)
from pneuma_knowledge_service.coding_agent.launcher import (
    BACKEND_ENV,
    BACKOFF_CEILING_S,
    LaunchRequest,
    backoff_wait,
    build_argv,
    launch_round,
    stdin_text,
)
from pneuma_knowledge_service.coding_agent.probe import probe

FAKE_DIR = Path(__file__).parent / "fake_harness"

SYSTEM_TEXT = "SYSTEM: the contract this round writes under"
TASK_TEXT = "TASK: the material of this round\n\n- 一句会议记录"


@pytest.fixture
def fake_path(monkeypatch, tmp_path):
    """`tests/fake_harness/` first on PATH, and a log the fakes append their argv to."""
    monkeypatch.setenv("PATH", f"{FAKE_DIR}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "invocations.jsonl"
    monkeypatch.setenv("PKC_FAKE_LOG", str(log))
    monkeypatch.setenv("PKC_FAKE_COUNTER", str(tmp_path / "attempts.txt"))
    monkeypatch.delenv("PKC_FAKE_MODE", raising=False)
    monkeypatch.delenv("PKC_FAKE_SCRIPT", raising=False)
    return log


def invocations(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def request(manifest, tmp_path, **kwargs) -> LaunchRequest:  # noqa: ANN001
    base = {
        "manifest": manifest,
        "system_text": SYSTEM_TEXT,
        "task_text": TASK_TEXT,
        "project_dir": str(tmp_path / "project"),
        "config_home": str(tmp_path / "home"),
        "timeout_s": 30.0,
        "retries": 0,
    }
    (tmp_path / "project").mkdir(exist_ok=True)
    return LaunchRequest(**{**base, **kwargs})


# ───────────────────────────────────────────────────────────────────────────────── the probe


async def test_a_live_harness_probes_live(fake_path):
    for manifest in (CODEX, CLAUDE_CODE):
        result = await probe(manifest, deadline_s=20)
        assert result.ok, result.reason
        assert result.binary_path.endswith(f"/{manifest.binary}")


async def test_a_harness_that_is_not_installed_is_named_as_such(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))  # nothing in it
    result = await probe(CODEX, deadline_s=5)
    assert not result.ok
    assert "not on PATH" in result.reason
    assert result.binary_path == ""


async def test_installed_but_not_logged_in_is_a_different_answer_from_missing(
    fake_path, monkeypatch
):
    """The failure that matters: the binary is there and the liveness command says no.

    This is what `codex login status` exiting non-zero looks like, and the reason has to name
    it — an operator who reads "not on PATH" for a login problem installs a second copy.
    """
    monkeypatch.setenv("PKC_FAKE_MODE", "fail")
    result = await probe(CODEX, deadline_s=10)
    assert not result.ok
    assert "not logged in" in result.reason
    assert result.binary_path  # it IS installed


async def test_a_harness_that_hangs_is_killed_at_the_deadline_and_says_so(
    fake_path, monkeypatch
):
    """An unfinished login waits forever. The probe must not: TERM the group, then KILL."""
    monkeypatch.setenv("PKC_FAKE_MODE", "hang")
    started = time.monotonic()
    result = await probe(CODEX, deadline_s=1.0)
    assert time.monotonic() - started < 10, "the probe did not return at its deadline"
    assert not result.ok
    assert "did not answer within 1s" in result.reason


async def test_the_probe_never_compares_a_version():
    """Ruling 9 as a property of the data: no manifest's liveness command asks for one."""
    for manifest in (CODEX, CLAUDE_CODE):
        assert "--version" not in manifest.probe_command
        assert "-V" not in manifest.probe_command


# ─────────────────────────────────────────────── reading a harness's own report of a round


def test_several_codex_turns_are_summed_because_each_states_its_own(tmp_path):
    stream = "\n".join(
        json.dumps({"type": "turn.completed", "usage": usage})
        for usage in (
            {"input_tokens": 100, "output_tokens": 10},
            {"input_tokens": 300, "output_tokens": 40},
        )
    )
    assert read_codex_output(stream).usage == {
        "input_tokens": 400,
        "output_tokens": 50,
        "total_tokens": 450,
    }


def test_anthropics_cache_counts_are_beside_its_input_and_are_added():
    """Two providers, two vocabularies: Anthropic reports cache reads BESIDE `input_tokens`,
    so a round whose context was cached would otherwise report a fraction of what it spent."""
    document = json.dumps(
        {
            "type": "result",
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 50,
                "output_tokens": 25,
            },
        }
    )
    assert read_claude_output(document).usage == {
        "input_tokens": 1050,
        "output_tokens": 25,
        "total_tokens": 1075,
    }


# ──────────────────────────────────────────────────────────────────────────── the argv


def test_the_prompt_is_never_in_argv(tmp_path):
    """§8's hard rule: a process list on a shared machine is not where material belongs."""
    for manifest in (CODEX, CLAUDE_CODE):
        argv = build_argv(request(manifest, tmp_path), tmp_path / "wd")
        joined = " ".join(argv)
        assert TASK_TEXT.splitlines()[0] not in joined
        assert SYSTEM_TEXT not in joined


def test_each_backend_carries_the_system_text_on_its_own_channel(tmp_path):
    """Claude replaces its preamble with a file; Codex has no channel, so the text heads
    stdin. Both are the same bytes in the same order — I5 does not weaken by travelling
    differently."""
    claude_argv = build_argv(request(CLAUDE_CODE, tmp_path), tmp_path / "wd")
    assert "--system-prompt-file" in claude_argv
    assert claude_argv[claude_argv.index("--system-prompt-file") + 1].endswith("system.txt")
    assert stdin_text(request(CLAUDE_CODE, tmp_path)) == TASK_TEXT

    codex_argv = build_argv(request(CODEX, tmp_path), tmp_path / "wd")
    assert "--system-prompt-file" not in codex_argv
    piped = stdin_text(request(CODEX, tmp_path))
    assert piped.startswith(SYSTEM_TEXT)
    assert piped.endswith(TASK_TEXT)


def test_an_unnamed_model_drops_its_flag_rather_than_passing_an_empty_one(tmp_path):
    with_model = build_argv(request(CODEX, tmp_path, model="gpt-x"), tmp_path / "wd")
    assert with_model[with_model.index("-m") + 1] == "gpt-x"
    without = build_argv(request(CODEX, tmp_path), tmp_path / "wd")
    assert "-m" not in without
    assert "" not in without


def test_a_named_reasoning_effort_rides_both_the_launch_and_the_repair_round(tmp_path):
    """The whole point of the setting: the Owner's global harness config says one thing and
    the library's rounds say another, in the argv of both the first round and the repair."""
    launch = build_argv(request(CODEX, tmp_path, reasoning_effort="medium"), tmp_path / "wd")
    assert launch[launch.index("-c") + 1 :].count("model_reasoning_effort=medium") == 1
    resumed = build_argv(
        request(CODEX, tmp_path, reasoning_effort="medium", resume_session="anything"),
        tmp_path / "wd",
    )
    assert resumed[:3] == ["codex", "exec", "resume"]
    assert "model_reasoning_effort=medium" in resumed


def test_an_unnamed_effort_drops_its_flag_and_leaves_no_dangling_one(tmp_path):
    """The same one substitution rule the model pair rides: an empty placeholder takes the
    flag before it, so the sandbox's own `-c` is the only one left."""
    without = build_argv(request(CODEX, tmp_path), tmp_path / "wd")
    assert not [argument for argument in without if "model_reasoning_effort" in argument]
    assert without.count("-c") == 1
    assert without[without.index("-c") + 1] == "sandbox_workspace_write.network_access=true"
    assert "" not in without


def test_a_harness_that_states_no_effort_flags_never_carries_one(tmp_path):
    """Claude Code's CLI has no reasoning-effort flag in this version, so a configured effort
    is dropped rather than invented. Read off the manifest, never off a backend name."""
    assert CLAUDE_CODE.effort_flags == ()
    argv = build_argv(
        request(CLAUDE_CODE, tmp_path, model="claude-x", reasoning_effort="medium"),
        tmp_path / "wd",
    )
    assert argv[argv.index("--model") + 1] == "claude-x"
    assert not [argument for argument in argv if "effort" in argument]
    assert "medium" not in argv


def test_an_effort_no_harness_takes_is_refused_where_it_is_written():
    """Not in a launched argv minutes later, one process out, in somebody else's stderr."""
    from pneuma_knowledge_service.settings import AGENT_REASONING_EFFORTS, Settings

    assert Settings(_env_file=None, agent_reasoning_effort="medium").agent_reasoning_effort == "medium"
    assert Settings(_env_file=None).agent_reasoning_effort == ""
    with pytest.raises(ValidationError) as refusal:
        Settings(_env_file=None, agent_reasoning_effort="ultra")
    message = str(refusal.value)
    assert "ultra" in message
    for effort in AGENT_REASONING_EFFORTS:
        assert effort in message


def test_the_worker_states_the_round_s_model_and_effort_rather_than_inheriting_them():
    """A per-job config home is SEEDED from the Owner's own, so a round with nothing stated
    thinks at whatever the Owner set for their own terminal. The worker is where the
    deployment's answer is stated, beside the other settings it already hands over."""
    import inspect

    from pneuma_knowledge_service.coding_agent.round_runner import AgentRoundRunner
    from pneuma_knowledge_service.workers import compile_worker

    source = inspect.getsource(compile_worker.process_agent_job)
    assert "model=str(ctx.settings.agent_model)" in source
    assert "reasoning_effort=agent_round_effort(ctx.settings, kind)" in source
    assert "reasoning_effort=self.reasoning_effort" in inspect.getsource(AgentRoundRunner._launch)


def test_an_episodes_round_thinks_at_its_own_effort_and_every_other_round_does_not(tmp_path):
    """Episodes rounds (L2 boundaries for one source) may run at their own effort; compile
    and evolve rounds keep the library's, and an empty episodes effort inherits it."""
    from pneuma_knowledge_service.settings import Settings
    from pneuma_knowledge_service.workers.compile_worker import agent_round_effort

    settings = Settings(
        _env_file=None, agent_reasoning_effort="medium", agent_reasoning_effort_episodes="low"
    )

    def effort_in_argv(kind: str) -> list[str]:
        effort = agent_round_effort(settings, kind)
        argv = build_argv(request(CODEX, tmp_path, reasoning_effort=effort), tmp_path / "wd")
        return [argument for argument in argv if argument.startswith("model_reasoning_effort=")]

    assert effort_in_argv("episodes") == ["model_reasoning_effort=low"]
    assert effort_in_argv("compile") == ["model_reasoning_effort=medium"]
    assert effort_in_argv("evolve") == ["model_reasoning_effort=medium"]
    inherited = Settings(_env_file=None, agent_reasoning_effort="medium")
    assert inherited.agent_reasoning_effort_episodes == ""
    assert agent_round_effort(inherited, "episodes") == "medium"
    assert agent_round_effort(Settings(_env_file=None), "episodes") == ""
    with pytest.raises(ValidationError, match="ultra"):
        Settings(_env_file=None, agent_reasoning_effort_episodes="ultra")


def _global_render(directory: Path, backend: str) -> Path:
    """What `pkchome skill install` leaves: the router SKILL.md with its version marker."""
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: pkc-steward\n---\nglobal router\n")
    (directory / "skill-version.json").write_text(json.dumps({"backend": backend}))
    return directory / "SKILL.md"


def test_a_codex_round_sees_only_its_library_s_skill_package(tmp_path, monkeypatch):
    """Codex reads `~/.agents/skills` from HOME whatever `CODEX_HOME` says. On a machine where
    that directory and `~/.claude/skills` are one directory behind symlinks, the Owner's global
    Claude Code copy was listed beside the library's package and read first. The round's skill
    roots are its per-job config home (which holds no skills), the manifest's HOME roots (whose
    copies are switched off by path), and the project's own package."""
    from pneuma_knowledge_service.coding_agent.launcher import (
        foreign_skill_copies,
        harness_env,
        seed_config_home,
    )

    owner = tmp_path / "owner"
    monkeypatch.setenv("HOME", str(owner))
    shared = owner / ".mirasim" / "skills"
    leaked = _global_render(shared / "pkc-steward", "claude-code")
    for harness in (".agents", ".claude"):
        (owner / harness).mkdir(parents=True)
        (owner / harness / "skills").symlink_to(shared)
    _global_render(owner / ".codex" / "skills" / "pkc-steward", "codex")
    (owner / ".codex" / "auth.json").write_text("{}")
    project = tmp_path / "project"
    own = _global_render(project / CODEX.skill_dir, "codex")

    assert CODEX.home_skill_roots == ("~/.agents/skills",)
    through_home = str(owner / ".agents" / "skills" / "pkc-steward" / "SKILL.md")
    hidden = foreign_skill_copies(CODEX, str(project))
    assert hidden == (through_home, str(leaked.resolve()))
    assert str(own) not in hidden and str(own.resolve()) not in hidden

    argv = build_argv(request(CODEX, tmp_path, project_dir=str(project), hidden_skills=hidden),
                      tmp_path / "wd")
    override = argv[argv.index(f"skills.config=[{{path={json.dumps(through_home)}, enabled=false}}, "
                                f"{{path={json.dumps(str(leaked.resolve()))}, enabled=false}}]") - 1]
    assert override == "-c"
    assert str(own) not in " ".join(argv)

    # The Owner's `~/.codex/skills` copy is out of reach because the round's CODEX_HOME is not
    # the Owner's: it is seeded with credentials and configuration, and no skills directory.
    round_home = tmp_path / "round-home"
    seed_config_home(CODEX, round_home)
    assert sorted(path.name for path in round_home.iterdir()) == ["auth.json"]
    assert harness_env(CODEX, config_home=str(round_home))["CODEX_HOME"] == str(round_home)

    # Nothing foreign, nothing stated: the flag pair drops and the sandbox `-c` stands alone.
    (shared / "pkc-steward" / "SKILL.md").unlink()
    assert foreign_skill_copies(CODEX, str(project)) == ()
    plain = build_argv(request(CODEX, tmp_path, project_dir=str(project)), tmp_path / "wd")
    assert not [argument for argument in plain if argument.startswith("skills.config")]


def test_a_library_reached_through_a_home_root_is_never_hidden_from_itself(tmp_path, monkeypatch):
    """If the library's own package is what a HOME root resolves to, it is the one it keeps."""
    from pneuma_knowledge_service.coding_agent.launcher import foreign_skill_copies

    owner = tmp_path / "owner"
    monkeypatch.setenv("HOME", str(owner))
    project = tmp_path / "project"
    _global_render(project / CODEX.skill_dir, "codex")
    (owner / ".agents").mkdir(parents=True)
    (owner / ".agents" / "skills").symlink_to(project / CODEX.skills_dir)
    assert foreign_skill_copies(CODEX, str(project)) == ()


def test_a_claude_round_reads_user_skills_only_from_its_own_config_home(tmp_path, monkeypatch):
    """Claude Code's user-level skills live under `CLAUDE_CONFIG_DIR`, which a round gets per
    job, seeded with credentials and settings only — so it names no HOME root and carries no
    switch, and a global copy under `~/.claude/skills` is out of its reach."""
    from pneuma_knowledge_service.coding_agent.launcher import foreign_skill_copies, seed_config_home

    owner = tmp_path / "owner"
    monkeypatch.setenv("HOME", str(owner))
    _global_render(owner / ".claude" / "skills" / "pkc-steward", "claude-code")
    assert CLAUDE_CODE.home_skill_roots == () and CLAUDE_CODE.render_hidden_skills is None
    assert foreign_skill_copies(CLAUDE_CODE, str(tmp_path / "project")) == ()
    round_home = tmp_path / "round-home"
    seed_config_home(CLAUDE_CODE, round_home)
    assert not (round_home / "skills").exists()
    argv = build_argv(request(CLAUDE_CODE, tmp_path, hidden_skills=("/x/SKILL.md",)),
                      tmp_path / "wd")
    assert not [argument for argument in argv if "skills.config" in argument]


def test_the_harness_gets_a_shell_and_not_the_open_world(tmp_path):
    """It has to run `pkc`, so `--tools ""` is wrong here; it must not have more than that.

    Codex's side of the same statement is the sandbox: it may execute, and the only place it
    may write is the empty working directory the launcher made.
    """
    claude_argv = build_argv(request(CLAUDE_CODE, tmp_path), tmp_path / "wd")
    assert claude_argv[claude_argv.index("--tools") + 1] == "Bash,Read"
    codex_argv = build_argv(request(CODEX, tmp_path), tmp_path / "wd")
    assert codex_argv[codex_argv.index("--sandbox") + 1] == "workspace-write"
    assert "--dangerously-bypass-approvals-and-sandbox" not in codex_argv


def test_a_repair_round_resumes_the_session_where_the_manifest_can(tmp_path):
    resumed = build_argv(
        request(CLAUDE_CODE, tmp_path, resume_session="sess-1"), tmp_path / "wd"
    )
    assert resumed[resumed.index("--resume") + 1] == "sess-1"
    # Codex resumes by position under its own per-job home, so no session id is needed.
    codex = build_argv(request(CODEX, tmp_path, resume_session="anything"), tmp_path / "wd")
    assert codex[:3] == ["codex", "exec", "resume"]
    assert "--last" in codex


# ─────────────────────────────────────────────────────────────────── a real launched round


async def test_a_round_runs_in_an_empty_directory_with_a_hermetic_config_home(fake_path, tmp_path):
    result = await launch_round(request(CODEX, tmp_path))
    assert result.ok, result.stderr
    (record,) = invocations(fake_path)
    # The working directory holds the round's own three files and nothing of the project.
    assert set(record["workdir_entries"]) == {"system.txt", "task.txt", "last-message.txt"}
    assert record["cwd"] != str(tmp_path / "project")
    assert record["env"]["CODEX_HOME"] == str(tmp_path / "home")
    assert record["env"][BACKEND_ENV] == "codex"
    # The prompt reached it, and it reached it on stdin.
    assert TASK_TEXT in record["stdin"]
    assert SYSTEM_TEXT in record["stdin"]


async def test_a_claude_round_is_never_told_it_is_nested(fake_path, tmp_path, monkeypatch):
    """`CLAUDECODE` set makes a Claude session believe it is nested and short-circuit, so a
    worker started from inside one would launch rounds that do nothing."""
    monkeypatch.setenv("CLAUDECODE", "1")
    result = await launch_round(request(CLAUDE_CODE, tmp_path))
    assert result.ok
    (record,) = invocations(fake_path)
    assert "CLAUDECODE" not in record["env"]
    assert record["env"]["CLAUDE_CONFIG_DIR"] == str(tmp_path / "home")


async def test_the_working_directory_is_deleted_unless_a_setting_says_keep_it(
    fake_path, tmp_path
):
    result = await launch_round(request(CODEX, tmp_path))
    assert result.workdir == ""
    kept = await launch_round(request(CODEX, tmp_path, keep_workdir=True))
    assert kept.workdir and Path(kept.workdir).is_dir()
    assert (Path(kept.workdir) / "task.txt").read_text().endswith(TASK_TEXT)


async def test_a_hung_harness_cannot_hold_the_worker_past_the_timeout(
    fake_path, tmp_path, monkeypatch
):
    monkeypatch.setenv("PKC_FAKE_MODE", "hang")
    started = time.monotonic()
    result = await launch_round(request(CODEX, tmp_path, timeout_s=1.0))
    elapsed = time.monotonic() - started
    assert elapsed < 15, f"the launcher held the worker for {elapsed:.1f}s"
    assert result.timed_out
    assert not result.ok
    assert result.usage is None  # nothing measured anything


# ────────────────────────────────────────────────────────────────────────────── usage


async def test_each_backend_s_own_report_is_read_into_one_shape(fake_path, tmp_path):
    codex = await launch_round(request(CODEX, tmp_path))
    # `cached_input_tokens` is the cached PORTION of `input_tokens`, so it is not added.
    assert codex.usage == {"input_tokens": 900, "output_tokens": 250, "total_tokens": 1150}
    # Codex prices nothing: the round ran on the Owner's subscription.
    assert codex.cost_usd is None
    assert codex.session_id == "th-fake-codex"

    claude = await launch_round(request(CLAUDE_CODE, tmp_path))
    assert claude.usage == {"input_tokens": 1300, "output_tokens": 300, "total_tokens": 1600}
    assert claude.cost_usd == pytest.approx(0.0421)
    assert claude.session_id == "sess-fake-claude"


async def test_a_harness_that_reports_nothing_reports_nothing_not_zero(
    fake_path, tmp_path, monkeypatch
):
    """An unknown protocol surface degrades and is logged (§8). A zero would be a claim that
    the round was free (story 2.15)."""
    monkeypatch.setenv("PKC_FAKE_MODE", "silent")
    for manifest in (CODEX, CLAUDE_CODE):
        result = await launch_round(request(manifest, tmp_path))
        assert result.usage is None
        assert result.cost_usd is None


def test_usage_parsing_survives_output_that_is_not_the_shape_we_expect():
    for reader in (read_codex_output, read_claude_output):
        assert reader("").usage is None
        assert reader("not json at all\n<html>").usage is None
        assert reader('{"type":"result"}').usage is None


def test_last_message_readers_capture_the_final_steward_text():
    stream = "\n".join(json.dumps(event) for event in [
        {"type": "item.completed", "item": "an unfamiliar surface"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Working."}},
        {"type": "item.completed", "item": {"type": "command_execution", "text": "tool output"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Consolidated delivery owners."}},
    ])
    assert read_codex_output(stream).last_message == "Consolidated delivery owners."
    assert read_codex_output("", "The output-file brief.").last_message == "The output-file brief."
    assert read_claude_output(json.dumps({
        "type": "result", "result": "Consolidated delivery owners.",
    })).last_message == "Consolidated delivery owners."


def test_a_cumulative_codex_total_is_read_once_and_not_summed():
    """Where a Codex version reports a RUNNING total, summing them would multiply the round.

    The shape 0.151 emits is a per-turn `turn.completed.usage`, which IS summed; this is the
    other surface, read tolerantly so a version bump does not silently lose the counts.
    """
    stream = "\n".join(
        json.dumps({"type": "token_count", "info": {"total_token_usage": usage}})
        for usage in (
            {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            {"input_tokens": 300, "output_tokens": 40, "total_tokens": 340},
        )
    )
    assert read_codex_output(stream).usage == {
        "input_tokens": 300,
        "output_tokens": 40,
        "total_tokens": 340,
    }


# ─────────────────────────────────────────────────────────────────────────────── backoff


async def test_a_rate_limit_is_waited_out_and_every_wait_is_logged(
    fake_path, tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("PKC_FAKE_MODE", "rate-limit")
    monkeypatch.setenv("PKC_FAKE_LIVE_AFTER", "3")  # the third attempt succeeds
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    with caplog.at_level("WARNING"):
        result = await launch_round(
            request(CODEX, tmp_path, retries=3), sleep=record, rng=random.Random(7)
        )
    assert result.ok
    assert result.attempts == 3
    assert len(waits) == 2 and all(0 < w <= BACKOFF_CEILING_S for w in waits)
    assert waits[1] > waits[0], "the backoff did not grow"
    assert sum("rate limit" in r.getMessage() for r in caplog.records) == 2


async def test_a_rate_limit_keeps_its_tight_spacing(fake_path, tmp_path, monkeypatch):
    """The usage-limit side of the split, pinned where it was: 5 s, then 10 s, ±25%."""
    from pneuma_knowledge_service.coding_agent.launcher import BACKOFF_BASE_S, BACKOFF_JITTER

    monkeypatch.setenv("PKC_FAKE_MODE", "rate-limit")
    monkeypatch.setenv("PKC_FAKE_LIVE_AFTER", "3")
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    result = await launch_round(
        request(CODEX, tmp_path, retries=3), sleep=record, rng=random.Random(7)
    )
    assert result.ok and result.attempts == 3
    for wait, base in zip(waits, (BACKOFF_BASE_S, 2 * BACKOFF_BASE_S), strict=True):
        assert base * (1 - BACKOFF_JITTER) <= wait <= base * (1 + BACKOFF_JITTER)


async def test_a_model_at_capacity_is_waited_out_wider_inside_one_launch(
    fake_path, tmp_path, monkeypatch, caplog
):
    """Capacity comes and goes within seconds-to-minutes. Relaunching five seconds later
    mostly met the same refusal, and four quick refusals then cooled the whole tenant; spaced
    15 s, 30 s, 60 s, a brief dip is absorbed here and the tenant never cools."""
    from pneuma_knowledge_service.coding_agent.launcher import BACKOFF_JITTER, CAPACITY_BACKOFF_S

    monkeypatch.setenv("PKC_FAKE_MODE", "at-capacity")
    monkeypatch.setenv("PKC_FAKE_LIVE_AFTER", "4")  # the fourth attempt finds room
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    with caplog.at_level("WARNING"):
        result = await launch_round(
            request(CODEX, tmp_path, retries=3), sleep=record, rng=random.Random(7)
        )
    assert result.ok and result.attempts == 4
    assert CAPACITY_BACKOFF_S == (15.0, 30.0, 60.0)
    for wait, base in zip(waits, CAPACITY_BACKOFF_S, strict=True):
        assert base * (1 - BACKOFF_JITTER) <= wait <= base * (1 + BACKOFF_JITTER)
    assert sum("the model at capacity" in r.getMessage() for r in caplog.records) == 3


async def test_the_retry_budget_is_a_bound_and_the_result_says_it_was_hit(
    fake_path, tmp_path, monkeypatch
):
    monkeypatch.setenv("PKC_FAKE_MODE", "rate-limit")  # never recovers

    async def instantly(seconds: float) -> None:
        return None

    result = await launch_round(request(CODEX, tmp_path, retries=1), sleep=instantly)
    assert result.attempts == 2
    assert result.rate_limited
    assert not result.ok


async def test_a_refusal_that_is_not_a_rate_limit_is_reported_rather_than_retried(
    fake_path, tmp_path, monkeypatch
):
    """A harness that refused the task will refuse it again; what it left behind is what the
    worker reads next."""
    monkeypatch.setenv("PKC_FAKE_MODE", "fail")
    result = await launch_round(request(CODEX, tmp_path, retries=3))
    assert result.attempts == 1
    assert not result.rate_limited
    assert result.exit_code == 1


async def test_a_model_at_capacity_is_read_off_stdout_even_at_exit_zero(
    fake_path, tmp_path, monkeypatch
):
    """The failure signature observed live, and the two things that hid it.

    `codex exec -m <model>` answered `{"type":"turn.failed" … "Selected model is at capacity
    …"}` — on STDOUT, as a JSON event, with an exit code a launcher reads as success. No tool
    calls, no draft touched. Read as a successful round it becomes a compile that wrote
    nothing; read as what it is, it is the same transient refusal a rate limit is, and it
    takes the same backoff and the same outcome.
    """
    monkeypatch.setenv("PKC_FAKE_MODE", "at-capacity")

    async def instantly(seconds: float) -> None:
        return None

    result = await launch_round(request(CODEX, tmp_path, retries=1), sleep=instantly)
    assert result.exit_code == 0, "the harness itself said nothing was wrong"
    assert result.rate_limited, "a turn the harness declared failed is not a finished round"
    assert result.attempts == 2, "it is waited out like any other transient refusal"
    assert backends.unavailable_reason(result.stdout, CODEX) == "at capacity"


def test_a_failed_turn_is_read_out_of_the_codex_event_stream():
    from pneuma_knowledge_service.coding_agent.harness_output import read_codex_output

    line = (
        '{"type":"turn.failed","error":{"message":'
        '"Selected model is at capacity. Please try a different model."}}'
    )
    report = read_codex_output(line)
    assert report.failed
    assert report.failure_message == "Selected model is at capacity. Please try a different model."
    assert report.usage is None, "a turn that did not happen spent nothing"


def test_the_same_words_inside_a_round_that_succeeded_are_not_a_refusal():
    """The scan runs at exit 0 only because the harness's own protocol said the turn failed.

    A library about a venue at capacity is not a library whose harness is down, and a marker
    match on ordinary output would take that library's whole queue off the air.
    """
    from pneuma_knowledge_service.coding_agent.launcher import _is_rate_limited

    prose = "the venue was at capacity; 429 people attended"
    assert not _is_rate_limited(CODEX, 0, prose)
    assert _is_rate_limited(CODEX, 0, prose, failed=True)


def test_the_backoff_grows_with_jitter_and_stops_at_the_ceiling():
    rng = random.Random(11)
    waits = [backoff_wait(n, rng=rng) for n in range(1, 12)]
    assert waits[0] < waits[3]
    assert all(w <= BACKOFF_CEILING_S * 1.25 for w in waits)


# ─────────────────────────────────────────────────────────── nothing branches on a name


def test_no_module_outside_the_manifest_branches_on_a_backend_name():
    """Ruling 9, checked the only way it can be: the launcher and the probe never mention one."""
    for module in ("launcher.py", "probe.py", "round_runner.py", "harness_output.py"):
        source = (
            Path(backends.__file__).parent / module
        ).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        for name in ("codex", "claude-code"):
            assert f'== "{name}"' not in code
            assert f'"{name}" ==' not in code


# ───────────────────────────────────── which library the launched harness stands in (B2)


def test_the_child_is_told_the_connection_settings_the_worker_resolved():
    """The launched harness runs in an empty `mkdtemp` with no project `.env` in it, so its
    `pkc` resolved the framework's own development defaults and read a DIFFERENT library than
    the worker that launched it. The worker states its own stack instead."""
    from pneuma_knowledge_service.coding_agent.launcher import (
        CONNECTION_SETTINGS,
        connection_env,
        harness_env,
    )
    from pneuma_knowledge_service.settings import Settings

    settings = Settings(
        pg_dsn="postgresql://u:p@localhost:52180/pneuma_knowledge",
        qdrant_url="http://localhost:57897",
        qdrant_collection="pneuma_app_chunks",
        meili_url="http://localhost:44322",
        meili_key="masterKey_change_me",
        canonical_root="./data/canonical",
        engine_dir="./engine",
        media_s3_endpoint_url="http://localhost:48304",
    )
    stated = connection_env(settings)
    assert {name for name, _ in CONNECTION_SETTINGS} <= set(stated)
    assert stated["PNEUMA_KNOWLEDGE_PG_DSN"] == settings.pg_dsn
    assert stated["PNEUMA_KNOWLEDGE_QDRANT_COLLECTION"] == "pneuma_app_chunks"
    # The two paths are made absolute: `./data/canonical` resolved in a mkdtemp is an empty
    # library the harness would happily create.
    assert Path(stated["PNEUMA_KNOWLEDGE_CANONICAL_ROOT"]).is_absolute()
    assert Path(stated["PNEUMA_KNOWLEDGE_ENGINE_DIR"]).is_absolute()

    env = harness_env(CODEX, config_home="/tmp/home", settings=settings)
    for name, value in stated.items():
        assert env[name] == value


def test_no_settings_states_nothing_and_extra_still_wins():
    from pneuma_knowledge_service.coding_agent.launcher import connection_env, harness_env
    from pneuma_knowledge_service.settings import Settings

    assert connection_env(None) == {}
    env = harness_env(CODEX, config_home="/tmp/home")
    assert "PNEUMA_KNOWLEDGE_PG_DSN" not in env or env["PNEUMA_KNOWLEDGE_PG_DSN"]
    settings = Settings(pg_dsn="postgresql://u:p@localhost:52180/x")
    env = harness_env(
        CODEX,
        config_home="/tmp/home",
        settings=settings,
        extra={"PNEUMA_KNOWLEDGE_PG_DSN": "postgresql://u:p@localhost:1/override"},
    )
    assert env["PNEUMA_KNOWLEDGE_PG_DSN"].endswith("/override")


async def test_the_round_carries_the_settings_onto_the_launch_request():
    """One hop, asserted because it is the hop that was missing: the worker's settings reach
    the child through `LaunchRequest`, not through whatever the worker's own environment
    happened to hold."""
    from pneuma_knowledge_service.coding_agent.launcher import LaunchRequest, _child_env
    from pneuma_knowledge_service.settings import Settings

    settings = Settings(pg_dsn="postgresql://u:p@localhost:52180/pneuma_knowledge")
    request = LaunchRequest(
        manifest=CODEX,
        system_text="s",
        task_text="t",
        project_dir="/project",
        config_home="/tmp/home",
        timeout_s=1.0,
        settings=settings,
    )
    assert _child_env(request)["PNEUMA_KNOWLEDGE_PG_DSN"] == settings.pg_dsn


def test_the_worker_hands_its_own_settings_to_the_round_runner():
    """The worker is the only place that HAS the resolved settings, so it is the place that
    must pass them — asserted on the source, because building a worker context needs a stack."""
    import inspect

    from pneuma_knowledge_service.workers import compile_worker

    source = inspect.getsource(compile_worker.process_agent_job)
    assert "settings=ctx.settings" in source


def test_the_round_runner_passes_them_through():
    import inspect

    from pneuma_knowledge_service.coding_agent.round_runner import AgentRoundRunner

    assert "settings" in AgentRoundRunner.__dataclass_fields__
    assert "settings=self.settings" in inspect.getsource(AgentRoundRunner._launch)
