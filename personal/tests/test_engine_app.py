"""The edition's engine entry: the home's routes over the library's own application.

Every test here builds the application and never enters its lifespan, which is the point:
`/home/*` answers a machine whose middleware is down, so nothing it does may need a live
AppContext. `build_context` is replaced with a refusal to make that mechanical.
"""

import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pneuma_knowledge_service.api import app as app_module
from pneuma_knowledge_service.settings import Settings

from pkc_personal import engine, engine_app, infra, status
from pkc_personal.library import Library

PKCHOME = "/opt/pkc/bin/pkchome"


@pytest.fixture
def client(home, make_library, monkeypatch):
    """One library's engine, with every probe that would touch the machine stubbed out."""
    make_library()
    config = home.config
    config.install.pkchome = PKCHOME
    home.save_config(config)
    monkeypatch.setattr(
        app_module, "build_context",
        lambda *_: pytest.fail("the home routes must answer without a live AppContext"),
    )
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    monkeypatch.setattr(engine, "pid_alive", lambda _: False)
    monkeypatch.setattr(status, "queue_status", lambda _: None)
    library = Library.load(home, "notes")
    app = engine_app.build_app(home, library, Settings(_env_file=None))
    return TestClient(app)


@pytest.fixture
def commands(monkeypatch):
    """Every `pkchome` invocation this process would make, run or detached."""
    runs, detached = [], []

    def run(command, **kwargs):
        runs.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="done\n", stderr="")

    def popen(command, **kwargs):
        detached.append((command, kwargs))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(engine_app.subprocess, "run", run)
    monkeypatch.setattr(engine_app.subprocess, "Popen", popen)
    return SimpleNamespace(runs=runs, detached=detached)


def test_status_is_the_document_the_command_prints(client, home):
    response = client.get("/home/status")
    assert response.status_code == 200
    document = response.json()
    assert set(document) == {"home", "docker", "services", "libraries", "sync"}
    assert document["home"]["path"] == str(home.path)
    assert document["docker"] == {"reachable": False}
    assert set(document["services"]) == {"postgres", "qdrant", "meili", "rustfs"}
    row = document["libraries"][0]
    assert row["name"] == "notes" and row["tenant"] == "lib-notes" and row["current"] is True
    # The two fields the console's parser cannot do without: the port it navigates to and
    # the five steps it draws.
    assert row["engine"]["port"] == Library.load(home, "notes").state.engine.port
    assert list(row["steps"]) == list(status.STEP_ORDER)


def test_status_answers_with_the_document_the_status_function_produced(client, monkeypatch):
    """The document is the function's, not a re-implementation and not `pkchome` re-run."""
    marker = {"home": {"path": "/h", "version": "9"}, "docker": {"reachable": True},
              "services": {}, "libraries": [{"name": "notes", "current": False}]}
    monkeypatch.setattr(status, "status_document", lambda _home: marker)
    monkeypatch.setattr(
        engine_app.subprocess, "run",
        lambda *a, **k: pytest.fail("the document is never shelled out for"),
    )
    body = client.get("/home/status").json()
    assert body["home"] == {"path": "/h", "version": "9"}


def test_libraries_is_the_array_alone(client):
    response = client.get("/home/libraries")
    assert response.status_code == 200
    rows = response.json()
    assert [row["name"] for row in rows] == ["notes"]
    assert rows[0]["tenant"] == "lib-notes"


def test_current_names_the_library_this_engine_serves(home, make_library, monkeypatch):
    """A console is served by ONE library's engine, so `current` is that library — whatever
    another terminal has since made the home's current one."""
    make_library()
    make_library("second")
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    monkeypatch.setattr(engine, "pid_alive", lambda _: False)
    from pkc_personal.library import use_library

    use_library(home, "second")
    app = engine_app.build_app(home, Library.load(home, "notes"), Settings(_env_file=None))
    rows = TestClient(app).get("/home/libraries").json()
    assert {row["name"]: row["current"] for row in rows} == {"notes": True, "second": False}


def test_version_names_the_edition(client):
    from pkc_personal import __version__

    assert client.get("/home/version").json() == {"pkc_personal": __version__}


def test_use_runs_the_recorded_pkchome(client, commands):
    body = client.post("/home/actions/use", json={"name": "second"}).json()
    assert body == {"ok": True, "stdout": "done\n", "stderr": "", "exit": 0}
    command, options = commands.runs[0]
    assert command == [PKCHOME, "library", "use", "second"]
    assert options["capture_output"] is True and options["timeout"] == engine_app.ACTION_TIMEOUT
    assert not commands.detached


