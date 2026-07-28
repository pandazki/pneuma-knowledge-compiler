"""AI Cue — the listening engine: a live transcript in, zero-or-a-few cards out.

Every other recall mode is pulled by a question. This one is pushed by the conversation
itself, and that single inversion sets every design choice here:

- **Shaped like `fast_recall`, not like deep/briefing.** Prefetch, then ONE llm round. No
  agentic loop. A card that arrives after the topic moved on is worthless, so latency is
  not a nice-to-have, it is the feature.
- **Silence is mechanical, never persuaded** (architecture.md:14-17). The contract does
  not plead "most segments deserve no cue". Four gates in `apply_gates` do that work:
  unparsed → nothing; ungrounded → dropped; under-confident → dropped; then capped by
  confidence. Prose asking a model to restrain itself is the road this repo already
  disproved.
- **Sensitivity is a server-side dial.** The model always scores each cue 1-10; the
  threshold lives in `min_confidence`. Retrieval scores could not do this job: `_rrf_scores`
  is pure reciprocal rank (a top hit is ~0.0167 regardless of how well it matched), so
  thresholding on it thresholds on nothing. A confidence already attached to a card can be
  re-thresholded without re-running anything.

**Retrieval is a per-turn union, not a cross-turn RRF fusion.** RRF fuses several
retrievers over ONE query; fusing across DIFFERENT queries introduces ubiquity bias — a
source that ranks mid-table on every turn (the owner profile doc, a long background
transcript) accumulates past the source that ranked #1 on exactly one turn, and that
sharp single-turn signal is precisely the one worth interrupting for. So: top-k per turn,
then union. The window union is re-`_coalesce_overlapping`d because each turn's
`rag_recall` coalesced only within itself — turn A's `[6,7]` and turn B's `[6,9]` are
different keys and would otherwise render as two near-duplicate passages.
`expand_and_merge` runs ONCE over the union (it rebuilds its source cache per call, so
per-turn calls would multiply PG loads by N).

**Handles never cross an evaluation boundary.** One `alias_sources` per evaluation (like
fast), and the result is resolved + stripped server-side, so a client never sees an `sNN`.
That is not cosmetic: handles are re-assigned every evaluation, so a leftover `[cite: s03]`
in a previously-shown card would point at a different source next round. `already_shown`
carries only `{kind, title}` and is stripped of any `[cite:` residue.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ..domain.canonical import Citation
from ..domain.cue import Cue, CueBatch, CueFocus, ResolvedCue
from ..domain.ids import UserId, SourceId
from ..domain.source import ConversationTurn
from ..ports.claim_index import ClaimLexicalIndex, ClaimVectorIndex
from ..ports.content_store import ContentStore
from ..ports.lexical_index import LexicalIndex
from ..ports.vector_index import VectorIndex
from .assembly import expand_and_merge, order_lost_in_middle
from .citation_alias import (
    alias_sources,
    iter_answer_citations,
    iter_answer_sources,
    strip_citations,
)
from .fast import (
    RetrievedClaim,
    _render_window_section,
    extract_usage,
    invoke_config,
    render_claims,
    retrieve_claims,
    zero_usage,
)
from .rag import RecallHit, _coalesce_overlapping, rag_recall
from .spine import CITE_PRECISE, spine

DEFAULT_TURN_WINDOW = 3
DEFAULT_PER_TURN_CLAIMS = 2
DEFAULT_PER_TURN_WINDOWS = 2
DEFAULT_MAX_CUES = 3
DEFAULT_MIN_CONFIDENCE = 6

OWNER_LABEL = "本人"


# ----------------------------------------------------------------- speaker labelling


def label_turns(
    turns: Sequence[ConversationTurn], label_map: dict[str, str] | None = None
) -> list[str]:
    """Speaker labels for a run of turns: 本人 / 参与者N / the raw speaker string.

    Returns one label per turn, positionally aligned with `turns`.

    `label_map` is the caller's — pass the SAME dict across evaluations and 参与者N
    numbering stays stable for the life of that conversation; pass None (or a fresh dict)
    and numbering restarts from first-appearance order within this call. That distinction
    is the entire reason this function exists: `ContextStreamAdapter` numbers within a
    single `normalize()`, which is right for a stored source but wrong under a sliding
    window — once the first speaker's turns scroll out, 参与者1 silently becomes a
    DIFFERENT person between one evaluation and the next. A caller that holds a
    connection-lifetime map never has that happen.

    (`ContextStreamAdapter` could be refactored onto this helper — the labelling rule is
    identical, parenthetical alias included. It deliberately is not: that path is tested
    and shipped, and churning it buys nothing here.)

    Vocabulary is `domain/source.py`'s `SpeakerRole`: an `unknown` turn falls back to its
    raw speaker string and makes no owner/other claim — guessing attribution from the
    text is exactly what produced identity errors before."""
    labels: dict[str, str] = label_map if label_map is not None else {}
    out: list[str] = []
    for turn in turns:
        if turn.role == "owner":
            out.append(OWNER_LABEL)
            continue
        if turn.role == "other":
            key = turn.speaker_id or turn.speaker
            if key not in labels:
                # Keep the raw diarization id as a parenthetical alias so provenance back
                # to the capture channel is never lost (same rule as the adapter).
                suffix = f"（{key}）" if turn.speaker_id else ""
                labels[key] = f"参与者{len(labels) + 1}{suffix}"
            out.append(labels[key])
            continue
        out.append(turn.speaker)
    return out


def render_transcript(turns: Sequence[ConversationTurn], labels: Sequence[str]) -> str:
    """`<label>：<text>` per line — the same grammar the context_stream adapter stores blocks
    in, so the compile-side and the listening-side speak one vocabulary."""
    return "\n".join(f"{label}：{turn.text}" for label, turn in zip(labels, turns))


# ---------------------------------------------------------------------- the contract

# The closing clause replacing the Q&A one. The Q&A close ("「无相关记录」就是忠实的答案")
# is right when a owner asked something and wrong here in two ways: it presumes a question
# that was never asked, and it would have the model push a card literally reading
# 「无相关记录」onto the lens. This states the output shape instead; the confidence + citation
# gates, not this sentence, are what actually produce silence.
CLOSE_CUE = (
    "- 一张卡片是一次打断：它凭空出现在本人眼前，而对话还在继续。卡片必须自身成立——\n"
    "  不复述对话、不预告、不写「无相关记录」这类空卡；没有可写的卡片时，cues 就是空列表，\n"
    "  空列表是本接口的正常返回值。"
)

_FOCUS_CLAUSE: dict[CueFocus, str] = {
    "general": (
        "**本次提词范围**：整段转录里任何值得提示的概念或事实，不论出自谁口。"
    ),
    "owner": (
        "**本次提词范围**：只为「本人」说出的内容出卡片。参与者的发言照旧全文读入，\n"
        "但只作理解上下文——不为参与者单独提到的东西出卡片。"
    ),
    "other": (
        "**本次提词范围**：只为「参与者」说出的内容出卡片。本人的发言照旧全文读入，\n"
        "但只作理解上下文——不为本人单独提到的东西出卡片。"
    ),
}

_CUE_HEAD = """\
# Pneuma 上下文流提示

