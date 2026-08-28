"""Per-stage wall-clock for the lanes with a FIXED vocabulary — part of the result, not a log.

The fast lane is no longer one call: a planning turn, a concurrent retrieval gather (claim
face, window face, routed component paths, the glance pass), a rerank pass, a selection turn,
evidence assembly and the answer call each cost their own time. "It took 9 seconds" is not an
answer to *which part*, so every stage carries its own measured duration to the wire and to
every surface that shows the lane's parameters.

Two mechanical properties, not conventions:

1. **The vocabulary is fixed and the emitted order is derived from it.** `STAGE_ORDER` is the
   single place the order lives; `StageRecorder.emit` walks it. A stage that did not run is
   still emitted — `status="skipped"`, `ms=0` — so a UI can lay out a stable strip and a
   reader can tell "did not happen" from "was free". Nothing is ever omitted.
2. **Concurrency is reported as concurrency.** `retrieve` is the gather's own wall-clock; its
   children (`retrieve.claims`, `retrieve.windows`, `retrieve.glance`, and one
   `retrieve.path:<name>` per routed component path) each report their own duration. The
   children therefore SUM TO MORE than their parent, and `route` overlaps `retrieve` because
   the routing turn runs inside that same gather. The only arithmetic invariant is
   `total >= every other stage` — `total` wraps the whole lane, so it holds by construction
   (`round` is monotonic, so it survives the millisecond rounding).

The vocabulary itself belongs to the lane, not to this module: `STAGE_ORDER` /
`RETRIEVE_CHILDREN` are the fast lane's and stay the default, and a second deterministic lane
(the briefing build, `briefing.py`) hands `StageRecorder` its own. What is shared is the
mechanism — accumulate, degrade, and emit one vocabulary completely, in its own fixed order.
The agentic lanes are the other shape entirely (`agentic.py`): no fixed vocabulary to emit
against, so they build an ordered interleaving out of the same `StageTiming`.

LIVE, NOT ONLY AFTERWARDS. The same measurement points that produce the final `stages`
also ANNOUNCE themselves: pass `on_event` and every stage reports a `StageEvent` when it
begins (`phase="start"`) and another when it settles (`phase="end"`, carrying the value the
stage has accumulated so far). One clock, one set of measure sites — so what a waiting UI
paints while the lane runs and what the finished result carries can never disagree. With no
callback nothing is emitted and the recorder is byte-identical to what it was before events
existed.

I5 is untouched: nothing measured here reaches a SystemMessage. Timings live on the result.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from ..canonical_glance import claim_display_text

#: `ran` — it happened. `skipped` — it did not happen at all (ms is 0). `degraded` — it
#: happened, cost what it cost, and fell back; `detail` carries the existing degraded reason.
StageStatus = Literal["ran", "skipped", "degraded"]

#: The fast lane's stages, in the order a reader walks them. Derived from the code path in
#: `fast_recall`, not from a wish list: `route` sits after `retrieve` because it runs INSIDE
#: that gather (it is reported separately because a routing turn is a model call, and a model
#: call is the thing a reader is looking for). `assemble` is the deterministic evidence work
#: between the selection and the answer — episode summaries, window assembly, provenance
#: expansion, images, the component merge — which would otherwise be an unexplained gap
#: between the stages and `total`.
STAGE_ORDER: tuple[str, ...] = (
    "plan",
    "retrieve",
    "route",
    "rerank",
    "select",
    "assemble",
    "answer",
    "total",
)

#: The built-in lanes inside the retrieval gather, in fixed order. Routed component paths are
#: appended after them as `retrieve.path:<name>`, in the order the routing turn chose them.
RETRIEVE_CHILDREN: tuple[str, ...] = ("claims", "windows", "glance")

#: A child's name is `<parent><CHILD_SEPARATOR><leaf>`. One separator, one parser — the wire
#: stays a flat list and every surface splits it the same way.
CHILD_SEPARATOR = "."

#: The parent every child hangs under today. Kept as a name rather than inlined so a future
#: second parent is a vocabulary change, not a rewrite of the emit walk.
RETRIEVE = "retrieve"


def child_name(leaf: str) -> str:
    """`claims` → `retrieve.claims`; `path:person` → `retrieve.path:person`."""
    return f"{RETRIEVE}{CHILD_SEPARATOR}{leaf}"



#: A preview is a GLANCE at what a stage was handed and what it produced — a bounded head of
#: what each item SAYS, where it is, and its id, never the evidence itself. The bound is what
#: makes that a mechanism rather than a wish: whatever a call site assembles, `bound_preview`
#: is the only way it reaches a `StageTiming`, and nothing bigger than this can come out the
#: other side. ~1 KB serialized, which is a few readable lines on a screen and far less than
#: any one claim, window or answer.
PREVIEW_BUDGET_CHARS = 1024

#: The keys an ITEM inside a preview list uses, in the order a reader needs them: what it
#: says, where it lives, which id it carries. One vocabulary across every lane, because a
#: person reads one popover the same way whichever lane drew it.
ITEM_TEXT = "text"
ITEM_DOC = "doc"
ITEM_SOURCE = "source"
ITEM_SPAN = "span"
ITEM_ID = "id"

#: What a list item gives up FIRST when the budget is tight, in this order. The ranking is the
#: owner's, and it is the whole redesign in one tuple: an id is recognisable only to someone
#: who already knows it, a location is recognisable to someone who knows the library, and the
#: words are recognisable to anyone. So the id goes, then the span, then the title — and the
#: text is shortened only once there is nothing left to drop. Applied to mappings that are
#: LIST ELEMENTS only, never to a stage's own top-level keys.
PREVIEW_ITEM_DROP_ORDER: tuple[str, ...] = (ITEM_ID, ITEM_SPAN, ITEM_DOC, ITEM_SOURCE)

#: Successive rungs of (list items kept, characters kept per string, item keys dropped). The
#: first that fits the budget wins; if the last one still does not, trailing keys are dropped.
#: Deterministic and terminating by construction — the empty object always fits. The ladder
#: descends by dropping decoration and shedding items before it cuts a text head below what
#: reads as a sentence: a rung that shortened `text` to 20 characters while keeping `id`
#: would spend the budget on exactly the half of an entry the owner said was not a preview.
PREVIEW_RUNGS: tuple[tuple[int, int, tuple[str, ...]], ...] = (
    (10, 160, ()),
    (8, 120, ()),
    (5, 100, PREVIEW_ITEM_DROP_ORDER[:1]),
    (4, 80, PREVIEW_ITEM_DROP_ORDER[:2]),
    (3, 80, PREVIEW_ITEM_DROP_ORDER[:2]),
    (3, 64, PREVIEW_ITEM_DROP_ORDER),
    (2, 48, PREVIEW_ITEM_DROP_ORDER),
    (1, 32, PREVIEW_ITEM_DROP_ORDER),
)

#: How much of what an item SAYS a preview carries, and how much of a tool's return value.
#: Enough to read as a sentence and recognise the thought; nowhere near the item itself.
#: Evidence reaches a reader through the answer and its citations — a telemetry frame is not
#: a second way out of the library, which is why these are small and the bound caps them again.
PREVIEW_TEXT_CHARS = 80
PREVIEW_RESULT_CHARS = 120

#: How many items a face's preview lists, and how many a selection lists across its faces.
PREVIEW_ITEMS = 5
PREVIEW_CHOSEN = 10

#: What an elided string or a truncated list ends with, so a reader can tell a preview that
#: was cut from one that happened to be short.
ELLIPSIS = "…"


def _plain(value: object) -> object:
    """The value as JSON-safe primitives. Anything unrecognised becomes its `str`."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    return str(value)


