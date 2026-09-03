"""The consultation record: what a miss is, and what each lane's answer maps to.

Everything here is pure — hand-built answer objects in, one frozen record out. No lane is
run and no store is touched, which is the point: core defines the type and the mapping, and
holds no consultation of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.consultation import (
    ConsultationRecord,
    EvidenceRef,
    claim_ref,
    document_ref,
    is_miss,
    span_ref,
)
from pneuma_knowledge_core.recall.fast import evidence_manifest
from pneuma_knowledge_core.recall.consultation import (
    consultation_from_briefing_ask,
    consultation_from_deep,
    consultation_from_fast,
)

AS_OF = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
CREATED = datetime(2026, 8, 31, 9, 0, 12, tzinfo=timezone.utc)

IDENTITY = {
    "user_id": "u-mei",
    "visitor_class": "audit",
    "question": "阿宝的入职日期是哪天？",
    "as_of": AS_OF,
    "library_ref": "a1b2c3d4",
    "consultation_id": "k-0001",
    "created_at": CREATED,
}


@dataclass(frozen=True)
class _Claim:
    anchor: str
    document_path: str
    citations: tuple = ()


@dataclass(frozen=True)
class _Window:
    source_id: str
    block_start: int
    block_end: int


@dataclass(frozen=True)
class _Episode:
    source_id: str
    block_start: int
    block_end: int


@dataclass(frozen=True)
class _Timeline:
    document_path: str
    claims: tuple = ()


@dataclass(frozen=True)
class _ComponentEvidence:
    claims: tuple = ()
    windows: tuple = ()


@dataclass(frozen=True)
class _Fast:
    answer: str = ""
    token_usage: dict | None = None
    used_claims: tuple = ()
    used_windows: tuple = ()
    used_episode_summaries: tuple = ()
    used_component_evidence: tuple = ()
    expanded_documents: tuple = ()
    evidence_manifest: tuple = ()
    citation_handles: dict | None = None
    answer_kind: str | None = None
    glance_degraded: str | None = None
    plan_degraded: str | None = None
    rerank_degraded: str | None = None
    evidence_selection_degraded: str | None = None
    answer_format_degraded: str | None = None
    route_degraded: str | None = None
    component_rerank_degraded: str | None = None


@dataclass(frozen=True)
class _Deep:
    answer: str = ""
    token_usage: dict | None = None
    used_claims: tuple = ()
    used_windows: tuple = ()
    evidence_manifest: tuple = ()


@dataclass(frozen=True)
class _Citation:
    source_id: str
    block_start: int
    block_end: int


@dataclass(frozen=True)
class _Ask:
    answer: str = ""
    token_usage: dict | None = None
    citations: tuple = ()
    verbatim_fetches: tuple = ()
    evidence_manifest: tuple = ()
    citation_handles: dict | None = None
    aliased: bool = False


# ------------------------------------------------------------------- the miss rule


@pytest.mark.parametrize(
    "answer_kind, handed, expected",
    [
        ("fact", (claim_ref("aa11", "memory/people/bao.md"),), False),
        ("list", (span_ref("src-01", 2, 4),), False),
        (None, (span_ref("src-01", 2, 4),), False),
        ("no_record", (claim_ref("aa11", "memory/people/bao.md"),), True),
        ("no_record", (), True),
        ("fact", (), True),
        (None, (), True),
    ],
)
def test_a_miss_is_the_model_saying_so_or_nothing_reaching_it(
    answer_kind, handed, expected
):
    """One rule, every lane. The `briefing_ask` exception that used to live here was
    standing in for a manifest that did not name the pack: an ask answered out of its own
    frozen pack handed back nothing and would have been counted as an unanswered question.
    The lane publishes the pack now, so an empty manifest means the same thing everywhere."""
    assert is_miss(answer_kind, handed) is expected


def test_the_record_is_frozen():
    record = ConsultationRecord(
        consultation_id="k-1",
        user_id="u-mei",
        created_at=CREATED,
        lane="fast",
        visitor_class="audit",
        question="?",
        as_of=AS_OF,
        library_ref="",
    )
    with pytest.raises(Exception):
        record.question = "something else"  # type: ignore[misc]


# ------------------------------------------------------------------- address grammar


def test_an_address_is_the_one_scheme_the_rest_of_the_system_uses():
    assert claim_ref("aa11", "memory/people/bao.md") == EvidenceRef(
        "claim", "c:aa11", "memory/people/bao.md"
    )
    # An already-prefixed anchor is not prefixed twice.
    assert claim_ref("c:aa11", "p.md").ref == "c:aa11"
    # A span carries no page, and a one-block span collapses like a canonical marker does.
    assert span_ref("src-01", 2, 4) == EvidenceRef("window", "src-01 ¶2-4", "")
    assert span_ref("src-01", 7, 7).ref == "src-01 ¶7"


# ------------------------------------------------------------------- the fast lane


def test_the_fast_builder_maps_every_face_and_resolves_the_query_local_handles():
    claims = (_Claim("aa11", "memory/people/bao.md"),)
    episodes = (_Episode("src-01", 0, 1),)
    windows = (_Window("src-01", 2, 4),)
    component = (
        _ComponentEvidence(
            claims=(_Claim("bb22", "memory/people/momo.md"),),
            windows=(_Window("src-02", 9, 9),),
        ),
    )
    answer = _Fast(
        answer="2026 年 3 月 2 日。[cite: s01 ¶2-4] [cite: s02 ¶9]",
        used_claims=claims,
        used_episode_summaries=episodes,
        used_windows=windows,
        used_component_evidence=component,
        evidence_manifest=evidence_manifest(
            claims=claims,
            episode_summaries=episodes,
            windows=windows,
            component_evidence=component,
        ),
        citation_handles={"s01": "src-01", "s02": "src-02"},
        answer_kind="time",
        glance_degraded="timeout",
        route_degraded="error",
    )

    record = consultation_from_fast(answer, lane="fast", **IDENTITY)

    assert record.lane == "fast" and record.answer_kind == "time"
    assert record.consultation_id == "k-0001" and record.library_ref == "a1b2c3d4"
    # Render order: claim notes, the component face, episode summaries, raw excerpts.
    assert record.evidence_handed == (
        EvidenceRef("claim", "c:aa11", "memory/people/bao.md"),
        EvidenceRef("component", "c:bb22", "memory/people/momo.md"),
        EvidenceRef("component", "src-02 ¶9", ""),
        EvidenceRef("episode", "src-01 ¶0-1", ""),
        EvidenceRef("window", "src-01 ¶2-4", ""),
    )
    # An admitted citation is recorded as the FACE it was reached through.
    assert record.citations == (
        EvidenceRef("window", "src-01 ¶2-4", ""),
        EvidenceRef("component", "src-02 ¶9", ""),
    )
    assert record.miss is False
    assert record.degraded == (("glance_degraded", "timeout"), ("route_degraded", "error"))
    # No query-local handle survives into a durable record.
    assert "s01" not in record.answer and "src-01" in record.answer


def test_the_fast_builder_drops_a_cited_handle_the_lane_could_not_bind():
    claim = _Claim("aa11", "p.md", citations=(_Citation("src-01", 1, 1),))
    answer = _Fast(
        answer="是的。[cite: s01 ¶1] [cite: s99 ¶3]",
        used_claims=(claim,),
        evidence_manifest=evidence_manifest(claims=(claim,)),
        citation_handles={"s01": "src-01"},
        answer_kind="yes_no",
    )
    record = consultation_from_fast(answer, lane="fast", **IDENTITY)
    assert record.citations == (EvidenceRef("claim", "src-01 ¶1", ""),)
    # And the unbindable handle leaves the RECORDED prose with the bracket it was in.
    assert record.answer == "是的。[cite: src-01 ¶1]"


def test_one_item_reached_by_two_faces_is_recorded_once():
    """TWO FACES, which is the case the dedup exists for: the ranked claim notes surfaced
    this claim and a routed component lookup corroborated it. `kind` says how the lane
    REACHED it — the address is the same address either way — so keeping both left one
    claim in the record twice, and the attention ledger (which dispatches on the address
    shape and never reads `kind`) counted its heat twice."""
    claim = _Claim("aa11", "memory/people/bao.md")
    answer = _Fast(
        answer="",
        evidence_manifest=evidence_manifest(
            claims=(claim,),
            component_evidence=(_ComponentEvidence(claims=(claim,)),),
        ),
        answer_kind="fact",
    )
    record = consultation_from_fast(answer, lane="fast", **IDENTITY)
    # First kind wins: it was reached as a ranked claim first.
    assert record.evidence_handed == (
        EvidenceRef("claim", "c:aa11", "memory/people/bao.md"),
    )


def test_the_same_address_repeated_inside_one_face_is_recorded_once_too():
    claim = _Claim("aa11", "memory/people/bao.md")
    answer = _Fast(
        answer="",
        evidence_manifest=evidence_manifest(
            claims=(claim, claim),
            windows=(_Window("src-01", 2, 4), _Window("src-01", 2, 4)),
        ),
        answer_kind="fact",
    )
    record = consultation_from_fast(answer, lane="fast", **IDENTITY)
    assert record.evidence_handed == (
        EvidenceRef("claim", "c:aa11", "memory/people/bao.md"),
        EvidenceRef("window", "src-01 ¶2-4", ""),
    )


def test_a_fast_answer_with_nothing_in_front_of_it_is_a_miss():
    record = consultation_from_fast(
        _Fast(answer="没有记录。", answer_kind="no_record"), lane="fast", **IDENTITY
    )
    assert record.evidence_handed == () and record.miss is True


# ------------------------------------------------------------------- the deep lane


def test_the_deep_builder_reads_real_source_ids_because_deep_never_aliases():
    claims = (_Claim("aa11", "memory/people/mei.md"),)
    windows = (_Window("src-01", 2, 4),)
    answer = _Deep(
        answer="她在三月接手。[cite: src-01 ¶2-4]",
        used_claims=claims,
        used_windows=windows,
        evidence_manifest=evidence_manifest(claims=claims, windows=windows),
    )
    record = consultation_from_deep(answer, lane="deep", **IDENTITY)

    assert record.lane == "deep"
    assert record.evidence_handed == (
        EvidenceRef("claim", "c:aa11", "memory/people/mei.md"),
        EvidenceRef("window", "src-01 ¶2-4", ""),
    )
    assert record.citations == (EvidenceRef("window", "src-01 ¶2-4", ""),)
    # Deep publishes neither, so the record states neither.
    assert record.answer_kind is None and record.degraded == ()
    assert record.miss is False


# ------------------------------------------------------------- the briefing ask lane


def test_the_ask_builder_copies_the_lanes_manifest_and_admits_against_it():
    """The lane publishes what it put in front of the model — the frozen pack's claims and
    spans, whatever `search_knowledge` rendered, and the L0 the loop fetched — and the
    record copies it. The citation is then ADMITTED against that manifest exactly as the
    other two lanes admit theirs."""
    answer = _Ask(
        answer="是在三月。[cite: s01 ¶2-4]",
        citations=(_Citation("src-01", 2, 4),),
        evidence_manifest=(
            claim_ref("aa11", "memory/people/bao.md"),
            span_ref("src-01", 1, 6),
        ),
        verbatim_fetches=({"source_id": "s01", "locator": {"blocks": [2, 4]}, "chars": 120},),
        citation_handles={"s01": "src-01"},
        aliased=True,
    )
    record = consultation_from_briefing_ask(answer, lane="briefing_ask", **IDENTITY)

    assert record.lane == "briefing_ask"
    assert record.evidence_handed == (
        EvidenceRef("claim", "c:aa11", "memory/people/bao.md"),
        EvidenceRef("window", "src-01 ¶1-6", ""),
    )
    assert record.citations == (EvidenceRef("window", "src-01 ¶2-4", ""),)
    assert record.answer == "是在三月。[cite: src-01 ¶2-4]"
    assert record.miss is False


def test_an_ask_citing_an_interval_the_pack_never_showed_records_no_provenance():
    """The hole admission closes. The lane's own `citations` field is a parse of the
    answer's markers and nothing more, so copying it stored an invented span on a real
    source id as durable provenance."""
    answer = _Ask(
        answer="是在三月。[cite: src-01 ¶900-901]",
        citations=(_Citation("src-01", 900, 901),),
        evidence_manifest=(span_ref("src-01", 1, 6),),
        aliased=False,
    )
    record = consultation_from_briefing_ask(answer, lane="briefing_ask", **IDENTITY)
    assert record.citations == ()
    assert record.evidence_handed == (EvidenceRef("window", "src-01 ¶1-6", ""),)


def test_an_unaliased_ask_keeps_the_real_source_ids_it_wrote():
    """Whether an ask aliases is a deployment setting. With it off the answer's markers are
    real source ids — addresses that still resolve tomorrow — and the handle map is empty
    for that reason rather than because nothing was surfaced. Reading that emptiness as
    "drop everything" would scrub a citation the record's own `evidence_handed` names."""
    answer = _Ask(
        answer="是在三月。[cite: src-01 ¶2-4]",
        citations=(_Citation("src-01", 2, 4),),
        evidence_manifest=(span_ref("src-01", 2, 4),),
        verbatim_fetches=({"source_id": "src-01", "locator": {"blocks": [2, 4]}, "chars": 120},),
        citation_handles={},
        aliased=False,
    )
    record = consultation_from_briefing_ask(answer, lane="briefing_ask", **IDENTITY)
    assert record.answer == "是在三月。[cite: src-01 ¶2-4]"
    assert record.evidence_handed == (EvidenceRef("window", "src-01 ¶2-4", ""),)
    assert record.citations == (EvidenceRef("window", "src-01 ¶2-4", ""),)


