"""Live Context, briefing scope: one frozen pack in, zero-or-a-few grounded cards out.

The FULL-scope lane lives in `live_pipeline.py` now — discover → retrieve → pick, three
stages and two small models, because a lane that retrieves on every tick and asks one big
model to author cards is both expensive and semantically blunt. What stayed here is the
scope that has nothing to throttle and nothing to plan: a **briefing** evaluation, whose
evidence is a pack frozen when the briefing was built. There is no retrieval to skip, no
plan to make and no candidate list to choose between — one round is the whole shape.

What is still shared, and is imported from here by the pipeline: speaker labelling
(`label_turns` / `render_transcript`), which must number a participant the same way on both
paths, and the card-expansion contract (`detail_contract`).

- **Shaped like `fast_recall`.** Prefetch — here, a pack already in hand — then ONE llm round.
  No agentic loop. A card that arrives after the topic moved on is worthless.
- **Silence is mechanical, never persuaded** (architecture.md:14-17). The contract does not
  plead "most segments deserve no suggestion". Four gates in `apply_gates` do that work:
  unparsed → nothing; ungrounded → dropped; under-confident → dropped; then capped by
  confidence. Prose asking a model to restrain itself is the road this repo already
  disproved.
- **Sensitivity is a server-side dial.** The model always scores each suggestion 1-10; the
  threshold lives in `min_confidence`, and it is the same number the pipeline gates on, so a
  deployment tunes one dial whichever scope is running.

**Handles never cross an evaluation boundary.** One `alias_sources` per evaluation (like
fast), and the result is resolved + stripped server-side, so a client never sees an `sNN`.
That is not cosmetic: handles are re-assigned every evaluation, so a leftover `[cite: s03]`
in a previously-shown card would point at a different source next round. `already_shown`
carries only `{kind, title}` for this gate's purposes and is stripped of any `[cite:` residue.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ..domain.canonical import Citation
from ..domain.suggestion import ContextSuggestion, SuggestionBatch, ContextFocus, ResolvedSuggestion
from ..domain.ids import UserId, SourceId
from ..domain.source import ConversationTurn
from ..prompts import prompt
from .citation_alias import (
    alias_sources,
    iter_answer_citations,
    iter_answer_sources,
    strip_citations,
)
from .fast import extract_usage, invoke_config, zero_usage
from .spine import CITE_PRECISE, CLOSE_SUGGESTION, spine

DEFAULT_TURN_WINDOW = 3
#: The briefing round's own emission cap, applied after the gates. Not a session policy knob
#: any more: the full-scope lane delivers exactly one card per tick by construction, so a
#: number that only ever meant something to this one path stopped deserving a dial.
DEFAULT_MAX_SUGGESTIONS = 3
DEFAULT_MIN_CONFIDENCE = 6


# ----------------------------------------------------------------- speaker labelling


def label_turns(
    turns: Sequence[ConversationTurn], label_map: dict[str, str] | None = None
) -> list[str]:
    """Speaker labels for a run of turns: the owner label / a numbered participant / the raw
    speaker string.

    Returns one label per turn, positionally aligned with `turns`.

    `label_map` is the caller's — pass the SAME dict across evaluations and participant
    numbering stays stable for the life of that conversation; pass None (or a fresh dict)
    and numbering restarts from first-appearance order within this call. That distinction
    is the entire reason this function exists: `ContextStreamAdapter` numbers within a
    single `normalize()`, which is right for a stored source but wrong under a sliding
    window — once the first speaker's turns scroll out, participant 1 silently becomes a
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
            out.append(prompt("ingest.owner_label"))
            continue
        if turn.role == "other":
            key = turn.speaker_id or turn.speaker
            if key not in labels:
                # Keep the raw diarization id as a parenthetical alias so provenance back
                # to the capture channel is never lost (same rule as the adapter).
                suffix = (
                    prompt("ingest.speaker_alias", speaker_id=key)
                    if turn.speaker_id
                    else ""
                )
                labels[key] = prompt(
                    "ingest.other_label", n=len(labels) + 1, suffix=suffix
                )
            out.append(labels[key])
            continue
        out.append(turn.speaker)
    return out


