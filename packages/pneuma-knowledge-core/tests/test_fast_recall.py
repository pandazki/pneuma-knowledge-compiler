"""fast recall: cap + dedup + selector assembly discipline I5 (M4)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import BlockImage, NormalizedSource
from pneuma_knowledge_core.recall.fast import (
    DEFAULT_CLAIM_CANDIDATE_CAP,
    DEFAULT_CLAIM_CAP,
    DEFAULT_EPISODE_SUMMARY_CAP,
    DEFAULT_WINDOW_CANDIDATE_CAP,
    DEFAULT_WINDOW_CAP,
    RecallImage,
    retrieve_claims,
    selector_contract,
    fast_recall,
    selector_messages,
)
from pneuma_knowledge_core.recall.rag import EpisodeSummarySignal, RecallHit
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


@dataclass
class ClaimStub:
    anchor: str
    document_path: str
    text: str
    section_path: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


class FakeClaimIndex:
    """Satisfies both ClaimLexicalIndex + ClaimVectorIndex (search_claims signature)."""

    def __init__(self, claims: list[ClaimStub]) -> None:
        self._claims = claims

    async def search_claims(self, user_id, query_or_embedding, *, limit=40):  # noqa: ANN001
        return self._claims[:limit]


class FakeEmbeddings:
    async def aembed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    async def aembed_documents(self, texts):  # noqa: ANN001
        return [[0.1, 0.2, 0.3] for _ in texts]


@dataclass
class LexHit:
    source_id: SourceId
    block_index: int
    text: str
    score: float = 1.0


@dataclass
class VecHit:
    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    score: float = 1.0


class FakeLexical:
    """Raw L1 LexicalIndex.search — body blocks, NOT claims."""

    def __init__(self, hits: list[LexHit]) -> None:
        self._hits = hits

    async def search(self, user_id, query, *, limit=20):  # noqa: ANN001
        return self._hits[:limit]


class FakeVector:
    """Raw L2 VectorIndex.search — body chunks, NOT claims."""

    def __init__(self, hits: list[VecHit]) -> None:
        self._hits = hits

    async def search(
        self, user_id, embedding, *, limit=20, representation="raw"
    ):  # noqa: ANN001
        return self._hits[:limit] if representation == "raw" else []


def _model(answer: str) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([AIMessage(content=answer)]))


_USER = UserId("u-fast")


def test_generic_fast_defaults_separate_candidate_recall_from_answer_evidence():
    assert DEFAULT_CLAIM_CANDIDATE_CAP == 80
    assert DEFAULT_CLAIM_CAP == 40
    assert DEFAULT_WINDOW_CANDIDATE_CAP == 60
    assert DEFAULT_EPISODE_SUMMARY_CAP == 16
    assert DEFAULT_WINDOW_CAP == 6


async def test_zero_claim_budget_short_circuits_both_indexes_and_embedding():
    class MustNotRun:
        def __getattr__(self, name):  # noqa: ANN001
            raise AssertionError(f"zero claim budget touched {name}")

    assert await retrieve_claims(
        _USER,
        "q",
        claim_lexical=MustNotRun(),
        claim_vectors=MustNotRun(),
        embeddings=MustNotRun(),
        limit=0,
    ) == []


async def test_cap_and_dedup_by_path_and_anchor():
    # lexical surfaces A,B; vector surfaces A,C — A must fuse to a single claim.
    a = ClaimStub("aaaa", "p1", "claim a")
    b = ClaimStub("bbbb", "p1", "claim b")
    c = ClaimStub("cccc", "p1", "claim c")
    lexical = FakeClaimIndex([a, b])
    vector = FakeClaimIndex([a, c])

    result = await fast_recall(
        _USER,
        "q",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=lexical,
        claim_vectors=vector,
        embeddings=FakeEmbeddings(),
        model=_model("最短答案"),
        cap=2,
    )
    anchors = [str(c.anchor) for c in result.used_claims]
    assert len(anchors) == 2  # capped
    assert anchors.count("aaaa") == 1  # deduped across paths
    assert result.answer == "最短答案"
    # A appears on both paths.
    assert set(result.used_claims[0].paths) == {"lexical", "vector"}


async def test_token_usage_carries_cache_fields():
    result = await fast_recall(
        _USER,
        "q",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([ClaimStub("aaaa", "p1", "x")]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=_model("y"),
    )
    for key in ("input_tokens", "output_tokens", "total_tokens", "cache_read", "cache_creation"):
        assert key in result.token_usage


async def test_windows_surface_when_claims_irrelevant_the_jack_regression():
    # Regression: a distill-treated record's compile produced only abstract meta-claims,
    # so the answer face was blind to the real candidate names living in the raw body.
    # fast recall must ALWAYS also retrieve L1/L2 body windows and answer over them.
    real_body = "候选人张三：后端与 SRE 经验 8 年，主导过高可用架构。"
    lexical = FakeLexical([LexHit(SourceId("srcbody1"), 3, real_body)])
    vectors = FakeVector([VecHit(SourceId("srcbody1"), 3, 3, real_body)])

    captured: dict[str, str] = {}

    class CapturingModel(GenericFakeChatModel):
        async def ainvoke(self, messages, *a, **k):  # noqa: ANN001, ANN002
            captured["human"] = messages[1].content
            return await super().ainvoke(messages, *a, **k)

    model = CapturingModel(messages=iter([AIMessage(content="张三")]))

    result = await fast_recall(
        _USER,
        "有哪些候选人适合后端或SRE岗位",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([]),  # 22 abstract meta-claims → nothing relevant
        claim_vectors=FakeClaimIndex([]),
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        model=model,
    )

    # 1) windows surfaced into the Human turn payload the model answered over.
    assert "# raw excerpts" in captured["human"]
    assert real_body in captured["human"]
    # the pre-hook aliases the real source id to a short query-local handle for the LLM.
    assert "[cite: s01 ¶3-3]" in captured["human"]
    assert "srcbody1" not in captured["human"]  # the real id is hidden from the model
    # Assembly order: evidence sections first, the live question LAST (attention-hot tail).
    human = captured["human"]
    assert (
        human.index("# claim notes")
        < human.index("# raw excerpts")
        < human.index("Owner input:")
    )
    assert human.rstrip().endswith("有哪些候选人适合后端或SRE岗位")
    # 2) windows surfaced into the returned payload (drill-downable).
    assert [(w.block_start, w.block_end) for w in result.used_windows] == [(3, 3)]
    assert result.used_windows[0].source_id == SourceId("srcbody1")
    # claims were empty, yet the body carried the answer.
    assert result.used_claims == ()
    assert result.answer == "张三"


async def test_episode_summaries_reach_answer_with_metadata_beside_fewer_verbatim_windows(
    monkeypatch,
):
    candidates = [
        RecallHit(
            source_id=SourceId(f"src-{index}"),
            block_start=index,
            block_end=index,
            text=f"verbatim-{index}",
            paths=("vector",),
            score=1.0 - index / 100,
            representations=("raw", "episode"),
            episode_summaries=(
                EpisodeSummarySignal(
                    source_id=SourceId(f"src-{index}"),
                    block_start=index,
                    block_end=index,
                    text=(
                        f"[episode title] Episode {index}\n"
                        f"[episode description] Dense factual summary {index}"
                    ),
                ),
            ),
        )
        for index in range(10)
    ]
    seen: dict[str, Any] = {}

    async def fake_retrieve_windows(*args, **kwargs):  # noqa: ANN002, ANN003
        seen["retrieval_limit"] = kwargs["limit"]
        return candidates[: kwargs["limit"]]

    from pneuma_knowledge_core.recall import fast as fast_module

    monkeypatch.setattr(fast_module, "retrieve_windows", fake_retrieve_windows)

    sources = {
        f"src-{index}": NormalizedSource.model_validate(
            {
                "raw": {
                    "source_id": f"src-{index}",
                    "user_id": str(_USER),
                    "kind": "im",
                    "origin": "mock",
                    "title": f"Conversation {index}",
                    "mime": "application/json",
                    "checksum": f"fixture-{index}",
                    "created_at": "2026-07-20T12:00:00Z",
                    "meta": {"occurred_on": f"2026-07-{index + 1:02d}"},
                },
                "blocks": [
                    {
                        "index": index,
                        "text": f"verbatim-{index}",
                        "section_path": ["session", str(index)],
                    }
                ],
                "structure": {"sections": []},
            }
        )
        for index in range(10)
    }

    class Content:
        async def get(self, user_id, source_id):  # noqa: ANN001
            return sources[str(source_id)]

    class AnswerModel(GenericFakeChatModel):
        async def ainvoke(self, messages, *args, **kwargs):  # noqa: ANN001, ANN002
            seen["answer_human"] = messages[1].content
            return AIMessage(content="answer")

    result = await fast_recall(
        _USER,
        "Which episode matters?",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        lexical=FakeLexical([]),
        vectors=FakeVector([]),
        embeddings=FakeEmbeddings(),
        model=AnswerModel(messages=iter(())),
        answer_model=AnswerModel(messages=iter(())),
        content=Content(),
        window_candidate_cap=10,
        episode_summary_cap=4,
        window_cap=2,
    )

    assert seen["retrieval_limit"] == 10
    assert "# derived episode summaries (4)" in seen["answer_human"]
    for index in range(4):
        assert f"Dense factual summary {index}" in seen["answer_human"]
        assert f"Conversation {index}" in seen["answer_human"]
        assert f"2026-07-{index + 1:02d}" in seen["answer_human"]
    assert "Dense factual summary 4" not in seen["answer_human"]
    assert [str(window.source_id) for window in result.used_windows] == ["src-0", "src-1"]
    assert "verbatim-0" in seen["answer_human"]
    assert "verbatim-1" in seen["answer_human"]
    assert "verbatim-2" not in seen["answer_human"]
    assert len(result.used_episode_summaries) == 4
    assert result.window_candidates == 10


async def test_native_images_aligned_to_recalled_windows_reach_the_answer_model():
    image_bytes = b"\xff\xd8\xffnative-recall-image"
    digest = hashlib.sha256(image_bytes).hexdigest()
    source = NormalizedSource.model_validate(
        {
            "raw": {
                "source_id": "src-image",
                "user_id": str(_USER),
                "kind": "im",
                "origin": "mock",
                "title": "image conversation",
                "mime": "application/json",
                "checksum": "fixture",
                "created_at": "2026-07-20T12:00:00Z",
            },
            "blocks": [
                {
                    "index": 4,
                    "text": "Caroline shared a picture.",
                    "images": [
                        {
                            "image_id": "image-1",
                            "mime_type": "image/jpeg",
                            "sha256": digest,
                            "size_bytes": len(image_bytes),
                            "storage_key": "tenant/image-1",
                            "derived": [
                                {
                                    "kind": "caption",
                                    "text": "a dog walking past a wall with a painting",
                                    "producer": "fixture-captioner",
                                }
                            ],
                        }
                    ],
                }
            ],
            "structure": {"sections": []},
        }
    )

    class Content:
        async def get(self, user_id, source_id):  # noqa: ANN001
            assert user_id == _USER
            assert source_id == SourceId("src-image")
            return source

        async def fetch(self, user_id, source_id, locator):  # noqa: ANN001
            return source.blocks[0].text

    class Media:
        async def get(self, user_id, storage_key):  # noqa: ANN001
            assert user_id == _USER
            assert storage_key == "tenant/image-1"
            return image_bytes

    captured: dict[str, Any] = {}

    class CapturingModel(GenericFakeChatModel):
        async def ainvoke(self, messages, *args, **kwargs):  # noqa: ANN001, ANN002
            captured["human"] = messages[1].content
            captured["metadata"] = kwargs["config"]["metadata"]
            return AIMessage(content="A dog, walking past a painted wall. [cite: s01 ¶4-4]")

    hit = "Caroline shared a picture. a dog walking past a wall with a painting"
    result = await fast_recall(
        _USER,
        "What animal was in the picture?",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        lexical=FakeLexical([LexHit(SourceId("src-image"), 4, hit)]),
        vectors=FakeVector([VecHit(SourceId("src-image"), 4, 4, hit)]),
        embeddings=FakeEmbeddings(),
        model=CapturingModel(messages=iter(())),
        content=Content(),
        media=Media(),
        image_mode="native",
        trace_metadata={"operation": "recall.fast"},
    )

    human = captured["human"]
    assert isinstance(human, list)
    assert any(
        block.get("type") == "image"
        and block.get("base64") == base64.b64encode(image_bytes).decode("ascii")
        for block in human
    )
    rendered_text = "\n".join(
        block["text"] for block in human if block.get("type") == "text"
    )
    assert "a dog walking past a wall with a painting" in rendered_text
    assert "[cite: s01 ¶4-4]" in rendered_text
    assert "src-image" not in rendered_text
    assert human[-1]["type"] == "text"
    assert human[-1]["text"].rstrip().endswith("What animal was in the picture?")
    assert captured["metadata"]["image_mode"] == "native"
    assert captured["metadata"]["image_count"] == 1
    assert result.image_count == 1
    assert result.answer.startswith("A dog")


def test_caption_image_mode_keeps_derived_text_labelled_and_question_last():
    image = BlockImage.model_validate(
        {
            "image_id": "image-1",
            "mime_type": "image/jpeg",
            "sha256": "a" * 64,
            "size_bytes": 123,
            "storage_key": "tenant/image-1",
            "derived": [
                {
                    "kind": "caption",
                    "text": "a dog walking past a painted wall",
                    "producer": "fixture-captioner",
                }
            ],
        }
    )

    messages = selector_messages(
        "What animal was in the picture?",
        [],
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        images=[
            RecallImage(
                source_id=SourceId("src-image"),
                block_index=4,
                image=image,
            )
        ],
        image_mode="caption",
    )

    human = messages[1].content
    assert isinstance(human, str)
    assert "caption; producer=fixture-captioner" in human
    assert "a dog walking past a painted wall" in human
    assert "src-image" in human
    assert human.rstrip().endswith("What animal was in the picture?")


async def test_no_raw_indices_means_no_windows_backcompat():
    # Without raw indices wired, fast recall is claims-only (windows empty), unchanged.
    result = await fast_recall(
        _USER,
        "q",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([ClaimStub("aaaa", "p1", "x")]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=_model("y"),
    )
    assert result.used_windows == ()


def test_contract_treats_grounded_date_reasoning_as_in_scope_not_refusal():
    """The answering posture above the no-fabrication floor: simple calendar reasoning over
    dates present in the evidence (ordering, earliest/latest, inclusive span counting) is
    in-scope competence, an inference-based answer says it is derived, and "no relevant
    record" is reserved for grounding that is genuinely absent — not for answers the
    evidence supports without stating word for word."""
    contract = selector_contract()
    assert "nothing may be fabricated" in contract
    assert "calendar reasoning" in contract
    assert "counting a span out inclusively" in contract
    assert "genuinely absent" in contract


def test_contract_resolves_all_question_qualifiers_before_a_near_match():
    contract = selector_contract()
    assert "Satisfy every qualifier in the input together" in contract
    assert "older or ongoing activity merely mentioned" in contract
    assert "doing or beginning from proposing, considering, or intending" in contract


async def test_selector_system_message_byte_stable_across_as_of():
    claims = (await fast_recall(  # reuse retrieval to get RetrievedClaim objects
        _USER,
        "q",
        as_of=datetime(2026, 1, 1),
        claim_lexical=FakeClaimIndex([ClaimStub("aaaa", "p1", "x")]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=_model("_"),
    )).used_claims

    a = selector_messages("同一个问题", list(claims), as_of=datetime(2026, 1, 1, 9))
    b = selector_messages("同一个问题", list(claims), as_of=datetime(2026, 7, 20, 18, 30))
    assert isinstance(a[0], SystemMessage) and isinstance(a[1], HumanMessage)
    # I5: SystemMessage is the fixed contract, byte-identical, no as_of.
    assert a[0].content == b[0].content == selector_contract()
    assert "2026-01-01" not in a[0].content
    assert "2026-01-01T09:00:00" in a[1].content


# ----------------------------------------------------- reasoning-effort pass-through


class _KwargRecordingModel(GenericFakeChatModel):
    """A fake chat model that records the per-invoke kwargs the client would receive.

    `.bind(extra_body=...)` merges its kwargs into the underlying `_generate` call —
    exactly the seam a real ChatOpenAI forwards into the provider request payload — so
    asserting on these kwargs asserts what would ride the wire."""

    recorded: list[dict] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        type(self).recorded.append(dict(kwargs))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _recording_model(answer: str) -> _KwargRecordingModel:
    _KwargRecordingModel.recorded = []
    return _KwargRecordingModel(messages=iter([AIMessage(content=answer)]))


async def test_reasoning_effort_default_none_sends_nothing():
    """Default None = the request kwargs are byte-identical to the pre-knob behaviour:
    no `extra_body`, no `reasoning` key anywhere."""
    model = _recording_model("y")
    result = await fast_recall(
        _USER,
        "q",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([ClaimStub("aaaa", "p1", "x")]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
    )
    assert result.answer == "y"
    assert len(_KwargRecordingModel.recorded) == 1
    assert "extra_body" not in _KwargRecordingModel.recorded[0]
    assert "reasoning" not in _KwargRecordingModel.recorded[0]


async def test_reasoning_effort_rides_extra_body_on_answer_call_only():
    """Set → the ANSWERING invoke carries OpenRouter's wire shape
    `extra_body={"reasoning": {"effort": ...}}`; nothing else about the call changes."""
    model = _recording_model("y")
    result = await fast_recall(
        _USER,
        "q",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([ClaimStub("aaaa", "p1", "x")]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        reasoning_effort="xhigh",
    )
    assert result.answer == "y"
    assert len(_KwargRecordingModel.recorded) == 1
    assert _KwargRecordingModel.recorded[0].get("extra_body") == {
        "reasoning": {"effort": "xhigh"}
    }


async def test_dedicated_answer_model_receives_only_the_final_answer_call():
    """A cheap recall model may serve planning/glance while a quality-first model serves
    only the final answer. With auxiliary passes off, the recall model is never invoked."""
    recall_model = GenericFakeChatModel(messages=iter([AIMessage(content="wrong model")]))
    answer_model = _recording_model("answer model")

    result = await fast_recall(
        _USER,
        "q",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([ClaimStub("aaaa", "p1", "x")]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=recall_model,
        answer_model=answer_model,
        reasoning_effort="high",
    )

    assert result.answer == "answer model"
    assert _KwargRecordingModel.recorded == [
        {"extra_body": {"reasoning": {"effort": "high"}}}
    ]


async def test_reasoning_effort_never_reaches_the_glance_pass():
    """With documents supplied the glance selection pass runs too; only the answering
    call may carry the override."""
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_core.domain.ids import DocumentId

    doc = CanonicalDocument(
        doc_id=DocumentId("d-p1"),
        path="areas/p1.md",
        frontmatter={"title": "P1"},
        body="# P1\n\ncontent",
    )
    model = _recording_model("y")
    # Same recorder class: every invoke (glance selection included) lands in one list.
    glance_model = _KwargRecordingModel(messages=iter([AIMessage(content="{}")]))

    result = await fast_recall(
        _USER,
        "q",
        as_of=datetime(2026, 7, 20, 12, 0, 0),
        claim_lexical=FakeClaimIndex([ClaimStub("aaaa", "areas/p1.md", "x")]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        model=model,
        documents=[doc],
        glance_model=glance_model,
        reasoning_effort="xhigh",
    )
    assert result.answer == "y"
    answer_calls = [k for k in _KwargRecordingModel.recorded if k.get("extra_body")]
    assert len(answer_calls) == 1
    assert answer_calls[0]["extra_body"] == {"reasoning": {"effort": "xhigh"}}
