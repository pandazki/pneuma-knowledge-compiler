"""AI ContextSuggestion: the four mechanical gates, focus as posture, stable speaker labelling.

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
from pneuma_knowledge_core.domain.suggestion import (
    CONTEXT_FOCUSES,
    SUGGESTION_KINDS,
    ContextSuggestion,
    SuggestionBatch,
    focus_option,
    kind_option,
)
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.briefing import briefing_contract
from pneuma_knowledge_core.recall.suggestion import (
    live_context_contracts,
    apply_gates,
    live_context_human,
    live_context_messages,
    evaluate_live_context,
    label_turns,
)
from pneuma_knowledge_core.recall.deep import deep_contract
from pneuma_knowledge_core.recall.fast import selector_contract
from langchain_core.messages import AIMessage

AS_OF = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)
USER = UserId("u-1")
SRC = "11111111-1111-1111-1111-111111111111"


# --------------------------------------------------------------------------- fakes


class FakeStructuredModel:
    """Stands in for `model.with_structured_output(SuggestionBatch, include_raw=True)`.

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


def envelope(batch: SuggestionBatch | None) -> dict:
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


def suggestion(
    *,
    body: str = f"[cite: s01 ¶1-2] 说明",
    confidence: int = 8,
    title: str = "术语",
    kind: str = "concept",
) -> ContextSuggestion:
    return ContextSuggestion(kind=kind, title=title, body=body, trigger="他刚提到术语", confidence=confidence)


HANDLES = {"s01": SRC, "s02": "22222222-2222-2222-2222-222222222222"}


# ------------------------------------------------------------- spine byte-stability
#
# Public framework baseline. These digests pin the three business-neutral answer
# contracts so later edits cannot silently drift the provider-cache-stable System bytes.

_PUBLIC_BASELINE_SHA256 = {
    # 2026-08: the fast head gained the grounded-inference paragraph (no-fabrication floor →
    # calendar reasoning over dated evidence is in-scope competence, inference-based answers
    # say so, refusal reserved for genuinely absent grounding).
    # 2026-08-01: the fast head gained the subject-attribution paragraph (the same
    # no-fabrication floor extends to attribution — a fact the records attribute to a
    # different subject does not answer a question about the asked subject; say the records
    # do not support it for that subject, and correct presuppositions attributed otherwise).
    # 2026-08-04: the shared honest-close became two-tier (recall.close.answer_honestly):
    # evidence supporting a reasonable inference → give the best-supported inference and
    # say what it rests on; no footing at all → "no relevant record" stays the faithful
    # answer. Measured on LoCoMo-refined: +3.6pp (p=0.001), reproduced +4.3pp (p=0.0001)
    # on a different retrieval base; abstention 4.8%→1.3% with no fabrication signature.
    # 2026-08-05: the honest-close gained the absolute-time law: relative time inside
    # material has expired by reading time and "now" is unknown unless explicitly given,
    # so answers reason in absolute dates (anchored spans when that is all the evidence
    # supports) and never emit a bare relative expression. Three independent conv-26 runs
    # showed the library normalizing perfectly while the answering layer still emitted
    # "Yesterday." — the floor belongs in the contract, not in every harness author's head.
    # 2026-08-05 (2): the fast/deep contracts gained the answer-style clause — three
    # deployment presets (concise / conversational / detailed) appended after the spine;
    # the default is "conversational" and these digests pin that default. Briefing keeps
    # its own genre and is unchanged. Style shapes the answer only; truth discipline
    # (red line, citations, honest close) is style-independent by construction.
    # 2026-08-06: briefing only — the head said the pack's two routes were "for what lies
    # outside it" and then defined the first as searching "within the range the pack covers",
    # which is a contradiction the model had to resolve for itself. Reworded to the tools'
    # real reach: `search_knowledge` searches the session's SOURCE RANGE again (the pack
    # sampled it), `fetch_verbatim` reaches any source by id. No capability changed.
    # 2026-08-11: the shared spine now resolves every question qualifier together and
    # distinguishes a transition in the asked period from an older activity merely
    # mentioned then. This is general temporal/evidence discipline, shared by all three.
    # 2026-08-12: the shared time clause no longer tells the model to resolve relative
    # expressions quoted from old evidence against the live ask's `as_of`. Evidence uses
    # its source occurrence clock; only the owner's live input uses the ask clock. An
    # ambiguous calendar period keeps that absolute anchor rather than fabricating exact
    # endpoints.
    # 2026-08-12: fast also receives source-addressed L2 episode descriptions as an
    # explicitly labelled derived summary face, alongside claims and verbatim excerpts.
    "fast": "a31e17d2a2e20ba1d474cc2b597cf393abdff81eaf3e929777ea29672aeda8b8",
    "deep": "1b04985e05e20b0d1b895c06493f92c5d9cd724183ed47b99f64447267840e94",
    "briefing": "b2be86ca8606007e2007508a065a7f9cae4222460e9b52299214cc5c826b29fc",
}