def render_transcript(turns: Sequence[ConversationTurn], labels: Sequence[str]) -> str:
    """`<label>: <text>` per line — the same grammar the context_stream adapter stores blocks
    in, so the compile-side and the listening-side speak one vocabulary."""
    return "\n".join(
        prompt("ingest.turn_line", label=label, text=turn.text)
        for label, turn in zip(labels, turns)
    )


# ---------------------------------------------------------------------- the contract

# The closing clause replacing the Q&A one (`spine.CLOSE_SUGGESTION`). The Q&A close ("no
# relevant record is the faithful answer") is right when an owner asked something and wrong
# here in two ways: it presumes a question that was never asked, and it would have the model
# emit a card literally reading "no relevant record". The suggestion close states the output
# shape instead; the confidence + citation gates, not that sentence, are what actually
# produce silence.

FOCUSES: tuple[ContextFocus, ...] = ("general", "owner", "other")

_FOCUS_CLAUSE_KEYS: dict[ContextFocus, str] = {
    focus: f"recall.suggestion.focus.{focus}" for focus in FOCUSES
}


def _live_context_contract(focus: ContextFocus) -> str:
    return prompt(
        "recall.suggestion.contract_head",
        focus=prompt(_FOCUS_CLAUSE_KEYS[focus]),
    ) + spine(CITE_PRECISE, CLOSE_SUGGESTION)


def live_context_contracts() -> dict[ContextFocus, str]:
    """I5: one byte-stable System per focus. focus rides the System tier because it is
    posture, not data — and three fixed strings keep the provider cache earnable, which one
    string interpolated per request would not. Assembled per call (cheap) rather than at
    import, so a startup-registered prompt overlay reaches them."""
    return {focus: _live_context_contract(focus) for focus in FOCUSES}


# I5, and deliberately NOT built on `spine()`. Every other contract here answers from wide
# recall, which is what the spine exists to discipline: near-miss subjects mixed into the
# evidence, provenance as the way to tell them apart, `[cite:]` as the way back. Expansion
# has none of that shape — the owner tapped one card, and its own citations resolve to
# exact verbatim blocks that were fetched, not retrieved. There is no other subject to
# confuse it with and no handle to cite, because the citations are already attached
# structurally. What it does keep is the red line (assertion strength = evidence strength),
# restated here rather than inherited, because that one is not about retrieval at all.
def detail_contract() -> str:
    """The expansion contract (I5, and deliberately NOT built on `spine()`)."""
    return prompt("recall.suggestion.detail_contract")


_CITE_RESIDUE_RE = re.compile(r"\[cite:[^\]]*\]?")


def _shown_line(item) -> str | None:
    """`- [kind] title` for one already-shown card, or None if it has no title.

    Accepts a ResolvedSuggestion/ContextSuggestion or a plain mapping (the WS layer replays client-held JSON).
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


def live_context_human(
    transcript: str,
    *,
    as_of: datetime,
    pack: str,
    profile: str | None = None,
    already_shown: Sequence = (),
) -> str:
    """The volatile Human turn: profile → evidence → already shown → as_of → transcript (LAST).

    Deliberately NOT `recall_human` (fast.py): that assembler closes with an "owner input:"
    label, which would hang a multi-speaker transcript under a label saying the owner said
    it — mislabelling every interlocutor line as the owner's, under a feature whose entire
    focus axis is speaker attribution.

    Same tail discipline as fast: the live thing (here, the transcript) sits in the
    attention-hot tail below the evidence wall, not above it. Section headers reuse the
    contract's exact names; what each IS is explained once, in the byte-stable System."""
    sections: list[str] = []
    if profile:
        sections.append(f"{prompt('recall.section.profile_header')}\n{profile}")
    # A frozen pack IS the evidence; zero retrieval, zero embedding this round.
    sections.append(pack.strip())
    shown = [line for line in (_shown_line(i) for i in already_shown) if line]
    if shown:
        sections.append(
            prompt("recall.section.already_shown_header") + "\n" + "\n".join(shown)
        )
    transcript_header = prompt(
        "recall.section.transcript_header", turns=transcript.count(chr(10)) + 1
    )
    return (
        "\n\n".join(sections)
        + f"\n\nas_of: {as_of.isoformat()}\n{transcript_header}\n"
        + transcript
    )


