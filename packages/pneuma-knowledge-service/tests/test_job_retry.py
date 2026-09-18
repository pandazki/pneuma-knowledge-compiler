"""One treatment for every failure: wait, and say why. And the one enumerated exception.

The rule these pin (`job_retry.py`) is the Owner's: anything that is not PROVABLY hopeless —
a provider with no money on the card, a harness that fell over, a network that blinked, a
library nobody has committed yet — puts the job back to `queued` behind a wait, on its own
row, with the reason written where a person reads it. Nothing is struck out and the service
never stops. A failure that a retry cannot fix is terminal, and there is one list of those.

The agent-round half of the same rule is in `test_agent_round.py` and `test_round_honesty.py`;
what is here is the rest of the queue — an index job, an unknown kind — and the two faces that
tell an Owner what their library is waiting for.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.draft_mock import InMemoryJobQueue
from pneuma_knowledge_service.adapters.read_mock import InMemoryLibraryStore
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.job_retry import (
    PAUSED_STATUS,
    RETRY_BACKOFF_S,
    TERMINAL_FAILURES,
    TerminalJobFailure,
    humanize_span,
    park,
    paused_detail,
    paused_reason,
    retry_backoff,
    waiting_detail,
    waiting_reason,
    waiting_reasons,
)
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import executor_for
from pneuma_knowledge_service.workers import compile_worker

USER = UserId("u-wait")


def _settings(**kwargs) -> Settings:
    base = {
        "llm_model": "openrouter:x/base",
        "llm_model_compile": "openrouter:x/compile",
        "llm_model_evolve": "openrouter:x/evolve",
        "llm_model_challenge": "openrouter:x/challenge",
        "llm_model_brief": "openrouter:x/brief",
    }
    return Settings(_env_file=None, **{**base, **kwargs})


class Ctx:
    """The little of an `AppContext` a drain reads to run and end a job."""

    def __init__(self, store) -> None:  # noqa: ANN001
        self.settings = _settings()
        self.store = store

    @property
    def compile_executor(self):
        return executor_for(self.settings, "compile")

    async def flush_traces(self) -> None:
        return None


def _row(rows: list[dict], job_id: str) -> dict:
    return next(r for r in rows if r["job_id"] == job_id)


# ───────────────────────────────────────────────────────────────── the schedule itself


def test_the_wait_grows_on_one_named_schedule_and_then_stays_at_its_last_step():
    """Six steps and a ceiling that is the last of them: a minute for the blip, a day for the
    card that expired. There is no ceiling knob because the last element IS the ceiling."""
    assert [retry_backoff(n) for n in range(1, 8)] == [*RETRY_BACKOFF_S, RETRY_BACKOFF_S[-1]]
    assert retry_backoff(1) == 60 and retry_backoff(999) == 24 * 3600


def test_a_reason_survives_the_round_trip_through_the_row_it_is_written_on():
    """The summary groups on the reason phrase, so the phrase has to come back out of the
    detail unchanged — including a reason that carries its own semicolons."""
    said = "round_incomplete: timed out; nothing was committed"
    when = datetime(2026, 9, 15, 14, 5, tzinfo=timezone.utc)
    assert waiting_reason(waiting_detail(said, when, 3)) == said
    assert waiting_detail(said, when, 3).endswith("(attempt 3)")
    # A row that is not a parked row says nothing rather than guessing.
    assert waiting_reason("projection:{}; rounds:1") == ""
    assert waiting_reason(None) == ""


async def test_a_park_keeps_the_row_counts_the_attempt_and_keeps_the_last_ten_failures():
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, "index", {"source_id": "src-01"})
    for attempt in range(1, 13):
        job = await jobs.get_job(USER, job_id)
        await park(jobs, USER, job_id, payload=dict(job.payload), reason=f"failure {attempt}")

    job = await jobs.get_job(USER, job_id)
    retry = job.payload["retry"]
    assert retry["attempts"] == 12
    assert retry["last_failure"]["detail"] == "failure 12"
    assert len(retry["history"]) == 10, "the payload grew a log"
    assert [entry["detail"] for entry in retry["history"]] == [
        f"failure {n}" for n in range(3, 13)
    ]
    assert job.payload["source_id"] == "src-01", "the work itself was rewritten"


async def test_a_provider_that_names_an_hour_is_waited_for_until_that_hour():
    """A stated deadline is a fact and the schedule is a guess; the fact wins. A deadline
    that has already passed is not a fact about the future, so the schedule takes it back."""
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, "compile", {"source_ids": ["src-01"]})
    stated = datetime.now(timezone.utc) + timedelta(hours=9)
    parked = await park(
        jobs, USER, job_id, payload={}, reason="codex usage limit", not_before=stated
    )
    assert parked.not_before == stated
    assert (await jobs.get_job(USER, job_id)).not_before == stated
    assert await jobs.claim_next(USER) is None, "a job that is waiting was handed out"

    past = datetime.now(timezone.utc) - timedelta(hours=1)
    job = await jobs.get_job(USER, job_id)
    parked = await park(
        jobs, USER, job_id, payload=dict(job.payload), reason="codex usage limit",
        not_before=past,
    )
    assert parked.attempts == 2
    assert round((parked.not_before - datetime.now(timezone.utc)).total_seconds()) == (
        RETRY_BACKOFF_S[1]
    )


# ─────────────────────────────────────────── the rest of the queue, through the real drain


def _index_body(monkeypatch, fail):  # noqa: ANN001
    runs: list[str] = []

    async def body(ctx, user_id, job):  # noqa: ANN001
        runs.append(job.job_id)
        exc = fail(job, runs.count(job.job_id))
        if exc is not None:
            raise exc
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="indexed")

    monkeypatch.setattr(compile_worker, "process_index_job", body)
    return runs


class PaymentRequired(Exception):
    """What an embedding client raises when the card behind the key has no money on it.

    Not an outage — the provider answered, and it answered about the account — and not a
    defect of the job either. It is exactly the shape the Owner's ruling is about: the same
    job succeeds the moment somebody tops the account up, and nothing about the queue should
    have to be repaired by hand when they do.
    """


async def test_a_payment_refusal_on_an_index_job_waits_instead_of_failing(monkeypatch):
    jobs = InMemoryJobQueue()
    first = await jobs.enqueue(USER, "index", {"source_id": "src-01"})
    second = await jobs.enqueue(USER, "index", {"source_id": "src-02"})
    said = "Error code: 402 - {'error': {'message': 'Insufficient credits'}}"
    runs = _index_body(
        monkeypatch,
        fail=lambda job, attempt: PaymentRequired(said) if job.job_id == first else None,
    )
    before = datetime.now(timezone.utc)

    processed = await compile_worker.drain_user(Ctx(jobs), None, SimpleNamespace(), USER)

    assert processed == 2 and runs.count(first) == 1
    # The second job ran: one account's refusal does not stop the library.
    assert [r["job_id"] for r in jobs.completed] == [second]
    row = _row(await jobs.list_jobs(USER), first)
    assert row["status"] == "queued"
    assert row["detail"] == (
        f"waiting: worker error: {said}; retry at {row['not_before'].isoformat()} (attempt 1)"
    )
    assert round((row["not_before"] - before).total_seconds()) == RETRY_BACKOFF_S[0]
    assert await jobs.claim_next(USER) is None, "a job that is waiting was handed out"


async def test_a_second_failure_waits_longer_and_carries_both_attempts(monkeypatch):
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, "index", {"source_id": "src-01"})
    _index_body(monkeypatch, fail=lambda job, attempt: PaymentRequired("402 payment required"))
    ctx = Ctx(jobs)

    waits = []
    for _ in range(2):
        job = await jobs.get_job(USER, job_id)
        job.not_before = None  # the wait has passed
        before = datetime.now(timezone.utc)
        await compile_worker.drain_user(ctx, None, SimpleNamespace(), USER)
        row = _row(await jobs.list_jobs(USER), job_id)
        waits.append(round((row["not_before"] - before).total_seconds()))

    assert waits == [RETRY_BACKOFF_S[0], RETRY_BACKOFF_S[1]] == [60, 300]
    row = _row(await jobs.list_jobs(USER), job_id)
    assert row["detail"].endswith("(attempt 2)")
    assert len(row["payload"]["retry"]["history"]) == 2
    assert jobs.completed == [], "a job that could still run was ended"


async def test_a_kind_no_body_in_this_build_runs_is_terminal(monkeypatch, caplog):
    """The one thing a wait cannot fix by itself: there is nothing here to run this row, and
    the next attempt dispatches to the same nothing. What has to change is the build.

    It used to fall through to the compile dispatch, which compiled the sources of a row that
    meant something else entirely."""
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, "sync-to-notion", {"source_ids": ["src-01"]})

    with caplog.at_level("WARNING"):
        await compile_worker.drain_user(Ctx(jobs), None, SimpleNamespace(), USER)

    done = jobs.completed[-1]
    assert done["job_id"] == job_id and done["ok"] is False
    assert done["detail"] == "unknown_kind: no body in this worker runs a 'sync-to-notion' job"
    assert [r["status"] for r in await jobs.list_jobs(USER)] == ["done"]
    assert any("will not come back" in r.getMessage() for r in caplog.records)


def test_every_terminal_code_says_why_waiting_cannot_help():
    """The enumeration is the whole exception to the rule, so it is readable in one place and
    a code nobody wrote a reason for cannot be raised."""
    assert set(TERMINAL_FAILURES) == {
        "unknown_kind", "payload_invalid", "source_gone", "input_too_large", "proposal_stale",
    }
    assert all(why.strip() for why in TERMINAL_FAILURES.values())
    with pytest.raises(ValueError, match="not an enumerated terminal failure"):
        TerminalJobFailure("just_because")
    assert TerminalJobFailure("source_gone", "src-01 is gone").detail == (
        "source_gone: src-01 is gone"
    )


# ───────────────────────────────────────────────────────── what the Owner is shown


def test_the_reasons_are_grouped_biggest_first_each_with_its_soonest_retry():
    now = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)
    rows = [
        (waiting_detail("codex provider refused", now + timedelta(minutes=52), 2), now + timedelta(minutes=52)),
        (waiting_detail("402 payment required", now + timedelta(hours=1, minutes=5), 1), now + timedelta(hours=1, minutes=5)),
        (waiting_detail("402 payment required", now + timedelta(minutes=5), 3), now + timedelta(minutes=5)),
        (None, now + timedelta(minutes=30)),
    ]
    assert waiting_reasons(rows) == [
        {"reason": "402 payment required", "count": 2, "next_retry_at": now + timedelta(minutes=5)},
        {"reason": "codex provider refused", "count": 1, "next_retry_at": now + timedelta(minutes=52)},
        # A queued row somebody delayed for another purpose is counted under one honest name
        # rather than dropped: the summary's counts have to add up.
        {"reason": "held back", "count": 1, "next_retry_at": now + timedelta(minutes=30)},
    ]


async def test_the_summary_endpoint_counts_four_disjoint_states_and_names_the_waiting():
    """What a console and `pkchome status` both read. `queued` is what a claim could take
    right now and `waiting` is the rest, so the four add up and a face can print them side by
    side without knowing which contains which."""
    store = InMemoryLibraryStore()
    ready = await store.enqueue(USER, "index", {"source_id": "src-00"})
    running = await store.enqueue(USER, "compile", {"source_ids": ["src-01"]})
    assert await store.claim(USER, running) is not None
    finished = await store.enqueue(USER, "index", {"source_id": "src-02"})
    assert await store.claim(USER, finished) is not None
    await store.complete(USER, finished, ok=True, detail="indexed")
    for source in ("src-03", "src-04"):
        job_id = await store.enqueue(USER, "index", {"source_id": source})
        await park(store, USER, job_id, payload={}, reason="402 payment required")
    lonely = await store.enqueue(USER, "index", {"source_id": "src-05"})
    await park(store, USER, lonely, payload={}, reason="codex provider refused")

    config = _settings()
    app = create_app()
    app.state.ctx = SimpleNamespace(
        store=store, settings=config, compile_executor=executor_for(config, "compile")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/users/{USER}/jobs/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["queued"] == 1 and body["claimed"] == 1
    assert body["failed"] == 0 and body["succeeded"] == 1
    assert body["waiting"]["count"] == 3
    assert [(r["reason"], r["count"]) for r in body["waiting"]["reasons"]] == [
        ("402 payment required", 2),
        ("codex provider refused", 1),
    ]
    assert all(r["next_retry_at"] for r in body["waiting"]["reasons"])
    assert ready in {r["job_id"] for r in await store.list_jobs(USER)}


async def test_pkc_jobs_says_the_same_thing_under_its_rows(capsys):
    """One grouping, two faces: the CLI must not be able to disagree with the console about
    what a library is waiting for."""
    from pneuma_knowledge_service.cli import read as read_cmd

    store = InMemoryLibraryStore()
    for source in ("src-01", "src-02"):
        job_id = await store.enqueue(USER, "index", {"source_id": source})
        await park(store, USER, job_id, payload={}, reason="402 payment required")

    rt = read_cmd.ReadRuntime(user_id=USER, ctx=SimpleNamespace(store=store), as_json=False)
    assert await read_cmd.cmd_jobs(rt) == read_cmd.EXIT_OK
    printed = capsys.readouterr().out
    assert "waiting: 2 · 402 payment required ×2 (next " in printed

    rt = read_cmd.ReadRuntime(user_id=USER, ctx=SimpleNamespace(store=store), as_json=True)
    assert await read_cmd.cmd_jobs(rt) == read_cmd.EXIT_OK
    import json

    body = json.loads(capsys.readouterr().out)
    assert body["waiting"]["count"] == 2
    assert body["waiting"]["reasons"][0]["reason"] == "402 payment required"
    assert body["waiting"]["reasons"][0]["next_retry_at"]


# ───────────────────────────────────── the end of the schedule is a pause, not a verdict


async def _fail(jobs, job_id: str, reason: str) -> object:  # noqa: ANN001
    """One failure of one job, with whatever wait it already had already passed."""
    job = await jobs.get_job(USER, job_id)
    job.not_before = None
    return await park(jobs, USER, job_id, payload=dict(job.payload), reason=reason)


async def test_the_seventh_failure_pauses_the_job_instead_of_asking_again():
    """Six attempts across a day and a half say what they are going to say. A seventh does
    not change the account balance, the harness's login or the state of the working tree —
    what changes those is a person, so the row stops and asks for one."""
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, "index", {"source_id": "src-01"})
    said = "worker error: 402 payment required"

    for attempt in range(1, len(RETRY_BACKOFF_S) + 1):
        parked = await _fail(jobs, job_id, said)
        assert parked.paused is False and parked.attempts == attempt
        assert (await jobs.get_job(USER, job_id)).status == "queued"

    parked = await _fail(jobs, job_id, said)
    assert parked.paused is True and parked.attempts == len(RETRY_BACKOFF_S) + 1
    assert parked.not_before is None
    job = await jobs.get_job(USER, job_id)
    assert job.status == PAUSED_STATUS
    assert job.not_before is None, "a paused job was given a clock to wait on"
    assert job.detail == parked.detail
    assert job.detail.startswith(f"paused: {said}; 7 attempts over ")
    assert job.detail.endswith("; resume with pkc jobs resume")
    assert job.payload["retry"]["attempts"] == 7
    assert len(job.payload["retry"]["history"]) == 7, "the history was thrown away"
    assert job.payload["source_id"] == "src-01", "the work itself was rewritten"


async def test_nothing_in_this_process_ever_picks_a_paused_job_up():
    """Neither the claim nor the self-heal, and neither of them has to know the word: the
    claim takes `queued` rows and the self-heal requeues `claimed` ones."""
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, "index", {"source_id": "src-01"})
    ready = await jobs.enqueue(USER, "index", {"source_id": "src-02"})
    for _ in range(len(RETRY_BACKOFF_S) + 1):
        await _fail(jobs, job_id, "worker error: 402 payment required")

    assert (await jobs.claim_next(USER)).job_id == ready, "a paused job was handed out"
    await jobs.complete(USER, ready, ok=True)
    assert await jobs.claim_next(USER) is None
    assert await jobs.claim(USER, job_id) is None, "a paused job was claimed by name"
    assert await jobs.requeue_claimed_jobs(draft_ttl=0) == 0
    assert (await jobs.get_job(USER, job_id)).status == PAUSED_STATUS


async def test_a_resume_starts_the_schedule_over_and_keeps_what_already_happened():
    """A person who resumes has CHANGED something — topped the account up, logged the harness
    in — so the next failure waits a minute, not the day the exhausted schedule ended on.
    What already happened to the job is not undone by resuming it: the history stays."""
    jobs = InMemoryJobQueue()
    job_id = await jobs.enqueue(USER, "index", {"source_id": "src-01"})
    for _ in range(len(RETRY_BACKOFF_S) + 1):
        await _fail(jobs, job_id, "worker error: 402 payment required")

    assert await jobs.resume_jobs(USER, job_id=job_id) == 1
    job = await jobs.get_job(USER, job_id)
    assert job.status == "queued" and job.not_before is None
    assert job.payload["retry"]["attempts"] == 0
    assert len(job.payload["retry"]["history"]) == 7, "the history was cleared by a resume"
    assert job.detail == "resumed after 7 attempts", "the row forgot what it had been through"
    assert (await jobs.claim_next(USER)).job_id == job_id, "a resumed job was not claimable"

    # …and the very next failure starts at the first step of the schedule again.
    before = datetime.now(timezone.utc)
    parked = await _fail(jobs, job_id, "worker error: 402 payment required")
    assert parked.paused is False and parked.attempts == 1
    assert round((parked.not_before - before).total_seconds()) == RETRY_BACKOFF_S[0] == 60


async def test_a_resume_selects_by_job_by_reason_or_all_and_refuses_an_empty_request():
    jobs = InMemoryJobQueue()
    ids = {}
    for source, reason in (("src-01", "402 payment required"),
                           ("src-02", "402 payment required"),
                           ("src-03", "codex provider refused")):
        job_id = await jobs.enqueue(USER, "index", {"source_id": source})
        for _ in range(len(RETRY_BACKOFF_S) + 1):
            await _fail(jobs, job_id, reason)
        ids[source] = job_id

    # Nothing stated changes nothing: a whole library's paused work is not restarted by an
    # empty request.
    async def statuses() -> list[str]:
        return [(await jobs.get_job(USER, j)).status for j in ids.values()]

    assert await jobs.resume_jobs(USER) == 0
    assert await statuses() == [PAUSED_STATUS] * 3

    assert await jobs.resume_jobs(USER, job_id=ids["src-03"]) == 1
    assert (await jobs.get_job(USER, ids["src-03"])).status == "queued"

    assert await jobs.resume_jobs(USER, reason_like="PAYMENT") == 2, "the match read a case"
    assert await statuses() == ["queued"] * 3

    # And `every` over a library with nothing paused resumes nothing rather than raising.
    assert await jobs.resume_jobs(USER, every=True) == 0


async def test_a_paused_reason_survives_the_row_it_is_written_on():
    said = "round_incomplete: timed out; nothing was committed"
    detail = paused_detail(said, 7, 31 * 3600)
    assert paused_reason(detail) == said
    assert detail.endswith("; 7 attempts over 1d 7h; resume with pkc jobs resume")
    assert paused_reason(waiting_detail(said, datetime.now(timezone.utc), 2)) == ""
    assert paused_reason(None) == ""


def test_the_span_a_paused_row_reports_is_coarse_and_readable():
    assert humanize_span(0) == "<1m"
    assert humanize_span(45) == "<1m"
    assert humanize_span(90 * 60) == "1h 30m"
    assert humanize_span(2 * 3600) == "2h"
    assert humanize_span(30 * 3600) == "1d 6h"
    assert humanize_span(2 * 86400) == "2d"


async def test_the_summary_names_the_paused_jobs_beside_the_waiting_ones():
    """Five disjoint counts. A paused job is not queued, not waiting and not failed — it is
    its own state, because the answer to it is a person rather than a clock."""
    store = InMemoryLibraryStore()
    ready = await store.enqueue(USER, "index", {"source_id": "src-00"})
    waiting_id = await store.enqueue(USER, "index", {"source_id": "src-01"})
    await park(store, USER, waiting_id, payload={}, reason="codex at capacity")
    for source in ("src-02", "src-03"):
        job_id = await store.enqueue(USER, "index", {"source_id": source})
        for _ in range(len(RETRY_BACKOFF_S) + 1):
            await _fail(store, job_id, "402 payment required")

    config = _settings()
    app = create_app()
    app.state.ctx = SimpleNamespace(
        store=store, settings=config, compile_executor=executor_for(config, "compile")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = (await client.get(f"/v1/users/{USER}/jobs/summary")).json()
        empty = await client.post(f"/v1/users/{USER}/jobs/resume", json={})
        resumed = await client.post(
            f"/v1/users/{USER}/jobs/resume", json={"reason_like": "payment"}
        )

    assert body["queued"] == 1 and body["waiting"]["count"] == 1
    assert body["paused"]["count"] == 2
    (reason,) = body["paused"]["reasons"]
    assert (reason["reason"], reason["count"]) == ("402 payment required", 2)
    assert reason["since"], "a paused group could not say how long it had been sitting"

    # The route refuses an empty request and then resumes exactly what was asked for.
    assert empty.status_code == 422, empty.text
    assert resumed.status_code == 200 and resumed.json() == {"resumed": 2}
    assert (await store.job_summary(USER))["paused"]["count"] == 0
    assert ready in {r["job_id"] for r in await store.list_jobs(USER)}


async def test_pkc_jobs_resume_selects_reports_and_refuses_without_a_selector(capsys):
    import io

    from pneuma_knowledge_service.cli import jobs as jobs_cmd

    store = InMemoryLibraryStore()
    job_id = await store.enqueue(USER, "index", {"source_id": "src-01"})
    for _ in range(len(RETRY_BACKOFF_S) + 1):
        await _fail(store, job_id, "402 payment required")

    err = io.StringIO()
    assert await jobs_cmd.cmd_jobs_resume(
        SimpleNamespace(store=store), USER, err=err
    ) == 2, "resume with no selector restarted a library's paused work"
    assert "resume needs a selector" in err.getvalue()

    out, err = io.StringIO(), io.StringIO()
    assert await jobs_cmd.cmd_jobs_resume(
        SimpleNamespace(store=store), USER, reason_like="nothing like this", err=err
    ) == 1
    assert "no paused job matches" in err.getvalue()

    out = io.StringIO()
    assert await jobs_cmd.cmd_jobs_resume(
        SimpleNamespace(store=store), USER, every=True, out=out
    ) == 0
    assert out.getvalue().strip() == "resumed 1 paused job"
    assert (await store.get_job(USER, job_id)).status == "queued"


async def test_pkc_jobs_puts_the_paused_rows_under_their_own_heading(capsys):
    """They are the only rows in the queue waiting for the READER, so they are not a count
    on a line — they get a heading, the ids on this page, and the command that ends them."""
    from pneuma_knowledge_service.cli import read as read_cmd

    store = InMemoryLibraryStore()
    job_id = await store.enqueue(USER, "index", {"source_id": "src-01"})
    for _ in range(len(RETRY_BACKOFF_S) + 1):
        await _fail(store, job_id, "402 payment required")

    rt = read_cmd.ReadRuntime(user_id=USER, ctx=SimpleNamespace(store=store), as_json=False)
    assert await read_cmd.cmd_jobs(rt) == read_cmd.EXIT_OK
    printed = capsys.readouterr().out
    assert "paused — waiting for you, not for a clock (1)" in printed
    assert "start them again with `pkc jobs resume`" in printed
    assert "402 payment required ×1 (since " in printed
    assert f"on this page: {job_id}" in printed

    rt = read_cmd.ReadRuntime(user_id=USER, ctx=SimpleNamespace(store=store), as_json=True)
    assert await read_cmd.cmd_jobs(rt) == read_cmd.EXIT_OK
    import json

    body = json.loads(capsys.readouterr().out)
    assert body["paused"]["count"] == 1
    assert body["paused"]["reasons"][0]["reason"] == "402 payment required"
    assert body["paused"]["reasons"][0]["since"]


async def test_resume_waiting_is_explicit_scoped_and_preserves_history():
    store = InMemoryLibraryStore()
    held = await store.enqueue(USER, "index", {"source_id": "synthetic"})
    await park(store, USER, held, payload={"source_id": "synthetic"}, reason="payment required")
    other = UserId("other-resume-tenant")
    foreign = await store.enqueue(other, "index", {})
    await park(store, other, foreign, payload={}, reason="payment required")
    history = (await store.get_job(USER, held)).payload["retry"]["history"]
    assert await store.resume_jobs(USER, every=True) == 0
    config = _settings()
    app = create_app()
    app.state.ctx = SimpleNamespace(store=store, settings=config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(f"/v1/users/{USER}/jobs/resume", json={"include_waiting": True})).status_code == 422
        response = await client.post(f"/v1/users/{USER}/jobs/resume", json={"all": True, "include_waiting": True})
    assert response.json() == {"resumed": 1}
    job = await store.get_job(USER, held)
    assert job.payload["retry"] == {"attempts": 0, "history": history, "last_failure": history[-1]}
    assert job.not_before is None
    assert (await store.get_job(other, foreign)).not_before is not None
    assert await store.resume_jobs(USER, every=True, include_waiting=True) == 0