def test_an_aliased_ask_that_surfaced_nothing_keeps_no_bracket_either():
    """The other side of the same signal: aliasing WAS on, the loop fetched nothing, and
    the model wrote a handle anyway. That bracket resolves to nothing an hour later."""
    answer = _Ask(
        answer="据说是三月。[cite: s99 ¶1]",
        citations=(),
        verbatim_fetches=(),
        citation_handles={},
        aliased=True,
    )
    record = consultation_from_briefing_ask(answer, lane="briefing_ask", **IDENTITY)
    assert record.answer == "据说是三月。"


def test_an_ask_answered_out_of_the_frozen_pack_records_the_pack_it_rested_on():
    """The ask that needed no tool at all. The pack IS the evidence here, so it is what the
    record names — and the answer is not a miss because something WAS in front of the model,
    which is the ordinary rule rather than a lane exception standing in for a gap."""
    answer = _Ask(
        answer="是在三月。",
        citations=(),
        verbatim_fetches=(),
        evidence_manifest=(claim_ref("aa11", "memory/people/bao.md"),),
    )
    record = consultation_from_briefing_ask(answer, lane="briefing_ask", **IDENTITY)
    assert record.evidence_handed == (
        EvidenceRef("claim", "c:aa11", "memory/people/bao.md"),
    )
    assert record.miss is False


