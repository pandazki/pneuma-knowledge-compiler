"""The edition's own Postgres connection names itself, so a server log line says which
client it served (the library's `wiring.connection_role` does the same for the engine)."""

from __future__ import annotations

import asyncio

import pytest
from pneuma_knowledge_core.domain.ids import UserId

from pkc_personal import library as library_module


class _Stop(Exception):
    """Raised by the stand-in store once it has recorded what it was built with."""


def test_the_profile_writer_names_its_connection(monkeypatch):
    names: list[str | None] = []

    def store(dsn, **kwargs):  # noqa: ANN001, ANN003
        names.append(kwargs.get("application_name"))
        raise _Stop

    monkeypatch.setattr(library_module, "PostgresStore", store)
    with pytest.raises(_Stop):
        asyncio.run(
            library_module._upsert_profile(
                "postgresql://pkc@127.0.0.1:1/pkc", UserId("u-owner"), {}, only_if_missing=False
            )
        )
    assert names == ["pkchome:profile"]
