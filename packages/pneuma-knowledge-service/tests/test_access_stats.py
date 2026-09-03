"""The framework's built-in access statistics: heat, target dispatch, windows, and the job.

Everything here runs without middleware because everything here is a function of its
arguments — which is the point of computing heat at read time instead of storing it. The
live tables, the transaction that makes an application at-most-once, and the replay are
exercised against a real postgres in `tests/integration/test_access_stats_pg.py`.
"""

from __future__ import annotations

import gc
import weakref
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.components import register_component, reset_components
from pneuma_knowledge_core.domain.consultation import (
    ConsultationRecord,
    EvidenceRef,
    dedup_evidence,
)
from pneuma_knowledge_core.domain.ids import UserId

from pneuma_knowledge_service.access_stats import (
    QUESTION_CHARS,
    access_stats,
    apply_record,
    bounded_question,
    heat,
    ledger_rows,
    rebuild_access_stats,
    run_recall_projection_job,
    summarize,
    targets,
    top_misses,
    top_targets,
)

TODAY = date(2026, 8, 31)
NOON = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _record(**kwargs) -> ConsultationRecord:
    base = dict(
        consultation_id="k-1",
        user_id="u-lynx-1",
        created_at=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
        lane="fast",
        visitor_class="business",
        question="阿宝上个季度盯的是哪条线？",
        as_of=None,
        library_ref="deadbeef",
    )
    base.update(kwargs)
    return ConsultationRecord(**base)


# ------------------------------------------------------------------------------- heat


def test_an_empty_ledger_is_cold():
    assert heat({}, now=TODAY, half_life_days=14) == 0.0


def test_todays_hits_count_in_full():
    assert heat({TODAY: 5}, now=TODAY, half_life_days=14) == 5.0


def test_one_half_life_ago_counts_half_and_two_count_a_quarter():
    assert heat({TODAY - timedelta(days=14): 8}, now=TODAY, half_life_days=14) == 4.0
    assert heat({TODAY - timedelta(days=28): 8}, now=TODAY, half_life_days=14) == 2.0


def test_days_add_up():
    ledger = {TODAY: 2, TODAY - timedelta(days=14): 4, TODAY - timedelta(days=28): 8}
    assert heat(ledger, now=TODAY, half_life_days=14) == 2 + 2 + 2


def test_a_shorter_half_life_forgets_faster():
    old = {TODAY - timedelta(days=7): 8}
    assert heat(old, now=TODAY, half_life_days=7) < heat(old, now=TODAY, half_life_days=28)


def test_more_hits_is_never_colder():
    assert heat({TODAY: 3}, now=TODAY, half_life_days=14) > heat(
        {TODAY: 2}, now=TODAY, half_life_days=14
    )


def test_no_half_life_means_no_decay_rather_than_a_division_by_zero():
    """A legitimate configuration — raw counts — and not an error to guard against."""
    ledger = {TODAY: 2, TODAY - timedelta(days=300): 3}
    assert heat(ledger, now=TODAY, half_life_days=0) == 5.0


def test_a_future_dated_row_counts_at_face_value_and_is_never_amplified():
    """Clock skew on a writer produces a row dated after `now`, and a negative age turns
    `0.5 ** age` into a MULTIPLIER: the one row nobody meant to write outranked every row
    somebody did."""
    tomorrow = TODAY + timedelta(days=1)
    assert heat({tomorrow: 3}, now=TODAY, half_life_days=14) == 3.0
    assert heat({tomorrow: 3}, now=TODAY, half_life_days=14) <= heat(
        {TODAY: 3}, now=TODAY, half_life_days=14
    )


# --------------------------------------------------------------------- target dispatch


def test_a_claim_counts_for_itself_and_for_the_page_it_lives_on():
    record = _record(
        evidence_handed=(EvidenceRef("claim", "c:aa11", "memory/people/mei-lin.md"),)
    )
    assert targets(record) == {
        ("claim", "c:aa11"): 1,
        ("document", "memory/people/mei-lin.md"): 1,
    }


def test_a_cited_item_counts_one_more_than_one_merely_handed_over():
    handed = EvidenceRef("claim", "c:aa11", "memory/people/mei-lin.md")
    record = _record(evidence_handed=(handed,), citations=(handed,))
    assert targets(record)[("claim", "c:aa11")] == 2