你在观察用户主动接入的一段工作上下文流，内容逐轮送到你面前。**没有人在向你提问**：
触发你的不是一个问题，而是上下文里刚刚出现的东西。产物不是一段回答，而是零张或
几张小卡片，显示在用户的知识工作台中。

随转录一并送到的是从本人个人知识库里取出的证据（claim 注记 + 原文摘录），它们由最近
几轮转录各自检索得来。

两种卡片（`kind`）：

- `concept`——对话里出现了一个知识库里有的概念 / 人 / 事，卡片说明它是什么。
- `fact`——对话里出现了一个知识库能直接回答的具体问题或待确认的事实，卡片给出答案。

每张卡片自带 `confidence`（1-10）。它不是修辞：服务端按阈值机械过滤并据此排序，低分卡片
不会展示。据实打分、把不确定的打低，比不写它更有用。

`trigger` 逐字摘自下面的转录——它是这张卡片弹出来的理由，前端拿它做高亮。

转录里**每一位说话人**的话都是语音识别的产物，不只是本人的——陌生参与者的人名与术语
最容易被听错。认主体时把这种音近的出入算作同一所指。

{focus}

以下作答姿态与问答模式共用。本场景没有提问，其中「本人所求」一律读作「对话里刚出现、
值得提示的那个东西」。

