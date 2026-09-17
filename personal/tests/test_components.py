"""Index components in the personal edition: enabled at creation, migrated on upgrade.

The Owner asked their own library 「说说我这两天的工作」 and got an answer built out of
unrelated lexical and vector hits. The reason was here, not in the framework: this edition
registered no index component, so a question about a PERIOD reached no path that answers
periods. These tests hold the three places that had to change — what a new library's engine
states, what an existing one is given on the next start, and what the processes started from
here are told — plus the rebuild that makes an upgraded library answer about its own past.

Keyless and store-free: the queue is a stand-in, so what is under test is which tenant is
asked for a rebuild and when, never psycopg.
"""

import json

import pytest

from pkc_personal import cli, engine, infra, library as library_module, status
from pkc_personal.environment import home_environment
from pkc_personal.home import read_yaml, yaml_text, atomic_write
from pkc_personal.library import DEFAULT_COMPONENTS, engine_components, migrate_engine


class _Queue:
    """The job queue, as a list. `store_up()` is separate because the port probe is also
    what keeps library creation off the machine's Postgres — it is turned on once the
    libraries a test needs already exist."""

    def __init__(self, monkeypatch) -> None:
        self.asked: list[tuple[str, str]] = []
        self._monkeypatch = monkeypatch
        monkeypatch.setattr(library_module, "_enqueue_rebuild", self._enqueue)

    async def _enqueue(self, dsn: str, tenant) -> str:
        self.asked.append((str(tenant), dsn))
        return f"job-{len(self.asked)}"

    def store_up(self) -> "_Queue":
        self._monkeypatch.setattr(infra, "tcp_port_open", lambda *_: True)
        return self


@pytest.fixture
def queue(monkeypatch):
    return _Queue(monkeypatch)


def engine_yaml(library) -> dict:
    return read_yaml(library.engine_dir / "engine.yaml")


# ------------------------------------------------------------------ a library gets `time`


def test_a_new_library_enables_time_and_nothing_else(make_library):
    """`time` is what a personal library needs to answer 这两天; `people` and `attention`
    are the application's later choice and are not switched on behind the Owner's back."""
    library = make_library()
    assert engine_yaml(library)["components"] == "time"
    assert engine_components(library) == DEFAULT_COMPONENTS == "time"
    assert "people" not in engine_yaml(library)["components"]
    assert "attention" not in engine_yaml(library)["components"]


def test_the_migration_adds_components_once_and_never_overwrites_a_choice(make_library):
    """A library created before the knob was set carries the schema's empty default. The
    migration states it once; a second run finds it stated and changes nothing; and a value
    the Owner put there by hand is their choice, not a gap to fill."""
    library = make_library()
    path = library.engine_dir / "engine.yaml"

    mapping = engine_yaml(library)
    mapping["components"] = ""  # the file as an older version of this edition wrote it
    atomic_write(path, yaml_text(mapping))
    assert engine_components(library) == ""

    assert migrate_engine(library) == ["components"]
    assert engine_yaml(library)["components"] == "time"
    keys = list(engine_yaml(library))
    before = path.read_bytes()

    assert migrate_engine(library) == []
    assert path.read_bytes() == before  # idempotent to the byte, key order included
    assert list(engine_yaml(library)) == keys

    mapping = engine_yaml(library)
    mapping["components"] = "time,people"
    atomic_write(path, yaml_text(mapping))
    assert migrate_engine(library) == []
    assert engine_yaml(library)["components"] == "time,people"

    # A file from before the knob existed does not state it at all, which means the same
    # empty set and is migrated the same way.
    mapping = engine_yaml(library)
    del mapping["components"]
    atomic_write(path, yaml_text(mapping))
    assert migrate_engine(library) == ["components"]
    assert engine_yaml(library)["components"] == "time"


def test_an_upgraded_library_is_queued_a_rebuild_before_its_engine_starts(
    home, make_library, monkeypatch
):
    """Enabling a component on a library that already holds sources indexes nothing by
    itself — the projection is derived, and what is already in L0 was indexed without it. So
    the start that migrates the file queues the rebuild that re-derives it, and it does both
    BEFORE the engine, which reads its directory once."""
    library = make_library()
    upgraded = make_library("older")
    mapping = engine_yaml(upgraded)
    mapping["components"] = ""
    atomic_write(upgraded.engine_dir / "engine.yaml", yaml_text(mapping))

    order: list[str] = []
    monkeypatch.setattr(infra, "render_compose", lambda _home: False)
    monkeypatch.setattr(infra, "stack_running", lambda _home: True)
    monkeypatch.setattr(infra, "persist_owner_profile", lambda *_a, **_k: False)
    monkeypatch.setattr(engine, "start", lambda _home, lib: order.append(f"start:{lib.state.name}"))

    def queued(_home, lib):
        order.append(f"rebuild:{lib.state.name}")
        return "job-1"

    monkeypatch.setattr(infra, "request_rebuild", queued)

    infra.up(home)

    # the library that already states the component is migrated by nobody and queued nothing
    assert order == ["start:notes", "rebuild:older", "start:older"]
    assert engine_yaml(upgraded)["components"] == "time"
    assert engine_yaml(library)["components"] == "time"

    order.clear()
    infra.up(home)
    assert order == ["start:notes", "start:older"]  # nothing left to migrate, nothing queued