def live_context_messages(
    transcript: str,
    *,
    as_of: datetime,
    pack: str,
    focus: ContextFocus = "general",
    profile: str | None = None,
    already_shown: Sequence = (),
) -> list[BaseMessage]:
    """[SystemMessage(the focus's fixed contract), HumanMessage(evidence → transcript)]."""
    human = live_context_human(
        transcript,
        as_of=as_of,
        pack=pack,
        profile=profile,
        already_shown=already_shown,
    )
    if focus not in _FOCUS_CLAUSE_KEYS:
        raise ValueError(f"unknown suggestion focus: {focus!r}")
    return [
        SystemMessage(content=_live_context_contract(focus)),
        HumanMessage(content=human),
    ]


# ----------------------------------------------------------------------- the gates


@dataclass(frozen=True)
class LiveContextResult:
    """One briefing-scope evaluation, whole."""

    suggestions: tuple[ResolvedSuggestion, ...]
    token_usage: dict[str, int]
    # Why the model's emission shrank, by reason. Zeroes everywhere with an empty `suggestions`
    # means the model chose silence; a non-zero reason means a gate did.
    dropped: dict[str, int] = field(default_factory=dict)


def _resolve_suggestion(suggestion: ContextSuggestion, handle_map: dict[str, str]) -> ResolvedSuggestion:
    """Lift the body's `[cite: …]` markers into structured citations, then strip them.

    A span whose handle is not in the map (a hallucinated or garbled `sNN`) yields no
    citation — it is not grounding, so it must not become one. Duplicates collapse,
    first-appearance order preserved."""
    citations: list[Citation] = []
    seen: set[tuple[str, int, int]] = set()
    for sid, start, end in iter_answer_citations(suggestion.body):
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
    return ResolvedSuggestion(
        kind=suggestion.kind,
        title=strip_citations(suggestion.title),
        body=strip_citations(suggestion.body),
        trigger=strip_citations(suggestion.trigger),
        confidence=suggestion.confidence,
        citations=citations,
    )


def apply_gates(
    parsed: SuggestionBatch | None,
    handle_map: dict[str, str],
    *,
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS,
    min_confidence: int = DEFAULT_MIN_CONFIDENCE,
    already_shown: Sequence = (),
) -> tuple[list[ResolvedSuggestion], dict[str, int]]:
    """The four mechanical gates, in order. Pure — no I/O, hence not a coroutine.

    1. `parsed is None` → zero suggestions. Under `include_raw=True` a parse failure lands here
       too: a background listening feature degrades to silence, it never 500s onto a pair
       of context clients.
    2. **Grounding.** A body with no `[cite: …]` that resolves back to a real source is
       dropped. An ungrounded suggestion is not a suggestion by definition. Same shape as the repo's
       existing `compile/gate.py` discipline.
    3. **Confidence.** Below `min_confidence` → dropped. The dial that makes sensitivity
       tunable without re-running anything.
    4. **Cap.** Sort by confidence descending (stable, so equal scores keep the model's
       own order) and truncate to `max_suggestions`.

    A suggestion already shown this conversation is dropped ahead of the four, by exact
    (kind, title): `already_shown` has to be load-bearing mechanically, because merely
    showing the model a list of what it already said and hoping is the persuasion road."""
    dropped = {"unparsed": 0, "repeat": 0, "uncited": 0, "low_confidence": 0, "capped": 0}
    if parsed is None:  # gate 1
        dropped["unparsed"] = 1
        return [], dropped

    seen_shown = {_shown_key(i) for i in already_shown}
    kept: list[ResolvedSuggestion] = []
    for suggestion in parsed.suggestions:
        if (suggestion.kind.strip(), suggestion.title.strip()) in seen_shown:
            dropped["repeat"] += 1
            continue
        if not any(sid in handle_map for sid in iter_answer_sources(suggestion.body)):  # gate 2
            dropped["uncited"] += 1
            continue
        if suggestion.confidence < min_confidence:  # gate 3
            dropped["low_confidence"] += 1
            continue
        kept.append(_resolve_suggestion(suggestion, handle_map))

    kept.sort(key=lambda c: -c.confidence)  # gate 4 (stable: ties keep emission order)
    if len(kept) > max_suggestions:
        dropped["capped"] = len(kept) - max_suggestions
        kept = kept[:max_suggestions]
    return kept, dropped