def _shrink(
    value: object, items: int, chars: int, drop: tuple[str, ...] = (), *, item: bool = False
) -> object:
    """One rung applied to the whole object. `item` is True for a mapping that is a LIST
    ELEMENT — the only place `drop` bites, so a stage's own `hits` or `cap` can never be
    mistaken for an entry's decoration and thrown away."""
    if isinstance(value, str):
        return value if len(value) <= chars else value[:chars] + ELLIPSIS
    if isinstance(value, Mapping):
        return {
            k: _shrink(v, items, chars, drop)
            for k, v in value.items()
            if not (item and k in drop)
        }
    if isinstance(value, list):
        kept = [_shrink(v, items, chars, drop, item=True) for v in value[:items]]
        dropped = len(value) - items
        return kept if dropped <= 0 else [*kept, f"{ELLIPSIS}+{dropped} more"]
    return value


def _too_big(data: object) -> bool:
    return len(json.dumps(data, ensure_ascii=False)) > PREVIEW_BUDGET_CHARS


def bound_preview(data: Mapping | None) -> dict | None:
    """The one place a preview is made small enough to be one. Returns None for nothing.

    Mechanical, not advisory: every call site hands its raw dict to this, and what comes back
    is under `PREVIEW_BUDGET_CHARS` serialized — whatever the call site thought it was
    sending. Lists are truncated, list items shed their decoration in
    `PREVIEW_ITEM_DROP_ORDER`, and strings are elided, at successively harder rungs until the
    whole object fits; if even the hardest rung is too big, trailing keys are dropped, which
    terminates because `{}` fits. A call site therefore cannot leak full text by writing a
    preview carelessly, which is the difference between a bound and a convention.

    Which half a squeeze takes is a DESIGN decision and not an accident of the ladder: what an
    item says survives longer than the id beside it, because ids are what a preview full of
    them taught us it must not be.
    """
    if not data:
        return None
    plain = _plain(dict(data))
    out: object = plain
    for items, chars, drop in PREVIEW_RUNGS:
        out = _shrink(plain, items, chars, drop)
        if not _too_big(out):
            return dict(out)  # type: ignore[arg-type]
    trimmed = dict(out)  # type: ignore[arg-type]
    while trimmed and _too_big(trimmed):
        trimmed.pop(next(reversed(trimmed)))
    return trimmed or None


