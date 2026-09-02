"""The briefing lane's timings on the wire: built, persisted, read back, and asked.

A build is mechanical work an owner waits on, and an ask is an agentic loop — two different
shapes, both reported as `stages`. What the routes have to get right is narrow and mechanical:

  * a build's whole vocabulary reaches `BriefingOut`, complete, with the half this scope did
    not have marked `skipped` rather than dropped;
  * the SAME list is what gets persisted — stored in the wire shape, so reading a briefing
    back is a parse and never a re-derivation (a build happens once and cannot be re-measured
    afterwards), and the detail endpoint hands it back unchanged;
  * a briefing stored before the column existed reads back as an empty list — "not recorded"
    is not "took no time", and the route never invents zeros to fill the gap;
  * an ask's interleaving reaches `AskOut` beside the answer it explains.

The store is stubbed at the port; the ask route's core call is replaced at the route's own
seam, because what is under test here is the mapping onto the response, not the loop (core's
`test_briefing_stage_timing.py` owns that).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.briefing import AskAnswer
from pneuma_knowledge_core.recall.stage_timing import StageTiming
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.api.routes import v1

OWNER = "u-brief-stages"
BRIEFING_ID = "b1a5ed"
PACK = "# Briefing\n\nc:0001 — the rollout moved to Friday. [cite: s-1 ¶2-3]\n"

BUILD_STAGES = [
    {"name": "retrieve", "ms": 340, "status": "ran", "detail": None},
    {"name": "retrieve.claims", "ms": 210, "status": "ran", "detail": None},
    {"name": "retrieve.passages", "ms": 130, "status": "ran", "detail": None},
    {"name": "expand", "ms": 480, "status": "ran", "detail": None},
    {"name": "pack", "ms": 12, "status": "ran", "detail": None},
    {"name": "total", "ms": 840, "status": "ran", "detail": None},
]


class _Store:
    """The briefing half of the store port, user-scoped exactly as Postgres' WHERE clause is,
    and keeping what it was handed so the persisted shape can be asserted."""

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
        self.created.append(
            {
                "user_id": str(user_id),
                "briefing_id": briefing_id,
                "scope": scope,
                "snapshot_ref": snapshot_ref,
                "system_prefix": system_prefix,
                "stages": stages,
            }
        )
        # Round-trip: the row a later GET reads is exactly what was stored, JSON and all.
        self.rows[(str(user_id), briefing_id)] = {
            "briefing_id": briefing_id,
            "scope": scope,
            "snapshot_ref": snapshot_ref,
            "system_prefix": system_prefix,
            "created_at": datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
            "stages": stages or [],
        }

    # --- the content-store face the build's source anchoring reads through -------------
    async def get(self, user_id, source_id):  # noqa: ANN001
        raise KeyError(source_id)


class _Canonical:
    async def snapshots(self, user_id):  # noqa: ANN001
        return []

    async def list(self, user_id, at=None):  # noqa: ANN001
        return []


def _ctx(store: _Store) -> SimpleNamespace:
    """Enough context for a build: no indexes registered, so the query half never runs — which
    is the point of one of the tests below."""
    return SimpleNamespace(
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


def _client(store: _Store) -> httpx.AsyncClient:
    app = create_app()
    app.state.ctx = _ctx(store)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_a_build_puts_its_whole_vocabulary_on_the_wire_and_into_the_row():
    store = _Store()
    async with _client(store) as client:
        response = await client.post(
            f"/v1/users/{OWNER}/briefings", json={"source_ids": ["s-1"]}
        )

    assert response.status_code == 200, response.text
    stages = response.json()["stages"]
    assert [s["name"] for s in stages] == [
        "retrieve",
        "retrieve.claims",
        "retrieve.passages",
        "expand",
        "pack",
        "total",
    ]
    # No indexes are registered here, so the query half genuinely did not happen — and says so
    # rather than vanishing from the strip.
    skipped = {s["name"] for s in stages if s["status"] == "skipped"}
    assert skipped == {"retrieve", "retrieve.claims", "retrieve.passages"}
    assert all(s["ms"] == 0 for s in stages if s["status"] == "skipped")
    # Persisted verbatim in the same shape, so reading it back is a parse.
    assert store.created[0]["stages"] == stages


@pytest.mark.asyncio
async def test_the_stored_breakdown_reads_back_unchanged():
    store = _Store()
    async with _client(store) as client:
        built = await client.post(
            f"/v1/users/{OWNER}/briefings", json={"source_ids": ["s-1"]}
        )
        briefing_id = built.json()["briefing_id"]
        detail = await client.get(f"/v1/users/{OWNER}/briefings/{briefing_id}")

    assert detail.status_code == 200, detail.text
    assert detail.json()["stages"] == built.json()["stages"]


@pytest.mark.asyncio
async def test_a_briefing_stored_before_builds_were_measured_reports_nothing():
    """An older row has no breakdown. It reads back empty — never as a strip of zeros, which
    would say the build was instant when what is true is that nobody measured it."""
    store = _Store(
        {
            (OWNER, BRIEFING_ID): {
                "briefing_id": BRIEFING_ID,
                "scope": {"query": "rollout"},
                "snapshot_ref": "9f1c2d",
                "system_prefix": PACK,
                "created_at": datetime(2026, 8, 26, 10, 15, tzinfo=UTC),
            }
        }
    )
    async with _client(store) as client:
        detail = await client.get(f"/v1/users/{OWNER}/briefings/{BRIEFING_ID}")

    assert detail.status_code == 200
    assert detail.json()["stages"] == []
    # The pack itself is untouched by any of this.
    assert detail.json()["text"] == PACK


@pytest.mark.asyncio
async def test_a_stored_breakdown_survives_the_row_verbatim():
    """The dicts come back out of jsonb, not out of a dataclass — the detail route parses that
    shape rather than re-deriving anything."""
    store = _Store(
        {
            (OWNER, BRIEFING_ID): {
                "briefing_id": BRIEFING_ID,
                "scope": {},
                "snapshot_ref": "9f1c2d",
                "system_prefix": PACK,
                "created_at": None,
                "stages": BUILD_STAGES,
            }
        }
    )
    async with _client(store) as client:
        detail = await client.get(f"/v1/users/{OWNER}/briefings/{BRIEFING_ID}")

    # A row written before previews existed comes back with `preview: None` — the field is
    # absent from the stored dict and is never invented, which is the same rule the `stages`
    # column follows for a briefing built before it was measured at all.
    assert detail.json()["stages"] == [{**s, "preview": None} for s in BUILD_STAGES]


@pytest.mark.asyncio
async def test_an_ask_carries_the_loops_interleaving_beside_its_answer(monkeypatch):
    """The route's own job: whatever shape the loop reported, it reaches `AskOut` unflattened
    and in order — `finalize`'s degraded reason included."""
    ask_stages = (
        StageTiming(name="turn:1", ms=1180),
        StageTiming(name="tool:search_knowledge", ms=340),
        StageTiming(name="tool:fetch_verbatim", ms=12, status="degraded", detail="s-gone"),
        StageTiming(name="turn:2", ms=640),
        StageTiming(name="finalize", ms=1120, status="degraded", detail="budget"),
        StageTiming(name="total", ms=3300),
    )

    async def fake_ask(briefing, question, **kwargs):  # noqa: ANN001, ARG001
        return AskAnswer(
            answer="the answer",
            citations=(),
            verbatim_fetches=({"source_id": "s-gone", "error": "missing", "ms": 12},),
            token_usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            stages=ask_stages,
        )

    monkeypatch.setattr(v1, "briefing_ask", fake_ask)
    monkeypatch.setattr(v1, "_render_profile", lambda ctx, user: _none())

    store = _Store(
        {
            (OWNER, BRIEFING_ID): {
                "briefing_id": BRIEFING_ID,
                "scope": {"source_ids": ["s-1"]},
                "snapshot_ref": "9f1c2d",
                "system_prefix": PACK,
                "created_at": None,
                "stages": BUILD_STAGES,
            }
        }
    )
    async with _client(store) as client:
        asked = await client.post(
            f"/v1/users/{OWNER}/briefings/{BRIEFING_ID}/ask", json={"question": "what?"}
        )

    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert [s["name"] for s in body["stages"]] == [
        "turn:1",
        "tool:search_knowledge",
        "tool:fetch_verbatim",
        "turn:2",
        "finalize",
        "total",
    ]
    by_name = {s["name"]: s for s in body["stages"]}
    assert by_name["finalize"]["status"] == "degraded"
    assert by_name["finalize"]["detail"] == "budget"
    # The record and the stage measured the same fetch, and both say it failed.
    assert by_name["tool:fetch_verbatim"]["status"] == "degraded"
    assert body["verbatim_fetches"][0]["ms"] == by_name["tool:fetch_verbatim"]["ms"]
    # A build's stages are the briefing's, not the ask's: the two never bleed into each other.
    assert all(not s["name"].startswith("turn:") for s in BUILD_STAGES)


async def _none():
    return None
