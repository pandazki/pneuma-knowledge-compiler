import json
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from pkc_personal import cli, engine, infra, status
from pkc_personal.home import Home, atomic_write, read_yaml, yaml_text
from pkc_personal.library import Library


def test_compose_ports_mounts_and_up_idempotence(home, make_library, monkeypatch):
    library = make_library()
    operations = []
    running = False
    def compose(_home, *args):
        nonlocal running
        if args[0] == "ps":
            rows = [{"Service": name, "State": "running", "Health": "healthy"}
                    for name in ("postgres", "qdrant", "meilisearch", "rustfs")] if running else []
            return SimpleNamespace(stdout=json.dumps(rows))
        operations.append(args)
        running = args[0] == "up"
        return SimpleNamespace(stdout="")
    monkeypatch.setattr(infra, "compose", compose)
    monkeypatch.setattr(engine, "start", lambda *_: False)
    monkeypatch.setattr(engine, "stop", lambda *_: operations.append(("engine-stop",)))
    infra.up(home)
    first_stamp = Library.load(home, "notes").state.steps.infra
    assert first_stamp
    compose_path = home.path / "infra" / "docker-compose.yml"
    old_mtime = compose_path.stat().st_mtime_ns
    document = read_yaml(compose_path)
    assert set(document["services"]) == {"postgres", "qdrant", "meilisearch", "rustfs"}
    for service, key in (("postgres", "postgres"), ("qdrant", "qdrant"), ("meilisearch", "meili"), ("rustfs", "rustfs")):
        settings = document["services"][service]
        assert str(getattr(home.config.infra.ports, key)) in settings["ports"][0]
        assert settings["volumes"][0].startswith(home.config.infra.data_dir)
    infra.up(home)
    assert operations == [("up", "-d", "--wait")]
    assert compose_path.stat().st_mtime_ns == old_mtime
    assert Library.load(home, "notes").state.steps.infra == first_stamp
    config = home.config
    config.infra.ports.meili = 31000
    home.save_config(config)
    infra.up(home)
    assert operations[-1] == ("up", "-d", "--wait")
    infra.down(home)
    assert operations[-2:] == [("engine-stop",), ("down",)]
    assert (home.path / "data").is_dir()


def test_compose_invocation_is_project_scoped(home, monkeypatch):
    calls = []
    monkeypatch.setattr(infra.subprocess, "run", lambda *args, **kw: calls.append((args, kw)))
    infra.compose(home, "up", "-d", "--wait")
    args, kwargs = calls[0]
    assert args[0] == ["docker", "compose", "-f", str(home.path / "infra" / "docker-compose.yml"),
                       "-p", "pkc-personal", "up", "-d", "--wait"]
    assert kwargs["check"] is True


def test_engine_detached_same_python_and_pid_owned_stop(home, make_library, monkeypatch):
    library = make_library()
    monkeypatch.setattr(engine, "Settings", SimpleNamespace(model_fields={"worker_tenants": object()}))
    live = set()
    calls = []
    def popen(command, **kwargs):
        calls.append((command, kwargs))
        live.add(654321)
        return SimpleNamespace(pid=654321, poll=lambda: None)
    monkeypatch.setattr(engine.subprocess, "Popen", popen)
    monkeypatch.setattr(engine, "pid_alive", lambda pid: pid in live)
    monkeypatch.setattr(engine.os, "getpgid", lambda pid: pid)
    signals = []
    def killpg(pid, sig):
        signals.append((pid, sig))
        live.discard(pid)
    monkeypatch.setattr(engine.os, "killpg", killpg)
    assert engine.start(home, library) is True
    assert engine.start(home, library) is False
    command, options = calls[0]
    # The edition's entry, not the library's: it adds the home's routes to the same app.
    assert command[:5] == [sys.executable, "-m", "pkc_personal.engine_app", "--library", "notes"]
    assert command[5:7] == ["--port", str(library.state.engine.port)]
    assert options["start_new_session"] is True
    assert options["env"]["PNEUMA_KNOWLEDGE_WORKER_TENANTS"] == "lib-notes"
    assert options["cwd"] == library.path
    assert engine.status(home, library)["up"] is True
    assert engine.stop(home, library) is True
    assert signals == [(654321, signal.SIGTERM)]
    assert not engine.pid_path(home, library).exists()
    assert engine.stop(home, library) is False


