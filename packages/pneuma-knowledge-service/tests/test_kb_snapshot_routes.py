"""The recall route's read plane: which tenant answers, which ref canonical reads, what is echoed.

Snapshot support on the read path is one substitution — swap the retrieval tenant, pin
canonical to the recorded commit — so that substitution is precisely what these tests assert.
The lanes themselves are monkeypatched: their behavior is covered against fake ports in core,
and what could silently go wrong HERE is routing (asking the live base while claiming to answer
over a snapshot, or reading canonical from the frozen tenant's non-existent repo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_service.api.routes import v1 as v1_module
from pneuma_knowledge_service.api.routes.v1 import (
    RecallIn,
    post_compile,
    recall,
)
from pneuma_knowledge_service.snapshot_tenant import (
    SnapshotTenantWriteError,
    snapshot_tenant_id,
)

OWNER = "u-plane-owner"
_SNAPSHOT_ID = "0123456789abcdef0123456789abcdef"
_FROZEN = datetime(2026, 3, 1, 9, 30, tzinfo=timezone.utc)


@dataclass
class _FakeFastAnswer:
    answer: str = "答案"
    used_claims: tuple = ()
    used_windows: tuple = ()
    used_episode_summaries: tuple = field(
        default_factory=lambda: (
            SimpleNamespace(
                source_id="src-episode",
                block_start=3,
                block_end=8,
                text="Weekend kayaking and safety planning. Caroline discussed equipment.",
                score=0.75,
                source_title="Saturday conversation",
                source_occurred_on="2025-06-14",
                section_path=("Caroline", "weekend"),
            ),
        )
    )
    citation_handles: dict = field(default_factory=dict)
    glance_chars: int = 0
    expanded_documents: tuple = ()
    glance_degraded: str | None = None
    image_count: int = 0
    image_mode: str = "caption"
    token_usage: dict = field(default_factory=lambda: {"total_tokens": 3})


def _row(status: str = "ready", label: str = "before the reorg") -> dict:
    return {
        "snapshot_id": _SNAPSHOT_ID,
        "label": label,
        "tenant_id": str(snapshot_tenant_id(_SNAPSHOT_ID)),
        "canonical_ref": "sha-frozen",
        "status": status,
        "counts": {"sources": 2, "claims": 1},
        "detail": "pg went away" if status == "failed" else None,
        "created_at": _FROZEN,
        "ready_at": _FROZEN if status == "ready" else None,
    }


def _request(row: dict | None) -> SimpleNamespace:
    """A Request stub carrying only what the route reads off it (`app.state.ctx`)."""
    canonical_reads: list[tuple[str, SnapshotRef | None]] = []

    async def snapshots(user):  # noqa: ANN001
        return [SnapshotRef(ref="sha-head")]

    async def canonical_list(user, *, at=None):  # noqa: ANN001
        canonical_reads.append((str(user), at))
        return []  # empty → `_glance_inputs` returns {} and the lane runs glance-less

    async def get_kb_snapshot(user, ref):  # noqa: ANN001
        if row is None:
            return None
        return row if ref in (row["snapshot_id"], row["label"]) else None

    async def undigested(user):  # noqa: ANN001
        return []

    async def enqueue(user, kind, payload):  # noqa: ANN001
        return "job-1"

    ctx = SimpleNamespace(
        canonical=SimpleNamespace(snapshots=snapshots, list=canonical_list),
        user_info=SimpleNamespace(get_profile=None),
        langfuse_handler=lambda: None,
        lexical=None,
        vectors=None,
        embeddings=None,
        media=object(),
        store=SimpleNamespace(
            get_kb_snapshot=get_kb_snapshot,
            undigested_source_ids=undigested,
            enqueue=enqueue,
        ),
        get_chat_model=lambda role="default": None,
        canonical_reads=canonical_reads,
        # The route forwards the configured retrieval budget + opt-in stages into fast_recall.
        settings=SimpleNamespace(
            recall_claim_candidate_cap=80,
            recall_claim_cap=40,
            recall_window_candidate_cap=60,
            recall_episode_summary_cap=24,
            recall_window_cap=6,
            recall_plan_queries=0,
            recall_rerank_candidates=120,
            recall_answer_style="conversational",
            answer_reasoning_effort="high",
            # The route refuses keyless deployments up front; the stub declares a model
            # so the lanes under test actually run.
            llm_model="scripted:stub",
            llm_model_recall="",
            llm_model_answer="",
            llm_model_deep="",
        ),
        get_reranker=lambda: None,
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))


@pytest.fixture
def captured(monkeypatch):
    """Capture the (user, kwargs) each lane was called with."""
    seen: dict = {}

    async def fake_fast_recall(user, question, **kwargs):  # noqa: ANN001
        seen["user"] = str(user)
        seen["scope"] = kwargs.get("scope")
        seen["image_mode"] = kwargs.get("image_mode")
        seen["media"] = kwargs.get("media")
        seen["reasoning_effort"] = kwargs.get("reasoning_effort")
        return _FakeFastAnswer(
            image_count=2 if kwargs.get("image_mode") == "native" else 0,
            image_mode=kwargs.get("image_mode") or "caption",
        )

    async def fake_rag_recall(user, query, **kwargs):  # noqa: ANN001
        seen["user"] = str(user)
        return []

    monkeypatch.setattr(v1_module, "fast_recall", fake_fast_recall)
    monkeypatch.setattr(v1_module, "rag_recall", fake_rag_recall)
    # The profile block is advisory context; drop it so the stub ctx stays minimal.
    monkeypatch.setattr(v1_module, "_render_profile", lambda ctx, user: _none())
    return seen


async def _none():
    return None


def test_recall_tool_schema_exposes_extensible_original_modality_enum_list():
    field = RecallIn.model_json_schema()["properties"]["include_original_modalities"]
    assert field["type"] == "array"
    # JSON Schema represents today's one-value enum as `const`; widening the Literal later
    # naturally turns it into `enum` without changing the surrounding list-shaped field.
    assert field["items"].get("enum", [field["items"].get("const")]) == ["image"]
    assert "direct visual inspection" in field["description"]
    assert RecallIn(query="q").include_original_modalities == []


async def test_without_a_snapshot_the_owner_answers_and_nothing_is_pinned(captured):
    request = _request(_row())
    out = await recall(OWNER, RecallIn(query="q", mode="fast"), request)
    assert captured["user"] == OWNER
    assert captured["scope"] is None
    assert captured["image_mode"] == "caption"
    assert captured["media"] is None
    assert captured["reasoning_effort"] == "high"
    assert out.snapshot is None
    assert len(out.used_episode_summaries) == 1
    summary = out.used_episode_summaries[0]
    assert summary.source_id == "src-episode"
    assert (summary.block_start, summary.block_end) == (3, 8)
    assert summary.source_title == "Saturday conversation"
    assert summary.source_occurred_on == "2025-06-14"
    assert summary.section_path == ["Caroline", "weekend"]
    assert summary.derived is True
    assert summary.verbatim is False
    # canonical read against the owner, at HEAD — today's behavior exactly.
    assert request.app.state.ctx.canonical_reads == [(OWNER, None)]


async def test_original_modalities_are_an_explicit_query_tool_choice(captured):
    request = _request(_row())
    out = await recall(
        OWNER,
        RecallIn(
            query="Does the painting contain a dog?",
            mode="fast",
            include_original_modalities=["image"],
        ),
        request,
    )

    assert captured["image_mode"] == "native"
    assert captured["media"] is request.app.state.ctx.media
    assert out.included_original_modalities == ["image"]
    assert out.original_modality_counts == {"image": 2}


async def test_raw_rag_hits_reject_original_modality_delivery(captured):
    request = _request(_row())
    with pytest.raises(HTTPException, match="fast/deep answering modes") as exc:
        await recall(
            OWNER,
            RecallIn(
                query="Does the painting contain a dog?",
                mode="rag",
                include_original_modalities=["image"],
            ),
            request,
        )
    assert exc.value.status_code == 400


async def test_a_ready_snapshot_swaps_the_retrieval_tenant_and_pins_canonical(captured):
    request = _request(_row())
    out = await recall(
        OWNER, RecallIn(query="q", mode="fast", snapshot="before the reorg"), request
    )
    # L0/L1/L2/claims answer from the frozen tenant …
    assert captured["user"] == str(snapshot_tenant_id(_SNAPSHOT_ID))
    # … while canonical is read from the OWNER's repo at the pinned commit (the frozen tenant
    # has no git repo of its own, by design).
    assert request.app.state.ctx.canonical_reads == [
        (OWNER, SnapshotRef(ref="sha-frozen"))
    ]
    # The prompt is told which snapshot is open.
    assert captured["scope"].label == "before the reorg"
    assert captured["scope"].created_at == _FROZEN
    # And the answer says which plane produced it — a client is never left guessing.
    assert out.snapshot is not None
    assert out.snapshot.snapshot_id == _SNAPSHOT_ID
    assert out.snapshot.canonical_ref == "sha-frozen"
    assert out.snapshot.created_at == _FROZEN.isoformat()


async def test_the_rag_lane_is_scoped_by_the_same_substitution(captured):
    request = _request(_row())
    await recall(
        OWNER, RecallIn(query="q", mode="rag", snapshot=_SNAPSHOT_ID), request
    )
    assert captured["user"] == str(snapshot_tenant_id(_SNAPSHOT_ID))


async def test_an_unknown_snapshot_is_a_404_not_a_silent_fallback_to_head(captured):
    # The failure mode this guards: answering over the live base while the caller believes it
    # asked history. That would present today's knowledge as the past.
    with pytest.raises(HTTPException) as excinfo:
        await recall(
            OWNER, RecallIn(query="q", mode="fast", snapshot="typo"), _request(None)
        )
    assert excinfo.value.status_code == 404
    assert "user" not in captured  # no lane ran


@pytest.mark.parametrize("status", ["creating", "failed"])
async def test_an_unready_snapshot_is_a_409(captured, status):
    with pytest.raises(HTTPException) as excinfo:
        await recall(
            OWNER,
            RecallIn(query="q", mode="fast", snapshot=_SNAPSHOT_ID),
            _request(_row(status=status)),
        )
    assert excinfo.value.status_code == 409
    assert status in str(excinfo.value.detail) or "failed" in str(excinfo.value.detail)
    assert "user" not in captured


async def test_compile_refuses_a_snapshot_tenant():
    with pytest.raises(SnapshotTenantWriteError):
        await post_compile(str(snapshot_tenant_id(_SNAPSHOT_ID)), _request(None))


async def test_compile_still_works_for_a_real_owner():
    out = await post_compile(OWNER, _request(None))
    assert out.source_ids == []


async def test_a_keyless_deployment_refuses_the_answering_lanes_with_a_clear_503(captured):
    # Browsing endpoints stay fully served keyless; the answering lanes are the one thing
    # that cannot run. The failure mode this guards: handing an empty model spec to the
    # model builder and surfacing its TypeError as a bare 500.
    request = _request(_row())
    request.app.state.ctx.settings.llm_model = ""
    with pytest.raises(HTTPException) as excinfo:
        await recall(OWNER, RecallIn(query="q", mode="fast"), request)
    assert excinfo.value.status_code == 503
    assert "keyless" in excinfo.value.detail
    assert "user" not in captured  # no lane ran
