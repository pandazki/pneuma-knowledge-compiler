"""Synthetic provider fixtures: no transcript content from the machine is test data."""

import asyncio
from dataclasses import replace
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from pkc_personal.home import asset_path
from pneuma_knowledge_service.engine.contract import load_engine_contract

SCRIPT = asset_path("skill/scripts/agent_sessions.py")
_spec = importlib.util.spec_from_file_location("personal_agent_sessions", SCRIPT)
sessions = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sessions
_spec.loader.exec_module(sessions)

OWNER_TEXTS = [
    "  I want momo to keep working offline. Mei LIN needs to read project notes without a connection.\n",
    "Choose a local store for the first version. A remote service is an alternative, but it would break that use.",
    "Keep the original decision date on the evolution page. The offline guarantee is a principle I want to preserve.",
]
AGENT_TEXT = "I implemented the local store. The synthetic example is at https://example.com/momo.\n"
OMITTED = "SYNTHETIC_TOOL_BODY_MUST_NOT_ENTER_THE_PAYLOAD"


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def claude_row(kind, content, second, **extra):
    return {"type": kind, "sessionId": "momo-claude", "uuid": f"{kind}-{second}",
            "timestamp": f"2026-09-01T10:00:{second:02}+08:00",
            "message": {"role": kind, "content": content}, **extra}


def claude_rows(project):
    return [
        {"type": "file-history-snapshot", "snapshot": {"text": OMITTED}},
        claude_row("user", OMITTED, 0, isSidechain=True),
        claude_row("user", OWNER_TEXTS[0], 1, cwd=str(project)),
        claude_row("assistant", [
            {"type": "text", "text": AGENT_TEXT},
            {"type": "thinking", "thinking": OMITTED},
            {"type": "tool_use", "id": "call-1", "name": "Write", "input": {
                "file_path": "src/" + "x" * 240 + ".py", "content": OMITTED}},
            {"type": "tool_use", "id": "call-2", "name": "Bash", "input": {
                "command": f"python -c '{OMITTED}'", "description": OMITTED}},
        ], 5),
        claude_row("user", [{"type": "tool_result", "content": OMITTED},
                            {"type": "text", "text": OWNER_TEXTS[1]}], 3),
        claude_row("user", [{"type": "tool_result", "content": [{"type": "text", "text": OMITTED}]}], 6),
        claude_row("user", OMITTED, 7, isCompactSummary=True),
        claude_row("user", OMITTED, 8, isMeta=True),
        claude_row("user", OWNER_TEXTS[2], 9),
        {"type": "permission-mode", "text": OMITTED},
        {"type": "mode", "text": OMITTED},
        {"type": "attachment", "attachment": {"text": OMITTED}},
    ]


def codex_row(kind, payload, second):
    return {"type": kind, "timestamp": f"2026-09-01T02:00:{second:02}+00:00", "payload": payload}


