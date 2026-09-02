"""Access statistics — the framework's own, built-in consumer of use-side records.

WHAT THIS IS
------------
A consultation is EMITTED, never processed in the request path (docs/design/
steward-owner-visitor.md §4). Delivery is the ordinary job queue, and this module is the
default consumer sitting at the end of it: per-target access metadata kept in the derived
layer — when a target was last read, how many times in the last 7 and 30 days.

Default-on and inert by default. It is not a component and needs none registered: every
`business` consultation reaches it. With every visitor `silent` there are no consultations
at all, so nothing is written and every seam renders exactly as it did before the concept
existed.

WHERE IT LIVES, AND WHERE IT MUST NOT
-------------------------------------
Two derived tables, keyed by address (I4) and by `user_id` first (I1):

- `recall_access_hits(user_id, target_kind, target_ref, day, hits, last_seen)` — one row per
  target per calendar day. Evidence merely HANDED to the model counts once; evidence the
  answer went on to CITE counts once more. `last_seen` is the exact instant of the latest
  consultation that touched the target on that day, so the target's true last access is the
  MAX across its day rows — the whole of last-access tracking, in a column the day row was
  already going to write, rather than in a second table saying the same thing.
- `recall_access_misses(user_id, day, question, count)` — the questions that came back with
  nothing, because what is missing has no address to be keyed by. The question is the row's
  own key, so it is bounded where it is written rather than by a btree index failing the day
  somebody pastes an essay into the query box: whitespace-normalized, capped at 400
  characters, and marked when it was cut, so a bounded question never reads as a whole one.

Access metadata NEVER touches a canonical file. It is joined at read time, by address, out
of the derived layer — a read must never become a write to the authority.

AT MOST ONCE PER RECORD
-----------------------
`apply_record` and the `projected_at` stamp on the consultation row land in ONE transaction.
A job that finds `projected_at` already set is a no-op, so a retry — a worker killed
mid-job, a queue self-heal on restart — cannot count the same consultation twice. What the
stamp does not cover is the component fan-out that follows it: a process death between the
commit and the fan-out loses the notification for good. That is the at-most-once trade this
delivery model chose out loud, in place of the at-least-once one that would double every
count it recovered.

NO SCORE IS STORED
------------------
`heat` is `Σ hits × 0.5^(age_days / half_life)`, computed at read time, so the half-life is
a knob rather than a migration and the tables stay a pure function of the records that
produced them. A rebuild replays this user's `business` consultations into a replacement set
and swaps it in — reproducing both tables byte-for-byte from `consultations` alone.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

from pneuma_knowledge_core.components import notify_recall
from pneuma_knowledge_core.domain.consultation import ConsultationRecord, EvidenceRef
from pneuma_knowledge_core.domain.ids import UserId

_log = logging.getLogger(__name__)

#: The job kind one `business` consultation is delivered under. The row and this job are
#: written in the same transaction (adapters/postgres.py `create_consultation`), so a job
#: never names a consultation that is not there.
RECALL_PROJECTION_JOB_KIND = "recall_projection"

#: The job kind an operator's rebuild runs under. It exists so the rebuild takes the same
#: per-user claim every other job takes: while it is claimed, `claim_next` hands out no
#: `recall_projection` for that user, and vice versa. That is the whole serialization story
#: — no second lock, no second pool.
RECALL_REBUILD_JOB_KIND = "recall_rebuild"

#: A question is the miss table's primary key, so it is bounded here rather than by a btree
#: index failing on the day somebody pastes an essay into the query box. Truncation is
#: marked, so a bounded question never reads as the whole question.
QUESTION_CHARS = 400
QUESTION_ELLIPSIS = "…"

#: The replay's page. Bounded because the caller is a rebuild, and a rebuild that loads a
#: year of records into one list is a rebuild that stops working exactly when the library
#: gets used.
REPLAY_PAGE = 500


# --------------------------------------------------------------------------- pure heat


def heat(
    hits_by_day: Mapping[date, int], *, now: date, half_life_days: float
) -> float:
    """`Σ hits × 0.5^(age_days / half_life)` — attention that fades, as a pure function.

    Two properties matter more than the exact curve. It is MONOTONIC in hits, so a target
    consulted more is never colder than the same target consulted less on the same days; and
    it is a function of the rows alone, so the same table with the same `now` renders the
    same number in a report, in a test and in a replay.

    A half-life of zero or less means "do not decay" rather than a division by zero: the
    knob then reports raw counts, which is a legitimate configuration and not an error.

    A future-dated row (clock skew on a writer) counts at FACE VALUE and never more: a
    negative age would make `0.5 ** age` a multiplier greater than one, so the one row
    nobody meant to write would outrank every row somebody did.
    """
    total = 0.0
    for day, hits in hits_by_day.items():
        if half_life_days <= 0:
            total += float(hits)
            continue
        age = max(0, (now - day).days)
        total += float(hits) * (0.5 ** (age / half_life_days))
    return total


def bounded_question(question: str) -> str:
    text = " ".join(str(question or "").split())
    if len(text) <= QUESTION_CHARS:
        return text
    return text[: QUESTION_CHARS - 1] + QUESTION_ELLIPSIS


def utc_day(moment: datetime | None) -> date:
    """A record's calendar day, in UTC. A naive datetime is read as UTC — the records are
    written by the service with an aware `now()`, and guessing a zone for one that arrived
    without would be inventing the very fact this ledger refuses to hold.

    The framework holds no zone opinion here on purpose: the `time` component owns the
    subject's calendar, and a second, divergent answer to "which day is this" is precisely
    what makes two projections disagree about the same afternoon.
    """
    if moment is None:
        return datetime.now(timezone.utc).date()
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc).date()
    return moment.astimezone(timezone.utc).date()


def _utc_instant(moment: datetime | None) -> datetime:
    """The record's own instant, in UTC — what `last_seen` records."""
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def targets(record: ConsultationRecord) -> dict[tuple[str, str], int]:
    """One record → `(target_kind, target_ref) → hits`, summed.

    Summed HERE and not at the write, for a mechanical reason: a claim that was handed over
    and then cited produces the same key twice, and one `INSERT … ON CONFLICT` may not touch
    the same row twice in a statement. The dict is also what makes "cited counts one more
    than handed" a single readable rule instead of two write paths.

    A ref is dispatched on its SHAPE FIRST, and only on `kind` when the shape says nothing:
    `kind` says how a lane reached the item (`component` covers both a routed claim lookup
    and a routed span; `document` covers both a page read in full and the provenance spans
    rendered inside it), while the address grammar says what it is — `c:xxxx` for a claim,
    `<source_id> ¶a-b` for a span (I4). An address that is neither is a canonical page path,
    and `kind == "document"` is what names it as one.

    A DOCUMENT counts at most once per pass, however many of its claims travelled — and
    whether it arrived as a page read whole or as the page some claims live on. It is not an
    evidence item; it is what evidence items live on, and counting it per claim would measure
    page LENGTH rather than attention — a nine-claim page would read nine times hotter than a
    one-claim page consulted just as often, and the report exists precisely to compare pages.
    Claims and sources are items and are counted as they come.
    """
    counts: dict[tuple[str, str], int] = {}

    def add(refs: Sequence[EvidenceRef]) -> None:
        pages: set[str] = set()
        for ref in refs or ():
            address = str(getattr(ref, "ref", "") or "").strip()
            if not address:
                continue
            if address.startswith("c:"):
                counts[("claim", address)] = counts.get(("claim", address), 0) + 1
                path = str(getattr(ref, "path", "") or "").strip()
                if path:
                    pages.add(path)
                continue
            if " ¶" in address:
                source_id = address.split(" ¶", 1)[0].strip()
                if source_id:
                    counts[("source", source_id)] = counts.get(("source", source_id), 0) + 1
                continue
            if str(getattr(ref, "kind", "") or "") == "document":
                pages.add(address)
                continue
            counts[("source", address)] = counts.get(("source", address), 0) + 1
        for path in pages:
            counts[("document", path)] = counts.get(("document", path), 0) + 1

    add(record.evidence_handed)
    add(record.citations)
    return counts