"""


def _cue_contract(focus: CueFocus) -> str:
    return _CUE_HEAD.format(focus=_FOCUS_CLAUSE[focus]) + spine(CITE_PRECISE, CLOSE_CUE)


# I5: one byte-stable System per focus, all computed at module load. focus rides the
# System tier because it is posture, not data — and three fixed strings keep the provider
# cache earnable, which one string interpolated per request would not.
CUE_CONTRACTS: dict[CueFocus, str] = {
    focus: _cue_contract(focus) for focus in ("general", "owner", "other")
}


# I5, and deliberately NOT built on `spine()`. Every other contract here answers from wide
# recall, which is what the spine exists to discipline: near-miss subjects mixed into the
# evidence, provenance as the way to tell them apart, `[cite:]` as the way back. Expansion
# has none of that shape — the owner tapped one card, and its own citations resolve to
# exact verbatim blocks that were fetched, not retrieved. There is no other subject to
# confuse it with and no handle to cite, because the citations are already attached
# structurally. What it does keep is the red line (assertion strength = evidence strength),
# restated here rather than inherited, because that one is not about retrieval at all.
DETAIL_CONTRACT = """\
# Pneuma 上下文提示 · 展开

本人刚刚看到一张提示卡片，并要求展开它。下面给出那张卡片本身，以及它引用的
来源原文——**逐字取自本人的个人知识库，没有经过检索或改写**。

在这些原文的范围内把卡片讲透：补上卡片因为篇幅省掉的细节、条件、数字与出处上下文。

- 断言强度以证据强度为准。原文没写的，就说原文没写；不要用常识补全，也不要引入原文之外
  的信息。