def test_an_ask_over_a_pack_with_nothing_in_it_is_a_miss_like_any_other_lane():
    answer = _Ask(answer="我这里没有记录。", citations=(), verbatim_fetches=())
    record = consultation_from_briefing_ask(answer, lane="briefing_ask", **IDENTITY)
    assert record.evidence_handed == () and record.miss is True


# --------------------------------------------- the manifest: every face, not just the ranked ones


def _page(path: str, body: str) -> CanonicalDocument:
    return CanonicalDocument(doc_id="d-1", path=path, frontmatter={"title": "阿宝"}, body=body)


def test_a_recall_answered_out_of_one_whole_document_is_not_recorded_as_a_miss():
    """The face the telemetry fields could not see. The glance picked a page, the lane read
    it whole and the answer came out of it — with no ranked hit anywhere. Reconstructing
    `evidence_handed` from `used_claims`/`used_windows` produced nothing, so the record said
    the library had been asked something it could not answer."""
    page = _page(
        "memory/people/bao.md",
        "## 入职\n\n阿宝 2026 年 3 月 2 日入职。[cite: src-07 ¶1-3]\n<!-- anchor: c:aa11 -->\n",
    )
    answer = _Fast(
        answer="2026 年 3 月 2 日。[cite: s01 ¶1-3]",
        expanded_documents=("memory/people/bao.md",),
        evidence_manifest=evidence_manifest(full_documents=(page,)),
        citation_handles={"s01": "src-07"},
        answer_kind="time",
    )
    record = consultation_from_fast(answer, lane="fast", **IDENTITY)
    assert record.evidence_handed == (
        document_ref("memory/people/bao.md"),
        EvidenceRef("document", "src-07 ¶1-3", ""),
    )
    assert record.miss is False


