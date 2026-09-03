"""deep mode — bounded agentic search over the four-level access model (architecture.md
§3 tool face + §7; milestone M4).

deep = fast's seed retrieval + a bounded agentic loop (langchain `create_agent`, via
`recall.agentic.run_agent_loop`). The model starts warm on the SAME dual-face evidence
fast answers over (byte-identical Human assembly via `recall_human`) — including the
knowledge base glance, so the map of the library is the first thing in context — then works
the tool face on demand:

- `search_claims(query)`   — L3: re-search the compiled claim face from a new angle
- `search_content(query)`  — L1/L2: re-search raw body windows (+ context assembly)
- `fetch_verbatim(source_id, locator)` — L0: exact raw text for a cited span
- `list_documents()`       — L3: the document paths, when the glance was truncated
- `read_document(path)`    — L3: one document in full, anchors and links included

MAP PLUS LEGS. The last two are what make canonical's follow-the-thread job usable from the
answering side: a document read in full carries its markdown links, and following one is
just `read_document` on the target — so a question whose subject is never named by the
retrieved fragments can still be walked to from a neighbouring one. They are deliberately
the compile face's tools, same names and same shapes, because one addressing vocabulary
across the system is the point (I4) — the answerer navigates canonical the way the compiler
wrote it.

SNAPSHOT SCOPING COSTS THIS LANE ALMOST NOTHING. A snapshot is a frozen TENANT (see
service/kb_snapshots.py): the caller hands the tools that tenant's `user_id` and the document
set read at its pinned canonical ref, and all five tools are then scoped by the per-user
isolation they already enforced. Only two things are added here: the prompt states which
snapshot is open (`SnapshotScope`, recall/scope.py), and a `fetch_verbatim` miss under a
snapshot is reported as "not part of this snapshot" rather than as a generic fetch failure —
in a frozen tenant those are the same event, and the honest wording is the specific one.

Verification is an agentic act — fetch the cited span and read it — not a fixed batch
protocol. What stays mechanical (§0 discipline 1): the tool budget (recursion_limit +
forced finalize, see `agentic.py`), the `trail` record per tool call, and the
byte-stable `deep_contract()` (I5) — input, as_of, and all evidence ride the
HumanMessage / ToolMessages.

WHAT EACH STEP COST is part of the answer, not of a log. Every tool call is measured around
its coroutine and the duration is stamped on the trail record BEFORE it is appended — so the
record streamed live to a waiting UI already carries its `ms` — while the model turns and the
forced finalize are measured by the loop itself (`agentic.AgentTimings`). `DeepAnswer.stages`
is the two interleaved in the order they happened, closed by `total`. `total` wraps the
AGENTIC LOOP; the seed retrieval above it is not a loop stage, so it is not inside that total.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool

from ..canonical_glance import render_canonical_glance
from ..compile.documents import render_document
from ..components import declared_tool_evidence, registered_components
from ..domain.archive import ArchiveView, is_archived_path, live_documents
from ..domain.canonical import CanonicalDocument
from ..domain.consultation import EvidenceRef
from ..domain.ids import UserId, SourceId
from ..ports.claim_index import ClaimLexicalIndex, ClaimVectorIndex
from ..ports.content_store import ContentStore
from ..ports.lexical_index import LexicalIndex
from ..ports.media_store import MediaStore
from ..ports.vector_index import VectorIndex
from ..prompts import prompt
from .agentic import AgentTimings, TokenSink, run_agent_loop, timed_tools
from .archive_filter import archive_view, scope_claims, scope_windows
from .scope import SnapshotScope, out_of_scope_source, scope_declaration
from .spine import (
    CITE_PRECISE,
    CLOSE_ANSWER_HONESTLY,
    DEFAULT_ANSWER_STYLE,
    spine,
    style_clause,
)
from .assembly import Passage
from .fast import (
    DEFAULT_CLAIM_CAP,
    DEFAULT_IMAGE_CAP,
    DEFAULT_WINDOW_CAP,
    RetrievedClaim,
    _render_window_section,
    assemble_windows,
    collect_window_images,
    evidence_manifest,
    recall_human_content,
    render_claims,
    retrieve_claims,
    retrieve_windows,
)
from .rag import RecallHit
from .stage_timing import StageEventSink, StageTiming
from .verbatim import fetched_span

_DEEP_TOOL_BUDGET = 6  # tool rounds before the forced tool-less finalize
_SEARCH_CLAIM_CAP = 8
_SEARCH_WINDOW_CAP = 4
_TRAIL_PREVIEW_CHARS = 1500  # per-step result kept for the UI trail (full text still goes to the model)


#: The tool call currently running IN THIS TASK: `{"started": perf_counter, "step": record}`.
#: A ContextVar rather than an attribute because langgraph's tool node runs a turn's tool
#: calls CONCURRENTLY, each in its own task: a shared slot would let one call's start time
#: stamp another call's record. Each task gets its own copy of the context, so the pairing of
#: a start time to the record appended under it is mechanical, not a matter of ordering luck.
_TOOL_CALL: ContextVar[dict | None] = ContextVar("pneuma_deep_tool_call", default=None)


class _TimedTrail(list):
    """The agentic trail: a list that times and announces every step as it is appended.

    Two things happen on the way in, and both have to happen HERE rather than around the
    tool, because the tools append mid-call and the caller streams what they appended:

    1. **`ms`** — the wall-clock since the running tool call started (`_TOOL_CALL`), stamped
       on the record before anyone sees it, so the step streamed live already carries it.
    2. **`on_append`** — the caller's live-step callback, invoked with the finished record.
    """

    def __init__(self, on_append: "Callable[[dict], None] | None" = None) -> None:
        super().__init__()
        self._on_append = on_append

    def append(self, item: dict) -> None:  # noqa: D102
        call = _TOOL_CALL.get()
        if call is not None:
            item["ms"] = int(round(max((time.perf_counter() - call["started"]) * 1000.0, 0.0)))
            call["step"] = item
        super().append(item)
        if self._on_append is not None:
            self._on_append(item)


def _trail_watch(name: str, started: float) -> "Callable[[], str | None]":
    """The `timed_tools` watch, the other half of `_TimedTrail`.

    Entering publishes the call's start on `_TOOL_CALL`, which is where `append` reads the
    `ms` it stamps. Leaving reports the error the tool SWALLOWED into its record
    (`fetch_verbatim` answers a bad id with a stated failure rather than raising), so the
    stage still reads `degraded` with that reason instead of as a fast success.

    The trail itself is not a parameter on purpose: the pairing travels through the context
    of the tool's own task, which is the only place it can be correct when a turn's tool
    calls run concurrently."""
    del name  # the stage's name is `timed_tools`' business, not the trail's
    call: dict = {"started": started, "step": None}
    token = _TOOL_CALL.set(call)

    def finish() -> str | None:
        _TOOL_CALL.reset(token)
        step = call["step"]
        return str(step["error"]) if step and step.get("error") else None

    return finish


def _trail_preview(text: str) -> str:
    """Cap a tool's result text for the UI trail so the response payload stays bounded;
    the model still receives the full return value."""
    if len(text) <= _TRAIL_PREVIEW_CHARS:
        return text
    return text[:_TRAIL_PREVIEW_CHARS].rstrip() + "\n…(truncated)"


def deep_contract(answer_style: str = DEFAULT_ANSWER_STYLE) -> str:
    """The deep lane's System contract: head + shared spine + answer-style clause.

    I5: byte-stable per prompt overlay and per `answer_style`. No timestamp, no input, no
    evidence content — posture only."""
    return (
        prompt("recall.deep.contract_head")
        + spine(CITE_PRECISE, CLOSE_ANSWER_HONESTLY)
        + style_clause(answer_style)
    )


@dataclass(frozen=True)
class DeepAnswer:
    answer: str
    # Every claim surfaced to the model (seed + search_claims), deduped by
    # (document_path, anchor) — drill-downable provenance for the UI.
    used_claims: tuple[RetrievedClaim, ...]
    token_usage: dict[str, int]
    # Every body window surfaced (seed + search_content), deduped by block span.
    used_windows: tuple[RecallHit | Passage, ...] = ()
    # The agentic search trace: one record per tool call, in execution order.
    trail: tuple[dict, ...] = ()
    # The glance's size in the opening context, 0 when no canonical documents were supplied.
    glance_chars: int = 0
    # Documents the loop actually opened with read_document, in first-read order — the
    # follow-the-thread walk, drill-downable for the UI.
    read_documents: tuple[str, ...] = ()
    # Images aligned to the seed windows and actually supplied to the model. Original bytes
    # are query opt-in; caption mode never reads the media store.
    image_count: int = 0
    image_mode: str = "caption"
    # The agentic loop's per-step wall-clock, in the order the steps happened: `turn:N` for
    # each model turn, `tool:<name>` for each tool call (the same call the matching `trail`
    # record carries `ms` for), `finalize` when the budget forced a closing call, and `total`
    # last. `total` wraps the LOOP — the seed retrieval that precedes it is not a loop stage.
    stages: tuple[StageTiming, ...] = ()
    # Every address the loop put in front of the model, as `EvidenceRef`s: the seed context
    # plus everything its tools returned into the transcript — claims, windows, the spans a
    # verbatim fetch came back with, whatever a component's tool declared, the pages it
    # opened in full, and the provenance spans rendered with them. The durable consultation
    # record copies this instead of re-deriving what was shown from the fields above.
    evidence_manifest: tuple[EvidenceRef, ...] = ()


def _search_claims_tool(
    user_id: UserId,
    *,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    found: list[RetrievedClaim],
    trail: list[dict],
    view: ArchiveView | None = None,
    include_archived: bool = False,
    live_paths: frozenset[str] | None = None,
) -> StructuredTool:
    """`search_claims(query)` — the L3 face, re-searchable mid-loop.

    It carries the lane's archive scope for the same reason the seed does: the loop can
    re-retrieve at any point, and a filter that applied only to the seed would let the second
    round put back exactly what the first excluded. `live_paths` rides along for the same
    reason: a stale L3 row is stale in round three as much as in the seed."""

    async def search_claims(query: str) -> str:
        """Re-search the claim notes; see `recall.deep.tool.search_claims_doc`."""
        claims = await retrieve_claims(
            user_id,
            query,
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            limit=_SEARCH_CLAIM_CAP,
            include_archived=include_archived,
        )
        claims, hidden = scope_claims(
            claims,
            view or ArchiveView.empty(),
            include_archived=include_archived,
            live_paths=live_paths,
        )
        found.extend(claims)
        out = (
            render_claims(claims)
            if claims
            else prompt("recall.deep.tool.search_claims_empty")
        )
        trail.append(
            {"tool": "search_claims", "query": query, "hits": len(claims),
             **({"archive_hidden": hidden} if hidden else {}),
             "result": _trail_preview(out)}
        )
        return out

    search_claims.__doc__ = prompt("recall.deep.tool.search_claims_doc")
    return StructuredTool.from_function(
        coroutine=search_claims,
        description=prompt("recall.deep.tool.search_claims"),
    )


def _search_content_tool(
    user_id: UserId,
    *,
    lexical: LexicalIndex | None,
    vectors: VectorIndex | None,
    embeddings,  # langchain_core.embeddings.Embeddings
    content: ContentStore | None,
    found: list,
    trail: list[dict],
    view: ArchiveView | None = None,
    include_archived: bool = False,
) -> StructuredTool:
    """`search_content(query)` — the L1/L2 face, re-searchable mid-loop.

    Carries the lane's archive scope for the same reason `search_claims` does. The filter
    runs AFTER assembly, because `expand_and_merge` builds new passages out of the raw hits
    and a marker stamped on a hit would not survive into what the model reads."""

    async def search_content(query: str) -> str:
        """Search raw fragments; see `recall.deep.tool.search_content_doc`."""
        hits = await retrieve_windows(
            user_id,
            query,
            lexical=lexical,
            vectors=vectors,
            embeddings=embeddings,
            limit=_SEARCH_WINDOW_CAP,
            include_archived=include_archived,
        )
        windows = await assemble_windows(
            hits, content=content, user_id=user_id
        )
        windows, hidden = scope_windows(
            windows, view or ArchiveView.empty(), include_archived=include_archived
        )
        found.extend(windows)
        out = (
            _render_window_section(windows)
            if windows
            else prompt("recall.deep.tool.search_content_empty")
        )
        trail.append(
            {"tool": "search_content", "query": query, "hits": len(windows),
             **({"archive_hidden": hidden} if hidden else {}),
             "result": _trail_preview(out)}
        )
        return out

    search_content.__doc__ = prompt("recall.deep.tool.search_content_doc")
    return StructuredTool.from_function(
        coroutine=search_content,
        description=prompt("recall.deep.tool.search_content"),
    )


def _fetch_verbatim_tool(
    user_id: UserId,
    content: ContentStore,
    trail: list[dict],
    scope: SnapshotScope | None = None,
    handed: list[EvidenceRef] | None = None,
) -> StructuredTool:
    """`fetch_verbatim(source_id, locator)` — L0 text for one addressed span.

    `handed` is the manifest sink: a fetch that came back with text put that span in front
    of the model, so the record must be able to say so — without it, an answer built on a
    verbatim fetch was recorded as a miss and the citation it copied off the span was
    rejected for naming an address nothing had handed over.

    BOTH locators yield a span (`recall/verbatim.py:fetched_span`). A `section` locator
    names a section path rather than an interval, so the span is resolved through the
    source's own structure map at fetch time — not guessed, and not skipped, which is what
    used to leave a section fetch's citations with nothing to be admitted against. Deep does
    not alias source ids, so the id the model passed IS the real one.
    """

    async def fetch_verbatim(source_id: str, locator: dict) -> str:
        """Fetch source text verbatim; see `recall.deep.tool.fetch_verbatim_doc`."""
        try:
            text = await content.fetch(user_id, SourceId(source_id), locator)
        except (KeyError, ValueError) as exc:
            # Under a snapshot the `user_id` above IS the frozen tenant, so "no such source"
            # means precisely "this source is not part of the snapshot" — the model copied an
            # id from somewhere newer. Say that, rather than the generic fetch failure, which
            # would read as a transport problem and invite a retry.
            failed = (
                out_of_scope_source(scope, source_id)
                if scope is not None and isinstance(exc, KeyError)
                else prompt("recall.deep.tool.fetch_verbatim_failed", error=exc)
            )
            trail.append(
                {"tool": "fetch_verbatim", "source_id": source_id,
                 "locator": locator, "error": str(exc), "result": failed}
            )
            return failed
        out = text if text else prompt("recall.deep.tool.fetch_verbatim_empty")
        if handed is not None and text:
            span = await fetched_span(user_id, source_id, locator, content=content)
            if span is not None:
                handed.append(span)
        trail.append(
            {"tool": "fetch_verbatim", "source_id": source_id, "locator": locator,
             "chars": len(text), "result": _trail_preview(out)}
        )
        return out

    fetch_verbatim.__doc__ = prompt("recall.deep.tool.fetch_verbatim_doc")
    return StructuredTool.from_function(
        coroutine=fetch_verbatim,
        description=prompt("recall.deep.tool.fetch_verbatim"),
    )


def _list_documents_tool(
    documents: Sequence[CanonicalDocument],
    trail: list[dict],
    include_archived: bool = False,
) -> StructuredTool:
    """`list_documents()` — the compile face's tool, read-only.

    Same name and same return shape as `compile.runner`'s (sorted paths, one per line, a
    stated-empty fallback), so the model that wrote the base and the model that answers over
    it name the same thing the same way. The glance already shows the layout; this exists for
    when it was truncated at the budget or an exact path spelling is needed.

    The ARCHIVE is not listed unless the call asked for it, for the same reason the glance
    does not list it: this is the map of what may be read, and a path on it that the read
    tool then refuses would be a map of somewhere else."""
    if not include_archived:
        documents = live_documents(documents)

    async def list_documents() -> str:
        """List document paths; see `recall.deep.tool.list_documents_doc`."""
        paths = sorted(doc.path for doc in documents)
        out = "\n".join(paths) or prompt("recall.deep.tool.list_documents_empty")
        trail.append(
            {"tool": "list_documents", "documents": len(paths), "result": _trail_preview(out)}
        )
        return out

    list_documents.__doc__ = prompt("recall.deep.tool.list_documents_doc")
    return StructuredTool.from_function(
        coroutine=list_documents,
        description=prompt("recall.deep.tool.list_documents"),
    )


def _read_document_tool(
    documents: Sequence[CanonicalDocument],
    read: list[str],
    trail: list[dict],
    include_archived: bool = False,
) -> StructuredTool:
    """`read_document(path)` — one document in full, anchors and links intact.

    The rendering is `compile.documents.render_document`, the same serializer the compiler
    writes with, so the answerer reads the exact bytes canonical holds: claim anchors it can
    cite and markdown links it can follow with another `read_document`. A missing path is a
    stated absence, never an exception — a wrong guess must cost one tool round, not the run.

    An ARCHIVED path is a THIRD outcome and is said as such: the document is there, whole and
    cited, and it is out of this answer's scope because nobody asked for the archive. Saying
    "no document at that path" would be false — the page exists — and silence would read as
    an empty page. It is the shape a snapshot miss is answered in, for the same reason.
    """
    by_path = {doc.path: doc for doc in documents}

    async def read_document(path: str) -> str:
        """Read one document in full; see `recall.deep.tool.read_document_doc`."""
        wanted = str(path or "").strip()
        doc = by_path.get(wanted)
        if doc is not None and is_archived_path(doc.path) and not include_archived:
            out = prompt("recall.deep.tool.read_document_archived", path=doc.path)
            trail.append(
                {"tool": "read_document", "path": doc.path, "found": False,
                 "archived": True, "result": out}
            )
            return out
        if doc is None:
            out = prompt("recall.deep.tool.read_document_not_found", path=path)
            trail.append({"tool": "read_document", "path": path, "found": False, "result": out})
            return out
        out = render_document(doc.frontmatter, doc.body)
        if doc.path not in read:
            read.append(doc.path)
        trail.append(
            {"tool": "read_document", "path": doc.path, "found": True,
             "chars": len(out), "result": _trail_preview(out)}
        )
        return out

    read_document.__doc__ = prompt("recall.deep.tool.read_document_doc")
    return StructuredTool.from_function(
        coroutine=read_document,
        description=prompt("recall.deep.tool.read_document"),
    )


def _merge_claims(
    seed: list[RetrievedClaim], found: list[RetrievedClaim]
) -> tuple[RetrievedClaim, ...]:
    seen: set[tuple[str, str]] = set()
    merged: list[RetrievedClaim] = []
    for c in [*seed, *found]:
        key = (c.document_path, str(c.anchor))
        if key not in seen:
            seen.add(key)
            merged.append(c)
    return tuple(merged)


def _merge_windows(seed: list, found: list) -> tuple:
    seen: set[tuple[str, int, int]] = set()
    merged: list = []
    for w in [*seed, *found]:
        key = (str(w.source_id), w.block_start, w.block_end)
        if key not in seen:
            seen.add(key)
            merged.append(w)
    return tuple(merged)


def _component_recall_tools(component, user_id, documents):
    """A component's deep tools, handed the lane's pinned `documents` (an empty pinned
    canonical stays empty — the component never falls back to live storage). A component
    written before `documents` joined the signature is still called, without it."""
    face = getattr(component, "recall_tools", None)
    if face is None:
        return []
    try:
        return face(user_id, documents=documents)
    except TypeError:
        return face(user_id)


async def deep_recall(
    user_id: UserId,
    question: str,
    *,
    as_of: datetime,
    claim_lexical: ClaimLexicalIndex,
    claim_vectors: ClaimVectorIndex,
    embeddings,  # langchain_core.embeddings.Embeddings
    model: BaseChatModel,
    content: ContentStore,
    media: MediaStore | None = None,
    image_mode: Literal["caption", "native"] = "caption",
    image_cap: int = DEFAULT_IMAGE_CAP,
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    profile: str | None = None,
    # The canonical documents at the answering snapshot: the glance is rendered from them and
    # they are what list_documents / read_document walk. Omitted (None) → the glance is absent
    # and both tools state that the base holds no documents (the tool FACE is constant either
    # way, so a deployment cannot silently lose a capability by forgetting a keyword).
    # THE RULING ON THE TWO EMPTIES: None means "not handed a document set" and nothing is
    # pinned; an empty SEQUENCE means "handed a set, and it is empty" and pins to nothing, so
    # every index claim is dropped. `()` was the old default and read as "not handed", which
    # is why the default moved to None — a caller that means "this library has no live page"
    # now has a way to say it, and the service always says it (`v1._glance_inputs`).
    documents: Sequence[CanonicalDocument] | None = None,
    skill: object | None = None,
    packs: Sequence[object] = (),
    # The frozen snapshot this answer is pinned to, or None = today's base. The tools are
    # already scoped by the caller's choice of tenant + document set (see module docstring);
    # this adds the prompt's snapshot declaration and the wording of a fetch miss.
    scope: SnapshotScope | None = None,
    on_step: "Callable[[dict], None] | None" = None,
    # The other two live faces, beside `on_step`. `on_event` fires when each model turn and
    # each tool call BEGINS and when it ends, so a waiting reader sees the turn it is
    # currently inside rather than only the ones that finished; `on_token` fires with the
    # answer's text deltas. Both None = the historical run, down to the langgraph stream mode.
    on_event: StageEventSink | None = None,
    on_token: TokenSink | None = None,
    cap: int = DEFAULT_CLAIM_CAP,
    window_cap: int = DEFAULT_WINDOW_CAP,
    # The SHAPE of the answer ("concise" / "conversational" / "detailed") — see
    # `fast_recall`. Style only; truth discipline is style-independent.
    answer_style: str = DEFAULT_ANSWER_STYLE,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    # The ARCHIVE, off by default (docs/design/archive.md §4). Off: the seed faces and both
    # search tools exclude it, `list_documents` does not list it, and `read_document` of an
    # archived path answers with the stated out-of-scope absence. On: every face admits it
    # and labels it, and the glance rendered from `documents` shows it. The `documents` the
    # lane is handed are the caller's decision — the service passes live documents only when
    # this is off.
    include_archived: bool = False,
    # Whether this library has EVER archived a document — stated by the caller that listed
    # the full canonical tree (`domain/archive.any_archived`). It turns the assembly
    # filter's document pin on; with nothing archived the filter is inert and this lane runs
    # byte-for-byte as it did before the archive existed (`archive_filter._pin`).
    archive_active: bool = False,
) -> DeepAnswer:
    """Seed with the glance + fast's dual-face retrieval, then run the bounded agentic loop.

    The seed Human payload is byte-identical to fast's (`recall_human`) under the deep
    contract — glance first, then the two evidence faces, then as_of + input — and the loop is
    `run_agent_loop` (create_agent + budget + forced finalize). All model calls trace under
    run_name "recall.deep".

    Deep does NOT alias source ids to query-local `sNN` handles (unlike fast): its agentic
    loop re-retrieves across rounds, so one source would get different handles in different
    tool results within the same chained context (s01 here, s15 there) — inconsistent and
    hard to maintain across turns. Deep answers over the real ids and manages its own
    citations; the citation_alias hook is fast-lane only."""
    # Two independent retrieval faces (each embeds the query + hits Meili/Qdrant) → run
    # them concurrently on the event loop via asyncio.gather; wall-clock is the slower
    # face, not their sum. gather preserves argument order, so the two results bind the
    # same way the previous thread-pool fan-out bound them.
    # The archive, read ONCE for this whole run — the seed AND every tool call the loop
    # makes below share it, because a filter that applied only to the seed would let the
    # second retrieval round put back exactly what the first excluded (archive.md §3).
    view = await archive_view(user_id, content, documents_archived=archive_active)
    #: The pages this run is PINNED TO: every path in the document set the caller handed in
    #: (archived ones included when the archive was asked for). A claim the index returns for
    #: a path outside it is dropped — after a move the L3 rows carry the old live path until
    #: the projection sync lands, and reading that path as "live" is exactly the leak the
    #: assembly filter exists to close. None ONLY when no document set was handed in; an
    #: EMPTY set pins to nothing and drops every index claim (see the parameter above).
    live_paths: frozenset[str] | None = (
        frozenset(doc.path for doc in documents) if documents is not None else None
    )
    #: …and below this line the set is a sequence again: every reader here (the two document
    #: tools, the glance, the component faces) asks "what is in it", never "was it handed".
    documents = () if documents is None else documents
    seed_claims_raw, raw_windows = await asyncio.gather(
        retrieve_claims(
            user_id,
            question,
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            limit=cap,
            include_archived=include_archived,
        ),
        retrieve_windows(
            user_id,
            question,
            lexical=lexical,
            vectors=vectors,
            embeddings=embeddings,
            limit=window_cap,
            include_archived=include_archived,
        ),
    )
    seed_claims_raw, _ = scope_claims(
        seed_claims_raw, view, include_archived=include_archived, live_paths=live_paths
    )
    seed_claims = seed_claims_raw[:cap]
    seed_windows = await assemble_windows(
        raw_windows, content=content, user_id=user_id
    )
    seed_windows, _ = scope_windows(
        seed_windows, view, include_archived=include_archived
    )
    images = (
        await collect_window_images(
            user_id,
            seed_windows,
            content=content,
            media=media,
            image_mode=image_mode,
            cap=image_cap,
        )
        if image_mode == "native"
        else []
    )

    found_claims: list[RetrievedClaim] = []
    found_windows: list = []
    read_paths: list[str] = []
    # What the evidence-returning tools put in front of the model, as addresses. The seed
    # and the search tools reach the manifest through `used_claims` / `used_windows`; a
    # verbatim fetch has no such field to ride on, so it publishes here directly.
    fetched: list[EvidenceRef] = []
    # A trail that fires on_step as each tool records a step → the agentic search can be
    # streamed one step at a time (the tools stay unchanged; they just .append as before).
    timings = AgentTimings(on_event=on_event)
    trail: list[dict] = _TimedTrail(on_step)
    tools = [
        _search_claims_tool(
            user_id,
            claim_lexical=claim_lexical,
            claim_vectors=claim_vectors,
            embeddings=embeddings,
            found=found_claims,
            trail=trail,
            view=view,
            include_archived=include_archived,
            live_paths=live_paths,
        ),
        _search_content_tool(
            user_id,
            lexical=lexical,
            vectors=vectors,
            embeddings=embeddings,
            content=content,
            found=found_windows,
            trail=trail,
            view=view,
            include_archived=include_archived,
        ),
        _fetch_verbatim_tool(user_id, content, trail, scope, fetched),
        _list_documents_tool(documents, trail, include_archived),
        _read_document_tool(documents, read_paths, trail, include_archived),
    ]
    # Tools contributed by enabled index components (components/__init__.py), scoped to
    # this user; none registered → the tool list is exactly what it always was. Kept in
    # their own list because the manifest reads each one's declared evidence afterwards,
    # off the tool the component built rather than the timing wrapper around it.
    component_tools = [
        t
        for component in registered_components()
        # LIVE documents unless the call asked otherwise. A component's tool returns the
        # component's own prose, which the framework cannot filter afterwards — so what it is
        # handed has to already be in scope. The component still learns nothing of the
        # archive (I7): it is given a document set, as it always was.
        for t in _component_recall_tools(
            component,
            user_id,
            documents if include_archived else live_documents(documents),
        )
    ]
    tools = [*tools, *component_tools]
    # Measured around the coroutine, failures included — and around EVERY tool, a component's
    # included, so a contributed tool cannot be the unexplained gap in the breakdown even
    # though it leaves no trail record of its own.
    tools = timed_tools(tools, timings, watch=_trail_watch)

    glance = (
        render_canonical_glance(
            documents, skill, packs=packs, include_archived=include_archived
        )
        if documents
        else None
    )
    answer_trace_metadata = {
        **(trace_metadata or {}),
        "image_count": len(images),
        "image_mode": image_mode,
    }
    answer, usage, _transcript = await run_agent_loop(
        model,
        tools,
        system_prompt=deep_contract(answer_style),
        human=recall_human_content(
            question,
            seed_claims,
            as_of=as_of,
            windows=seed_windows,
            profile=profile,
            glance=glance,
            snapshot=scope_declaration(scope),
            images=images,
            image_mode=image_mode,
        ),
        tool_budget=_DEEP_TOOL_BUDGET,
        run_name="recall.deep",
        callbacks=callbacks,
        trace_metadata=answer_trace_metadata,
        timings=timings,
        on_token=on_token,
    )

    used_claims = _merge_claims(seed_claims, found_claims)
    used_windows = _merge_windows(seed_windows, found_windows)
    # What the tools actually returned into the transcript. `read_document` renders a whole
    # page with `render_document`, so a page it opened contributes its own address and every
    # `[cite: …]` marker its body carries — the same rule the fast lane applies to a page it
    # expanded, and the reason a citation copied out of one is admissible in the record.
    by_path = {doc.path: doc for doc in documents}
    manifest = evidence_manifest(
        claims=used_claims,
        windows=used_windows,
        full_documents=[by_path[path] for path in read_paths if path in by_path],
        tool_evidence=[
            *fetched,
            # A component's tool result is the component's own prose in the component's own
            # shape; the framework cannot read addresses out of it and does not try. What a
            # tool DECLARED is what it contributes — and a tool that declares nothing
            # contributes nothing, so a citation copied out of its result is not admissible.
            *(
                EvidenceRef(kind=kind, ref=ref, path=path)
                for tool in component_tools
                for kind, ref, path in declared_tool_evidence(tool)
            ),
        ],
    )

    return DeepAnswer(
        answer=answer,
        used_claims=used_claims,
        token_usage=usage,
        used_windows=used_windows,
        trail=tuple(trail),
        glance_chars=len(glance or ""),
        read_documents=tuple(read_paths),
        image_count=len(images),
        image_mode=image_mode,
        stages=timings.stages(),
        evidence_manifest=manifest,
    )
