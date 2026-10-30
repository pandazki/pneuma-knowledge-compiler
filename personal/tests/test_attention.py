import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pkc_personal.attention import kernel
from pkc_personal.attention.evidence import observe, validate_sources
from pkc_personal.attention.routes import build_router
from pkc_personal.attention.store import Preferences, Store, initial, stamp
from pkc_personal.attention.worker import Worker, due

NOW = 1800000000


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


@pytest.fixture(autouse=True)
def fixed_worker_clock(monkeypatch):
    monkeypatch.setattr("pkc_personal.attention.worker.monotonic", lambda: 0.0)


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "canonical"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "synthetic@example.invalid")
    git(repo, "config", "user.name", "Synthetic Owner")
    (repo / "work.md").write_text(
        "# Synthetic launch\nRelease review is due tomorrow. [cite: s-test ¶1]\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "synthetic knowledge")
    library = SimpleNamespace(
        path=tmp_path,
        canonical_dir=repo,
        state=SimpleNamespace(name="test", tenant="tenant-test"),
    )
    return library, Store(tmp_path / "attention")


def batch(ref, title="Review launch", weight="high"):
    return {
        "declarations": [
            {
                "id": "launch",
                "relation": "new",
                "title": title,
                "summary": "A synthetic release needs review.",
                "kind": "needs-you",
                "weight": weight,
                "reason": "Owner decision pending",
                "sources": [{"channel": "canonical", "ref": ref}],
            }
        ],
        "acknowledges": [],
    }


async def executor(library, settings, system, packet):
    if not packet["state"]["root"]["items"]:
        return batch(packet["documents"][0]["ref"])
    return {"declarations": [], "acknowledges": []}


def test_window_is_anchored_and_threshold_obeys_minimum_interval():
    state = initial()
    prefs = Preferences()
    state.update(pending={"a": "head"}, pending_since=NOW, pending_count=1)
    assert due(state, prefs, NOW + 299) is None
    assert due(state, prefs, NOW + 300) == "window"
    state["pending_count"] = 5
    assert due(state, prefs, NOW) == "threshold"
    state["last_attempt"] = NOW
    assert due(state, prefs, NOW + 299) is None
    assert due(state, prefs, NOW + 300) == "threshold"
    state.update(pending={}, last_run=NOW, last_attempt=NOW)
    assert due(state, prefs, NOW + 21600) == "review"
    state["retry_at"] = NOW + 22000
    assert due(state, prefs, NOW + 21600) is None
    assert due(state, prefs.model_copy(update={"enabled": False}), NOW + 23000) is None


def test_restart_preserves_pending_and_frozen_history(setup):
    library, store = setup
    worker = Worker(library, None, store, executor)
    asyncio.run(worker.tick(NOW))
    assert store.read()["pending"]
    assert not store.frames()
    reopened = Store(store.directory)
    worker = Worker(library, None, reopened, executor)
    asyncio.run(worker.tick(NOW + 300))
    frame = reopened.frames()[0]
    assert frame["state"]["root"]["items"][0]["share"] == 12
    assert not reopened.read()["pending"]
    original = json.dumps(frame)
    asyncio.run(worker.tick(NOW + 21900))
    assert len(reopened.frames()) == 2
    assert reopened.frames()[0]["signal"]["received"] == 0
    assert reopened.frames()[0]["signal"]["type"] == "review"
    assert reopened.frames()[0]["state"]["revision"] == frame["state"]["revision"]
    assert json.dumps(reopened.frame(frame["id"])) == original
    assert git(library.canonical_dir, "status", "--porcelain") == ""
    assert git(library.canonical_dir, "rev-list", "--count", "HEAD") == "1"


def test_only_committed_objects_are_read(setup):
    library, store = setup
    original = git(library.canonical_dir, "rev-parse", "HEAD")
    (library.canonical_dir / "work.md").write_text("Uncommitted private change")
    store.configure({"threshold": 1})
    asyncio.run(Worker(library, None, store, executor).tick(NOW))
    evidence = store.frames()[0]["evidence"][0]
    assert "Uncommitted" not in evidence["text"]
    assert evidence["head"] == original
    assert (
        library.canonical_dir / "work.md"
    ).read_text() == "Uncommitted private change"


def test_failure_does_not_consume_cursor_or_affect_library(setup):
    library, store = setup
    store.configure({"threshold": 1})

    async def broken(*args):
        raise RuntimeError("synthetic provider failure")

    asyncio.run(Worker(library, None, store, broken).tick(NOW))
    state = store.read()
    assert state["pending"] and state["retry_at"] == NOW + 300
    assert state["snapshot"]["event_seq"] == 0 and not state["running"]
    assert not store.frames()
    asyncio.run(Worker(library, None, store, executor).tick(NOW + 300))
    assert len(store.frames()) == 1 and not store.read()["error"]


def test_canonical_change_during_round_is_received_next_tick(setup):
    library, store = setup
    store.configure({"threshold": 1})

    async def changes(lib, settings, system, packet):
        (lib.canonical_dir / "second.md").write_text("Synthetic later observation")
        git(lib.canonical_dir, "add", "second.md")
        git(lib.canonical_dir, "commit", "-qm", "later knowledge")
        return await executor(lib, settings, system, packet)

    asyncio.run(Worker(library, None, store, changes).tick(NOW))
    asyncio.run(Worker(library, None, store, executor).tick(NOW + 1))
    assert "second.md" in store.read()["pending"]
    asyncio.run(Worker(library, None, store, executor).tick(NOW + 300))
    assert len(store.frames()) == 2
    assert store.frames()[0]["evidence"][0]["path"] == "second.md"


def test_annotation_race_cannot_be_overwritten(setup):
    library, store = setup
    store.configure({"threshold": 1})
    asyncio.run(Worker(library, None, store, executor).tick(NOW))
    store.request()

    async def concurrent(lib, settings, system, packet):
        store.annotate("launch", "Synthetic Owner correction", "owner-1", NOW + 301)
        return {"declarations": [], "acknowledges": []}

    asyncio.run(Worker(library, None, store, concurrent).tick(NOW + 300))
    state = store.read()
    assert len(store.frames()) == 1
    assert len(state["snapshot"]["annotations"]) == 1
    assert due(state, store.preferences(), NOW + 600) == "requested"
    assert not state["running"]


def test_budget_rejection_gets_bounded_repair(setup):
    library, store = setup
    store.configure({"threshold": 1})
    calls = []

    async def repair(lib, settings, system, packet):
        calls.append(packet)
        result = batch(packet["documents"][0]["ref"])
        if len(calls) == 1:
            result["declarations"] = [
                dict(result["declarations"][0], id=f"item-{i}", weight="critical")
                for i in range(3)
            ]
        return result

    asyncio.run(Worker(library, None, store, repair).tick(NOW))
    assert len(calls) == 2
    assert calls[1]["validation_error"]["code"] == "budget_exceeded"
    assert store.frames()[0]["state"]["root"]["used"] == 12


def test_new_sources_cannot_be_invented():
    before = kernel.initial_snapshot()
    result, _ = kernel.commit(
        before,
        dict(batch("canonical:other:secret.md"), batch_id="test"),
        "fold",
        stamp(NOW),
    )
    with pytest.raises(ValueError, match="unknown attention"):
        validate_sources(result, before, [])


def test_routes_isolate_libraries_and_refuse_cross_origin(setup, tmp_path):
    library, store = setup
    store.configure({"threshold": 1})
    asyncio.run(Worker(library, None, store, executor).tick(NOW))
    app = FastAPI()
    app.include_router(build_router(library))
    client = TestClient(app)
    assert client.get("/home/attention/state").json()["tenant"] == "tenant-test"
    assert (
        client.patch("/home/attention/preferences", json={"board": "space"}).json()[
            "board"
        ]
        == "space"
    )
    assert (
        client.patch("/home/attention/preferences", json={"threshold": 0}).status_code
        == 422
    )
    assert (
        client.post(
            "/home/attention/review", headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/home/attention/state", headers={"Host": "attacker.invalid"}
        ).status_code
        == 403
    )
    ref = store.frames()[0]["evidence"][0]["ref"]
    assert (
        client.get("/home/attention/evidence", params={"ref": ref}).status_code == 200
    )
    second = SimpleNamespace(
        path=tmp_path / "second",
        state=SimpleNamespace(name="other", tenant="tenant-other"),
    )
    other = FastAPI()
    other.include_router(build_router(second))
    other = TestClient(other)
    assert other.get("/home/attention/frames/1").status_code == 404
    assert other.get("/home/attention/evidence", params={"ref": ref}).status_code == 404
    assert other.get("/home/attention/state").json()["state"]["root"]["items"] == []
    assert client.get("/home/attention/view").status_code == 200
    assert (
        "script-src"
        in client.get("/home/attention/view").headers["content-security-policy"]
    )
    assert client.get("/home/attention/assets/board.js").status_code == 200
    assert (
        client.post(
            "/home/attention/annotations",
            json={"item": "launch", "text": "test", "batch_id": "a", "event_seq": 0},
        ).status_code
        == 409
    )


def test_backlog_survives_bounded_packet(setup):
    library, store = setup
    for i in range(20):
        (library.canonical_dir / f"synthetic-{i}.md").write_text(f"Synthetic topic {i}")
    git(library.canonical_dir, "add", ".")
    git(library.canonical_dir, "commit", "-qm", "synthetic batch")
    store.configure({"threshold": 1})
    worker = Worker(library, None, store, executor)
    asyncio.run(worker.tick(NOW))
    assert len(store.read()["pending"]) == 5
    asyncio.run(worker.tick(NOW + 300))
    assert not store.read()["pending"]
    assert sum(len(frame["evidence"]) for frame in store.frames()) == 21


def test_annotation_retry_is_idempotent_even_after_revision_changed(setup):
    library, store = setup
    store.configure({"threshold": 1})
    asyncio.run(Worker(library, None, store, executor).tick(NOW))
    seq = store.read()["snapshot"]["event_seq"]
    receipt = store.annotate(
        "launch", "Synthetic correction", "same-request", NOW + 1, seq
    )
    again = store.annotate(
        "launch", "Synthetic correction", "same-request", NOW + 2, seq
    )
    assert receipt["annotation_id"] == again["annotation_id"]
    assert again["batch_status"] == "already_committed"
    assert len(store.read()["snapshot"]["annotations"]) == 1
    with pytest.raises(kernel.FoldError):
        store.annotate("launch", "Different text", "same-request", NOW + 2, seq)


def test_quiet_signal_never_mislabels_a_pending_window():
    state = initial()
    state.update(
        last_run=NOW - 21600, pending={"a": "head"}, pending_count=1, pending_since=NOW
    )
    assert due(state, Preferences(), NOW) is None


def test_executor_timeout_terminates_its_process(tmp_path):
    import os
    import sys
    from pkc_personal.attention.runner import subprocess_text

    with pytest.raises(TimeoutError):
        asyncio.run(
            subprocess_text(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                "",
                tmp_path,
                dict(os.environ),
                timeout=0.1,
            )
        )


def test_upstream_kernel_behavior_is_pinned():
    import ast
    import hashlib
    from pathlib import Path

    tree = ast.parse(Path(kernel.__file__).read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
    digest = hashlib.sha256(ast.dump(tree).encode()).hexdigest()
    assert digest == "35a1d6a46d026f9132ae02ffb3ad4463c7ff3189fbd46337ef6184ddfabacabf"


def test_retrospective_uses_original_dates_and_deduplicates_exported_turns():
    from pkc_personal.attention.retrospective import aggregate

    row = dict(
        day="2026-10-02",
        source_id="source-a",
        block=0,
        provider="synthetic",
        session="session-a",
        turn_id="turn-a",
        project_path="/synthetic/alpha",
        text="We will pause alpha after the experiment.",
        text_length=41,
    )
    repeated = dict(row, source_id="source-b", block=7)
    other = dict(
        row, day="2026-10-04", turn_id="turn-b", project_path="/synthetic/beta"
    )
    result = aggregate(
        [row, repeated, other],
        {("synthetic", "session-a", "/synthetic/alpha"): "prj_alpha"},
        "2026-10-01",
        "2026-10-04",
    )
    assert [day["total"] for day in result["days"]] == [0, 1, 0, 1]
    assert result["days"][1]["counts"] == {"prj-alpha": 1}
    assert result["coverage"]["dated_owner_turns"] == 2
    assert len(result["samples"]) == 2
    assert result["samples"][0]["ref"] == "source:source-a:0"
    assert result["samples"][0]["date"] == "2026-10-02"
    assert result["metric"] == "recorded_owner_turns"


def test_retrospective_bounds_model_context_across_the_entire_horizon():
    from datetime import date, timedelta
    from pkc_personal.attention.retrospective import aggregate

    rows = [
        dict(
            day=str(date(2026, 7, 1) + timedelta(days=day)),
            source_id=f"s-{day}-{project}",
            block=0,
            provider="synthetic",
            session=f"p-{project}",
            turn_id=str(day),
            project_path=f"/synthetic/{project}",
            text="A dated observation.",
            text_length=20,
        )
        for day in range(90)
        for project in range(12)
    ]
    result = aggregate(rows, {}, "2026-07-01", "2026-09-28", truncated=True)
    assert len(result["samples"]) == 96
    assert result["samples"][0]["date"] == "2026-07-01"
    assert result["samples"][-1]["date"] == "2026-09-28"
    assert result["coverage"]["candidate_samples"] == 900
    assert result["coverage"]["truncated"]
    assert sum(day["total"] for day in result["days"]) == 1080


def test_collection_bindings_do_not_take_writer_lock_or_read_partial_append(tmp_path):
    from pkc_personal.attention.retrospective import bindings

    (tmp_path / "collection-observations.jsonl").write_bytes(
        b'{"provider":"synthetic","session_id":"s1","project_path":"/alpha","project_id":"prj_alpha"}\n'
        b'{"provider":"synthetic","session_id":"s2"'
    )
    assert bindings(SimpleNamespace(path=tmp_path)) == {
        ("synthetic", "s1", "/alpha"): "prj_alpha"
    }


def test_landscape_connection_is_readonly_and_scoped_to_bound_tenant(
    setup, monkeypatch
):
    from pkc_personal.attention import retrospective
    from psycopg.conninfo import conninfo_to_dict

    library, _ = setup
    calls = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, query, parameters):
            calls.append((query, parameters))
            return self

        async def fetchall(self):
            return []

    async def connect(dsn, **kwargs):
        options = conninfo_to_dict(dsn)["options"]
        assert "default_transaction_read_only=on" in options
        assert "statement_timeout=15000" in options
        return Connection()

    monkeypatch.setattr(retrospective.psycopg.AsyncConnection, "connect", connect)
    result = asyncio.run(
        retrospective.read_landscape(
            library,
            SimpleNamespace(
                default_timezone="Asia/Shanghai",
                pg_dsn="postgresql://synthetic@localhost/synthetic",
            ),
            NOW,
        )
    )
    query, parameters = calls[0]
    assert parameters[0] == "tenant-test"
    assert "s.user_id=t.user_id" in query and "b.user_id=t.user_id" in query
    assert "t.user_id=%s" in query and "s.archived_at IS NULL" in query
    assert len(result["days"]) == 14 and all(d["total"] == 0 for d in result["days"])


def test_reflection_rejects_uncited_or_unknown_evidence_and_preserves_original_frame(
    setup,
):
    from pkc_personal.attention.worker import validate_reflection

    library, store = setup
    ref = "source:synthetic-source:0"
    docs = [
        {
            "ref": ref,
            "path": "source/synthetic-source/0",
            "head": None,
            "text": "Pause alpha to finish beta.",
        }
    ]
    reflection = {
        "direction": {
            "text": "The recorded reason supports an intentional pivot.",
            "refs": [ref],
        }
    }
    assert validate_reflection(reflection, store.read()["snapshot"], docs) == reflection
    for invalid in (
        {"text": "Unsupported", "refs": []},
        {"text": "Unsupported", "refs": ["source:another-user:0"]},
        {"text": "", "refs": [ref]},
    ):
        with pytest.raises(ValueError):
            validate_reflection({"summary": invalid}, store.read()["snapshot"], docs)
    before = store.read()
    snapshot, receipt = kernel.commit(
        before["snapshot"],
        {"batch_id": "first", "declarations": []},
        "fold",
        stamp(NOW),
    )
    store.accept(
        before,
        snapshot,
        receipt,
        {"type": "review"},
        docs,
        NOW,
        "synthetic",
        reflection=reflection,
        landscape={"days": []},
    )
    first = store.frames()[0]
    with store.transaction() as (_, state):
        state["reflection"] = {
            "summary": {"text": "Later understanding", "refs": [ref]}
        }
    assert store.frame(first["id"])["reflection"] == reflection
    app = FastAPI()
    app.include_router(build_router(library))
    client = TestClient(app)
    history = client.get("/home/attention/history").json()
    assert history[0]["reflection"] == reflection and "evidence" not in history[0]
    assert (
        client.get("/home/attention/evidence", params={"ref": ref}).json()["text"]
        == docs[0]["text"]
    )
    assert (
        client.patch(
            "/home/attention/preferences", json={"board": "lineage", "horizon_days": 30}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/home/attention/preferences", json={"horizon_days": 100}
        ).status_code
        == 422
    )


def test_rewritten_head_retargets_pending_evidence(setup):
    library, store = setup
    repo = library.canonical_dir
    base = git(repo, "rev-parse", "HEAD")
    (repo / "obsolete.md").write_text("obsolete-body")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "obsolete branch")
    asyncio.run(Worker(library, None, store, executor).tick(NOW))
    git(repo, "reset", "--hard", base)
    (repo / "current.md").write_text("current-body")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "replacement branch")
    head = git(repo, "rev-parse", "HEAD")
    history = git(repo, "log", "--format=%H")
    asyncio.run(Worker(library, None, store, executor).tick(NOW + 300))
    documents = store.frames()[0]["evidence"]
    assert all(d["head"] == head for d in documents)
    assert not any("obsolete-body" in d["text"] for d in documents)
    assert next(d for d in documents if d["path"] == "obsolete.md")["deleted"]
    assert next(d for d in documents if d["path"] == "current.md")["text"] == "current-body"
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "log", "--format=%H") == history