# ------------------------------------------------------------------ what a preview SAYS
#
# The bound above is the mechanism; what follows is the CONTENT, and the two live together
# because they are one decision. A preview used to be a list of addresses — `c1a2b3c4
# projects/pricing.md`, `d4e5f6a7 ¶7-7` — which named every item and described none of them.
# It was all ids, and a panel of ids is not a preview of anything: an id is a handle for a
# machine, and a person recognises WORDS. So an entry now leads with a bounded head of what
# the item says, then where it lives, then — if there is still room — the id as a tag. The
# preference is not advisory: `PREVIEW_ITEM_DROP_ORDER` is the same order, enforced by the
# squeeze, so the budget can never be spent on ids while the words are cut.


def preview_head(text: str, limit: int = PREVIEW_TEXT_CHARS) -> str:
    """A bounded head of what a piece of text SAYS — one line, display text, no machinery.

    The stripping is `claim_display_text`'s — citation spans, anchor and supersedes comments,
    then the markdown itself — which is the one path this repository turns stored text into a
    line a person reads, so a preview head and a glance line cannot disagree about what a
    claim says. Cut on a word boundary when there is one late enough to keep the
    head nearly full, because a head that stops mid-word reads as damage rather than as a
    quotation that continues.
    """
    plain = claim_display_text(text or "")
    if len(plain) <= limit:
        return plain
    cut = plain[:limit]
    space = cut.rfind(" ")
    if space >= int(limit * 0.6):
        cut = cut[:space]
    return cut.rstrip() + ELLIPSIS


def span_label(start: object, end: object) -> str:
    """`¶7-12` — the span half of the one addressing scheme (I4), as a reader sees it."""
    return f"¶{start}-{end}"


def claim_entry(claim: object, titles: Mapping[str, str] | None = None) -> dict:
    """One claim as an entry: what it says, the document it lives in, its anchor.

    `titles` maps a document path to its title when the caller holds the documents; without
    one the path's filename stem stands in, which is derived rather than invented — a preview
    must never call a port to look prettier, because every stage would then pay for it.
    """
    path = str(getattr(claim, "document_path", "") or "")
    doc = (titles or {}).get(path) or path.rsplit("/", 1)[-1].removesuffix(".md")
    entry = {ITEM_TEXT: preview_head(str(getattr(claim, "text", "") or ""))}
    if doc:
        entry[ITEM_DOC] = doc
    anchor = str(getattr(claim, "anchor", "") or "")
    if anchor:
        entry[ITEM_ID] = anchor
    return entry


