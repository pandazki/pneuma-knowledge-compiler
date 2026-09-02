"""A pack's manifest is written with the pack, and it is what a later ask admits against.

The manifest cannot be recovered from a stored briefing: by then the pack is text, and text
cannot say whether a `[cite: …]` inside it is a marker a renderer printed or a line the
source quotes. So the BUILD records it and the row keeps it, in the same statement as the
text it describes — and the ask route hands exactly that back to the lane.

A row written before the column existed carries none. Its ask then admits no citation
against the pack at all, which is the honest reading of "nobody recorded what this pack
showed" — the alternative is inventing provenance for an answer, which is the failure this
whole mechanism exists to make impossible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_core.recall.briefing import AskAnswer
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.api.routes import v1

OWNER = "u-brief-manifest-route"
SOURCE = "s-1"
BRIEFING_ID = "b3a7f0"
PACK = "# Briefing\n\n- [第一章] 报价单在周五定稿。\n"


def _source() -> NormalizedSource:
    raw = RawSource(
        source_id=SourceId(SOURCE),
        user_id=UserId(OWNER),
        kind="document",
        title="报价单",
        mime="text/plain",
        checksum="x",
        created_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    return NormalizedSource(
        raw=raw,
        blocks=[
            NormalizedBlock(index=0, text="报价单在周五定稿。", section_path=["第一章"]),
            NormalizedBlock(index=1, text="第二段。", section_path=["第一章"]),
        ],
        structure=StructureMap(
            sections=[SectionSpan(path=["第一章"], start_block=0, end_block=1)]
        ),
    )


class _Store:
    """The briefing half of the store port plus the content face the build's anchoring reads
    through. Round-trips what it was handed, so what a GET reads is what a POST wrote."""

    def __init__(self, rows: dict[tuple[str, str], dict[str, Any]] | None = None) -> None:
        self.rows = dict(rows or {})
        self.created: list[dict[str, Any]] = []

    async def get_briefing(self, user_id: UserId, briefing_id: str):
        return self.rows.get((str(user_id), briefing_id))

    async def create_briefing(
        self,
        user_id: UserId,
        briefing_id: str,
        scope: dict[str, Any],
        snapshot_ref: str,
        system_prefix: str,
        stages: list[dict[str, Any]] | None = None,
        pack_manifest: list[dict[str, str]] | None = None,
    ) -> None:
        row = {
            "briefing_id": briefing_id,
            "scope": scope,
            "snapshot_ref": snapshot_ref,
            "system_prefix": system_prefix,
            "created_at": datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
            "stages": stages or [],
            "pack_manifest": pack_manifest or [],
        }
        self.created.append(row)
        self.rows[(str(user_id), briefing_id)] = row

    async def get(self, user_id, source_id):  # noqa: ANN001
        if str(source_id) == SOURCE:
            return _source()
        raise KeyError(source_id)


class _Canonical:
    async def snapshots(self, user_id):  # noqa: ANN001
        return []

    async def list(self, user_id, at=None):  # noqa: ANN001
        return []


def _client(store: _Store) -> httpx.AsyncClient:
    app = create_app()
    app.state.ctx = SimpleNamespace(
        store=store,
        canonical=_Canonical(),
        lexical=None,
        vectors=None,
        embeddings=None,
        settings=SimpleNamespace(briefing_citation_alias=False),
        user_info=SimpleNamespace(get_profile=None),
        get_chat_model=lambda role: None,
        langfuse_handler=lambda: None,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _none():
    return None


@pytest.mark.asyncio
async def test_the_build_stores_what_the_pack_showed_beside_the_pack():
    store = _Store()
    async with _client(store) as client:
        built = await client.post(
            f"/v1/users/{OWNER}/briefings", json={"source_ids": [SOURCE]}
        )

    assert built.status_code == 200, built.text
    stored = store.created[0]["pack_manifest"]
    # The raw excerpt the pack inlined, at the block it came from — an address nothing in
    # the rendered text carries, so only the build could have recorded it.
    assert {"kind": "window", "ref": f"{SOURCE} ¶0", "path": ""} in stored


@pytest.mark.asyncio
async def test_the_ask_hands_the_lane_the_manifest_the_row_kept(monkeypatch):
    seen: dict[str, Any] = {}

    async def fake_ask(briefing, question, **kwargs):  # noqa: ANN001, ARG001
        seen["manifest"] = briefing.pack_manifest
        return AskAnswer(answer="ok", citations=(), verbatim_fetches=(), token_usage={})

    monkeypatch.setattr(v1, "briefing_ask", fake_ask)
    monkeypatch.setattr(v1, "_render_profile", lambda ctx, user: _none())

    store = _Store()
    async with _client(store) as client:
        built = await client.post(
            f"/v1/users/{OWNER}/briefings", json={"source_ids": [SOURCE]}
        )
        briefing_id = built.json()["briefing_id"]
        asked = await client.post(
            f"/v1/users/{OWNER}/briefings/{briefing_id}/ask",
            json={"question": "报价单什么时候定稿？"},
        )

    assert asked.status_code == 200, asked.text
    kept = store.rows[(OWNER, briefing_id)]["pack_manifest"]
    assert kept  # precondition: this pack showed something
    assert [
        {"kind": r.kind, "ref": r.ref, "path": r.path} for r in seen["manifest"]
    ] == kept


@pytest.mark.asyncio
async def test_a_briefing_stored_before_the_manifest_existed_admits_nothing(monkeypatch):
    """No backfill, and no guess. An older row's ask carries an empty manifest, so every
    citation it writes fails admission — the record says the pack's evidence is unknown
    rather than pretending to know it."""
    seen: dict[str, Any] = {}

    async def fake_ask(briefing, question, **kwargs):  # noqa: ANN001, ARG001
        seen["manifest"] = briefing.pack_manifest
        return AskAnswer(answer="ok", citations=(), verbatim_fetches=(), token_usage={})

    monkeypatch.setattr(v1, "briefing_ask", fake_ask)
    monkeypatch.setattr(v1, "_render_profile", lambda ctx, user: _none())

    store = _Store(
        {
            (OWNER, BRIEFING_ID): {
                "briefing_id": BRIEFING_ID,
                "scope": {"source_ids": [SOURCE]},
                "snapshot_ref": "9f1c2d",
                "system_prefix": PACK,
                "created_at": None,
                "stages": [],
            }
        }
    )
    async with _client(store) as client:
        asked = await client.post(
            f"/v1/users/{OWNER}/briefings/{BRIEFING_ID}/ask", json={"question": "?"}
        )

    assert asked.status_code == 200, asked.text
    assert seen["manifest"] == ()


@pytest.mark.asyncio
async def test_a_budget_of_zero_or_less_is_refused_at_the_route():
    """The other end of the same rule. A non-positive budget is not a small pack: the cut
    shows nothing or nearly everything, and the manifest is taken against a boundary the
    emitted text never had — a pack in front of the model with no admitted address in it.
    The route names the field rather than letting it become a 500 one layer down."""
    store = _Store()
    async with _client(store) as client:
        refused = await client.post(
            f"/v1/users/{OWNER}/briefings",
            json={"source_ids": [SOURCE], "budget_chars": -5},
        )
        zero = await client.post(
            f"/v1/users/{OWNER}/briefings",
            json={"source_ids": [SOURCE], "budget_chars": 0},
        )

    assert refused.status_code == 422, refused.text
    assert zero.status_code == 422, zero.text
    assert "budget_chars" in refused.text
    assert store.created == []  # nothing was built, so nothing was stored
