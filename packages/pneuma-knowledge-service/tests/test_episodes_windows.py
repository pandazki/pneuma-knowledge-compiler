"""Episodes over windows: a source too long for one round is judged window by window.

The live failure: a 1,370,277-character source rendered whole into one episodes task, and
the harness refused it at `turn/start` (`input_too_large`) three times; the source could
never get semantic chunks. Every source and description here is synthetic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from pneuma_knowledge_core.compile.runner import first_round_budget
from pneuma_knowledge_core.domain.authorship import block_authorship
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource, SectionSpan, StructureMap
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_service.cli import draft, episodes
from pneuma_knowledge_service.wiring import chunks_from_agent_manifest, executor_for, plan_l2_chunks
from pneuma_knowledge_service.workers import compile_worker

from test_episodes_door import SID, make_runtime, points, propose, replay_via_rebuild, source

LONG = "the synthetic pipeline reported a nominal status and nothing else of note. "


def long_source(user, *, blocks=2800):
    """~1.37M characters in 2,800 blocks (the live source's order), with nested sections so
    windows open inside them."""
    texts = [f"Block {i} of a synthetic operations log. " + LONG * 6 for i in range(blocks)]
    sections = [SectionSpan(path=["Log"], start_block=0, end_block=blocks - 1)]
    sections += [
        SectionSpan(path=["Log", f"Part {n}"], start_block=start, end_block=min(start + 99, blocks - 1))
        for n, start in enumerate(range(0, blocks, 100))
    ]
    return NormalizedSource(
        raw=RawSource(
            source_id=SID, user_id=user, kind="agent_session", origin="mock",
            title="Synthetic long operations log", mime="text/plain", checksum="synthetic-long-checksum",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            intake_plan={"canonical_treatment": "full", "semantic_indexing": "full", "rationale": "synthetic"},
        ),
        blocks=[NormalizedBlock(index=i, text=text) for i, text in enumerate(texts)],
        structure=StructureMap(sections=sections),
    )


def _tiles(windows, indices):
    assert windows[0][0] == indices[0] and windows[-1][1] == indices[-1]
    for (_, end), (start, _) in zip(windows, windows[1:]):
        assert start == end + 1, "windows must be contiguous and disjoint"


@pytest.fixture
async def rt(tmp_path):
    runtime = await make_runtime(tmp_path)
    yield runtime
    await runtime.ctx.vectors.aclose()


# ───────────────────────────────────────────────────────────── the windows themselves


async def test_a_long_source_splits_at_block_boundaries_and_every_window_task_fits(rt):
    src = long_source(rt.user_id)
    assert sum(len(b.text) for b in src.blocks) > 1_300_000
    bound = rt.ctx.settings.agent_episodes_window_chars
    assert bound == 400_000
    windows = episodes.source_windows(src, bound)
    assert len(windows) >= 4
    _tiles(windows, [b.index for b in src.blocks])
    budget = first_round_budget(1, rt.max_tool_calls)
    for window in windows:
        task = episodes._window_task(src, window, budget)
        assert len(task) <= bound, (window, len(task))
        assert f"¶{window[0]}-{window[1]} of ¶0-{len(src.blocks) - 1}" in task
        shown = json.loads(task.split("Source window and structure map:\n", 1)[1].rsplit("\n\nBudget:", 1)[0])
        assert [b["index"] for b in shown["blocks"]] == list(range(window[0], window[1] + 1))
        assert all(s["start_block"] <= window[1] and s["end_block"] >= window[0] for s in shown["structure"]["sections"])


def test_a_block_over_the_bound_is_its_own_window():
    user = "u-windows-huge"
    src = long_source(user, blocks=3)
    src.blocks[1].text = "x" * 5000
    windows = episodes.source_windows(src, 3000)
    assert (1, 1) in windows
    _tiles(windows, [0, 1, 2])


# ─────────────────────────────────────────────────────────────── the job becomes N jobs


async def test_the_worker_replaces_an_unwindowed_job_with_windowed_jobs_at_its_place(rt, monkeypatch):
    await rt.ctx.store.add(rt.user_id, long_source(rt.user_id))
    rt.ctx.settings.agent_unattended = True
    rt.ctx.compile_executor = executor_for(rt.ctx.settings, "compile")
    place = datetime.now(timezone.utc) - timedelta(hours=1)
    original = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID)}, order_at=place)
    compile_id = await rt.jobs.enqueue(rt.user_id, "compile", {"source_ids": [str(SID)]})
    launched = []

    async def agent(ctx, user_id, job):  # noqa: ANN001
        launched.append((job.kind, job.payload.get("window"), job.order_at))
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="done")

    monkeypatch.setattr(compile_worker, "process_agent_job", agent)
    await compile_worker.drain_user(rt.ctx, None, None, rt.user_id)
    windows = episodes.source_windows(await rt.ctx.store.get(rt.user_id, SID), 400_000)
    assert launched[:-1] == [("episodes", {"start": s, "end": e}, place) for s, e in windows]
    assert launched[-1][0] == "compile", "every window is claimed ahead of the source's compile"
    rows = {j["job_id"]: j for j in await rt.jobs.list_jobs(rt.user_id)}
    assert rows[original]["status"] == "done" and rows[original]["ok"] is True
    assert rows[original]["detail"] == f"episodes: split into {len(windows)} windows"
    assert rows[compile_id]["status"] == "done"


async def test_split_skips_recorded_windows_and_an_attended_open_splits_too(rt, tmp_path):
    rt.ctx.settings.agent_episodes_window_chars = 1  # every block its own window
    first = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID), "window": {"start": 0, "end": 0}})
    assert await episodes.cmd_open(rt, first) == 0, rt.err.getvalue()
    assert await propose(rt, tmp_path, []) == 0
    assert await episodes.cmd_finish(rt) == 0
    unwindowed = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID)})
    assert await episodes.cmd_open(rt, unwindowed) == draft.EXIT_NOTHING
    assert "judged in 6 windows" in rt.out.getvalue()
    jobs = await rt.jobs.list_jobs(rt.user_id)
    queued = sorted(j["payload"]["window"]["start"] for j in jobs if j["status"] == "queued")
    assert queued == [1, 2, 3, 4, 5]
    done = next(j for j in jobs if j["job_id"] == unwindowed)
    assert done["detail"] == "episodes: split into 6 windows; 1 already recorded or queued"
    assert await rt.drafts.get(rt.user_id, unwindowed) is None


async def test_a_source_under_the_bound_keeps_one_job_and_todays_task_byte_for_byte(rt):
    ns = await rt.ctx.store.get(rt.user_id, SID)
    job = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID)})
    assert await episodes.split_oversized(rt.ctx, rt.jobs, rt.user_id, await rt.jobs.get_job(rt.user_id, job)) is None
    code, _, task = await episodes.open_round(rt, job)
    assert code == 0
    roles = {row["index"]: row for row in block_authorship(ns.raw)}
    surface = json.dumps({
        "source_id": str(ns.raw.source_id),
        "source_context": ns.raw.retrieval_context_lines(),
        "structure": ns.structure.model_dump(mode="json"),
        "blocks": [{**b.model_dump(mode="json"), **roles.get(b.index, {})} for b in sorted(ns.blocks, key=lambda b: b.index)],
    }, ensure_ascii=False, indent=2)
    assert task == prompt("steward.episodes.task", source=surface, budget=first_round_budget(1, rt.max_tool_calls))
    assert "window" not in (await rt.drafts.get(rt.user_id, job))["session"]["context"]
    assert len(await rt.jobs.list_jobs(rt.user_id)) == 1


# ─────────────────────────────────────────────────────────────── the gate, per window


async def test_the_gate_refuses_a_boundary_outside_the_window_and_names_the_windows_residue(rt, tmp_path):
    job = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID), "window": {"start": 2, "end": 4}})
    code, _, task = await episodes.open_round(rt, job)
    assert code == 0 and "¶2-4 of ¶0-5" in task
    inside = {"start": 2, "end": 3, "title": "Delivery test", "description": "Delivery needs a passing test."}
    for outside in ({**inside, "start": 1}, {**inside, "end": 5}):
        assert await propose(rt, tmp_path, [outside]) == draft.EXIT_REFUSED
        assert "episodes.window" in rt.err.getvalue() and "¶2-4" in rt.err.getvalue()
    assert await propose(rt, tmp_path, [inside]) == 0
    # The coverage rule is the window's: its uncovered block is named, never the source's.
    assert "no episode: [4]" in rt.out.getvalue()
    assert await propose(rt, tmp_path, []) == 0
    assert "no episode: [2, 3, 4]" in rt.out.getvalue()


async def test_a_malformed_window_is_refused_and_released(rt):
    job = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID), "window": {"start": 4, "end": 2}})
    assert await episodes.cmd_open(rt, job) == draft.EXIT_REFUSED
    assert (await rt.jobs.get_job(rt.user_id, job)).status == "queued"


# ─────────────────────────────────────────────────────────────── the kept record


WINDOWS = [
    ((0, 2), [{"start": 1, "end": 2, "title": "Aurora delivery", "description": "Aurora will deliver in June, subject to a passing test."}]),
    ((3, 5), [{"start": 4, "end": 4, "title": "Borealis review", "description": "Borealis reviews the delivery on Monday."}]),
]


async def judge_window(rt, tmp_path, window, proposal):
    job = await rt.jobs.enqueue(rt.user_id, "episodes", {"source_id": str(SID), "window": {"start": window[0], "end": window[1]}})
    assert await episodes.cmd_open(rt, job) == 0, rt.err.getvalue()
    assert await propose(rt, tmp_path, proposal) == 0, rt.err.getvalue()
    assert await episodes.cmd_finish(rt) == 0, rt.err.getvalue()
    return job


async def windowed_round_trip(rt, tmp_path, monkeypatch):
    ns = await rt.ctx.store.get(rt.user_id, SID)
    first = await judge_window(rt, tmp_path, *WINDOWS[0])
    # One window of two is not a judgement: no chunks, no vectors, no invented partition.
    assert await plan_l2_chunks(rt.ctx, SID, ns, rt.user_id) == []
    assert await points(rt) == []
    assert (await rt.jobs.get_job(rt.user_id, first)).status == "done"
    second = await judge_window(rt, tmp_path, *WINDOWS[1])
    rows = await rt.ctx.store.get_chunk_manifest_windows(rt.user_id, SID)
    assert [(r["window_start"], r["window_end"]) for r in rows] == [(0, 2), (3, 5)]
    assert all(r["segments"]["producer"] == "agent" and r["model"] == "agent:codex" for r in rows)
    assert await rt.ctx.store.get_chunk_manifest(rt.user_id, SID) is None, "whole-source record untouched"
    whole = {**rows[0], "segments": {**rows[0]["segments"], "episodes": [e for r in rows for e in r["segments"]["episodes"]]}}
    expected = await chunks_from_agent_manifest(rt.ctx, SID, ns.blocks, ns.structure, whole)
    chunks = await plan_l2_chunks(rt.ctx, SID, ns, rt.user_id)
    assert chunks == expected and chunks
    before = await points(rt)
    assert {(p["payload"]["block_start"], p["payload"]["block_end"]) for p in before} == {(1, 2), (4, 4)}
    await replay_via_rebuild(rt, monkeypatch)
    after = await points(rt)
    assert [p["id"] for p in after] == [p["id"] for p in before]
    assert [p["payload"] for p in after] == [p["payload"] for p in before]
    assert await rt.ctx.store.get_chunk_manifest_windows(rt.user_id, SID) == rows
    assert await plan_l2_chunks(rt.ctx, SID, ns, rt.user_id) == chunks
    return first, second


async def test_windows_compose_only_when_all_are_recorded_and_rebuild_replays_them(rt, tmp_path, monkeypatch):
    first, second = await windowed_round_trip(rt, tmp_path, monkeypatch)
    details = {j["job_id"]: j["detail"] for j in await rt.jobs.list_jobs(rt.user_id)}
    assert details[first] == "episodes: 1 in window ¶0-2; the source awaits its other windows"
    assert details[second] == "episodes: 1 in window ¶3-5; every window recorded"
    assert rt.ctx.store.manifest_writes == 2
    # An index retry replays the kept windows; it neither re-commissions nor rewrites them.
    job = await rt.jobs.enqueue(rt.user_id, "index", {"source_id": str(SID)})
    await compile_worker.process_index_job(rt.ctx, rt.user_id, await rt.jobs.claim(rt.user_id, job))
    assert not [j for j in await rt.jobs.list_jobs(rt.user_id) if j["kind"] == "episodes" and j["status"] == "queued"]
    assert rt.ctx.store.manifest_writes == 2


async def test_an_edit_anywhere_retires_every_window(rt, tmp_path):
    for window, proposal in WINDOWS:
        await judge_window(rt, tmp_path, window, proposal)
    changed = source(rt.user_id)
    changed.blocks[5].text = "A different synthetic ending."
    await rt.ctx.store.add(rt.user_id, changed)
    assert await plan_l2_chunks(rt.ctx, SID, changed, rt.user_id) == []