def window_entry(window: object) -> dict:
    """One window/passage/hit as an entry: what it says, its source, its block span.

    A `RecallHit` carries no title (only an assembled `Passage` or an episode summary does),
    so the source id stands in — the address is still the address, it is simply the least
    readable of the three fields and the first location to be dropped under pressure.
    """
    start = getattr(window, "block_start", getattr(window, "block_index", 0))
    end = getattr(window, "block_end", getattr(window, "block_index", 0))
    source = str(getattr(window, "source_title", "") or "") or str(
        getattr(window, "source_id", "?")
    )
    return {
        ITEM_TEXT: preview_head(str(getattr(window, "text", "") or "")),
        ITEM_SOURCE: source,
        ITEM_SPAN: span_label(start, end),
    }


def claim_entries(
    claims, titles: Mapping[str, str] | None = None, limit: int = PREVIEW_ITEMS
) -> list[dict]:
    return [claim_entry(c, titles) for c in list(claims)[:limit]]


def window_entries(windows, limit: int = PREVIEW_ITEMS) -> list[dict]:
    return [window_entry(w) for w in list(windows)[:limit]]


def face_preview(rows, entries: list[dict]) -> dict:
    """The shape every retrieval face's preview takes: how many, and what the first few say."""
    return {"hits": len(rows), "items": entries}


def call_line(name: str, args: Mapping | None = None, rejected: str | None = None) -> str:
    """`person(alias="Wei Lin")` — a tool call as the call it was, arguments inline.

    A routing decision is a sentence about the question ("look this person up"), and a reader
    recognises it as one only when the name and the arguments arrive together. A rejected call
    says so on the same line: it is the same decision, plus what stopped it.
    """
    rendered = ", ".join(f"{k}={_arg_literal(v)}" for k, v in dict(args or {}).items())
    line = f"{name}({rendered})"
    return f"{line} — rejected: {rejected}" if rejected else line


def _arg_literal(value: object) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    return json.dumps(_plain(value), ensure_ascii=False)


def no_call_line(offered) -> str:
    """What a routing turn that chose nothing DID — the paths it was offered and declined.

    "none" is a finding about the question, but a count of what was on the table is not: a
    reader who cannot see which paths existed cannot tell a sensible decline from a broken
    router. So the offered paths are named."""
    names = ", ".join(str(name) for name in offered)
    return f"no path chosen — offered: {names}" if names else "no path chosen"


def face_line(counts) -> str:
    """`claims 80 → 1, episodes 52 → 0, windows 60 → 0` — a selection in one line.

    `counts` is `(face, candidates, chosen)` triples. A face with no candidates is left out:
    it was not a choice the selector made, it is a face this deployment does not have.
    """
    return ", ".join(
        f"{name} {before} → {after}" for name, before, after in counts if before
    )


def section_line(counts, chars: int) -> str:
    """`claims 8 · windows 12 · episodes 4 · 11.5k chars` — a context in one line.

    The counts a section carries and the size they add up to, which is the pair that explains
    both what the answer was given and what it was charged for."""
    parts = [f"{name} {count}" for name, count in counts if count]
    parts.append(f"{_short_count(chars)} chars")
    return " · ".join(parts)


def _short_count(value: int) -> str:
    """`11500` → `11.5k`. Four digits of characters is a number nobody reads."""
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)


@dataclass(frozen=True)
class StageTiming:
    """One stage's measured wall-clock, as it reaches the result and the wire."""

    name: str
    ms: int
    status: StageStatus = "ran"
    #: Why it degraded — the lane's existing reason string ("timeout", "error",
    #: "invalid_args", …), copied rather than re-detected. None on every other status.
    detail: str | None = None
    #: What went in and what came out, small enough to read at a glance — the queries a plan
    #: generated, how many hits a face returned and the first few labels, the tools a routing
    #: turn chose. Bounded by `bound_preview`, never full text, None when the stage offered
    #: none. A duration says a stage was slow; this says what it was slow AT.
    preview: dict | None = None


#: A stage is either beginning or settling. There is no third phase: a stage that never
#: begins simply has no events, which is the same fact `emit` reports as `status="skipped"`.
StagePhase = Literal["start", "end"]