class LedgerSums:
    """The two tables' running sums, over records fed in any number of batches.

    Exists so a replay never has to hold its records. The rows a ledger needs are a
    SUMMATION, and a sum has a fixed size — one entry per (target, day) and per (day,
    question) — while the records producing it carry a whole answer and a whole evidence
    manifest each. Feeding a page and dropping it keeps the memory of a rebuild bounded by
    the library's distinct targets rather than by how much the library has been used.
    """

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str, date], int] = {}
        self._seen: dict[tuple[str, str, date], datetime] = {}
        self._misses: dict[tuple[date, str], int] = {}

    def add(self, records: Sequence[ConsultationRecord]) -> None:
        """Fold one batch in. The caller may drop it the moment this returns."""
        for record in records:
            if getattr(record, "visitor_class", "") != "business":
                continue
            day = utc_day(record.created_at)
            instant = _utc_instant(record.created_at)
            for (kind, ref), count in targets(record).items():
                key = (kind, ref, day)
                self._hits[key] = self._hits.get(key, 0) + count
                prior = self._seen.get(key)
                if prior is None or instant > prior:
                    self._seen[key] = instant
            if getattr(record, "miss", False):
                question = bounded_question(record.question)
                if question:
                    self._misses[(day, question)] = self._misses.get((day, question), 0) + 1

    def rows(self) -> tuple[list[dict], list[dict]]:
        """The two tables' rows, deterministically ordered."""
        return (
            [
                {
                    "target_kind": kind,
                    "target_ref": ref,
                    "day": day,
                    "hits": count,
                    "last_seen": self._seen[(kind, ref, day)],
                }
                for (kind, ref, day), count in sorted(self._hits.items())
            ],
            [
                {"day": day, "question": question, "count": count}
                for (day, question), count in sorted(self._misses.items())
            ],
        )