_ANSWER_CONTRACTS = {
    "fast": selector_contract(),
    "deep": deep_contract(),
    "briefing": briefing_contract(),
}


@pytest.mark.parametrize("name", ["fast", "deep", "briefing"])
def test_public_answer_contracts_are_byte_stable(name):
    digest = hashlib.sha256(_ANSWER_CONTRACTS[name].encode()).hexdigest()
    assert digest == _PUBLIC_BASELINE_SHA256[name]


@pytest.mark.parametrize("contract", [selector_contract, deep_contract])
def test_answer_style_presets_swap_exactly_the_style_clause(contract):
    """Each preset yields a distinct contract; the default IS "conversational"; and the
    three variants share every byte except the style clause (truth discipline never
    varies with style). Unknown names raise instead of answering in the default voice."""
    from pneuma_knowledge_core.recall.spine import ANSWER_STYLES, style_clause

    variants = {s: contract(answer_style=s) for s in ANSWER_STYLES}
    assert len(set(variants.values())) == 3
    assert contract() == variants["conversational"]
    for style, text in variants.items():
        clause = style_clause(style)
        assert text.endswith(clause)
        assert text.removesuffix(clause) == variants["concise"].removesuffix(
            style_clause("concise")
        )
    with pytest.raises(ValueError):
        contract(answer_style="terse")


def test_fast_contract_extends_the_no_fabrication_floor_to_attribution():
    """2026-08-01: a true fact the records attribute to a different subject is not an
    answer about the asked subject. The fast head must say so in so many words — confirm
    the evidence is about the asked subject, refuse for that subject on a mismatch, and
    give a presupposing question the same correction — without displacing the existing
    grounded-inference and refusal clauses."""
    text = " ".join(selector_contract().split())
    # the attribution paragraph
    assert "The same floor extends to attribution" in text
    assert (
        "confirm the supporting evidence is actually about that subject" in text
    )
    assert (
        "a fact the records attribute to a different subject is not an answer about "
        "the one asked" in text
    )
    assert "say the records do not support it for the asked subject" in text
    assert (
        "A question that presupposes something the records attribute to a different "
        "subject deserves that same correction" in text
    )
    # the pre-existing clauses stay intact around it
    assert "nothing may be fabricated" in text
    assert "a reasonable inference grounded in the recorded facts" in text
    assert 'Reserve "no relevant record" for grounding that is genuinely absent' in text


def test_live_context_contract_drops_the_qa_close_and_keeps_the_red_lines():
    """The whole reason `close` exists: the Q&A closing would have the model push a visible
    "no relevant record" card. The red line (assertion strength = evidence strength) and the
    wide-recall/subject-identity paragraph stay — in a multi-party conversation they matter
    MORE, not less."""
    contract = live_context_contracts()["general"]
    assert '"no relevant record" is the faithful answer' not in contract
    assert (
        "The strength of an assertion must match the strength of the evidence" in contract
    )
    assert "is another record however similar it looks" in contract
    # Speech recognition stays an input concern without making the whole feature
    # conversation-only.
    assert "The stream may come from speech recognition" in contract


def test_live_context_contracts_are_byte_stable_per_focus():
    """Computed at module load, no timestamp / transcript / evidence (I5)."""
    from pneuma_knowledge_core.recall.suggestion import _live_context_contract

    for focus in ("general", "owner", "other"):
        # rebuilding is byte-identical: nothing volatile was baked in at load time
        assert _live_context_contract(focus) == live_context_contracts()[focus]
        # no timestamp, no transcript, no evidence — posture only (I5)
        assert not re.search(r"\d{4}-\d{2}-\d{2}", live_context_contracts()[focus])
        assert "Owner input:" not in live_context_contracts()[focus]


# ------------------------------------------------------------------- the four gates


def test_gate1_unparsed_yields_zero_suggestions():
    """`parsed is None` (prose answer, schema violation, provider hiccup) → silence, never
    an exception onto a pair of context clients."""
    suggestions, dropped = apply_gates(None, HANDLES)
    assert suggestions == []
    assert dropped["unparsed"] == 1


