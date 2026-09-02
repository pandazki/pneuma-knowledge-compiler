"""fast mode — canonical-annotation-dense recall (architecture.md §7; milestone M4).

Three seals, all mechanical (§0 discipline 1), not prose pleas:

1. **Fixed answer contract.** The SystemMessage is `selector_contract()` verbatim — a
   byte-stable string (I5). It is a top-down account (identity → the three evidence forms
   → world-facts about the evidence → answer shape), not a rule list; it never carries
   a timestamp, the question, or claim content, so the provider cache is earned by
   assembly order.
2. **Annotation cap + dedup.** Claims come from a dual-path retrieval (Meili claims +
   Qdrant claim layer) fused by RRF, deduped by (document_path, anchor), then capped to
   `cap` (default 40) before rendering.
3. **Everything volatile in the Human turn, question LAST.** Evidence sections render
   first (glance → claim notes → derived episode summaries → raw excerpts → any fully-read
   documents), then as_of +
   question close the message — the live ask sits in the attention-hot tail instead of
   drowning above a 40-claim wall.

On top of retrieval the lane carries the knowledge base GLANCE (canonical_glance.py) — the
library's layout, present for every question — plus one concurrent selection pass that may
ask for a handful of documents to be read in full. Both are additive: with no canonical
documents supplied the lane is byte-for-byte the retrieval-only one it has always been, and
a failed selection pass degrades to exactly that. See `fast_recall`.

`token_usage` passes through the provider's cache_read / cache_creation fields
(defaulting to 0 when absent — scripted/keyless models report 0).
"""

from __future__ import annotations

import asyncio
import base64
import json
import hashlib
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.content import create_image_block
from pydantic import BaseModel, Field

from ..canonical_glance import (
    display_identity,
    document_definition,
    document_ledger_line,
    render_canonical_glance,
)
from ..compile.documents import render_document
from ..compile.documents import OVERVIEW_LABEL
from ..domain.canonical import CanonicalDocument, Citation, iter_canonical_citations
from ..domain.consultation import (
    EvidenceRef,
    claim_ref,
    dedup_evidence,
    document_ref,
    span_ref,
)
from ..domain.ids import AnchorId, UserId, SourceId
from ..domain.pricing import USAGE_FIELDS
from ..domain.source import BlockImage, NormalizedSource
from ..ports.claim_index import ClaimLexicalIndex, ClaimVectorIndex
from ..ports.content_store import ContentStore
from ..ports.lexical_index import LexicalIndex
from ..ports.media_store import MediaStore
from ..ports.reranker import Reranker
from ..ports.vector_index import VectorIndex
from ..prompts import prompt
from .citation_alias import (
    SessionAliaser,
    alias_sources,
    iter_answer_citations,
    strip_citations,
)
from .scope import SnapshotScope, scope_declaration
from .stage_timing import (
    PREVIEW_CHOSEN,
    PREVIEW_ITEMS,
    StageEventSink,
    StageRecorder,
    StageTiming,
    call_line,
    child_name,
    claim_entries,
    face_line,
    face_preview,
    no_call_line,
    preview_head,
    section_line,
    window_entries,
)
from .spine import (
    CITE_SOURCE_LEVEL,
    CLOSE_ANSWER_HONESTLY,
    DEFAULT_ANSWER_STYLE,
    spine,
    style_clause,
)
from .assembly import (
    Passage,
    expand_and_merge,
    order_lost_in_middle,
    render_passages,
)
from .projection import PROJECTION_V1, ProjectedClaim, project_document_claims
from .rag import EpisodeSummarySignal, RecallHit, _rrf_scores, rag_recall, rrf_fuse
from ..compile.supersession import superseded_index
from .paths import (
    DEFAULT_COMPONENT_BUDGET_CHARS,
    DEFAULT_PATH_TIMEOUT_SECONDS,
    DEFAULT_ROUTE_TIMEOUT_SECONDS,
    ComponentEvidence,
    FastPath,
    evidence_counts,
    fast_paths_from_registry,
    merge_component_evidence,
    render_component_evidence,
    rerank_component_evidence,
    route_paths,
    run_paths,
)

# Product defaults separate cheap retrieval breadth from expensive answer evidence. The
# values are intentionally corpus-agnostic: retrieve enough tail for lexical/semantic
# disagreement and post-dedup backfill, then keep the final wall small enough for an
# interactive personal or team knowledge base. A deployment may tune each boundary without
# changing the mechanism.
DEFAULT_CLAIM_CANDIDATE_CAP = 80
DEFAULT_CLAIM_CAP = 40
DEFAULT_WINDOW_CANDIDATE_CAP = 60
DEFAULT_EPISODE_SUMMARY_CAP = 16
DEFAULT_WINDOW_CAP = 6
DEFAULT_IMAGE_CAP = 8

# The model-selected quality path uses the same public final caps as ranked recall, then
# preserves a small deterministic head inside each cap. The anchors are deliberately not a
# second tuning surface: they are a safety mechanism that prevents a stochastic selector
# from erasing every strong index hit.
#: How many component-lookup items one selection call may keep. A lookup is exact and
#: already ordered, so this is a context bound, not a relevance judgement.
DEFAULT_COMPONENT_SELECT_CAP = 12
DEFAULT_SELECTION_CLAIM_ANCHORS = 8
DEFAULT_SELECTION_EPISODE_ANCHORS = 4
DEFAULT_SELECTION_WINDOW_ANCHORS = 4
DEFAULT_EVIDENCE_SELECTION_TIMEOUT_SECONDS = 30.0
DEFAULT_STRUCTURED_ANSWER_TIMEOUT_SECONDS = 60.0

#: The `all` strategy's ONE bound. It hands the whole candidate pool to the answer with no
#: selection call and no score truncation, so the thing that would otherwise be unbounded is
#: the context itself — a pathological question could reach a pool no provider will take.
#: This is the ceiling on the assembled evidence faces (claims + assembled windows + episode
#: summaries), enforced AFTER assembly because a window's real size is only known once it
#: has been expanded and merged. Over it the lane drops — windows, then episode summaries,
#: then the lowest-ranked claims — and says so (`evidence_selection_degraded="all:truncated"`
#: plus per-face counts in the `assemble` preview). Never silent, and never a second selector:
#: the order is fixed and mechanical, not a judgement about this question.
DEFAULT_ALL_CONTEXT_CHARS = 120_000

#: How much of the deliberation field is kept on the result. The clause states the bound to
#: the model; this enforces it on the way out, because a schema `max_length` would turn an
#: overlong deliberation into a parse failure and cost the answer a second turn.
DELIBERATION_CHARS = 600

#: How many hit documents `timeline_expand` may expand into sibling timelines. Together with
#: the per-document sibling cap this bounds the section's total size mechanically:
#: ≤ timeline_expand × DEFAULT_TIMELINE_DOC_CAP claims (~55 tokens each), never "whatever the
#: retrieval happened to touch".
DEFAULT_TIMELINE_DOC_CAP = 4

#: How many claim notes may hang under ONE window when `annotate_windows` is on. Small on
#: purpose: a footnote stack taller than the excerpt it annotates stops reading as a footnote
#: and becomes a second claim section wearing an indent.
DEFAULT_WINDOW_NOTE_CAP = 3

#: How many documents the glance pass may ask to be read in full. Small on purpose: the pass
#: exists for the question whose answer IS one document, not as a second retrieval channel.
DEFAULT_GLANCE_PICK_CAP = 3

#: Wall-clock ceiling on the glance pass. It runs concurrently with retrieval, so the whole
#: lane costs max(retrieval, this) — but a hung provider must not hold the answer hostage, and
#: the answer is well-formed without the pass (that is the whole point of it being additive).
DEFAULT_GLANCE_TIMEOUT_SECONDS = 8.0


def invoke_config(
    run_name: str,
    callbacks: list | None,
    trace_metadata: dict | None,
) -> dict:
    """Assemble the langchain `config` passed to every `model.ainvoke` in core.

    core stays middleware-free (architecture.md §2): it depends only on langchain's
    callback abstraction. A langfuse handler (or any BaseCallbackHandler) is injected by
    the service via `callbacks`; `trace_metadata` rides `config["metadata"]` so a trace
    can be filtered by operation / user_id / snapshot. Both default to no-ops, so
    the keyless path (callbacks=None) is byte-for-byte the pre-tracing behavior.
    """
    return {
        "callbacks": callbacks or [],
        "metadata": trace_metadata or {},
        "run_name": run_name,
    }


#: What a caller passes to watch the answer TEXT arrive delta by delta while the answering
#: call is still running. CONTRACT: it MUST NOT BLOCK — it is called synchronously from
#: inside the streaming loop, on that loop's own event loop.
TokenSink = Callable[[str], None]


def _answer_input_preview(
    claims: Sequence[object],
    windows: Sequence[object],
    episode_summaries: Sequence[object],
    documents: Sequence[object],
    glance: str | None,
) -> dict:
    """How big the answer call's context was, by section — counted, not estimated.

    These are the characters of the EVIDENCE handed to the call; the contract itself is
    byte-stable per deployment (I5) and adds the same constant to every ask, so the number
    that varies — and the one that explains a slow answer — is this one. The same facts also
    read as one line (`sections`), because four counts and a total are a table and what a
    person wants at a glance is a sentence."""
    document_chars = sum(len(getattr(d, "body", "") or "") for d in documents)
    input_chars = (
        _chars(claims)
        + _chars(windows)
        + _chars(episode_summaries)
        + document_chars
        + len(glance or "")
    )
    return {
        "sections": section_line(
            (
                ("claims", len(claims)),
                ("windows", len(windows)),
                ("episodes", len(episode_summaries)),
                ("documents", len(documents)),
            ),
            input_chars,
        ),
        "input_chars": input_chars,
        "claims": len(claims),
        "windows": len(windows),
        "episode_summaries": len(episode_summaries),
        "documents": len(documents),
    }


def _glance_entries(
    paths: Sequence[str], by_path: Mapping[str, CanonicalDocument]
) -> list[dict]:
    """A chosen document as what it SAYS it is: its definition (or its ledger head), under
    its title. A path was never a preview of a page — it is where the page is filed."""
    out: list[dict] = []
    for path in list(paths)[:PREVIEW_ITEMS]:
        doc = by_path.get(path)
        if doc is None:
            out.append({"doc": path.rsplit("/", 1)[-1].removesuffix(".md")})
            continue
        says = document_definition(doc) or document_ledger_line(doc) or ""
        entry: dict = {"doc": display_identity(by_path, path).title}
        if says:
            entry = {"text": preview_head(says), **entry}
        out.append(entry)
    return out


def _component_entries(
    candidates: Sequence["ComponentCandidate"],
    titles: Mapping[str, str],
    limit: int,
) -> list[dict]:
    """A component candidate previews as what it IS — a claim among claims, a window among
    windows — which is exactly how it is rendered once selected."""
    out: list[dict] = []
    for candidate in list(candidates)[:limit]:
        if candidate.claim is not None:
            out.append(claim_entries([candidate.claim], titles)[0])
        elif candidate.window is not None:
            out.append(window_entries([candidate.window])[0])
    return out


def _selection_preview(
    choice: "SelectedEvidence | None",
    *,
    claims: Sequence[RetrievedClaim],
    episodes: Sequence[object],
    windows: Sequence[object],
    components: Sequence["ComponentCandidate"],
    titles: Mapping[str, str],
) -> dict:
    """What the selection turn was offered and what it kept: one line, then the picks.

    The line answers "how much of each face survived" — `claims 80 → 1, windows 60 → 0` — which
    is the cheapest way to see a selector that kept almost nothing. Under it the picks are
    listed IN THEIR OWN WORDS and grouped by the face they came from, because the question a
    reader actually has about a selection is which items it chose, and a list of ids answers
    that only for someone who already knows them.
    """
    picked_claims = [claims[i] for i in choice.claim_indexes] if choice else []
    picked_episodes = [episodes[i] for i in choice.episode_indexes] if choice else []
    picked_windows = [windows[i] for i in choice.window_indexes] if choice else []
    picked_components = (
        [components[i] for i in choice.component_indexes] if choice else []
    )
    out: dict = {
        "faces": face_line(
            (
                ("claims", len(claims), len(picked_claims)),
                ("episodes", len(episodes), len(picked_episodes)),
                ("windows", len(windows), len(picked_windows)),
                ("components", len(components), len(picked_components)),
            )
        )
    }
    if choice is None:
        # The exact ranked heads still answer; what did NOT happen is the selection.
        out["chosen"] = "none"
        return out
    if choice.document_paths:
        out["documents"] = ", ".join(
            titles.get(path, path) for path in choice.document_paths
        )
    groups = (
        ("claims", picked_claims, lambda rows, n: claim_entries(rows, titles, n)),
        ("episodes", picked_episodes, lambda rows, n: window_entries(rows, n)),
        ("windows", picked_windows, lambda rows, n: window_entries(rows, n)),
        ("components", picked_components, lambda rows, n: _component_entries(rows, titles, n)),
    )
    # The budget is SHARED between the faces rather than spent first-come. A selection that
    # kept twenty claims and six windows would otherwise show ten claims and no windows at
    # all — and "what did the other faces contribute" is most of what a reader opens this for.
    filled = [(key, rows, build) for key, rows, build in groups if rows]
    for index, (key, rows, build) in enumerate(filled):
        share = PREVIEW_CHOSEN // len(filled) + (
            1 if index < PREVIEW_CHOSEN % len(filled) else 0
        )
        entries = build(rows, share)
        if entries:
            out[key] = entries
    return out


def _chars(rows: Sequence[object]) -> int:
    """Characters of text a set of evidence rows carries — the SIZE of a section, which is
    what `assemble` spends its time producing and the answer call spends its budget on."""
    return sum(len(getattr(r, "text", "") or "") for r in rows)


def apply_context_ceiling(
    claims: Sequence[RetrievedClaim],
    episode_summaries: Sequence["EpisodeSummary"],
    windows: Sequence[object],
    *,
    ceiling: int,
) -> tuple[list, list, list, dict[str, int]]:
    """Bound the assembled evidence faces, dropping in ONE fixed order and saying what fell.

    The `all` strategy's only bound. It exists because that strategy removes both of the
    things that used to bound the context — the selection call and the score truncation — so
    without it a pathological question could assemble a pool no provider will accept.

    The order is mechanical and stated, never a judgement about this question: **windows
    first** (the widest face, and the one whose content the claims and episode summaries
    already point at), **then episode summaries** (derived navigation, not authority), **then
    the lowest-ranked claims** (the precise, citable face, so it is the last to give ground).
    Within a face the TAIL goes first, which is the lowest-ranked end — the caller must not
    have applied lost-in-the-middle ordering yet, or the tail is no longer the weak end.

    Component items ride inside the claim and window faces by this point, so they drop as
    members of those faces. They sit at each face's tail (a lookup returns exact results with
    no rank of their own), which means they are the first to go — deliberate: an item with no
    rank cannot be shown to be worth a ranked one's place.

    `ceiling <= 0` is OFF, not "drop everything". Returns the kept faces plus the per-face
    counts, empty when nothing was dropped."""
    kept_claims = list(claims)
    kept_episodes = list(episode_summaries)
    kept_windows = list(windows)
    dropped = {"windows": 0, "episode_summaries": 0, "claims": 0}
    if ceiling <= 0:
        return kept_claims, kept_episodes, kept_windows, {}
    total = _chars(kept_claims) + _chars(kept_episodes) + _chars(kept_windows)
    for key, rows in (
        ("windows", kept_windows),
        ("episode_summaries", kept_episodes),
        ("claims", kept_claims),
    ):
        while total > ceiling and rows:
            total -= len(getattr(rows[-1], "text", "") or "")
            rows.pop()
            dropped[key] += 1
    return (
        kept_claims,
        kept_episodes,
        kept_windows,
        dropped if any(dropped.values()) else {},
    )