def test_the_glance_is_how_a_page_gets_chosen_and_the_page_is_what_is_handed_over():
    """The line between a map and the thing, pinned where a reviewer will look for it.

    The library glance lists every page's path, title and one-line definition so the model
    can decide what to READ. It is not evidence and is in no manifest: counting it would
    make every consultation touch every page in the library, and heat would stop meaning
    "this was read". What the glance then SELECTS for reading in full IS evidence, and
    arrives as a `document` item carrying every span the page's body cites.
    """
    chosen = _page(
        "memory/people/bao.md",
        "## 入职\n\n阿宝 2026 年 3 月 2 日入职。[cite: src-07 ¶1-3]\n<!-- anchor: c:aa11 -->\n",
    )
    unread = _page("memory/people/mei.md", "## 梅\n\n梅是 CFO。[cite: src-09 ¶0-0]\n")

    # The lane is handed both pages by the glance and reads ONE of them in full.
    manifest = evidence_manifest(full_documents=(chosen,))

    assert document_ref("memory/people/bao.md") in manifest
    assert EvidenceRef("document", "src-07 ¶1-3", "") in manifest
    assert document_ref(unread.path) not in manifest
    assert all("src-09" not in ref.ref for ref in manifest)


def test_a_claim_moved_under_its_window_or_carried_by_the_timeline_is_still_handed_over():
    """`join_claims_to_windows` MOVES a claim out of `used_claims` and renders it as a note
    under its window; the timeline section renders sibling claims that were never in the
    ranked face at all. Both were in front of the model."""
    annotated = _Claim("bb22", "memory/people/momo.md")
    sibling = _Claim("cc33", "memory/people/momo.md", citations=(_Citation("src-09", 4, 4),))
    manifest = evidence_manifest(
        window_notes=((_Window("src-08", 0, 2), (annotated,)),),
        timelines=(_Timeline("memory/people/momo.md", (sibling,)),),
        windows=(_Window("src-08", 0, 2),),
    )
    record = consultation_from_fast(
        _Fast(answer="好。", evidence_manifest=manifest, answer_kind="fact"),
        lane="fast",
        **IDENTITY,
    )
    assert EvidenceRef("claim", "c:bb22", "memory/people/momo.md") in record.evidence_handed
    assert EvidenceRef("claim", "c:cc33", "memory/people/momo.md") in record.evidence_handed
    assert EvidenceRef("claim", "src-09 ¶4", "") in record.evidence_handed
    assert record.miss is False


