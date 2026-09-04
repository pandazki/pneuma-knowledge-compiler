"""The projection channel at the index job: a component learns a source finished indexing,
and a component that raises never costs the job that already succeeded.

Keyless and middleware-free — the worker's `process_index_job` runs over fakes, so what is
under test is the hook's placement and its fail-soft rule.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.components import BaseComponent, register_component, reset_components
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)

from pneuma_knowledge_service.workers.compile_worker import process_index_job

USER = UserId("u-index")
SID = SourceId("s-index-1")


@pytest.fixture(autouse=True)
def _clean():
    reset_components()
    yield
    reset_components()


def _normalized() -> NormalizedSource:
    raw = RawSource(
        source_id=SID,
        user_id=USER,
        kind="conversation",
        source_class="workstream",
        title="t",
        mime="text/plain",
        checksum="chk",
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        meta={"occurred_on": "2026-04-12"},
        # `none` keeps this test off every model path: L1 is unconditional (I3), L2 is
        # skipped, and what remains is exactly the seam under test.
        intake_plan={
            "canonical_treatment": "full",
            "semantic_indexing": "none",
            "rationale": "test",
        },
    )
    blocks = [NormalizedBlock(index=i, text=f"第{i}段", section_path=["2026-04-12"]) for i in range(2)]
    return NormalizedSource(
        raw=raw,
        blocks=blocks,
        structure=StructureMap(
            sections=[SectionSpan(path=["2026-04-12"], start_block=0, end_block=1)]
        ),
    )


class _Store:
    def __init__(self, normalized: NormalizedSource) -> None:
        self.normalized = normalized
        self.completed: list[tuple[str, bool, str]] = []

    async def get(self, user_id, source_id):
        if str(source_id) != str(SID):
            raise KeyError(source_id)
        return self.normalized

    async def complete(self, user_id, job_id, *, ok, detail, token_usage=None):
        self.completed.append((job_id, ok, detail))


class _Lexical:
    def __init__(self) -> None:
        self.indexed: list[tuple[str, int]] = []

    async def index_blocks(self, user_id, source_id, blocks, *, archived=False):
        self.indexed.append((str(source_id), len(blocks)))


def _ctx(store: _Store) -> SimpleNamespace:
    return SimpleNamespace(
        store=store,
        lexical=_Lexical(),
        vectors=SimpleNamespace(),
        settings=SimpleNamespace(),
    )


class _Recorder(BaseComponent):
    name = "recorder"

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, int]] = []

    async def on_source_indexed(self, user_id, source):
        self.seen.append((str(user_id), str(source.raw.source_id), len(source.blocks)))


class _Broken(BaseComponent):
    name = "broken"

    async def on_source_indexed(self, user_id, source):
        raise RuntimeError("this component's projection is on fire")


async def test_the_index_job_tells_every_component_the_source_is_ready():
    store = _Store(_normalized())
    ctx = _ctx(store)
    recorder = _Recorder()
    register_component(recorder)

    await process_index_job(ctx, USER, SimpleNamespace(job_id="j1", payload={"source_id": str(SID)}))

    assert ctx.lexical.indexed == [(str(SID), 2)]
    assert recorder.seen == [(str(USER), str(SID), 2)]
    assert store.completed == [("j1", True, "indexed")]


async def test_a_component_that_raises_does_not_fail_the_index_job():
    """A component projection is derived and rebuildable; L1/L2 is the job's actual work.
    Failing the job over a component would re-run the indexing that already succeeded — and
    loop forever if the component stays broken."""
    store = _Store(_normalized())
    ctx = _ctx(store)
    recorder = _Recorder()
    register_component(_Broken())
    register_component(recorder)

    await process_index_job(ctx, USER, SimpleNamespace(job_id="j2", payload={"source_id": str(SID)}))

    assert store.completed == [("j2", True, "indexed")]  # the job still succeeded
    assert recorder.seen  # …and the fan-out continued past the broken one


async def test_with_no_component_registered_the_job_is_exactly_what_it_was():
    store = _Store(_normalized())
    ctx = _ctx(store)
    await process_index_job(ctx, USER, SimpleNamespace(job_id="j3", payload={"source_id": str(SID)}))
    assert store.completed == [("j3", True, "indexed")]


async def test_a_source_deleted_since_enqueue_never_reaches_the_channel():
    store = _Store(_normalized())
    ctx = _ctx(store)
    recorder = _Recorder()
    register_component(recorder)

    await process_index_job(ctx, USER, SimpleNamespace(job_id="j4", payload={"source_id": "gone"}))

    assert store.completed == [("j4", True, "source gone")]
    assert recorder.seen == []