- 原文若与卡片有出入，以原文为准并明确指出这一点。
- 直接写正文，不要重复卡片标题，不要写开场白。
"""


# ------------------------------------------------------------------------- assembly


@dataclass(frozen=True)
class CueEvidence:
    """The per-turn retrieval union feeding one evaluation.

    `claim_turn` / `source_turn` record WHICH transcript turn surfaced a piece of
    evidence. `source_turn` is per-source (earliest turn wins), deliberately coarser than
    per-span: spans get coalesced and expanded downstream, so a span-keyed map would go
    stale, while "this turn is what pulled this source in" survives every merge."""

    claims: tuple[RetrievedClaim, ...] = ()
    windows: tuple = ()
    claim_turn: dict[str, int] = field(default_factory=dict)
    source_turn: dict[str, int] = field(default_factory=dict)


async def gather_evidence(
    user_id: UserId,
    queries: Sequence[str],
    *,
    claim_lexical: ClaimLexicalIndex | None,
    claim_vectors: ClaimVectorIndex | None,
    embeddings,  # langchain_core.embeddings.Embeddings
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    content: ContentStore | None = None,
    per_turn_claims: int = DEFAULT_PER_TURN_CLAIMS,
    per_turn_windows: int = DEFAULT_PER_TURN_WINDOWS,
) -> CueEvidence:
    """Per-turn retrieval → union → re-coalesce → assemble. ONE embedding round trip.

    All N turn queries go through a single `aembed_documents`, then every index call fans
    out concurrently with its vector pre-supplied (that is what the `query_embedding`
    parameter on `retrieve_claims` / `rag_recall` is for). Embedding per turn would make
    N=3 cost six sequential OpenRouter round trips, which for a latency-shaped feature is
    the whole budget.

    Union, NOT RRF across turns — see the module docstring on ubiquity bias."""
    queries = [q for q in queries if q and q.strip()]
    if not queries:
        return CueEvidence()

    embedded = await embeddings.aembed_documents(list(queries))

    claim_jobs = []
    window_jobs = []
    do_claims = claim_lexical is not None and claim_vectors is not None and per_turn_claims > 0
    do_windows = lexical is not None and vectors is not None and per_turn_windows > 0
    for query, vector in zip(queries, embedded):
        if do_claims:
            claim_jobs.append(
                retrieve_claims(
                    user_id,
                    query,
                    claim_lexical=claim_lexical,
                    claim_vectors=claim_vectors,
                    embeddings=embeddings,
                    limit=per_turn_claims,
                    query_embedding=vector,
                )
            )
        if do_windows:
            window_jobs.append(
                rag_recall(
                    user_id,
                    query,
                    lexical=lexical,
                    vectors=vectors,
                    embeddings=embeddings,
                    limit=per_turn_windows,
                    query_embedding=vector,
                )
            )

    claim_lists, window_lists = await asyncio.gather(
        asyncio.gather(*claim_jobs), asyncio.gather(*window_jobs)
    )

    # Claim union: first turn to surface a (document_path, anchor) owns it.
    claims: list[RetrievedClaim] = []
    claim_turn: dict[str, int] = {}
    source_turn: dict[str, int] = {}
    seen_claims: set[tuple[str, str]] = set()
    for turn_index, batch in enumerate(claim_lists):
        for claim in batch:
            key = (claim.document_path, str(claim.anchor))
            if key in seen_claims:
                continue
            seen_claims.add(key)
            claims.append(claim)
            claim_turn.setdefault(str(claim.anchor), turn_index)
            for cit in claim.citations:
                source_turn.setdefault(str(cit.source_id), turn_index)

    # Window union: concatenate, then re-coalesce ACROSS turns (each rag_recall only
    # coalesced within its own call), then one assembly pass over the whole union.
    raw_hits: list[RecallHit] = []
    for turn_index, batch in enumerate(window_lists):
        for hit in batch:
            source_turn.setdefault(str(hit.source_id), turn_index)
            raw_hits.append(hit)

    windows: list = []
    if raw_hits:
        merged = _coalesce_overlapping(raw_hits)
        merged.sort(key=lambda h: (-h.score, str(h.source_id), h.block_start))
        if content is None:
            windows = merged
        else:
            windows = order_lost_in_middle(
                await expand_and_merge(
                    merged, content=content, user_id=user_id
                )
            )

    return CueEvidence(
        claims=tuple(claims),
        windows=tuple(windows),
        claim_turn=claim_turn,
        source_turn=source_turn,
    )


_CITE_RESIDUE_RE = re.compile(r"\[cite:[^\]]*\]?")


def _shown_line(item) -> str | None:
    """`- [kind] title` for one already-shown card, or None if it has no title.

    Accepts a ResolvedCue/Cue or a plain mapping (the WS layer replays client-held JSON).
    Any `[cite:` residue is stripped MECHANICALLY, not asked for: a handle from a previous
    evaluation resolves to a different source in this one."""
    if isinstance(item, Mapping):
        kind = str(item.get("kind") or "").strip()
        title = str(item.get("title") or "").strip()
    else:
        kind = str(getattr(item, "kind", "") or "").strip()
        title = str(getattr(item, "title", "") or "").strip()
    title = _CITE_RESIDUE_RE.sub("", title).strip()
    if not title:
        return None
    return f"- [{kind}] {title}" if kind else f"- {title}"


def _shown_key(item) -> tuple[str, str]:
    if isinstance(item, Mapping):
        kind = str(item.get("kind") or "")
        title = str(item.get("title") or "")
    else:
        kind = str(getattr(item, "kind", "") or "")
        title = str(getattr(item, "title", "") or "")
    return kind.strip(), _CITE_RESIDUE_RE.sub("", title).strip()


def cue_human(
    transcript: str,
    *,
    as_of: datetime,
    claims: Sequence[RetrievedClaim] = (),
    windows: Sequence = (),
    pack: str | None = None,
    profile: str | None = None,
    already_shown: Sequence = (),
) -> str:
    """The volatile Human turn: 画像 → evidence → 已提示过 → as_of → 转录 (LAST).

    Deliberately NOT `recall_human` (fast.py): that assembler closes with
    `本人输入：{question}`, which would hang a multi-speaker transcript under a label
    saying the owner said it — mislabelling every interlocutor line as the owner's,
    under a feature whose entire focus axis is speaker attribution.

    Same tail discipline as fast: the live thing (here, the transcript) sits in the
    attention-hot tail below the evidence wall, not above it. Section headers reuse the
    contract's exact names; what each IS is explained once, in the byte-stable System."""
    sections: list[str] = []
    if profile:
        sections.append(f"# 本人画像\n{profile}")
    if pack is not None:
        # briefing scope: a frozen pack IS the evidence; zero retrieval this round.
        sections.append(pack.strip())
    else:
        sections.append(
            f"# claim 注记（{len(claims)} 条）\n"
            f"{render_claims(list(claims)) or '（本次检索无命中）'}"
        )
        if windows:
            sections.append(
                f"# 原文摘录（{len(windows)} 条）\n{_render_window_section(list(windows))}"
            )
    shown = [line for line in (_shown_line(i) for i in already_shown) if line]
    if shown:
        sections.append("# 本次对话已提示过（同一张不再出）\n" + "\n".join(shown))
    return (
        "\n\n".join(sections)
        + f"\n\nas_of: {as_of.isoformat()}\n# 对话转录（最近 {transcript.count(chr(10)) + 1} 轮）\n"
        + transcript
    )


