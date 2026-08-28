"""Component retrieval paths for the fast lane — routed by one tool call, run concurrently,
merged as their own evidence face.

WHY A ROUTED PATH, NOT A BLIND ONE
----------------------------------
The built-in paths (lexical, raw-vector, episode-vector, claim) are homogeneous: ranked
lists over the same kinds of item, fused by RRF. A component path is different in two ways.
It answers a STRUCTURED query — `person(alias="贾宁")`, not the raw question — so something
has to derive that query from the question; and it returns exact lookups (an identity match,
an enumeration), not relevance estimates, so its results have no rank an RRF could fuse
without either drowning three exact hits under sixty lexical ones or over-weighting a tiny
list.

So the fast lane, when at least one path is offered, spends ONE routing call: the paths are
bound as tools, the recall model emits zero or more tool calls in a single turn (no loop),
and every chosen path runs concurrently — alongside the built-in retrieval, which never
waits for the routing. What the model chose and with which arguments is the audit trail.

MERGE
-----
Path results are a fourth evidence face next to claims / episode summaries / raw windows:
rendered under their own header with the path name and arguments. They never enter the RRF.
Every candidate is an ordinary `RetrievedClaim` or `RecallHit` — a claim anchor or a
`source_id + block span` (I4) — so citation aliasing, the structured answer's admission
check, and the wire echo all apply unchanged.

A path returns EVERYTHING it knows; this module decides what is shown. Ordering is
`component_rank.rank_candidates` (deterministic, question-aware, reranker-aware), the
path's declared `cap` is spent on that order rather than on document order, and the
character budget holds the whole face. Dedup runs in both directions and BOTH ways it
protects the ranked faces: they keep their claims and windows (they carry relevance order,
and the selector/reranker already judged them), while the component face shows only what
they do not already contain and says how many it hid. A ranked claim a lookup also returned
is labelled `via:<path>` — corroboration without a second copy. Every truncation is
described, not merely counted (`dropped_summary`), because a lookup that silently returns
its first N items reads as "that was everything".

NO PATH, NO COST
----------------
With no path offered there is no routing call, no extra section, and no telemetry beyond
`None`/empty defaults: the lane's messages are byte-identical to the lane without the seam.
Routing and each path are fail-soft with their own timeouts; a failure is a telemetry
marker, never a failed answer.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError

from ..components import registered_components
from ..prompts import prompt
from .component_rank import apply_cap, rank_candidates, truncate_window

if TYPE_CHECKING:  # pragma: no cover
    from ..domain.canonical import CanonicalDocument
    from ..ports.reranker import Reranker
    from .fast import RetrievedClaim
    from .rag import RecallHit
    from .scope import SnapshotScope

DEFAULT_ROUTE_TIMEOUT_SECONDS = 10.0
DEFAULT_PATH_TIMEOUT_SECONDS = 15.0
#: Character ceiling on the WHOLE component face, however many paths ran. A per-path cap
#: bounds item counts; this bounds the context the face may occupy, which item counts
#: cannot (one verbatim day is longer than forty claims).
DEFAULT_COMPONENT_BUDGET_CHARS = 6000
#: Below this a truncated window is not worth showing at all, so the item is dropped
#: instead of being cut to a stub.
MIN_WINDOW_CHARS = 240
#: Upper bound on tool calls honoured from one routing turn (a model that fans out wildly
#: is capped mechanically; the cap is stated in telemetry through what was dropped).
DEFAULT_ROUTE_CALL_CAP = 4


@dataclass(frozen=True)
class PathResult:
    """What one path run returns: EVERYTHING it knows, in the path's own order (the path
    decides what comes first — a current state before its history).

    A path does not truncate. It has no question to truncate against: `person(alias="…")`
    is an exact lookup over a page, and cutting that page at 24 items cuts it in document
    order, which is how the claim a question needs ends up just past the edge. The framework
    orders the results against the question and spends the path's declared `cap` on THAT
    order (`component_rank`), stating what it did not show."""

    claims: tuple["RetrievedClaim", ...] = ()
    windows: tuple["RecallHit", ...] = ()


@runtime_checkable
class FastPath(Protocol):
    """One routed retrieval path a component offers to the fast lane."""

    name: str  # the tool name the routing model sees; unique per enabled set
    description: str  # the tool description — the path's whole self-introduction
    #: The pydantic model of the path's STRUCTURED query. It is the routing tool's argument
    #: schema, and the same model validates what comes back — a malformed argument becomes
    #: an `invalid_args` telemetry row and never reaches the component.
    args_schema: type[BaseModel]
    # The path's DECLARED default budget: the most claims + windows it should put into the
    # context. The framework applies it after ordering, never the path itself.
    cap: int

    async def run(
        self,
        user_id: str,
        args: BaseModel,
        *,
        scope: "SnapshotScope | None" = None,
        documents: Sequence["CanonicalDocument"] | None = None,
        as_of: "datetime | None" = None,
    ) -> PathResult: ...


@dataclass(frozen=True)
class ComponentEvidence:
    """One chosen path's contribution, as it reaches the answer and the wire."""

    path: str
    args: dict
    claims: tuple["RetrievedClaim", ...] = ()
    windows: tuple["RecallHit", ...] = ()
    degraded: str | None = None  # None | "timeout" | "error" | "invalid_args"
    dropped: int = 0  # candidates the cap and the budget did not show
    #: The same omission, DESCRIBED: `(section-or-day, count)` in relevance order. A count
    #: alone tells the reader something is missing; this tells them what.
    dropped_summary: tuple[tuple[str, int], ...] = ()
    #: Candidates the ranked faces already show — hidden here rather than there, because the
    #: ranked faces carry relevance order and this face would only be a second copy.
    already_shown: int = 0
    #: Claims folded into a window of this same face (every citation span inside it).
    covered_by_windows: int = 0
    #: The path's declared cap, carried so the merge can spend it after ordering.
    cap: int = 0
    #: This path run's own wall-clock, in milliseconds. The chosen paths run concurrently
    #: with each other and with the built-in faces, so these do NOT sum to the gather's
    #: duration — each one answers "how long did THIS lookup take", which is the only way to
    #: see which lane was the slow one inside the concurrency. A timed-out or errored run
    #: still carries what it spent before giving up; a run rejected at argument validation
    #: never happened and carries 0.
    elapsed_ms: int = 0

    def key(self) -> str:
        return f"{self.path}({json.dumps(self.args, ensure_ascii=False, sort_keys=True)})"