def ledger_rows(
    records: Sequence[ConsultationRecord],
) -> tuple[list[dict], list[dict]]:
    """`business` consultations → the two tables' rows, summed and deterministically ordered.

    ONE summation for both write paths. The projection job calls it with a single record and
    the rebuild folds its pages into the same `LedgerSums`, so "the same records produce the
    same rows" is a property of the code rather than of two implementations agreeing today.

    Summed rather than emitted per record for a mechanical reason as well: one
    `INSERT … ON CONFLICT` may not touch the same row twice in a statement, and a day
    accumulates across every consultation that happened in it.

    `last_seen` is the LATEST instant among the records that contributed to a row, so it
    survives the summation the way the counts do.
    """
    sums = LedgerSums()
    sums.add(records)
    return sums.rows()


# ------------------------------------------------------------------------- the read face


def summarize(
    rows: Sequence[Mapping[str, Any]], *, now: date, half_life_days: float
) -> dict[str, Any]:
    """One target's day rows → `{last_accessed_at, hits_7d, hits_30d, heat}`.

    The windows are CLOSED at both ends of a whole number of days: `hits_7d` is today and
    the six days before it, so a library asked once a day for a week reports seven.

    `last_accessed_at` is the MAX over EVERY day row, not over the window — a target last
    read forty-five days ago has a real last access and zero recent hits, and reporting the
    last access as absent because the window missed it would be the one wrong answer.
    """
    hits_by_day: dict[date, int] = {}
    last: datetime | None = None
    for row in rows:
        day = row["day"]
        hits_by_day[day] = hits_by_day.get(day, 0) + int(row.get("hits") or 0)
        seen = row.get("last_seen")
        if seen is not None and (last is None or seen > last):
            last = seen
    return {
        "last_accessed_at": last,
        "hits_7d": sum(
            count for day, count in hits_by_day.items() if (now - day).days < 7 and day <= now
        ),
        "hits_30d": sum(
            count for day, count in hits_by_day.items() if (now - day).days < 30 and day <= now
        ),
        "heat": heat(hits_by_day, now=now, half_life_days=half_life_days),
    }


