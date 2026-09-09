"""The tenant's owner profile: persisted at creation, so an empty library says it is empty.

An absent record and the untouched engine template both mean an unstated Owner.
These tests hold the record's presence, its contents, and the two
things persisting it must never do: overwrite a named Owner, or fail a setup because the
middleware is not up yet.
"""

import asyncio
import json
import secrets
from types import SimpleNamespace

import pytest

from pneuma_knowledge_service.persona_profile import is_placeholder

from pkc_personal import infra, library as library_module, status
from pkc_personal.environment import home_environment
from pkc_personal.library import Library, create_library, persist_owner_profile

#: The repository's own development stack (`infra/docker-compose.yml`).
DEV_PG_PORT = 15432
DEV_PG_PASSWORD = "pneuma_knowledge"


class FakeStore:
    """Every call the persistence makes, in the order it makes them."""

    def __init__(self, dsn, existing=None, **_kwargs):
        self.dsn = dsn
        self.existing = existing
        self.calls = []
        self.written = None

    async def open(self):
        self.calls.append("open")

    async def apply_schema(self):
        self.calls.append("apply_schema")

    async def get_user_profile(self, user_id):
        self.calls.append(f"get:{user_id}")
        return self.existing

    async def upsert_user_profile(self, user_id, profile):
        self.calls.append(f"upsert:{user_id}")
        self.written = profile

    async def aclose(self):
        self.calls.append("aclose")


@pytest.fixture
def fake_store(monkeypatch):
    """A reachable store whose one instance the test can read afterwards."""
    made = []

    def build(dsn, **kwargs):
        store = FakeStore(dsn, existing=build.existing, **kwargs)
        made.append(store)
        return store

    build.existing = None
    build.made = made
    monkeypatch.setattr(infra, "tcp_port_open", lambda host, port: True)
    monkeypatch.setattr(library_module, "PostgresStore", build)
    return build


def test_a_new_library_persists_the_engine_placeholder_under_its_own_tenant(
    home, make_library, fake_store
):
    library = make_library()
    # `create_library` did it once; the record is there before any engine has started.
    assert [store.calls for store in fake_store.made] == [
        ["open", "apply_schema", "upsert:lib-notes", "aclose"]
    ]
    written = fake_store.made[0].written
    assert written["user_id"] == "lib-notes"
    from pneuma_knowledge_core.domain.user import UserProfile
    assert written == UserProfile.unstated(library.state.tenant).model_dump(exclude={"level_style"})
    # The point of the write: what lands is a placeholder, and reads back as one.
    assert is_placeholder(written) is True
    assert fake_store.made[0].dsn == home_environment(home, library)["PNEUMA_KNOWLEDGE_PG_DSN"]


def test_only_if_missing_never_overwrites_an_owner_who_has_been_named(home, make_library, fake_store):
    library = make_library()
    fake_store.made.clear()
    fake_store.existing = {"display_name": "Wen", "occupation": "translator"}
    assert persist_owner_profile(home, library, only_if_missing=True) is False
    assert fake_store.made[0].calls == ["open", "apply_schema", "get:lib-notes", "aclose"]
    assert fake_store.made[0].written is None
    fake_store.existing = None
    assert persist_owner_profile(home, library, only_if_missing=True) is True
    assert fake_store.made[1].calls[-2:] == ["upsert:lib-notes", "aclose"]


def test_a_store_that_is_not_up_is_a_step_not_yet_doable(home, make_library, monkeypatch):
    monkeypatch.setattr(infra, "tcp_port_open", lambda host, port: False)

    def refuse(*_args, **_kwargs):
        raise AssertionError("no connection is opened while the stack is down")

    monkeypatch.setattr(library_module, "PostgresStore", refuse)
    library = make_library()
    assert persist_owner_profile(home, library) is False