def fast_paths_from_registry(user_id: str) -> list[FastPath]:
    """Every path the enabled components offer, in registration order."""
    # A component written against the four-face protocol simply offers no path; the seam
    # must never turn a missing optional face into a failed answer.
    return [
        p
        for component in registered_components()
        for p in (getattr(component, "fast_paths", None) or (lambda _u: []))(user_id)
    ]


# ------------------------------------------------------------------------------ routing


async def _never_called(**_kwargs: object) -> str:  # pragma: no cover — binding only
    return ""


def route_messages(question: str, as_of: "datetime", zone: str) -> list[BaseMessage]:
    """[byte-stable SystemMessage, HumanMessage(question + as_of + zone)] — the tools ride
    the binding.

    `as_of` and the subject's zone are the routing turn's whole answer to relative time. The
    index never parses "上季度" or "last Monday"; the ROUTING MODEL resolves such a phrase
    into ISO days here, because it is the one participant that already reads the question
    and now also knows what "now" is and whose calendar it is on. Both ride the Human turn:
    the System contract stays byte-stable (I5), which is exactly why a volatile timestamp
    may not go in it.
    """
    return [
        SystemMessage(content=prompt("recall.fast.route.system")),
        HumanMessage(
            content=prompt(
                "recall.fast.route.request",
                question=question,
                as_of=as_of.isoformat(),
                zone=zone,
            )
        ),
    ]


