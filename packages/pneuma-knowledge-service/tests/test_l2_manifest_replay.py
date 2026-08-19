"""The chunk manifest across the `semantic_overlap` knob — the rebuild_derived path.

`rebuild_derived` and `reindex_l2` both re-chunk through `wiring.full_l2_chunks`, so this
is where "a rebuild is byte-deterministic" is either true or not. Two promises meet here
and they pull in opposite directions:

* a recorded segmentation REPLAYS, so a rebuild reproduces the layout exactly rather than
  paying for a second non-reproducible boundary call;
* `semantic_overlap` is declared a `derived_rebuild` knob, so flipping it and rebuilding has
  to actually re-cut — a replay that ignored the mode would make the badge a lie.

Both hold because the recorded MODE is part of the replay key. Fully keyless: the fake
model stands in for the compile role, and any unexpected model build is an assertion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    RawSource,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_core.ingest.semantic import (
    MANIFEST_VERSION,
    SegmentSpans,
    Segments,
)
from pneuma_knowledge_service.wiring import full_l2_chunks

USER = UserId("u-manifest")
SID = SourceId("11111111-1111-1111-1111-111111111111")


def _blocks(n: int) -> list[NormalizedBlock]:
    return [NormalizedBlock(index=i, text=f"第{i}段记录内容，足够长到值得独立成块。") for i in range(n)]


STRUCTURE = StructureMap(sections=[SectionSpan(path=["S"], start_block=0, end_block=9)])


class _FakeStructured:
    def __init__(self, payload) -> None:
        self._payload = payload
        self.calls: list[tuple] = []

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.calls.append((messages, config))
        return self._payload


class _FakeModel:
    """Answers whichever contract it is asked for, and records which one was asked — so
    "did the LLM run, and under which contract?" is an assertion, not an inference."""

    def __init__(self, *, starts: list[int], spans: list[tuple[int, int]]) -> None:
        self._starts = starts
        self._spans = spans
        self.schemas: list[object] = []

    def with_structured_output(self, schema):  # noqa: ANN001
        self.schemas.append(schema)
        return _FakeStructured(
            SegmentSpans(segments=[list(p) for p in self._spans])
            if schema is SegmentSpans
            else Segments(segments=list(self._starts))
        )


class _EpisodeModel:
    def __init__(self) -> None:
        self.schemas: list[object] = []
        self.structured = None

    def with_structured_output(self, schema):  # noqa: ANN001
        self.schemas.append(schema)
        self.structured = _FakeStructured(
            SegmentSpans(
                segments=[
                    {
                        "title": "Weekend kayaking and safety planning",
                        "description": (
                            "Caroline discussed a kayaking trip and safety equipment."
                        ),
                        "start": 0,
                        "end": 9,
                    }
                ]
            )
        )
        return self.structured


class _Store:
    """The one port `full_l2_chunks` touches, in memory and per (user, source)."""

    def __init__(self, seeded: dict | None = None) -> None:
        self.rows: dict[tuple[str, str], dict] = dict(seeded or {})

    async def get_chunk_manifest(self, user_id, source_id):  # noqa: ANN001
        return self.rows.get((str(user_id), str(source_id)))

    async def put_chunk_manifest(
        self, user_id, source_id, *, strategy, model, content_digest, segments, result_digest
    ):  # noqa: ANN001
        self.rows[(str(user_id), str(source_id))] = {
            "strategy": strategy,
            "model": model,
            "content_digest": content_digest,
            "segments": segments,
            "result_digest": result_digest,
        }


def _ctx(
    model: _FakeModel | None,
    *,
    overlap: str,
    store: _Store,
    chunk_size: int = 768,
) -> SimpleNamespace:
    settings = SimpleNamespace(
        chunk_strategy="semantic",
        semantic_overlap=overlap,
        chunk_size=chunk_size,
        chunk_overlap=128,
        openrouter_api_key="k",
        llm_model="openrouter:test/base",
        llm_model_compile="openrouter:test/strong",
        llm_model_recall="",
        llm_model_deep="",
        llm_model_skill="",
        llm_model_evolve="",
        llm_model_live_context="",
        llm_model_challenge="",
    )

    def _get_chat_model(role="default"):  # noqa: ANN001
        if model is None:
            raise AssertionError("a replay must not build a chat model")
        return model

    return SimpleNamespace(
        settings=settings,
        store=store,
        get_chat_model=_get_chat_model,
        langfuse_handler=lambda: None,
    )


async def _chunks(ctx, *, raw=None) -> list:  # noqa: ANN001
    return await full_l2_chunks(ctx, SID, _blocks(10), STRUCTURE, USER, raw=raw)


def _record(store: _Store) -> dict:
    return store.rows[(str(USER), str(SID))]


# ─────────────────────────────────────────────────────────── first detection, then rebuild


async def test_a_smart_detection_is_recorded_with_its_mode_and_then_replayed():
    store = _Store()
    model = _FakeModel(starts=[0, 5], spans=[(0, 4), (3, 9)])
    first = await _chunks(_ctx(model, overlap="smart", store=store))

    assert [(c.block_start, c.block_end) for c in first] == [(0, 4), (3, 9)]
    assert model.schemas == [SegmentSpans]
    record = _record(store)
    assert record["segments"] == {
        "version": MANIFEST_VERSION,
        "overlap": "smart",
        "episodes": [
            {"title": "", "description": "", "start": 0, "end": 4},
            {"title": "", "description": "", "start": 3, "end": 9},
        ],
    }

    # The rebuild: same content, same model spec, same mode → no model at all, and the
    # layout comes back byte-identical (this is `rebuild_derived`'s whole promise).
    rebuilt = await _chunks(_ctx(None, overlap="smart", store=store))
    assert rebuilt == first
    assert _record(store) == record  # replay does not rewrite the manifest


async def test_episode_representation_is_recorded_and_replayed_without_a_model():
    store = _Store()
    first = await _chunks(_ctx(_EpisodeModel(), overlap="smart", store=store))

    assert first[0].episode_title == "Weekend kayaking and safety planning"
    assert "safety equipment" in first[0].episode_description
    assert list(_record(store)["segments"]["episodes"][0]) == [
        "title",
        "description",
        "start",
        "end",
    ]

    rebuilt = await _chunks(_ctx(None, overlap="smart", store=store))
    assert rebuilt == first


async def test_source_occurrence_context_reaches_the_episode_generation_call():
    store = _Store()
    model = _EpisodeModel()
    raw = RawSource(
        source_id=SID,
        user_id=USER,
        kind="im",
        title="Saturday lake conversation",
        mime="application/json",
        checksum="checksum",
        created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        meta={"occurred_on": "2023-08-12"},
    )

    await _chunks(_ctx(model, overlap="smart", store=store), raw=raw)

    messages, _ = model.structured.calls[0]
    assert "[source title] Saturday lake conversation" in messages[1].content
    assert "[source occurred_on] 2023-08-12" in messages[1].content


async def test_an_off_detection_records_a_partition_and_replays_the_same_way():
    store = _Store()
    model = _FakeModel(starts=[0, 5], spans=[(0, 9)])
    first = await _chunks(_ctx(model, overlap="off", store=store))

    assert [(c.block_start, c.block_end) for c in first] == [(0, 4), (5, 9)]
    assert model.schemas == [Segments]
    assert _record(store)["segments"]["overlap"] == "off"
    assert await _chunks(_ctx(None, overlap="off", store=store)) == first


async def test_replay_subsplits_an_episode_at_the_deployment_chunk_size():
    store = _Store()
    first = await _chunks(
        _ctx(
            _FakeModel(starts=[], spans=[(0, 9)]),
            overlap="smart",
            store=store,
        )
    )
    first_digest = _record(store)["result_digest"]
    assert len(first) == 1

    # The semantic episode is replayed without another model call, but the configured
    # embedding-unit ceiling is a derived rebuild knob and must take effect.
    rebuilt = await _chunks(
        _ctx(None, overlap="smart", store=store, chunk_size=160)
    )

    assert len(rebuilt) > 1
    assert max(len(chunk.text) for chunk in rebuilt) <= 160
    assert _record(store)["result_digest"] != first_digest


# ─────────────────────────────────────────────────────────────────── the knob actually applies


async def test_flipping_the_knob_re_detects_instead_of_replaying_the_old_layout():
    """`apply: derived_rebuild`, made true. Recorded under `off`, rebuilt under `smart`:
    the recorded partition is NOT replayed, the model is asked again under the new
    contract, and the manifest is rewritten with the mode that produced it."""
    store = _Store()
    await _chunks(_ctx(_FakeModel(starts=[0, 5], spans=[]), overlap="off", store=store))
    assert _record(store)["segments"]["overlap"] == "off"

    model = _FakeModel(starts=[], spans=[(0, 4), (3, 9)])
    flipped = await _chunks(_ctx(model, overlap="smart", store=store))
    assert model.schemas == [SegmentSpans]
    assert [(c.block_start, c.block_end) for c in flipped] == [(0, 4), (3, 9)]
    assert _record(store)["segments"] == {
        "version": MANIFEST_VERSION,
        "overlap": "smart",
        "episodes": [
            {"title": "", "description": "", "start": 0, "end": 4},
            {"title": "", "description": "", "start": 3, "end": 9},
        ],
    }
    # And back again: the same flip in the other direction re-detects too.
    back = _FakeModel(starts=[0, 5], spans=[])
    await _chunks(_ctx(back, overlap="off", store=store))
    assert back.schemas == [Segments]
    assert _record(store)["segments"]["overlap"] == "off"


# ──────────────────────────────────────────────────────── records written by older builds


def _seed(store: _Store, segments) -> None:
    from pneuma_knowledge_core.ingest.semantic import blocks_content_digest

    store.rows[(str(USER), str(SID))] = {
        "strategy": "semantic",
        "model": "openrouter:test/strong",
        "content_digest": blocks_content_digest(_blocks(10)),
        "segments": segments,
        "result_digest": "",
    }


async def test_a_pre_envelope_pair_list_keeps_boundaries_while_adding_descriptions():
    """The shape written before the envelope existed. Overlapping pairs can only have come
    from the overlapping contract, so under `smart` they replay as written — an upgrade
    does not re-detect a library to learn what its own record already says. One migration
    call may add retrieval descriptions to those fixed boundaries."""
    store = _Store()
    _seed(store, [[0, 4], [3, 9]])
    model = _FakeModel(starts=[], spans=[(0, 4), (3, 9)])
    chunks = await _chunks(_ctx(model, overlap="smart", store=store))
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 4), (3, 9)]
    assert model.schemas == [SegmentSpans]


async def test_a_boundary_only_envelope_gets_descriptions_without_resegmentation():
    store = _Store()
    _seed(
        store,
        {
            "version": 2,
            "overlap": "smart",
            "spans": [[0, 9]],
        },
    )
    model = _EpisodeModel()

    chunks = await _chunks(_ctx(model, overlap="smart", store=store))

    assert [(chunk.block_start, chunk.block_end) for chunk in chunks] == [(0, 9)]
    assert chunks[0].episode_title == "Weekend kayaking and safety planning"
    assert _record(store)["segments"]["version"] == MANIFEST_VERSION
    assert "already fixed" in model.structured.calls[0][0][0].content


async def test_a_pre_envelope_partition_replays_under_off():
    store = _Store()
    _seed(store, [[0, 4], [5, 9]])
    model = _FakeModel(starts=[], spans=[(0, 4), (5, 9)])
    chunks = await _chunks(_ctx(model, overlap="off", store=store))
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 4), (5, 9)]
    assert model.schemas == [SegmentSpans]


async def test_a_starts_only_record_expands_through_the_partition_rule():
    store = _Store()
    _seed(store, [0, 5])
    model = _FakeModel(starts=[], spans=[(0, 4), (5, 9)])
    chunks = await _chunks(_ctx(model, overlap="off", store=store))
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 4), (5, 9)]
    assert model.schemas == [SegmentSpans]


async def test_an_unreadable_record_re_detects_rather_than_indexing_something_wrong():
    store = _Store()
    _seed(store, {"version": 99, "spans": [[0, 9]]})
    model = _FakeModel(starts=[], spans=[(0, 4), (3, 9)])
    chunks = await _chunks(_ctx(model, overlap="smart", store=store))
    assert model.schemas == [SegmentSpans]
    assert [(c.block_start, c.block_end) for c in chunks] == [(0, 4), (3, 9)]
