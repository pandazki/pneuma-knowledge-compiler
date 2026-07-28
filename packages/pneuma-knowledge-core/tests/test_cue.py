"""AI Cue: the four mechanical gates, focus as posture, stable speaker labelling.

Keyless throughout — plain fakes, no provider, no middleware. The gate tests each break
exactly one mechanism, so removing that mechanism from `apply_gates` turns exactly one
test red.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.cue import (
    CUE_FOCUSES,
    CUE_KINDS,
    Cue,
    CueBatch,
    focus_option,
    kind_option,
)
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.briefing import _BRIEFING_CONTRACT
from pneuma_knowledge_core.recall.cue import (
    CUE_CONTRACTS,
    apply_gates,
    cue_human,
    cue_messages,
    cue_once,
    gather_evidence,
    label_turns,
)
from pneuma_knowledge_core.recall.deep import _DEEP_CONTRACT
from pneuma_knowledge_core.recall.fast import _SELECTOR_CONTRACT
from langchain_core.messages import AIMessage

AS_OF = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)
USER = UserId("u-1")
SRC = "11111111-1111-1111-1111-111111111111"


# --------------------------------------------------------------------------- fakes


class FakeStructuredModel:
    """Stands in for `model.with_structured_output(CueBatch, include_raw=True)`.

    Returns the scripted `include_raw` envelopes in order; once exhausted it returns the
    shape a real model produces when it answers with prose instead of a tool call —
    parsed None. Records every message list it was handed."""

    def __init__(self, envelopes: list[dict] | None = None) -> None:
        self._envelopes = list(envelopes or [])
        self.calls: list[list] = []
        self.schemas: list[Any] = []
        self.include_raw: list[bool] = []

    def with_structured_output(self, schema, *, include_raw: bool = False):  # noqa: ANN001
        self.schemas.append(schema)
        self.include_raw.append(include_raw)
        outer = self

        class _Runnable:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001
                outer.calls.append(messages)
                if outer._envelopes:
                    return outer._envelopes.pop(0)
                return {
                    "raw": AIMessage(content="done"),
                    "parsed": None,
                    "parsing_error": None,
                }

        return _Runnable()


def envelope(batch: CueBatch | None) -> dict:
    return {"raw": AIMessage(content=""), "parsed": batch, "parsing_error": None}


class FakeEmbeddings:
    """Counts the two round-trip shapes so batching is observable, not asserted on faith."""

    def __init__(self) -> None:
        self.query_calls = 0
        self.document_calls = 0
        self.batched: list[list[str]] = []

    async def aembed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return [0.1, 0.2, 0.3]

    async def aembed_documents(self, texts):  # noqa: ANN001
        self.document_calls += 1
        self.batched.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


@dataclass
class ClaimStub:
    anchor: str
    document_path: str
    text: str
    section_path: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


class FakeClaimLexical:
    """Returns a different claim per query text, so the per-turn union is observable."""

    def __init__(self, by_query: dict[str, list[ClaimStub]]) -> None:
        self._by_query = by_query

    async def search_claims(self, user_id, query, *, limit=40):  # noqa: ANN001
        return self._by_query.get(query, [])[:limit]


class FakeClaimVectors:
    async def search_claims(self, user_id, embedding, *, limit=40):  # noqa: ANN001
        return []


def claim_stub(anchor: str, text: str, source: str = SRC) -> ClaimStub:
    return ClaimStub(
        anchor=anchor,
        document_path=f"memory/{anchor}.md",
        text=text,
        citations=[{"source_id": source, "block_start": 1, "block_end": 2}],
    )


def cue(
    *,
    body: str = f"[cite: s01 ¶1-2] 说明",
    confidence: int = 8,
    title: str = "术语",
    kind: str = "concept",
) -> Cue:
    return Cue(kind=kind, title=title, body=body, trigger="他刚提到术语", confidence=confidence)


HANDLES = {"s01": SRC, "s02": "22222222-2222-2222-2222-222222222222"}


# ------------------------------------------------------------- spine byte-stability
#
# Public OPC strategy baseline. These digests pin the three business-neutral answer
# contracts so later edits cannot silently drift the provider-cache-stable System bytes.

_PUBLIC_BASELINE_SHA256 = {
    "fast": "13dccd9e2db1da26652605cd13ad857f845df03951357df109bb647ce5d7242e",
    "deep": "c2aec38af57a9764154868f35f3083e13fd7ad4c54a414f06268c91ff215a36b",
    "briefing": "04592260b176bdd7707da7100aa32393e554728880a838380b64b2294026e9e2",
}


_ANSWER_CONTRACTS = {
    "fast": _SELECTOR_CONTRACT,
    "deep": _DEEP_CONTRACT,
    "briefing": _BRIEFING_CONTRACT,
}


@pytest.mark.parametrize("name", ["fast", "deep", "briefing"])
def test_public_answer_contracts_are_byte_stable(name):
    digest = hashlib.sha256(_ANSWER_CONTRACTS[name].encode()).hexdigest()
    assert digest == _PUBLIC_BASELINE_SHA256[name]


def test_cue_contract_drops_the_qa_close_and_keeps_the_red_lines():
    """The whole reason `close` exists: the Q&A closing would have the model push a card
    reading 「无相关记录」onto the lens. The red line (assertion strength = evidence
    strength) and the wide-recall/subject-identity paragraph stay — in a multi-party
    conversation they matter MORE, not less."""
    contract = CUE_CONTRACTS["general"]
    assert "「无相关记录」就是忠实的答案" not in contract
    assert "断言的强度必须与证据的强度对齐" in contract
    assert "属于其他主体的证据再相似也是另一条记录" in contract
    # ASR error is re-attributed to every speaker, not just the owner.
    assert "每一位说话人" in contract


def test_cue_contracts_are_byte_stable_per_focus():
    """Computed at module load, no timestamp / transcript / evidence (I5)."""
    from pneuma_knowledge_core.recall.cue import _cue_contract

    for focus in ("general", "owner", "other"):
        # rebuilding is byte-identical: nothing volatile was baked in at load time
        assert _cue_contract(focus) == CUE_CONTRACTS[focus]
        # no timestamp, no transcript, no evidence — posture only (I5)
        assert not re.search(r"\d{4}-\d{2}-\d{2}", CUE_CONTRACTS[focus])
        assert "本人输入" not in CUE_CONTRACTS[focus]


# ------------------------------------------------------------------- the four gates


def test_gate1_unparsed_yields_zero_cues():
    """`parsed is None` (prose answer, schema violation, provider hiccup) → silence, never
    an exception onto a pair of context clients."""
    cues, dropped = apply_gates(None, HANDLES)
    assert cues == []
    assert dropped["unparsed"] == 1


def test_gate2_uncited_cue_is_dropped():
    """No `[cite: …]` resolving to a real source → not grounded → not a cue."""
    batch = CueBatch(
        cues=[
            cue(title="有引用", body="[cite: s01 ¶1-2] 有据"),
            cue(title="无引用", body="听起来很重要但没有出处"),
            cue(title="幻觉句柄", body="[cite: s99 ¶1-2] 指向不存在的来源"),
        ]
    )
    cues, dropped = apply_gates(batch, HANDLES, max_cues=5, min_confidence=1)
    assert [c.title for c in cues] == ["有引用"]
    assert dropped["uncited"] == 2


def test_gate3_confidence_below_threshold_is_dropped():
    batch = CueBatch(
        cues=[
            cue(title="高分", confidence=9),
            cue(title="低分", confidence=3),
        ]
    )
    cues, dropped = apply_gates(batch, HANDLES, max_cues=5, min_confidence=6)
    assert [c.title for c in cues] == ["高分"]
    assert dropped["low_confidence"] == 1


def test_gate3_threshold_is_a_dial_over_the_same_batch():
    """The confidence is already computed, so re-thresholding re-runs nothing — that is
    the reason sensitivity lives here and not on a retrieval score."""
    batch = CueBatch(cues=[cue(title=f"c{n}", confidence=n) for n in (2, 5, 8)])
    for threshold, expected in [(1, 3), (5, 2), (8, 1), (9, 0)]:
        cues, _ = apply_gates(batch, HANDLES, max_cues=5, min_confidence=threshold)
        assert len(cues) == expected


def test_gate4_caps_by_confidence_descending():
    batch = CueBatch(
        cues=[
            cue(title="中", confidence=7),
            cue(title="低", confidence=6),
            cue(title="高", confidence=10),
            cue(title="次高", confidence=9),
        ]
    )
    cues, dropped = apply_gates(batch, HANDLES, max_cues=2, min_confidence=1)
    assert [c.title for c in cues] == ["高", "次高"]
    assert [c.confidence for c in cues] == [10, 9]
    assert dropped["capped"] == 2


def test_gate4_ties_keep_the_models_own_order():
    batch = CueBatch(cues=[cue(title=t, confidence=7) for t in ("甲", "乙", "丙")])
    cues, _ = apply_gates(batch, HANDLES, max_cues=2, min_confidence=1)
    assert [c.title for c in cues] == ["甲", "乙"]


def test_already_shown_is_dropped_mechanically_not_asked_for():
    batch = CueBatch(cues=[cue(title="术语", kind="concept"), cue(title="新的")])
    cues, dropped = apply_gates(
        batch,
        HANDLES,
        max_cues=5,
        min_confidence=1,
        # a client replaying its own JSON, cite residue and all
        already_shown=[{"kind": "concept", "title": "术语 [cite: s07 ¶1-2]"}],
    )
    assert [c.title for c in cues] == ["新的"]
    assert dropped["repeat"] == 1


def test_handles_are_resolved_and_stripped_before_leaving_the_server():
    """A client never sees `sNN`: handles are re-assigned every evaluation, so one that
    outlived its evaluation would point at a different source."""
    batch = CueBatch(cues=[cue(body="RRF 是排名倒数融合 [cite: s01 ¶3-5]。")])
    cues, _ = apply_gates(batch, HANDLES, min_confidence=1)
    assert "[cite:" not in cues[0].body
    assert "s01" not in cues[0].body
    assert cues[0].body == "RRF 是排名倒数融合。"
    assert cues[0].citations == [
        Citation(source_id=SourceId(SRC), block_start=3, block_end=5)
    ]


def test_hallucinated_handle_yields_no_citation():
    batch = CueBatch(cues=[cue(body="有据 [cite: s01 ¶1-2] 与臆造 [cite: s42 ¶9-9]")])
    cues, _ = apply_gates(batch, HANDLES, min_confidence=1)
    assert [c.source_id for c in cues[0].citations] == [SourceId(SRC)]


# ------------------------------------------------------------------------- focus


def test_three_focus_values_produce_three_different_contracts():
    contracts = {f: CUE_CONTRACTS[f] for f in ("general", "owner", "other")}
    assert len(set(contracts.values())) == 3
    assert "不论出自谁口" in contracts["general"]
    assert "只为「本人」说出的内容出卡片" in contracts["owner"]
    assert "只为「参与者」说出的内容出卡片" in contracts["other"]


TRANSCRIPT = "本人：我们在谈 RRF。\n参与者1（others/2）：那 chonkie 呢？"


def test_focus_changes_the_system_the_model_sees_but_never_the_transcript():
    """铁律: the full transcript always goes in. focus is attention direction, expressed
    in the System tier — it is NEVER a speaker filter, because filtering would destroy the
    context needed to understand what is left."""
    systems, humans = set(), set()
    for focus in ("general", "owner", "other"):
        system, human = cue_messages(TRANSCRIPT, as_of=AS_OF, focus=focus)
        systems.add(system.content)
        humans.add(human.content)
    assert len(systems) == 3, "focus must change the posture"
    assert len(humans) == 1, "focus must NOT change the evidence/transcript payload"
    only_human = humans.pop()
    assert "我们在谈 RRF。" in only_human
    assert "那 chonkie 呢？" in only_human


@pytest.mark.asyncio
async def test_focus_reaches_the_model_end_to_end():
    turns = [
        ConversationTurn(speaker="self/1", text="我们在谈 RRF。", role="owner"),
        ConversationTurn(speaker="others/2", text="那 chonkie 呢？", role="other", speaker_id="others/2"),
    ]
    seen = []
    for focus in ("general", "owner", "other"):
        model = FakeStructuredModel()
        await cue_once(USER, turns, as_of=AS_OF, model=model, focus=focus)
        seen.append(model.calls[0][0].content)
    assert len(set(seen)) == 3


def test_unknown_focus_is_a_hard_error_not_a_silent_fallback():
    with pytest.raises(ValueError):
        cue_messages(TRANSCRIPT, as_of=AS_OF, focus="everyone")  # type: ignore[arg-type]


# ------------------------------------------------------------------ speaker labels


def owner(text: str) -> ConversationTurn:
    return ConversationTurn(speaker="self/1", text=text, role="owner")


def other(text: str, sid: str) -> ConversationTurn:
    return ConversationTurn(speaker=sid, text=text, role="other", speaker_id=sid)


def test_label_turns_numbers_owner_and_others():
    turns = [owner("嗨"), other("你好", "others/2"), other("我也在", "others/5")]
    assert label_turns(turns) == ["本人", "参与者1（others/2）", "参与者2（others/5）"]


def test_label_turns_is_stable_across_evaluations_with_a_caller_owned_map():
    """The sliding-window bug this helper exists for: once the first speaker's turns
    scroll out of the window, within-call numbering silently reassigns 参与者1 to a
    DIFFERENT person. A connection-lifetime map prevents that."""
    a, b = other("A 说", "others/2"), other("B 说", "others/5")
    label_map: dict[str, str] = {}

    first = label_turns([a, b], label_map)
    # window slides: speaker A has scrolled out entirely
    second = label_turns([b, other("B 又说", "others/5")], label_map)

    assert first == ["参与者1（others/2）", "参与者2（others/5）"]
    assert second == ["参与者2（others/5）", "参与者2（others/5）"]
    assert second[0] == first[1], "B must keep its number across evaluations"


def test_label_turns_renumbers_without_a_shared_map():
    """The same two windows with no caller-owned map: B is 参与者2 in the first and
    参与者1 in the second — the exact failure the map prevents."""
    a, b = other("A 说", "others/2"), other("B 说", "others/5")
    first = label_turns([a, b])
    second = label_turns([b])
    assert first[1] == "参与者2（others/5）"
    assert second[0] == "参与者1（others/5）"
    assert second[0] != first[1]


def test_label_turns_leaves_undiarized_turns_verbatim():
    turns = [ConversationTurn(speaker="Speaker 3", text="嗯")]
    assert label_turns(turns) == ["Speaker 3"]


# ------------------------------------------------------------------ assembly + engine


def test_transcript_sits_last_in_the_human_turn():
    human = cue_human(
        TRANSCRIPT,
        as_of=AS_OF,
        claims=[],
        profile="张三，工程师",
        already_shown=[{"kind": "fact", "title": "上一张"}],
    )
    assert human.index("本人画像") < human.index("claim 注记")
    assert human.index("claim 注记") < human.index("已提示过")
    assert human.index("已提示过") < human.index("as_of:")
    assert human.rstrip().endswith("那 chonkie 呢？")


def test_human_turn_never_labels_the_transcript_as_the_owners_input():
    """Not `recall_human`: hanging a multi-speaker transcript under 「本人输入」 would
    mislabel every interlocutor line as the owner's — under a feature whose whole focus
    axis is speaker attribution."""
    human = cue_human(TRANSCRIPT, as_of=AS_OF)
    assert "本人输入" not in human


def test_already_shown_cite_residue_never_reaches_the_prompt():
    human = cue_human(
        TRANSCRIPT,
        as_of=AS_OF,
        already_shown=[{"kind": "concept", "title": "RRF [cite: s03 ¶1-2]"}],
    )
    assert "[cite:" not in human.split("# 对话转录")[0].split("已提示过")[1]


@pytest.mark.asyncio
async def test_gather_evidence_batches_every_turn_into_one_embedding_call():
    """N=3 turns must cost ONE embedding round trip, not N. Latency is why cue exists."""
    embeddings = FakeEmbeddings()
    lexical = FakeClaimLexical(
        {
            "第一轮": [claim_stub("c1", "一")],
            "第二轮": [claim_stub("c2", "二")],
            "第三轮": [claim_stub("c3", "三")],
        }
    )
    evidence = await gather_evidence(
        USER,
        ["第一轮", "第二轮", "第三轮"],
        claim_lexical=lexical,
        claim_vectors=FakeClaimVectors(),
        embeddings=embeddings,
    )
    assert embeddings.document_calls == 1
    assert embeddings.query_calls == 0
    assert embeddings.batched == [["第一轮", "第二轮", "第三轮"]]
    # union of every turn's top-k, each attributed to the turn that surfaced it
    assert [str(c.anchor) for c in evidence.claims] == ["c1", "c2", "c3"]
    assert evidence.claim_turn == {"c1": 0, "c2": 1, "c3": 2}


@pytest.mark.asyncio
async def test_gather_evidence_dedups_a_claim_surfaced_by_several_turns():
    embeddings = FakeEmbeddings()
    shared = claim_stub("c1", "同一条")
    lexical = FakeClaimLexical({"甲": [shared], "乙": [shared]})
    evidence = await gather_evidence(
        USER, ["甲", "乙"], claim_lexical=lexical, claim_vectors=FakeClaimVectors(), embeddings=embeddings
    )
    assert len(evidence.claims) == 1
    assert evidence.claim_turn == {"c1": 0}, "the FIRST turn to surface it owns it"


@pytest.mark.asyncio
async def test_cue_once_end_to_end_grounded_card():
    embeddings = FakeEmbeddings()
    lexical = FakeClaimLexical({"RRF 是什么？": [claim_stub("c1", "RRF = 排名倒数融合")]})
    model = FakeStructuredModel(
        [envelope(CueBatch(cues=[cue(body="RRF 是排名倒数融合 [cite: s01 ¶1-2]")]))]
    )
    result = await cue_once(
        USER,
        [other("RRF 是什么？", "others/2")],
        as_of=AS_OF,
        model=model,
        embeddings=embeddings,
        claim_lexical=lexical,
        claim_vectors=FakeClaimVectors(),
    )
    assert model.schemas == [CueBatch]
    assert model.include_raw == [True], "include_raw is what makes a parse failure silent"
    assert len(result.cues) == 1
    assert result.cues[0].citations[0].source_id == SourceId(SRC)
    assert "[cite:" not in result.cues[0].body
    assert result.dropped == {
        "unparsed": 0, "repeat": 0, "uncited": 0, "low_confidence": 0, "capped": 0
    }
    # the model saw short handles, never the 32-char id
    human = model.calls[0][1].content
    assert "[cite: s01" in human and SRC not in human


@pytest.mark.asyncio
async def test_cue_once_is_silent_when_the_model_answers_with_prose():
    """FakeStructuredModel exhausted → parsed None. Gate 1, end to end."""
    result = await cue_once(USER, [owner("随便聊聊")], as_of=AS_OF, model=FakeStructuredModel())
    assert result.cues == ()
    assert result.dropped["unparsed"] == 1
    assert result.token_usage["input_tokens"] == 0


@pytest.mark.asyncio
async def test_cue_once_window_keeps_only_the_last_n_turns():
    embeddings = FakeEmbeddings()
    turns = [owner(f"第{i}句") for i in range(6)]
    await cue_once(
        USER,
        turns,
        as_of=AS_OF,
        model=FakeStructuredModel(),
        embeddings=embeddings,
        claim_lexical=FakeClaimLexical({}),
        claim_vectors=FakeClaimVectors(),
        turn_window=3,
    )
    assert embeddings.batched == [["第3句", "第4句", "第5句"]]


@pytest.mark.asyncio
async def test_briefing_scope_does_zero_retrieval():
    """A frozen pack IS the evidence: no embedding, no index call, fastest path."""
    embeddings = FakeEmbeddings()
    model = FakeStructuredModel()
    await cue_once(
        USER,
        [owner("说点什么")],
        as_of=AS_OF,
        model=model,
        embeddings=embeddings,
        pack="# claim 注记（1 条）\n[c:c1 · memory/c1.md] 冻结包内容",
    )
    assert embeddings.document_calls == 0 and embeddings.query_calls == 0
    assert "冻结包内容" in model.calls[0][1].content


@pytest.mark.asyncio
async def test_cue_once_holds_speaker_numbering_across_evaluations():
    a, b = other("A 说", "others/2"), other("B 说", "others/5")
    label_map: dict[str, str] = {}
    model = FakeStructuredModel()
    await cue_once(USER, [a, b], as_of=AS_OF, model=model, label_map=label_map)
    await cue_once(USER, [b], as_of=AS_OF, model=model, label_map=label_map)
    assert "参与者2（others/5）：B 说" in model.calls[1][1].content


# ------------------------------------------------------------------- the vocabulary


def test_focus_and_kind_vocabularies_are_closed():
    assert [f.key for f in CUE_FOCUSES] == ["general", "owner", "other"]
    assert [k.key for k in CUE_KINDS] == ["concept", "fact"]
    assert set(CUE_CONTRACTS) == {f.key for f in CUE_FOCUSES}
    assert focus_option("owner").label == "仅我说的"
    assert kind_option("fact").key == "fact"
    with pytest.raises(ValueError):
        focus_option("everybody")
    with pytest.raises(ValueError):
        kind_option("opinion")


def test_cue_batch_has_a_mechanical_ceiling():
    """max_length=5 is what the model can physically emit; under include_raw a longer list
    becomes a parsing_error → silence. Distinct from the tunable max_cues cap."""
    with pytest.raises(Exception):
        CueBatch(cues=[cue(title=f"c{i}") for i in range(6)])


def test_confidence_is_bounded_by_the_schema():
    for bad in (0, 11, -3):
        with pytest.raises(Exception):
            cue(confidence=bad)
