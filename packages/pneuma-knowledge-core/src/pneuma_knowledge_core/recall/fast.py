"""fast mode — canonical-annotation-dense recall (architecture.md §7; milestone M4).

Three seals, all mechanical (§0 discipline 1), not prose pleas:

1. **Fixed answer contract.** The SystemMessage is `selector_contract()` verbatim — a
   byte-stable string (I5). It is a top-down account (identity → the two evidence forms
   → world-facts about the evidence → answer shape), not a rule list; it never carries
   a timestamp, the question, or claim content, so the provider cache is earned by
   assembly order.
2. **Annotation cap + dedup.** Claims come from a dual-path retrieval (Meili claims +
   Qdrant claim layer) fused by RRF, deduped by (document_path, anchor), then capped to
   `cap` (default 40) before rendering.
3. **Everything volatile in the Human turn, question LAST.** Evidence sections render
   first (glance → claim notes → raw excerpts → any fully-read documents), then as_of +
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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..canonical_glance import render_canonical_glance
from ..compile.documents import render_document
from ..domain.canonical import CanonicalDocument, Citation
from ..domain.ids import AnchorId, UserId, SourceId
from ..ports.claim_index import ClaimLexicalIndex, ClaimVectorIndex
from ..ports.content_store import ContentStore
from ..ports.lexical_index import LexicalIndex
from ..ports.vector_index import VectorIndex
from ..prompts import prompt
from .citation_alias import alias_sources
from .scope import SnapshotScope, scope_declaration
from .spine import CITE_SOURCE_LEVEL, CLOSE_ANSWER_HONESTLY, spine
from .assembly import (
    Passage,
    expand_and_merge,
    order_lost_in_middle,
    render_passages,
)
from .rag import RecallHit, _rrf_scores, rag_recall, rrf_fuse

DEFAULT_CLAIM_CAP = 40
DEFAULT_WINDOW_CAP = 8

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


def selector_contract() -> str:
    """The fast lane's System contract: head + shared spine.

    I5: byte-stable per prompt overlay. No timestamp, no question, no claim/window content —
    posture only. Assembled per call rather than at import so a startup-registered overlay
    reaches it."""
    return prompt("recall.fast.contract_head") + spine(
        CITE_SOURCE_LEVEL, CLOSE_ANSWER_HONESTLY
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


@dataclass(frozen=True)
class FastAnswer:
    answer: str
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


def zero_usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read": 0,
        "cache_creation": 0,
    }


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
    return RetrievedClaim(
        anchor=AnchorId(hit.anchor),
        document_path=hit.document_path,
        section_path=tuple(hit.section_path or ()),
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
    )


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
    lexical_hits = await claim_lexical.search_claims(user_id, query, limit=limit)
    if query_embedding is None:
        query_embedding = await embeddings.aembed_query(query)
    vector_hits = await claim_vectors.search_claims(
        user_id, query_embedding, limit=limit
    )

    info: dict[tuple, dict] = {}
    lexical_ranking: list[str] = []
    for hit in lexical_hits:
        key = (hit.document_path, hit.anchor)
        lexical_ranking.append(repr(key))
        entry = info.setdefault(key, {"hit": hit, "paths": []})
        if "lexical" not in entry["paths"]:
            entry["paths"].append("lexical")

    vector_ranking: list[str] = []
    for hit in vector_hits:
        key = (hit.document_path, hit.anchor)
        vector_ranking.append(repr(key))
        entry = info.setdefault(key, {"hit": hit, "paths": []})
        if "vector" not in entry["paths"]:
            entry["paths"].append("vector")

    fused = rrf_fuse([lexical_ranking, vector_ranking])
    scores = _rrf_scores([lexical_ranking, vector_ranking], 60)
    by_repr = {repr(k): k for k in info}

    claims: list[RetrievedClaim] = []
    for key_repr in fused:
        entry = info[by_repr[key_repr]]
        claims.append(
            _claim_from_hit(entry["hit"], entry["paths"], scores[key_repr])
        )
        if len(claims) >= limit:
            break
    return claims


def render_claims(claims: list[RetrievedClaim]) -> str:
    """Compact deterministic claim payload for the Human turn (input order preserved)."""
    lines: list[str] = []
    for c in claims:
        section = " › ".join(c.section_path) if c.section_path else ""
        head = f"[c:{c.anchor} · {c.document_path}"
        head += f" · {section}]" if section else "]"
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


def _render_window_section(windows: list) -> str:
    """Render the window payload: assembled Passages (labeled, context-expanded) when the
    hits carry a section_path, else the flat RecallHit rendering (langchain-only fallback)."""
    if windows and hasattr(windows[0], "section_path"):
        return render_passages(windows, header="")
    return render_windows(windows)


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


def recall_human(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
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
    claim is stated, not whether the claim section is there."""
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
    return (
        "\n\n".join(sections)
        + f"\n\nas_of: {as_of.isoformat()}\n"
        + prompt("recall.section.input", question=question)
    )


def selector_messages(
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
) -> list[BaseMessage]:
    """[SystemMessage(fixed contract), HumanMessage(profile → snapshot → glance → evidence →
    as_of → input)]."""
    human = recall_human(
        question,
        claims,
        as_of=as_of,
        windows=windows,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
    )
    return [SystemMessage(content=selector_contract()), HumanMessage(content=human)]