def test_a_window_note_carries_no_span_the_window_did_not_show():
    """The annotated layout renders its notes WITHOUT a `[cite: …]` marker — the window's
    own provenance header is the citation. So a note may only contribute its claim address:
    a claim joined to blocks 1-2 of a source can also cite blocks 100-101 of it, and that
    second span was in neither the window nor the note. Admitting it would let a citation
    the model invented resolve, and would heat a stretch of source nobody read."""
    joined = _Claim(
        "bb22",
        "memory/people/momo.md",
        citations=(_Citation("src-08", 1, 2), _Citation("src-08", 100, 101)),
    )
    window = _Window("src-08", 1, 2)
    manifest = evidence_manifest(window_notes=((window, (joined,)),), windows=(window,))
    assert manifest == (
        EvidenceRef("claim", "c:bb22", "memory/people/momo.md"),
        EvidenceRef("window", "src-08 ¶1-2", ""),
    )


def test_a_claims_own_provenance_marker_is_an_address_the_model_was_shown():
    """`render_claims` prints each claim's `[cite: …]` marker and the contract tells the
    model to copy source references verbatim from those markers. A span named there is an
    address the lane put in front of the model, and the record says so."""
    claim = _Claim("aa11", "p.md", citations=(_Citation("src-01", 2, 4), _Citation("src-02", 7, 7)))
    manifest = evidence_manifest(claims=(claim,))
    assert manifest == (
        EvidenceRef("claim", "c:aa11", "p.md"),
        EvidenceRef("claim", "src-01 ¶2-4", ""),
        EvidenceRef("claim", "src-02 ¶7", ""),
    )