def cue_messages(
    transcript: str,
    *,
    as_of: datetime,
    focus: CueFocus = "general",
    claims: Sequence[RetrievedClaim] = (),
    windows: Sequence = (),
    pack: str | None = None,
    profile: str | None = None,
    already_shown: Sequence = (),
) -> list[BaseMessage]:
    """[SystemMessage(the focus's fixed contract), HumanMessage(evidence → transcript)]."""
    human = cue_human(
        transcript,
        as_of=as_of,
        claims=claims,
        windows=windows,
        pack=pack,
        profile=profile,
        already_shown=already_shown,
    )
    if focus not in CUE_CONTRACTS:
        raise ValueError(f"unknown cue focus: {focus!r}")
    return [SystemMessage(content=CUE_CONTRACTS[focus]), HumanMessage(content=human)]


# ----------------------------------------------------------------------- the gates


@dataclass(frozen=True)
class CueResult:
    cues: tuple[ResolvedCue, ...]
    token_usage: dict[str, int]
    # Why the model's emission shrank, by reason. Zeroes everywhere with an empty `cues`
    # means the model chose silence; a non-zero reason means a gate did.
    dropped: dict[str, int] = field(default_factory=dict)
    used_claims: tuple[RetrievedClaim, ...] = ()
    used_windows: tuple = ()
    # Which transcript turn (0-based within the evaluated window) surfaced each piece of
    # evidence — see CueEvidence.
    claim_turn: dict[str, int] = field(default_factory=dict)
    source_turn: dict[str, int] = field(default_factory=dict)


def _resolve_cue(cue: Cue, handle_map: dict[str, str]) -> ResolvedCue:
    """Lift the body's `[cite: …]` markers into structured citations, then strip them.

    A span whose handle is not in the map (a hallucinated or garbled `sNN`) yields no
    citation — it is not grounding, so it must not become one. Duplicates collapse,
    first-appearance order preserved."""
    citations: list[Citation] = []
    seen: set[tuple[str, int, int]] = set()
    for sid, start, end in iter_answer_citations(cue.body):
        real = handle_map.get(sid)
        if real is None:
            continue
        key = (real, start, end)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(source_id=SourceId(real), block_start=start, block_end=end)
        )
    return ResolvedCue(
        kind=cue.kind,
        title=strip_citations(cue.title),
        body=strip_citations(cue.body),
        trigger=strip_citations(cue.trigger),
        confidence=cue.confidence,
        citations=citations,
    )


def apply_gates(
    parsed: CueBatch | None,
    handle_map: dict[str, str],
    *,
    max_cues: int = DEFAULT_MAX_CUES,
    min_confidence: int = DEFAULT_MIN_CONFIDENCE,
    already_shown: Sequence = (),
) -> tuple[list[ResolvedCue], dict[str, int]]:
    """The four mechanical gates, in order. Pure — no I/O, hence not a coroutine.

    1. `parsed is None` → zero cues. Under `include_raw=True` a parse failure lands here
       too: a background listening feature degrades to silence, it never 500s onto a pair
       of context clients.
    2. **Grounding.** A body with no `[cite: …]` that resolves back to a real source is
       dropped. An ungrounded cue is not a cue by definition. Same shape as the repo's
       existing `compile/gate.py` discipline.
    3. **Confidence.** Below `min_confidence` → dropped. The dial that makes sensitivity
       tunable without re-running anything.
    4. **Cap.** Sort by confidence descending (stable, so equal scores keep the model's
       own order) and truncate to `max_cues`.

    A cue already shown this conversation is dropped ahead of the four, by exact
    (kind, title): `already_shown` has to be load-bearing mechanically, because merely
    showing the model a list of what it already said and hoping is the persuasion road."""
    dropped = {"unparsed": 0, "repeat": 0, "uncited": 0, "low_confidence": 0, "capped": 0}
    if parsed is None:  # gate 1
        dropped["unparsed"] = 1
        return [], dropped

    seen_shown = {_shown_key(i) for i in already_shown}
    kept: list[ResolvedCue] = []
    for cue in parsed.cues:
        if (cue.kind.strip(), cue.title.strip()) in seen_shown:
            dropped["repeat"] += 1
            continue
        if not any(sid in handle_map for sid in iter_answer_sources(cue.body)):  # gate 2
            dropped["uncited"] += 1
            continue
        if cue.confidence < min_confidence:  # gate 3
            dropped["low_confidence"] += 1
            continue
        kept.append(_resolve_cue(cue, handle_map))

    kept.sort(key=lambda c: -c.confidence)  # gate 4 (stable: ties keep emission order)
    if len(kept) > max_cues:
        dropped["capped"] = len(kept) - max_cues
        kept = kept[:max_cues]
    return kept, dropped