def test_a_posture_change_restarts_the_running_engine(home, make_library, monkeypatch, capsys):
    library = make_library()
    monkeypatch.setattr(engine, "Settings", SimpleNamespace(model_fields={"worker_tenants": object()}))
    live, started = set(), []
    pids = iter([1001, 1002])
    def popen(command, **kwargs):
        pid = next(pids)
        started.append(kwargs["env"]["PNEUMA_KNOWLEDGE_AGENT_UNATTENDED"])
        live.add(pid)
        return SimpleNamespace(pid=pid, poll=lambda: None)
    monkeypatch.setattr(engine.subprocess, "Popen", popen)
    monkeypatch.setattr(engine, "pid_alive", lambda pid: pid in live)
    monkeypatch.setattr(engine.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(engine.os, "killpg", lambda pid, _sig: live.discard(pid))
    assert engine.start(home, library) is True
    assert cli.main(["config", "set", "unattended", "off", "--library", "notes"]) == 0
    output = capsys.readouterr().out
    assert "restarted" in output and "attended" in output and "unattended" not in output
    # The worker reads the posture at start, so the choice is only obeyed by a new process.
    assert started == ["true", "false"]
    assert engine.status(home, library)["pid"] == 1002


def test_missing_worker_filter_is_a_startup_refusal(home, make_library, monkeypatch):
    library = make_library()
    monkeypatch.setattr(engine, "Settings", SimpleNamespace(model_fields={}))
    monkeypatch.setattr(engine, "pid_alive", lambda _: False)
    with pytest.raises(RuntimeError, match="other libraries' jobs"):
        engine.start(home, library)
    assert not engine.pid_path(home, library).exists()


def test_status_document_shape_and_failed_probes(home, make_library, monkeypatch, capsys):
    library = make_library()
    atomic_write(engine.pid_path(home, library), "987654\n")
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    monkeypatch.setattr(infra, "tcp_port_open", lambda *_: pytest.fail("Docker down means unknown service probes"))
    monkeypatch.setattr(engine, "pid_alive", lambda _: False)
    monkeypatch.setattr(status, "queue_status", lambda _: None)
    assert cli.main(["status", "--json", "--library", "notes"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert set(document) == {"home", "docker", "services", "libraries"}
    assert all(row["up"] is None for row in document["services"].values())
    row = document["libraries"][0]
    assert set(row) == {"name", "tenant", "current", "engine", "unattended", "agent_model",
                        "reasoning_effort", "reasoning_effort_episodes",
                        "compile_call_timeout", "compile_call_timeout_default", "queue", "key",
                        "engine_dir", "canonical_head",
                        "skill_fresh", "steps", "last_used", "sync"}
    # The tenant travels with the name: it is what the console reads once it has switched to
    # a library by name, and a row without it names a library no request could reach.
    assert row["tenant"] == "lib-notes"
    assert row["engine"] == {"pid": 987654, "up": False, "port": library.state.engine.port, "uptime": None}
    assert row["queue"] is None and row["skill_fresh"] is None and row["canonical_head"] is None
    rendered = status.render_text(document)
    assert "Docker: down" in rendered
    # The console page is machine-wide, so it is reported beside Docker, not per library.
    assert document["home"]["console"] and "Console: " in rendered
    # The posture is carried per library and shown per library, recorded rather than probed.
    assert row["unattended"] is True and "Worker: unattended" in rendered
    # So are the round's model and effort: recorded, and empty means the harness's own.
    assert row["agent_model"] == "" and row["reasoning_effort"] == ""
    assert "Rounds: the harness default model at the harness default effort" in rendered
    assert row["reasoning_effort_episodes"] == "" and "(episodes" not in rendered
    # Episodes rounds at their own effort are named on the same line, only when stated.
    named = {**row, "agent_model": "gpt-5.6-luna", "reasoning_effort": "medium",
             "reasoning_effort_episodes": "low"}
    assert status.rounds_line(named) == "gpt-5.6-luna at medium (episodes low)"
    assert "  Rounds: gpt-5.6-luna at medium (episodes low)" in status.render_text(
        {**document, "libraries": [named]})


def test_queue_reads_one_bounded_page_of_succeeded_compiles(home, make_library, monkeypatch):
    library = make_library()
    calls = []
    def jobs(_library, *, timeout=1.0, **query):
        calls.append({**query, "timeout": timeout})
        state = query["status"]
        if state == "failed":
            return {"items": [{"kind": "evolve"}, {"kind": "evolve"}], "page": {"total": 2}}
        if state != "succeeded":
            return {"items": [], "page": {"total": {"queued": 4, "claimed": 1}[state]}}
        if "kind" not in query:
            return {"items": [], "page": {"total": 135}}
        return {"items": [{"completed_at": "2026-07-02T00:00:00Z"},
                          {"completed_at": "2026-07-03T00:00:00Z"},
                          {"completed_at": None}],
                "page": {"next_cursor": "next"}}
    monkeypatch.setattr(status, "_jobs", jobs)
    assert status.queue_status(library) == {
        "pending": 5, "failed": 2, "failed_by_kind": {"evolve": 2}, "succeeded": 135,
        "last_compile_at": "2026-07-03T00:00:00Z",
        # Nothing is holding this queue back, which is a reading and not an absence.
        "cooling": None,
    }
    # Five reads, no cursor: an offered next page is never followed, so a library with a
    # long succeeded history costs the same status call as a fresh one.
    assert len(calls) == 5
    assert not any("cursor" in call for call in calls)
    succeeded = calls[-1]
    assert succeeded["kind"] == "compile" and succeeded["limit"] == 20
    assert all(0 < call["timeout"] <= status.QUEUE_BUDGET_SECONDS for call in calls)


def test_a_queue_waiting_on_a_spent_subscription_says_so_on_the_worker_line(
    home, make_library, monkeypatch
):
    """A worker that is claiming nothing looks exactly like a worker that is broken.

    The engine reads it off the rows (a queued job's `not_before`), so it survives the worker
    restarting and is answerable by a process that never cooled anything. It rides the page
    `status` already asks for, so saying it costs no extra read — and it lands on the one line
    an Owner looks at before deciding whether something is wrong.
    """
    library = make_library()
    calls = []

    def jobs(_library, *, timeout=1.0, **query):
        calls.append(query)
        page = {"total": 3}
        if query["status"] == "queued":
            page |= {"cooling_until": "2026-09-15T01:23:00+00:00",
                     "cooling_reason": "codex usage limit"}
        return {"items": [], "page": page}

    monkeypatch.setattr(status, "_jobs", jobs)
    queue = status.queue_status(library)
    assert queue["cooling"] == {"until": "2026-09-15T01:23:00+00:00",
                                "reason": "codex usage limit"}
    assert len(calls) == 5, "the cooling window rides a page status already asks for"

    row = {"unattended": True, "queue": queue}
    assert status.worker_line(row) == (
        f"unattended — cooling until {status.local_time('2026-09-15T01:23:00+00:00')} "
        "(codex usage limit)"
    )
    # …and a library with nothing holding it back says exactly what it always said.
    assert status.worker_line({"unattended": True, "queue": None}) == "unattended"


def test_queue_stops_when_the_second_budget_is_spent(home, make_library, monkeypatch):
    library = make_library()
    calls = []
    clock = iter([0.0, 0.4, 0.8, 1.2, 1.6])
    monkeypatch.setattr(status.time, "monotonic", lambda: next(clock))
    def jobs(_library, *, timeout=1.0, **query):
        if timeout <= 0:
            raise TimeoutError("spent")
        calls.append(query)
        return {"items": [], "page": {"total": 0}}
    monkeypatch.setattr(status, "_jobs", jobs)
    assert status.queue_status(library) is None
    assert len(calls) == 2


def test_queue_is_not_probed_when_the_engine_pid_is_dead(home, make_library, monkeypatch, capsys):
    make_library()
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    monkeypatch.setattr(engine, "pid_alive", lambda _: False)
    monkeypatch.setattr(status, "_jobs", lambda *a, **k: pytest.fail("a dead engine is never asked"))
    assert cli.main(["status", "--json", "--library", "notes"]) == 0
    assert json.loads(capsys.readouterr().out)["libraries"][0]["queue"] is None


PROFILE_DONE = {"profile": {"display_name": "Wen", "provenance": {"display_name": "owner"}},
                "placeholder": False, "file": "/engine/persona/profile.yaml"}


def _name_the_owner(library):
    """Take the engine file out of the placeholder, so the record probe is worth running."""
    path = library.engine_dir / "persona" / "profile.yaml"
    atomic_write(path, path.read_text(encoding="utf-8").replace('"Owner"', '"Wen"'))


def _profile_run(monkeypatch, payload, *, code=0):
    """Stand in for `pkc profile show --json`; every other probe keeps its real subprocess."""
    calls = []
    real = status.subprocess.run
    def run(command, **kwargs):
        if command[1:3] != ["profile", "show"]:
            return real(command, **kwargs)
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=code, stdout=json.dumps(payload) if payload is not None else "")
    monkeypatch.setattr(status.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("payload,expected", [
    (PROFILE_DONE, True),
    # No provenance map at all — the older shape — is not an unconfirmed inference.
    ({"profile": {"display_name": "Wen"}, "placeholder": False}, True),
    ({"profile": {"display_name": "Wen", "provenance": {"display_name": "inferred",
                                                        "occupation": "owner"}},
      "placeholder": False}, None),
    ({"profile": {"display_name": "Someone"}, "placeholder": True}, None),
    ({"profile": None, "placeholder": True}, None),
])
def test_profile_step_is_derived_from_the_library_answer(home, make_library, monkeypatch, payload, expected):
    library = make_library()
    _name_the_owner(library)
    calls = _profile_run(monkeypatch, payload)
    assert status.profile_settled(home, library) is expected
    assert calls[0][0][1:] == ["profile", "show", "--json"]
    assert calls[0][1]["env"]["PNEUMA_KNOWLEDGE_TENANT"] == "lib-notes"
    assert calls[0][1]["timeout"] == 5


@pytest.mark.parametrize("code,payload", [(2, PROFILE_DONE), (0, None)])
def test_an_unanswerable_profile_probe_is_null(home, make_library, monkeypatch, code, payload):
    library = make_library()
    _name_the_owner(library)
    _profile_run(monkeypatch, payload, code=code)
    assert status.profile_settled(home, library) is None


def test_first_compile_is_the_oldest_compile_commit(home, make_library):
    library = make_library()
    repo = library.canonical_dir
    assert status.first_compile_at(library) is None            # no commits at all
    _commit(repo, "memory/a.md", "seed")
    assert status.first_compile_at(library) is None            # nothing named a compile
    _commit(repo, "memory/b.md", "compile 0198f0aa-1111-7000-8000-000000000001")
    first = status.first_compile_at(library)
    assert first and first.startswith("20") and "T" in first
    _commit(repo, "memory/c.md", "compile 0198f0aa-1111-7000-8000-000000000002")
    # A second compile does not move the step: it is the FIRST compile that completed it.
    assert status.first_compile_at(library) == first


def test_derived_steps_join_the_recorded_ones_under_the_five_names(home, make_library, monkeypatch):
    library = make_library()
    library.record_step("infra")
    _name_the_owner(library)
    _commit(library.canonical_dir, "memory/a.md", "compile 0198f0aa-1111-7000-8000-000000000001")
    _profile_run(monkeypatch, PROFILE_DONE)
    steps = status.steps_document(home, library, probe_profile=True)
    assert list(steps) == ["infra", "credentials", "profile", "skill", "first_compile"]
    assert steps["infra"] and steps["profile"] is True and steps["first_compile"]
    assert steps["credentials"] is None and steps["skill"] is None
    # Nothing derived reached library.yaml: the file still carries three steps only.
    assert set(read_yaml(library.path / "library.yaml")["steps"]) == {"infra", "credentials", "skill"}
    assert "profile: done" in status.render_text(
        {"home": {"path": "/h", "version": "0"}, "docker": {"reachable": True}, "services": {},
         "libraries": [{"name": "notes", "current": True, "engine": {"up": True, "port": 1},
                        "engine_dir": "/e", "key": False, "canonical_head": None, "skill_fresh": None,
                        "unattended": False, "agent_model": "", "reasoning_effort": "",
                        "queue": None, "last_used": None, "steps": steps}]}
    )


def test_a_library_yaml_from_before_the_change_still_loads(home, make_library):
    library = make_library()
    path = library.path / "library.yaml"
    document = read_yaml(path)
    document["steps"] = {"infra": "2026-07-01T00:00:00+00:00", "credentials": None,
                         "profile": "2026-07-02T00:00:00+00:00", "skill": None,
                         "first_compile": "2026-07-03T00:00:00+00:00"}
    atomic_write(path, yaml_text(document))
    reloaded = Library.load(home, "notes")
    assert reloaded.state.steps.infra == "2026-07-01T00:00:00+00:00"
    assert set(reloaded.state.steps.model_dump()) == {"infra", "credentials", "skill"}
    with pytest.raises(ValueError, match="no home command owns the step"):
        reloaded.record_step("profile")


@pytest.mark.parametrize("code,expected", [(0, True), (4, False), (2, None)])
def test_skill_verify_exit_meanings(home, make_library, monkeypatch, code, expected):
    library = make_library()
    library.record_step("skill")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=code)
    monkeypatch.setattr(status.subprocess, "run", run)
    assert status.skill_fresh(home, library) is expected
    # A project verify: the library directory is the project the package is installed into.
    assert calls[0][0][1:5] == ["skill", "verify", "--project", str(library.path)]
    assert "--dir" not in calls[0][0]
    assert calls[0][1]["env"]["PNEUMA_KNOWLEDGE_ENV_FILE"] == ""


def test_empty_home_status_is_read_only(tmp_path, monkeypatch):
    home = Home(tmp_path / "absent")
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    assert status.status_document(home)["libraries"] == []
    assert not home.path.exists()


def _commit(repo, relative, message):
    """One canonical commit, written the way the library's adapter writes them."""
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(message, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-q", "-m", message],
                   check=True, capture_output=True)