# ------------------------------------------- citations are a subset of what was handed over


def test_an_invented_interval_on_a_real_source_is_not_durable_provenance():
    """The failure the manifest exists to close: the lane supplied blocks 1-2 of a source
    and the model wrote `¶999` on it. Resolution alone accepts that — the handle is known —
    and the record then names a span nobody was ever shown."""
    answer = _Fast(
        answer="见 [cite: s01 ¶1-2] 与 [cite: s01 ¶999]。",
        evidence_manifest=evidence_manifest(windows=(_Window("src-01", 1, 2),)),
        citation_handles={"s01": "src-01"},
        answer_kind="fact",
    )
    record = consultation_from_fast(answer, lane="fast", **IDENTITY)
    assert record.citations == (EvidenceRef("window", "src-01 ¶1-2", ""),)


def test_a_citation_copied_from_a_claims_own_marker_is_admitted():
    """`render_claims` prints the claim's `[cite: …]` marker and the contract tells the
    model to copy it verbatim, so this is the commonest legitimate citation there is."""
    claim = _Claim("aa11", "p.md", citations=(_Citation("src-05", 3, 9),))
    answer = _Fast(
        answer="是的。[cite: s01 ¶3-9]",
        evidence_manifest=evidence_manifest(claims=(claim,)),
        citation_handles={"s01": "src-05"},
        answer_kind="yes_no",
    )
    assert consultation_from_fast(answer, lane="fast", **IDENTITY).citations == (
        EvidenceRef("claim", "src-05 ¶3-9", ""),
    )


def test_citing_part_of_what_was_shown_is_more_precise_not_less_grounded():
    answer = _Fast(
        answer="见 [cite: s01 ¶2]。",
        evidence_manifest=evidence_manifest(windows=(_Window("src-01", 1, 3),)),
        citation_handles={"s01": "src-01"},
        answer_kind="fact",
    )
    assert consultation_from_fast(answer, lane="fast", **IDENTITY).citations == (
        EvidenceRef("window", "src-01 ¶2", ""),
    )


def test_deep_citing_a_source_it_never_surfaced_records_nothing_for_it():
    """Deep does not alias, so every syntactically shaped `<id> ¶a-b` used to become a
    durable citation — including one for a source the loop never returned."""
    windows = (_Window("src-01", 2, 4),)
    answer = _Deep(
        answer="[cite: src-01 ¶2-4] 与 [cite: src-77 ¶1-1]",
        used_windows=windows,
        evidence_manifest=evidence_manifest(windows=windows),
    )
    assert consultation_from_deep(answer, lane="deep", **IDENTITY).citations == (
        EvidenceRef("window", "src-01 ¶2-4", ""),
    )