@pytest.mark.parametrize("answer", ["{invalid", "[]", '{"declarations":null,"acknowledges":[]}'])
@pytest.mark.parametrize("exhaust", [False, True])
def test_runner_output_gets_bounded_repair(setup, monkeypatch, answer, exhaust):
    from pkc_personal.attention import runner

    library, store = setup
    library.state.choices = SimpleNamespace(backend="claude", model=None)
    store.configure({"threshold": 1})
    calls = []
    history = git(library.canonical_dir, "log", "--format=%H")

    async def output(argv, prompt, cwd, env):
        packet = json.loads(prompt)
        calls.append(packet)
        return answer if exhaust or len(calls) == 1 else json.dumps(batch(packet["documents"][0]["ref"]))

    monkeypatch.setattr(runner, "subprocess_text", output)
    asyncio.run(Worker(library, None, store, runner.judge).tick(NOW))
    assert len(calls) == (3 if exhaust else 2)
    assert all(p["state"] == calls[0]["state"] for p in calls)
    assert calls[1]["validation_error"]
    state = store.read()
    if exhaust:
        assert not store.frames() and state["pending"]
        assert state["snapshot"]["event_seq"] == 0
        assert state["retry_at"] == NOW + 300
    else:
        assert len(store.frames()) == 1 and not state["pending"]
    assert git(library.canonical_dir, "status", "--porcelain") == ""
    assert git(library.canonical_dir, "log", "--format=%H") == history