def message_text(content: object) -> str:
    """The readable text of a message's content, in either shape a provider sends.

    A plain string is itself; a content-block list is its `text` blocks joined. Reasoning and
    image blocks are not text and are skipped — this returns what a reader would read, which
    is the only thing worth streaming to one."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, str):
                out.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                out.append(str(block.get("text") or ""))
        return "".join(out)
    return ""


async def invoke_or_stream(
    model: BaseChatModel,
    messages: list,
    *,
    config: dict,
    on_token: TokenSink | None,
) -> BaseMessage:
    """One model call — `ainvoke` when nobody is watching, `astream` when someone is.

    The streamed branch folds the chunks back into ONE message with `+`, so everything
    downstream (usage extraction, the content read) sees exactly the shape it saw before
    streaming existed. With `on_token=None` this is byte-for-byte the historical call: not a
    stream that is quietly re-joined, the same `ainvoke` it always was."""
    if on_token is None:
        return await model.ainvoke(messages, config=config)
    merged: BaseMessage | None = None
    async for chunk in model.astream(messages, config=config):
        delta = message_text(chunk.content)
        if delta:
            on_token(delta)
        merged = chunk if merged is None else merged + chunk  # type: ignore[operator]
    return merged if merged is not None else AIMessage(content="")


def selector_contract(answer_style: str = DEFAULT_ANSWER_STYLE) -> str:
    """The fast lane's System contract: head + shared spine + answer-style clause.

    I5: byte-stable per prompt overlay and per `answer_style` — a deployment picks one
    style and every ask shares those bytes. No timestamp, no question, no claim/window
    content — posture only. Assembled per call rather than at import so a
    startup-registered overlay reaches it."""
    return (
        prompt("recall.fast.contract_head")
        + spine(CITE_SOURCE_LEVEL, CLOSE_ANSWER_HONESTLY)
        + style_clause(answer_style)
    )


def structured_answer_contract(
    answer_style: str = DEFAULT_ANSWER_STYLE, *, deliberate: bool = False
) -> str:
    """Fast's byte-stable contract when citations travel in a separate schema field.

    `deliberate` appends ONE clause, and only the `all` strategy asks for it: the schema
    that lane answers with opens with a `deliberation` field, and a field the contract never
    mentions is a field the model fills with whatever it guesses. The default is byte-for-byte
    the historical contract, so `ranked` and `select` cannot be moved by this at all."""

    return (
        prompt("recall.fast.contract_head")
        + spine("recall.cite.structured", CLOSE_ANSWER_HONESTLY)
        + style_clause(answer_style)
        + (prompt("recall.fast.deliberation") if deliberate else "")
    )


@dataclass(frozen=True)
class RetrievedClaim:
    """A claim surfaced by the L3 retrieval face, carrying provenance (I4)."""

    anchor: AnchorId
    document_path: str
    section_path: tuple[str, ...]
    text: str
    citations: tuple[Citation, ...]
    paths: tuple[str, ...] = field(default_factory=tuple)  # ("lexical","vector") subset
    score: float = 0.0
    # Mechanical labels a component path may attach (e.g. "current", "superseded"); empty
    # for the ranked faces, so their rendering is unchanged.
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class FastAnswer:
    answer: str
    # Citation-free semantic payload for APIs, scoring and downstream automation. `answer`
    # remains the backward-compatible cited rendering used by interactive surfaces.
    answer_text: str
    used_claims: tuple[RetrievedClaim, ...]
    token_usage: dict[str, int]
    # {handle: real_source_id} for the query-local `sNN` citation handles the answer uses —
    # the business/UI side reverse-binds each `[cite: sNN]` to its real source.
    citation_handles: dict[str, str] = field(default_factory=dict)
    # L1/L2 body windows fused into the answer alongside claims (uncompiled content).
    # Merged Passages when a ContentStore is wired (expand→merge assembly); raw RecallHits
    # in the langchain-only fallback. Both expose source_id/block_start/block_end/text.
    used_windows: tuple[RecallHit | Passage, ...] = field(default_factory=tuple)
    # The glance's size in the prompt, 0 when no canonical documents were supplied — the
    # in-presence signal a caller (or the evaluation) checks without re-rendering.
    glance_chars: int = 0
    # Paths the glance pass asked to be read in full and that were actually expanded.
    expanded_documents: tuple[str, ...] = field(default_factory=tuple)
    # Why the glance pass contributed nothing, when it failed rather than simply selecting
    # nothing: "timeout", "error", or None. Telemetry, never an error surfaced to the owner.
    glance_degraded: str | None = None
    # The annotation join's yield, both 0 whenever `annotate_windows` is off: how many claims
    # were MOVED under a window (so `used_claims` is short by exactly this many), and how many
    # windows ended up carrying at least one note. The measurable of the experiment.
    annotated_claims: int = 0
    annotated_windows: int = 0
    # The timeline expansion's yield, both empty/0 whenever `timeline_expand` is off: which
    # hit documents were expanded into sibling timelines, and how many sibling claims the
    # timeline section carries in total. The measurable of that experiment.
    timeline_documents: tuple[str, ...] = field(default_factory=tuple)
    timeline_claims: int = 0
    # The planning pass's yield, empty whenever `plan_queries_cap` is 0: the extra retrieval
    # queries the model derived (the question itself is always searched and never listed).
    planned_queries: tuple[str, ...] = field(default_factory=tuple)
    # Why the planning / rerank passes contributed nothing, when they failed rather than
    # simply choosing nothing: "timeout", "error", or None. Telemetry, like glance_degraded.
    plan_degraded: str | None = None
    rerank_degraded: str | None = None
    # Images aligned to the selected raw windows and actually supplied to the answer call.
    # Bytes never leave the model boundary; this count is safe response/trace telemetry.
    image_count: int = 0
    image_mode: str = "caption"
    # Candidate-vs-evidence telemetry makes the two budgets observable without exposing any
    # generated navigation text or source content.
    claim_candidates: int = 0
    episode_summary_candidates: int = 0
    window_candidates: int = 0
    # Coordinates the selector model actually chose, before deterministic ranked anchors
    # and provenance rollback add context. Zero for ranked and fail-soft paths.
    model_selected_claims: int = 0
    model_selected_episode_summaries: int = 0
    model_selected_windows: int = 0
    #: `select` only: how many of the component pool the selector actually took (the pool
    #: itself is `component_candidates`). Zero on the ranked path, where the face is not
    #: selected from but rendered.
    model_selected_component_items: int = 0
    used_episode_summaries: tuple["EpisodeSummary", ...] = field(default_factory=tuple)
    # Query-time context composition. `ranked` is the historical fixed head; `select` is
    # one structured cross-face model call; `all` hands the whole candidate pool to the
    # answer with no selection call. Degradation is explicit and fail-soft.
    evidence_strategy: str = "ranked"
    evidence_selection_degraded: str | None = None
    # The answer wire shape. Structured answers still return the same public `answer`
    # string; kind/degradation are additive telemetry.
    answer_format: str = "text"
    answer_kind: str | None = None
    answer_format_degraded: str | None = None
    #: The answer call's own evidence review, when the structured schema asked for one
    #: (`all` + `structured`). None everywhere else, so the historical wire is unchanged.
    #: It is model output, never a SystemMessage clause (I5) and never evidence.
    deliberation: str | None = None
    # Component paths (recall/paths.py). All empty/None when no path was offered, so the
    # lane's telemetry is unchanged by the seam's existence.
    route_offered: tuple[str, ...] = ()
    route_chosen: tuple[str, ...] = ()  # "name({json args})" per honoured call
    route_degraded: str | None = None
    component_candidates: int = 0
    used_component_evidence: tuple[ComponentEvidence, ...] = ()
    #: Why the component rerank pass fell back to the lexical order, when it failed rather
    #: than simply not being wired: "timeout", "error", or None.
    component_rerank_degraded: str | None = None
    #: Per-stage wall-clock for this run, in the fixed vocabulary of `recall/stage_timing.py`
    #: — every stage present, the ones that did not run marked `skipped` at 0 ms, `total`
    #: last. The lane is several model calls and a concurrent gather; "it took 9 seconds"
    #: does not say which part, so the breakdown travels WITH the answer rather than living
    #: in a log the owner cannot see. Default empty so a directly-constructed FastAnswer
    #: (tests, fixtures) is unchanged.
    stages: tuple[StageTiming, ...] = field(default_factory=tuple)
    #: Every address this call put in front of the model, built by `evidence_manifest` from
    #: the very arguments the answer call was handed. The durable consultation record COPIES
    #: this rather than reconstructing "what was shown" out of the telemetry fields above —
    #: those report the ranked faces and miss the annotated claims, the timeline claims and
    #: a page read in full, which is how a recall that answered out of one whole document
    #: used to record itself as having been handed nothing at all.
    evidence_manifest: tuple[EvidenceRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EpisodeSummary:
    """One explicitly derived, source-addressed episode description shown to the answer.

    `text` is model-generated compression, never verbatim source. The remaining fields are
    mechanical metadata from L0 plus the exact span that the episode representation indexes.
    """

    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    score: float
    source_title: str = ""
    source_occurred_on: str = ""
    section_path: tuple[str, ...] = ()


class EvidenceSelection(BaseModel):
    """Untrusted structured output of the cross-face context selector."""

    claims: list[int] = Field(default_factory=list)
    episode_summaries: list[int] = Field(default_factory=list)
    raw_windows: list[int] = Field(default_factory=list)
    component_items: list[int] = Field(default_factory=list)
    document_paths: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class SelectedEvidence:
    """Mechanically validated query-local evidence coordinates."""

    claim_indexes: tuple[int, ...]
    episode_indexes: tuple[int, ...]
    window_indexes: tuple[int, ...]
    # Component candidates carry NO ranked safety anchors: a lookup joins the pool as an
    # ordinary candidate, and what the selector does not pick is dropped rather than
    # smuggled in behind it.
    component_indexes: tuple[int, ...] = ()
    document_paths: tuple[str, ...] = ()
    model_claim_count: int = 0
    model_episode_count: int = 0
    model_window_count: int = 0
    model_component_count: int = 0


class StructuredRecallAnswer(BaseModel):
    """Answer text and provenance kept in separate model-output fields."""

    answer_kind: Literal[
        "fact", "list", "time", "duration", "yes_no", "inference", "no_record"
    ]
    answer: str
    citations: list[str] = Field(default_factory=list)


class DeliberatedRecallAnswer(BaseModel):
    """`StructuredRecallAnswer` with one field in front of it: the evidence review.

    A SEPARATE schema rather than an optional field, so the historical structured wire is
    byte-identical by construction — `ranked` and `select` never see this class, and the
    contract clause that describes the field is its own assembled variant.

    Field ORDER is the whole mechanism. Structured output is emitted in declaration order,
    so `deliberation` is written BEFORE the answer commits to anything: the model names
    which of the handed-over candidates actually bear on the question, in the same call,
    with the evidence still in front of it. There is no `max_length` on purpose — an
    overlong deliberation must not become a parse failure and cost a second turn, so the
    bound is stated in the clause and enforced mechanically on the way out.
    """

    deliberation: str
    answer_kind: Literal[
        "fact", "list", "time", "duration", "yes_no", "inference", "no_record"
    ]
    answer: str
    citations: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class RecallImage:
    """One immutable image aligned to a recalled source block."""

    source_id: SourceId
    block_index: int
    image: BlockImage
    data: bytes | None = None


def zero_usage() -> dict[str, int]:
    """The usage vocabulary, all zero. Built from `domain.pricing.USAGE_FIELDS` so the
    counters a lane reports, the pairs a record stores and the fields money is computed
    over are one list in one place."""
    return {name: 0 for name in USAGE_FIELDS}


def extract_usage(response: BaseMessage) -> dict[str, int]:
    """Pull usage + provider cache fields off a chat response (cache defaults 0)."""
    meta: Mapping = getattr(response, "usage_metadata", None) or {}
    details: Mapping = meta.get("input_token_details") or {}
    return {
        "input_tokens": int(meta.get("input_tokens", 0) or 0),
        "output_tokens": int(meta.get("output_tokens", 0) or 0),
        "total_tokens": int(meta.get("total_tokens", 0) or 0),
        "cache_read": int(details.get("cache_read", 0) or 0),
        "cache_creation": int(details.get("cache_creation", 0) or 0),
    }


def add_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in zero_usage()}


def _claim_from_hit(hit, paths: list[str], score: float) -> RetrievedClaim:
    section_path = tuple(hit.section_path or ())
    return RetrievedClaim(
        anchor=AnchorId(hit.anchor),
        document_path=hit.document_path,
        section_path=section_path,
        text=hit.text,
        citations=tuple(
            Citation(
                source_id=SourceId(str(c["source_id"])),
                block_start=int(c["block_start"]),
                block_end=int(c["block_end"]),
            )
            for c in (hit.citations or [])
        ),
        paths=tuple(paths),
        score=score,
        # A claim from a document's overview region arrives labelled `("overview", "<slot>")`.
        # The label rides the section path the index already stores (recall/projection.py), so
        # nothing between the projection and here had to learn a new field.
        labels=(
            tuple(section_path[:2])
            if section_path[:1] == (OVERVIEW_LABEL,)
            else ()
        ),
    )


def _dedup_by_containment(claims: list[RetrievedClaim]) -> list[RetrievedClaim]:
    """Drop claims whose text is equal to, or contained in, another claim's text —
    keeping the more complete one at the better (earlier) rank of the pair.

    Anchor-level dedup cannot see these: the same fact re-filed by a later compile (a
    compensation round, a second document) carries a different anchor but adds nothing
    the longer statement doesn't already say, and every duplicate burns one slot of the
    claim budget. Containment is judged on stripped text; the kept claim keeps its own
    provenance (equal texts state the same fact, and the surviving statement's citation
    is a valid trail for it)."""
    kept: list[RetrievedClaim] = []
    kept_texts: list[str] = []
    for claim in claims:
        text = claim.text.strip()
        replaced = False
        for position, existing in enumerate(kept_texts):
            if text == existing or text in existing:
                replaced = True  # an equal or more complete statement is already ranked
                break
            if existing in text:
                kept[position] = claim  # more complete version takes the better rank
                kept_texts[position] = text
                replaced = True
                break
        if not replaced:
            kept.append(claim)
            kept_texts.append(text)
    return kept


def _fuse_claim_hits(
    labeled_hits: Sequence[tuple[str, Sequence]], limit: int
) -> list[RetrievedClaim]:
    """RRF-fuse any number of labeled hit lists into one claim ranking, deduped by
    (document_path, anchor) and then by text containment (`_dedup_by_containment`) before
    the cap — a slot freed by a duplicate refills from the fused tail. A claim keyed the
    same in several lists fuses into one hit carrying every path marker it appeared under.
    Shared by the single-query pair (lexical, vector) and the multi-query pool — one
    fusion, however many rankings."""
    info: dict[tuple, dict] = {}
    rankings: list[list[str]] = []
    for label, hits in labeled_hits:
        ranking: list[str] = []
        for hit in hits:
            key = (hit.document_path, hit.anchor)
            ranking.append(repr(key))
            entry = info.setdefault(key, {"hit": hit, "paths": []})
            if label not in entry["paths"]:
                entry["paths"].append(label)
        rankings.append(ranking)

    fused = rrf_fuse(rankings)
    scores = _rrf_scores(rankings, 60)
    by_repr = {repr(k): k for k in info}

    claims: list[RetrievedClaim] = []
    for key_repr in fused:
        entry = info[by_repr[key_repr]]
        claims.append(
            _claim_from_hit(entry["hit"], entry["paths"], scores[key_repr])
        )
    # Containment dedup runs over the FULL fused ranking before the cap, so a slot freed
    # by a duplicate refills from the tail instead of shrinking the budget.
    return _dedup_by_containment(claims)[:limit]


async def retrieve_claims(
    user_id: UserId,
    query: str,
    *,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = DEFAULT_CLAIM_CAP,
    query_embedding: list[float] | None = None,
) -> list[RetrievedClaim]:
    """Dual-path claim retrieval fused by RRF, deduped by (document_path, anchor).

    Mirrors rag_recall's fusion but over the claim face; a claim keyed the same in both
    paths fuses into one hit carrying both path markers.

    `query_embedding` (default None = embed here, i.e. today's behavior verbatim) lets a
    caller that already holds the vector skip the round trip — see `rag_recall`.

    Snapshot-scoped recall needs nothing here either (see `rag_recall`): the claim faces are
    per-tenant, so a frozen snapshot tenant carries its own frozen claim projection."""
    if limit <= 0:
        return []
    lexical_hits = await claim_lexical.search_claims(user_id, query, limit=limit)
    if query_embedding is None:
        query_embedding = await embeddings.aembed_query(query)
    vector_hits = await claim_vectors.search_claims(
        user_id, query_embedding, limit=limit
    )
    return _fuse_claim_hits(
        [("lexical", lexical_hits), ("vector", vector_hits)], limit
    )


async def retrieve_claims_multi(
    user_id: UserId,
    queries: Sequence[str],
    *,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = DEFAULT_CLAIM_CAP,
    pool_cap: int | None = None,
) -> list[RetrievedClaim]:
    """Pooled multi-query claim retrieval: every query contributes its own lexical and
    vector rankings, and ONE RRF fusion ranks the union.

    This is the retrieval half of the planned fan-out (`plan_retrieval_queries`): a
    multi-aspect question retrieves each aspect at full strength instead of blending them
    into one query. With a single query this is byte-for-byte `retrieve_claims`. Queries
    run concurrently; per-query rank order is preserved into the fusion in query order,
    so the result is deterministic for a given hit set.

    `limit` is the per-query, per-face retrieval depth; the fused result is truncated to
    `pool_cap` (default None = `limit`, today's behavior). A reranking caller passes a
    LARGER pool_cap so RRF — which is score-blind — never discards a candidate the
    reranker was going to judge: fusion order then only decides dedup, the failure
    fallback, and which tail falls off the hard cap."""

    if limit <= 0 or (pool_cap is not None and pool_cap <= 0):
        return []

    async def one(query: str) -> tuple[Sequence, Sequence]:
        lexical_hits = await claim_lexical.search_claims(user_id, query, limit=limit)
        vector = await embeddings.aembed_query(query)
        vector_hits = await claim_vectors.search_claims(user_id, vector, limit=limit)
        return lexical_hits, vector_hits

    per_query = await asyncio.gather(*(one(q) for q in queries))
    labeled: list[tuple[str, Sequence]] = []
    for lexical_hits, vector_hits in per_query:
        labeled.append(("lexical", lexical_hits))
        labeled.append(("vector", vector_hits))
    return _fuse_claim_hits(labeled, pool_cap if pool_cap is not None else limit)


def mark_superseded_claims(
    claims: Sequence[RetrievedClaim], documents: Sequence[CanonicalDocument] | None
) -> list[RetrievedClaim]:
    """Label claims that canonical has superseded and move them behind the live ones.

    Whether a claim is the current state of its fact is a property of canonical
    (compile/supersession.py), not of any index: the ranked faces surface a superseded claim
    exactly like a live one whenever its words match. Judged here, at assembly, over the
    lane's already-pinned `documents` — so it is always as fresh as canonical and needs no
    index payload. Without `documents` (no glance loaded) nothing is judged and the order
    is untouched.
    """
    if not documents:
        return list(claims)
    dead = superseded_index({doc.path: doc.body for doc in documents})
    live: list[RetrievedClaim] = []
    stale: list[RetrievedClaim] = []
    for claim in claims:
        if str(claim.anchor) not in dead:
            live.append(claim)
        elif "superseded" in claim.labels:
            stale.append(claim)
        else:
            stale.append(replace(claim, labels=(*claim.labels, "superseded")))
    return [*live, *stale]


def render_claims(claims: list[RetrievedClaim]) -> str:
    """Compact deterministic claim payload for the Human turn (input order preserved)."""
    lines: list[str] = []
    for c in claims:
        section = " › ".join(c.section_path) if c.section_path else ""
        head = f"[c:{c.anchor} · {c.document_path}"
        head += f" · {section}" if section else ""
        head += f" · {' · '.join(c.labels)}" if c.labels else ""
        head += "]"
        # Provenance as the fixed English `[cite: …]` marker (full source_id) — the model
        # cites by copying it; the app extracts it into a component, so it is never
        # translated to the answer's language.
        cites = " ".join(
            f"[cite: {cit.source_id} ¶{cit.block_start}-{cit.block_end}]"
            for cit in c.citations
        )
        line = f"{head} {c.text}"
        if cites:
            line += f"  {cites}"
        lines.append(line)
    return "\n".join(lines)


def render_windows(windows: list[RecallHit]) -> str:
    """Compact deterministic body-window payload for the Human turn (full block text).

    Windows are the recall lever over uncompiled content, so each line carries the FULL
    block text (capped by count upstream, never truncated). The provenance label uses the
    same `[cite: …]` grammar as render_passages (I4: one addressing vocabulary everywhere)."""
    lines: list[str] = []
    for w in windows:
        # Same fixed English `[cite: …]` marker with the FULL source_id (never truncated),
        # so a window-sourced citation resolves like a claim's.
        lines.append(f"[cite: {w.source_id} ¶{w.block_start}-{w.block_end}] {w.text}")
    return "\n".join(lines)


async def build_episode_summaries(
    hits: Sequence[RecallHit],
    *,
    content: ContentStore | None,
    user_id: UserId,
    cap: int = DEFAULT_EPISODE_SUMMARY_CAP,
) -> list[EpisodeSummary]:
    """Lift dense derived episode text from a wide window pool and add mechanical L0 metadata.

    Rank and cap follow the fused source-hit order. Exact `(source, span, text)` duplicates are
    removed. L0 metadata is best-effort (the core-only path may have no ContentStore), but the
    source id and block span are always present because they are the vector point's address.
    """

    if cap <= 0:
        return []
    selected: list[tuple[RecallHit, EpisodeSummarySignal, str]] = []
    seen: set[tuple[str, int, int, str]] = set()
    for hit in hits:
        for signal in hit.episode_summaries:
            text = signal.text.strip()
            key = (
                str(signal.source_id),
                signal.block_start,
                signal.block_end,
                text,
            )
            if not text or key in seen:
                continue
            seen.add(key)
            selected.append((hit, signal, text))
            if len(selected) >= cap:
                break
        if len(selected) >= cap:
            break

    source_ids = tuple(
        dict.fromkeys(str(signal.source_id) for _, signal, _ in selected)
    )

    async def load_source(source_id: str):
        if content is None:
            return None
        try:
            return await content.get(user_id, SourceId(source_id))
        except KeyError:
            return None

    loaded = await asyncio.gather(*(load_source(source_id) for source_id in source_ids))
    cache = dict(zip(source_ids, loaded))

    summaries: list[EpisodeSummary] = []
    for hit, signal, text in selected:
        source = cache[str(signal.source_id)]
        source_title = ""
        source_occurred_on = ""
        section_path: tuple[str, ...] = ()
        if source is not None:
            source_title = getattr(source.raw, "title", "") or ""
            source_occurred_on = source.raw.occurred_on()
            section_path = next(
                (
                    tuple(block.section_path)
                    for block in source.blocks
                    if block.index == signal.block_start
                ),
                (),
            )
        summaries.append(
            EpisodeSummary(
                source_id=signal.source_id,
                block_start=signal.block_start,
                block_end=signal.block_end,
                text=text,
                score=hit.score,
                source_title=source_title,
                source_occurred_on=source_occurred_on,
                section_path=section_path,
            )
        )
    return summaries


def render_episode_summaries(summaries: Sequence[EpisodeSummary]) -> str:
    """Render derived compression with an explicit identity and enough source metadata."""

    return "\n\n".join(
        prompt(
            "recall.fast.episode_summary.item",
            source_id=summary.source_id,
            start=summary.block_start,
            end=summary.block_end,
            source_title=summary.source_title,
            occurred_on=summary.source_occurred_on,
            section=" › ".join(summary.section_path),
            text=summary.text,
        )
        for summary in summaries
    )


def _render_window_section(windows: list) -> str:
    """Render the window payload: assembled Passages (labeled, context-expanded) when the
    hits carry a section_path, else the flat RecallHit rendering (langchain-only fallback)."""
    if windows and hasattr(windows[0], "section_path"):
        return render_passages(windows, header="")
    return render_windows(windows)


def _render_recall_image(image: RecallImage) -> str:
    """Textual locator and derived representations that travel with one image."""

    lines = [
        prompt(
            "recall.fast.image_locator",
            source_id=image.source_id,
            index=image.block_index,
            image_id=image.image.image_id,
        )
    ]
    if image.image.derived:
        lines.extend(
            prompt(
                "compile.task.image_derived",
                image_id=image.image.image_id,
                kind=derived.kind,
                producer=derived.producer,
                text=derived.text,
            )
            for derived in image.image.derived
        )
    else:
        lines.append(
            prompt(
                "compile.task.image_without_derived",
                image_id=image.image.image_id,
            )
        )
    return "\n".join(lines)


async def collect_window_images(
    user_id: UserId,
    windows: Sequence,
    *,
    content: ContentStore | None,
    media: MediaStore | None,
    image_mode: Literal["caption", "native"],
    cap: int = DEFAULT_IMAGE_CAP,
) -> list[RecallImage]:
    """Load images whose blocks overlap selected windows, deduped by immutable digest.

    Caption mode reads only the L0 image manifests and their labelled derived text. Native
    mode additionally retrieves and verifies the original bytes before they can reach the
    model. The selected windows are the mechanical relevance gate: an unrelated image in the
    same source is never attached merely because that source had one hit elsewhere.
    """
    if content is None or not windows or cap <= 0:
        return []
    if image_mode == "native" and media is None:
        raise RuntimeError("native image recall requires a media store")

    spans: dict[SourceId, list[tuple[int, int]]] = {}
    source_order: list[SourceId] = []
    for window in windows:
        source_id = SourceId(str(window.source_id))
        if source_id not in spans:
            spans[source_id] = []
            source_order.append(source_id)
        spans[source_id].append((int(window.block_start), int(window.block_end)))

    result: list[RecallImage] = []
    seen_digests: set[str] = set()
    for source_id in source_order:
        source = await content.get(user_id, source_id)
        for block in source.blocks:
            if not any(start <= block.index <= end for start, end in spans[source_id]):
                continue
            for image in block.images:
                if image.sha256 in seen_digests:
                    continue
                data: bytes | None = None
                if image_mode == "native":
                    assert media is not None
                    data = await media.get(user_id, image.storage_key)
                    if len(data) != image.size_bytes:
                        raise ValueError(
                            f"stored image {image.image_id!r} size no longer matches L0 manifest"
                        )
                    if hashlib.sha256(data).hexdigest() != image.sha256:
                        raise ValueError(
                            f"stored image {image.image_id!r} digest no longer matches L0 manifest"
                        )
                result.append(
                    RecallImage(
                        source_id=source_id,
                        block_index=block.index,
                        image=image,
                        data=data,
                    )
                )
                seen_digests.add(image.sha256)
                if len(result) >= cap:
                    return result
    return result


# ------------------------------------------------- annotation join (opt-in, default off)
#
# The two evidence faces are addressed in disjoint id spaces (claim anchor vs block span),
# which is why they render as two sections — but they are NOT disjoint in the underlying
# text: a claim carries `[cite: <source_id> ¶a-b]`, and a window IS a `[cite: <source_id>
# ¶a-b]`. When those spans overlap, the claim is the compiled reading OF the lines in that
# window, and the model is being asked to discover that by attending across the whole
# evidence wall. The join below does it mechanically instead, and MOVES the claim under its
# window — a move, not a copy, so the claim is stated exactly once and the model is never
# invited to treat the note and the notes-section entry as two pieces of evidence.

#: The skill's controlled strength prefix (`contract.rule.strength_labels`), which the
#: compiler writes at the head of a commitment/relationship claim in every locale: the
#: 【…】 brackets are the fixed shape, the label inside them is the overlay's word.
_STRENGTH_PREFIX_RE = re.compile(r"^【([^】\n]{1,12})】\s*")


def split_strength_label(text: str) -> tuple[str | None, str]:
    """`("firm", "the rest")` for a labeled claim, `(None, text)` for an unlabeled one.

    Lifted out of the text rather than re-derived: the projection layer already tiers on
    this prefix, so a footnote that keeps it in its own slot presents the same tiering the
    rest of the system does, instead of leaving a bracket floating in prose."""
    match = _STRENGTH_PREFIX_RE.match(text)
    if not match:
        return None, text
    return match.group(1), text[match.end() :]


def _overlaps(claim: RetrievedClaim, window) -> bool:
    """True when any of the claim's cited spans intersects the window's block interval."""
    return any(
        str(cit.source_id) == str(window.source_id)
        and cit.block_start <= window.block_end
        and window.block_start <= cit.block_end
        for cit in claim.citations
    )


def join_claims_to_windows(
    claims: Sequence[RetrievedClaim],
    windows: Sequence,
    *,
    cap: int = DEFAULT_WINDOW_NOTE_CAP,
) -> tuple[list[RetrievedClaim], list[tuple[object, tuple[RetrievedClaim, ...]]]]:
    """Move each claim under the FIRST window its citation overlaps; cap `cap` per window.

    Returns `(claims that stayed in the notes section, [(window, its notes)] in window
    order)`. A claim lands under at most one window even when it overlaps several — it is
    one statement, and repeating it under each window would re-introduce exactly the
    duplication this join exists to remove. Deterministic: windows in their given order,
    claims in retrieval (RRF) order within each window."""
    taken: set[int] = set()
    paired: list[tuple[object, tuple[RetrievedClaim, ...]]] = []
    for window in windows:
        notes: list[RetrievedClaim] = []
        for index, claim in enumerate(claims):
            if len(notes) >= cap:
                break
            if index in taken or not _overlaps(claim, window):
                continue
            notes.append(claim)
            taken.add(index)
        paired.append((window, tuple(notes)))
    remaining = [c for i, c in enumerate(claims) if i not in taken]
    return remaining, paired


def render_window_notes(notes: Sequence[RetrievedClaim]) -> str:
    """The footnote block under one window: a count line, then one indented line per claim.

    No `[cite: …]` marker on a note line — the window's own provenance header, three lines
    above, IS that citation, and a second copy of the same span would only give the model a
    second thing to transcribe. What the note adds is what the window cannot show: the
    strength the compiler assigned, the claim's anchor, and the document it was filed into."""
    lines = [prompt("recall.fast.window_note.header", count=len(notes))]
    for claim in notes:
        label, text = split_strength_label(claim.text)
        key = "recall.fast.window_note.line_labeled" if label else "recall.fast.window_note.line"
        fields = {
            "text": text,
            "anchor": f"c:{claim.anchor}",
            "document": claim.document_path,
        }
        if label:
            fields["label"] = label
        lines.append(prompt(key, **fields))
    return "\n".join(lines)


def render_annotated_windows(
    paired: Sequence[tuple[object, tuple[RetrievedClaim, ...]]]
) -> str:
    """The window section with each window's claim notes hung directly beneath it."""
    parts: list[str] = []
    for window, notes in paired:
        parts.append(_render_window_section([window]))
        if notes:
            parts.append(render_window_notes(notes))
    return "\n".join(parts)


# --------------------------------------------- subject-timeline expansion (opt-in, default off)
#
# Retrieval surfaces a subject's dated facts one at a time — whichever claims happened to
# match the question's wording — while an interval/ordering question ("when did X first…",
# "what changed between…") is answered by the subject's dated facts arriving TOGETHER, in
# order. Claims are compiled into per-subject documents whose body order approximates
# chronology (the compiler appends as the record grows), and every claim carries its dates in
# its own text. So when a retrieved claim proves a document relevant, the expansion below
# re-projects that document's sibling claims (recall/projection.py — the same parse the L3
# index was built from) and renders them as one compact timeline block per document. The
# expansion is VOLUME-AWARE: a rolled-over subject is one file plus a same-name directory of
# frozen `aNN.md` volumes (compile/rollover.py), and a hit on ANY of those shards expands the
# subject's whole timeline — volumes oldest-first, then the active page — as one block.
# Additive: the claim-notes section is untouched, and `timeline_expand=0` is byte-for-byte
# the lane without this section.


@dataclass(frozen=True)
class TimelineBlock:
    """One hit subject's sibling claims, in document (projection) order.

    `document_path` is the subject's ACTIVE page. For a rolled-over subject the claims span
    its frozen history volumes (oldest first) plus the active page — one subject, one block."""

    document_path: str
    claims: tuple[ProjectedClaim, ...]
    total_claims: int  # the subject's full claim count (all pages), before the per-subject cap


#: A rollover volume's filename inside a subject's history directory (`<page>/aNN.md`).
#: Mirrors `compile.patch._VOLUME_FILE_RE` mechanically: recall reads the layout the groom
#: channel produces without importing the write channel.
_TIMELINE_VOLUME_FILE_RE = re.compile(r"^a\d{2,}\.md$")


def timeline_subject(path: str, documents_by_path: Mapping[str, CanonicalDocument]) -> str:
    """The active page whose timeline `path` belongs to.

    A rollover volume (`work/products/x/a01.md`) belongs to its active page
    (`work/products/x.md`) when that page is in the supplied canonical set; every other path
    — including a volume whose active page is absent — is its own subject. Mechanical, like
    `compile.patch.history_volume_owner`, but keyed off the supplied documents rather than
    the write templates: the canonical set is this lane's authority (never the hit's path)."""
    directory, _, filename = path.rpartition("/")
    if directory and _TIMELINE_VOLUME_FILE_RE.match(filename):
        owner = f"{directory}.md"
        if owner in documents_by_path:
            return owner
    return path


def subject_timeline_paths(
    subject: str, documents_by_path: Mapping[str, CanonicalDocument]
) -> list[str]:
    """The subject's pages oldest-first: frozen volumes in volume order, then the active page.

    Rollover archives the OLDEST claim blocks (`compile.rollover`), so reading a01, a02, …,
    then the active page keeps the concatenated projection in approximate chronological
    order — exactly the order the timeline section renders."""
    prefix = subject.removesuffix(".md") + "/"
    volumes = sorted(
        p
        for p in documents_by_path
        if p.startswith(prefix) and _TIMELINE_VOLUME_FILE_RE.match(p[len(prefix) :])
    )
    return [*volumes, subject]


def select_timeline_claims(
    doc_claims: Sequence[ProjectedClaim],
    hit_anchors: set[str],
    cap: int,
) -> list[ProjectedClaim]:
    """The ≤`cap` sibling claims kept for one document, in document order.

    A document at or under the cap is kept whole — the timeline IS the point. Over the cap,
    the kept set is the claims nearest (by document-order distance) to a retrieved hit: the
    hits anchor which stretch of the subject's history the question touched, and the window
    around them is that stretch's before/after context. Deterministic ties: the earlier claim
    wins. The result is re-sorted into document order, so the rendered block always reads
    oldest → newest regardless of which claims were kept."""
    if cap <= 0 or not doc_claims:
        return []
    if len(doc_claims) <= cap:
        return list(doc_claims)
    hit_positions = [
        i for i, claim in enumerate(doc_claims) if str(claim.anchor) in hit_anchors
    ] or [0]
    ranked = sorted(
        range(len(doc_claims)),
        key=lambda i: (min(abs(i - h) for h in hit_positions), i),
    )
    kept = sorted(ranked[:cap])
    return [doc_claims[i] for i in kept]


def build_subject_timelines(
    hits: Sequence[RetrievedClaim],
    documents_by_path: Mapping[str, CanonicalDocument],
    *,
    per_doc: int,
    doc_cap: int = DEFAULT_TIMELINE_DOC_CAP,
) -> list[TimelineBlock]:
    """The timeline blocks for the subjects the retrieval hit, most-hit subjects first.

    VOLUME-AWARE: a hit on any shard of a rolled-over subject — its active page or one of
    its frozen `aNN.md` history volumes — counts toward ONE subject, and expanding that
    subject projects its whole timeline: volumes oldest-first, then the active page. Without
    this, a retrieval that lands on an archive shard used to expand only that shard and miss
    the sibling volumes (and the active tail) of the very subject the question is about.

    Subjects are ranked by (hit count desc, first-hit RRF position) and the top `doc_cap`
    expanded — a subject the retrieval touched three times is more load-bearing for the
    question than one it grazed once. Only hits whose path is actually present in
    `documents_by_path` count (the hit's path is derived data; the canonical set is the
    authority). The caps are unchanged: `per_doc` bounds the claims kept per SUBJECT (all its
    pages together), so total size stays mechanically ≤ `per_doc × doc_cap` claims."""
    if per_doc <= 0 or doc_cap <= 0 or not hits or not documents_by_path:
        return []
    hit_count: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for position, hit in enumerate(hits):
        path = hit.document_path
        if path not in documents_by_path:
            continue
        subject = timeline_subject(path, documents_by_path)
        hit_count[subject] = hit_count.get(subject, 0) + 1
        first_seen.setdefault(subject, position)
    ordered = sorted(hit_count, key=lambda p: (-hit_count[p], first_seen[p]))

    hit_anchors = {str(hit.anchor) for hit in hits}
    blocks: list[TimelineBlock] = []
    for subject in ordered[:doc_cap]:
        doc_claims: list[ProjectedClaim] = []
        for page in subject_timeline_paths(subject, documents_by_path):
            doc_claims.extend(
                project_document_claims(documents_by_path[page], PROJECTION_V1)
            )
        kept = select_timeline_claims(doc_claims, hit_anchors, per_doc)
        if kept:
            blocks.append(
                TimelineBlock(
                    document_path=subject,
                    claims=tuple(kept),
                    total_claims=len(doc_claims),
                )
            )
    return blocks


def render_subject_timelines(blocks: Sequence[TimelineBlock]) -> str:
    """The timeline section: a self-describing header, then one dated block per document.

    Each line keeps the claim's text (its dates live there), its FIRST citation — enough for
    the answer to cite the span, without repeating a multi-citation tail that can outweigh the
    claim itself — and its anchor. The header explains the section inline because the
    byte-stable System contract (I5) must not change under an experiment flag."""
    parts = [prompt("recall.section.timelines_header", count=len(blocks))]
    for block in blocks:
        parts.append(
            prompt(
                "recall.fast.timeline.document",
                path=block.document_path,
                shown=len(block.claims),
                total=block.total_claims,
            )
        )
        for claim in block.claims:
            line = f"- {claim.text}"
            if claim.citations:
                cit = claim.citations[0]
                line += f" [cite: {cit.source_id} ¶{cit.block_start}-{cit.block_end}]"
            line += f" 〔c:{claim.anchor}〕"
            parts.append(line)
    return "\n".join(parts)


def render_full_documents(documents: Sequence[CanonicalDocument]) -> str:
    """The whole of each selected document, in supplied order, headed by its path.

    Rendered with the compile side's `render_document`, so frontmatter, claim anchors and
    inter-document links reach the answerer in exactly the form the compiler wrote them —
    which is what lets an answer cite a claim it read here the same way it cites a retrieved
    one, and lets the model see the links it could follow."""
    parts: list[str] = []
    for doc in documents:
        parts.append(prompt("recall.fast.select.document_heading", path=doc.path))
        parts.append(render_document(doc.frontmatter, doc.body).rstrip())
    return "\n".join(parts)


def _claim_manifest(claim: object, kind: str, *, rendered_citations: int | None = None):
    """One rendered claim → its own address, then the provenance spans rendered with it.

    `rendered_citations` is how many of the claim's `[cite: …]` markers the face that
    rendered it actually PRINTED: `None` for every one of them (`render_claims`), an int
    for the faces that print fewer — 1 for the timeline block, 0 for a window note, which
    prints none at all. A span the model never saw is not an address it was shown, so it is
    not provenance the record may admit a citation against, and counting it as source
    attention would be heat for a page nobody read.
    """
    item = claim_ref(
        str(getattr(claim, "anchor", "")), str(getattr(claim, "document_path", "")), kind=kind
    )
    citations = tuple(getattr(claim, "citations", ()) or ())
    if rendered_citations is not None:
        citations = citations[:rendered_citations]
    provenance = [
        span_ref(cit.source_id, cit.block_start, cit.block_end, kind=kind)
        for cit in citations
    ]
    return item, provenance


def evidence_manifest(
    *,
    claims: Sequence[RetrievedClaim] = (),
    windows: Sequence = (),
    episode_summaries: Sequence["EpisodeSummary"] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence["TimelineBlock"] = (),
    component_evidence: Sequence["ComponentEvidence"] = (),
    full_documents: Sequence[CanonicalDocument] = (),
    tool_evidence: Sequence[EvidenceRef] = (),
) -> tuple[EvidenceRef, ...]:
    """Every ADDRESS this call put in front of the model, as `EvidenceRef`s.

    It takes the same arguments the answer call is handed, so it observes rendering rather
    than repeating it: `recall_human` composes its sections out of exactly these, and this
    function never touches the text. Nothing here can move a prompt byte.

    Two layers, in this order:

    - the evidence ITEMS, in render order — claim notes, the component face, episode
      summaries, timeline claims, raw excerpts (annotated claims travel under their window
      and are items all the same), whatever a lane's TOOLS returned into the transcript
      (`tool_evidence`, already addresses), then each page selected for reading in full;
    - the PROVENANCE spans rendered with them. A claim note carries its own
      `[cite: <source_id> ¶a-b]` marker and the contract tells the model to copy source
      references verbatim from the markers in the evidence, so those spans are addresses
      the model was shown — and a citation copied out of one is admissible precisely
      because it appears here. A fully-read page contributes every marker its body carries.
      A face that renders FEWER markers than the claim carries contributes fewer spans
      (`_claim_manifest`'s `rendered_citations`), and the annotated layout — whose notes
      print no marker at all — contributes none: what the model was not shown is not
      provenance, however true it is of the claim.

    Items before provenance so that a span which is BOTH a shown window and some claim's
    provenance keeps the kind that says more about it (`window`: its text was there too).
    """
    items: list[EvidenceRef] = []
    provenance: list[EvidenceRef] = []

    def add_claim(claim: object, kind: str, *, rendered_citations: int | None = None) -> None:
        item, spans = _claim_manifest(claim, kind, rendered_citations=rendered_citations)
        items.append(item)
        provenance.extend(spans)

    for claim in claims:
        add_claim(claim, "claim")
    for _window, notes in window_notes or ():
        for claim in notes:
            # `render_window_notes` prints NO `[cite: …]` marker: the window's own
            # provenance header IS the citation for everything hung beneath it. So a note
            # contributes its claim address and nothing else — a claim joined on blocks 1-2
            # may also cite blocks 100-101 of the same source, and that second span reached
            # the model in neither the window nor the note.
            add_claim(claim, "claim", rendered_citations=0)
    for evidence in component_evidence:
        for claim in getattr(evidence, "claims", ()) or ():
            add_claim(claim, "component")
        for window in getattr(evidence, "windows", ()) or ():
            items.append(
                span_ref(
                    window.source_id, window.block_start, window.block_end, kind="component"
                )
            )
    for summary in episode_summaries:
        items.append(
            span_ref(
                summary.source_id, summary.block_start, summary.block_end, kind="episode"
            )
        )
    for block in timelines:
        for claim in getattr(block, "claims", ()) or ():
            # `render_subject_timelines` prints the FIRST citation and no more, so that is
            # the only provenance span this face actually showed.
            add_claim(claim, "claim", rendered_citations=1)
    for window in windows:
        items.append(
            span_ref(window.source_id, window.block_start, window.block_end, kind="window")
        )
    # Addresses a TOOL returned into the transcript, already in address form: the deep
    # lane's verbatim fetches, and what a component's contributed tool declared. They are
    # items rather than provenance — the text was there, this is not somebody else's marker.
    items.extend(tool_evidence)
    for document in full_documents:
        items.append(document_ref(document.path))
        provenance.extend(
            span_ref(
                cit.source_id, cit.block_start, cit.block_end, kind="document"
            )
            for cit in iter_canonical_citations(document.body)
        )
    return dedup_evidence([*items, *provenance])


def recall_human(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    component_evidence: Sequence[ComponentEvidence] = (),
) -> str:
    """The volatile Human payload shared by fast and deep: profile → snapshot → glance →
    evidence → documents → as_of → input.

    Deterministic assembly order (I5 / prompt-cache discipline), input LAST: the owner profile
    (who is asking — the System tier explains what it is) → the snapshot declaration when the
    question is pinned to a past state of the base → the knowledge base glance (the library's
    shape, which is per-snapshot rather than per-question, so it sits high where a provider
    cache can reach it) → claim section → window section → any documents selected for
    full reading → as_of → the owner's input, so the live ask sits in the attention-hot tail
    below the evidence wall instead of above it. Section headers reuse the contract's exact
    names (owner profile / claim notes / raw excerpts) — what each IS is explained once, in the
    stable System tier, never re-explained per turn. Claims and windows live in disjoint id
    spaces (anchor vs block-span), so they are presented as two sections, never cross-fused.
    The profile is the reason it lives in the Human turn, not the byte-stable System (it is
    per-owner volatile).

    The snapshot declaration sits immediately ABOVE the glance because it governs everything
    below it: the glance, both evidence faces and every tool result are that snapshot. It is
    absent entirely for a HEAD question, so an unpinned prompt is unchanged.

    `window_notes` (default None = the two-section layout above, byte-for-byte) is the opt-in
    annotated layout: (window, notes) pairs whose claims have already been MOVED out of
    `claims` by `join_claims_to_windows`, rendered as footnotes under their own window. The
    two sections still exist and still hold disjoint content — what moves is where a joined
    claim is stated, not whether the claim section is there.

    `timelines` (default () = no section, byte-for-byte the layout above) is the opt-in
    subject-timeline expansion: one dated block per hit document, rendered directly below the
    claim notes it expands on, above the raw excerpts."""
    return _recall_human_evidence(
        claims,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
        component_evidence=component_evidence,
    ) + _recall_human_tail(question, as_of)


def _recall_human_evidence(
    claims: list[RetrievedClaim],
    *,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    component_evidence: Sequence[ComponentEvidence] = (),
) -> str:
    """Everything before the volatile clock/question tail in the Human message."""

    windows = windows or []
    sections: list[str] = []
    if profile:
        sections.append(f"{prompt('recall.section.profile_header')}\n{profile}")
    if snapshot:
        sections.append(snapshot)
    if glance:
        sections.append(glance)
    sections.append(
        prompt("recall.section.claims_header", count=len(claims))
        + "\n"
        + (render_claims(claims) or prompt("recall.section.claims_empty"))
    )
    if component_evidence:
        sections.append(
            prompt("recall.section.component_header", count=evidence_counts(component_evidence))
            + "\n"
            + render_component_evidence(component_evidence)
        )
    if episode_summaries:
        sections.append(
            prompt(
                "recall.section.episode_summaries_header",
                count=len(episode_summaries),
            )
            + "\n"
            + render_episode_summaries(episode_summaries)
        )
    if timelines:
        sections.append(render_subject_timelines(timelines))
    if windows:
        sections.append(
            prompt("recall.section.windows_header", count=len(windows))
            + "\n"
            + (
                render_annotated_windows(window_notes)
                if window_notes is not None
                else _render_window_section(windows)
            )
        )
    if full_documents:
        sections.append(
            prompt("recall.fast.select.documents_header", count=len(full_documents))
            + "\n"
            + render_full_documents(full_documents)
        )
    return "\n\n".join(sections)


def _recall_human_tail(question: str, as_of: datetime) -> str:
    """Attention-hot Human tail, shared by text-only and native-image messages."""

    return f"\n\nas_of: {as_of.isoformat()}\n" + prompt(
        "recall.section.input", question=question
    )


def _selected_indexes(
    values: Sequence[int], *, available: int, cap: int, anchors: int
) -> tuple[int, ...]:
    """Validate untrusted model indexes, union the ranked safety head, then cap."""

    if available <= 0 or cap <= 0:
        return ()
    ordered: list[int] = []
    for raw in (*values, *range(min(anchors, available))):
        try:
            index = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= index < available and index not in ordered:
            ordered.append(index)
        if len(ordered) >= cap:
            break
    return tuple(ordered)


def _model_selected_indexes(
    values: Sequence[int], *, available: int, cap: int
) -> tuple[int, ...]:
    """Validate only the model's coordinates, before ranked safety anchors are added."""

    if available <= 0 or cap <= 0:
        return ()
    ordered: list[int] = []
    for raw in values:
        try:
            index = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= index < available and index not in ordered:
            ordered.append(index)
        if len(ordered) >= cap:
            break
    return tuple(ordered)


@dataclass(frozen=True)
class ComponentCandidate:
    """One component result offered to the selector, and where it goes when picked."""

    group: str  # `component:person(alias="贾宁")` — the lookup it came from
    path: str  # the path name, for the `via:` label a selected claim carries
    claim: RetrievedClaim | None = None
    window: RecallHit | None = None

    @property
    def kind(self) -> str:
        return "claim" if self.claim is not None else "window"

    @property
    def text(self) -> str:
        return self.claim.text if self.claim is not None else (self.window.text if self.window else "")

    @property
    def locator(self) -> str:
        if self.claim is not None:
            section = " / ".join(self.claim.section_path) or "-"
            return f"{self.claim.document_path}; {section}"
        if self.window is not None:
            return f"{self.window.source_id}; {self.window.block_start}-{self.window.block_end}"
        return "-"


def component_candidate_pool(
    evidence: Sequence[ComponentEvidence],
) -> list[ComponentCandidate]:
    """The component face, flattened into one numbered pool the selector can pick from.

    In `select` the component face is not a section the answer receives untouched: it is
    candidates like any other, so the ONE selection call decides the whole context instead
    of one face bypassing it. Grouping by lookup is kept in the rendering (a candidate's
    provenance is part of judging it), the coordinates stay flat."""
    out: list[ComponentCandidate] = []
    for row in evidence:
        if row.degraded:
            continue
        args = ", ".join(
            f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in row.args.items()
        )
        group = f"component:{row.path}({args})"
        out.extend(
            ComponentCandidate(group=group, path=row.path, claim=claim) for claim in row.claims
        )
        out.extend(
            ComponentCandidate(group=group, path=row.path, window=window)
            for window in row.windows
        )
    return out


def evidence_selection_messages(
    question: str,
    *,
    claims: Sequence[RetrievedClaim],
    episode_summaries: Sequence[EpisodeSummary],
    windows: Sequence[RecallHit],
    components: Sequence[ComponentCandidate] = (),
    glance: str | None = None,
    claim_cap: int,
    episode_summary_cap: int,
    window_cap: int,
    component_cap: int = DEFAULT_COMPONENT_SELECT_CAP,
    document_cap: int = DEFAULT_GLANCE_PICK_CAP,
) -> list[BaseMessage]:
    """Byte-stable selector contract plus numbered volatile candidates, question last."""

    sections: list[str] = []
    if glance:
        sections.append(prompt("recall.fast.evidence_select.glance", glance=glance))
    sections.append(prompt("recall.fast.evidence_select.claims_header"))
    sections.extend(
        prompt(
            "recall.fast.evidence_select.claim",
            index=index,
            path=claim.document_path,
            section=" / ".join(claim.section_path) or "-",
            text=claim.text,
        )
        for index, claim in enumerate(claims)
    )
    sections.append(prompt("recall.fast.evidence_select.episodes_header"))
    sections.extend(
        prompt(
            "recall.fast.evidence_select.episode",
            index=index,
            occurred_on=summary.source_occurred_on or "-",
            start=summary.block_start,
            end=summary.block_end,
            text=summary.text,
        )
        for index, summary in enumerate(episode_summaries)
    )
    sections.append(prompt("recall.fast.evidence_select.windows_header"))
    sections.extend(
        prompt(
            "recall.fast.evidence_select.window",
            index=index,
            source_id=window.source_id,
            start=window.block_start,
            end=window.block_end,
            text=window.text,
        )
        for index, window in enumerate(windows)
    )
    if components:
        sections.append(prompt("recall.fast.evidence_select.components_header"))
        group = ""
        for index, candidate in enumerate(components):
            if candidate.group != group:
                group = candidate.group
                sections.append(
                    prompt("recall.fast.evidence_select.component_group", label=group)
                )
            sections.append(
                prompt(
                    "recall.fast.evidence_select.component_item",
                    index=index,
                    kind=candidate.kind,
                    locator=candidate.locator,
                    text=candidate.text,
                )
            )
    return [
        SystemMessage(
            content=prompt(
                "recall.fast.evidence_select.contract",
                claim_cap=claim_cap,
                episode_cap=episode_summary_cap,
                window_cap=window_cap,
                component_cap=component_cap,
                document_cap=document_cap,
            )
        ),
        HumanMessage(
            content=prompt(
                "recall.fast.evidence_select.request",
                candidates="\n".join(sections),
                question=question,
            )
        ),
    ]


async def select_evidence(
    model: BaseChatModel,
    question: str,
    *,
    claims: Sequence[RetrievedClaim],
    episode_summaries: Sequence[EpisodeSummary],
    windows: Sequence[RecallHit],
    components: Sequence[ComponentCandidate] = (),
    glance: str | None = None,
    known_paths: Sequence[str] = (),
    claim_cap: int = DEFAULT_CLAIM_CAP,
    episode_summary_cap: int = DEFAULT_EPISODE_SUMMARY_CAP,
    window_cap: int = DEFAULT_WINDOW_CAP,
    component_cap: int = DEFAULT_COMPONENT_SELECT_CAP,
    document_cap: int = DEFAULT_GLANCE_PICK_CAP,
    reasoning_effort: str | None = None,
    timeout: float | None = DEFAULT_EVIDENCE_SELECTION_TIMEOUT_SECONDS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[SelectedEvidence | None, dict[str, int], str | None]:
    """One fail-soft structured selection over every recall evidence face.

    The model returns only coordinates. Range/path validation, ranked safety anchors and
    final caps are mechanical; on failure the caller receives `None` and can use its exact
    ranked path without inventing a selection.
    """

    if (
        not claims
        and not episode_summaries
        and not windows
        and not components
        and not (glance and known_paths)
    ):
        return SelectedEvidence((), (), (), (), ()), zero_usage(), None
    messages = evidence_selection_messages(
        question,
        claims=claims,
        episode_summaries=episode_summaries,
        windows=windows,
        components=components,
        glance=glance,
        claim_cap=claim_cap,
        episode_summary_cap=episode_summary_cap,
        window_cap=window_cap,
        component_cap=component_cap,
        document_cap=document_cap,
    )
    selecting_model = (
        model.bind(extra_body={"reasoning": {"effort": reasoning_effort}})
        if reasoning_effort
        else model
    )
    try:
        structured = selecting_model.with_structured_output(
            EvidenceSelection, include_raw=True
        )
        call = structured.ainvoke(
            messages,
            config=invoke_config(
                "recall.fast.evidence_select", callbacks, trace_metadata
            ),
        )
        raw = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return None, zero_usage(), "timeout"
    except Exception:  # noqa: BLE001 — additive selector degrades to ranked evidence
        return None, zero_usage(), "error"

    usage = zero_usage()
    parsed: object = raw
    if isinstance(raw, Mapping):
        response = raw.get("raw")
        if isinstance(response, BaseMessage):
            usage = extract_usage(response)
        parsed = raw.get("parsed")
    if not isinstance(parsed, EvidenceSelection):
        return None, usage, "error"

    allowed_paths = set(known_paths)
    paths: list[str] = []
    for raw_path in parsed.document_paths:
        path = str(raw_path or "").strip()
        if path in allowed_paths and path not in paths:
            paths.append(path)
        if len(paths) >= document_cap:
            break
    return (
        SelectedEvidence(
            claim_indexes=_selected_indexes(
                parsed.claims,
                available=len(claims),
                cap=claim_cap,
                anchors=DEFAULT_SELECTION_CLAIM_ANCHORS,
            ),
            episode_indexes=_selected_indexes(
                parsed.episode_summaries,
                available=len(episode_summaries),
                cap=episode_summary_cap,
                anchors=DEFAULT_SELECTION_EPISODE_ANCHORS,
            ),
            window_indexes=_selected_indexes(
                parsed.raw_windows,
                available=len(windows),
                cap=window_cap,
                anchors=DEFAULT_SELECTION_WINDOW_ANCHORS,
            ),
            component_indexes=_selected_indexes(
                parsed.component_items,
                available=len(components),
                cap=component_cap,
                anchors=0,
            ),
            document_paths=tuple(paths),
            model_claim_count=len(
                _model_selected_indexes(
                    parsed.claims, available=len(claims), cap=claim_cap
                )
            ),
            model_episode_count=len(
                _model_selected_indexes(
                    parsed.episode_summaries,
                    available=len(episode_summaries),
                    cap=episode_summary_cap,
                )
            ),
            model_window_count=len(
                _model_selected_indexes(
                    parsed.raw_windows, available=len(windows), cap=window_cap
                )
            ),
            model_component_count=len(
                _model_selected_indexes(
                    parsed.component_items, available=len(components), cap=component_cap
                )
            ),
        ),
        usage,
        None,
    )


def selector_messages(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    component_evidence: Sequence[ComponentEvidence] = (),
    images: Sequence[RecallImage] = (),
    image_mode: Literal["caption", "native"] = "caption",
    answer_style: str = DEFAULT_ANSWER_STYLE,
) -> list[BaseMessage]:
    """[SystemMessage(fixed contract), HumanMessage(profile → snapshot → glance → evidence →
    as_of → input)]."""
    human = recall_human_content(
        question,
        claims,
        as_of=as_of,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
        component_evidence=component_evidence,
        images=images,
        image_mode=image_mode,
    )
    return [
        SystemMessage(content=selector_contract(answer_style)),
        HumanMessage(content=human),
    ]


def recall_human_content(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    component_evidence: Sequence[ComponentEvidence] = (),
    images: Sequence[RecallImage] = (),
    image_mode: Literal["caption", "native"] = "caption",
) -> str | list[dict]:
    """Build the volatile Human content shared by direct and agentic recall.

    Original image bytes enter only when the query caller explicitly selected native
    delivery. Caption mode keeps the same block-aligned derived evidence in text form.
    """
    evidence = _recall_human_evidence(
        claims,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
        component_evidence=component_evidence,
    )
    tail = _recall_human_tail(question, as_of)
    if not images:
        return evidence + tail
    header = prompt("recall.section.images_header", count=len(images))
    if image_mode == "caption":
        return (
            evidence
            + "\n\n"
            + header
            + "\n"
            + "\n".join(_render_recall_image(image) for image in images)
            + tail
        )

    human: list[dict] = [{"type": "text", "text": evidence + "\n\n" + header}]
    for recall_image in images:
        if recall_image.data is None:
            raise ValueError(
                f"native image payload is missing for {recall_image.image.image_id!r}"
            )
        human.append(
            {"type": "text", "text": _render_recall_image(recall_image)}
        )
        human.append(
            create_image_block(
                base64=base64.b64encode(recall_image.data).decode("ascii"),
                mime_type=recall_image.image.mime_type,
                id=recall_image.image.image_id,
            )
        )
    human.append({"type": "text", "text": tail})
    return human


def _alias_human_content(content: str | list[dict]) -> tuple[str | list[dict], dict[str, str]]:
    """Apply query-local source handles to text-only or multimodal Human content."""

    if isinstance(content, str):
        return alias_sources(content)
    aliaser = SessionAliaser()
    aliased: list[dict] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            aliased.append({**block, "text": aliaser.alias(str(block.get("text") or ""))})
        else:
            aliased.append(block)
    return aliased, aliaser.handle_map


async def answer_with_selector(
    model: BaseChatModel,
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    component_evidence: Sequence[ComponentEvidence] = (),
    images: Sequence[RecallImage] = (),
    image_mode: Literal["caption", "native"] = "caption",
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    run_name: str = "recall.fast",
    reasoning_effort: str | None = None,
    answer_style: str = DEFAULT_ANSWER_STYLE,
    on_token: TokenSink | None = None,
) -> tuple[str, dict[str, int], dict[str, str]]:
    """One selector round: assemble → (pre-hook: alias source ids) → invoke → (answer,
    usage, handle→real_id map). The LLM only ever sees/copies short query-local `sNN`
    handles; the caller reverse-binds them (business side / UI).

    `reasoning_effort` — optional override of the answering model's reasoning effort
    (e.g. "high"/"xhigh"). None (the default) sends NOTHING: the request body is
    byte-identical to the pre-knob behavior and the provider default applies. When set,
    it rides the OpenAI-compatible `extra_body` as `{"reasoning": {"effort": ...}}` —
    the wire shape OpenRouter expects — bound to THIS answer invoke only (the glance
    pass and every other call are untouched). Measurement plumbing; product callers
    pass nothing."""
    system, human = selector_messages(
        question,
        claims,
        as_of=as_of,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
        component_evidence=component_evidence,
        images=images,
        image_mode=image_mode,
        answer_style=answer_style,
    )
    aliased_human, handle_map = _alias_human_content(human.content)
    # `bind` rather than a constructor knob: the client instance is shared across roles
    # (wiring caches by model spec), so the override must live on this call, not the client.
    answering_model = (
        model.bind(extra_body={"reasoning": {"effort": reasoning_effort}})
        if reasoning_effort
        else model
    )
    response = await invoke_or_stream(
        answering_model,
        [system, HumanMessage(content=aliased_human)],
        config=invoke_config(run_name, callbacks, trace_metadata),
        on_token=on_token,
    )
    content = response.content
    text = content if isinstance(content, str) else str(content)
    return text.strip(), extract_usage(response), handle_map


def _text_blocks(content: str | list[dict]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _raw_delta(chunk: BaseMessage) -> str:
    """The JSON a structured answer is being written as, in either shape a provider sends it.

    Native structured output arrives as message CONTENT; a schema riding a function call
    arrives as tool-call argument deltas. Both are the same JSON, so both are streamed."""
    return message_text(chunk.content) or "".join(
        str(call.get("args") or "")
        for call in getattr(chunk, "tool_call_chunks", None) or []
    )


def _merge_raw(merged: BaseMessage | None, chunk: BaseMessage) -> BaseMessage:
    if merged is None:
        return chunk
    try:
        return merged + chunk  # type: ignore[operator]
    except TypeError:
        # A provider that ends the stream with a whole AIMessage rather than a chunk: keep
        # the later one, which is the complete message.
        return chunk


def split_structured(structured) -> tuple[Any, Any]:  # noqa: ANN001
    """The chat model and the parser INSIDE a `with_structured_output(..., include_raw=True)`.

    Why this exists, and why it is not a micro-optimisation: that helper returns
    `RunnableMap(raw=llm) | RunnableWithFallbacks(parser)`, and `RunnableWithFallbacks`
    implements no `transform`/`atransform`. Streaming the CHAIN therefore falls back to the
    default "buffer the whole input stream, then run" — the model's deltas are folded into one
    message before the parser is even tried, and the chain yields EXACTLY ONE value, at the
    end. A caller watching that stream sees a single "token" carrying the finished JSON: not a
    stream at all, and precisely the wait streaming exists to remove.

    Streaming the model itself and handing the merged message to the SAME parser gives real
    deltas and byte-identical parsing — the parser already only ever saw a merged streamed
    message on this path.

    Returns `(None, None)` for any other shape. A langchain that reorganises this internally
    must degrade to the historical chain call, never crash a live answer.
    """
    try:
        head, tail = structured.first, structured.last
        model = head.steps__["raw"]
    except (AttributeError, KeyError, TypeError):
        return None, None
    if not hasattr(model, "astream") or not hasattr(tail, "ainvoke"):
        return None, None
    return model, tail


async def _stream_structured(
    structured,  # a Runnable from with_structured_output(..., include_raw=True)
    messages: list,
    *,
    config: dict,
    timeout: float | None,
    on_token: TokenSink,
) -> dict:
    """The structured answer call, streamed — same return shape the `ainvoke` branch has.

    A structured answer is JSON on the wire, and the JSON is what the provider emits token by
    token (as content, or as tool-call argument deltas when the schema rides a function call).
    Those RAW deltas are what is streamed: a reader watching a structured answer being written
    sees provisional text, and the parsed answer replaces it the moment the call settles. The
    alternative — showing nothing until the JSON parses — is the wait this whole feature
    exists to remove.

    THE MODEL IS STREAMED, NOT THE CHAIN (`split_structured` explains why the chain cannot
    be). The merged message then goes through the chain's own parser, so `parsed` /
    `parsing_error` are produced by exactly the code the non-streaming branch uses.

    A chain of an unrecognised shape falls back to streaming the chain — one late value rather
    than none, which is what this call did before the split existed.
    """
    model, parser = split_structured(structured)

    async def drain_model() -> dict:
        merged: BaseMessage | None = None
        async for chunk in model.astream(messages, config=config):
            delta = _raw_delta(chunk)
            if delta:
                on_token(delta)
            merged = _merge_raw(merged, chunk)
        if merged is None:
            return {"raw": None, "parsed": None, "parsing_error": None}
        out = await parser.ainvoke({"raw": merged}, config=config)
        if isinstance(out, Mapping):
            return dict(out)
        return {"raw": merged, "parsed": out, "parsing_error": None}

    async def drain_chain() -> dict:
        """The historical whole-chain stream: kept only as the fall-back for an unknown shape.

        `parsed` is tracked by hand rather than by summing the chunk dicts: a parsed pydantic
        model is not addable, so folding the parts with `+` would raise on the last one and
        turn a good answer into a degradation."""
        raw_message: BaseMessage | None = None
        parsed: object = None
        parsing_error: object = None
        async for part in structured.astream(messages, config=config):
            if not isinstance(part, Mapping):
                parsed = part if part is not None else parsed
                continue
            chunk = part.get("raw")
            if isinstance(chunk, BaseMessage):
                delta = _raw_delta(chunk)
                if delta:
                    on_token(delta)
                raw_message = _merge_raw(raw_message, chunk)
            if part.get("parsed") is not None:
                parsed = part["parsed"]
            if part.get("parsing_error") is not None:
                parsing_error = part["parsing_error"]
        return {"raw": raw_message, "parsed": parsed, "parsing_error": parsing_error}

    drain = drain_chain if model is None else drain_model
    if timeout:
        async with asyncio.timeout(timeout):
            return await drain()
    return await drain()


async def answer_with_structured(
    model: BaseChatModel,
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    episode_summaries: Sequence[EpisodeSummary] = (),
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    timelines: Sequence[TimelineBlock] = (),
    component_evidence: Sequence[ComponentEvidence] = (),
    images: Sequence[RecallImage] = (),
    image_mode: Literal["caption", "native"] = "caption",
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    run_name: str = "recall.fast",
    reasoning_effort: str | None = None,
    answer_style: str = DEFAULT_ANSWER_STYLE,
    timeout: float | None = DEFAULT_STRUCTURED_ANSWER_TIMEOUT_SECONDS,
    on_token: TokenSink | None = None,
    # The `all` strategy's schema: one bounded evidence-review field emitted BEFORE the
    # answer, plus the contract clause that asks for it. Off = byte-for-byte the historical
    # structured call, which is what `ranked` and `select` keep making.
    deliberate: bool = False,
) -> tuple[str, str, dict[str, int], dict[str, str], str | None, str | None, str | None]:
    """Structured final answer with mechanically admitted evidence citations.

    Provider/schema failure retries through the historical text answer once and exposes the
    degradation reason. A successful structured call keeps answer text and citations apart;
    only exact citation spans present in the aliased evidence are appended.

    Returns the deliberation as its seventh element: the text of the review when one was
    asked for and produced, None otherwise (including on the degraded fallback, which
    answers through the historical text contract and has no such field).
    """

    human = recall_human_content(
        question,
        claims,
        as_of=as_of,
        windows=windows,
        episode_summaries=episode_summaries,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
        timelines=timelines,
        component_evidence=component_evidence,
        images=images,
        image_mode=image_mode,
    )
    aliased_human, handle_map = _alias_human_content(human)
    answering_model = (
        model.bind(extra_body={"reasoning": {"effort": reasoning_effort}})
        if reasoning_effort
        else model
    )
    usage = zero_usage()
    degraded: str | None = None
    parsed: object = None
    schema = DeliberatedRecallAnswer if deliberate else StructuredRecallAnswer
    try:
        structured = answering_model.with_structured_output(schema, include_raw=True)
        messages = [
            SystemMessage(
                content=structured_answer_contract(answer_style, deliberate=deliberate)
            ),
            HumanMessage(content=aliased_human),
        ]
        config = invoke_config(run_name, callbacks, trace_metadata)
        if on_token is None:
            call = structured.ainvoke(messages, config=config)
            raw = await (asyncio.wait_for(call, timeout) if timeout else call)
        else:
            raw = await _stream_structured(
                structured, messages, config=config, timeout=timeout, on_token=on_token
            )
        parsed = raw
        if isinstance(raw, Mapping):
            response = raw.get("raw")
            if isinstance(response, BaseMessage):
                usage = extract_usage(response)
            parsed = raw.get("parsed")
        if not isinstance(parsed, schema):
            degraded = "error"
    except asyncio.TimeoutError:
        degraded = "timeout"
    except Exception:  # noqa: BLE001 — explicit fallback to the historical text contract
        degraded = "error"

    if not isinstance(parsed, schema):
        fallback, fallback_usage, fallback_handles = await answer_with_selector(
            model,
            question,
            claims,
            as_of=as_of,
            windows=windows,
            episode_summaries=episode_summaries,
            profile=profile,
            glance=glance,
            snapshot=snapshot,
            full_documents=full_documents,
            window_notes=window_notes,
            timelines=timelines,
        component_evidence=component_evidence,
            images=images,
            image_mode=image_mode,
            callbacks=callbacks,
            trace_metadata=trace_metadata,
            run_name=run_name,
            reasoning_effort=reasoning_effort,
            answer_style=answer_style,
            on_token=on_token,
        )
        return (
            strip_citations(fallback),
            fallback,
            add_usage(usage, fallback_usage),
            fallback_handles,
            None,
            degraded,
            None,
        )

    allowed = set(iter_answer_citations(_text_blocks(aliased_human)))
    citations: list[str] = []
    for candidate in parsed.citations:
        marker = str(candidate or "").strip()
        references = tuple(iter_answer_citations(marker))
        if (
            not marker
            or strip_citations(marker)
            or not references
            or any(reference not in allowed for reference in references)
            or any(source not in handle_map for source, _start, _end in references)
        ):
            continue
        if marker not in citations:
            citations.append(marker)
    answer_text = parsed.answer.strip()
    answer = answer_text
    if citations:
        answer = (answer + " " + " ".join(citations)).strip()
    # Bounded HERE rather than in the schema: the clause states 600 characters, and a model
    # that overruns it must cost a trimmed note, never a parse failure and a second turn.
    review = getattr(parsed, "deliberation", "") or ""
    deliberation = review.strip()[:DELIBERATION_CHARS] or None
    return (
        answer_text,
        answer,
        usage,
        handle_map,
        parsed.answer_kind,
        None,
        deliberation,
    )


# ------------------------------------------------------- the glance selection pass (B)


class DocumentSelection(BaseModel):
    """Structured output of the glance pass: 0..K paths, and nothing else.

    A list of paths rather than free text because the result is CONSUMED mechanically (each
    path is looked up in the document set and dropped if absent) — a prose answer would have
    to be parsed, and a parse this pass cannot verify is a way to read a hallucinated path as
    an instruction."""

    paths: list[str] = Field(default_factory=list)


def glance_selection_contract(cap: int = DEFAULT_GLANCE_PICK_CAP) -> str:
    """The System contract for the glance pass — NOT the answer contract.

    Named apart from `selector_contract()` on purpose. That one is the fast lane's ANSWERING
    posture (it "selects" an answer out of evidence); this one selects DOCUMENTS to read and
    never answers anything. Two different jobs, two different contracts, no shared prose."""
    return prompt("recall.fast.select.contract", cap=cap)


def glance_selection_messages(
    question: str, glance: str, *, cap: int = DEFAULT_GLANCE_PICK_CAP
) -> list[BaseMessage]:
    """[SystemMessage(the pass's contract), HumanMessage(glance → question)]."""
    return [
        SystemMessage(content=glance_selection_contract(cap)),
        HumanMessage(
            content=prompt(
                "recall.fast.select.request", glance=glance, question=question, cap=cap
            )
        ),
    ]


async def select_glance_documents(
    model: BaseChatModel,
    question: str,
    glance: str,
    *,
    known_paths: Sequence[str],
    cap: int = DEFAULT_GLANCE_PICK_CAP,
    timeout: float | None = DEFAULT_GLANCE_TIMEOUT_SECONDS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[tuple[str, ...], dict[str, int], str | None]:
    """One small structured call: glance + question → the paths worth reading in full.

    Returns `(paths, token_usage, degraded_reason)`. Fail-soft by construction, because this
    pass is ADDITIVE: a timeout, a provider error, a non-schema reply or a path that is not in
    `known_paths` all degrade to selecting less (or nothing) and let the answer proceed on
    retrieval alone. `degraded_reason` distinguishes "the pass ran and chose nothing" (None —
    the normal, common outcome) from "the pass never delivered" (telemetry).

    Selecting nothing is not a failure and is not retried: an empty selection is exactly what
    a question already covered by matching fragments should produce.
    """
    messages = glance_selection_messages(question, glance, cap=cap)
    config = invoke_config("recall.fast.select", callbacks, trace_metadata)
    try:
        # Inside the guard: a model that does not implement structured output at all raises
        # right here, and that is the same class of failure as a provider error — the lane
        # must keep answering, not 500 because a keyless model lacks a capability.
        structured = model.with_structured_output(DocumentSelection, include_raw=True)
        call = structured.ainvoke(messages, config=config)
        raw = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return (), zero_usage(), "timeout"
    except Exception:  # noqa: BLE001 — an additive pass never fails the answer
        return (), zero_usage(), "error"

    usage = zero_usage()
    parsed: object = raw
    if isinstance(raw, Mapping):
        response = raw.get("raw")
        if isinstance(response, BaseMessage):
            usage = extract_usage(response)
        parsed = raw.get("parsed")
    if not isinstance(parsed, DocumentSelection):
        return (), usage, "error"

    # Only paths that actually exist survive: the glance is the model's whole view of the
    # library, so anything outside it is invented, and an invented path would otherwise be
    # reported as an expanded document.
    allowed = set(known_paths)
    picked: list[str] = []
    for raw_path in parsed.paths:
        path = str(raw_path or "").strip()
        if path in allowed and path not in picked:
            picked.append(path)
        if len(picked) >= cap:
            break
    return tuple(picked), usage, None


# ------------------------- the retrieval planning + claim rerank passes (both opt-in)

DEFAULT_PLAN_TIMEOUT_SECONDS = 15.0
DEFAULT_RERANK_TIMEOUT_SECONDS = 30.0

#: Safety ceiling on how many pooled candidates one rerank call may score. When a reranker
#: is on, the pool handed to it is the FULL deduped union of every query's hits — RRF is
#: score-blind, so pre-truncating with it would discard candidates the reranker exists to
#: judge. This cap only guards the provider's own per-call document limit (Cohere rerank
#: accepts up to 1000); the RRF head is what survives if the union ever exceeds it.
RERANK_POOL_HARD_CAP = 1000


class QueryPlan(BaseModel):
    """Structured output of the planning pass: 0..K extra retrieval queries.

    A list of strings consumed mechanically (deduped against the question and each other,
    truncated to the cap) — the pass proposes searches, it never controls anything else."""

    queries: list[str] = Field(default_factory=list)




async def plan_retrieval_queries(
    model: BaseChatModel,
    question: str,
    *,
    cap: int,
    timeout: float | None = DEFAULT_PLAN_TIMEOUT_SECONDS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[tuple[str, ...], dict[str, int], str | None]:
    """One small structured call BEFORE retrieval: question → extra search queries.

    The fast lane's answer to multi-aspect questions without result-driven loops (those
    belong to deep recall): the model splits the question into the distinct things that
    must be found, each retrieved at full strength alongside the verbatim question.
    Fail-soft like the glance pass: timeout/provider error/non-schema reply all degrade to
    planning nothing, and an empty plan is the normal outcome for a single-aspect question.
    """
    messages = [
        SystemMessage(content=prompt("recall.fast.plan.contract", cap=cap)),
        HumanMessage(content=prompt("recall.fast.plan.request", question=question, cap=cap)),
    ]
    config = invoke_config("recall.fast.plan", callbacks, trace_metadata)
    try:
        structured = model.with_structured_output(QueryPlan, include_raw=True)
        call = structured.ainvoke(messages, config=config)
        raw = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return (), zero_usage(), "timeout"
    except Exception:  # noqa: BLE001 — an additive pass never fails the answer
        return (), zero_usage(), "error"

    usage = zero_usage()
    parsed: object = raw
    if isinstance(raw, Mapping):
        response = raw.get("raw")
        if isinstance(response, BaseMessage):
            usage = extract_usage(response)
        parsed = raw.get("parsed")
    if not isinstance(parsed, QueryPlan):
        return (), usage, "error"

    seen = {question.strip().casefold()}
    picked: list[str] = []
    for raw_query in parsed.queries:
        query = str(raw_query or "").strip()
        if not query or query.casefold() in seen:
            continue
        seen.add(query.casefold())
        picked.append(query)
        if len(picked) >= cap:
            break
    return tuple(picked), usage, None


async def rerank_claims(
    reranker: "Reranker",
    question: str,
    candidates: Sequence[RetrievedClaim],
    *,
    cap: int,
    timeout: float | None = DEFAULT_RERANK_TIMEOUT_SECONDS,
) -> tuple[list[RetrievedClaim], str | None]:
    """Score the pooled candidates with a dedicated reranker and keep the best `cap`.

    RRF stays the candidate generator (cheap, score-blind); a cross-encoder reranker reads
    question and claim text together and returns real relevance scores — the magnitude
    judgement fusion cannot make. The answering model is deliberately NOT used here: it
    already reads every surviving claim while answering, so asking it to rank first would
    be the same judgement twice (a caller wanting deeper answer-time judgement raises
    `reasoning_effort` instead).

    Mechanics: valid scored indexes lead (score order, stamped into `.score`), the pool's
    own order backfills to the cap — so a sparse or partial rerank reorders evidence but
    never loses recall relative to the un-reranked lane. Fail-soft: timeout or provider
    error returns the pool head unchanged with a degradation marker."""
    if not candidates:
        return [], None
    fallback = list(candidates[:cap])
    try:
        call = reranker.rerank(
            question, [c.text for c in candidates], top_n=len(candidates)
        )
        results = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return fallback, "timeout"
    except Exception:  # noqa: BLE001 — an additive pass never fails the answer
        return fallback, "error"

    scored: dict[int, float] = {}
    for result in results:
        index = int(result.index)
        if 0 <= index < len(candidates) and index not in scored:
            scored[index] = float(result.score)
    chosen = sorted(scored, key=lambda i: scored[i], reverse=True)[:cap]
    remainder = [i for i in range(len(candidates)) if i not in scored]
    ordered = [
        replace(candidates[i], score=scored[i]) if i in scored else candidates[i]
        for i in (*chosen, *remainder)
    ][:cap]
    return ordered, None


async def retrieve_windows(
    user_id: UserId,
    query: str,
    *,
    lexical: LexicalIndex | None,
    vectors: VectorIndex | None,
    embeddings,  # langchain_core.embeddings.Embeddings
    limit: int = DEFAULT_WINDOW_CAP,
) -> list[RecallHit]:
    """L1+L2 body windows for the answer's recall face (empty if raw indices absent).

    Lexical blocks, raw/caption vectors and episode-description vectors rank independently,
    then ordinary RRF and source-span overlap suppression produce one bounded evidence list. No path
    receives a quota: exact identifiers and dates remain able to outrank broad semantics.
    """
    if lexical is None or vectors is None or limit <= 0:
        return []
    return await rag_recall(
        user_id,
        query,
        lexical=lexical,
        vectors=vectors,
        embeddings=embeddings,
        limit=limit,
    )


async def assemble_windows(
    hits: list[RecallHit],
    *,
    content: ContentStore | None,
    user_id: UserId,
    order: bool = True,
    assembly: Mapping[str, int] | None = None,
) -> list:
    """Post-retrieval assembly over raw window hits: lexical expansion → overlap dedup → per-source cap
    → lost-in-the-middle order. With no ContentStore (langchain-only path) the raw hits are
    returned unchanged so no caller breaks.

    `order=False` stops one step short, at score-descending order. Only the annotation join
    wants that: which windows are high-value is not known until the claims have been matched
    against them, so the positional ordering has to happen after the join, not before it.

    `assembly` (default None = `expand_and_merge`'s own defaults, byte-for-byte) is an
    override mapping forwarded verbatim to `expand_and_merge` — the assembly caps
    (`per_source_cap`, `forward_blocks`, `forward_char_budget`, `max_passage_chars`,
    `merge_gap_blocks`) stay defined in ONE place, and an unknown key fails loudly as a
    TypeError rather than being silently dropped. It exists for measurement work (the
    eval bench sweeps these caps); product callers pass nothing and are unchanged."""
    if content is None or not hits:
        return list(hits)
    passages = await expand_and_merge(
        hits, content=content, user_id=user_id, **dict(assembly or {})
    )
    return order_lost_in_middle(passages) if order else passages


def _span_overlaps(items: Sequence[object], source_id: str, start: int, end: int) -> bool:
    return any(
        str(getattr(item, "source_id")) == source_id
        and int(getattr(item, "block_start")) <= end
        and start <= int(getattr(item, "block_end"))
        for item in items
    )


async def expand_claim_provenance(
    user_id: UserId,
    claims: Sequence[RetrievedClaim],
    *,
    content: ContentStore | None,
    existing: Sequence[object] = (),
    claim_cap: int = 16,
    passage_cap: int = 12,
) -> list[Passage]:
    """Follow selected canonical claims to authoritative, deduplicated L0 passages."""

    if content is None or claim_cap <= 0 or passage_cap <= 0:
        return []
    cache: dict[str, NormalizedSource] = {}
    passages: list[Passage] = []
    for claim in claims[:claim_cap]:
        for citation in claim.citations:
            source_id = str(citation.source_id)
            if _span_overlaps(
                (*existing, *passages),
                source_id,
                citation.block_start,
                citation.block_end,
            ):
                continue
            source = cache.get(source_id)
            if source is None:
                source = await content.get(user_id, citation.source_id)
                cache[source_id] = source
            blocks = [
                block
                for block in source.blocks
                if citation.block_start <= block.index <= citation.block_end
            ]
            if not blocks:
                raise ValueError(
                    f"claim citation {source_id} ¶{citation.block_start}-{citation.block_end} "
                    "does not resolve to L0 blocks"
                )
            passages.append(
                Passage(
                    source_id=citation.source_id,
                    block_start=citation.block_start,
                    block_end=citation.block_end,
                    text="\n".join(block.text for block in blocks),
                    paths=("claim-provenance",),
                    score=claim.score,
                    section_path=tuple(blocks[0].section_path),
                    source_title=source.raw.title,
                    source_occurred_on=source.raw.occurred_on(),
                )
            )
            if len(passages) >= passage_cap:
                return passages
    return passages


async def expand_episode_provenance(
    user_id: UserId,
    summaries: Sequence[EpisodeSummary],
    *,
    content: ContentStore | None,
    existing: Sequence[object] = (),
    episode_cap: int = 4,
) -> list[Passage]:
    """Follow selected derived episodes to their authoritative L0 spans."""

    if content is None or episode_cap <= 0:
        return []
    cache: dict[str, NormalizedSource] = {}
    passages: list[Passage] = []
    for summary in summaries[:episode_cap]:
        source_id = str(summary.source_id)
        if _span_overlaps(
            (*existing, *passages),
            source_id,
            summary.block_start,
            summary.block_end,
        ):
            continue
        source = cache.get(source_id)
        if source is None:
            source = await content.get(user_id, summary.source_id)
            cache[source_id] = source
        blocks = [
            block
            for block in source.blocks
            if summary.block_start <= block.index <= summary.block_end
        ]
        if not blocks:
            raise ValueError(
                f"episode span {source_id} ¶{summary.block_start}-{summary.block_end} "
                "does not resolve to L0 blocks"
            )
        passages.append(
            Passage(
                source_id=summary.source_id,
                block_start=summary.block_start,
                block_end=summary.block_end,
                text="\n".join(block.text for block in blocks),
                paths=("episode-provenance",),
                score=summary.score,
                section_path=tuple(blocks[0].section_path),
                source_title=source.raw.title,
                source_occurred_on=source.raw.occurred_on(),
            )
        )
    return passages


async def fast_recall(
    user_id: UserId,
    question: str,
    *,
    as_of: datetime,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    model: BaseChatModel,
    answer_model: BaseChatModel | None = None,
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    content: ContentStore | None = None,
    media: MediaStore | None = None,
    image_mode: Literal["caption", "native"] = "caption",
    image_cap: int = DEFAULT_IMAGE_CAP,
    profile: str | None = None,
    cap: int = DEFAULT_CLAIM_CAP,
    claim_candidate_cap: int = DEFAULT_CLAIM_CANDIDATE_CAP,
    window_cap: int = DEFAULT_WINDOW_CAP,
    window_candidate_cap: int = DEFAULT_WINDOW_CANDIDATE_CAP,
    episode_summary_cap: int = DEFAULT_EPISODE_SUMMARY_CAP,
    # `ranked` preserves the historical fixed-head context. `select` spends one structured
    # model call after retrieval to compose a bounded mix across claims, derived episodes,
    # raw windows and canonical documents. The selector returns coordinates only; the
    # framework validates them and keeps deterministic ranked anchors.
    # `all` is the third: the pool `select` would have JUDGED is handed to the answer whole —
    # no selection call, no score truncation — so the only thing between retrieval and the
    # answer is assembly. Its one bound is `all_context_chars`.
    evidence_strategy: Literal["ranked", "select", "all"] = "ranked",
    selection_reasoning_effort: str | None = None,
    evidence_selection_timeout: float | None = DEFAULT_EVIDENCE_SELECTION_TIMEOUT_SECONDS,
    # `all` only, and its ONLY ceiling: how many characters the assembled evidence faces may
    # occupy. Over it the lane drops windows, then episode summaries, then the lowest-ranked
    # claims, and states the counts (`apply_context_ceiling`). 0 = no ceiling.
    all_context_chars: int = DEFAULT_ALL_CONTEXT_CHARS,
    # Whether the structured answer schema opens with a bounded `deliberation` field — the
    # evidence review no selection call performed. None = follow the strategy (`all` asks for
    # one, `ranked`/`select` do not, so their wire is unchanged by construction); True/False
    # states it outright, which is what a measurement needs. Ignored under `answer_format`
    # `text`, which has no schema to put a field in.
    deliberate: bool | None = None,
    # `text` preserves the historical answer wire. `structured` asks for answer text,
    # answer kind and citations separately, then mechanically admits only exact spans that
    # were present in the evidence context.
    answer_format: Literal["text", "structured"] = "text",
    structured_answer_timeout: float | None = DEFAULT_STRUCTURED_ANSWER_TIMEOUT_SECONDS,
    claim_provenance_passage_cap: int = 12,
    episode_provenance_passage_cap: int = 4,
    # The SHAPE of the answer: "concise" (the bare exact value — graders, scripts),
    # "conversational" (a natural chat reply, the default), or "detailed" (a
    # self-contained written note). Style only — truth discipline is style-independent.
    answer_style: str = DEFAULT_ANSWER_STYLE,
    # The canonical documents at the answering snapshot. Supplied → the glance is rendered
    # into the prompt and the glance pass runs; omitted (None) → byte-for-byte the
    # retrieval-only lane, so no caller is forced to load canonical to ask a question.
    documents: Sequence[CanonicalDocument] | None = None,
    skill: object | None = None,
    packs: Sequence[object] = (),
    # The frozen snapshot this answer is pinned to, or None = today's base. It changes ONE
    # thing in this lane: the prompt states which snapshot is open. The evidence is already
    # snapshot-scoped upstream — the caller passed the snapshot tenant's indexes and the
    # document set read at its canonical ref.
    scope: SnapshotScope | None = None,
    # OFF by default, and the off path is byte-for-byte the lane above. On: every claim whose
    # cited span overlaps a retrieved window is MOVED out of the claim-notes section and hung
    # under that window as a footnote, and annotated windows are ordered as high-value units.
    # See `join_claims_to_windows` for why it is a move rather than a copy.
    annotate_windows: bool = False,
    window_note_cap: int = DEFAULT_WINDOW_NOTE_CAP,
    # None by default = `expand_and_merge`'s own assembly defaults, byte-for-byte. A mapping
    # here is forwarded verbatim through `assemble_windows` to `expand_and_merge` (e.g.
    # {"per_source_cap": 6}); the defaults stay defined in one place, and an unknown key
    # raises rather than silently doing nothing. Measurement plumbing — product callers
    # pass nothing.
    window_assembly: Mapping[str, int] | None = None,
    # OFF by default (0), and the off path is byte-for-byte the lane above. N > 0: every
    # document a retrieved claim lives in (top `timeline_doc_cap` by hit count, and only when
    # `documents` was supplied — the expansion reads canonical, never the index) is expanded
    # into a subject-timeline block of up to N sibling claims in document order. See
    # `build_subject_timelines`.
    timeline_expand: int = 0,
    timeline_doc_cap: int = DEFAULT_TIMELINE_DOC_CAP,
    glance_model: BaseChatModel | None = None,
    glance_pick_cap: int = DEFAULT_GLANCE_PICK_CAP,
    glance_timeout: float | None = DEFAULT_GLANCE_TIMEOUT_SECONDS,
    # OFF by default (0), and the off path is byte-for-byte the lane above. N > 0: one
    # planning call (on `plan_model`, falling back to `model`) derives up to N extra
    # retrieval queries BEFORE retrieval, and the claim face pools all queries through one
    # RRF fusion (`retrieve_claims_multi`). Planning sees only the question — result-driven
    # multi-round retrieval belongs to deep recall, not this lane.
    plan_queries_cap: int = 0,
    plan_model: BaseChatModel | None = None,
    plan_timeout: float | None = DEFAULT_PLAN_TIMEOUT_SECONDS,
    # OFF by default (None/0), and the off path is byte-for-byte the lane above. A Reranker
    # plus N > 0 widens claim retrieval to an N-candidate pool and lets the reranker's real
    # relevance scores pick the `cap` that survive (see `rerank_claims` for why the
    # answering model is not used for this).
    reranker: Reranker | None = None,
    rerank_candidates: int = 0,
    rerank_timeout: float | None = DEFAULT_RERANK_TIMEOUT_SECONDS,
    # `answer_model` splits the final generation from the cheap recall-role model used by
    # planning/glance. None preserves the historical one-model lane. A None reasoning effort
    # sends nothing; a value (e.g. "xhigh") overrides the ANSWERING call via OpenRouter's
    # `{"reasoning": {"effort": ...}}` extra_body — see `answer_with_selector`. The
    # glance pass never takes it. Measurement plumbing — product callers pass nothing.
    reasoning_effort: str | None = None,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    # Component paths: None → whatever the enabled components offer; () → none, which also
    # skips the routing call entirely (no path, no cost).
    fast_paths: Sequence[FastPath] | None = None,
    route_model: BaseChatModel | None = None,
    route_timeout: float | None = DEFAULT_ROUTE_TIMEOUT_SECONDS,
    path_timeout: float | None = DEFAULT_PATH_TIMEOUT_SECONDS,
    # Character ceiling on the whole component face. A path's own cap bounds item counts;
    # this bounds the context those items may occupy, and every cut it makes is stated.
    component_budget_chars: int = DEFAULT_COMPONENT_BUDGET_CHARS,
    # The SUBJECT's IANA timezone, for the routing turn only (and only when a path is
    # offered — with none the turn does not happen and this is never read). A path may take
    # calendar days as arguments, and a calendar day is only meaningful in someone's zone;
    # the routing model resolves a relative expression against `as_of` in THIS zone. Core
    # cannot resolve a profile, so the service passes what `time_context_for` decided.
    zone: str = "UTC",
    # Watch the lane AS IT RUNS. `on_event` receives a `StageEvent` when each stage (and each
    # concurrent retrieval child) begins and when it settles — the same measure sites that
    # produce the final `stages`, so the live picture and the finished result are one clock.
    # `on_token` receives the answer's text deltas while the answering call is still running.
    # Both default to None, and with both None this function takes exactly the code path it
    # took before either existed.
    on_event: StageEventSink | None = None,
    on_token: TokenSink | None = None,
) -> FastAnswer:
    """fast recall: the knowledge base glance + L3 claims + L1/L2 body windows → one answer.

    Two disjoint retrieval faces answer one question: claims give precision + citation
    provenance, body windows give recall over content never lifted into claims (e.g. a
    distill-treated record whose compile produced only abstract meta-claims). Each face
    is internally RRF-fused; they are presented as two sections, never cross-fused.

    When a ContentStore is wired the raw window hits go through the post-retrieval assembly
    pipeline (expand → merge/dedup → per-source cap → lost-in-the-middle order), so a bare
    hit carries its surrounding context; without one the raw hits render as before.

    TWO BRANCHES, ONE WALL CLOCK. When `documents` is supplied, retrieval (A) and the glance
    selection pass (B) are launched together under one `asyncio.gather`, so the lane costs
    max(A, B) + the answer call rather than A + B + the answer. B is a single small
    structured call whose output is a handful of paths, so it is normally the faster of the
    two. B is strictly additive: it selects nothing for most questions, and a timeout or
    provider error degrades to the retrieval-only answer with a `glance_degraded` marker —
    it can never fail or delay the answer past its own timeout.

    The glance itself is present whether or not B selects anything: the shape of the library
    is context for every question, not a reward for a successful selection.

    The retrieval faces are independent network work (each embeds the query + hits
    Meili/Qdrant), so they run concurrently on the event loop via `asyncio.gather` — the
    wall-clock is the slower face, not their sum, and the double query-embed overlaps
    instead of stacking. `gather` returns results in argument order, so `claims` and
    `raw_windows` bind exactly as they did under the previous thread-pool fan-out."""

    if evidence_strategy not in {"ranked", "select", "all"}:
        raise ValueError("evidence_strategy must be 'ranked', 'select' or 'all'")
    if answer_format not in {"text", "structured"}:
        raise ValueError("answer_format must be 'text' or 'structured'")

    # Every stage below is measured into this one recorder and emitted once, at the end, in
    # the fixed vocabulary — so "which stage came back and in what order" is a property of
    # `stage_timing.STAGE_ORDER`, not of how many `if` branches this function happened to
    # take (recall/stage_timing.py).
    timer = StageRecorder(on_event=on_event)
    lane_started = time.perf_counter()

    # The planning pass runs BEFORE retrieval (its whole output is retrieval input), so it
    # is the one stage that adds sequential wall-clock — which is why it is opt-in.
    planned: tuple[str, ...] = ()
    plan_usage = zero_usage()
    plan_degraded: str | None = None
    if plan_queries_cap > 0:
        with timer.measure("plan"):
            planned, plan_usage, plan_degraded = await plan_retrieval_queries(
                plan_model or model,
                question,
                cap=plan_queries_cap,
                timeout=plan_timeout,
                callbacks=callbacks,
                trace_metadata=trace_metadata,
            )
            timer.preview("plan", {"cap": plan_queries_cap, "queries": list(planned)})
        timer.degrade("plan", plan_degraded)

    # The claim face always retrieves beyond the final evidence wall. This is cheap index
    # work and leaves enough tail for containment dedup and multi-path disagreement. With a
    # reranker on, `rerank_candidates` may widen it further: it is the
    # per-query/per-face retrieval depth, and the reranker judges the FULL deduped union
    # against the original question (RRF pre-truncation would silently drop candidates it
    # never saw — fusion order is kept only for dedup, backfill and the failure fallback).
    # The final `cap` remains independent from either candidate depth.
    # Built BEFORE the retrieval closures below rather than beside the glance pass that reads
    # it: `titles` is what lets a claim's preview say which PAGE it came from ("Pricing")
    # instead of which file ("docs/product/pricing.md"), and the claim face is the first
    # thing that needs it.
    #
    # Read through `display_identity` and not through `document_title`, so the ONE document
    # whose own title names nothing — a frozen rollover volume, filed as `a02` with no `# `
    # heading in its body — previews under the active document it is history of. Every
    # preview surface in this lane draws its document name from this one mapping, so the
    # correction reaches all of them at once.
    glance: str | None = None
    by_path: dict[str, CanonicalDocument] = {}
    titles: dict[str, str] = {}
    if documents is not None:
        glance = render_canonical_glance(documents, skill, packs=packs)
        by_path = {doc.path: doc for doc in documents}
        titles = {path: display_identity(by_path, path).title for path in by_path}

    reranking = reranker is not None and rerank_candidates > 0
    claim_pool = max(
        cap,
        claim_candidate_cap,
        rerank_candidates if reranking else 0,
    )

    async def retrieve_claim_face() -> list[RetrievedClaim]:
        with timer.measure(child_name("claims")):
            if planned or reranking:
                found = await retrieve_claims_multi(
                    user_id,
                    (question, *planned),
                    claim_lexical=claim_lexical,
                    claim_vectors=claim_vectors,
                    embeddings=embeddings,
                    limit=claim_pool,
                    pool_cap=RERANK_POOL_HARD_CAP if reranking else None,
                )
            else:
                found = await retrieve_claims(
                    user_id,
                    question,
                    claim_lexical=claim_lexical,
                    claim_vectors=claim_vectors,
                    embeddings=embeddings,
                    limit=claim_pool,
                )
            timer.preview(
                child_name("claims"),
                {"pool": claim_pool, **face_preview(found, claim_entries(found, titles))},
            )
            return found

    async def retrieve_window_face() -> list[RecallHit]:
        # Not merely "0 ms": with no raw index wired this lane does not exist, and the strip
        # must be able to say so. `retrieve_windows` would return [] either way.
        if lexical is None or vectors is None:
            return []
        with timer.measure(child_name("windows")):
            hits = await retrieve_windows(
                user_id,
                question,
                lexical=lexical,
                vectors=vectors,
                embeddings=embeddings,
                limit=max(window_cap, window_candidate_cap),
            )
            timer.preview(
                child_name("windows"), face_preview(hits, window_entries(hits))
            )
            return hits

    offered_paths = list(fast_paths) if fast_paths is not None else fast_paths_from_registry(user_id)

    async def component_branch() -> tuple[list[ComponentEvidence], dict[str, int], str | None]:
        # One routing turn chooses paths and arguments; the chosen paths run concurrently.
        # The built-in faces never wait for this arm — they are gathered beside it.
        if not offered_paths:
            return [], zero_usage(), None
        with timer.measure("route"):
            chosen, usage, degraded, rejected = await route_paths(
                route_model or model,
                question,
                offered_paths,
                as_of=as_of,
                zone=zone,
                timeout=route_timeout,
                callbacks=callbacks,
                trace_metadata=trace_metadata,
            )
            # What the routing turn DECIDED, which is the only thing that explains the
            # `retrieve.path:*` children that follow it. A turn that chose nothing says so:
            # "none" is a finding about the question, not a blank.
            calls = [
                call_line(path.name, args.model_dump()) for path, args in chosen
            ] + [
                call_line(row.path, row.args, rejected=row.degraded) for row in rejected
            ]
            timer.preview(
                "route",
                {
                    "tool_calls": calls
                    or no_call_line(path.name for path in offered_paths)
                },
            )
        timer.degrade("route", degraded)
        ran = await run_paths(
            user_id,
            chosen,
            question=question,
            scope=scope,
            documents=documents,
            as_of=as_of,
            timeout=path_timeout,
        )
        # Each chosen path timed ITSELF inside `run_paths` (they run concurrently, so only a
        # per-run clock says which lookup was the slow one). A rejected call never ran and
        # carries 0 ms with its `invalid_args` reason.
        for row in (*ran, *rejected):
            timer.record_path(
                row.path,
                row.elapsed_ms,
                detail=row.degraded,
                preview={
                    "call": call_line(row.path, row.args, rejected=row.degraded),
                    "hits": len(row.claims) + len(row.windows),
                    "items": [
                        *claim_entries(row.claims, titles),
                        *window_entries(row.windows),
                    ][:PREVIEW_ITEMS],
                },
            )
        return [*ran, *rejected], usage, degraded

    async def retrieval_branch() -> tuple[list[RetrievedClaim], list[RecallHit], tuple]:
        return await asyncio.gather(  # type: ignore[return-value]
            retrieve_claim_face(),
            retrieve_window_face(),
            component_branch(),
        )

    selected: tuple[str, ...] = ()
    select_usage = zero_usage()
    degraded: str | None = None
    # The historical document-only glance pass stays on the ranked path. The quality path
    # sees the same glance in its one cross-face selection call below, so enabling it does
    # not accidentally add two sequential model judgements before the answer.
    async def glance_branch():
        with timer.measure(child_name("glance")):
            picked = await select_glance_documents(
                glance_model or model,
                question,
                glance,
                known_paths=tuple(by_path),
                cap=glance_pick_cap,
                timeout=glance_timeout,
                callbacks=callbacks,
                trace_metadata=trace_metadata,
            )
            timer.preview(
                child_name("glance"),
                {
                    "offered": len(by_path),
                    "cap": glance_pick_cap,
                    # A chosen document previews as its title and the definition under it —
                    # what the page SAYS it is, which is exactly what the pass judged it on.
                    **face_preview(picked[0], _glance_entries(picked[0], by_path)),
                },
            )
            return picked

    # `retrieve` is the GATHER's wall-clock — what the concurrency actually cost — while each
    # arm reports its own. That is why the children sum to more than the parent, and why
    # `route` (a model call inside this same gather) can be longer than nothing else here.
    if evidence_strategy == "ranked" and glance and by_path:
        with timer.measure("retrieve"):
            (claims_raw, raw_windows, component_arm), (selected, select_usage, degraded) = (
                await asyncio.gather(retrieval_branch(), glance_branch())
            )
        timer.degrade(child_name("glance"), degraded)
    else:
        with timer.measure("retrieve"):
            claims_raw, raw_windows, component_arm = await retrieval_branch()
    component_evidence, route_usage, route_degraded = component_arm
    component_evidence = list(component_evidence)
    component_rerank_degraded: str | None = None
    if reranker is not None and any(e.claims or e.windows for e in component_evidence):
        # The lookup returned exact results with no rank of their own; when a real
        # cross-encoder is wired it makes the relevance judgement that lexical overlap only
        # approximates. Fail-soft: the lexical order stands and the fallback is telemetry.
        with timer.measure("rerank"):
            before = sum(len(e.claims) + len(e.windows) for e in component_evidence)
            component_evidence, component_rerank_degraded = await rerank_component_evidence(
                reranker, question, component_evidence, as_of=as_of, timeout=rerank_timeout
            )
            kept = [c for e in component_evidence for c in e.claims]
            timer.preview(
                "rerank",
                {
                    "component_candidates": before,
                    "component_kept": sum(
                        len(e.claims) + len(e.windows) for e in component_evidence
                    ),
                    "component_top": claim_entries(kept, titles),
                },
            )
        timer.degrade("rerank", component_rerank_degraded)

    rerank_degraded: str | None = None
    evidence_selection_usage = zero_usage()
    evidence_selection_degraded: str | None = None
    episode_summary_candidates = 0
    model_selected_claims = 0
    model_selected_episode_summaries = 0
    model_selected_windows = 0
    model_selected_component_items = 0
    # The merge runs once. In `select` it runs against the candidate pool, before selection;
    # on every other path it runs at assembly, against the evidence that survived.
    component_merged = False
    render_component_face = True
    if evidence_strategy == "select":
        # Episode summaries are a first-class evidence face. Build them over candidate
        # breadth before selection; only the selected bounded subset reaches the answer.
        with timer.measure("assemble"):
            episode_candidates = await build_episode_summaries(
                raw_windows,
                content=content,
                user_id=user_id,
                cap=max(episode_summary_cap, window_candidate_cap),
            )
            timer.preview(
                "assemble",
                {
                    "episode_summaries": len(episode_candidates),
                    "episode_chars": _chars(episode_candidates),
                },
            )
        episode_summary_candidates = len(episode_candidates)
        # The component face joins the pool instead of bypassing it: one selection call
        # decides the whole context. Ordering, dedup against the pool and the caps have
        # already run, so what the selector reads is the same face the ranked path renders.
        component_pool: list[ComponentCandidate] = []
        if component_evidence:
            component_evidence, claims_raw = merge_component_evidence(
                component_evidence,
                claims=claims_raw,
                windows=raw_windows,
                budget_chars=component_budget_chars,
            )
            component_merged = True
            component_pool = component_candidate_pool(component_evidence)
        with timer.measure("select"):
            evidence_choice, evidence_selection_usage, evidence_selection_degraded = (
                await select_evidence(
                    glance_model or model,
                    question,
                    claims=claims_raw,
                    episode_summaries=episode_candidates,
                    windows=raw_windows,
                    components=component_pool,
                    glance=glance,
                    known_paths=tuple(by_path),
                    claim_cap=cap,
                    episode_summary_cap=episode_summary_cap,
                    window_cap=window_cap,
                    document_cap=glance_pick_cap,
                    reasoning_effort=selection_reasoning_effort,
                    timeout=evidence_selection_timeout,
                    callbacks=callbacks,
                    trace_metadata=trace_metadata,
                )
            )
            timer.preview(
                "select",
                _selection_preview(
                    evidence_choice,
                    claims=claims_raw,
                    episodes=episode_candidates,
                    windows=raw_windows,
                    components=component_pool,
                    titles=titles,
                ),
            )
        timer.degrade("select", evidence_selection_degraded)
        if evidence_choice is None:
            # Fail-soft means the exact ranked heads remain usable; no partial/unvalidated
            # model output is allowed to influence context.
            claims = claims_raw[:cap]
            episode_summaries = episode_candidates[:episode_summary_cap]
            selected_raw_windows = raw_windows[:window_cap]
        else:
            model_selected_claims = evidence_choice.model_claim_count
            model_selected_episode_summaries = evidence_choice.model_episode_count
            model_selected_windows = evidence_choice.model_window_count
            model_selected_component_items = evidence_choice.model_component_count
            claims = [claims_raw[index] for index in evidence_choice.claim_indexes]
            episode_summaries = [
                episode_candidates[index] for index in evidence_choice.episode_indexes
            ]
            selected_raw_windows = [
                raw_windows[index] for index in evidence_choice.window_indexes
            ]
            # A selected component item is rendered as what it IS — a claim among the claim
            # notes, a window among the raw excerpts — carrying `via:<path>` so its exact
            # provenance survives the merge. Unselected component items are dropped: the
            # selector saw them and did not want them.
            for index in evidence_choice.component_indexes:
                picked = component_pool[index]
                if picked.claim is not None:
                    label = f"via:{picked.path}"
                    claims.append(
                        picked.claim
                        if label in picked.claim.labels
                        else replace(picked.claim, labels=(*picked.claim.labels, label))
                    )
                elif picked.window is not None:
                    selected_raw_windows.append(picked.window)
            # The face itself is not a section in this mode — it was candidates, and its
            # chosen members are now inside the ordinary faces.
            render_component_face = False
            selected = evidence_choice.document_paths
    elif evidence_strategy == "all":
        # The same pool `select` would have been offered, handed over whole. No selection
        # call (`select` stays `skipped` in the stage strip, and nothing here consults a
        # model), no score truncation, and the faces are built, merged, ordered and rendered
        # exactly as the selector's chosen set would have been — so what an answer misses on
        # this path cannot be blamed on a selection. The one bound is `all_context_chars`,
        # applied after assembly (below), because a window's real size is only known once it
        # has been expanded and merged.
        with timer.measure("assemble"):
            episode_summaries = await build_episode_summaries(
                raw_windows,
                content=content,
                user_id=user_id,
                cap=max(episode_summary_cap, window_candidate_cap),
            )
            timer.preview(
                "assemble",
                {
                    "episode_summaries": len(episode_summaries),
                    "episode_chars": _chars(episode_summaries),
                },
            )
        episode_summary_candidates = len(episode_summaries)
        # `claim_pool` can be DEEPER than the candidate cap when a reranker is configured for
        # the deployment. `all` never reranks, so it hands over exactly the stated pool
        # rather than whatever depth another feature happened to ask the index for.
        claims = claims_raw[:claim_candidate_cap]
        selected_raw_windows = list(raw_windows)
        if component_evidence:
            # Merged against the pool, like `select` does — dedup, `via:` labels and the char
            # budget all run once — and then every candidate it leaves is taken, because
            # taking everything is the whole strategy.
            component_evidence, labelled = merge_component_evidence(
                component_evidence,
                claims=claims,
                windows=selected_raw_windows,
                budget_chars=component_budget_chars,
            )
            claims = list(labelled)
            component_merged = True
            for candidate in component_candidate_pool(component_evidence):
                if candidate.claim is not None:
                    label = f"via:{candidate.path}"
                    claims.append(
                        candidate.claim
                        if label in candidate.claim.labels
                        else replace(
                            candidate.claim, labels=(*candidate.claim.labels, label)
                        )
                    )
                elif candidate.window is not None:
                    selected_raw_windows.append(candidate.window)
            # As in `select`: its members are inside the ordinary faces now, so rendering the
            # face again under its own header would be the same evidence twice.
            render_component_face = False
    elif reranking:
        with timer.measure("rerank"):
            claims, rerank_degraded = await rerank_claims(
                reranker, question, claims_raw, cap=cap, timeout=rerank_timeout
            )
            timer.preview(
                "rerank",
                {
                    "candidates": len(claims_raw),
                    "kept": len(claims),
                    "top": claim_entries(claims, titles),
                },
            )
        timer.degrade("rerank", rerank_degraded)
        with timer.measure("assemble"):
            episode_summaries = await build_episode_summaries(
                raw_windows,
                content=content,
                user_id=user_id,
                cap=episode_summary_cap,
            )
            timer.preview(
                "assemble",
                {
                    "episode_summaries": len(episode_summaries),
                    "episode_chars": _chars(episode_summaries),
                },
            )
        episode_summary_candidates = len(episode_summaries)
        selected_raw_windows = raw_windows[:window_cap]
    else:
        claims = claims_raw[:cap]
        with timer.measure("assemble"):
            episode_summaries = await build_episode_summaries(
                raw_windows,
                content=content,
                user_id=user_id,
                cap=episode_summary_cap,
            )
            timer.preview(
                "assemble",
                {
                    "episode_summaries": len(episode_summaries),
                    "episode_chars": _chars(episode_summaries),
                },
            )
        episode_summary_candidates = len(episode_summaries)
        selected_raw_windows = raw_windows[:window_cap]
    # Built from the FULL capped hit set, before the annotation join may move claims out of
    # the notes section: which documents the retrieval touched is a property of retrieval,
    # not of where a claim happens to be rendered.
    timelines: list[TimelineBlock] = []
    if timeline_expand > 0 and by_path:
        timelines = build_subject_timelines(
            claims, by_path, per_doc=timeline_expand, doc_cap=timeline_doc_cap
        )
    # Everything from here to the answer call is evidence assembly — L0 reads, merges and
    # media fetches that cost real time between the last model turn and the next one. It is
    # accumulated into one `assemble` stage rather than left as an unexplained gap under
    # `total`.
    with timer.measure("assemble"):
        windows = await assemble_windows(
            selected_raw_windows,
            content=content,
            user_id=user_id,
            # `all` orders LAST, after its ceiling has run: lost-in-the-middle placement puts
            # the strongest window at the TAIL, and a ceiling that drops from the tail of an
            # ordered list would drop the strongest evidence it has.
            order=not annotate_windows and evidence_strategy != "all",
            assembly=window_assembly,
        )
        timer.preview(
            "assemble", {"windows": len(windows), "window_chars": _chars(windows)}
        )
        if evidence_strategy == "all":
            offered_chars = _chars(claims) + _chars(episode_summaries) + _chars(windows)
            claims, episode_summaries, windows, dropped = apply_context_ceiling(
                claims, episode_summaries, windows, ceiling=all_context_chars
            )
            if dropped:
                # Never silent: the field says the context was cut, the preview says by how
                # much and out of which face.
                evidence_selection_degraded = "all:truncated"
                timer.preview(
                    "assemble",
                    {
                        "context_ceiling": all_context_chars,
                        "dropped": section_line(
                            tuple(dropped.items()),
                            offered_chars
                            - _chars(claims)
                            - _chars(episode_summaries)
                            - _chars(windows),
                        ),
                        "dropped_windows": dropped["windows"],
                        "dropped_episode_summaries": dropped["episode_summaries"],
                        "dropped_claims": dropped["claims"],
                    },
                )
            if not annotate_windows:
                windows = order_lost_in_middle(windows)
    # Query tools request original modalities from the selected RAW evidence face. L0
    # passages followed from claim/episode provenance below are verification context, not a
    # hidden way to pull extra media into a call.
    image_windows = list(windows)
    if evidence_strategy == "select" and content is not None:
        # L3 and derived L2 are navigation, not authority. Once selected, follow their
        # source spans back to bounded L0 passages and deduplicate them against the raw face.
        with timer.measure("assemble"):
            claim_passages = await expand_claim_provenance(
                user_id,
                claims,
                content=content,
                existing=windows,
                claim_cap=len(claims),
                passage_cap=claim_provenance_passage_cap,
            )
            episode_passages = await expand_episode_provenance(
                user_id,
                episode_summaries,
                content=content,
                existing=(*windows, *claim_passages),
                episode_cap=episode_provenance_passage_cap,
            )
            timer.preview(
                "assemble",
                {
                    "provenance_passages": len(claim_passages) + len(episode_passages),
                    "provenance_chars": _chars(claim_passages) + _chars(episode_passages),
                },
            )
        windows = [*windows, *claim_passages, *episode_passages]
        if not annotate_windows:
            windows = order_lost_in_middle(windows)
    with timer.measure("assemble"):
        images = await collect_window_images(
            user_id,
            image_windows,
            content=content,
            media=media,
            image_mode=image_mode,
            cap=image_cap,
        )
        # The LAST assemble pass, so every section is in hand: the counts stay (they are what
        # the passes measured) and one line states what the assembly actually produced —
        # `claims 8 · windows 12 · episodes 4 · 11.5k chars`. A merged preview keeps both.
        timer.preview(
            "assemble",
            {
                # Restated at the end rather than left at what the first pass measured: by
                # here the window face has grown by the provenance passages, and one panel
                # showing `windows 6` beside `windows 20` is two numbers for one word.
                "windows": len(windows),
                "window_chars": _chars(windows),
                "images": len(images),
                "image_mode": image_mode,
                "sections": section_line(
                    (
                        ("claims", len(claims)),
                        ("windows", len(windows)),
                        ("episodes", len(episode_summaries)),
                        ("images", len(images)),
                    ),
                    _chars(claims) + _chars(windows) + _chars(episode_summaries),
                ),
            },
        )
    window_notes: list[tuple[object, tuple[RetrievedClaim, ...]]] | None = None
    if annotate_windows:
        claims, paired = join_claims_to_windows(
            claims, windows, cap=window_note_cap
        )
        window_notes = order_lost_in_middle(paired, priority=lambda p: bool(p[1]))
        windows = [w for w, _ in window_notes]
    # A superseded claim is history, whichever face found it: labelled and placed last.
    claims = mark_superseded_claims(claims, documents)
    if component_evidence and not component_merged:
        # The ranked faces keep everything they carry — they are ordered, and the reranker
        # or the selector has already judged them. The component face yields instead: it
        # shows only what they do not already contain, says how much it hid, and spends its
        # cap on the remainder (recall/paths.py `merge_component_evidence`).
        # An annotated claim is still shown — under its window instead of in the notes
        # section — so it counts as ranked-face content for both the dedup and the `via:`
        # labels, and is put back exactly where it was.
        annotated = [claim for _, notes in (window_notes or ()) for claim in notes]
        component_evidence, labelled = merge_component_evidence(
            component_evidence,
            claims=[*claims, *annotated],
            windows=windows,
            budget_chars=component_budget_chars,
        )
        claims = labelled[: len(claims)]
        if window_notes is not None:
            tail = iter(labelled[len(claims) :])
            window_notes = [
                (window, tuple(next(tail) for _ in notes)) for window, notes in window_notes
            ]
    # Reading the selected documents is a local git read the caller already paid for (they
    # are in `documents`), so the expansion costs nothing on the wire.
    expanded = [by_path[path] for path in selected]
    # In `select` the face was candidates, and what the selector took now lives inside the
    # ordinary faces; rendering it a second time under its own header would be the same
    # evidence twice. It stays in `used_component_evidence` either way — the audit trail of
    # what was looked up does not depend on how the context was composed.
    shown_component_evidence = component_evidence if render_component_face else ()
    # Built from the very arguments both answer branches below are handed, once, so the two
    # cannot disagree about what was shown. It observes the render; it never alters it.
    manifest = evidence_manifest(
        claims=claims,
        windows=windows,
        episode_summaries=episode_summaries,
        window_notes=window_notes,
        timelines=timelines,
        component_evidence=shown_component_evidence,
        full_documents=expanded,
    )
    answer_trace_metadata = {
        **(trace_metadata or {}),
        "image_count": len(images),
        "image_mode": image_mode,
        "evidence_strategy": evidence_strategy,
        "answer_format": answer_format,
    }
    answer_kind: str | None = None
    answer_format_degraded: str | None = None
    deliberation: str | None = None
    # The review the selection call no longer performs, asked for inside the answering call
    # instead. Follows the strategy unless the caller states it; a `text` answer has no
    # schema to carry it, so the flag cannot reach a lane that could not honour it.
    deliberating = (
        (evidence_strategy == "all") if deliberate is None else bool(deliberate)
    ) and answer_format == "structured"
    if answer_format == "structured":
        with timer.measure("answer"):
            (
                answer_text,
                answer,
                usage,
                citation_handles,
                answer_kind,
                answer_format_degraded,
                deliberation,
            ) = await answer_with_structured(
                answer_model or model,
                question,
                claims,
                as_of=as_of,
                windows=windows,
                episode_summaries=episode_summaries,
                profile=profile,
                glance=glance,
                snapshot=scope_declaration(scope),
                full_documents=expanded,
                window_notes=window_notes,
                timelines=timelines,
                component_evidence=shown_component_evidence,
                images=images,
                image_mode=image_mode,
                callbacks=callbacks,
                trace_metadata=answer_trace_metadata,
                run_name="recall.fast",
                reasoning_effort=reasoning_effort,
                answer_style=answer_style,
                timeout=structured_answer_timeout,
                on_token=on_token,
                deliberate=deliberating,
            )
            # One call normally; TWO when the structured contract failed and the historical
            # text answer had to be made — which is what the extra seconds were spent on.
            timer.preview(
                "answer",
                {
                    "format": answer_format,
                    "turns": 2 if answer_format_degraded else 1,
                    **({"deliberation": preview_head(deliberation)} if deliberation else {}),
                    **_answer_input_preview(
                        claims, windows, episode_summaries, expanded, glance
                    ),
                },
            )
        timer.degrade("answer", answer_format_degraded)
    else:
        with timer.measure("answer"):
            answer, usage, citation_handles = await answer_with_selector(
                answer_model or model,
                question,
                claims,
                as_of=as_of,
                windows=windows,
                episode_summaries=episode_summaries,
                profile=profile,
                glance=glance,
                snapshot=scope_declaration(scope),
                full_documents=expanded,
                window_notes=window_notes,
                timelines=timelines,
                component_evidence=shown_component_evidence,
                images=images,
                image_mode=image_mode,
                callbacks=callbacks,
                trace_metadata=answer_trace_metadata,
                run_name="recall.fast",
                reasoning_effort=reasoning_effort,
                answer_style=answer_style,
                on_token=on_token,
            )
            timer.preview(
                "answer",
                {
                    "format": answer_format,
                    "turns": 1,
                    **_answer_input_preview(
                        claims, windows, episode_summaries, expanded, glance
                    ),
                },
            )
        answer_text = strip_citations(answer)
    # `total` is recorded LAST and wraps the whole lane, so `total >= every other stage`
    # holds by construction rather than by assertion (rounding is monotonic).
    timer.record("total", (time.perf_counter() - lane_started) * 1000.0)
    total_usage = add_usage(usage, select_usage)
    total_usage = add_usage(total_usage, plan_usage)
    total_usage = add_usage(total_usage, evidence_selection_usage)
    total_usage = add_usage(total_usage, route_usage)
    return FastAnswer(
        answer=answer,
        answer_text=answer_text,
        used_claims=tuple(claims),
        token_usage=total_usage,
        used_windows=tuple(windows),
        citation_handles=citation_handles,
        glance_chars=len(glance or ""),
        expanded_documents=selected,
        glance_degraded=degraded,
        annotated_claims=sum(len(n) for _, n in (window_notes or ())),
        annotated_windows=sum(1 for _, n in (window_notes or ()) if n),
        timeline_documents=tuple(block.document_path for block in timelines),
        timeline_claims=sum(len(block.claims) for block in timelines),
        planned_queries=planned,
        plan_degraded=plan_degraded,
        rerank_degraded=rerank_degraded,
        image_count=len(images),
        image_mode=image_mode,
        claim_candidates=len(claims_raw),
        episode_summary_candidates=episode_summary_candidates,
        window_candidates=len(raw_windows),
        model_selected_claims=model_selected_claims,
        model_selected_episode_summaries=model_selected_episode_summaries,
        model_selected_windows=model_selected_windows,
        model_selected_component_items=model_selected_component_items,
        used_episode_summaries=tuple(episode_summaries),
        evidence_strategy=evidence_strategy,
        evidence_selection_degraded=evidence_selection_degraded,
        answer_format=answer_format,
        answer_kind=answer_kind,
        answer_format_degraded=answer_format_degraded,
        deliberation=deliberation,
        route_offered=tuple(p.name for p in offered_paths),
        route_chosen=tuple(e.key() for e in component_evidence if e.degraded != "invalid_args"),
        route_degraded=route_degraded,
        component_candidates=evidence_counts(component_evidence),
        used_component_evidence=tuple(component_evidence),
        component_rerank_degraded=component_rerank_degraded,
        stages=timer.emit(),
        evidence_manifest=manifest,
    )