@dataclass(frozen=True)
class StageEvent:
    """One stage crossing a boundary, announced the moment it happens.

    `key` is what a consumer identifies a NODE by, and it is the emitter's business, not the
    reader's. A `StageRecorder` accumulates by name (`rerank` is genuinely two sequential
    passes reported as one stage), so its key IS the name and a later `end` supersedes the
    earlier one. An agentic lane appends instead (two `tool:search_claims` calls are two
    steps), so it mints a fresh key per step. A consumer that keys on `key` and prints `name`
    is therefore correct for both without knowing which lane it is watching.

    `at_ms` is the elapsed milliseconds since the LANE began — the emitter's own clock, so a
    reader never has to time anything from arrival gaps. `ms` is null on a `start` (nothing
    has been measured yet) and the stage's settled duration on an `end`.
    """

    name: str
    phase: StagePhase
    key: str
    at_ms: int
    ms: int | None = None
    status: StageStatus = "ran"
    detail: str | None = None
    #: The stage's bounded preview, on `end` frames only — a `start` has nothing to preview
    #: yet, and inventing one would be the only value here that was not measured.
    preview: dict | None = None


#: What a caller passes to watch a lane as it runs. CONTRACT: it MUST NOT BLOCK — it is
#: called synchronously from inside the measured code, on that code's own event loop.
StageEventSink = Callable[[StageEvent], None]