def test_a_span_is_addressed_by_its_source_and_has_no_page():
    record = _record(evidence_handed=(EvidenceRef("window", "src-01 ¶2-4", ""),))
    assert targets(record) == {("source", "src-01"): 1}


def test_a_page_counts_once_per_pass_however_many_of_its_claims_travelled():
    """A document is not an evidence item; it is what the items live on. Counted per claim,
    a nine-claim page would read nine times hotter than a one-claim page consulted just as
    often — which measures length, not attention."""
    long_page = tuple(
        EvidenceRef("claim", f"c:{i:04x}", "memory/topics/pricing.md") for i in range(9)
    )
    short_page = (EvidenceRef("claim", "c:ffff", "memory/people/mei-lin.md"),)
    counts = targets(_record(evidence_handed=long_page + short_page))

    assert counts[("document", "memory/topics/pricing.md")] == 1
    assert counts[("document", "memory/people/mei-lin.md")] == 1
    assert counts[("claim", "c:0000")] == 1


def test_a_routed_lookup_is_dispatched_on_the_address_not_on_the_kind():
    """`kind="component"` says HOW the lane reached the item; the address grammar says what
    it is. A component face returns both claims and spans, so a projection that switched on
    the kind would file half of them as the wrong thing."""
    record = _record(
        evidence_handed=(
            EvidenceRef("component", "c:bb22", "memory/topics/pricing.md"),
            EvidenceRef("component", "src-09 ¶0-1", ""),
            EvidenceRef("episode", "src-09 ¶4-6", ""),
        )
    )
    assert targets(record) == {
        ("claim", "c:bb22"): 1,
        ("document", "memory/topics/pricing.md"): 1,
        ("source", "src-09"): 2,
    }


def test_a_page_read_in_full_is_a_document_and_never_mistaken_for_a_source():
    """A `document` address is a canonical PAGE PATH — the one shape that is neither
    `c:xxxx` nor `<source_id> ¶a-b`. Dispatched on shape alone it fell through to the source
    branch, so a recall answered out of one whole page produced a phantom source whose id
    was a file path, and no document heat for the page anybody actually read."""
    record = _record(
        evidence_handed=(
            EvidenceRef("document", "memory/people/mei-lin.md", ""),
            EvidenceRef("document", "src-07 ¶1-3", ""),
        )
    )
    assert targets(record) == {
        ("document", "memory/people/mei-lin.md"): 1,
        ("source", "src-07"): 1,
    }


def test_a_page_reached_both_as_a_full_read_and_by_one_of_its_claims_counts_once():
    record = _record(
        evidence_handed=(
            EvidenceRef("document", "memory/people/mei-lin.md", ""),
            EvidenceRef("claim", "c:aa11", "memory/people/mei-lin.md"),
        )
    )
    assert targets(record)[("document", "memory/people/mei-lin.md")] == 1


def test_a_claim_two_faces_reached_is_one_hit_not_two():
    """Heat must count what the consultation was SHOWN, not how many ways it got there —
    otherwise a claim a component happens to route to reads twice as hot as an identical one
    it does not, and the report exists to compare them."""
    handed = dedup_evidence(
        [
            EvidenceRef("claim", "c:aa11", "memory/people/mei-lin.md"),
            EvidenceRef("component", "c:aa11", "memory/people/mei-lin.md"),
        ]
    )
    counts = targets(_record(evidence_handed=handed))
    assert counts[("claim", "c:aa11")] == 1
    assert counts[("document", "memory/people/mei-lin.md")] == 1


def test_a_question_longer_than_the_key_allows_is_bounded_and_says_so():
    long = "为什么" * 500
    bounded = bounded_question(long)
    assert len(bounded) == QUESTION_CHARS and bounded.endswith("…")
    assert bounded_question("  多行\n  问题  ") == "多行 问题"


# ---------------------------------------------------------------------------- last seen


