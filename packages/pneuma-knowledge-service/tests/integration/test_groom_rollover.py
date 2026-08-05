"""Document rollover end-to-end over real middleware: compile → groom → projection.

One tenant, one oversized document, no HTTP. The compile writes a document past the size
threshold; the worker enqueues a groom on the SAME per-user queue and drains it in the same
sweep; the rollover commits an archive volume plus a rewritten active document, and the L3
projection follows the claims to their new path.

What this covers that the unit tests cannot: that the trigger actually fires off a real
compile, that the groom rides the real queue serially behind it, that git accepts the two
files as one commit, that the claim projection re-keys the moved claims (the archived claim
is queryable at the VOLUME path, not at the document it left), that the archive shows up as
a graph edge, and that the active document really did get smaller.

Never run against a live worker or a tenant an experiment is using — this claims jobs.
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from pneuma_knowledge_core.canonical_glance import render_canonical_glance
from pneuma_knowledge_core.compile.rollover import (
    ARCHIVED_FROM_KEY,
    VOLUME_NUMBER_KEY,
    _OverviewDraft,
    _OverviewPointDraft,
)
from pneuma_knowledge_core.domain.ids import ANCHOR_MARK_RE, UserId, extract_anchors
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.dataset import build_dataset
from pneuma_knowledge_service.groom_service import GROOM_JOB_KIND
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_user

ACTIVE = "work/products/aurora-planner.md"
VOLUME = "work/products/aurora-planner/a01.md"


def _open(url: str, default: int) -> bool:
    p = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((p.hostname, p.port or default), timeout=1.5):
            return True
    except OSError:
        return False


@pytest.fixture
async def ctx(tmp_path):
    # Small thresholds so a realistic little document crosses them; evolve off so the only
    # thing the compile can trigger is the rollover under test.
    s = Settings(
        canonical_root=str(tmp_path / "canonical"),
        evolve_auto_trigger=False,
        rollover_threshold_chars=900,
        rollover_keep_recent_chars=250,
    )
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    c = await build_context(s)
    yield c
    await c.aclose()


def _turn(speaker: str, text: str) -> ConversationTurn:
    return ConversationTurn(
        speaker=speaker, text=text, at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    )


class _CardModel:
    """Answers the history-card call, grounded in the ids it is actually shown.

    Claim anchors are content-addressed, so a fixed script could not name one — this reads the
    archived material out of the prompt exactly as a real model would, which is also the
    cheapest way to prove the archived entries reach the call with their ids intact.
    """

    def __init__(self) -> None:
        self.seen_ids: list[str] = []

    def with_structured_output(self, schema, include_raw=False):  # noqa: ANN001, ARG002
        return self

    async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
        self.seen_ids = ANCHOR_MARK_RE.findall(str(messages[-1].content))
        return {
            "parsed": _OverviewDraft(
                points=[
                    _OverviewPointDraft(
                        text="Aurora's early delivery sprints closed out the launch checklist.",
                        anchors=self.seen_ids[:3],
                    )
                ]
            ),
            "raw": None,
        }


async def test_compile_triggers_a_rollover_that_moves_claims_and_reprojects(ctx):
    user = UserId(f"u-it-groom-{uuid.uuid4().hex[:8]}")
    result = await ingest_conversation(
        ctx,
        user,
        [
            _turn("Ada", f"第 {i} 轮：Aurora 的发布清单又推进了一格。")
            for i in range(14)
        ],
        title="Aurora 周会",
    )
    sid = str(result.source_id)

    # One create_document whose body is comfortably past the 900-char threshold.
    rows = "\n".join(
        f"- 第 {i} 个 Aurora 发布清单进展：本轮确认了下一步的验收口径。[cite: {sid} ¶{i}]"
        for i in range(14)
    )
    compile_model = ScriptedChatModel(
        turns=[
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": ACTIVE,
                        "frontmatter": {"type": "product", "slug": "aurora-planner"},
                        "body": f"# Aurora planner\n\n## 交付\n\n{rows}",
                    },
                },
                {"name": "finish_compile"},
            ]
        ]
    )
    card_model = _CardModel()
    ctx.get_chat_model = lambda role="default": card_model

    await ctx.store.enqueue(user, "compile", {"source_ids": [sid]})
    # index job, compile job, and the groom the compile enqueues — one serial sweep.
    processed = await drain_user(ctx, compile_model, load_skill_base("v1"), user)
    assert processed >= 3

    jobs = await ctx.store.list_jobs(user)
    groom = [j for j in jobs if j["kind"] == GROOM_JOB_KIND]
    assert len(groom) == 1, jobs
    assert groom[0]["ok"] is True, groom[0]["detail"]
    assert '"volume":"work/products/aurora-planner/a01.md"' in groom[0]["detail"]

    docs = await ctx.canonical.list(user)
    by_path = {d.path: d for d in docs}
    # one file plus one same-name directory — git carries the subdirectory without ceremony
    assert set(by_path) == {ACTIVE, VOLUME}
    assert VOLUME.startswith(ACTIVE.removesuffix(".md") + "/")

    # ---- the volume is a frozen, self-describing document -------------------------------
    volume = by_path[VOLUME]
    assert volume.frontmatter[ARCHIVED_FROM_KEY] == ACTIVE
    assert volume.frontmatter[VOLUME_NUMBER_KEY] == "01"
    assert volume.frontmatter["type"] == "product"

    # ---- the active document kept its path and shrank ------------------------------------
    active = by_path[ACTIVE]
    assert active.doc_id  # same path ⇒ same derived doc_id ⇒ inbound links still resolve
    assert active.body.startswith("# Aurora planner")
    assert prompt("compile.groom.overview_heading") in active.body
    assert prompt("compile.groom.volumes_heading") in active.body
    assert "(aurora-planner/a01.md)" in active.body
    assert len(active.body) < len(volume.body)

    # ---- nothing was lost: every original claim anchor is still somewhere ----------------
    committed_anchors = set(extract_anchors(active.body)) | set(extract_anchors(volume.body))
    events = await ctx.store.list_compile_events(user)
    compiled_anchors = {e["anchor"] for e in events if e["type"] == "claim_added"}
    assert compiled_anchors and compiled_anchors <= committed_anchors

    # the card really was grounded in the archive it was shown
    assert set(card_model.seen_ids) & set(extract_anchors(volume.body))

    # ---- the projection followed the claims to their new path ----------------------------
    rows_pg = await ctx.store.list_canonical_claims(user)
    by_anchor = {str(r["anchor"]): str(r["document_path"]) for r in rows_pg}
    for anchor in extract_anchors(volume.body):
        assert by_anchor.get(anchor) == VOLUME
    for anchor in extract_anchors(active.body):
        assert by_anchor.get(anchor) == ACTIVE
    # and the L3 lexical face answers at the volume path, not the one the claims left
    hits = await ctx.lexical.search_claims(user, "Aurora 发布清单", limit=50)
    assert any(h.document_path == VOLUME for h in hits)

    # ---- the archive is a graph edge, and the glance collapses it ------------------------
    dataset = await build_dataset(ctx, user, audit=False)
    ids = {node["path"]: node["id"] for node in dataset["graph"]["nodes"]}
    assert {"source": ids[ACTIVE], "target": ids[VOLUME], "type": "link"} in dataset["graph"][
        "edges"
    ]
    glance = render_canonical_glance(docs, load_skill_base("v1"))
    assert "+1 archived volume(s)" in glance
    assert VOLUME not in glance

    # ---- and a NEXT compile is not tripped up by the volume it must not write --------------
    await ctx.store.enqueue(user, "compile", {"source_ids": [sid]})
    await drain_user(ctx, ScriptedChatModel(turns=[]), load_skill_base("v1"), user)
    follow_up = [j for j in await ctx.store.list_jobs(user) if j["kind"] == "compile"][0]
    assert follow_up["ok"] is True, follow_up["detail"]

    await ctx.store.delete_user(user)