def test_gate2_uncited_suggestion_is_dropped():
    """No `[cite: …]` resolving to a real source → not grounded → not a suggestion."""
    batch = SuggestionBatch(
        suggestions=[
            suggestion(title="有引用", body="[cite: s01 ¶1-2] 有据"),
            suggestion(title="无引用", body="听起来很重要但没有出处"),
            suggestion(title="幻觉句柄", body="[cite: s99 ¶1-2] 指向不存在的来源"),
        ]
    )
    suggestions, dropped = apply_gates(batch, HANDLES, max_suggestions=5, min_confidence=1)
    assert [c.title for c in suggestions] == ["有引用"]
    assert dropped["uncited"] == 2


def test_gate3_confidence_below_threshold_is_dropped():
    batch = SuggestionBatch(
        suggestions=[
            suggestion(title="高分", confidence=9),
            suggestion(title="低分", confidence=3),
        ]
    )
    suggestions, dropped = apply_gates(batch, HANDLES, max_suggestions=5, min_confidence=6)
    assert [c.title for c in suggestions] == ["高分"]
    assert dropped["low_confidence"] == 1


def test_gate3_threshold_is_a_dial_over_the_same_batch():
    """The confidence is already computed, so re-thresholding re-runs nothing — that is
    the reason sensitivity lives here and not on a retrieval score."""
    batch = SuggestionBatch(suggestions=[suggestion(title=f"c{n}", confidence=n) for n in (2, 5, 8)])
    for threshold, expected in [(1, 3), (5, 2), (8, 1), (9, 0)]:
        suggestions, _ = apply_gates(batch, HANDLES, max_suggestions=5, min_confidence=threshold)
        assert len(suggestions) == expected


def test_gate4_caps_by_confidence_descending():
    batch = SuggestionBatch(
        suggestions=[
            suggestion(title="中", confidence=7),
            suggestion(title="低", confidence=6),
            suggestion(title="高", confidence=10),
            suggestion(title="次高", confidence=9),
        ]
    )
    suggestions, dropped = apply_gates(batch, HANDLES, max_suggestions=2, min_confidence=1)
    assert [c.title for c in suggestions] == ["高", "次高"]
    assert [c.confidence for c in suggestions] == [10, 9]
    assert dropped["capped"] == 2


def test_gate4_ties_keep_the_models_own_order():
    batch = SuggestionBatch(suggestions=[suggestion(title=t, confidence=7) for t in ("甲", "乙", "丙")])
    suggestions, _ = apply_gates(batch, HANDLES, max_suggestions=2, min_confidence=1)
    assert [c.title for c in suggestions] == ["甲", "乙"]


def test_already_shown_is_dropped_mechanically_not_asked_for():
    batch = SuggestionBatch(suggestions=[suggestion(title="术语", kind="concept"), suggestion(title="新的")])
    suggestions, dropped = apply_gates(
        batch,
        HANDLES,
        max_suggestions=5,
        min_confidence=1,
        # a client replaying its own JSON, cite residue and all
        already_shown=[{"kind": "concept", "title": "术语 [cite: s07 ¶1-2]"}],
    )
    assert [c.title for c in suggestions] == ["新的"]
    assert dropped["repeat"] == 1


def test_handles_are_resolved_and_stripped_before_leaving_the_server():
    """A client never sees `sNN`: handles are re-assigned every evaluation, so one that
    outlived its evaluation would point at a different source."""
    batch = SuggestionBatch(suggestions=[suggestion(body="RRF 是排名倒数融合 [cite: s01 ¶3-5]。")])
    suggestions, _ = apply_gates(batch, HANDLES, min_confidence=1)
    assert "[cite:" not in suggestions[0].body
    assert "s01" not in suggestions[0].body
    assert suggestions[0].body == "RRF 是排名倒数融合。"
    assert suggestions[0].citations == [
        Citation(source_id=SourceId(SRC), block_start=3, block_end=5)
    ]


def test_hallucinated_handle_yields_no_citation():
    batch = SuggestionBatch(suggestions=[suggestion(body="有据 [cite: s01 ¶1-2] 与臆造 [cite: s42 ¶9-9]")])
    suggestions, _ = apply_gates(batch, HANDLES, min_confidence=1)
    assert [c.source_id for c in suggestions[0].citations] == [SourceId(SRC)]


# ------------------------------------------------------------------------- focus


def test_three_focus_values_produce_three_different_contracts():
    contracts = {f: live_context_contracts()[f] for f in ("general", "owner", "other")}
    assert len(set(contracts.values())) == 3
    assert "whoever said it" in contracts["general"]
    assert "generate cards only for what the owner put in" in contracts["owner"]
    assert "generate cards only for what the participants put" in contracts["other"]