def test_a_days_row_carries_the_instant_of_the_latest_record_that_touched_it():
    """`last_seen` is what makes exact last-access a column on a row that was going to be
    written anyway, instead of a second table restating it."""
    early = _record(consultation_id="k-1", created_at=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
                    evidence_handed=(EvidenceRef("claim", "c:aa11", ""),))
    late = _record(consultation_id="k-2", created_at=datetime(2026, 8, 31, 17, 30, tzinfo=timezone.utc),
                   evidence_handed=(EvidenceRef("claim", "c:aa11", ""),))
    hits, _ = ledger_rows([late, early])
    [row] = hits
    assert row["hits"] == 2
    assert row["last_seen"] == datetime(2026, 8, 31, 17, 30, tzinfo=timezone.utc)


def test_a_naive_timestamp_is_read_as_utc_rather_than_guessed_at():
    hits, _ = ledger_rows(
        [
            _record(
                created_at=datetime(2026, 8, 31, 23, 30),
                evidence_handed=(EvidenceRef("claim", "c:aa11", ""),),
            )
        ]
    )
    assert hits[0]["day"] == TODAY
    assert hits[0]["last_seen"].tzinfo is timezone.utc


def test_only_business_records_reach_the_ledger():
    audit = _record(visitor_class="audit", evidence_handed=(EvidenceRef("claim", "c:aa11", ""),))
    assert ledger_rows([audit]) == ([], [])


def test_a_miss_is_kept_verbatim_and_counted_per_day():
    hits, misses = ledger_rows(
        [
            _record(consultation_id="k-1", miss=True),
            _record(consultation_id="k-2", miss=True),
        ]
    )
    assert hits == []
    assert misses == [
        {"day": TODAY, "question": "阿宝上个季度盯的是哪条线？", "count": 2}
    ]


# ------------------------------------------------------------------------- the read face


def _row(day: date, hits: int, *, seen: datetime | None = None) -> dict:
    return {
        "target_kind": "document",
        "target_ref": "memory/topics/pricing.md",
        "day": day,
        "hits": hits,
        "last_seen": seen or datetime.combine(day, datetime.min.time(), timezone.utc),
    }


def test_the_windows_are_closed_whole_days_and_today_counts():
    rows = [_row(TODAY - timedelta(days=n), 1) for n in (0, 6, 7, 29, 30)]
    out = summarize(rows, now=TODAY, half_life_days=14)
    assert out["hits_7d"] == 2  # today and six days back
    assert out["hits_30d"] == 4  # …through twenty-nine days back
    assert out["heat"] > 0


def test_a_target_read_long_ago_still_has_a_last_access_and_no_recent_hits():
    """The one wrong answer this shape could give: reading `last_accessed_at` out of the
    window would report a page read forty-five days ago as never read at all."""
    out = summarize([_row(TODAY - timedelta(days=45), 3)], now=TODAY, half_life_days=14)
    assert out["hits_7d"] == 0 and out["hits_30d"] == 0
    assert out["last_accessed_at"] == datetime(2026, 7, 17, tzinfo=timezone.utc)


def test_a_target_nobody_has_read_answers_with_zeros_rather_than_absence():
    out = summarize([], now=TODAY, half_life_days=14)
    assert out == {"last_accessed_at": None, "hits_7d": 0, "hits_30d": 0, "heat": 0.0}


class _ReadStore:
    def __init__(self, rows) -> None:
        self._rows = rows
        self.asked: list = []

    async def access_rows_for(self, user_id, pairs):
        self.asked.append((str(user_id), list(pairs)))
        wanted = {(k, r) for k, r in pairs}
        return [r for r in self._rows if (r["target_kind"], r["target_ref"]) in wanted]


async def test_the_read_face_answers_a_page_of_targets_in_one_query():
    store = _ReadStore([_row(TODAY, 4)])
    out = await access_stats(
        store,
        UserId("u-lynx-1"),
        [("document", "memory/topics/pricing.md"), ("claim", "c:ffff")],
        now=TODAY,
    )
    assert len(store.asked) == 1
    assert out[("document", "memory/topics/pricing.md")]["hits_7d"] == 4
    assert out[("claim", "c:ffff")]["last_accessed_at"] is None


# --------------------------------------------------------------- the write path and job