async def answer_with_selector(
    model: BaseChatModel,
    question: str,
    claims: list[RetrievedClaim],
    *,
    as_of: datetime,
    windows: list | None = None,
    profile: str | None = None,
    glance: str | None = None,
    snapshot: str | None = None,
    full_documents: Sequence[CanonicalDocument] = (),
    window_notes: Sequence[tuple[object, tuple[RetrievedClaim, ...]]] | None = None,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    run_name: str = "recall.fast",
) -> tuple[str, dict[str, int], dict[str, str]]:
    """One selector round: assemble → (pre-hook: alias source ids) → invoke → (answer,
    usage, handle→real_id map). The LLM only ever sees/copies short query-local `sNN`
    handles; the caller reverse-binds them (business side / UI)."""
    system, human = selector_messages(
        question,
        claims,
        as_of=as_of,
        windows=windows,
        profile=profile,
        glance=glance,
        snapshot=snapshot,
        full_documents=full_documents,
        window_notes=window_notes,
    )
    aliased_human, handle_map = alias_sources(human.content)
    response = await model.ainvoke(
        [system, HumanMessage(content=aliased_human)],
        config=invoke_config(run_name, callbacks, trace_metadata),
    )
    content = response.content
    text = content if isinstance(content, str) else str(content)
    return text.strip(), extract_usage(response), handle_map


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

    Reuses rag_recall verbatim; capped by count so uncompiled content still surfaces
    even when a source produced only abstract meta-claims."""
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
) -> list:
    """Post-retrieval assembly over raw window hits: expand → merge/dedup → per-source cap
    → lost-in-the-middle order. With no ContentStore (langchain-only path) the raw hits are
    returned unchanged so no caller breaks.

    `order=False` stops one step short, at score-descending order. Only the annotation join
    wants that: which windows are high-value is not known until the claims have been matched
    against them, so the positional ordering has to happen after the join, not before it."""
    if content is None or not hits:
        return list(hits)
    passages = await expand_and_merge(hits, content=content, user_id=user_id)
    return order_lost_in_middle(passages) if order else passages


async def fast_recall(
    user_id: UserId,
    question: str,
    *,
    as_of: datetime,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    model: BaseChatModel,
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    content: ContentStore | None = None,
    profile: str | None = None,
    cap: int = DEFAULT_CLAIM_CAP,
    window_cap: int = DEFAULT_WINDOW_CAP,
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
    glance_model: BaseChatModel | None = None,
    glance_pick_cap: int = DEFAULT_GLANCE_PICK_CAP,
    glance_timeout: float | None = DEFAULT_GLANCE_TIMEOUT_SECONDS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
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

    async def retrieval_branch() -> tuple[list[RetrievedClaim], list[RecallHit]]:
        return await asyncio.gather(  # type: ignore[return-value]
            retrieve_claims(
                user_id,
                question,
                claim_lexical=claim_lexical,
                claim_vectors=claim_vectors,
                embeddings=embeddings,
                limit=cap,
            ),
            retrieve_windows(
                user_id,
                question,
                lexical=lexical,
                vectors=vectors,
                embeddings=embeddings,
                limit=window_cap,
            ),
        )

    glance: str | None = None
    by_path: dict[str, CanonicalDocument] = {}
    if documents is not None:
        glance = render_canonical_glance(documents, skill, packs=packs)
        by_path = {doc.path: doc for doc in documents}

    selected: tuple[str, ...] = ()
    select_usage = zero_usage()
    degraded: str | None = None
    if glance and by_path:
        (claims_raw, raw_windows), (selected, select_usage, degraded) = await asyncio.gather(
            retrieval_branch(),
            select_glance_documents(
                glance_model or model,
                question,
                glance,
                known_paths=tuple(by_path),
                cap=glance_pick_cap,
                timeout=glance_timeout,
                callbacks=callbacks,
                trace_metadata=trace_metadata,
            ),
        )
    else:
        claims_raw, raw_windows = await retrieval_branch()

    claims = claims_raw[:cap]
    windows = await assemble_windows(
        raw_windows, content=content, user_id=user_id, order=not annotate_windows
    )
    window_notes: list[tuple[object, tuple[RetrievedClaim, ...]]] | None = None
    if annotate_windows:
        claims, paired = join_claims_to_windows(
            claims, windows, cap=window_note_cap
        )
        window_notes = order_lost_in_middle(paired, priority=lambda p: bool(p[1]))
        windows = [w for w, _ in window_notes]
    # Reading the selected documents is a local git read the caller already paid for (they
    # are in `documents`), so the expansion costs nothing on the wire.
    expanded = [by_path[path] for path in selected]
    answer, usage, citation_handles = await answer_with_selector(
        model,
        question,
        claims,
        as_of=as_of,
        windows=windows,
        profile=profile,
        glance=glance,
        snapshot=scope_declaration(scope),
        full_documents=expanded,
        window_notes=window_notes,
        callbacks=callbacks,
        trace_metadata=trace_metadata,
        run_name="recall.fast",
    )
    return FastAnswer(
        answer=answer,
        used_claims=tuple(claims),
        token_usage=add_usage(usage, select_usage),
        used_windows=tuple(windows),
        citation_handles=citation_handles,
        glance_chars=len(glance or ""),
        expanded_documents=selected,
        glance_degraded=degraded,
        annotated_claims=sum(len(n) for _, n in (window_notes or ())),
        annotated_windows=sum(1 for _, n in (window_notes or ()) if n),
    )