TRANSCRIPT = "本人：我们在谈 RRF。\n参与者1（others/2）：那 chonkie 呢？"


def test_focus_changes_the_system_the_model_sees_but_never_the_transcript():
    """铁律: the full transcript always goes in. focus is attention direction, expressed
    in the System tier — it is NEVER a speaker filter, because filtering would destroy the
    context needed to understand what is left."""
    systems, humans = set(), set()
    for focus in ("general", "owner", "other"):
        system, human = live_context_messages(
            TRANSCRIPT, as_of=AS_OF, pack="frozen pack", focus=focus
        )
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
        await evaluate_live_context(
            USER, turns, as_of=AS_OF, model=model, pack="frozen pack", focus=focus
        )
        seen.append(model.calls[0][0].content)
    assert len(set(seen)) == 3


def test_unknown_focus_is_a_hard_error_not_a_silent_fallback():
    with pytest.raises(ValueError):
        live_context_messages(
            TRANSCRIPT, as_of=AS_OF, pack="frozen pack", focus="everyone"
        )  # type: ignore[arg-type]


# ------------------------------------------------------------------ speaker labels


def owner(text: str) -> ConversationTurn:
    return ConversationTurn(speaker="self/1", text=text, role="owner")


def other(text: str, sid: str) -> ConversationTurn:
    return ConversationTurn(speaker=sid, text=text, role="other", speaker_id=sid)


def test_label_turns_numbers_owner_and_others():
    turns = [owner("嗨"), other("你好", "others/2"), other("我也在", "others/5")]
    assert label_turns(turns) == ["Owner", "Participant1 (others/2)", "Participant2 (others/5)"]


def test_label_turns_is_stable_across_evaluations_with_a_caller_owned_map():
    """The sliding-window bug this helper exists for: once the first speaker's turns
    scroll out of the window, within-call numbering silently reassigns 参与者1 to a
    DIFFERENT person. A connection-lifetime map prevents that."""
    a, b = other("A 说", "others/2"), other("B 说", "others/5")
    label_map: dict[str, str] = {}

    first = label_turns([a, b], label_map)
    # window slides: speaker A has scrolled out entirely
    second = label_turns([b, other("B 又说", "others/5")], label_map)

    assert first == ["Participant1 (others/2)", "Participant2 (others/5)"]
    assert second == ["Participant2 (others/5)", "Participant2 (others/5)"]
    assert second[0] == first[1], "B must keep its number across evaluations"


def test_label_turns_renumbers_without_a_shared_map():
    """The same two windows with no caller-owned map: B is 参与者2 in the first and
    参与者1 in the second — the exact failure the map prevents."""
    a, b = other("A 说", "others/2"), other("B 说", "others/5")
    first = label_turns([a, b])
    second = label_turns([b])
    assert first[1] == "Participant2 (others/5)"
    assert second[0] == "Participant1 (others/5)"
    assert second[0] != first[1]


def test_label_turns_leaves_undiarized_turns_verbatim():
    turns = [ConversationTurn(speaker="Speaker 3", text="嗯")]
    assert label_turns(turns) == ["Speaker 3"]


# ------------------------------------------------------------------ assembly + engine


def test_transcript_sits_last_in_the_human_turn():
    human = live_context_human(
        TRANSCRIPT,
        as_of=AS_OF,
        pack="# claim notes (1)\n[c:c1 · memory/c1.md] frozen pack",
        profile="张三，工程师",
        already_shown=[{"kind": "fact", "title": "上一张"}],
    )
    assert human.index("Owner profile") < human.index("claim notes")
    assert human.index("claim notes") < human.index("Already surfaced")
    assert human.index("Already surfaced") < human.index("as_of:")
    assert human.rstrip().endswith("那 chonkie 呢？")


def test_human_turn_never_labels_the_transcript_as_the_owners_input():
    """Not `recall_human`: hanging a multi-speaker transcript under 「本人输入」 would
    mislabel every interlocutor line as the owner's — under a feature whose whole focus
    axis is speaker attribution."""
    human = live_context_human(TRANSCRIPT, as_of=AS_OF, pack="frozen pack")
    assert "本人输入" not in human


def test_already_shown_cite_residue_never_reaches_the_prompt():
    human = live_context_human(
        TRANSCRIPT,
        as_of=AS_OF,
        pack="frozen pack",
        already_shown=[{"kind": "concept", "title": "RRF [cite: s03 ¶1-2]"}],
    )
    assert "[cite:" not in human.split("# Stream transcript")[0].split("Already surfaced")[1]