class _StatsStore:
    """The store face the projection job and the replay use, in memory."""

    def __init__(self, records=()) -> None:
        self.records = {r.consultation_id: r for r in records}
        self.projected: set[str] = set()
        self.hits: list[dict] = []
        self.misses: list[dict] = []
        self.swaps = 0
        self.completed: list[tuple] = []

    async def get_consultation(self, user_id, consultation_id):
        return self.records.get(consultation_id)

    async def apply_access_stats(self, user_id, consultation_id, hits, misses):
        if consultation_id in self.projected:
            return False
        self.projected.add(consultation_id)
        self.hits.extend(hits)
        self.misses.extend(misses)
        return True

    async def replace_access_stats(self, user_id, hits, misses):
        self.swaps += 1
        self.hits = list(hits)
        self.misses = list(misses)
        return len(hits) + len(misses)

    async def list_consultations(
        self, user_id, *, visitor_class=None, projected=None, after=None, limit=500
    ):
        rows = sorted(
            (
                r
                for r in self.records.values()
                if (visitor_class is None or r.visitor_class == visitor_class)
                # `self.projected` is this fake's `projected_at`: stamped or not.
                and (
                    projected is None
                    or (r.consultation_id in self.projected) is bool(projected)
                )
            ),
            key=lambda r: (r.created_at, r.consultation_id),
        )
        if after is not None:
            rows = [r for r in rows if (r.created_at, r.consultation_id) > after]
        return rows[:limit]

    async def complete(
        self, user_id, job_id, *, ok=True, detail=None, snapshot_ref=None, token_usage=None
    ):
        self.completed.append((job_id, ok, detail))


class _Watcher:
    name = "test-watcher"

    def __init__(self) -> None:
        self.seen: list = []

    async def on_recall(self, user_id, record) -> None:  # noqa: ANN001
        self.seen.append((user_id, record.consultation_id))


class _Raiser:
    name = "test-raiser"

    async def on_recall(self, user_id, record) -> None:  # noqa: ANN001
        raise RuntimeError("this component is having a day")


def _job(consultation_id: str, job_id: str = "j-1"):
    return SimpleNamespace(
        job_id=job_id, kind="recall_projection", payload={"consultation_id": consultation_id}
    )


async def test_the_job_applies_the_stats_and_then_tells_the_components():
    record = _record(evidence_handed=(EvidenceRef("claim", "c:aa11", "memory/x.md"),))
    store = _StatsStore([record])
    reset_components()
    watcher = _Watcher()
    register_component(watcher)
    try:
        await run_recall_projection_job(
            SimpleNamespace(store=store), UserId("u-lynx-1"), _job("k-1")
        )
    finally:
        reset_components()

    assert {(r["target_kind"], r["target_ref"]) for r in store.hits} == {
        ("claim", "c:aa11"),
        ("document", "memory/x.md"),
    }
    assert watcher.seen == [("u-lynx-1", "k-1")]
    assert store.completed == [("j-1", True, "projected")]


async def test_the_same_job_run_twice_is_a_no_op():
    """The `projected_at` stamp, seen from above it: a worker killed mid-job and a queue
    self-heal on restart both replay this job, and a ledger that counted twice would be a
    ledger nothing could reproduce from the records."""
    record = _record(evidence_handed=(EvidenceRef("claim", "c:aa11", ""),))
    store = _StatsStore([record])
    reset_components()
    watcher = _Watcher()
    register_component(watcher)
    try:
        for job_id in ("j-1", "j-2"):
            await run_recall_projection_job(
                SimpleNamespace(store=store), UserId("u-lynx-1"), _job("k-1", job_id)
            )
    finally:
        reset_components()

    assert len(store.hits) == 1
    assert watcher.seen == [("u-lynx-1", "k-1")]
    assert store.completed[1] == ("j-2", True, "already projected")


async def test_a_component_that_raises_costs_a_warning_and_never_the_job():
    record = _record(evidence_handed=(EvidenceRef("claim", "c:aa11", ""),))
    store = _StatsStore([record])
    reset_components()
    register_component(_Raiser())
    watcher = _Watcher()
    register_component(watcher)
    try:
        await run_recall_projection_job(
            SimpleNamespace(store=store), UserId("u-lynx-1"), _job("k-1")
        )
    finally:
        reset_components()

    assert store.completed == [("j-1", True, "projected")]
    assert len(store.hits) == 1
    # the fan-out carries on past the one that raised
    assert watcher.seen == [("u-lynx-1", "k-1")]