def test_the_recorded_answer_carries_no_unresolvable_handle():
    """The rule the module states out loud — a query-local handle never reaches a record.
    Reverse-binding leaves an unknown one in place for the CALLER to see; the record, which
    outlives the call by which it could be resolved, drops the bracket that holds it."""
    answer = _Fast(
        answer="上半年是这样。[cite: s01 ¶1-2] 下半年据说 [cite: s99 ¶4] 换了。",
        evidence_manifest=evidence_manifest(windows=(_Window("src-01", 1, 2),)),
        citation_handles={"s01": "src-01"},
        answer_kind="fact",
    )
    record = consultation_from_fast(answer, lane="fast", **IDENTITY)
    assert "s99" not in record.answer
    assert record.answer == "上半年是这样。[cite: src-01 ¶1-2] 下半年据说 换了。"


def test_an_answer_with_no_source_behind_it_keeps_no_citation_either():
    """The emptiest retrieval there is: fast surfaced nothing, so the handle map is empty —
    and an empty map used to mean "this lane does not alias, leave the prose alone". The
    answers with no evidence behind them were exactly the ones that kept their invented
    brackets in the durable record."""
    answer = _Fast(
        answer="据我所知是这样。[cite: s99 ¶1]",
        evidence_manifest=(),
        citation_handles={},
        answer_kind="fact",
    )
    record = consultation_from_fast(answer, lane="fast", **IDENTITY)
    assert record.answer == "据我所知是这样。"
    assert record.citations == ()
    assert record.miss is True


def test_a_merged_bracket_reaches_the_record_with_both_sources_resolved():
    answer = _Fast(
        answer="两处。[cite: s01 ¶1-3, s02 ¶2-4]",
        evidence_manifest=evidence_manifest(
            windows=(_Window("src-01", 1, 3), _Window("src-02", 2, 4))
        ),
        citation_handles={"s01": "src-01", "s02": "src-02"},
        answer_kind="fact",
    )
    record = consultation_from_fast(answer, lane="fast", **IDENTITY)
    assert record.answer == "两处。[cite: src-01 ¶1-3, src-02 ¶2-4]"
    assert record.citations == (
        EvidenceRef("window", "src-01 ¶1-3", ""),
        EvidenceRef("window", "src-02 ¶2-4", ""),
    )


# --------------------------------------------------------------------- what it spent


def test_every_lane_records_what_it_spent_in_tokens_in_field_order():
    """Usage is a fact about the call, so it belongs in the record of the call. Tokens
    only: the money is derived when someone reads, out of the rates declared then."""
    spent = {
        "input_tokens": 4310,
        "output_tokens": 182,
        "total_tokens": 4492,
        "cache_read": 1780,
        "cache_creation": 2524,
    }
    expected = (
        ("input_tokens", 4310),
        ("output_tokens", 182),
        ("total_tokens", 4492),
        ("cache_read", 1780),
        ("cache_creation", 2524),
    )
    fast = consultation_from_fast(_Fast(answer="是 8 月 3 日。", token_usage=spent), lane="fast", **IDENTITY)
    deep = consultation_from_deep(_Deep(answer="是 8 月 3 日。", token_usage=spent), lane="deep", **IDENTITY)
    ask = consultation_from_briefing_ask(
        _Ask(answer="是 8 月 3 日。", token_usage=spent), lane="briefing_ask", **IDENTITY
    )
    assert fast.token_usage == expected
    assert deep.token_usage == expected
    assert ask.token_usage == expected


def test_a_lane_that_reported_no_usage_records_an_empty_tuple_not_zeros():
    """The two are different statements: a row of zeros claims the call was free, and an
    empty tuple says nothing was reported. Only the second is true here."""
    record = consultation_from_fast(_Fast(answer="不知道。"), lane="fast", **IDENTITY)
    assert record.token_usage == ()