def test_pkchome_up_persists_the_profile_of_a_library_created_while_the_stack_was_down(
    home, make_library, fake_store, monkeypatch
):
    from pkc_personal import engine

    library = make_library()
    fake_store.made.clear()
    monkeypatch.setattr(infra, "render_compose", lambda _home: False)
    monkeypatch.setattr(infra, "stack_running", lambda _home: True)
    monkeypatch.setattr(engine, "start", lambda *_: False)
    infra.up(home)
    assert fake_store.made[0].calls == [
        "open", "apply_schema", "get:lib-notes", "upsert:lib-notes", "aclose"
    ]
    assert Library.load(home, "notes").state.name == library.state.name


def test_the_engine_placeholder_reaches_a_real_postgres(home, monkeypatch):
    """The one integration: an isolated tenant on the development stack, then cleaned up."""
    if not infra.tcp_port_open("127.0.0.1", DEV_PG_PORT):
        pytest.skip(f"middleware unreachable: no Postgres on 127.0.0.1:{DEV_PG_PORT}")
    import psycopg

    from pneuma_knowledge_service.adapters.postgres import PostgresStore

    config = home.config
    config.infra.ports.postgres = DEV_PG_PORT
    config.infra.pg_password = DEV_PG_PASSWORD
    home.save_config(config)
    monkeypatch.setattr(library_module, "render_library", lambda *_: None)
    name = f"probe-{secrets.token_hex(6)}"
    library = create_library(home, name)
    dsn = home_environment(home, library)["PNEUMA_KNOWLEDGE_PG_DSN"]
    try:
        # `create_library` wrote it; the assertion is on the row, not on the return value.
        async def read():
            store = PostgresStore(dsn)
            await store.open()
            try:
                return await store.get_user_profile(library.state.tenant)
            finally:
                await store.aclose()

        record = asyncio.run(read())
        assert record is not None and record["user_id"] == library.state.tenant
        assert is_placeholder(record) is True
        # A second pass leaves the named Owner alone, and reports that it wrote nothing.
        assert persist_owner_profile(home, library, only_if_missing=True) is False
    finally:
        async def clean():
            async with await psycopg.AsyncConnection.connect(dsn) as conn:
                await conn.execute("DELETE FROM user_profiles WHERE user_id = %s",
                                   (library.state.tenant,))
                await conn.commit()

        asyncio.run(clean())
    assert asyncio.run(_absent(dsn, library.state.tenant))


async def _absent(dsn, tenant):
    from pneuma_knowledge_service.adapters.postgres import PostgresStore

    store = PostgresStore(dsn)
    await store.open()
    try:
        return await store.get_user_profile(tenant) is None
    finally:
        await store.aclose()


def test_status_derives_profile_as_not_done_while_the_engine_file_is_the_placeholder(
    home, make_library, monkeypatch
):
    """An unchanged template is unstated without needing to ask the persisted record."""
    library = make_library()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        raise AssertionError("the record is not worth asking while the file names nobody")

    monkeypatch.setattr(status.subprocess, "run", run)
    assert status.profile_settled(home, library) is None
    assert calls == []


@pytest.mark.parametrize("industry", ["tech", "other"])
def test_declared_industry_without_a_name_persists_as_owner(home, make_library, fake_store, industry):
    library = make_library()
    (library.engine_dir / "persona/profile.yaml").write_text(f"industry: {industry}\n")
    assert persist_owner_profile(home, library)
    written = fake_store.made[-1].written
    assert written["source"] == "user"
    assert written["display_name"] == ""
    assert written["provenance"]["industry"] == "owner"
    assert written["provenance"]["display_name"] == "placeholder"
    assert not is_placeholder(written)


@pytest.mark.parametrize("marker,expected", [("owner", True), ("inferred", None)])
def test_profile_settled_accepts_nameless_declarations_but_not_inferences(
    home, make_library, monkeypatch, marker, expected
):
    library = make_library()
    path = library.engine_dir / "persona/profile.yaml"
    path.write_text("industry: tech\n")
    payload = {"profile": {"industry": "tech", "provenance": {"industry": marker}}, "placeholder": False}
    monkeypatch.setattr(status.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout=json.dumps(payload)))
    assert status.profile_settled(home, library) is expected
    # An inference in the engine file is also unsettled, even if the record is older.
    path.write_text("industry: tech\nprovenance:\n  industry: inferred\n")
    assert status.profile_settled(home, library) is None