def test_a_store_that_cannot_be_reached_leaves_the_library_unmigrated(
    home, make_library, monkeypatch
):
    """Both or neither. The migration is idempotent on the file, so a key written while the
    rebuild could not be queued would be a library holding the component with nothing indexed
    and no second chance — the next start must find the same work still to do."""
    upgraded = make_library("older")
    mapping = engine_yaml(upgraded)
    mapping["components"] = ""
    atomic_write(upgraded.engine_dir / "engine.yaml", yaml_text(mapping))

    monkeypatch.setattr(infra, "render_compose", lambda _home: False)
    monkeypatch.setattr(infra, "stack_running", lambda _home: True)
    monkeypatch.setattr(infra, "persist_owner_profile", lambda *_a, **_k: False)
    monkeypatch.setattr(engine, "start", lambda *_: None)
    monkeypatch.setattr(infra, "request_rebuild", lambda *_: None)

    infra.up(home)

    assert engine_yaml(upgraded)["components"] == ""


# ------------------------------------------------------------------ what the engine is told


def test_the_environment_states_the_components_the_engine_file_states(home, make_library):
    library = make_library()
    assert home_environment(home, library)["PNEUMA_KNOWLEDGE_COMPONENTS"] == "time"

    mapping = engine_yaml(library)
    mapping["components"] = "time,people"
    atomic_write(library.engine_dir / "engine.yaml", yaml_text(mapping))
    assert home_environment(home, library)["PNEUMA_KNOWLEDGE_COMPONENTS"] == "time,people"


def test_an_empty_components_file_states_no_variable_at_all(home, make_library):
    """Process environment outranks the engine file even when it is empty, so a variable set
    to nothing would be the statement that disables every component — never stated."""
    library = make_library()
    mapping = engine_yaml(library)
    mapping["components"] = ""
    atomic_write(library.engine_dir / "engine.yaml", yaml_text(mapping))
    assert "PNEUMA_KNOWLEDGE_COMPONENTS" not in home_environment(home, library)


# ------------------------------------------------------------------------- pkchome rebuild


def test_rebuild_queues_the_librarys_own_tenant(home, make_library, capsys, queue):
    make_library()
    library = make_library("other")

    queue.store_up()

    assert cli.main(["rebuild", "--library", "other"]) == 0
    assert queue.asked == [
        ("lib-other", home_environment(home, library)["PNEUMA_KNOWLEDGE_PG_DSN"])
    ]
    assert capsys.readouterr().out == (
        "rebuild queued for other (job job-1); pkchome status shows it while it runs\n"
    )


def test_rebuild_says_so_when_the_store_is_not_up(home, make_library, monkeypatch, capsys):
    make_library()
    monkeypatch.setattr(infra, "tcp_port_open", lambda *_: False)
    assert cli.main(["rebuild", "--library", "notes"]) == 1
    assert capsys.readouterr().err == (
        "the store is not up; run pkchome up, then pkchome rebuild\n"
    )


# --------------------------------------------------------------------------- what status says


def test_status_names_the_components_and_the_rebuild_in_flight(
    home, make_library, monkeypatch, capsys
):
    make_library()
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    monkeypatch.setattr(status, "skill_fresh", lambda *_: None)
    monkeypatch.setattr(
        engine, "status",
        lambda *_: {"pid": 4321, "up": True, "port": 24010, "uptime": 12.0},
    )
    monkeypatch.setattr(
        status, "queue_status",
        lambda _library: {"pending": 1, "failed": 0, "failed_by_kind": {}, "succeeded": 0,
                          "rebuilding": 1, "last_compile_at": None, "cooling": None,
                          "waiting": {}, "paused": {}},
    )

    assert cli.main(["status"]) == 0
    text = capsys.readouterr().out
    assert "  Components: time" in text
    assert "  Rebuild: 1 derived rebuild job(s) in the queue" in text

    assert cli.main(["status", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)["libraries"][0]
    assert row["components"] == "time" and row["queue"]["rebuilding"] == 1