# -------------------------------------------------------------------------- engine


async def cue_once(
    user_id: UserId,
    turns: Sequence[ConversationTurn],
    *,
    as_of: datetime,
    model: BaseChatModel,
    embeddings=None,  # langchain_core.embeddings.Embeddings; unused when `pack` is given
    claim_lexical: ClaimLexicalIndex | None = None,
    claim_vectors: ClaimVectorIndex | None = None,
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    content: ContentStore | None = None,
    focus: CueFocus = "general",
    profile: str | None = None,
    pack: str | None = None,
    already_shown: Sequence = (),
    label_map: dict[str, str] | None = None,
    turn_window: int = DEFAULT_TURN_WINDOW,
    per_turn_claims: int = DEFAULT_PER_TURN_CLAIMS,
    per_turn_windows: int = DEFAULT_PER_TURN_WINDOWS,
    max_cues: int = DEFAULT_MAX_CUES,
    min_confidence: int = DEFAULT_MIN_CONFIDENCE,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> CueResult:
    """One evaluation: prefetch → assemble → ONE structured llm round → gates.

    Two evidence scopes, chosen by whether `pack` is supplied:

    - **full** (`pack is None`): per-turn retrieval over the last `turn_window` turns.
    - **briefing** (`pack` given): the frozen briefing pack IS the evidence — zero
      retrieval, zero embedding, which is both the fastest path and the cleaner
      architecture. It is also the only correct one: the port layer has no source filter,
      so briefing's own `search_knowledge` post-filters and routinely filters to zero on a
      large KB, while pre-loading is the entire point of a briefing.

    The whole transcript window is always sent regardless of `focus`; `focus` never
    filters by speaker. Dropping the other party's lines would destroy the context needed
    to understand the owner's, and vice versa — focus is attention direction, expressed
    in the (byte-stable, per-focus) System contract.

    `label_map`, when passed, is the caller's and is MUTATED in place — hold one per
    connection and 参与者N stays the same person across evaluations (see `label_turns`)."""
    recent = list(turns)[-turn_window:] if turn_window > 0 else list(turns)
    labels = label_turns(recent, label_map)
    transcript = render_transcript(recent, labels)

    evidence = CueEvidence()
    if pack is None and embeddings is not None:
        evidence = await gather_evidence(
            user_id,
            [t.text for t in recent],
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            lexical=lexical,
            vectors=vectors,
            content=content,
            per_turn_claims=per_turn_claims,
            per_turn_windows=per_turn_windows,
        )

    system, human = cue_messages(
        transcript,
        as_of=as_of,
        focus=focus,
        claims=evidence.claims,
        windows=evidence.windows,
        pack=pack,
        profile=profile,
        already_shown=already_shown,
    )
    # One-shot aliasing per evaluation, like fast — NOT a SessionAliaser. A session
    # aliaser is built to hold one handle steady across the rounds of a single ask; spread
    # over a whole WS connection (~40 evaluations × ~8 sources in a 45-minute conversation)
    # it blows straight past s99, and once handles stop being short and stable the entire
    # reason aliasing exists — a 32-char id being mis-transcribed — comes back.
    aliased_human, handle_map = alias_sources(str(human.content))

    structured = model.with_structured_output(CueBatch, include_raw=True)
    raw = await structured.ainvoke(
        [system, HumanMessage(content=aliased_human)],
        config=invoke_config("recall.cue", callbacks, trace_metadata),
    )
    if isinstance(raw, Mapping):
        parsed = raw.get("parsed")
        message = raw.get("raw")
    else:  # a model handing back the bare object despite include_raw=True
        parsed, message = raw, None
    if parsed is not None and not isinstance(parsed, CueBatch):
        parsed = None  # anything but the schema is a parse failure → silence
    usage = extract_usage(message) if message is not None else zero_usage()

    cues, dropped = apply_gates(
        parsed,
        handle_map,
        max_cues=max_cues,
        min_confidence=min_confidence,
        already_shown=already_shown,
    )
    return CueResult(
        cues=tuple(cues),
        token_usage=usage,
        dropped=dropped,
        used_claims=evidence.claims,
        used_windows=evidence.windows,
        claim_turn=dict(evidence.claim_turn),
        source_turn=dict(evidence.source_turn),
    )