class StageRecorder:
    """Collects durations as the lane runs, then emits the fixed vocabulary in one place.

    `measure` is the only timing primitive: a stage that is never measured is emitted as
    `skipped`, which is how "never ran" stays mechanical instead of depending on a caller
    remembering to declare it. Measuring the same name twice ACCUMULATES — the rerank stage
    is genuinely two sequential passes (claims, then component evidence) and reads as one.

    `order` / `children` are the vocabulary to emit against, defaulting to the fast lane's.
    A second deterministic lane (the briefing build) passes its own, which is why the walk
    reads them off the instance: the vocabulary belongs to the lane that measured it, this
    module owns only the mechanics of emitting one completely and in a fixed order.
    """

    def __init__(
        self,
        order: tuple[str, ...] = STAGE_ORDER,
        children: tuple[str, ...] = RETRIEVE_CHILDREN,
        *,
        on_event: StageEventSink | None = None,
    ) -> None:
        self._order = order
        self._children = children
        self._ms: dict[str, float] = {}
        self._detail: dict[str, str] = {}
        #: Per-stage previews, merged across passes and re-bounded on every merge.
        self._preview: dict[str, dict] = {}
        #: Stages currently inside a `measure` block. A preview recorded there must NOT
        #: announce an `end` of its own — the block's own `finally` is about to send one,
        #: and a premature `end` would settle a node a UI is still drawing as running.
        self._open: set[str] = set()
        #: Dynamic `retrieve.path:<name>` children, in first-measured order.
        self._paths: list[str] = []
        self._on_event = on_event
        #: The lane's own clock. Every `at_ms` is elapsed against THIS, so a consumer never
        #: has to reconstruct when something happened from when it heard about it.
        self._started = time.perf_counter()

    # ------------------------------------------------------------------ live events

    def _at(self) -> int:
        return int(round(max((time.perf_counter() - self._started) * 1000.0, 0.0)))

    def _announce(self, name: str, phase: StagePhase, at_ms: int) -> None:
        """One event, built from the SAME state `emit` will read at the end.

        An `end` therefore carries exactly what the final `stages` entry for that name would
        carry if the lane stopped here — accumulated ms, current status, current reason —
        which is why the last `end` per name and the final list cannot drift apart."""
        if self._on_event is None:
            return
        settled = self._one(name)
        self._on_event(
            StageEvent(
                name=name,
                phase=phase,
                key=name,
                at_ms=at_ms,
                ms=settled.ms if phase == "end" else None,
                status="ran" if phase == "start" else settled.status,
                detail=settled.detail,
                preview=settled.preview if phase == "end" else None,
            )
        )

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        self._announce(name, "start", self._at())
        started = time.perf_counter()
        self._open.add(name)
        try:
            yield
        finally:
            self._open.discard(name)
            self._accumulate(name, (time.perf_counter() - started) * 1000.0)
            self._announce(name, "end", self._at())

    def _accumulate(self, name: str, ms: float) -> None:
        self._ms[name] = self._ms.get(name, 0.0) + max(ms, 0.0)

    def record(self, name: str, ms: float, *, preview: Mapping | None = None) -> None:
        """Add a measured duration for `name`. Marks it as having run, even at 0 ms.

        Unlike `measure`, this arrives AFTER the fact (the caller timed it itself), so the
        pair of events is back-dated: the `start` is placed `ms` before now, which is where
        the work actually was. A consumer sees a node that is already finished rather than
        one that appears to have taken no time."""
        self._merge_preview(name, preview)
        self._accumulate(name, ms)
        at = self._at()
        self._announce(name, "start", max(at - int(round(max(ms, 0.0))), 0))
        self._announce(name, "end", at)

    def record_path(
        self,
        path: str,
        ms: float,
        *,
        detail: str | None = None,
        preview: Mapping | None = None,
    ) -> None:
        """Record one routed component path as a `retrieve` child.

        Unlike `record`, a repeated name keeps the LONGER duration rather than summing:
        two calls to the same path (different arguments) ran concurrently, so their sum is
        not a duration anything took.
        """
        name = child_name(f"path:{path}")
        if name not in self._ms:
            self._paths.append(name)
        self._ms[name] = max(self._ms.get(name, 0.0), max(ms, 0.0))
        # Silent: `degrade` announces, and the reason has to be on the stage BEFORE the
        # pair of events below carries it — otherwise a degraded path would announce itself
        # as a clean success and be corrected a microsecond later.
        if detail:
            self._detail[name] = detail
        self._merge_preview(name, preview)
        at = self._at()
        self._announce(name, "start", max(at - int(round(max(ms, 0.0))), 0))
        self._announce(name, "end", at)

    def _merge_preview(self, name: str, data: Mapping | None) -> None:
        """Merge into what the stage already previewed, then re-bound the WHOLE thing.

        Merged rather than replaced because a stage can be measured more than once (fast's
        `assemble` is five passes and one stage), and a second pass describing a different
        part of the same work must not erase the first. Re-bounded after the merge, so the
        cap holds over the union and not merely over each contribution."""
        if not data:
            return
        merged = {**self._preview.get(name, {}), **dict(data)}
        bounded = bound_preview(merged)
        if bounded is not None:
            self._preview[name] = bounded

    def preview(self, name: str, data: Mapping | None) -> None:
        """Attach what went in and what came out to a stage. Falsy data changes nothing.

        Call it INSIDE the `measure` block, where the result is in hand: the block's own
        `end` then carries it, and the live frame and the final `stages` entry are one fact.
        Called after the block (or for a stage recorded after the fact), it corrects an
        already-settled stage with a second `end` — same key, last end wins, which is the
        rule a consumer follows anyway."""
        if not data:
            return
        self._merge_preview(name, data)
        if name in self._ms and name not in self._open:
            self._announce(name, "end", self._at())

    def degrade(self, name: str, detail: str | None) -> None:
        """Attach a fall-back reason to a stage that ran. A falsy reason changes nothing.

        The lanes call this just AFTER the `measure` block that produced the reason, so a
        stage that has already ended is corrected with a second `end` — same key, new status.
        Last end wins, which is the rule a consumer follows anyway."""
        if not detail:
            return
        self._detail[name] = detail
        if name in self._ms:
            self._announce(name, "end", self._at())

    def emit(self) -> tuple[StageTiming, ...]:
        out: list[StageTiming] = []
        for name in self._order:
            out.append(self._one(name))
            if name == RETRIEVE:
                out.extend(
                    self._one(child)
                    for child in (*(child_name(c) for c in self._children), *self._paths)
                )
        return tuple(out)

    def _one(self, name: str) -> StageTiming:
        detail = self._detail.get(name)
        preview = self._preview.get(name)
        if name not in self._ms:
            return StageTiming(
                name=name, ms=0, status="skipped", detail=detail, preview=preview
            )
        return StageTiming(
            name=name,
            ms=int(round(self._ms[name])),
            status="degraded" if detail else "ran",
            detail=detail,
            preview=preview,
        )