async def access_stats(
    store: Any,
    user_id: UserId,
    pairs: Sequence[tuple[str, str]],
    *,
    half_life_days: float = 14.0,
    now: date | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """`(kind, ref) → {last_accessed_at, hits_7d, hits_30d, heat}` for a page of targets.

    The bulk form IS the form: a single target is a page of one, so a caller joining a list
    of documents against their access metadata makes one query rather than one per row, and
    there is no second code path to keep in step with this one. A target with no rows comes
    back with zeros and `last_accessed_at: None` — never absent, because "never read" is an
    answer and a missing key is not.
    """
    wanted = [(str(k), str(r)) for k, r in pairs]
    if not wanted:
        return {}
    today = now or datetime.now(timezone.utc).date()
    rows = await store.access_rows_for(user_id, wanted)
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {key: [] for key in wanted}
    for row in rows:
        key = (str(row["target_kind"]), str(row["target_ref"]))
        if key in grouped:
            grouped[key].append(row)
    return {
        key: summarize(group, now=today, half_life_days=half_life_days)
        for key, group in grouped.items()
    }



def top_targets(
    rows: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    now: date,
    half_life_days: float,
    window_days: int,
    limit: int,
) -> list[dict[str, Any]]:
    """The hottest targets of one kind, hottest first — the dashboard's half of the ledger.

    Two windows, on purpose, and the difference is the whole reason this is not `summarize`
    over a filtered list. `heat` RANKS, and it ranks over the window the caller asked about
    (`window_days`), because "what has this library been reading lately" is a question with a
    stated period. `hits_7d` / `hits_30d` / `last_accessed_at` REPORT, and they are the read
    face's own fixed windows over every row handed in — the same three numbers
    `GET /access-stats` gives for a single target, so a document reads the same on a
    dashboard as it does on its own page.

    A target with no row inside the ranking window is dropped rather than ranked at zero: it
    was not read in the period, and a top list padded with cold entries is a list about the
    library's size rather than about its use.

    Ties break on the address, so two targets read identically render in a stable order
    rather than in whatever order the rows arrived.
    """
    by_ref: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if str(row.get("target_kind") or "") != kind:
            continue
        by_ref.setdefault(str(row.get("target_ref") or ""), []).append(row)

    span = max(1, int(window_days))
    out: list[dict[str, Any]] = []
    for ref, group in by_ref.items():
        if not ref:
            continue
        windowed: dict[date, int] = {}
        for row in group:
            day = row["day"]
            age = (now - day).days
            if 0 <= age < span:
                windowed[day] = windowed.get(day, 0) + int(row.get("hits") or 0)
        if not windowed:
            continue
        stats = summarize(group, now=now, half_life_days=half_life_days)
        out.append(
            {
                "ref": ref,
                "heat": heat(windowed, now=now, half_life_days=half_life_days),
                "hits_7d": stats["hits_7d"],
                "hits_30d": stats["hits_30d"],
                "last_accessed_at": stats["last_accessed_at"],
            }
        )
    out.sort(key=lambda item: (-item["heat"], item["ref"]))
    return out[: max(0, int(limit))]


def top_misses(
    rows: Sequence[Mapping[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    """The questions this library answered with nothing, most-asked first.

    Summed across the window's days because the table is keyed by day and the question is
    not a different question for having been asked again on Tuesday. `last_day` is the most
    recent day it was asked, which is what tells a reader whether a miss is a standing gap or
    one afternoon's frustration.
    """
    counts: dict[str, int] = {}
    last: dict[str, date] = {}
    for row in rows:
        question = str(row.get("question") or "")
        if not question:
            continue
        counts[question] = counts.get(question, 0) + int(row.get("count") or 0)
        day = row["day"]
        if question not in last or day > last[question]:
            last[question] = day
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"question": question, "count": count, "last_day": last[question]}
        for question, count in ordered[: max(0, int(limit))]
    ]


# ------------------------------------------------------------------------- the write face


async def apply_record(store: Any, user_id: UserId, record: ConsultationRecord) -> bool:
    """Apply one record's hits and miss, and stamp it projected — in ONE transaction.

    Returns whether this call was the one that applied it. `False` means the record was
    already stamped, which is what makes a retried job a no-op rather than a second count.
    """
    hits, misses = ledger_rows([record])
    return await store.apply_access_stats(
        user_id, record.consultation_id, hits, misses
    )


async def rebuild_access_stats(store: Any, user_id: UserId) -> int:
    """Re-derive the whole ledger by replaying this user's `business` consultations.

    Built in memory, then SWAPPED in one write, so no reader ever sees a gap. The soundness
    against live increments is not a lock any more: this runs as a `recall_rebuild` job, and
    `claim_next` refuses to hand out a second job for a user with one in flight — so no
    `recall_projection` for this user can be applied while the replay and the swap run.

    The replay is paged to exhaustion: the walk's page is bounded, and a rebuild that read
    one page would silently truncate the ledger of exactly the libraries that get used. Each
    page is FOLDED into the running sums and dropped — the rows are a summation whose size is
    the library's distinct targets, while the records producing them each carry a whole
    answer and a whole evidence manifest, so retaining them would make a rebuild's memory a
    function of how much the library has been used.

    ONLY RECORDS ALREADY STAMPED `projected_at` ARE REPLAYED. A record still unstamped at
    scan time has a `recall_projection` job of its own waiting in this user's queue, and
    that queue is the serialization: this rebuild runs as a `recall_rebuild` job holding the
    user's one in-flight claim, so no projection can land between the scan and the swap.
    Excluded here, such a record is applied exactly once by its own job after the swap.
    Included, it would be counted twice — once by the replay, once by the job that has not
    yet run — and the ledger of a library being used while it is rebuilt would drift upward.

    A record replayed here is left STAMPED as it was. The stamp answers "has this record
    been applied once", and a rebuild that cleared it would hand the queue permission to
    apply an already-replayed record a second time.
    """
    sums = LedgerSums()
    replayed = 0
    after: tuple[datetime, str] | None = None
    while True:
        page = await store.list_consultations(
            user_id,
            visitor_class="business",
            projected=True,
            after=after,
            limit=REPLAY_PAGE,
        )
        if not page:
            break
        sums.add(page)
        replayed += len(page)
        after = (page[-1].created_at, page[-1].consultation_id)
        # The cursor is two scalars, so nothing from the page outlives this line.
        del page
    hits, misses = sums.rows()
    await store.replace_access_stats(user_id, hits, misses)
    return replayed


# ------------------------------------------------------------------------- the job handlers


async def run_recall_projection_job(ctx: Any, user_id: UserId, job: object) -> None:
    """One `kind="recall_projection"` job: the built-in consumer, then the components.

    Order is load-bearing. The stats and the stamp commit first, so a retry cannot
    double-count; the fan-out runs after, outside that transaction, because a component's
    hook is arbitrary code and holding a database transaction open across it is how one slow
    component becomes every tenant's lock wait. A component that raises is logged by
    `notify_recall` and costs a stale projection — never the job.
    """
    payload = getattr(job, "payload", {}) or {}
    job_id = getattr(job, "job_id")
    consultation_id = str(payload.get("consultation_id", ""))
    record = await ctx.store.get_consultation(user_id, consultation_id)
    if record is None:
        await ctx.store.complete(user_id, job_id, ok=True, detail="consultation gone")
        return
    applied = await apply_record(ctx.store, user_id, record)
    if applied:
        await notify_recall(str(user_id), record)
    await ctx.store.complete(
        user_id,
        job_id,
        ok=True,
        detail="projected" if applied else "already projected",
    )


async def run_recall_rebuild_job(ctx: Any, user_id: UserId, job: object) -> None:
    """One `kind="recall_rebuild"` job: the built-in ledger, then every component's own.

    Both halves run HERE, inside the claim, and that is the point: the ops script no longer
    re-derives anything itself, so nothing can interleave with this user's in-flight
    projection jobs. The built-in ledger is rebuilt whether or not any component is
    registered — it is the framework's, not a component's.
    """
    from pneuma_knowledge_core.components import rebuild_components

    job_id = getattr(job, "job_id")
    replayed = await rebuild_access_stats(ctx.store, user_id)
    names = await rebuild_components(str(user_id))
    detail = f"replayed {replayed} record(s)"
    if names:
        detail += f"; components: {', '.join(names)}"
    await ctx.store.complete(user_id, job_id, ok=True, detail=detail)


__all__ = [
    "QUESTION_CHARS",
    "RECALL_PROJECTION_JOB_KIND",
    "RECALL_REBUILD_JOB_KIND",
    "LedgerSums",
    "access_stats",
    "apply_record",
    "bounded_question",
    "heat",
    "ledger_rows",
    "rebuild_access_stats",
    "run_recall_projection_job",
    "run_recall_rebuild_job",
    "summarize",
    "targets",
    "top_misses",
    "top_targets",
    "utc_day",
]
