"""Briefing: preloaded Q&A session context assembly (architecture.md §7; M4).

A Briefing is a stable knowledge pack built once over a fixed snapshot, then reused
across many asks. Two scope halves compose:

- `scope.query` — one retrieval pass (claims dual-path + L1/L2 excerpts), selected by
  relevance then rendered in canonical order;
- `scope.source_ids` — **anchors historical raw data**: for each source, its materials
  card + every canonical claim that cites it (citation reverse lookup) + raw excerpts.

Invariant I5 (context assembly discipline): the SystemMessage carries ONLY
`briefing.system_prefix`'s raw bytes and is byte-stable across asks — it never contains
a timestamp or other volatile content. The live input and as_of ride the HumanMessage.
Cache hits are earned by correct assembly order, not optimized for.

Asks run on the shared bounded agentic loop (`recall.agentic.run_agent_loop`,
langchain `create_agent`): search_knowledge / fetch_verbatim as the tool face,
`_ASK_TOOL_BUDGET` rounds, forced tool-less finalize at the budget edge.

Determinism: the same (user, scope, snapshot) rebuilds a byte-identical system_prefix.
Every list is sorted by path / anchor / block — never a set/dict iteration order.

Both halves report their own per-stage wall-clock, each in the shape its own work has. The
BUILD is mechanical and has a fixed vocabulary, so it uses the fast lane's `StageRecorder`
(`BUILD_STAGE_ORDER`) — a stage that did not run is still emitted, marked `skipped`, which is
how "there was no query half" reads as a fact rather than as an absence. The ASK is an agentic
loop, so it uses `agentic.AgentTimings`: the ordered interleaving of turns and tool calls the
run actually took, `total` wrapping the LOOP (the pack was assembled once, long before).

I5 again: nothing measured reaches a SystemMessage — timings live on the result only.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from ..canonical_glance import render_canonical_glance
from ..domain.canonical import (
    CanonicalDocument,
    Citation,
    iter_canonical_citations,
)
from ..domain.ids import UserId, SourceId
from ..domain.snapshot import SnapshotRef
from ..ports.content_store import ContentStore
from ..prompts import prompt
from .agentic import AgentTimings, TokenSink, run_agent_loop, timed_tools
from .assembly import expand_and_merge, render_passages
from .citation_alias import SessionAliaser, iter_answer_citations
from .spine import CITE_PRECISE, CLOSE_ANSWER_HONESTLY, spine
from .fast import render_claims, retrieve_claims
from .projection import ProjectedClaim, claims_citing, project_snapshot_claims
from .rag import rag_recall
from .stage_timing import (
    RETRIEVE,
    claim_entries,
    StageEventSink,
    StageRecorder,
    StageTiming,
    child_name,
    window_entries,
)

def briefing_contract() -> str:
    """The briefing lane's System contract: head + shared spine.

    I5: byte-stable per prompt overlay. No snapshot ref, no as_of, no pack content — posture
    only."""
    return prompt("recall.briefing.contract_head") + spine(
        CITE_PRECISE, CLOSE_ANSWER_HONESTLY
    )

DEFAULT_TOOL_NAMES: tuple[str, ...] = ("fetch_verbatim", "search_knowledge")
_ASK_TOOL_BUDGET = 4

#: The build's stages, in the order the pack is assembled. `retrieve` is the query half's two
#: lookups; `expand` is what turns bare hits and anchored source ids into evidence with
#: provenance (context windows, materials cards, the citation reverse lookup, L0 excerpts);
#: `pack` is the deterministic assembly — glance, segment join, budget truncation. Unlike the
#: fast lane's gather, the children here run SEQUENTIALLY, so they sum to their parent.
BUILD_STAGE_ORDER: tuple[str, ...] = ("retrieve", "expand", "pack", "total")

#: The two lookups inside `retrieve`: the claim face and the L1/L2 body face. Named
#: `passages` because that is what this code path calls what comes back.
BUILD_RETRIEVE_CHILDREN: tuple[str, ...] = ("claims", "passages")

#: Spelled once so the measure sites and the vocabulary above cannot drift apart.
EXPAND = "expand"
PACK = "pack"
TOTAL = "total"


@dataclass
class BriefingScope:
    query: str | None = None
    source_ids: list[SourceId] = field(default_factory=list)
    budget_chars: int = 24_000


@dataclass(frozen=True)
class Briefing:
    user_id: UserId
    snapshot: SnapshotRef
    system_prefix: str
    tool_names: tuple[str, ...]
    claims_count: int = 0
    source_count: int = 0
    char_count: int = 0
    # The anchored sources (scope.source_ids). search_knowledge scopes retrieval to these
    # when non-empty; empty means the whole user KB is in scope.
    source_ids: tuple[str, ...] = ()
    # The build's per-stage wall-clock, in `BUILD_STAGE_ORDER`. Measured, not derived: a
    # briefing reconstructed from a stored row (the ask route) carries none, and says so by
    # carrying an empty tuple rather than zeros.
    stages: tuple[StageTiming, ...] = ()


@dataclass(frozen=True)
class AskAnswer:
    answer: str
    citations: tuple[Citation, ...]
    verbatim_fetches: tuple[dict, ...]
    token_usage: dict[str, int]
    # {handle: real_source_id} when consumption aliasing is on — the answer's `[cite: sNN]`
    # markers are query-local handles; the UI reverse-binds them (like the fast lane).
    citation_handles: dict[str, str] = field(default_factory=dict)
    # The ask loop's per-step wall-clock, in the order the steps happened: `turn:N` per model
    # turn, `tool:<name>` per tool call (the same call the matching `verbatim_fetches` /
    # search record carries `ms` for), `finalize` when the budget forced a closing call, and
    # `total` last. `total` wraps the LOOP — the pack it asks over was built earlier.
    stages: tuple[StageTiming, ...] = ()


def assemble_messages(
    briefing: Briefing, question: str, *, as_of: datetime, profile: str | None = None
) -> list[BaseMessage]:
    """Assemble the message list for one ask: profile → as_of → the owner's input.

    I5: SystemMessage = briefing.system_prefix verbatim (byte-stable across asks, no as_of).
    The per-owner profile (who is asking; the System tier explains what it is) and the live
    input ride the HumanMessage — the profile sits at the top, the input last."""
    parts: list[str] = []
    if profile:
        parts.append(f"{prompt('recall.section.profile_header')}\n{profile}")
    parts.append(
        f"as_of: {as_of.isoformat()}\n"
        + prompt("recall.section.input", question=question)
    )
    human = "\n\n".join(parts)
    return [SystemMessage(content=briefing.system_prefix), HumanMessage(content=human)]


# --------------------------------------------------------------------- pack assembly


def _sort_key(claim: ProjectedClaim | object) -> tuple:
    return (getattr(claim, "document_path", ""), getattr(claim, "section_path", ()), str(getattr(claim, "anchor", "")))


def _render_projected_claim(claim: ProjectedClaim) -> str:
    section = " › ".join(claim.section_path) if claim.section_path else ""
    head = f"[c:{claim.anchor} · {claim.document_path}"
    head += f" · {section}]" if section else "]"
    cites = "; ".join(
        f"{c.source_id} ¶{c.block_start}-{c.block_end}" for c in claim.citations
    )
    line = f"{head} {claim.text}"
    if cites:
        line += prompt("recall.briefing.provenance_suffix", cites=cites)
    return line


async def _query_section(
    user_id: UserId,
    query: str,
    *,
    claim_lexical=None,
    claim_vectors=None,
    embeddings=None,
    lexical=None,
    vectors=None,
    content: ContentStore | None = None,
    max_claims: int = 24,
    max_excerpts: int = 12,
    stages: StageRecorder | None = None,
) -> tuple[list[str], int]:
    """Render the scope.query knowledge — claims selected by relevance, laid out in
    canonical (path/anchor) order for byte-stability. Returns (segments, claim_count).

    `stages` is the build's recorder, threaded in rather than returned: the two lookups and
    the context expansion belong to different stages of the same build, so they have to be
    measured where they happen, not around this whole call."""
    lines: list[str] = []
    claim_count = 0
    stages = stages if stages is not None else StageRecorder(
        BUILD_STAGE_ORDER, BUILD_RETRIEVE_CHILDREN
    )

    if claim_lexical is not None and claim_vectors is not None and embeddings is not None:
        with stages.measure(RETRIEVE), stages.measure(child_name("claims")):
            retrieved = (await retrieve_claims(
                user_id,
                query,
                claim_lexical=claim_lexical,
                claim_vectors=claim_vectors,
                embeddings=embeddings,
                limit=max_claims,
            ))[:max_claims]
            stages.preview(
                child_name("claims"),
                {"cap": max_claims, "hits": len(retrieved), "items": claim_entries(retrieved)},
            )
        if retrieved:
            # select by relevance, render in canonical order (deterministic).
            ordered = sorted(retrieved, key=_sort_key)
            lines.append(
                prompt("recall.briefing.query_claims_header", query=query)
            )
            lines.append(render_claims(ordered))
            claim_count = len(ordered)

    if lexical is not None and vectors is not None and embeddings is not None:
        with stages.measure(RETRIEVE), stages.measure(child_name("passages")):
            hits = await rag_recall(
                user_id,
                query,
                lexical=lexical,
                vectors=vectors,
                embeddings=embeddings,
                limit=max_excerpts,
            )
            stages.preview(
                child_name("passages"),
                {"cap": max_excerpts, "hits": len(hits), "items": window_entries(hits)},
            )
        if hits:
            # Post-retrieval assembly: expand each bare hit into a context window, merge
            # near-contiguous ones, then lay out in canonical order for byte-stability.
            with stages.measure(EXPAND):
                passages = await expand_and_merge(
                    hits, content=content, user_id=user_id
                )
                stages.preview(
                    EXPAND,
                    {
                        "passages": len(passages),
                        "passage_chars": sum(len(p.text or "") for p in passages),
                    },
                )
            ordered = sorted(
                passages, key=lambda p: (str(p.source_id), p.block_start, p.block_end)
            )
            lines.append(prompt("recall.briefing.query_excerpts_header"))
            lines.append(render_passages(ordered, header=""))
    return lines, claim_count


async def _source_section(
    user_id: UserId,
    source_id: SourceId,
    all_claims: list[ProjectedClaim],
    snapshot_docs: list[CanonicalDocument],
    *,
    content: ContentStore | None,
    max_excerpt_blocks: int = 4,
    max_outline_sections: int = 60,
) -> tuple[list[str], int]:
    """Anchor one source: materials card + citing claims + raw excerpts (deterministic)."""
    sid = str(source_id)
    lines: list[str] = [prompt("recall.briefing.source_heading", source_id=sid)]

    # ① materials card: a canonical doc under materials/ that cites this source.
    cards = sorted(
        (
            d
            for d in snapshot_docs
            if d.path.startswith("materials/")
            and any(
                str(citation.source_id) == sid
                for citation in iter_canonical_citations(d.body)
            )
        ),
        key=lambda d: d.path,
    )
    if cards:
        lines.append(prompt("recall.briefing.material_cards_header"))
        for d in cards:
            lines.append(f"[{d.path}]\n{d.body.strip()}")

    # ② every canonical claim citing this source (citation reverse lookup).
    citing = sorted(claims_citing(all_claims, source_id), key=_sort_key)
    if citing:
        lines.append(prompt("recall.briefing.citing_claims_header"))
        for c in citing:
            lines.append(_render_projected_claim(c))

    # ③ structure outline + raw excerpts (L0), budget-bounded.
    if content is not None:
        try:
            ns = await content.get(user_id, source_id)
        except KeyError:
            ns = None
        if ns is not None:
            sections = sorted(ns.structure.sections, key=lambda s: s.start_block)
            # structure outline: the section paths the document contains, so the model
            # sees what is inside (e.g. a candidate roster) and can target search_knowledge.
            if sections:
                lines.append(prompt("recall.briefing.outline_header"))
                for span in sections[:max_outline_sections]:
                    path = " › ".join(span.path) if span.path else f"¶{span.start_block}"
                    lines.append(f"- {path}  ¶{span.start_block}-{span.end_block}")
                if len(sections) > max_outline_sections:
                    lines.append(
                        prompt(
                            "recall.briefing.outline_more",
                            count=len(sections) - max_outline_sections,
                        )
                    )
            excerpts: list[str] = []
            for span in sections[:max_excerpt_blocks]:
                block = next(
                    (b for b in ns.blocks if b.index == span.start_block), None
                )
                if block is not None:
                    path = " › ".join(span.path) if span.path else f"¶{span.start_block}"
                    excerpts.append(f"- [{path}] {block.text}")
            if excerpts:
                lines.append(prompt("recall.briefing.excerpts_header"))
                lines.extend(excerpts)
    return lines, len(citing)


async def build_briefing(
    user_id: UserId,
    scope: BriefingScope,
    *,
    snapshot: SnapshotRef,
    snapshot_docs: list[CanonicalDocument],
    content: ContentStore | None = None,
    claim_lexical=None,
    claim_vectors=None,
    embeddings=None,
    lexical=None,
    vectors=None,
    skill: object | None = None,
    packs: Sequence[object] = (),
    tool_names: tuple[str, ...] = DEFAULT_TOOL_NAMES,
    # Watch the build AS IT RUNS: one `StageEvent` when each stage begins and one when it
    # settles, from the same recorder that produces `Briefing.stages`. None = silent, and the
    # build is byte-identical to what it was before events existed.
    on_event: StageEventSink | None = None,
) -> Briefing:
    """Assemble a Briefing's stable knowledge pack over a fixed snapshot.

    Byte-stable per (user, scope, snapshot): claims/sources are projected from
    snapshot_docs and rendered in canonical order; the budget truncates the assembled
    pack deterministically. The fixed contract prefix is never truncated.

    The pack OPENS with the knowledge base glance (canonical_glance.py) — the same static
    shape fast and deep carry, with no selection pass, because a briefing is built once and
    reused across many asks so there is no per-question moment to select in. It is rendered
    from `snapshot_docs`, which the caller already loaded, and it is deterministic, so it does
    not cost the pack its byte-stability. `skill` supplies the declared families and `packs`
    their blurbs; without them the glance still lists what exists.

    The build is mechanical — no model call anywhere in it — which is exactly why its cost has
    to be reported per stage: when a build takes nine seconds the whole answer is in which
    retrieval or expansion it spent them. `Briefing.stages` carries the fixed vocabulary
    complete (`BUILD_STAGE_ORDER`), so a half that did not run — no `scope.query`, no anchored
    sources — is present and marked `skipped` rather than silently missing.
    """
    stages = StageRecorder(BUILD_STAGE_ORDER, BUILD_RETRIEVE_CHILDREN, on_event=on_event)
    build_started = time.perf_counter()

    all_claims = project_snapshot_claims(snapshot_docs)

    segments: list[str] = []
    claims_count = 0

    if snapshot_docs:
        with stages.measure(PACK):
            glance = render_canonical_glance(snapshot_docs, skill, packs=packs)
            segments.append(glance)
            stages.preview(
                PACK, {"documents": len(snapshot_docs), "glance_chars": len(glance)}
            )

    if scope.query:
        query_lines, qcount = await _query_section(
            user_id,
            scope.query,
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            lexical=lexical,
            vectors=vectors,
            content=content,
            stages=stages,
        )
        if query_lines:
            segments.append(
                prompt("recall.briefing.query_section_header")
                + "\n"
                + "\n".join(query_lines)
            )
            claims_count += qcount

    if scope.source_ids:
        source_segments: list[str] = []
        # deterministic: sources in sorted id order (never the input/set order).
        for sid in sorted(set(str(s) for s in scope.source_ids)):
            # Anchoring a source IS provenance expansion — the citation reverse lookup, the
            # materials card, the L0 read — so it accumulates onto the same `expand` stage
            # the query half's context windows land on, once per source.
            with stages.measure(EXPAND):
                src_lines, ccount = await _source_section(
                    user_id,
                    SourceId(sid),
                    all_claims,
                    snapshot_docs,
                    content=content,
                )
                stages.preview(
                    EXPAND,
                    {
                        "sources": len(set(str(x) for x in scope.source_ids)),
                        "source_chars": sum(len(line) for line in src_lines),
                    },
                )
            source_segments.append("\n".join(src_lines))
            claims_count += ccount
        if source_segments:
            segments.append(
                prompt("recall.briefing.source_section_header")
                + "\n"
                + "\n\n".join(source_segments)
            )

    with stages.measure(PACK):
        # Budget truncation on the knowledge pack (the fixed contract is exempt).
        pack = "\n\n".join(segments)
        if len(pack) > scope.budget_chars:
            pack = (
                pack[: scope.budget_chars].rstrip()
                + prompt("recall.briefing.budget_truncated")
            )

        contract = briefing_contract()
        system_prefix = contract + "\n" + pack + "\n" if pack else contract
        stages.preview(
            PACK,
            {
                "sections": len(segments),
                "pack_chars": len(pack),
                "budget_chars": scope.budget_chars,
                "prefix_chars": len(system_prefix),
            },
        )

    # `total` last and around everything above, so it bounds every other stage by
    # construction rather than by an assertion someone has to remember.
    stages.record(TOTAL, (time.perf_counter() - build_started) * 1000.0)

    return Briefing(
        user_id=user_id,
        snapshot=snapshot,
        system_prefix=system_prefix,
        tool_names=tuple(tool_names),
        claims_count=claims_count,
        source_count=len(set(str(s) for s in scope.source_ids)),
        char_count=len(system_prefix),
        source_ids=tuple(sorted(set(str(s) for s in scope.source_ids))),
        stages=stages.emit(),
    )


# ------------------------------------------------------------------------------- ask


#: The tool call currently running IN THIS TASK: `{"started": perf_counter, "record": dict}`.
#: A ContextVar and not an attribute for the same reason deep's is: langgraph runs a turn's
#: tool calls concurrently, each in its own task, so a shared slot would let one call's start
#: time stamp another call's record. A task gets its own copy of the context, which makes the
#: pairing mechanical rather than a matter of ordering luck.
_TOOL_CALL: ContextVar[dict | None] = ContextVar("pneuma_briefing_tool_call", default=None)


class _TimedRecords(list):
    """A tool's record sink that stamps `ms` on every record as it is appended.

    It has to happen HERE rather than around the tool because the tools append MID-CALL: the
    record is built from what the call found, and by the time the wrapper returns there is no
    longer a "before anyone sees it" to write into. `fetches` and `searches` are both this
    list, so every ask record carries the duration of the call that produced it."""

    def append(self, item: dict) -> None:  # noqa: D102
        call = _TOOL_CALL.get()
        if call is not None:
            item["ms"] = int(round(max((time.perf_counter() - call["started"]) * 1000.0, 0.0)))
            call["record"] = item
        super().append(item)


def _ask_watch(name: str, started: float) -> Callable[[], str | None]:
    """The `timed_tools` watch, the other half of `_TimedRecords`.

    Entering publishes the call's start on `_TOOL_CALL`, which is where `append` reads the
    `ms` it stamps. Leaving reports the error the tool SWALLOWED into its record —
    `fetch_verbatim` answers a bad source id or locator with a stated failure rather than
    raising, so without this the stage would read as a fast success."""
    del name  # the stage's name is `timed_tools`' business, not the record's
    call: dict = {"started": started, "record": None}
    token = _TOOL_CALL.set(call)

    def finish() -> str | None:
        _TOOL_CALL.reset(token)
        record = call["record"]
        return str(record["error"]) if record and record.get("error") else None

    return finish


def _fetch_verbatim_tool(
    user_id: UserId, content: ContentStore, sink: list[dict], aliaser=None
) -> StructuredTool:
    async def fetch_verbatim(source_id: str, locator: dict) -> str:
        """L0 verbatim fetch; see `recall.briefing.tool.fetch_verbatim_doc`."""
        # The model may pass the query-local handle it saw (sNN) — resolve it to the real id.
        real_id = aliaser.to_real(source_id) if aliaser else source_id
        try:
            text = await content.fetch(user_id, SourceId(real_id), locator)
            sink.append({"source_id": source_id, "locator": locator, "chars": len(text)})
            return text
        except (KeyError, ValueError) as exc:
            sink.append({"source_id": source_id, "locator": locator, "error": str(exc)})
            return prompt(
                "recall.briefing.tool.fetch_verbatim_failed", error=exc
            )

    fetch_verbatim.__doc__ = prompt("recall.briefing.tool.fetch_verbatim_doc")
    return StructuredTool.from_function(
        coroutine=fetch_verbatim,
        description=prompt("recall.briefing.tool.fetch_verbatim"),
    )


_SEARCH_MAX_PASSAGES = 6
_SEARCH_MAX_CLAIMS = 8


def _search_knowledge_tool(
    user_id: UserId,
    *,
    source_ids: tuple[str, ...],
    claim_lexical=None,
    claim_vectors=None,
    embeddings=None,
    lexical=None,
    vectors=None,
    content: ContentStore | None = None,
    sink: list[dict],
    aliaser=None,
) -> StructuredTool:
    """Agentic in-scope retrieval: retrieve_claims + rag_recall → expand_and_merge, scoped
    to the briefing's anchored sources (whole KB when none). Fixes the static-pack blind
    spot: a mid-document item absent from the pre-packed sample is reachable on demand."""
    allowed = set(source_ids)

    async def search_knowledge(query: str) -> str:
        """In-scope retrieval; see `recall.briefing.tool.search_knowledge_doc`."""
        claims = []
        if claim_lexical is not None and claim_vectors is not None and embeddings is not None:
            claims = await retrieve_claims(
                user_id,
                query,
                claim_lexical=claim_lexical,
                claim_vectors=claim_vectors,
                embeddings=embeddings,
                limit=_SEARCH_MAX_CLAIMS,
            )
        passages = []
        if lexical is not None and vectors is not None and embeddings is not None:
            hits = await rag_recall(
                user_id,
                query,
                lexical=lexical,
                vectors=vectors,
                embeddings=embeddings,
                limit=_SEARCH_MAX_PASSAGES * 2,
            )
            passages = await expand_and_merge(
                hits, content=content, user_id=user_id
            )

        if allowed:  # scope to the briefing's anchored sources
            passages = [p for p in passages if str(p.source_id) in allowed]
            claims = [
                c
                for c in claims
                if any(str(cit.source_id) in allowed for cit in c.citations)
            ]
        passages = passages[:_SEARCH_MAX_PASSAGES]
        claims = claims[:_SEARCH_MAX_CLAIMS]
        sink.append(
            {"query": query, "claims": len(claims), "passages": len(passages)}
        )

        parts: list[str] = []
        if claims:
            parts.append(
                prompt("recall.briefing.tool.claims_header")
                + "\n"
                + render_claims(claims)
            )
        if passages:
            parts.append(
                render_passages(
                    passages, header=prompt("recall.briefing.tool.passages_header")
                )
            )
        result = (
            "\n\n".join(parts)
            if parts
            else prompt("recall.briefing.tool.search_empty")
        )
        # keep source handles consistent with the pack (same session aliaser).
        return aliaser.alias(result) if aliaser else result

    search_knowledge.__doc__ = prompt("recall.briefing.tool.search_knowledge_doc")
    return StructuredTool.from_function(
        coroutine=search_knowledge,
        description=prompt("recall.briefing.tool.search_knowledge"),
    )


async def briefing_ask(
    briefing: Briefing,
    question: str,
    *,
    as_of: datetime,
    model: BaseChatModel,
    content: ContentStore,
    claim_lexical=None,
    claim_vectors=None,
    embeddings=None,
    lexical=None,
    vectors=None,
    profile: str | None = None,
    citation_alias: bool = False,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    # Watch the ask AS IT RUNS: `on_event` fires when each model turn and each tool call
    # begins and ends (`AgentTimings`), `on_token` as the answer text is generated. Both
    # None = the historical call, down to the langgraph stream mode.
    on_event: StageEventSink | None = None,
    on_token: TokenSink | None = None,
) -> AskAnswer:
    """Ask over a briefing: fixed-prefix messages + a bounded tool loop.

    Two tools: `search_knowledge(query)` runs in-scope retrieval (claim notes + context-
    expanded raw excerpts, filtered to the briefing's anchored sources) so the model can locate
    an item the static pack didn't inline; `fetch_verbatim(source_id, locator)` pulls exact
    L0 text. The loop is the shared `run_agent_loop` (create_agent, budget-bounded).

    Consumption is fast-lane (the owner reads the answer immediately): with
    `citation_alias`, one `SessionAliaser` gives every source a stable query-local `sNN`
    handle across the pack + tool results of THIS ask (consistent within the ask,
    query-local across asks), so the model copies short handles instead of raw ids. The
    pack itself keeps real source ids (built for fast-like consumption); aliasing it per
    ask trades its byte-stable prompt-cache for copyable citations (the switch's point).

    `AskAnswer.stages` is the loop's own interleaving — one entry per model turn and per tool
    call, in the order they happened, `total` around the loop. The pack is NOT in that total:
    it was built once, possibly days ago, and charging this ask for it would misname where the
    seconds went."""
    # Both sinks stamp their own `ms` (see `_TimedRecords`), so a record and the stage that
    # measured the same call agree by construction instead of by two clocks that might not.
    fetches: list[dict] = _TimedRecords()
    searches: list[dict] = _TimedRecords()
    timings = AgentTimings(on_event=on_event)
    aliaser = SessionAliaser() if citation_alias else None
    fetch_tool = _fetch_verbatim_tool(briefing.user_id, content, fetches, aliaser=aliaser)
    search_tool = _search_knowledge_tool(
        briefing.user_id,
        source_ids=briefing.source_ids,
        claim_lexical=claim_lexical,
        claim_vectors=claim_vectors,
        embeddings=embeddings,
        lexical=lexical,
        vectors=vectors,
        content=content,
        sink=searches,
        aliaser=aliaser,
    )
    human = assemble_messages(briefing, question, as_of=as_of, profile=profile)[1].content
    system_prefix = briefing.system_prefix
    if aliaser is not None:
        human = aliaser.alias(str(human))
        # Alias ONLY the knowledge pack, never the fixed contract. The contract's
        # `[cite: <source_id> ¶a-b]` / `[cite: …]` are teaching syntax, not real sources
        # (I5: the contract carries no source refs). Aliasing them would rewrite the shown
        # examples into `[cite: s01 …]` AND offset every real source's handle by two.
        contract = briefing_contract()
        if system_prefix.startswith(contract):
            pack = system_prefix[len(contract) :]
            system_prefix = contract + aliaser.alias(pack)
        else:
            system_prefix = aliaser.alias(system_prefix)
    # Measured around the coroutine, failures included — a fetch that answered a bad id with
    # a stated failure is a `degraded` stage naming that reason, not a suspiciously fast one.
    tools = timed_tools([search_tool, fetch_tool], timings, watch=_ask_watch)
    answer, usage, _transcript = await run_agent_loop(
        model,
        tools,
        system_prompt=system_prefix,
        human=str(human),
        tool_budget=_ASK_TOOL_BUDGET,
        run_name="briefing.ask",
        callbacks=callbacks,
        trace_metadata=trace_metadata,
        timings=timings,
        on_token=on_token,
    )

    handle_map = aliaser.handle_map if aliaser is not None else {}
    citations = tuple(
        Citation(
            # the answer's cite marker may be a query-local handle → map back to the real id.
            source_id=SourceId(handle_map.get(sid, sid)),
            block_start=start,
            block_end=end,
        )
        # tolerant parse: expands merged brackets a free-text answer may emit.
        for sid, start, end in iter_answer_citations(answer)
    )
    return AskAnswer(
        answer=answer,
        citations=citations,
        verbatim_fetches=tuple(fetches),
        token_usage=usage,
        citation_handles=handle_map,
        stages=timings.stages(),
    )