def test_a_name_that_is_not_a_library_name_never_reaches_a_subprocess(client, commands):
    assert client.post("/home/actions/use", json={"name": "../etc"}).status_code == 422
    assert client.post("/home/actions/use", json={}).status_code == 422
    assert not commands.runs


def test_up_reports_the_command_result(client, commands):
    body = client.post("/home/actions/up").json()
    assert body == {"ok": True, "stdout": "done\n", "stderr": "", "exit": 0}
    assert commands.runs[0][0] == [PKCHOME, "up"]


def test_a_failed_command_is_reported_not_raised(client, commands, monkeypatch):
    monkeypatch.setattr(
        engine_app.subprocess, "run",
        lambda command, **kw: SimpleNamespace(returncode=2, stdout="", stderr="no docker\n"),
    )
    assert client.post("/home/actions/up").json() == {
        "ok": False, "stdout": "", "stderr": "no docker\n", "exit": 2}


def test_a_command_that_never_returns_is_bounded(client, monkeypatch):
    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(engine_app.subprocess, "run", run)
    body = client.post("/home/actions/up").json()
    assert body["ok"] is False and body["exit"] is None and "timed out" in body["stderr"]


@pytest.mark.parametrize("verb", ["down", "restart"])
def test_stopping_this_engine_is_detached_and_answered_at_once(client, commands, verb):
    """`down` and `restart` kill the process group this request is being served from. Waited
    on, the answer would never be written; detached, the request returns first."""
    assert client.post(f"/home/actions/{verb}").json() == {"ok": True, "detached": True}
    command, options = commands.detached[0]
    assert command == [PKCHOME, verb]
    assert options["start_new_session"] is True
    assert not commands.runs


def test_an_unknown_action_is_a_404(client, commands):
    assert client.post("/home/actions/wipe").status_code == 404
    assert not commands.runs and not commands.detached


def test_sync_action_pins_this_engine_and_detaches(client, commands, home):
    assert client.post("/home/actions/sync").json() == {"ok": True, "detached": True}
    command, options = commands.detached[0]
    assert command == [PKCHOME, "sync", "--library", "notes", "--json"]
    assert options["start_new_session"] is True
    assert options["env"]["PKC_HOME"] == str(home.path)
    assert not commands.runs


def test_sync_status_is_computed_from_edition_state(client, home):
    from pkc_personal.library import watch_project
    from pkc_personal.sync import converter

    library = Library.load(home, "notes")
    watch_project(library, str(home.path))
    state = {"version": 1, "sessions": {}, "last_run_at": "2026-09-01T00:00:00+00:00",
             "last_result": {"scanned": 3, "held": 2, "ingested": 1}}
    converter().atomic_json(library.path / "sync-state.json", state)
    document = client.get("/home/status").json()
    observation = document["sync"]
    assert observation == document["libraries"][0]["sync"]
    assert observation["last_result"] == state["last_result"]
    assert observation["watching"] == [str(home.path)]
    assert observation["next_due"] == "2026-09-01T00:15:00+00:00"


def test_the_console_mount_leaves_the_home_namespace_alone(home, make_library, monkeypatch, tmp_path):
    """The SPA fallback answers every unclaimed path with index.html. `/home/*` is claimed."""
    make_library()
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    monkeypatch.setattr(engine, "pid_alive", lambda _: False)
    monkeypatch.setattr(status, "queue_status", lambda _: None)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>console", encoding="utf-8")
    app = engine_app.build_app(
        home, Library.load(home, "notes"), Settings(_env_file=None), static_dir=dist
    )
    client = TestClient(app)
    assert client.get("/home/status").json()["libraries"][0]["name"] == "notes"
    assert client.get("/anything").text == "<!doctype html>console"


def test_main_hands_the_home_app_to_the_library_engine(home, make_library, monkeypatch):
    """The entry builds the app itself and gives it to the library's `run_engine`: one
    process, one lifecycle, and the console's dist still mounted by the library."""
    make_library()
    calls = {}

    async def run_engine(settings, **kwargs):
        calls.update(kwargs, settings=settings)

    monkeypatch.setattr(engine_app, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(engine_app, "run_engine", run_engine)
    engine_app.main(["--library", "notes", "--port", "24999", "--no-worker"])
    assert calls["port"] == 24999 and calls["host"] == "127.0.0.1" and calls["worker"] is False
    served = TestClient(calls["app"])
    assert served.get("/home/version").status_code == 200
    assert served.get("/healthz").status_code == 200   # the library's own surface is untouched