async def test_a_job_naming_a_consultation_that_is_gone_finishes_rather_than_looping():
    store = _StatsStore([])
    await run_recall_projection_job(
        SimpleNamespace(store=store), UserId("u-lynx-1"), _job("k-missing")
    )
    assert store.completed == [("j-1", True, "consultation gone")]


async def test_the_stats_are_applied_with_no_component_registered_at_all():
    """Default-on: the built-in consumer is the framework's, not a component's."""
    record = _record(evidence_handed=(EvidenceRef("claim", "c:aa11", ""),))
    store = _StatsStore([record])
    reset_components()
    await run_recall_projection_job(
        SimpleNamespace(store=store), UserId("u-lynx-1"), _job("k-1")
    )
    assert len(store.hits) == 1


async def test_the_replay_reproduces_the_ledger_and_leaves_the_stamps_alone():
    records = [
        _record(
            consultation_id="k-1",
            created_at=datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc),
            evidence_handed=(EvidenceRef("claim", "c:aa11", ""),),
        ),
        _record(
            consultation_id="k-2",
            created_at=NOON,
            evidence_handed=(EvidenceRef("claim", "c:aa11", ""),),
            miss=True,
        ),
        _record(consultation_id="k-3", visitor_class="audit"),
    ]
    store = _StatsStore(records)
    for consultation_id in ("k-1", "k-2"):
        await apply_record(store, UserId("u-lynx-1"), store.records[consultation_id])
    live_hits, live_misses = list(store.hits), list(store.misses)

    replayed = await rebuild_access_stats(store, UserId("u-lynx-1"))

    assert replayed == 2  # the audit record is not a business one
    assert store.swaps == 1
    assert sorted(store.hits, key=lambda r: (r["day"], r["target_ref"])) == sorted(
        live_hits, key=lambda r: (r["day"], r["target_ref"])
    )
    assert store.misses == live_misses
    # the stamps survive: a rebuild is not permission to apply a record a second time
    assert store.projected == {"k-1", "k-2"}


async def test_a_record_that_arrives_mid_scan_is_left_for_its_own_job_and_counted_once():
    """The double-count the replay used to walk into.

    API writes stay live while a rebuild runs. A consultation inserted before the scan
    cursor passed it was picked up by the replay AND still had its own `recall_projection`
    job queued, so the job applied it a second time on top of the swap. The replay now takes
    only records already stamped `projected_at`; the queue is what makes that sound — this
    rebuild holds the user's one in-flight claim, so no projection can land between the scan
    and the swap, and the excluded record is applied exactly once by its own job afterwards.
    """
    settled = _record(
        consultation_id="k-1", evidence_handed=(EvidenceRef("claim", "c:aa11", ""),)
    )
    arriving = _record(
        consultation_id="k-2",
        created_at=NOON,
        evidence_handed=(EvidenceRef("claim", "c:bb22", ""),),
    )
    store = _StatsStore([settled])
    await apply_record(store, UserId("u-lynx-1"), settled)

    # The insert happens mid-walk: the first page is served, and the row lands behind it
    # with `projected_at` null and a projection job of its own waiting in the queue.
    served = 0
    plain_list = store.list_consultations

    async def listing(*args, **kwargs):
        nonlocal served
        page = await plain_list(*args, **kwargs)
        served += 1
        if served == 1:
            store.records[arriving.consultation_id] = arriving
        return page

    store.list_consultations = listing

    replayed = await rebuild_access_stats(store, UserId("u-lynx-1"))

    assert replayed == 1  # only the settled record; the arriving one is not the replay's
    assert [(r["target_ref"], r["hits"]) for r in store.hits] == [("c:aa11", 1)]

    # …and its own job then applies it, once.
    store.list_consultations = plain_list
    await run_recall_projection_job(
        SimpleNamespace(store=store), UserId("u-lynx-1"), _job("k-2", "j-2")
    )
    assert sorted((r["target_ref"], r["hits"]) for r in store.hits) == [
        ("c:aa11", 1),
        ("c:bb22", 1),
    ]


