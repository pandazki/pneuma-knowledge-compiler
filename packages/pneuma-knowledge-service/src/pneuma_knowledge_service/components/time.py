"""The `time` component: the owner's calendar as an index, and the first PERSISTED
component projection.

WHAT IT ADDS
------------
Canonical has no concept of a calendar. Every layer can already say *what* a source said
and *which span* said it, but "what happened between June and August", "what did we decide
before the price change", "what held on 2026-04-12" are questions about the owner's days,
and answering them from L1/L2 means hoping the words "June" appear in the text.

This component keeps one derived row per L0 block — the block's UTC instant, and the
SUBJECT's calendar day it belongs to — and offers it at three seams:

- fast path `timespan(since, until)`: the sources whose spans fall in a day range, grouped
  into per-day spans and ordered by time, plus the claims whose evidence comes from those
  days (current first, superseded labelled). Exact enumeration, no ranking and no
  truncation — the WHOLE range travels, and the framework ranks it against the question
  before spending the path's cap on it (core recall/component_rank.py), stating per day what
  it did not show;
- deep tools `timeline(since, until, granularity, offset, limit)` — a day-by-day or
  week-by-week digest of what the library actually holds in a window, paginated, with
  `granularity="verbatim"` reading ONE day block by block so a day can be read rather than
  sampled — and `as_of(date, alias, identity)`, which walks a subject's supersession chains
  and reports the claim that was IN FORCE on a date, with its citation;
- `source_preamble`: the compile task states a source's span in the owner's local terms and,
  when the source carries its own zone, in that zone too.

THE SEVEN DAY RULES IT IS BUILT ON
----------------------------------
Every rule below is enforced somewhere; this list is the one place that says where, so a
`D4` written in a comment three modules away resolves to a rule rather than to a memory.

D1 · Instants are stored UTC; the INDEX KEY is the subject's local day — the same day
     ingest wrote into `section_path[0]`. A source's own zone (a meeting's `timezone`) is
     metadata, rendered beside, never the key. For a subject at +08:00 a message sent at
     00:30 local carries the previous UTC date; keyed by UTC it would answer the wrong day.
     (`time_rows` here; `local_day` in core recall/timespan.py.)
D2 · Every row records the zone it was normalized under AND where that zone came from
     (profile / provider / deployment default). Changing a zone does not rewrite rows —
     `scripts/ops/rebuild_derived.py` re-derives them, explicitly. Never a silent mix.
     (`time_rows` and `TimeComponent.rebuild` here.)
D3 · A day range converts to UTC with the zone in effect FOR THAT PERIOD, walking
     `UserProfile.locale.timezone_history`. (`day_range_to_utc` / `zone_at` in core.)
D4 · Natural-language time is never parsed here. "上季度" and "last Monday" are resolved by
     the ROUTING model, which sees `as_of` and the subject's zone; the args schemas accept
     ISO `YYYY-MM-DD` and nothing else, so a colloquial argument becomes an `invalid_args`
     audit row instead of a quietly wrong range. (`TimespanArgs._iso_only` here;
     `parse_iso_day` in core.)
D5 · One representation on input, several on output: a rendered time line carries the
     owner's day and clock, the zone it was rendered under, and the source's own clock when
     the two differ — a reader is never left guessing whose watch they are reading.
     (`day_label` / `dual_clock` / `span_label` in core; `source_preamble` here.)
D6 · No claim time is ever stored. Which day a claim is about is derived at query time from
     its citations' sources, so this projection cannot drift out of step with canonical.
     (`evidence_day` inside `as_of`, and the claim half of `timespan`.)
D7 · A day range is answered by an index on the day column, not by a scan of the tenant's
     blocks. (`component_time_blocks_day` in infra/schema.sql; `time_blocks_in_range` in
     the Postgres adapter.)

The mechanics of D1, D3, D4 and D5 live in core recall/timespan.py — this component holds
the projection and the seams, core holds the calendar arithmetic.

The rows are derived (I2) and rebuildable in full from L0; user_id is first everywhere (I1);
every span it returns is an ordinary `source_id + block span` and every claim an anchor with
its `[cite: …]` (I4).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool
from pneuma_knowledge_core.canonical_glance import document_title
from pneuma_knowledge_core.components import BaseComponent, registered_components
from pneuma_knowledge_core.compile.supersession import (
    block_by_anchor,
    chains,
    superseded_index,
)
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource
from pneuma_knowledge_core.domain.time_context import UTC, TimeContext, time_context_for
from pneuma_knowledge_core.recall.fast import RetrievedClaim
from pneuma_knowledge_core.recall.paths import PathResult
from pneuma_knowledge_core.recall.projection import ProjectedClaim, project_document_claims
from pneuma_knowledge_core.recall.rag import RecallHit
from pneuma_knowledge_core.recall.timespan import (
    ISO_DAY_RE,
    day_label,
    dual_clock,
    parse_iso_day,
    span_label,
)
from pydantic import BaseModel, Field, field_validator

from .pagination import (
    PAGINATED_NOTE,
    TIMELINE_PAGE_LIMIT,
    VERBATIM_PAGE_LIMIT,
    call_text,
    navigation_line,
)

_log = logging.getLogger(__name__)

#: Which meta list carries a per-block instant, per official source contract. The block
#: sequence and the meta list are built from the SAME sorted order in
#: `ingest/canonical_sources.py`, so block index i is meta entry i — the alignment is
#: verified by length before it is relied on, and a mismatch degrades to "no clock, the
#: source's occurrence day only" rather than to a wrong timestamp.
_INSTANT_META: dict[str, tuple[str, str]] = {
    "meeting": ("segments", "started_at"),
    "im": ("messages", "sent_at"),
    "email": ("messages", "sent_at"),
    # An owner dialogue is conversation-shaped like the three above: one block per turn,
    # each carrying the instant it was said. Left out of this table its turns kept only the
    # coarse occurrence day, so a timeline could not tell a morning correction from the
    # afternoon one that walked it back — on the one material whose author is the subject.
    "owner_dialogue": ("turns", "said_at"),
}

#: Output bounds. A digest that silently stops reads as "that was everything"; each of
#: these is paired with an explicit "…and N more" line.
TIMELINE_BUCKET_CAP = 40
TIMELINE_SOURCES_PER_BUCKET = 8
TIMELINE_CLAIMS_PER_BUCKET = 8
RANGE_ROW_CAP = 5000


# ------------------------------------------------------------------ derivation from L0


def _instant(value: object) -> datetime | None:
    """An ISO timestamp string from `RawSource.meta` → an aware UTC datetime, or None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(UTC)


