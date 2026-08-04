"""First-party source-type plugin: diarization typing + per-type compile guidance."""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.compile.runner import _render_task
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import (
    ConversationTurn,
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.ingest.source_types import (
    ContextStreamSourceType,
    describe_source,
    first_party_type,
    parse_diarized_turns,
)


def _raw(source_id: str = "s1", **kw: object) -> RawSource:
    """A minimal RawSource; `kind`/`meta`/`title`/`source_class` overridable per case."""
    fields: dict[str, object] = dict(
        kind="conversation",
        origin="upload",
        title="t",
        mime="text/plain",
        checksum="c",
        created_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    fields.update(kw)
    return RawSource(source_id=SourceId(source_id), user_id=UserId("u1"), **fields)


def _norm(raw: RawSource) -> NormalizedSource:
    return NormalizedSource(
        raw=raw,
        blocks=[NormalizedBlock(index=0, text="x: hi")],
        structure=StructureMap(),
    )


def test_parse_diarized_turns_types_self_and_others():
    turns = [
        ConversationTurn(speaker="self/1", text="a"),
        ConversationTurn(speaker="others/2", text="b"),
        ConversationTurn(speaker="Alice", text="c"),  # not diarized → stays unknown
    ]
    out = parse_diarized_turns(turns)
    assert (out[0].role, out[0].speaker_id) == ("owner", "self/1")
    assert (out[1].role, out[1].speaker_id) == ("other", "others/2")
    assert out[2].role == "unknown"


def test_parse_preserves_caller_supplied_roles():
    # If the device already typed the role, we never re-derive it from the string.
    turns = [ConversationTurn(speaker="x", text="a", role="owner", speaker_id="x")]
    assert parse_diarized_turns(turns)[0].role == "owner"


def test_context_stream_type_bundles_all_concerns():
    ct = ContextStreamSourceType()
    assert ct.origin == "context_stream"
    assert first_party_type("context_stream") is not None
    assert first_party_type("upload") is None  # generic path has no plugin
    assert ct.indexing().chunk_strategy == "semantic"
    g = ct.compile_guidance()
    assert (
        g is not None
        and "the owner and numbered" in g.data_context
        and "context stream" in g.app_context
    )
    # attribution is framed as provenance, not adjudication — the systemic fix for the
    # over-assertion the sharp discrimination framing caused on the strong agentic lane.
    assert "tracing, not" in g.app_context

    raw = RawSource(
        source_id=SourceId("s1"), user_id=UserId("u1"), kind="conversation",
        origin="context_stream", title="t", mime="application/vnd.pneuma.context-stream+json",
        checksum="c", created_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    norm = ct.format(raw, ct.load([ConversationTurn(speaker="self/1", text="hi")]))
    assert norm.blocks[0].text == "Owner: hi"


def test_render_task_injects_guidance_before_blocks():
    raw = RawSource(
        source_id=SourceId("s1"), user_id=UserId("u1"), kind="conversation",
        origin="context_stream", title="t", mime="text/plain", checksum="c",
        created_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    ct = ContextStreamSourceType()
    norm = ct.format(raw, ct.load([ConversationTurn(speaker="self/1", text="hi")]))
    task = _render_task(
        [norm], [], source_guidance={"s1": ct.compile_guidance().render()}
    )
    # guidance appears, and before the block body it annotates
    assert "[First-party data notes]" in task
    assert task.index("Feature intent") < task.index("¶0 Owner: hi")


def test_render_task_no_guidance_is_unchanged_generic_path():
    task = _render_task([_norm(_raw("s2"))], [], source_guidance={})
    assert "[First-party data notes]" not in task


# ── the source's own date reaches the compile prompt ────────────────────────────────────
#
# `meta["occurred_on"]` is the framework's authoritative occurrence day (stamped by
# `ingest.adapters.stamp_occurred_on` for every path). It used to be read only by the
# context_stream preamble and the round-level time frame, so under a PER-DAY round nobody
# noticed the gap — the round span was the source's day. Under a BATCHED round the span
# covers several days and the per-source dates vanished entirely: sources rendered as
# "supplies no provenance and no time" while their date sat in metadata, and the skill's
# "resolve relative dates by calendar arithmetic" rule became unexecutable.


def test_a_source_whose_only_date_is_occurred_on_states_that_date():
    # The bench/EverMemBench shape exactly: kind=conversation, origin=upload, no author,
    # no created metadata — only the stamped day.
    sentence = describe_source(_raw(meta={"occurred_on": "2022-01-21"}), 12, "the owner")
    assert "2022-01-21" in sentence
    assert "no provenance and no time" not in sentence
    # attribution still degrades honestly — a date is not authorship
    assert "no author" in sentence and "pending" in sentence


def test_a_dated_document_with_no_author_states_the_date():
    sentence = describe_source(
        _raw(kind="document", title="Plan", meta={"occurred_on": "2022-02-25"}),
        3,
        "the owner",
    )
    assert "2022-02-25" in sentence
    assert "no author" in sentence


def test_dated_external_reference_states_the_date_and_keeps_its_stance():
    sentence = describe_source(
        _raw(
            kind="document",
            source_class="reference",
            title="Spec",
            meta={"occurred_on": "2023-05-07"},
        ),
        3,
        "the owner",
    )
    assert "2023-05-07" in sentence
    assert "not their own statement" in sentence


def test_an_authored_document_without_a_timestamp_falls_back_to_occurred_on():
    sentence = describe_source(
        _raw(
            kind="document",
            title="Note",
            meta={"author": "a teammate", "occurred_on": "2026-07-10"},
        ),
        3,
        "the owner",
    )
    assert "dated 2026-07-10" in sentence


def test_a_document_that_already_states_its_authoring_time_is_worded_as_before():
    # Regression guard: `created_at` wins and the sentence is untouched by the date fix.
    sentence = describe_source(
        _raw(
            kind="document",
            title="Note",
            meta={
                "author": "a teammate",
                "created_at": "2026-07-10T14:05:00",
                "occurred_on": "2026-07-18",
            },
        ),
        3,
        "the owner",
    )
    assert "created on 2026-07-10 14:05" in sentence
    assert "2026-07-18" not in sentence


def test_a_source_with_no_date_at_all_still_degrades_honestly():
    sentence = describe_source(_raw(), 3, "the owner")
    assert "no provenance and no time" in sentence
    assert "pending" in sentence


def test_a_dateless_document_keeps_the_no_authoring_time_wording():
    sentence = describe_source(_raw(kind="document", title="Plan"), 3, "the owner")
    assert "no author and no authoring time" in sentence


# ── the round's real shape, stated mechanically ─────────────────────────────────────────


def test_a_multi_day_round_states_that_it_is_not_one_day_and_names_the_span():
    sources = [
        _norm(_raw("s01", meta={"occurred_on": "2022-01-21"})),
        _norm(_raw("s02", meta={"occurred_on": "2022-02-01"})),
        _norm(_raw("s03", meta={"occurred_on": "2022-02-25"})),
    ]
    task = _render_task(
        sources,
        [],
        source_preamble={
            str(s.raw.source_id): describe_source(s.raw, 1, "the owner")
            for s in sources
        },
    )
    assert "2022-01-21 — 2022-02-25 (3 day(s))" in task
    assert "not a single day" in task
    assert "bundles 3 source(s) across 3 calendar days" in task
    # and every source's own date is actually present, which is the whole point
    for day in ("2022-01-21", "2022-02-01", "2022-02-25"):
        assert task.count(day) >= 1
    assert "supplies no provenance and no time" not in task


def test_a_single_day_round_reads_exactly_as_before():
    sources = [
        _norm(_raw("s01", meta={"occurred_on": "2022-01-21"})),
        _norm(_raw("s02", meta={"occurred_on": "2022-01-21"})),
    ]
    task = _render_task(sources, [])
    assert "2022-01-21 (1 day(s))" in task
    assert "not a single day" not in task


def test_a_round_with_no_dates_at_all_is_unchanged():
    task = _render_task([_norm(_raw("s01"))], [])
    assert "carries no occurrence time" in task
    assert "not a single day" not in task