@pytest.mark.asyncio
async def test_evaluate_live_context_end_to_end_grounded_card():
    model = FakeStructuredModel(
        [envelope(SuggestionBatch(suggestions=[suggestion(body="RRF 是排名倒数融合 [cite: s01 ¶1-2]")]))]
    )
    result = await evaluate_live_context(
        USER,
        [other("RRF 是什么？", "others/2")],
        as_of=AS_OF,
        model=model,
        pack=f"# claim notes (1)\n[c:c1 · memory/c1.md] RRF = 排名倒数融合 [cite: {SRC} ¶1-2]",
    )
    assert model.schemas == [SuggestionBatch]
    assert model.include_raw == [True], "include_raw is what makes a parse failure silent"
    assert len(result.suggestions) == 1
    assert result.suggestions[0].citations[0].source_id == SourceId(SRC)
    assert "[cite:" not in result.suggestions[0].body
    assert result.dropped == {
        "unparsed": 0, "repeat": 0, "uncited": 0, "low_confidence": 0, "capped": 0
    }
    # the model saw short handles, never the 32-char id
    human = model.calls[0][1].content
    assert "[cite: s01" in human and SRC not in human


@pytest.mark.asyncio
async def test_evaluate_live_context_is_silent_when_the_model_answers_with_prose():
    """FakeStructuredModel exhausted → parsed None. Gate 1, end to end."""
    result = await evaluate_live_context(
        USER, [owner("随便聊聊")], as_of=AS_OF, model=FakeStructuredModel(), pack="frozen pack"
    )
    assert result.suggestions == ()
    assert result.dropped["unparsed"] == 1
    assert result.token_usage["input_tokens"] == 0


@pytest.mark.asyncio
async def test_evaluate_live_context_window_keeps_only_the_last_n_turns():
    turns = [owner(f"第{i}句") for i in range(6)]
    model = FakeStructuredModel()
    await evaluate_live_context(
        USER, turns, as_of=AS_OF, model=model, pack="frozen pack", turn_window=3
    )
    human = model.calls[0][1].content
    assert "第3句" in human and "第4句" in human and "第5句" in human
    assert "第2句" not in human


@pytest.mark.asyncio
async def test_briefing_scope_does_zero_retrieval():
    """A frozen pack IS the evidence: no embedding, no index call, fastest path."""
    model = FakeStructuredModel()
    await evaluate_live_context(
        USER,
        [owner("说点什么")],
        as_of=AS_OF,
        model=model,
        pack="# claim 注记（1 条）\n[c:c1 · memory/c1.md] 冻结包内容",
    )
    assert "冻结包内容" in model.calls[0][1].content


@pytest.mark.asyncio
async def test_evaluate_live_context_holds_speaker_numbering_across_evaluations():
    a, b = other("A 说", "others/2"), other("B 说", "others/5")
    label_map: dict[str, str] = {}
    model = FakeStructuredModel()
    await evaluate_live_context(
        USER, [a, b], as_of=AS_OF, model=model, pack="frozen", label_map=label_map
    )
    await evaluate_live_context(USER, [b], as_of=AS_OF, model=model, pack="frozen", label_map=label_map)
    assert "Participant2 (others/5): B 说" in model.calls[1][1].content


# ------------------------------------------------------------------- the vocabulary


def test_focus_and_kind_vocabularies_are_closed():
    assert [f.key for f in CONTEXT_FOCUSES] == ["general", "owner", "other"]
    # `web` was added on the owner's sign-off, which the vocabulary requires
    # (architecture.md:123-124). It is here rather than as a flag on the other two because
    # its provenance is a URL rather than a source span, and the client renders it as such.
    assert [k.key for k in SUGGESTION_KINDS] == ["concept", "fact", "web"]
    assert set(live_context_contracts()) == {f.key for f in CONTEXT_FOCUSES}
    assert focus_option("owner").label == "Focus on the owner"
    assert kind_option("fact").key == "fact"
    with pytest.raises(ValueError):
        focus_option("everybody")
    with pytest.raises(ValueError):
        kind_option("opinion")


def test_suggestion_batch_has_a_mechanical_ceiling():
    """max_length=5 is what the model can physically emit; under include_raw a longer list
    becomes a parsing_error → silence. Distinct from the tunable max_suggestions cap."""
    with pytest.raises(Exception):
        SuggestionBatch(suggestions=[suggestion(title=f"c{i}") for i in range(6)])


def test_confidence_is_bounded_by_the_schema():
    for bad in (0, 11, -3):
        with pytest.raises(Exception):
            suggestion(confidence=bad)