def block_instants(raw: RawSource, block_count: int) -> tuple[list[datetime | None], str | None]:
    """Per-block UTC instants (index-aligned) and the source's OWN zone when it declares one.

    Only the conversation-shaped contracts carry per-block timestamps. Anything else — a
    document library, a plain import — gets `None` for every block: it still has an
    occurrence day, it simply has no clock, and inventing one would be the exact fabrication
    this system exists to make impossible.
    """
    meta = raw.meta or {}
    source_zone = str(meta.get("timezone") or "").strip() or None
    spec = _INSTANT_META.get(raw.kind)
    if spec is None:
        return [None] * block_count, source_zone
    list_key, field = spec
    entries = meta.get(list_key) or []
    if len(entries) != block_count:
        # The one thing that must never happen silently: attaching entry i's timestamp to a
        # block it does not belong to. Length is the whole alignment contract, so a mismatch
        # drops the clock for this source rather than guessing.
        _log.warning(
            "source %s: %d %s meta entries for %d blocks; dropping per-block instants",
            raw.source_id, len(entries), list_key, block_count,
        )
        return [None] * block_count, source_zone
    return [_instant((e or {}).get(field)) for e in entries], source_zone


def _block_day(block: NormalizedBlock, fallback: str) -> str:
    """The subject-local day a block belongs to when it has no instant of its own.

    Ingest already computed it, in the subject's zone, and wrote it into `section_path[0]`
    for the day-sectioned contracts; a heading-sectioned one falls back to the source's
    `occurred_on`. A block with neither gets no row at all — a NULL day would answer every
    range query wrongly rather than not at all.
    """
    head = str((block.section_path or [""])[0] or "").strip()
    return head if ISO_DAY_RE.match(head) else fallback


def time_rows(raw: RawSource, blocks: Sequence[NormalizedBlock], ctx: TimeContext) -> list[dict]:
    """One source's projection rows. Pure — the store writes whatever this returns."""
    instants, source_zone = block_instants(raw, len(blocks))
    fallback = raw.occurred_on()[:10]
    rows: list[dict] = []
    for position, block in enumerate(blocks):
        instant = instants[position] if position < len(instants) else None
        if instant is not None:
            day: date | None = ctx.local_date(instant)
        else:
            iso = _block_day(block, fallback)
            day = date.fromisoformat(iso) if ISO_DAY_RE.match(iso) else None
        if day is None:
            continue
        rows.append(
            {
                "block_index": block.index,
                "instant_utc": instant,
                "local_day": day,
                "zone": ctx.zone_name,
                "zone_source": ctx.zone_source,
                "source_zone": source_zone,
                "kind": raw.kind,
            }
        )
    return rows