class _PagedStore:
    """A store that manufactures each page on demand and keeps only WEAK references to it.

    Whether the replay retains what it read is then a question the garbage collector
    answers, sampled at the one moment it can be asked honestly: at the top of the next
    page's call, when the caller has finished with the page before it.
    """

    PER_PAGE = 3

    def __init__(self, pages: int) -> None:
        self.total = pages * self.PER_PAGE
        self.alive: list[weakref.ref] = []
        self.live_before_each_page: list[int] = []
        self.hits: list[dict] = []
        self.misses: list[dict] = []

    def _record_at(self, index: int) -> ConsultationRecord:
        return _record(
            consultation_id=f"k-{index:04d}",
            created_at=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
            + timedelta(seconds=index),
            # A real record carries its whole answer and evidence manifest; the ledger
            # keeps one summed row per (target, day) whatever the volume behind it.
            answer="供应商把交期从两周缩短到五天。" * 40,
            evidence_handed=(EvidenceRef("claim", "c:aa11", ""),),
        )

    async def list_consultations(
        self, user_id, *, visitor_class=None, projected=None, after=None, limit=500
    ):
        gc.collect()
        self.live_before_each_page.append(sum(1 for r in self.alive if r() is not None))
        start = 0 if after is None else int(str(after[1]).split("-")[1]) + 1
        page = [
            self._record_at(i) for i in range(start, min(start + limit, self.total))
        ]
        self.alive.extend(weakref.ref(item) for item in page)
        return page

    async def replace_access_stats(self, user_id, hits, misses):
        self.hits, self.misses = list(hits), list(misses)
        return len(hits) + len(misses)


async def test_the_replay_folds_each_page_and_holds_on_to_none_of_it(monkeypatch):
    """The page bound was on the READ and not on what was kept: every page was appended to
    one list, so rebuilding a heavily-used tenant held every answer and every evidence
    manifest in memory at once. The rows are a summation — bounded by the library's distinct
    targets — so a page is folded in and dropped."""
    monkeypatch.setattr("pneuma_knowledge_service.access_stats.REPLAY_PAGE", 3)
    store = _PagedStore(pages=5)

    replayed = await rebuild_access_stats(store, UserId("u-lynx-1"))

    assert replayed == store.total == 15
    assert [(r["target_ref"], r["hits"]) for r in store.hits] == [("c:aa11", 15)]
    # Never more than one page's worth of records alive at once.
    assert max(store.live_before_each_page) <= _PagedStore.PER_PAGE


# --------------------------------------------------------------- whose queue is swept


class _SweepStore:
    def __init__(self, users, consultation_users=None) -> None:
        self._users = list(users)
        self._consultation_users = consultation_users

    async def list_users(self):
        return list(self._users)

    def __getattr__(self, name):
        if name == "list_consultation_users" and self._consultation_users is not None:
            async def lister():
                return list(self._consultation_users)

            return lister
        raise AttributeError(name)


async def test_the_sweep_reaches_a_tenant_that_has_only_ever_asked():
    """A `recall_projection` job is enqueued with the consultation row, and a tenant can ask
    business questions before importing anything. Swept from `sources` alone, that tenant's
    jobs sat queued forever with nothing in the system able to notice."""
    from pneuma_knowledge_service.workers.compile_worker import _users_with_jobs

    ctx = SimpleNamespace(store=_SweepStore(["u-bao"], ["u-mei", "u-bao"]))
    assert await _users_with_jobs(ctx) == ["u-bao", "u-mei"]


async def test_a_store_without_the_consultation_listing_still_sweeps():
    """The listing is optional on the port, so an adapter that predates it degrades to the
    old answer rather than failing the worker's whole sweep."""
    from pneuma_knowledge_service.workers.compile_worker import _users_with_jobs

    ctx = SimpleNamespace(store=_SweepStore(["u-bao"]))
    assert await _users_with_jobs(ctx) == ["u-bao"]


# ------------------------------------------------------------------------- the endpoint