@pytest.mark.parametrize("failure", [ValueError, RuntimeError, asyncio.CancelledError])
def test_executor_failures_are_not_validation_repairs(setup, monkeypatch, failure):
    from pkc_personal.attention import runner

    library, store = setup
    library.state.choices = SimpleNamespace(backend="api")
    store.configure({"threshold": 1})
    calls = []

    class Model:
        async def ainvoke(self, messages):
            calls.append(messages)
            raise failure("synthetic failure")

    monkeypatch.setattr(runner, "build_chat_model_for", lambda *args: Model())
    if failure is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(Worker(library, None, store, runner.judge).tick(NOW))
    else:
        asyncio.run(Worker(library, None, store, runner.judge).tick(NOW))
    assert len(calls) == 1
    assert not store.frames() and store.read()["pending"]
    assert not store.read()["running"]


def test_missing_blob_is_not_recorded_as_deletion(setup):
    library, store = setup
    repo = library.canonical_dir
    store.configure({"threshold": 1})
    head = git(repo, "rev-parse", "HEAD")
    blob = git(repo, "rev-parse", "HEAD:work.md")
    (repo / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
    asyncio.run(Worker(library, None, store, executor).tick(NOW))
    assert not store.frames()
    assert store.read()["pending"] == {"work.md": head}
    assert store.read()["retry_at"] == NOW + 300


def test_committed_deletion_supplies_tombstone(setup):
    library, store = setup
    repo = library.canonical_dir
    worker = Worker(library, None, store, executor)
    asyncio.run(worker.tick(NOW))
    git(repo, "rm", "work.md")
    git(repo, "commit", "-qm", "synthetic removal")
    head = git(repo, "rev-parse", "HEAD")
    asyncio.run(worker.tick(NOW + 300))
    evidence = store.frames()[0]["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["head"] == head
    assert evidence[0]["deleted"] and evidence[0]["text"] == ""
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("enabled", [False, True])
def test_request_during_judgment_survives_accept(setup, enabled):
    library, store = setup
    store.configure({"enabled": enabled})
    store.request()

    async def concurrent(lib, settings, system, packet):
        store.configure({"horizon_days": 30})
        store.request()
        return await executor(lib, settings, system, packet)

    asyncio.run(Worker(library, None, store, concurrent).tick(NOW))
    assert len(store.frames()) == 1
    assert due(store.read(), store.preferences(), NOW + 300) == "requested"
    asyncio.run(Worker(library, None, store, executor).tick(NOW + 300))
    assert len(store.frames()) == 2
    assert due(store.read(), store.preferences(), NOW + 600) is None


@pytest.mark.parametrize("explicit_now", [False, True])
def test_slow_validation_failure_backoff_starts_at_completion(
    setup, monkeypatch, explicit_now
):
    from pkc_personal.attention import worker

    library, store = setup
    store.request()
    elapsed = [0.0]
    monkeypatch.setattr(worker, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(worker.time, "time", lambda: NOW)
    calls = []

    async def invalid(*args):
        calls.append(True)
        elapsed[0] += 180
        raise worker.OutputValidationError("synthetic invalid output")

    asyncio.run(Worker(library, None, store, invalid).tick(NOW if explicit_now else None))
    assert len(calls) == 3
    assert due(store.read(), store.preferences(), NOW + 839) is None
    assert due(store.read(), store.preferences(), NOW + 840) == "requested"
    assert store.read()["retry_at"] == NOW + 840


@pytest.mark.parametrize("requested", [False, True])
def test_legacy_request_state_loads_and_consumes_only_its_batch(setup, requested):
    library, store = setup
    legacy = initial()
    legacy.pop("request_seq")
    legacy.pop("completed_request_seq")
    legacy["requested"] = requested
    with store.connect() as db:
        db.execute("UPDATE state SET body=? WHERE id=1", (json.dumps(legacy),))
    store = Store(store.directory)
    store.configure({"enabled": False})
    assert due(store.read(), store.preferences(), NOW) == (
        "requested" if requested else None
    )
    store.request()
    asyncio.run(Worker(library, None, store, executor).tick(NOW))
    assert len(store.frames()) == 1
    assert due(store.read(), store.preferences(), NOW + 300) is None