def codex_message(role, text, second, **extra):
    return codex_row("response_item", {"type": "message", "role": role,
        "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}], **extra}, second)


def codex_rows(project):
    return [
        codex_row("session_meta", {"id": "momo-codex", "cwd": str(project), "source": "cli",
                                  "base_instructions": OMITTED}, 0),
        codex_message("developer", OMITTED, 0),
        codex_message("user", "# AGENTS.md instructions for momo\n" + OMITTED, 0),
        codex_message("user", "<environment_context>" + OMITTED + "</environment_context>", 0),
        codex_message("user", OWNER_TEXTS[0], 1),
        codex_row("event_msg", {"type": "user_message", "message": OWNER_TEXTS[0]}, 1),
        codex_row("turn_context", {"model": "synthetic-model", "cwd": str(project), "summary": OMITTED}, 2),
        codex_message("assistant", AGENT_TEXT, 5),
        codex_row("event_msg", {"type": "agent_message", "message": AGENT_TEXT}, 5),
        codex_message("user", OWNER_TEXTS[1], 3),
        codex_row("response_item", {"type": "function_call", "call_id": "call-1", "name": "exec_command",
                  "arguments": json.dumps({"cmd": f"python -c '{OMITTED}'"})}, 6),
        codex_row("response_item", {"type": "function_call_output", "call_id": "call-1", "output": OMITTED}, 7),
        codex_row("response_item", {"type": "custom_tool_call", "name": "apply_patch", "input": OMITTED}, 8),
        codex_row("response_item", {"type": "custom_tool_call_output", "output": OMITTED}, 8),
        codex_row("response_item", {"type": "reasoning", "summary": [{"text": OMITTED}]}, 8),
        codex_row("response_item", {"type": "agent_message", "author": "momo-subagent",
                  "content": [{"type": "input_text", "text": OMITTED}]}, 8),
        codex_message("user", OWNER_TEXTS[2], 9),
        codex_row("event_msg", {"type": "task_complete", "last_agent_message": OMITTED}, 10),
    ]


@pytest.fixture
def provider_files(tmp_path):
    project = tmp_path / "momo"
    project.mkdir()
    claude_root = tmp_path / "claude-projects"
    codex_root = tmp_path / "codex-sessions"
    claude_file = write_jsonl(claude_root / str(project).replace("/", "-") / "momo.jsonl", claude_rows(project))
    codex_file = write_jsonl(codex_root / "2026/09/01/rollout-momo.jsonl", codex_rows(project))
    return SimpleNamespace(project=project, claude_root=claude_root, codex_root=codex_root,
                           claude_file=claude_file, codex_file=codex_file)


def common_args(files):
    return ["--project", str(files.project), "--claude-root", str(files.claude_root),
            "--codex-root", str(files.codex_root)]


def read_provider(files, provider):
    return (sessions.read_claude(files.claude_file, files.project) if provider == "claude-code"
            else sessions.read_codex(files.codex_file, files.project))


def assert_wire_shape(payload):
    """The agreed interface remains testable while the library task is in flight."""
    assert payload["schema"] == "pneuma.source.agent-session/v1"
    assert payload["owner_id"].strip() and payload["session_id"].strip()
    assert set(payload) <= {"schema", "provider", "session_id", "owner_id", "owner_name", "agent", "project",
                            "started_at", "ended_at", "turns", "metadata"}
    # The agent's turns are labelled with this name in L0: the harness's own name, not its id.
    assert payload["agent"]["name"] == {"codex": "Codex", "claude-code": "Claude Code"}[payload["provider"]]
    assert all(set(turn) == {"turn_id", "role", "kind", "at", "text"} for turn in payload["turns"])
    assert len({turn["turn_id"] for turn in payload["turns"]}) == len(payload["turns"])
    assert any(turn["role"] == "owner" and turn["text"].strip() for turn in payload["turns"])
    times = [datetime.fromisoformat(turn["at"]) for turn in payload["turns"]]
    assert all(at.utcoffset() is not None for at in times)
    assert times == sorted(times)
    assert datetime.fromisoformat(payload["started_at"]) <= times[0]
    assert datetime.fromisoformat(payload["ended_at"]) >= times[-1]
    for turn in payload["turns"]:
        assert turn["text"].strip()
        assert (turn["role"], turn["kind"]) in {("owner", "say"), ("agent", "narrative"), ("agent", "action")}
        if turn["kind"] == "action":
            assert len(turn["text"]) <= 200
            assert len(turn["text"].splitlines()) == 1


@pytest.mark.parametrize("provider", ["claude-code", "codex"])
def test_readers_preserve_speakers_verbatim_drop_tools_and_order_times(provider_files, provider):
    session = read_provider(provider_files, provider)
    assert not session.is_subagent
    assert [turn["text"] for turn in session.turns if turn["role"] == "owner"] == OWNER_TEXTS
    assert [turn["text"] for turn in session.turns if turn["kind"] == "narrative"] == [AGENT_TEXT]
    verdict = sessions.triage(session)
    assert verdict["verdict"] == "compile"
    assert verdict["owner_turns"] == 3
    payload = session.payload("lib-notes", verdict)
    assert_wire_shape(payload)
    assert OMITTED not in json.dumps(payload)
    assert payload["project"] == {"path": str(provider_files.project), "name": "momo"}
    assert session.timestamp_repairs > 0
    actions = [turn["text"] for turn in session.turns if turn["kind"] == "action"]
    if provider == "claude-code":
        assert len(actions[0]) == 200
        assert actions[0].startswith("Write: src/")
        assert actions[1] == "Bash: python"
    else:
        assert actions == ["exec_command: python", "apply_patch"]
        assert session.model == "synthetic-model"


@pytest.mark.parametrize("arguments, expected", [
    ({"path": "src/\nmomo.py", "content": OMITTED}, "Edit: src/ momo.py"),
    ({"command": f"TOKEN={OMITTED} python main.py"}, "Edit"),
    ({"command": f"echo '{OMITTED}'"}, "Edit: echo"),
    ({"command": "'unclosed"}, "Edit"),
    (OMITTED, "Edit"),
    ({"input": OMITTED, "message": OMITTED}, "Edit"),
])
def test_stubs_never_copy_arbitrary_arguments(arguments, expected):
    assert sessions.action_stub("Edit", arguments) == expected


def test_multiblock_owner_message_counts_once_and_duplicate_uuid_is_ignored(provider_files):
    row = claude_row("user", [{"type": "text", "text": " first "}, {"type": "text", "text": "second\n"},
                               {"type": "tool_result", "content": OMITTED}], 1)
    write_jsonl(provider_files.claude_file, [row, row])
    session = read_provider(provider_files, "claude-code")
    assert [turn["text"] for turn in session.turns] == [" first \nsecond\n"]
    assert sessions.triage(session, min_owner_chars=0)["owner_turns"] == 1


def test_codex_old_event_only_rollout_and_repeated_real_messages(provider_files):
    rows = [codex_rows(provider_files.project)[0]] + [
        codex_row("event_msg", {"type": "user_message", "message": text}, index)
        for index, text in enumerate(OWNER_TEXTS, 1)
    ] + [codex_row("event_msg", {"type": "agent_message", "message": AGENT_TEXT}, 4)]
    write_jsonl(provider_files.codex_file, rows)
    assert sessions.triage(read_provider(provider_files, "codex"))["verdict"] == "compile"
    # Equal words in separate actual turns are not a duplicate event mirror.
    rows = [rows[0], codex_message("user", "continue", 1), codex_message("user", "continue", 2)]
    write_jsonl(provider_files.codex_file, rows)
    assert len(read_provider(provider_files, "codex").turns) == 2


@pytest.mark.parametrize("provider", ["claude-code", "codex"])
def test_subagent_prompts_never_become_owner_speech(provider_files, provider):
    if provider == "claude-code":
        write_jsonl(provider_files.claude_file, [claude_row("user", text, i, isSidechain=True)
                                               for i, text in enumerate(OWNER_TEXTS, 1)])
    else:
        rows = codex_rows(provider_files.project)
        rows[0]["payload"]["source"] = {"subagent": {"spawn": {"parent_thread_id": "momo-root"}}}
        write_jsonl(provider_files.codex_file, rows)
    session = read_provider(provider_files, provider)
    assert session.is_subagent and not session.turns
    assert sessions.triage(session)["verdict"] == "skip"
    with pytest.raises(ValueError, match="owner turn"):
        session.payload("lib-notes", sessions.triage(session))


def triage_session(texts, project=Path("/synthetic/momo"), **kwargs):
    session = sessions.Session("codex", "synthetic", Path("synthetic.jsonl"), project, **kwargs)
    session.last_at = sessions.timestamp("2026-09-01T10:00:00+08:00")
    for text in texts:
        session.add("owner", "say", text)
    return session.finish()


@pytest.mark.parametrize("texts, options, verdict, reason", [
    (OWNER_TEXTS, {}, "compile", None),
    (OWNER_TEXTS[:2], {}, "index", "too_few_owner_turns"),
    (["a" * 67, "b" * 66, "c" * 66], {}, "skip", "owner_text_below_threshold"),
    (["a" * 67, "b" * 67, "c" * 66], {}, "compile", None),
    (["OK!", "/compact", "yes"], {"min_owner_chars": 0}, "index", "commands_or_acknowledgements_only"),
    (["/review " + "x" * 200, "/compact", "okay"], {}, "index", "commands_or_acknowledgements_only"),
    (["<command-name>/review</command-name>", "OK", "yes"], {"min_owner_chars": 0}, "index", "commands_or_acknowledgements_only"),
    (["thank you"] * 3, {"min_owner_chars": 0, "ack_max_words": 2}, "index", "commands_or_acknowledgements_only"),
    (OWNER_TEXTS, {"min_owner_turns": 4}, "index", "too_few_owner_turns"),
    (OWNER_TEXTS, {"purpose": "research"}, "index", "research_session"),
    (OWNER_TEXTS, {"purpose": "chat"}, "index", "chat_session"),
    ([], {"min_owner_chars": 0}, "skip", "no_owner_turns"),
])
def test_triage_thresholds_and_treatments(texts, options, verdict, reason):
    result = sessions.triage(triage_session(texts), **options)
    assert result["verdict"] == verdict
    assert result["canonical_treatment"] == ("full" if verdict == "compile" else "none")
    if reason:
        assert reason in result["reasons"]


@pytest.mark.parametrize("stub, steward", [
    ("Bash: pkc", True),
    ("Bash: pkchome", True),
    ("Bash: /Users/x/.pkc/libraries/notes/.agents/skills/pkc-steward/scripts/pkc", True),
    ("Bash: pkcompose", False),
    ("Bash: python", False),
    ("Write", False),
])
def test_the_stewards_own_commands_make_a_session_the_librarys_maintenance(stub, steward):
    session = triage_session(OWNER_TEXTS)
    session.turns.append({"turn_id": "t9", "role": "agent", "kind": "action",
                          "at": session.turns[-1]["at"], "text": stub})
    assert sessions.steward_work(session) is steward
    result = sessions.triage(session, steward=sessions.steward_work(session))
    assert result["verdict"] == ("skip" if steward else "compile")
    assert ("steward_session" in result["reasons"]) is steward
    assert result["canonical_treatment"] == ("none" if steward else "full")


def test_a_session_inside_the_home_is_the_stewards_own_work(tmp_path):
    library = tmp_path / "home/libraries/notes"
    roots = sessions.steward_roots({"path": str(library), "engine_dir": str(library / "engine")})
    assert sessions.steward_work(triage_session(OWNER_TEXTS, project=library / "engine"), roots)
    assert sessions.steward_work(triage_session(OWNER_TEXTS, project=tmp_path / "home/run"), roots)
    assert not sessions.steward_work(triage_session(OWNER_TEXTS, project=tmp_path / "momo"), roots)
    # Components, never characters: a sibling whose name merely starts the same is not inside.
    assert not sessions.steward_work(triage_session(OWNER_TEXTS, project=tmp_path / "home-of-momo"), roots)


def test_project_membership_and_subagent_are_required_for_compile():
    assert sessions.triage(triage_session(OWNER_TEXTS, project=None))["verdict"] == "index"
    assert sessions.triage(triage_session(OWNER_TEXTS, is_subagent=True))["verdict"] == "index"


def test_claude_encoded_directory_collision_is_never_imported(provider_files, tmp_path):
    rows = claude_rows(provider_files.project)
    rows[2]["cwd"] = str(tmp_path / "another-project")
    write_jsonl(provider_files.claude_file, rows)
    session = read_provider(provider_files, "claude-code")
    result = sessions.triage(session)
    assert result["verdict"] == "skip" and "project_directory_conflict" in result["reasons"]
    output = tmp_path / "exported"
    assert sessions.main(["export", *common_args(provider_files), "--out", str(output),
                          "--session-id", "momo-claude"]) == 0
    assert not output.exists()


def test_list_and_export_are_project_scoped_and_since_is_inclusive(provider_files, tmp_path, capsys):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    write_jsonl(provider_files.codex_root / "2026/09/01/rollout-unrelated.jsonl", codex_rows(unrelated))
    assert sessions.main(["list", *common_args(provider_files)]) == 0
    listed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(listed) == 2 and {row["verdict"] for row in listed} == {"compile"}
    assert sessions.main(["list", *common_args(provider_files), "--since", "2026-09-01T02:00:09Z"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert sessions.main(["list", *common_args(provider_files), "--since", "2026-09-01T02:00:10Z"]) == 0
    assert capsys.readouterr().out == ""
    output = tmp_path / "exported"
    assert sessions.main(["export", *common_args(provider_files), "--out", str(output), "--owner-id", "lib-notes"]) == 0
    assert len(list(output.glob("*.json"))) == 2
    for path in output.glob("*.json"):
        payload = json.loads(path.read_text())
        assert_wire_shape(payload)
        assert OMITTED not in path.read_text()
    assert not list(tmp_path.rglob("ingested-sessions.json"))


def test_export_skips_short_sessions_and_supports_individual_research_selection(provider_files, tmp_path, capsys):
    write_jsonl(provider_files.claude_file, [claude_row("user", "thanks", 1)])
    output = tmp_path / "exported"
    assert sessions.main(["export", *common_args(provider_files), "--out", str(output),
                          "--session-id", "momo-codex", "--purpose", "research"]) == 0
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(reports) == 1 and reports[0]["verdict"] == "index"
    assert len(list(output.glob("*.json"))) == 1
    assert sessions.main(["export", *common_args(provider_files), "--out", str(tmp_path / "short"),
                          "--session-id", "momo-claude"]) == 0
    assert not (tmp_path / "short").exists()


@pytest.mark.parametrize("extra", [
    ["--min-owner-turns", "2"], ["--min-owner-chars", "-1"], ["--ack-max-words", "0"],
    ["--since", "2026-09-01T10:00:00"],
])
def test_bad_options_refused_before_export(provider_files, tmp_path, extra):
    output = tmp_path / "exported"
    assert sessions.main(["export", *common_args(provider_files), "--out", str(output), *extra]) == 2
    assert not output.exists()


def test_bad_json_or_clock_is_reported_without_echoing_material(provider_files, capsys):
    provider_files.claude_file.write_text('{"text": "' + OMITTED)
    assert sessions.main(["list", *common_args(provider_files)]) == 1
    output = capsys.readouterr().out
    assert "invalid JSON at line 1" in output and OMITTED not in output
    write_jsonl(provider_files.claude_file, [claude_row("user", OWNER_TEXTS[0], 1, timestamp="2026-09-01T10:00:01")])
    with pytest.raises(ValueError, match="timezone"):
        read_provider(provider_files, "claude-code")


def test_missing_turn_clock_inherits_recorded_clock_only(provider_files):
    rows = claude_rows(provider_files.project)
    rows[-4].pop("timestamp")
    write_jsonl(provider_files.claude_file, rows)
    assert_wire_shape(read_provider(provider_files, "claude-code").payload("lib-notes", {}))
    write_jsonl(provider_files.claude_file, [{"type": "user", "message": {"content": OWNER_TEXTS[0]}}])
    with pytest.raises(ValueError, match="no recorded timestamp"):
        read_provider(provider_files, "claude-code")


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    library_path = tmp_path / "home/libraries/notes"
    library_path.mkdir(parents=True)
    calls = []
    state = {"returncode": 0, "name": "notes", "path": str(library_path), "tenant": "lib-notes", "owner_name": "Momo"}

    def run(command, **kwargs):
        calls.append(command)
        if command[-2:] == ["library", "show"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(state))
        assert command[:7] == ["pkchome", "exec", "--library", state["name"], "--", "pkc", "ingest"]
        assert command[7:9] == ["--contract", "agent-session/v1"]
        payload = json.loads(Path(command[command.index("--file") + 1]).read_text())
        assert_wire_shape(payload)
        assert payload["owner_id"] == state["tenant"]
        # The Owner's turns are labelled with the profile name `library show` handed over.
        assert payload.get("owner_name") == state.get("owner_name")
        if payload["metadata"]["triage"]["verdict"] == "index":
            assert command[-2:] == ["--intake", "searchable"]
        else:
            assert "--intake" not in command
        source_id = "source-" + sessions.digest(sessions.encoded_json(payload).encode())[:16]
        return SimpleNamespace(returncode=state["returncode"], stdout=json.dumps({
            "sources": [{"source_id": source_id, "deduplicated": False}], "compile_jobs": ["job-1"]}), stderr=OMITTED)

    monkeypatch.setattr(sessions.subprocess, "run", run)
    return SimpleNamespace(path=library_path, calls=calls, state=state)


def test_ingestion_uses_the_shared_cursor_and_holds_small_increments(provider_files, launcher):
    args = ["ingest", *common_args(provider_files), "--library", "notes"]
    assert sessions.main(args) == 0
    record = launcher.path / "sync-state.json"
    saved = json.loads(record.read_text())
    assert len(saved["sessions"]) == 2
    assert sessions.main(args) == 0
    assert len([call for call in launcher.calls if "ingest" in call]) == 2
    assert json.loads(record.read_text())["sessions"] == saved["sessions"]
    with provider_files.claude_file.open("a") as stream:
        stream.write(json.dumps(claude_row("user", "The first version is accepted as of today.", 12)) + "\n")
    assert sessions.main(args) == 0
    assert len([call for call in launcher.calls if "ingest" in call]) == 2
    entry = next(e for e in json.loads(record.read_text())["sessions"].values() if e["provider"] == "claude-code")
    assert entry["held"]["owner_turns"] == 1
    assert OMITTED not in record.read_text() and OWNER_TEXTS[0] not in record.read_text()


def test_index_only_uses_searchable_and_dry_run_writes_no_record(provider_files, launcher):
    args = ["ingest", *common_args(provider_files), "--purpose", "research"]
    assert sessions.main([*args, "--dry-run"]) == 0
    assert not list(launcher.path.iterdir())
    assert not any("ingest" in call for call in launcher.calls)
    assert sessions.main(args) == 0
    for call in launcher.calls:
        if "ingest" in call:
            assert call[-2:] == ["--intake", "searchable"]


def test_failures_keep_exact_pending_payloads_for_retry(provider_files, launcher, capsys):
    launcher.state["returncode"] = 2
    args = ["ingest", *common_args(provider_files)]
    assert sessions.main(args) == 1
    assert all("pending" in entry for entry in json.loads((launcher.path / "sync-state.json").read_text())["sessions"].values())
    assert OMITTED not in capsys.readouterr().out
    launcher.state["returncode"] = 0
    assert sessions.main(args) == 0
    assert len(json.loads((launcher.path / "sync-state.json").read_text())["sessions"]) == 2


def test_ingestion_state_is_per_library(provider_files, launcher, tmp_path):
    args = ["ingest", *common_args(provider_files)]
    assert sessions.main(args) == 0
    other = tmp_path / "home/libraries/second"
    other.mkdir()
    launcher.state.update(name="second", path=str(other), tenant="lib-second")
    assert sessions.main(args) == 0
    assert len([call for call in launcher.calls if "ingest" in call]) == 4
    assert (other / "sync-state.json").exists()


def test_corrupt_record_and_concurrent_import_refuse_before_ingest(provider_files, launcher):
    args = ["ingest", *common_args(provider_files)]
    record = launcher.path / "ingested-sessions.json"
    record.write_text("invalid")
    assert sessions.main(args) == 2
    record.unlink()
    with sessions.sync_lock(launcher.path.parents[1] / "run/notes.sync.lock"):
        assert sessions.main(args) == 2
    assert not any("ingest" in call for call in launcher.calls)


def test_script_runs_without_site_packages(provider_files):
    result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), "list", *common_args(provider_files)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 2


@pytest.mark.parametrize("language", ["en", "zh"])
def test_projects_contract_loads_and_owner_view_creation_template_is_flagged(tmp_path, language):
    engine = tmp_path / "engine"
    (engine / "compile").mkdir(parents=True)
    text = asset_path(f"contracts/personal-projects.{language}.md").read_text()
    (engine / "compile/contract.md").write_text(text)
    contract = load_engine_contract(engine)
    assert contract is not None and contract.skill_id == "personal-projects"
    assert contract.owner_voice_templates == ["owner/views/{slug}.md"]
    assert contract.path_templates == [
        "projects/{slug}/overview.md", "projects/{slug}/evolution.md", "projects/{slug}/features/{slug}.md",
        "projects/{slug}/decisions/{slug}.md", "owner/views/{slug}.md", "memory/people/{slug}.md", "memory/topics/{slug}.md",
    ]
    template = contract.instructions.split("```yaml\n", 1)[1].split("```", 1)[0]
    assert yaml.safe_load(template)["owner_voice"] is True
    assert "definition" in contract.instructions and "summary" in contract.instructions


@pytest.mark.parametrize("provider", ["claude-code", "codex"])
def test_converter_output_through_library_ingest_when_contract_is_available(provider_files, provider, monkeypatch):
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.cli.ingest import CONTRACTS, cmd_ingest
    from pneuma_knowledge_service import ingest_sources

    if "agent-session/v1" not in CONTRACTS:
        pytest.skip("pending: library task has not exposed pkc ingest --contract agent-session/v1")
    session = read_provider(provider_files, provider)
    payload = session.payload("lib-notes", sessions.triage(session))
    captured = []

    async def ingest(ctx, user_id, parsed, *, intake_archetype):
        captured.append((user_id, parsed, intake_archetype))
        return SimpleNamespace(contract_schema=SCHEMA, sources=[], compile_jobs=[])

    SCHEMA = "pneuma.source.agent-session/v1"
    monkeypatch.setattr(ingest_sources, "ingest_source_contract", ingest)
    out, err = io.StringIO(), io.StringIO()
    result = asyncio.run(cmd_ingest(object(), UserId("lib-notes"), contract_name="agent-session/v1",
                                    payload_text=json.dumps(payload), as_json=True, out=out, err=err))
    assert result == 0, err.getvalue()
    assert len(captured) == 1
    user, parsed, intake = captured[0]
    assert str(user) == "lib-notes" and intake is None
    assert [turn.text for turn in parsed.turns if turn.role == "owner"] == OWNER_TEXTS
    assert json.loads(out.getvalue())["contract_schema"] == SCHEMA



# ───────────────────────────────────────── material too large for one round, cut at turns


def exchanges_session(sizes, *, lead=0):
    """Owner turn, agent turn of each size; `lead` agent characters ahead of the first Owner."""
    session = sessions.Session("codex", "synthetic", Path("synthetic.jsonl"), Path("/synthetic/momo"))
    session.last_at = sessions.timestamp("2026-09-01T10:00:00+08:00")
    if lead:
        session.add("agent", "narrative", "l" * lead)
    for index, size in enumerate(sizes):
        session.add("owner", "say", OWNER_TEXTS[index % 3])
        session.add("agent", "narrative", "x" * size)
    return session.finish()


def test_a_session_under_the_bound_is_its_own_single_part_untouched():
    session = exchanges_session([100, 100])
    assert sessions.split_parts(session, 400_000) == [session]


def test_parts_are_cut_at_owner_turns_only_and_cover_every_turn_once():
    session = exchanges_session([3_000, 3_000, 3_000, 3_000], lead=50)
    parts = sessions.split_parts(session, 7_000)
    assert [turn for part in parts for turn in part.turns] == session.turns
    assert all(part.turns[0]["role"] == "owner" for part in parts[1:])
    # Agent turns ahead of the first Owner turn ride with it: no part lacks an Owner turn.
    assert all(any(t["role"] == "owner" for t in part.turns) for part in parts)
    assert all(sessions.turn_chars(part.turns) <= 7_000 for part in parts)
    assert len(parts) == 2


def test_one_exchange_past_the_bound_is_one_whole_part():
    parts = sessions.split_parts(exchanges_session([500, 5_000, 500]), 2_000)
    assert [len(part.turns) for part in parts] == [2, 2, 2]
    assert parts[1].turns[1]["text"] == "x" * 5_000


def test_a_bound_below_the_floor_is_refused_rather_than_applied():
    with pytest.raises(ValueError, match="max-part-chars"):
        sessions.split_parts(exchanges_session([100]), 10)


def test_a_split_part_inherits_the_whole_verdict_and_a_part_without_owner_words_is_index_only():
    """The inheritance is pure: counts describe the part, the verdict comes from the increment.

    `split_parts` never yields a part without an Owner turn, and the contract refuses such a
    source, so this exception is a mechanical guard rather than a path sync walks today."""
    whole = exchanges_session([3_000, 3_000, 3_000])
    verdict = sessions.triage(whole)
    assert verdict["verdict"] == "compile"
    siblings = sessions.split_parts(whole, 4_000)
    # Judged alone, a one-Owner-turn part would not even be indexed: its Owner words fall
    # under `min_owner_chars`.
    assert len(siblings) == 3 and sessions.triage(siblings[0])["verdict"] == "skip"
    agent_only = replace(siblings[1], turns=[t for t in siblings[1].turns if t["role"] == "agent"])
    records = [sessions.part_triage(part, verdict) for part in (siblings[0], agent_only, siblings[2])]
    assert [r["verdict"] for r in records] == ["compile", "index", "compile"]
    assert [r["canonical_treatment"] for r in records] == ["full", "none", "full"]
    assert records[1]["reasons"] == ["no_owner_turns_in_part"]
    assert "no_owner_turns_in_part" not in records[0]["reasons"]
    assert [r["owner_turns"] for r in records] == [1, 0, 1]
    assert records[0]["owner_chars"] == len(OWNER_TEXTS[0]) and records[1]["owner_chars"] == 0
    assert all(r["verdict_from"] == "increment" for r in records)
    assert all(r["increment"] == {"owner_turns": 3, "owner_chars": verdict["owner_chars"]} for r in records)
    # A verdict below compile is never raised by inheritance.
    index = {**verdict, "verdict": "index", "canonical_treatment": "none", "reasons": ["research_session"]}
    assert sessions.part_triage(siblings[0], index)["verdict"] == "index"
    assert sessions.part_triage(agent_only, index)["reasons"] == ["research_session", "no_owner_turns_in_part"]


def test_list_and_export_judge_the_whole_session_however_large(provider_files, tmp_path, capsys):
    rows = []
    for index in range(3):
        rows.append(claude_row("user", OWNER_TEXTS[index], 2 * index + 1, cwd=str(provider_files.project)))
        rows.append(claude_row("assistant", [{"type": "text", "text": "x" * 330_000}], 2 * index + 2))
    write_jsonl(provider_files.claude_file, rows)
    assert sessions.main(["list", *common_args(provider_files), "--session-id", "momo-claude"]) == 0
    listed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(listed) == 1 and listed[0]["verdict"] == "compile" and listed[0]["owner_turns"] == 3
    assert "verdict_from" not in listed[0]
    output = tmp_path / "exported"
    assert sessions.main(["export", *common_args(provider_files), "--out", str(output),
                          "--session-id", "momo-claude", "--owner-id", "lib-notes"]) == 0
    [path] = output.glob("*.json")
    payload = json.loads(path.read_text())
    assert len(payload["turns"]) == 6 and "verdict_from" not in payload["metadata"]["triage"]