# --------------------------------------------------------------------------- grouping


class Span:
    """A contiguous run of one source's blocks on one of the owner's calendar days."""

    __slots__ = ("source_id", "title", "kind", "day", "start", "end", "first", "last", "zone", "source_zone")

    def __init__(self, row: dict) -> None:
        self.source_id = str(row["source_id"])
        self.title = str(row.get("title") or "")
        self.kind = str(row.get("kind") or "")
        self.day: date = row["local_day"]
        self.start = int(row["block_index"])
        self.end = int(row["block_index"])
        self.first: datetime | None = row.get("instant_utc")
        self.last: datetime | None = row.get("instant_utc")
        self.zone = str(row.get("zone") or "UTC")
        self.source_zone = row.get("source_zone")

    def extend(self, row: dict) -> None:
        self.end = int(row["block_index"])
        instant = row.get("instant_utc")
        if instant is not None:
            self.first = instant if self.first is None else min(self.first, instant)
            self.last = instant if self.last is None else max(self.last, instant)

    def order_key(self) -> tuple:
        return (self.day, self.first or datetime.min.replace(tzinfo=UTC), self.source_id, self.start)


def group_spans(rows: Sequence[Mapping]) -> list[Span]:
    """Rows → spans: consecutive blocks of ONE source on ONE day become one span.

    A day boundary always cuts, even mid-conversation: the day is the unit the owner recalls
    by, so an IM thread that ran past midnight is two spans, exactly as it is two sections.
    """
    by_source_day: dict[tuple[str, date], list[dict]] = {}
    for row in rows:
        by_source_day.setdefault((str(row["source_id"]), row["local_day"]), []).append(dict(row))
    spans: list[Span] = []
    for key in sorted(by_source_day, key=lambda k: (k[1], k[0])):
        group = sorted(by_source_day[key], key=lambda r: int(r["block_index"]))
        current: Span | None = None
        for row in group:
            if current is not None and int(row["block_index"]) == current.end + 1:
                current.extend(row)
                continue
            if current is not None:
                spans.append(current)
            current = Span(row)
        if current is not None:
            spans.append(current)
    spans.sort(key=Span.order_key)
    return spans


def _iso_week_start(day: date) -> date:
    return date.fromordinal(day.toordinal() - day.weekday())


# ------------------------------------------------------------------------ args schemas


class TimespanArgs(BaseModel):
    since: str = Field(description="first day of the range, ISO YYYY-MM-DD, inclusive")
    until: str = Field(description="last day of the range, ISO YYYY-MM-DD, inclusive")

    @field_validator("since", "until")
    @classmethod
    def _iso_only(cls, value: str) -> str:
        parse_iso_day(value)  # raises → the routing call becomes an `invalid_args` row
        return value.strip()


# ------------------------------------------------------------------------ the component