# -------------------------------------------------------------------------- engine


async def evaluate_live_context(
    user_id: UserId,
    turns: Sequence[ConversationTurn],
    *,
    as_of: datetime,
    model: BaseChatModel,
    pack: str,
    focus: ContextFocus = "general",
    profile: str | None = None,
    already_shown: Sequence = (),
    label_map: dict[str, str] | None = None,
    turn_window: int = DEFAULT_TURN_WINDOW,
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS,
    min_confidence: int = DEFAULT_MIN_CONFIDENCE,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> LiveContextResult:
    """One briefing-scope evaluation: assemble → ONE structured llm round → gates.

    The frozen briefing pack IS the evidence — zero retrieval, zero embedding, which is
    both the fastest path and the cleaner architecture. It is also the only correct one: the
    port layer has no source filter, so briefing's own `search_knowledge` post-filters and
    routinely filters to zero on a large KB, while pre-loading is the entire point of a
    briefing. Full scope goes through `live_pipeline.evaluate_live_pipeline` instead.

    The whole transcript window is always sent regardless of `focus`; `focus` never filters
    by speaker. Dropping the other party's lines would destroy the context needed to
    understand the owner's, and vice versa — focus is attention direction, expressed in the
    (byte-stable, per-focus) System contract.

    `label_map`, when passed, is the caller's and is MUTATED in place — hold one per
    connection and a participant number stays the same person across evaluations (see
    `label_turns`)."""
    recent = list(turns)[-turn_window:] if turn_window > 0 else list(turns)
    labels = label_turns(recent, label_map)
    transcript = render_transcript(recent, labels)

    system, human = live_context_messages(
        transcript,
        as_of=as_of,
        focus=focus,
        pack=pack,
        profile=profile,
        already_shown=already_shown,
    )
    # One-shot aliasing per evaluation, like fast — NOT a SessionAliaser. A session
    # aliaser is built to hold one handle steady across the rounds of a single ask; spread
    # over a whole WS connection it blows straight past s99, and once handles stop being
    # short and stable the entire reason aliasing exists — a 32-char id being
    # mis-transcribed — comes back.
    aliased_human, handle_map = alias_sources(str(human.content))

    structured = model.with_structured_output(SuggestionBatch, include_raw=True)
    raw = await structured.ainvoke(
        [system, HumanMessage(content=aliased_human)],
        config=invoke_config("recall.suggestion", callbacks, trace_metadata),
    )
    if isinstance(raw, Mapping):
        parsed = raw.get("parsed")
        message = raw.get("raw")
    else:  # a model handing back the bare object despite include_raw=True
        parsed, message = raw, None
    if parsed is not None and not isinstance(parsed, SuggestionBatch):
        parsed = None  # anything but the schema is a parse failure → silence
    usage = extract_usage(message) if message is not None else zero_usage()

    suggestions, dropped = apply_gates(
        parsed,
        handle_map,
        max_suggestions=max_suggestions,
        min_confidence=min_confidence,
        already_shown=already_shown,
    )
    return LiveContextResult(
        suggestions=tuple(suggestions), token_usage=usage, dropped=dropped
    )