async def route_paths(
    model: BaseChatModel,
    question: str,
    paths: Sequence[FastPath],
    *,
    as_of: "datetime | None" = None,
    zone: str = "UTC",
    timeout: float | None = DEFAULT_ROUTE_TIMEOUT_SECONDS,
    call_cap: int = DEFAULT_ROUTE_CALL_CAP,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[list[tuple[FastPath, BaseModel]], dict[str, int], str | None, list[ComponentEvidence]]:
    """One tool-calling turn: which paths, with which arguments.

    Returns `(chosen, usage, degraded, rejected)`. `chosen` pairs a path with validated
    arguments; `rejected` holds calls the model made that could not be honoured (unknown
    tool, arguments failing the schema) as `ComponentEvidence` rows with `degraded` set, so
    the audit trail keeps what the model tried. Timeout / provider error → nothing chosen,
    `degraded` names why; choosing nothing is the normal outcome for a question no path
    serves and is not a degradation.
    """
    from .fast import extract_usage, invoke_config, zero_usage  # local: avoids a cycle

    if not paths:
        return [], zero_usage(), None, []
    by_name = {p.name: p for p in paths}
    tools = [
        StructuredTool.from_function(
            coroutine=_never_called,
            name=p.name,
            description=p.description,
            args_schema=p.args_schema,
        )
        for p in paths
    ]
    try:
        bound = model.bind_tools(tools)
        call = bound.ainvoke(
            route_messages(question, as_of or datetime.now(timezone.utc), zone),
            config=invoke_config("recall.fast.route", callbacks, trace_metadata),
        )
        response = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return [], zero_usage(), "timeout", []
    except Exception:  # noqa: BLE001 — routing is additive; the lane answers regardless
        return [], zero_usage(), "error", []

    usage = extract_usage(response) if isinstance(response, BaseMessage) else zero_usage()
    calls = list(getattr(response, "tool_calls", None) or [])
    chosen: list[tuple[FastPath, BaseModel]] = []
    rejected: list[ComponentEvidence] = []
    seen: set[str] = set()
    for tool_call in calls[:call_cap]:
        name = str(tool_call.get("name") or "")
        raw_args = tool_call.get("args") or {}
        path = by_name.get(name)
        if path is None:
            rejected.append(ComponentEvidence(path=name, args=dict(raw_args), degraded="invalid_args"))
            continue
        try:
            args = path.args_schema.model_validate(raw_args)
        except ValidationError:
            rejected.append(ComponentEvidence(path=name, args=dict(raw_args), degraded="invalid_args"))
            continue
        key = f"{name}:{json.dumps(args.model_dump(), ensure_ascii=False, sort_keys=True)}"
        if key in seen:
            continue
        seen.add(key)
        chosen.append((path, args))
    return chosen, usage, None, rejected


# ------------------------------------------------------------------------------ running


async def run_paths(
    user_id: str,
    chosen: Sequence[tuple[FastPath, BaseModel]],
    *,
    question: str = "",
    scope: "SnapshotScope | None" = None,
    documents: Sequence["CanonicalDocument"] | None = None,
    as_of: "datetime | None" = None,
    timeout: float | None = DEFAULT_PATH_TIMEOUT_SECONDS,
) -> list[ComponentEvidence]:
    """Run every chosen path concurrently and ORDER what each returns against the question.

    Each run is fail-soft. Nothing is truncated here: the full ordered result travels to the
    merge (`merge_component_evidence`), which is the only place that knows what the ranked
    faces already show and therefore the only place that can spend a cap without wasting it
    on a duplicate. `documents` is the lane's already-pinned canonical, so a path reads the
    same state the glance and the claim face describe."""

    async def one(path: FastPath, args: BaseModel) -> ComponentEvidence:
        shown = args.model_dump()
        cap = max(int(path.cap), 0)
        # The clock covers the lookup AND the ordering that makes it usable: both are what
        # this path costs the gather. A failure is timed too — "the timeout fired at 6s" is
        # the fact a reader needs, and reporting 0 there would hide the slowest lane.
        started = time.perf_counter()

        def spent() -> int:
            return int(round((time.perf_counter() - started) * 1000.0))

        try:
            call = path.run(user_id, args, scope=scope, documents=documents, as_of=as_of)
            result = await (asyncio.wait_for(call, timeout) if timeout else call)
        except asyncio.TimeoutError:
            return ComponentEvidence(
                path=path.name, args=shown, degraded="timeout", cap=cap, elapsed_ms=spent()
            )
        except Exception:  # noqa: BLE001 — one path failing never fails the answer
            return ComponentEvidence(
                path=path.name, args=shown, degraded="error", cap=cap, elapsed_ms=spent()
            )
        ranked = rank_candidates(
            question, tuple(result.claims), tuple(result.windows), as_of=as_of
        )
        return ComponentEvidence(
            path=path.name,
            args=shown,
            claims=ranked.claims,
            windows=ranked.windows,
            cap=cap,
            elapsed_ms=spent(),
        )

    if not chosen:
        return []
    return list(await asyncio.gather(*(one(p, a) for p, a in chosen)))


async def rerank_component_evidence(
    reranker: "Reranker",
    question: str,
    evidence: Sequence[ComponentEvidence],
    *,
    as_of: "datetime | None" = None,
    timeout: float | None = None,
) -> tuple[list[ComponentEvidence], str | None]:
    """Re-order each path's candidates with the wired reranker instead of lexical overlap.

    The label and time terms stay exactly as they are (`component_rank`), so this sharpens
    the relevance term and changes nothing else. One call per path — a path is one lookup
    and its candidates are one document set. Fail-soft in the lane's usual sense: a timeout
    or provider error leaves the lexical order untouched and returns a marker."""
    degraded: str | None = None
    out: list[ComponentEvidence] = []
    for row in evidence:
        texts = [c.text for c in row.claims] + [w.text for w in row.windows]
        if row.degraded or not texts:
            out.append(row)
            continue
        try:
            call = reranker.rerank(question, texts, top_n=len(texts))
            results = await (asyncio.wait_for(call, timeout) if timeout else call)
        except asyncio.TimeoutError:
            degraded = degraded or "timeout"
            out.append(row)
            continue
        except Exception:  # noqa: BLE001 — an additive pass never fails the answer
            degraded = degraded or "error"
            out.append(row)
            continue
        scores = [0.0] * len(texts)
        for result in results:
            index = int(result.index)
            if 0 <= index < len(texts):
                scores[index] = float(result.score)
        ranked = rank_candidates(
            question, row.claims, row.windows, as_of=as_of, reranker_scores=scores
        )
        out.append(replace(row, claims=ranked.claims, windows=ranked.windows))
    return out, degraded


# ------------------------------------------------------------------------------ merging


def _claim_key(claim: "RetrievedClaim") -> tuple:
    return (claim.document_path, str(claim.anchor))


def _span_key(window: object) -> tuple:
    return (
        str(getattr(window, "source_id", "")),
        getattr(window, "block_start", None),
        getattr(window, "block_end", None),
    )


def label_ranked_claims(
    claims: Sequence["RetrievedClaim"], evidence: Sequence[ComponentEvidence]
) -> list["RetrievedClaim"]:
    """Mark ranked claims a lookup ALSO returned with `via:<path>`.

    Corroboration is a fact about the claim, and it costs one label rather than a second
    copy of the text: the model sees that an exact lookup found the same claim the ranked
    face ranked, and the API/web echo the same mark."""
    by_key: dict[tuple, list[str]] = {}
    for row in evidence:
        for claim in row.claims:
            paths = by_key.setdefault(_claim_key(claim), [])
            if row.path not in paths:
                paths.append(row.path)
    out: list["RetrievedClaim"] = []
    for claim in claims:
        paths = by_key.get(_claim_key(claim))
        if not paths:
            out.append(claim)
            continue
        label = "via:" + ",".join(paths)
        out.append(
            claim if label in claim.labels else replace(claim, labels=(*claim.labels, label))
        )
    return out


def hide_already_shown(
    evidence: Sequence[ComponentEvidence],
    claims: Sequence["RetrievedClaim"],
    windows: Sequence[object],
) -> list[ComponentEvidence]:
    """Drop from the COMPONENT face what the ranked faces already show, and say how many.

    The direction matters and it used to run the other way. The ranked faces are ordered by
    relevance and have already been through the selector or the reranker; removing an item
    from them to make room for the same item under a component header costs that ordering
    and gains nothing. The component face is the additive one, so it is the one that yields
    — and it states the overlap (`already_shown`) so the model knows the lookup corroborated
    what it is reading above rather than having failed to find it."""
    claim_keys = {_claim_key(c) for c in claims}
    span_keys = {_span_key(w) for w in windows}
    out: list[ComponentEvidence] = []
    for row in evidence:
        kept_claims = tuple(c for c in row.claims if _claim_key(c) not in claim_keys)
        kept_windows = tuple(w for w in row.windows if _span_key(w) not in span_keys)
        hidden = (len(row.claims) - len(kept_claims)) + (len(row.windows) - len(kept_windows))
        out.append(
            replace(
                row,
                claims=kept_claims,
                windows=kept_windows,
                already_shown=row.already_shown + hidden,
            )
        )
    return out


def fold_claims_into_windows(evidence: Sequence[ComponentEvidence]) -> list[ComponentEvidence]:
    """Inside one face: a claim every citation of which lies inside a window of the SAME
    face is folded into that window, and text-duplicate claims collapse.

    The window carries the verbatim material the claim was compiled from, so showing both is
    the same evidence twice at two levels of abstraction. The fold is counted in the block
    header (`covered_by_windows`), never silent."""
    from .fast import _dedup_by_containment  # local: avoids a cycle

    out: list[ComponentEvidence] = []
    for row in evidence:
        spans = [(str(w.source_id), w.block_start, w.block_end) for w in row.windows]

        def covered(claim: "RetrievedClaim", spans=spans) -> bool:
            if not claim.citations or not spans:
                return False
            return all(
                any(
                    str(cit.source_id) == sid
                    and start <= cit.block_start
                    and cit.block_end <= end
                    for sid, start, end in spans
                )
                for cit in claim.citations
            )

        kept = [c for c in row.claims if not covered(c)]
        folded = len(row.claims) - len(kept)
        deduped = _dedup_by_containment(kept)
        surviving = {id(c) for c in deduped}
        duplicates = [c for c in kept if id(c) not in surviving]
        out.append(
            replace(
                row,
                claims=tuple(deduped),
                covered_by_windows=row.covered_by_windows + folded,
                dropped=row.dropped + len(duplicates),
                dropped_summary=_merge_summaries(
                    row.dropped_summary, _summarize_claims(duplicates)
                ),
            )
        )
    return out


def _summarize_claims(claims: Sequence["RetrievedClaim"]) -> tuple[tuple[str, int], ...]:
    from .component_rank import claim_group

    counts: dict[str, int] = {}
    for claim in claims:
        counts[claim_group(claim)] = counts.get(claim_group(claim), 0) + 1
    return tuple(counts.items())


def dedup_across_paths(evidence: Sequence[ComponentEvidence]) -> list[ComponentEvidence]:
    """One address returned by two paths is shown once, under the first path, labelled with
    every path that found it (`via:person,timespan`)."""
    by_claim: dict[tuple, list[str]] = {}
    by_span: dict[tuple, list[str]] = {}
    for row in evidence:
        for claim in row.claims:
            by_claim.setdefault(_claim_key(claim), []).append(row.path)
        for window in row.windows:
            by_span.setdefault(_span_key(window), []).append(row.path)
    seen_claims: set[tuple] = set()
    seen_spans: set[tuple] = set()
    out: list[ComponentEvidence] = []
    for row in evidence:
        kept_claims: list["RetrievedClaim"] = []
        for claim in row.claims:
            key = _claim_key(claim)
            if key in seen_claims:
                continue
            seen_claims.add(key)
            paths = by_claim.get(key, [])
            if len(paths) > 1:
                label = "via:" + ",".join(dict.fromkeys(paths))
                claim = replace(claim, labels=(*claim.labels, label))
            kept_claims.append(claim)
        kept_windows = []
        for window in row.windows:
            key = _span_key(window)
            if key in seen_spans:
                continue
            seen_spans.add(key)
            kept_windows.append(window)
        out.append(replace(row, claims=tuple(kept_claims), windows=tuple(kept_windows)))
    return out


def cap_component_evidence(evidence: Sequence[ComponentEvidence]) -> list[ComponentEvidence]:
    """Spend each path's declared cap on the ORDERED candidates (see `component_rank`)."""
    out: list[ComponentEvidence] = []
    for row in evidence:
        if row.degraded:
            out.append(row)
            continue
        capped = apply_cap(_as_ranked(row), row.cap)
        out.append(
            replace(
                row,
                claims=capped.claims,
                windows=capped.windows,
                dropped=row.dropped + capped.dropped,
                dropped_summary=_merge_summaries(row.dropped_summary, capped.dropped_summary),
            )
        )
    return out


def _as_ranked(row: ComponentEvidence):
    from .component_rank import RankedCandidates

    return RankedCandidates(claims=row.claims, windows=row.windows)


def _merge_summaries(
    left: Sequence[tuple[str, int]], right: Sequence[tuple[str, int]]
) -> tuple[tuple[str, int], ...]:
    merged: dict[str, int] = {}
    for group, count in (*left, *right):
        merged[group] = merged.get(group, 0) + count
    return tuple(merged.items())


def budget_component_evidence(
    evidence: Sequence[ComponentEvidence], *, budget_chars: int = DEFAULT_COMPONENT_BUDGET_CHARS
) -> list[ComponentEvidence]:
    """Hold the WHOLE component face under `budget_chars`, honestly.

    Item caps bound counts, not size: one verbatim day is longer than forty claims, so the
    face needs a budget of its own. Each non-degraded path gets an equal share; inside a
    share an over-long window is cut at a block boundary and SAYS which blocks it did not
    show, and if the share is still exceeded the lowest-ranked items fall off into
    `dropped_summary`. Ordering already ran, so what falls off is what mattered least."""
    rows = list(evidence)
    if budget_chars <= 0 or len(render_component_evidence(rows)) <= budget_chars:
        return rows
    live = {id(row) for row in rows if not row.degraded and (row.claims or row.windows)}
    if not live:
        return rows
    # A degraded or empty path still renders a header line, and the blocks are joined by a
    # blank line. Neither is negotiable, so both come off the budget BEFORE it is shared —
    # otherwise a face with three paths quietly exceeds the ceiling it declares.
    fixed = sum(_row_chars(row) for row in rows if id(row) not in live)
    fixed += 2 * max(len(rows) - 1, 0)
    share = max((budget_chars - fixed) // len(live), 1)
    return [_fit_row(row, share) if id(row) in live else row for row in rows]


def _row_chars(row: ComponentEvidence) -> int:
    return len(render_component_evidence([row]))


def _fit_row(row: ComponentEvidence, share: int) -> ComponentEvidence:
    """One path's block, cut to `share` characters: long windows first, then the tail."""
    windows = list(row.windows)
    claims = list(row.claims)
    # The header and its notes are part of the block and are not negotiable, so the items
    # get what is left of the share, not the share itself.
    overhead = _row_chars(replace(row, claims=(), windows=()))
    usable = max(share - overhead, 1)
    if windows:
        window_share = usable if not claims else max(usable * 2 // 3, 1)
        per_window = max(window_share // len(windows), 0)
        if per_window >= MIN_WINDOW_CHARS:
            cut: list["RecallHit"] = []
            for window in windows:
                trimmed, omitted = truncate_window(window, per_window)
                if omitted is not None:
                    note = prompt(
                        "recall.fast.component.window_truncated",
                        start=omitted[0],
                        end=omitted[1],
                    )
                    trimmed = replace(trimmed, text=f"{trimmed.text}\n{note}")
                cut.append(trimmed)
            windows = cut
    row = replace(row, claims=tuple(claims), windows=tuple(windows))
    dropped_claims: list["RetrievedClaim"] = []
    dropped_windows: list["RecallHit"] = []
    while _row_chars(row) > share and (row.claims or row.windows):
        claims, windows = list(row.claims), list(row.windows)
        # Lowest-ranked first, whichever kind it is; a lone window is kept while any claim
        # remains, so the §B.1 window floor survives the budget too.
        if windows and (not claims or (len(windows) > 1 and windows[-1].score <= claims[-1].score)):
            dropped_windows.append(windows.pop())
        elif claims:
            dropped_claims.append(claims.pop())
        else:
            dropped_windows.append(windows.pop())
        row = replace(row, claims=tuple(claims), windows=tuple(windows))
    if not dropped_claims and not dropped_windows:
        return row
    from .component_rank import claim_group, window_group

    summary: dict[str, int] = {}
    for claim in dropped_claims:
        summary[claim_group(claim)] = summary.get(claim_group(claim), 0) + 1
    for window in dropped_windows:
        summary[window_group(window)] = summary.get(window_group(window), 0) + 1
    return replace(
        row,
        dropped=row.dropped + len(dropped_claims) + len(dropped_windows),
        dropped_summary=_merge_summaries(row.dropped_summary, tuple(summary.items())),
    )


def merge_component_evidence(
    evidence: Sequence[ComponentEvidence],
    *,
    claims: Sequence["RetrievedClaim"],
    windows: Sequence[object],
    budget_chars: int = DEFAULT_COMPONENT_BUDGET_CHARS,
) -> tuple[list[ComponentEvidence], list["RetrievedClaim"]]:
    """Everything between "the paths returned everything" and "this is the face", in the one
    order that keeps each step honest:

    1. label the ranked claims a lookup corroborated (`via:`), over the FULL lookup result —
       before anything is hidden, so corroboration does not depend on what survived;
    2. hide from this face what the ranked faces already show (counted);
    3. fold claims whose evidence is inside a window of this same face (counted), then
       collapse text duplicates;
    4. keep one copy of an address two paths both returned (labelled with both);
    5. spend each path's declared cap on the ordered remainder, under the window/section
       floors;
    6. hold the whole face under the character budget.

    Returns the merged evidence and the ranked claims with their `via:` labels.
    """
    labelled = label_ranked_claims(claims, evidence)
    rows = hide_already_shown(evidence, labelled, windows)
    rows = fold_claims_into_windows(rows)
    rows = dedup_across_paths(rows)
    rows = cap_component_evidence(rows)
    rows = budget_component_evidence(rows, budget_chars=budget_chars)
    return rows, labelled


def render_component_evidence(evidence: Sequence[ComponentEvidence]) -> str:
    """The component face: one block per chosen path, name and arguments stated, claims and
    spans in the path's own order. A degraded path is stated as such, not omitted — the
    model should know a lookup was attempted and did not deliver."""
    from .fast import render_claims, render_windows  # local: avoids a cycle

    blocks: list[str] = []
    for e in evidence:
        args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in e.args.items())
        head = prompt("recall.fast.component.path_header", path=e.path, args=args)
        if e.degraded:
            blocks.append(head + "\n" + prompt("recall.fast.component.path_degraded", reason=e.degraded))
            continue
        parts = [head]
        if e.already_shown:
            parts.append(
                prompt("recall.fast.component.path_already_shown", count=e.already_shown)
            )
        if e.covered_by_windows:
            parts.append(
                prompt("recall.fast.component.path_covered", count=e.covered_by_windows)
            )
        if e.claims:
            parts.append(render_claims(list(e.claims)))
        if e.windows:
            parts.append(render_windows(list(e.windows)))
        if not e.claims and not e.windows and not e.already_shown and not e.covered_by_windows:
            parts.append(prompt("recall.fast.component.path_empty"))
        if e.dropped_summary:
            parts.append(
                prompt(
                    "recall.fast.component.path_dropped_detail",
                    detail=" · ".join(f"{group} ×{count}" for group, count in e.dropped_summary),
                )
            )
        elif e.dropped:
            parts.append(prompt("recall.fast.component.path_dropped", count=e.dropped))
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def evidence_counts(evidence: Sequence[ComponentEvidence]) -> int:
    return sum(len(e.claims) + len(e.windows) for e in evidence)


__all__ = [
    "ComponentEvidence",
    "DEFAULT_COMPONENT_BUDGET_CHARS",
    "DEFAULT_PATH_TIMEOUT_SECONDS",
    "DEFAULT_ROUTE_CALL_CAP",
    "DEFAULT_ROUTE_TIMEOUT_SECONDS",
    "FastPath",
    "PathResult",
    "budget_component_evidence",
    "cap_component_evidence",
    "dedup_across_paths",
    "evidence_counts",
    "fast_paths_from_registry",
    "fold_claims_into_windows",
    "hide_already_shown",
    "label_ranked_claims",
    "merge_component_evidence",
    "render_component_evidence",
    "rerank_component_evidence",
    "route_messages",
    "route_paths",
    "run_paths",
]