class TimeComponent(BaseComponent):
    name = "time"

    def __init__(
        self,
        *,
        content=None,
        canonical=None,
        user_info=None,
        default_timezone: str = "UTC",
    ) -> None:
        self._content = content
        self._canonical = canonical
        self._user_info = user_info
        self._default_timezone = default_timezone
        # Last resolved TimeContext per user. `source_preamble` is a SYNC seam inside prompt
        # assembly and cannot await a profile lookup, so it reads this cache, which the
        # index hook fills for every source it projects. A cold cache falls through to the
        # provider/deployment resolution below, and either way the rendered line NAMES the
        # zone it used — a reader is never left guessing whose clock they are reading.
        self._zones: dict[str, TimeContext] = {}

    # --- zone resolution ------------------------------------------------------------

    async def time_context(self, user_id: UserId, *, raw: RawSource | None = None) -> TimeContext:
        """The subject's clock, resolved exactly as compile resolves it (provider → profile
        → deployment default), and remembered for the sync seams."""
        profile = None
        if self._user_info is not None:
            try:
                profile = await self._user_info.get_profile(UserId(user_id))
            except Exception:  # noqa: BLE001 — a profile lookup never fails an index job
                _log.warning("profile lookup failed for %s; using the deployment default", user_id)
        ctx = time_context_for(
            UserId(user_id), profile, raw=raw, default_timezone=self._default_timezone
        )
        self._zones[str(user_id)] = ctx
        return ctx

    def _cached_context(self, user_id: str, raw: RawSource | None = None) -> TimeContext:
        cached = self._zones.get(str(user_id))
        if cached is not None:
            return cached
        return time_context_for(
            UserId(user_id), None, raw=raw, default_timezone=self._default_timezone
        )

    async def prepare(self, user_id: str) -> None:
        """The framework is about to run a job for this user through the SYNC seams —
        resolve the clock now, because they cannot.

        `source_preamble` renders inside prompt assembly and cannot await a profile lookup,
        so it reads `self._zones`. In a compile process that cache is cold by construction
        (the index job that filled it ran elsewhere), and a cold read falls through to the
        DEPLOYMENT default — which renders a subject at +08:00 under UTC and names UTC as
        the zone. Honest, and still the wrong clock. This hook is the async face that makes
        the sync one right.
        """
        await self.time_context(UserId(user_id))

    # --- face: the projection channel -------------------------------------------------

    async def on_source_indexed(self, user_id: str, source: NormalizedSource) -> None:
        """One source finished L1/L2 → (re)derive its time rows. Idempotent."""
        if self._content is None or not hasattr(self._content, "put_time_blocks"):
            return
        uid = UserId(user_id)
        ctx = await self.time_context(uid, raw=source.raw)
        rows = time_rows(source.raw, source.blocks, ctx)
        await self._content.put_time_blocks(uid, source.raw.source_id, rows)

    async def rebuild(self, user_id: str) -> None:
        """Re-derive this user's whole projection from L0 under the CURRENT zone (D2): the
        one place a timezone change is allowed to change already-written rows, and it is
        explicit, operator-run and reported."""
        if self._content is None or not hasattr(self._content, "put_time_blocks"):
            return
        uid = UserId(user_id)
        ctx = await self.time_context(uid)
        await self._content.delete_time_blocks(uid)
        for raw in await self._content.list(uid):
            normalized = await self._content.get(uid, raw.source_id)
            await self._content.put_time_blocks(
                uid, raw.source_id, time_rows(normalized.raw, normalized.blocks, ctx)
            )

    # --- canonical helpers ------------------------------------------------------------

    async def _documents(self, user_id: UserId, documents) -> dict[str, object]:
        """The lane's pinned `documents` when given (a snapshot query stays pinned), else
        canonical HEAD."""
        if documents is not None:
            return {d.path: d for d in documents}
        if self._canonical is None:
            return {}
        return {d.path: d for d in await self._canonical.list(user_id)}

    @staticmethod
    def _projected(docs: Mapping[str, object]) -> dict[str, ProjectedClaim]:
        """anchor → projected claim, over every pinned document."""
        out: dict[str, ProjectedClaim] = {}
        for doc in docs.values():
            for claim in project_document_claims(doc):
                out[str(claim.anchor)] = claim
        return out

    @staticmethod
    def _cite(claim: ProjectedClaim) -> str:
        return " ".join(
            f"[cite: {c.source_id} ¶{c.block_start}-{c.block_end}]" for c in claim.citations
        )

    def _find_pages(self, docs: Mapping[str, object], *, alias: str, identity: str) -> list[str]:
        """The subject's page(s). Delegated to the `people` component when it is enabled —
        it owns identity resolution and this component must not grow a second, divergent
        answer to "who is 贾宁". Without it, title/slug only: an honest lesser lookup, not a
        guess dressed as one."""
        for component in registered_components():
            if getattr(component, "name", "") == "people" and hasattr(component, "find_in"):
                return list(component.find_in(docs, identity=identity, alias=alias))
        want = alias.strip().casefold()
        if not want:
            return []
        hits: list[str] = []
        for path in sorted(docs):
            doc = docs[path]
            names = {str((doc.frontmatter or {}).get("slug") or "").casefold(),
                     document_title(doc).casefold()}
            if want in names:
                hits.append(path)
        return hits

    # --- face: the fast path ------------------------------------------------------------

    async def timespan(
        self,
        user_id: UserId,
        *,
        since: str,
        until: str,
        documents=None,
        as_of: datetime | None = None,
    ) -> PathResult:
        """The library's own content for a range of the owner's days: source spans in time
        order, and the claims whose evidence comes from those same days.

        Everything in the range, never the first N of it. The range is the query — cutting
        it at six spans and six claims answers a narrower question than the one that was
        asked, in whichever order the days happened to sort. The framework ranks these
        against the question and spends the path's cap on that order
        (core `recall/component_rank.py`), stating per day what it did not show."""
        if self._content is None or not hasattr(self._content, "time_blocks_in_range"):
            return PathResult()
        uid = UserId(user_id)
        first, last = parse_iso_day(since), parse_iso_day(until)
        if last < first:
            first, last = last, first
        ctx = await self.time_context(uid)
        as_of_day = ctx.local_date(as_of) if as_of is not None else None
        rows = await self._content.time_blocks_in_range(uid, first, last, limit=RANGE_ROW_CAP)
        spans = group_spans(rows)

        # Block text comes from L0, for the spans that will actually be shown — the
        # projection holds addresses, never content.
        windows: list[RecallHit] = []
        cached: dict[str, NormalizedSource] = {}
        for span in spans:
            if span.source_id not in cached:
                try:
                    cached[span.source_id] = await self._content.get(uid, SourceId(span.source_id))
                except KeyError:
                    continue
            normalized = cached[span.source_id]
            by_index = {b.index: b.text for b in normalized.blocks}
            body = "\n".join(
                by_index[i] for i in range(span.start, span.end + 1) if i in by_index
            )
            head = span_label(
                span.day,
                first=span.first,
                last=span.last,
                subject_zone=_zone(span.zone, ctx.zone),
                source_zone=_zone(span.source_zone, None),
                as_of_day=as_of_day,
            )
            label = f"{head} · {span.kind} · {span.title}".rstrip(" ·")
            windows.append(
                RecallHit(
                    source_id=SourceId(span.source_id),
                    block_start=span.start,
                    block_end=span.end,
                    text=f"{label}\n{body}",
                    paths=("time",),
                    score=1.0,
                )
            )

        docs = await self._documents(uid, documents)
        in_range = {span.source_id for span in spans}
        dead = superseded_index({p: d.body for p, d in docs.items()})
        current: list[RetrievedClaim] = []
        history: list[RetrievedClaim] = []
        for path in sorted(docs):
            for claim in project_document_claims(docs[path]):
                if not any(str(c.source_id) in in_range for c in claim.citations):
                    continue
                superseded = str(claim.anchor) in dead
                hit = RetrievedClaim(
                    anchor=claim.anchor,
                    document_path=claim.document_path,
                    section_path=claim.section_path,
                    text=claim.text,
                    citations=claim.citations,
                    paths=("time",),
                    score=1.0,
                    labels=("superseded",) if superseded else ("current",),
                )
                (history if superseded else current).append(hit)
        # Both lists complete and in their own order (spans by time, claims current-first).
        # Which of the two a question actually wants is a relevance judgement, and relevance
        # judgements belong to the framework, not to an enumeration.
        return PathResult(claims=tuple([*current, *history]), windows=tuple(windows))

    def fast_paths(self, user_id: str):
        component = self
        uid = UserId(user_id)

        class TimespanPath:
            name = "timespan"
            description = (
                "Everything the owner's library holds between two calendar days: the "
                "sources whose material falls in that range (in time order, each with its "
                "day, weekday and clock) and the claims whose evidence comes from those "
                "days, current ones first and superseded ones labelled. It answers a "
                "PERIOD, not a topic: what happened in a month, what changed between two "
                "dates. since/until are calendar days in the owner's timezone, inclusive, "
                "and are ISO YYYY-MM-DD only — this path parses no relative or colloquial "
                "expression (\"last quarter\", \"上个月\"); as_of and the owner's timezone "
                "are stated above, and anything else becomes an invalid_args audit row."
            )
            args_schema = TimespanArgs
            cap = 12

            async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):
                return await component.timespan(
                    uid,
                    since=args.since,
                    until=args.until,
                    documents=documents,
                    as_of=as_of,
                )

        return [TimespanPath()]

    # --- face: deep-recall tools ---------------------------------------------------------

    async def timeline(
        self,
        user_id: UserId,
        *,
        since: str,
        until: str,
        granularity: str = "day",
        offset: int = 0,
        limit: int = TIMELINE_PAGE_LIMIT,
        documents=None,
    ) -> str:
        """A day-by-day (or week-by-week) digest of what the library holds in a window — or,
        with `granularity="verbatim"`, one day's material in full.

        The point is COMPLETENESS, not relevance: a "what happened in June" question is
        answered over the closed set of that month's material, and what does not fit on this
        page is stated with the exact call that fetches it, never dropped. `verbatim` is the
        way down to the source without guessing block numbers first: the whole day, in block
        order, paginated — so a day can be READ rather than sampled."""
        if self._content is None or not hasattr(self._content, "time_blocks_in_range"):
            return "timeline unavailable: no content store wired."
        uid = UserId(user_id)
        first, last = parse_iso_day(since), parse_iso_day(until)
        if last < first:
            first, last = last, first
        mode = str(granularity or "day").strip().lower()
        if mode == "verbatim":
            return await self._verbatim_day(
                uid, first, last, offset=offset, limit=limit
            )
        weekly = mode == "week"
        ctx = await self.time_context(uid)
        rows = await self._content.time_blocks_in_range(uid, first, last, limit=RANGE_ROW_CAP)
        spans = group_spans(rows)
        docs = await self._documents(uid, documents)
        dead = superseded_index({p: d.body for p, d in docs.items()})
        by_source: dict[str, list[ProjectedClaim]] = {}
        labels: dict[str, str] = {}
        for path in sorted(docs):
            for claim in project_document_claims(docs[path]):
                for citation in claim.citations:
                    by_source.setdefault(str(citation.source_id), []).append(claim)
                labels[str(claim.anchor)] = "superseded" if str(claim.anchor) in dead else "current"

        buckets: dict[date, list[Span]] = {}
        for span in spans:
            buckets.setdefault(_iso_week_start(span.day) if weekly else span.day, []).append(span)

        unit = "week" if weekly else "day"
        lines = [
            f"{len(spans)} source span(s) across {len(buckets)} {unit}(s) "
            f"in {first.isoformat()}..{last.isoformat()} "
            f"(the owner's calendar, {ctx.zone_name}; zone from {ctx.zone_source})"
        ]
        if not spans:
            lines.append("(no material in this window)")
            return "\n".join(lines)
        offset = max(int(offset), 0)
        limit = max(int(limit), 1)
        ordered_buckets = sorted(buckets)
        for bucket in ordered_buckets[offset : offset + limit]:
            members = buckets[bucket]
            head = (
                f"## {bucket.isoformat()}..{date.fromordinal(bucket.toordinal() + 6).isoformat()} (week)"
                if weekly
                else f"## {day_label(bucket)}"
            )
            lines.append(head)
            for span in members[:TIMELINE_SOURCES_PER_BUCKET]:
                clock_text = (
                    dual_clock(
                        span.first,
                        span.last,
                        subject_zone=_zone(span.zone, ctx.zone),
                        source_zone=_zone(span.source_zone, None),
                    )
                    if span.first is not None
                    else "(no clock)"
                )
                lines.append(
                    f"- {span.kind} · {span.title or '(untitled)'} · {clock_text} · "
                    f"{span.end - span.start + 1} block(s) "
                    f"[cite: {span.source_id} ¶{span.start}-{span.end}]"
                )
            if len(members) > TIMELINE_SOURCES_PER_BUCKET:
                lines.append(f"  …and {len(members) - TIMELINE_SOURCES_PER_BUCKET} more source span(s).")
            seen: set[str] = set()
            claims: list[ProjectedClaim] = []
            for span in members:
                for claim in by_source.get(span.source_id, ()):
                    if str(claim.anchor) in seen:
                        continue
                    seen.add(str(claim.anchor))
                    claims.append(claim)
            claims.sort(key=lambda c: (labels.get(str(c.anchor)) != "current", c.document_path, str(c.anchor)))
            for claim in claims[:TIMELINE_CLAIMS_PER_BUCKET]:
                lines.append(
                    f"  · [c:{claim.anchor} · {claim.document_path} · "
                    f"{labels.get(str(claim.anchor), 'current')}] {claim.text} {self._cite(claim)}".rstrip()
                )
            if len(claims) > TIMELINE_CLAIMS_PER_BUCKET:
                lines.append(
                    f"  …and {len(claims) - TIMELINE_CLAIMS_PER_BUCKET} more claim(s) — read "
                    f"the day in full with "
                    + call_text(
                        "timeline",
                        since=bucket.isoformat(),
                        until=bucket.isoformat(),
                        granularity="verbatim",
                    )
                )
        page = ordered_buckets[offset : offset + limit]
        lines.append(
            navigation_line(
                total=len(ordered_buckets),
                offset=offset,
                shown=len(page),
                unit=f"{unit}(s)",
                more=call_text(
                    "timeline",
                    since=first.isoformat(),
                    until=last.isoformat(),
                    granularity=unit,
                    offset=offset + limit,
                    limit=limit,
                ),
                narrow=(
                    call_text(
                        "timeline",
                        since=page[0].isoformat(),
                        until=page[0].isoformat(),
                        granularity="verbatim",
                    )
                    if page and not weekly
                    else ""
                ),
            )
        )
        return "\n".join(lines)

    async def _verbatim_day(
        self, user_id: UserId, first: date, last: date, *, offset: int = 0, limit: int = VERBATIM_PAGE_LIMIT
    ) -> str:
        """One day of L0, verbatim and block-addressed, paginated by block.

        `timeline` says a day holds 60 blocks and 3 sources; this is how the lane reads them
        without calling `fetch_verbatim` on a guessed range. One day only — "verbatim" over a
        month is not a digest, it is the corpus."""
        if first != last:
            return (
                "verbatim reads ONE day at a time — call "
                + call_text(
                    "timeline",
                    since=first.isoformat(),
                    until=first.isoformat(),
                    granularity="verbatim",
                )
                + f" (the window asked for was {first.isoformat()}..{last.isoformat()})."
            )
        ctx = await self.time_context(user_id)
        rows = await self._content.time_blocks_in_range(user_id, first, last, limit=RANGE_ROW_CAP)
        spans = group_spans(rows)
        offset = max(int(offset), 0)
        limit = max(int(limit), 1)
        addresses: list[tuple[Span, int]] = [
            (span, index) for span in spans for index in range(span.start, span.end + 1)
        ]
        lines = [
            f"# {day_label(first)} — {len(addresses)} block(s) across {len(spans)} source "
            f"span(s) (the owner's calendar, {ctx.zone_name})"
        ]
        page = addresses[offset : offset + limit]
        cached: dict[str, NormalizedSource] = {}
        current_span: Span | None = None
        for span, index in page:
            if span.source_id not in cached:
                try:
                    cached[span.source_id] = await self._content.get(
                        user_id, SourceId(span.source_id)
                    )
                except KeyError:
                    continue
            if current_span is not span:
                current_span = span
                head = span_label(
                    span.day,
                    first=span.first,
                    last=span.last,
                    subject_zone=_zone(span.zone, ctx.zone),
                    source_zone=_zone(span.source_zone, None),
                )
                lines.append(f"## {head} · {span.kind} · {span.title}".rstrip(" ·"))
            by_index = {b.index: b.text for b in cached[span.source_id].blocks}
            text = by_index.get(index, "")
            lines.append(f"[cite: {span.source_id} ¶{index}-{index}] {text}")
        lines.append(
            navigation_line(
                total=len(addresses),
                offset=offset,
                shown=len(page),
                unit="blocks",
                more=call_text(
                    "timeline",
                    since=first.isoformat(),
                    until=first.isoformat(),
                    granularity="verbatim",
                    offset=offset + limit,
                    limit=limit,
                ),
            )
        )
        return "\n".join(lines)

    async def as_of(
        self,
        user_id: UserId,
        *,
        day: str,
        alias: str = "",
        identity: str = "",
        documents=None,
    ) -> str:
        """What held on a given day: per supersession chain, the claim in force then.

        Time-travel over canonical without storing a single claim date. A chain is walked by
        each link's EVIDENCE day (the projected day of the source it cites), so the answer
        stays exactly as fresh as canonical and as honest as the citations.
        """
        target = parse_iso_day(day)
        uid = UserId(user_id)
        docs = await self._documents(uid, documents)
        hits = self._find_pages(docs, alias=alias, identity=identity)
        if not hits:
            what = " / ".join(x for x in (alias.strip(), identity.strip()) if x) or "(empty query)"
            return f"no page matches {what}."
        bodies = {p: d.body for p, d in docs.items()}
        located = block_by_anchor(bodies)
        projected = self._projected(docs)
        wanted = set(hits)
        # Only the chains that touch this subject's page(s), and only the sources THOSE
        # chains cite: the day lookup asks for the handful of ids it will actually read,
        # never for the library's whole citation set.
        walk = [
            chain
            for chain in chains(bodies)
            if any(located.get(a, ("", ""))[0] in wanted for a in chain)
        ]
        source_ids = {
            str(c.source_id)
            for chain in walk
            for anchor in chain
            for c in (projected[anchor].citations if anchor in projected else ())
        }
        days: dict[str, str] = {}
        if source_ids and hasattr(self._content, "time_days_for_sources"):
            days = await self._content.time_days_for_sources(uid, sorted(source_ids))

        def evidence_day(anchor: str) -> str:
            claim = projected.get(anchor)
            if claim is None:
                return ""
            found = [days.get(str(c.source_id), "") for c in claim.citations]
            return min((d for d in found if d), default="")

        lines = [
            f"# in force on {day_label(target)} — "
            + ", ".join(f"`{p}`" for p in hits)
        ]
        for chain in walk:
            in_force: str | None = None
            later: list[str] = []
            for anchor in chain:
                when = evidence_day(anchor)
                if when and when > target.isoformat():
                    later.append(anchor)
                else:
                    in_force = anchor
            if in_force is None:
                first = projected.get(chain[0])
                lines.append(
                    f"- (nothing in this chain had evidence by then; the earliest is "
                    f"[c:{chain[0]}] {first.text if first else ''} "
                    f"{self._cite(first) if first else ''})".rstrip()
                )
                continue
            claim = projected.get(in_force)
            when = evidence_day(in_force) or "(no dated evidence)"
            text = claim.text if claim else "(claim text unavailable)"
            lines.append(
                f"- [c:{in_force} · evidence {when}] {text} "
                f"{self._cite(claim) if claim else ''}".rstrip()
            )
            if later:
                lines.append(
                    f"  (superseded after this date by {', '.join('c:' + a for a in later)})"
                )
        if not walk:
            lines.append(
                "(no superseded chain on this page — nothing about it has been recorded as "
                "changing, so its current claims are also what held then)"
            )
        return "\n".join(lines)

    def recall_tools(self, user_id: str, *, documents=None) -> list[StructuredTool]:
        component = self
        uid = UserId(user_id)

        async def timeline(
            since: str,
            until: str,
            granularity: str = "day",
            offset: int = 0,
            limit: int = TIMELINE_PAGE_LIMIT,
        ) -> str:
            return await component.timeline(
                uid,
                since=since,
                until=until,
                granularity=granularity,
                offset=offset,
                limit=limit,
                documents=documents,
            )

        async def as_of(date: str, alias: str = "", identity: str = "") -> str:
            return await component.as_of(
                uid, day=date, alias=alias, identity=identity, documents=documents
            )

        return [
            StructuredTool.from_function(
                coroutine=timeline,
                name="timeline",
                description=(
                    "A day-by-day (or week-by-week) digest of everything the owner's library "
                    "holds between two calendar days: every source span with its clock and "
                    "block range, and the claims whose evidence comes from it, current or "
                    "superseded. The CLOSED set for that window — what does not fit is "
                    "counted, not dropped. since/until are ISO YYYY-MM-DD in the owner's "
                    "timezone, inclusive; granularity is \"day\", \"week\", or "
                    "\"verbatim\" — which reads ONE day (since == until) block by block, "
                    "the whole material rather than a digest of it. " + PAGINATED_NOTE
                ),
            ),
            StructuredTool.from_function(
                coroutine=as_of,
                name="as_of",
                description=(
                    "What held on a PAST date. For the subject named by alias/identity, walks "
                    "each recorded chain of superseded claims and reports the one that was in "
                    "force on that date, with its citation and the day its evidence is from. "
                    "Use for \"what was X back then\", \"when did this change\", or any "
                    "question whose answer the current state would get wrong. date is ISO "
                    "YYYY-MM-DD in the owner's timezone."
                ),
            ),
        ]

    # --- face: the compile-task preamble --------------------------------------------------

    def source_preamble(self, source: NormalizedSource) -> str | None:
        """One line: this source's span in the owner's day and clock, plus its own zone when
        that differs. Only for sources that HAVE per-block instants — compile already states
        `occurred_on`, and repeating it would be noise.

        The DAY comes from the blocks' own sections, not from a zone resolved here. Ingest
        already computed it in the subject's zone and wrote it into `section_path[0]`, and
        index and compile are separate jobs: a worker restart between them leaves this sync
        seam's zone cache cold, and a preamble that re-derived the day would then state one
        day while the very blocks beneath it are sectioned under another. Only the wall
        clock needs a zone, and the line names the zone it rendered under.
        """
        instants, source_zone = block_instants(source.raw, len(source.blocks))
        known = [i for i in instants if i is not None]
        if not known:
            return None
        ctx = self._cached_context(str(source.raw.user_id), source.raw)
        first, last = min(known), max(known)
        sectioned = sorted(
            {
                head
                for block in source.blocks
                for head in [str((block.section_path or [""])[0] or "").strip()]
                if ISO_DAY_RE.match(head)
            }
        )
        if sectioned:
            start_day = date.fromisoformat(sectioned[0])
            end_day = date.fromisoformat(sectioned[-1])
        else:
            start_day, end_day = ctx.local_date(first), ctx.local_date(last)
        clock_text = dual_clock(
            first, last, subject_zone=ctx.zone, source_zone=_zone(source_zone, None)
        )
        span = day_label(start_day)
        if end_day != start_day:
            span += f"..{day_label(end_day)}"
        return f"Time of this source (the owner's calendar): {span} {clock_text}"


def _zone(name: object, fallback: ZoneInfo | None) -> ZoneInfo | None:
    """An IANA name → ZoneInfo, or the fallback. An unusable name never raises here: the
    value came from a stored row or a provider's metadata, and a bad one degrades to the
    subject's zone rather than failing a query."""
    from pneuma_knowledge_core.domain.time_context import load_zone

    return load_zone(name) or fallback


__all__ = [
    "RANGE_ROW_CAP",
    "Span",
    "TimeComponent",
    "TimespanArgs",
    "block_instants",
    "group_spans",
    "time_rows",
]