async def test_the_endpoint_answers_for_one_target_under_the_callers_tenant():
    """I1-scoped like every other route: the user id in the path is the only tenant the
    query can reach, and a target nobody read is zeros rather than a 404."""
    from pneuma_knowledge_service.api.routes.v1 import get_access_stats

    # The route resolves "now" from the wall clock, so the row is dated by it too — a
    # fixture pinned to a literal date passes on the day it was written and no other.
    today = datetime.now(timezone.utc).date()
    store = _ReadStore([_row(today, 2)])
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                ctx=SimpleNamespace(
                    store=store,
                    settings=SimpleNamespace(attention_half_life_days=14),
                )
            )
        )
    )

    out = await get_access_stats(
        "u-mei", request, kind="document", ref="memory/topics/pricing.md"
    )
    assert store.asked == [("u-mei", [("document", "memory/topics/pricing.md")])]
    assert (out.kind, out.ref) == ("document", "memory/topics/pricing.md")
    assert out.hits_7d == 2 and out.hits_30d == 2 and out.heat == 2.0

    cold = await get_access_stats("u-mei", request, kind="claim", ref="c:ffff")
    assert cold.last_accessed_at is None and cold.hits_30d == 0


# ------------------------------------------------------- the dashboard's two top lists


def _hit(kind: str, ref: str, day: date, hits: int) -> dict:
    return {
        "target_kind": kind,
        "target_ref": ref,
        "day": day,
        "hits": hits,
        "last_seen": datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc),
    }


def test_the_top_list_ranks_on_its_window_and_reports_on_the_read_faces_windows():
    """Two windows, and they are not the same window.

    `heat` RANKS over the period the caller asked about; `hits_7d` / `hits_30d` /
    `last_accessed_at` REPORT the read face's own fixed windows over every row handed in, so
    a document reads the same on a dashboard as on `GET /access-stats`. A page read heavily
    three weeks ago and not since is therefore outranked in a 7-day window by one read once
    yesterday, and still shows its real 30-day count.
    """
    rows = [
        _hit("document", "memory/topics/pricing.md", TODAY - timedelta(days=1), 1),
        _hit("document", "memory/people/bao.md", TODAY - timedelta(days=20), 9),
        _hit("document", "memory/people/bao.md", TODAY - timedelta(days=2), 1),
        _hit("claim", "c:aa11", TODAY, 40),
    ]
    top = top_targets(
        rows, kind="document", now=TODAY, half_life_days=14, window_days=7, limit=10
    )
    assert [item["ref"] for item in top] == [
        "memory/topics/pricing.md",
        "memory/people/bao.md",
    ]
    # bao's 30-day count keeps the twenty-day-old reads the ranking window did not weigh —
    # ten hits reported, and a heat worth the single recent one that put it in the window.
    bao = top[1]
    assert bao["hits_30d"] == 10 and bao["hits_7d"] == 1
    assert bao["heat"] < 1.0
    assert bao["last_accessed_at"].date() == TODAY - timedelta(days=2)
    # A claim row is not a document, whatever else it is.
    assert all(item["ref"].endswith(".md") for item in top)


def test_a_target_with_nothing_in_the_window_is_dropped_rather_than_ranked_at_zero():
    """A top list padded with cold entries is a list about the library's SIZE. The rows are
    there — the read face will still report them for that page — but the ranking is about
    what has been read in the period, and nothing was."""
    rows = [_hit("document", "memory/people/bao.md", TODAY - timedelta(days=20), 9)]
    assert top_targets(
        rows, kind="document", now=TODAY, half_life_days=14, window_days=7, limit=10
    ) == []
    assert len(
        top_targets(
            rows, kind="document", now=TODAY, half_life_days=14, window_days=30, limit=10
        )
    ) == 1


def test_misses_sum_across_days_and_keep_the_last_day_they_were_asked():
    """The same question asked on two days is one question asked twice — the table is keyed
    by day, and a reader counting what the library could not answer means the question."""
    rows = [
        {"day": TODAY - timedelta(days=3), "question": "第二批验收谁签的？", "count": 1},
        {"day": TODAY, "question": "第二批验收谁签的？", "count": 2},
        {"day": TODAY - timedelta(days=1), "question": "momo 的合同到期了吗？", "count": 2},
        {"day": TODAY, "question": "", "count": 5},
    ]
    out = top_misses(rows, limit=10)
    assert [item["question"] for item in out] == [
        "第二批验收谁签的？",
        "momo 的合同到期了吗？",
    ]
    assert out[0]["count"] == 3 and out[0]["last_day"] == TODAY
    assert out[1]["last_day"] == TODAY - timedelta(days=1)
    assert len(top_misses(rows, limit=1)) == 1
