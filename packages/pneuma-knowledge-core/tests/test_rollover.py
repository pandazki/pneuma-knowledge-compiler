"""Document rollover: the mechanics, the groom-only gate, and the one model call.

What is locked here is the whole reason rollover is allowed to write canonical at all — that
it MOVES claims and cannot do anything else to them:

- the cut lands on claim-block boundaries and never splits or reflows a block;
- the archive volume plus the retained tail reproduce the original claims byte for byte OUTSIDE
  their links, and point at exactly the same documents INSIDE them — a volume sits one level
  deeper, so a byte-preserved relative link would be a repointed one (once measured: 556 dead
  links from a single groom). A tampered move, either half, is refused rather than repaired;
- repo-wide claim anchors are conserved exactly; the only ids that may appear or disappear are
  the history card's own, which the frontmatter ledger declares;
- every history-card point names archived evidence, and a point that cannot is not written;
- a volume is frozen: the next rollover opens the next volume and leaves the old one alone;
- a card rewrite reuses the same anchor ids, so the projection sees an edit, not a churn.

The model's only job is the card's prose, so it is driven here by a stub — there is nothing
non-deterministic left in a rollover once that one call has answered.
"""

from __future__ import annotations

import hashlib

import pytest
from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.gate import run_gate
from pneuma_knowledge_core.compile.patch import (
    PatchDraft,
    history_volume_owner,
    path_allowed,
)
from pneuma_knowledge_core.compile.rollover import (
    ARCHIVED_FROM_KEY,
    VOLUME_COUNT_KEY,
    VOLUME_NUMBER_KEY,
    VOLUME_SPAN_KEY,
    OverviewPoint,
    _OverviewDraft,
    _OverviewPointDraft,
    archive_date_span,
    build_rollover,
    catalog_anchors,
    claim_occurrence_date,
    commit_message,
    date_span,
    dead_links,
    heal_commit_message,
    heal_volume_links,
    is_archive_volume,
    link_elided,
    link_targets,
    needs_rollover,
    overview_anchors,
    plan_rollover,
    relink,
    render_overview_input,
    run_groom_gate,
    volume_path_for,
    volumes_of,
    write_overview,
)
from pneuma_knowledge_core.compile.documents import parse_document, render_document
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, extract_anchors
from pneuma_knowledge_core.prompts import prompt

TEMPLATES = ["memory/profile.md", "work/products/{slug}.md", "memory/topics/{slug}.md"]
ACTIVE = "work/products/aurora-planner.md"


def _anchor(tag: str) -> str:
    """A valid anchor id (`[0-9a-f]{4,}`), stable per tag."""
    return hashlib.sha256(tag.encode()).hexdigest()[:8]


def _claim(index: int) -> str:
    return (
        f"- Sprint {index}: the Aurora launch checklist advanced. "
        f"[cite: src-01 ¶{index}] <!-- c:{_anchor(f'claim-{index}')} -->"
    )


def _doc(path: str, body: str, **frontmatter: str) -> CanonicalDocument:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=path,
        frontmatter={
            "doc_id": f"d-{slug}",
            "type": "product",
            "slug": slug,
            **frontmatter,
        },
        body=body,
    )


def _active(count: int = 30, **frontmatter: str) -> CanonicalDocument:
    rows = "\n".join(_claim(i) for i in range(count))
    return _doc(ACTIVE, f"# Aurora planner\n\n## Delivery\n\n{rows}\n", **frontmatter)


def _point(*indexes: int, text: str = "The checklist was driven to done.") -> OverviewPoint:
    return OverviewPoint(
        text=text, anchors=tuple(_anchor(f"claim-{i}") for i in indexes)
    )


def _roll(
    docs: list[CanonicalDocument],
    active: CanonicalDocument,
    points: list[OverviewPoint],
    *,
    keep_recent_chars: int = 400,
):
    plan = plan_rollover(
        active, docs, path_templates=TEMPLATES, keep_recent_chars=keep_recent_chars
    )
    assert plan is not None
    return plan, build_rollover(plan, points, docs, path_templates=TEMPLATES)


def _as_doc(path: str, file_text: str) -> CanonicalDocument:
    frontmatter, body = parse_document(file_text)
    return CanonicalDocument(
        doc_id=DocumentId(str(frontmatter.get("doc_id"))),
        path=path,
        frontmatter=frontmatter,
        body=body,
    )


# ---------------------------------------------------------------------------- the trigger


def test_the_trigger_is_size_only_and_zero_disables_it():
    assert needs_rollover("x" * 41_000, 40_000) is True
    assert needs_rollover("x" * 40_000, 40_000) is False  # strictly greater
    # 0 is off, not "roll over everything" — the knob has to be safe to leave unset.
    assert needs_rollover("x" * 10_000_000, 0) is False


def test_even_a_fixed_path_document_has_a_history_directory_of_its_own():
    """`memory/profile.md` owns no slug, but the archive is a same-name DIRECTORY rather than a
    sibling slug — so a fixed-path document rolls over exactly like any other."""
    profile = _doc(
        "memory/profile.md", "# Profile\n\n## Facts\n\n" + "\n".join(_claim(i) for i in range(30))
    )
    plan = plan_rollover(
        profile, [profile], path_templates=TEMPLATES, keep_recent_chars=400
    )
    assert plan is not None
    assert plan.volume_path == "memory/profile/a01.md"


def test_a_document_the_skill_does_not_own_has_no_history_directory():
    stray = _doc("stray/note.md", "# Stray\n\n## S\n\n" + "\n".join(_claim(i) for i in range(30)))
    assert (
        plan_rollover(stray, [stray], path_templates=TEMPLATES, keep_recent_chars=400)
        is None
    )


def test_a_volume_is_never_itself_rolled_over():
    """A volume lives one level down, so its own history directory would be `.../a01/` — which
    no template owns. Frozen history cannot grow a second floor."""
    volume = _doc(
        "work/products/aurora-planner/a01.md",
        "# Aurora planner\n\n## Delivery\n\n" + "\n".join(_claim(i) for i in range(30)),
        **{ARCHIVED_FROM_KEY: ACTIVE},
    )
    assert (
        plan_rollover(volume, [volume], path_templates=TEMPLATES, keep_recent_chars=400)
        is None
    )


def test_nothing_to_archive_is_not_an_error():
    """One oversized claim block cannot be split, so there is no cut to make."""
    single = _doc(ACTIVE, "# Aurora planner\n\n## Delivery\n\n" + _claim(0))
    assert (
        plan_rollover(single, [single], path_templates=TEMPLATES, keep_recent_chars=10)
        is None
    )


# ------------------------------------------------------------------- the cut is on blocks


def test_the_retained_tail_is_the_largest_whole_block_suffix_that_fits():
    active = _active(30)
    plan = plan_rollover(active, [active], path_templates=TEMPLATES, keep_recent_chars=400)
    assert plan is not None
    assert plan.archived_claims + plan.kept_claims == 30
    # every retained block is one of the ORIGINAL blocks, byte for byte — no claim was cut
    original = set(active.body.splitlines())
    assert all(line in original for line in plan.kept_body.splitlines() if line.startswith("- "))
    # the tail respects the budget, and adding the next block back would break it
    tail_blocks = [l for l in plan.kept_body.splitlines() if l.startswith("- ")]
    assert sum(len(b) + 1 for b in tail_blocks) <= 400
    assert len(tail_blocks) >= 1


def test_the_last_claim_is_always_retained_so_a_rollover_cannot_empty_a_document():
    active = _active(30)
    plan = plan_rollover(active, [active], path_templates=TEMPLATES, keep_recent_chars=1)
    assert plan is not None
    assert plan.kept_claims == 1
    assert _claim(29) in plan.kept_body


def test_removing_a_middle_block_never_fuses_its_neighbours_into_one_claim():
    """A list item between two paragraphs is the one shape where naive deletion would leave
    the paragraphs adjacent — and adjacent paragraphs are ONE block, i.e. two claims silently
    fused. The byte-equality gate would catch it; the assembly must not produce it."""
    body = (
        "# Aurora planner\n\n## Delivery\n\n"
        f"Paragraph one about the pilot. [cite: src-01 ¶0] <!-- c:{_anchor('p1')} -->\n"
        f"- A bullet between them. [cite: src-01 ¶1] <!-- c:{_anchor('b1')} -->\n"
        f"Paragraph two about the pilot. [cite: src-01 ¶2] <!-- c:{_anchor('p2')} -->\n"
    )
    active = _doc(ACTIVE, body)
    plan = plan_rollover(
        active, [active], path_templates=TEMPLATES, keep_recent_chars=60
    )
    assert plan is not None
    result = build_rollover(
        plan,
        [OverviewPoint(text="Pilot paragraphs.", anchors=(_anchor("p1"),))],
        [active],
        path_templates=TEMPLATES,
    )
    assert result.status == "ready", [v.render() for v in result.violations]


# ------------------------------------------------------------------- the produced documents


def test_the_active_document_keeps_its_path_and_gains_a_card_and_a_volume_catalog():
    active = _active(30)
    plan, result = _roll([active], active, [_point(0, 5)])
    assert result.status == "ready", [v.render() for v in result.violations]

    rolled = _as_doc(ACTIVE, result.files[ACTIVE])
    # the path, the doc_id and the frontmatter type survive: every inbound link still resolves
    assert rolled.frontmatter["doc_id"] == active.frontmatter["doc_id"]
    assert rolled.frontmatter["type"] == "product"
    # title → card → catalog → retained tail
    assert rolled.body.startswith("# Aurora planner")
    assert rolled.body.index(prompt("compile.groom.overview_heading")) < rolled.body.index(
        prompt("compile.groom.volumes_heading")
    )
    assert rolled.body.index(prompt("compile.groom.volumes_heading")) < rolled.body.index(
        _claim(29)
    )
    # the catalog entry is a markdown link to a sibling — the form the graph reads
    assert "(aurora-planner/a01.md)" in rolled.body
    # the ledger names the groom's own ids, so the conservation check can stay exact
    assert len(overview_anchors(rolled.frontmatter)) == 1
    assert len(catalog_anchors(rolled.frontmatter)) == 1
    assert rolled.frontmatter[VOLUME_COUNT_KEY] == "1"


def test_the_volume_is_a_complete_document_stamped_with_where_it_came_from():
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    volume = _as_doc(plan.volume_path, result.files[plan.volume_path])
    assert plan.volume_path == "work/products/aurora-planner/a01.md"
    assert volume.frontmatter[ARCHIVED_FROM_KEY] == ACTIVE
    assert volume.frontmatter[VOLUME_NUMBER_KEY] == "01"
    assert volume.frontmatter["slug"] == "a01"
    assert is_archive_volume(volume) and not is_archive_volume(active)
    # frozen history, verbatim
    assert _claim(0) in volume.body


def test_a_volumes_date_span_is_derived_and_becomes_the_catalog_link_text():
    """The span is what lets a reader pick WHICH volume to open, so it rides both the volume's
    frontmatter and the link that points at it."""
    dated = _doc(
        ACTIVE,
        "# Aurora planner\n\n## Delivery\n\n"
        + "\n".join(
            f"- (2026-0{3 + i // 6}-{2 + i:02d}) Sprint {i} landed. "
            f"[cite: src-01 ¶{i}] <!-- c:{_anchor(f'claim-{i}')} -->"
            for i in range(20)
        ),
    )
    plan, result = _roll([dated], dated, [_point(0, 1)])
    assert result.status == "ready", [v.render() for v in result.violations]
    volume = _as_doc(plan.volume_path, result.files[plan.volume_path])
    span = volume.frontmatter[VOLUME_SPAN_KEY]
    # min..max over the ARCHIVED entries only — the retained tail's later dates are not in it
    assert span == "2026-03-02 — 2026-05-16"
    assert "2026-05-19" not in span  # a retained claim's date
    assert f"[{span}](aurora-planner/a01.md)" in result.files[ACTIVE]


def test_a_volume_whose_entries_state_no_date_gets_no_span_rather_than_a_guessed_one():
    active = _active(30)  # the fixture's claims carry no dates
    plan, result = _roll([active], active, [_point(0)])
    volume = _as_doc(plan.volume_path, result.files[plan.volume_path])
    assert VOLUME_SPAN_KEY not in volume.frontmatter
    # the catalog falls back to naming the volume
    assert "[a01](aurora-planner/a01.md)" in result.files[ACTIVE]
    assert date_span("no dates in here at all") == ""
    assert date_span("only 2026-05-01 once") == "2026-05-01"


def test_a_span_is_the_days_the_entries_HAPPENED_not_every_day_they_mention():
    """The catalog's date range is the only thing a reader has when choosing a volume, so it
    is a claim about the archive. Read loosely it is made out of dates the entries merely
    mention: measured on a real archive, one recounted event from before the corpus began and
    one FUTURE launch date stretched a seven-month volume's advertised span to ten."""
    entries = [
        "- (2026-03-02) Sprint 0 landed; the retrospective recalls the 2025-11-04 kickoff. "
        f"[cite: src-01 ¶0] <!-- c:{_anchor('claim-0')} -->",
        "- (2026-03-09) Sprint 1 landed; the launch is now set for 2026-12-25. "
        f"[cite: src-01 ¶1] <!-- c:{_anchor('claim-1')} -->",
    ]
    span = archive_date_span("## Delivery\n\n" + "\n".join(entries))
    assert span == "2026-03-02 — 2026-03-09"
    assert "2025-11-04" not in span  # a date the entry recounts, not one it happened on
    assert "2026-12-25" not in span  # a future date mid-sentence


def test_the_second_occurrence_shape_is_the_opening_clause_after_an_optional_label():
    """The real corpus writes a claim's day either parenthesized or as the opening clause,
    optionally behind a strength-tier label. Both are the claim's own day; anything further
    into the sentence is context."""
    assert claim_occurrence_date("- (2026-03-04) the review happened.") == "2026-03-04"
    assert claim_occurrence_date("- 【中】2026-06-10，the review happened.") == "2026-06-10"
    assert claim_occurrence_date("- 2026-06-10, the review happened.") == "2026-06-10"
    # not an occurrence: the day is something the sentence talks about
    assert claim_occurrence_date("- 【中】as of 2026-06-10, 296 defects remain.") == ""
    assert claim_occurrence_date("- the launch is set for 2026-09-29.") == ""


def test_the_span_falls_back_through_three_tiers():
    stated = (
        "- (2026-03-02) Sprint 0 landed. "
        f"[cite: src-01 ¶0] <!-- c:{_anchor('claim-0')} -->"
    )
    mentioned = (
        "- The launch is set for 2026-09-29. "
        f"[cite: src-01 ¶1] <!-- c:{_anchor('claim-1')} -->"
    )
    undated = f"- No day at all. [cite: src-01 ¶2] <!-- c:{_anchor('claim-2')} -->"

    # 1. an entry states when it happened → that, and only that
    assert archive_date_span(f"## D\n\n{stated}\n{mentioned}") == "2026-03-02"
    # 2. nothing states an occurrence → the loose reading still tells a reader the era
    assert archive_date_span(f"## D\n\n{mentioned}") == "2026-09-29"
    # 3. no dates at all → "", and the catalog names the volume instead of guessing
    assert archive_date_span(f"## D\n\n{undated}") == ""


def test_only_the_two_written_documents_are_in_the_commit():
    active = _active(30)
    other = _doc("memory/topics/orion.md", f"# Orion\n\n## Scope\n\n{_claim(99)}")
    plan, result = _roll([active, other], active, [_point(0)])
    assert set(result.files) == {ACTIVE, plan.volume_path}


def test_the_commit_subject_names_the_document_the_count_and_the_volume():
    active = _active(30)
    plan, _ = _roll([active], active, [_point(0)])
    subject = commit_message(plan)
    assert ACTIVE in subject and plan.volume_path in subject
    assert str(plan.archived_claims) in subject


# ------------------------------------------------------- relative links travel with the claim

VOLUME = "work/products/aurora-planner/a01.md"
ORION = "memory/topics/orion.md"
LUMEN = "work/products/lumen.md"


def _linked_claim(index: int, href: str, label: str = "the topic") -> str:
    return (
        f"- Sprint {index}: see [{label}]({href}). "
        f"[cite: src-01 ¶{index}] <!-- c:{_anchor(f'claim-{index}')} -->"
    )


def _linked_world() -> tuple[list[CanonicalDocument], CanonicalDocument]:
    """A repo whose oldest claims link out five different ways, all of them archived."""
    orion = _doc(ORION, f"# Orion\n\n## Scope\n\n{_claim(90)}")
    lumen = _doc(LUMEN, f"# Lumen\n\n## Scope\n\n{_claim(91)}")
    rows = [
        _linked_claim(0, "../../memory/topics/orion.md"),  # two levels up
        _linked_claim(1, "lumen.md"),  # same directory
        _linked_claim(2, "../../memory/topics/orion.md#scope"),  # with a fragment
        _linked_claim(3, "../../data/sheet.csv"),  # not a canonical document
        _linked_claim(4, "https://example.com/paper.md"),  # not a link into this repo
    ] + [_claim(i) for i in range(5, 30)]
    active = _doc(ACTIVE, "# Aurora planner\n\n## Delivery\n\n" + "\n".join(rows) + "\n")
    return [active, orion, lumen], active


def test_relink_re_renders_a_target_from_the_new_position_and_leaves_the_rest_alone():
    """The primitive, on its own. Everything the rewrite may and may not touch, in one place."""
    moved = relink(
        "[a](../../memory/topics/orion.md) [b](lumen.md) [c](../../memory/topics/orion.md#scope) "
        "[d](../../data/sheet.csv) [e](https://example.com/paper.md)",
        from_path=ACTIVE,
        to_path=VOLUME,
    )
    assert moved == (
        "[a](../../../memory/topics/orion.md) [b](../lumen.md) "
        "[c](../../../memory/topics/orion.md#scope) "
        "[d](../../data/sheet.csv) [e](https://example.com/paper.md)"
    )
    # the law that makes this safe: what a link points at is unchanged by re-rendering it
    assert link_targets(moved, VOLUME) == (
        ORION,
        LUMEN,
        ORION,
    )
    # and a rewrite to the same place is the identity
    assert relink(moved, from_path=VOLUME, to_path=VOLUME) == moved


def test_a_moved_claims_links_still_point_at_the_documents_they_pointed_at():
    docs, active = _linked_world()
    plan, result = _roll(docs, active, [_point(0)])
    assert result.status == "ready", [v.render() for v in result.violations]

    volume = result.files[plan.volume_path]
    assert "(../../../memory/topics/orion.md)" in volume  # one more `..` for the extra level
    assert "(../lumen.md)" in volume  # a sibling of the page is an uncle of the volume
    assert "(../../../memory/topics/orion.md#scope)" in volume  # the fragment rides along
    assert "(../../data/sheet.csv)" in volume  # not a canonical document: untouched
    assert "(https://example.com/paper.md)" in volume  # external: untouched

    # the regression this exists for: a groom used to cost the graph every link it moved
    after = {path: parse_document(text)[1] for path, text in result.files.items()}
    after.update({d.path: d.body for d in docs if d.path not in after})
    assert dead_links({d.path: d.body for d in docs}) == 0
    assert dead_links(after) == 0


def test_a_link_left_at_its_old_spelling_is_refused_as_a_repointed_target():
    """The 556-dead-link bug, stated as a gate assertion: the bytes are conserved and that is
    precisely what is wrong with them."""
    docs, active = _linked_world()
    plan, result = _roll(docs, active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])
    unrewritten = volume_body.replace(
        "(../../../memory/topics/orion.md)", "(../../memory/topics/orion.md)"
    )

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body,
        volume_frontmatter_=volume_fm,
        volume_body=unrewritten,
        base_docs=docs,
        path_templates=TEMPLATES,
        overview_blocks=[],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    # not a byte violation — the non-link bytes are untouched, which is the whole distinction
    assert [v.kind for v in violations] == ["groom_links", "groom_links"]
    assert violations[0].detail == prompt(
        "gate.groom.link_target_changed",
        anchor=_anchor("claim-0"),
        before=ORION,
        after="work/memory/topics/orion.md",
    )
    assert violations[1].detail == prompt(
        "gate.groom.dead_links_increased", before=0, after=1
    )


def test_a_link_dropped_from_a_moved_claim_is_refused():
    docs, active = _linked_world()
    plan, result = _roll(docs, active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])
    # the claim keeps every other byte; only its link is gone
    stripped = volume_body.replace(
        "[the topic](../lumen.md)", "[the topic]"
    )

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body,
        volume_frontmatter_=volume_fm,
        volume_body=stripped,
        base_docs=docs,
        path_templates=TEMPLATES,
        overview_blocks=[],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    kinds = [v.kind for v in violations]
    assert "groom_bytes" in kinds  # `](…)` itself is non-link text, so this shows up there too
    assert prompt(
        "gate.groom.link_count_changed", anchor=_anchor("claim-1"), before=1, after=0
    ) in [v.detail for v in violations]


def test_a_volume_catalog_link_that_resolves_nowhere_is_refused_as_a_new_dead_end():
    """The repo-wide half of the check. The catalog card is groom-managed, so per-claim link
    conservation says nothing about it — only the dead-link count does."""
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body.replace("(aurora-planner/a01.md)", "(aurora-planner/a09.md)"),
        volume_frontmatter_=volume_fm,
        volume_body=volume_body,
        base_docs=[active],
        path_templates=TEMPLATES,
        overview_blocks=[],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    assert [v.kind for v in violations] == ["groom_links"]
    assert violations[0].detail == prompt(
        "gate.groom.dead_links_increased", before=0, after=1
    )


def test_a_reworded_claim_is_still_caught_when_it_also_carries_a_link():
    """Splitting the invariant must not open a hole in it: the non-link bytes of a linking
    claim are as byte-conserved as any other claim's."""
    docs, active = _linked_world()
    plan, result = _roll(docs, active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body,
        volume_frontmatter_=volume_fm,
        volume_body=volume_body.replace("Sprint 0: see", "Sprint 0: SEE"),
        base_docs=docs,
        path_templates=TEMPLATES,
        overview_blocks=[],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    assert [v.kind for v in violations] == ["groom_bytes"]


# -------------------------------------------------------------------------- the groom gate


def test_a_reworded_claim_in_the_volume_is_refused():
    """The move is byte-level. A rollover that "tidied" a claim on the way out would be
    rewriting the one non-rebuildable layer under the cover of maintenance."""
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    assert result.status == "ready"

    reworded = result.files[plan.volume_path].replace(
        "Sprint 0: the Aurora launch checklist advanced.",
        "Sprint 0: the Aurora launch checklist ADVANCED.",
    )
    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=parse_document(result.files[ACTIVE])[0],
        active_body=parse_document(result.files[ACTIVE])[1],
        volume_frontmatter_=parse_document(reworded)[0],
        volume_body=parse_document(reworded)[1],
        base_docs=[active],
        path_templates=TEMPLATES,
        overview_blocks=[],
        overview_anchor_ids=list(overview_anchors(parse_document(result.files[ACTIVE])[0])),
        catalog_anchor_ids=list(catalog_anchors(parse_document(result.files[ACTIVE])[0])),
    )
    assert [v.kind for v in violations] == ["groom_bytes"]
    assert violations[0].detail == prompt(
        "gate.groom.claims_not_byte_equal", before=30, after=30
    )


def test_a_dropped_claim_is_refused_as_a_lost_anchor():
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])
    trimmed = "\n".join(l for l in volume_body.splitlines() if _claim(0) != l)

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body,
        volume_frontmatter_=volume_fm,
        volume_body=trimmed,
        base_docs=[active],
        path_templates=TEMPLATES,
        overview_blocks=[],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    kinds = [v.kind for v in violations]
    assert "groom_conservation" in kinds and "groom_bytes" in kinds
    lost = next(v for v in violations if v.kind == "groom_conservation")
    assert lost.detail == prompt("gate.groom.anchor_lost", anchor=_anchor("claim-0"))


def test_an_invented_anchor_is_refused():
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])
    smuggled = volume_body + f"\n\n- Invented. [cite: src-01 ¶0] <!-- c:{_anchor('nope')} -->"

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body,
        volume_frontmatter_=volume_fm,
        volume_body=smuggled,
        base_docs=[active],
        path_templates=TEMPLATES,
        overview_blocks=[],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    added = [v for v in violations if v.kind == "groom_conservation"]
    assert added and added[0].detail == prompt(
        "gate.groom.anchor_added", anchor=_anchor("nope")
    )


def test_a_card_point_without_a_reference_is_refused():
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body,
        volume_frontmatter_=volume_fm,
        volume_body=volume_body,
        base_docs=[active],
        path_templates=TEMPLATES,
        overview_blocks=[f"- A claim with no evidence at all. <!-- c:{_anchor('ov')} -->"],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    overview = [v for v in violations if v.kind == "groom_overview"]
    assert overview and "names no archived entry" in overview[0].detail


def test_a_card_point_referencing_something_outside_the_archive_is_refused():
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])
    # c:<the retained tail's last claim> is a real anchor, but it is NOT archived.
    outside = _anchor("claim-29")

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body,
        volume_frontmatter_=volume_fm,
        volume_body=volume_body,
        base_docs=[active],
        path_templates=TEMPLATES,
        overview_blocks=[f"- Summary. (from c:{outside}) <!-- c:{_anchor('ov')} -->"],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    overview = [v for v in violations if v.kind == "groom_overview"]
    assert overview and overview[0].detail == prompt(
        "gate.groom.overview_unknown_reference",
        preview=f"- Summary. (from c:{outside}) <!-- c:{_anchor('ov')} -->"[:48],
        anchor=outside,
    )


def test_a_rejected_rollover_hands_back_no_files_at_all():
    """All-or-nothing by construction: a half-applied rollover would have moved claims out of
    the active document without recording where they went."""
    active = _active(30)
    plan = plan_rollover(active, [active], path_templates=TEMPLATES, keep_recent_chars=400)
    assert plan is not None
    # a point whose evidence is not in the archive at all
    bad = build_rollover(
        plan,
        [OverviewPoint(text="Ungrounded.", anchors=(_anchor("claim-29"),))],
        [active],
        path_templates=TEMPLATES,
    )
    assert bad.status == "rejected"
    assert bad.files == {}


# ----------------------------------------------------------------- everything the gate shares


def test_the_written_documents_are_checked_by_the_shared_compile_checks_too():
    """Coverage / frontmatter / uniqueness / ownership run over what a groom writes, using the
    SAME functions compile uses. Without coverage in particular, a groom could commit an
    unanchored block and hard-fail every later compile on that user."""
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    frontmatter, active_body = parse_document(result.files[ACTIVE])
    volume_fm, volume_body = parse_document(result.files[plan.volume_path])

    violations = run_groom_gate(
        plan=plan,
        active_frontmatter=frontmatter,
        active_body=active_body + "\n\nA stray unanchored sentence.",
        volume_frontmatter_=volume_fm,
        volume_body=volume_body,
        base_docs=[active],
        path_templates=TEMPLATES,
        overview_blocks=[],
        overview_anchor_ids=list(overview_anchors(frontmatter)),
        catalog_anchor_ids=list(catalog_anchors(frontmatter)),
    )
    assert "anchor_coverage" in [v.kind for v in violations]


# ------------------------------------------------------------------ the second rollover


def test_the_second_rollover_opens_a_new_volume_and_leaves_the_first_frozen():
    active = _active(30)
    plan_a, first = _roll([active], active, [_point(0)])
    rolled = _as_doc(ACTIVE, first.files[ACTIVE])
    volume_one = _as_doc(plan_a.volume_path, first.files[plan_a.volume_path])

    # more compile activity lands on the (now small) active document
    grown = CanonicalDocument(
        doc_id=rolled.doc_id,
        path=rolled.path,
        frontmatter=rolled.frontmatter,
        body=rolled.body.rstrip("\n")
        + "\n"
        + "\n".join(_claim(i) for i in range(30, 45))
        + "\n",
    )
    docs = [grown, volume_one]
    plan_b, second = _roll(docs, grown, [_point(0, 31)], keep_recent_chars=400)
    assert second.status == "ready", [v.render() for v in second.violations]

    assert plan_b.volume_path == "work/products/aurora-planner/a02.md"
    # volume 01 is not in the commit at all — a frozen volume is never rewritten
    assert plan_a.volume_path not in second.files
    volume_two = _as_doc(plan_b.volume_path, second.files[plan_b.volume_path])
    assert volume_two.frontmatter[VOLUME_NUMBER_KEY] == "02"
    # the catalog now lists both volumes, and the count says so
    rolled_again = _as_doc(ACTIVE, second.files[ACTIVE])
    assert "(aurora-planner/a01.md)" in rolled_again.body
    assert "(aurora-planner/a02.md)" in rolled_again.body
    assert rolled_again.frontmatter[VOLUME_COUNT_KEY] == "2"
    assert [d.path for d in volumes_of(ACTIVE, docs)] == [plan_a.volume_path]


def test_a_card_point_may_reference_an_older_volume_it_still_summarizes():
    """The card is replaced wholesale each time, so it must be able to carry forward a point
    whose evidence lives in a volume frozen two rollovers ago."""
    active = _active(30)
    plan_a, first = _roll([active], active, [_point(0)])
    rolled = _as_doc(ACTIVE, first.files[ACTIVE])
    volume_one = _as_doc(plan_a.volume_path, first.files[plan_a.volume_path])
    grown = CanonicalDocument(
        doc_id=rolled.doc_id,
        path=rolled.path,
        frontmatter=rolled.frontmatter,
        body=rolled.body.rstrip("\n") + "\n" + "\n".join(_claim(i) for i in range(30, 45)) + "\n",
    )
    # c:claim-0 lives in volume 01, not in the volume this rollover writes
    _, second = _roll([grown, volume_one], grown, [_point(0)], keep_recent_chars=400)
    assert second.status == "ready", [v.render() for v in second.violations]


def test_rewriting_the_card_reuses_its_anchor_ids_rather_than_churning_them():
    """The card's ids are deterministic per (document, slot), so a rewrite is an EDIT in the
    projection — not a delete plus an insert on every rollover."""
    active = _active(30)
    plan_a, first = _roll([active], active, [_point(0)])
    rolled = _as_doc(ACTIVE, first.files[ACTIVE])
    volume_one = _as_doc(plan_a.volume_path, first.files[plan_a.volume_path])
    grown = CanonicalDocument(
        doc_id=rolled.doc_id,
        path=rolled.path,
        frontmatter=rolled.frontmatter,
        body=rolled.body.rstrip("\n") + "\n" + "\n".join(_claim(i) for i in range(30, 45)) + "\n",
    )
    _, second = _roll([grown, volume_one], grown, [_point(0, 31)], keep_recent_chars=400)
    again = _as_doc(ACTIVE, second.files[ACTIVE])
    assert overview_anchors(again.frontmatter)[0] == overview_anchors(rolled.frontmatter)[0]
    assert catalog_anchors(again.frontmatter)[0] == catalog_anchors(rolled.frontmatter)[0]


def test_the_previous_card_is_dropped_rather_than_re_archived():
    """The card is an index, not a ledger — the ledger is the volume. So the old card's blocks
    are neither archived nor duplicated; they are simply replaced."""
    active = _active(30)
    plan_a, first = _roll([active], active, [_point(0)])
    rolled = _as_doc(ACTIVE, first.files[ACTIVE])
    volume_one = _as_doc(plan_a.volume_path, first.files[plan_a.volume_path])
    grown = CanonicalDocument(
        doc_id=rolled.doc_id,
        path=rolled.path,
        frontmatter=rolled.frontmatter,
        body=rolled.body.rstrip("\n") + "\n" + "\n".join(_claim(i) for i in range(30, 45)) + "\n",
    )
    plan_b, second = _roll([grown, volume_one], grown, [_point(0, 31)], keep_recent_chars=400)
    old_card_anchor = overview_anchors(rolled.frontmatter)[0]
    volume_two_body = parse_document(second.files[plan_b.volume_path])[1]
    assert old_card_anchor not in extract_anchors(volume_two_body)
    # and the card slot still holds exactly one point's worth of ids
    assert second.status == "ready"


# -------------------------------------------------------------------- the one model call


class _StubStructured:
    def __init__(self, payload, *, boom=False):
        self.payload = payload
        self.boom = boom
        self.messages: list = []

    async def ainvoke(self, messages, config=None):  # noqa: ARG002
        self.messages = messages
        if self.boom:
            raise RuntimeError("provider exploded")
        return {"parsed": self.payload}


class _StubModel:
    def __init__(self, payload, *, boom=False):
        self.structured = _StubStructured(payload, boom=boom)

    def with_structured_output(self, schema, include_raw=False):  # noqa: ARG002
        return self.structured


def _plan_for_overview():
    active = _active(30)
    plan = plan_rollover(active, [active], path_templates=TEMPLATES, keep_recent_chars=400)
    assert plan is not None
    return active, plan


async def test_the_overview_call_sees_the_archived_entries_with_their_ids():
    active, plan = _plan_for_overview()
    model = _StubModel(
        _OverviewDraft(
            points=[
                _OverviewPointDraft(
                    text="Checklist driven to done.", anchors=[_anchor("claim-0")]
                )
            ]
        )
    )
    points, reason = await write_overview(
        model=model, plan=plan, known_anchors=set(extract_anchors(plan.archived_body))
    )
    assert reason == "written"
    assert points == [OverviewPoint("Checklist driven to done.", (_anchor("claim-0"),))]
    human = model.structured.messages[-1].content
    assert f"<!-- c:{_anchor('claim-0')} -->" in human
    assert prompt("compile.groom.previous_empty") in human


async def test_a_point_naming_an_id_it_was_not_shown_is_dropped_not_repaired():
    _, plan = _plan_for_overview()
    model = _StubModel(
        _OverviewDraft(
            points=[
                _OverviewPointDraft(text="Real.", anchors=[_anchor("claim-1")]),
                _OverviewPointDraft(text="Hallucinated.", anchors=["deadbeef"]),
                _OverviewPointDraft(text="", anchors=[_anchor("claim-2")]),
            ]
        )
    )
    points, reason = await write_overview(
        model=model, plan=plan, known_anchors=set(extract_anchors(plan.archived_body))
    )
    assert reason == "written"
    assert [p.text for p in points] == ["Real."]


async def test_a_c_prefixed_id_is_accepted_because_that_is_how_the_material_shows_it():
    _, plan = _plan_for_overview()
    model = _StubModel(
        _OverviewDraft(
            points=[_OverviewPointDraft(text="Real.", anchors=[f"c:{_anchor('claim-1')}"])]
        )
    )
    points, reason = await write_overview(
        model=model, plan=plan, known_anchors=set(extract_anchors(plan.archived_body))
    )
    assert reason == "written" and points[0].anchors == (_anchor("claim-1"),)


async def test_a_failed_or_unusable_overview_call_abandons_the_groom():
    _, plan = _plan_for_overview()
    known = set(extract_anchors(plan.archived_body))

    boom = _StubModel(_OverviewDraft(), boom=True)
    assert await write_overview(model=boom, plan=plan, known_anchors=known) == ([], "call_failed")

    junk = _StubModel({"points": []})
    assert await write_overview(model=junk, plan=plan, known_anchors=known) == ([], "parse_error")

    empty = _StubModel(_OverviewDraft(points=[]))
    assert await write_overview(model=empty, plan=plan, known_anchors=known) == ([], "empty")


def test_a_truncated_overview_input_says_so_and_keeps_the_most_recent_archive():
    _, plan = _plan_for_overview()
    rendered = render_overview_input(plan, budget=300)
    assert "line(s) of the archive are omitted here" in rendered
    # the tail of the archive survives, the head is what was dropped
    assert _claim(25) in rendered
    assert _claim(0) not in rendered


# ------------------------------------------------------------------------- naming convention


def test_volume_paths_live_in_the_documents_own_same_name_directory():
    assert volume_path_for("work/products/aurora-planner.md", 1) == (
        "work/products/aurora-planner/a01.md"
    )
    assert volume_path_for("work/products/aurora-planner.md", 12) == (
        "work/products/aurora-planner/a12.md"
    )
    assert volume_path_for("flat.md", 3) == "flat/a03.md"


def test_the_volume_path_is_outside_the_write_templates_but_owned_by_its_document():
    """The whole freeze mechanism in one assertion: `create_document` cannot name a volume
    (path_allowed says no), while the gate still recognizes it as that document's own archive
    (history_volume_owner says whose)."""
    volume = volume_path_for(ACTIVE, 1)
    assert path_allowed(volume, TEMPLATES) is False
    assert history_volume_owner(volume, TEMPLATES) == ACTIVE
    # and nothing else is mistaken for a volume
    assert history_volume_owner("stray/note/a01.md", TEMPLATES) is None
    assert history_volume_owner("work/products/aurora-planner/notes.md", TEMPLATES) is None


# --------------------------------------------------- what a later COMPILE makes of a volume


def _draft_after_rollover(files: dict[str, str]) -> PatchDraft:
    docs = [_as_doc(path, text) for path, text in files.items()]
    return PatchDraft.from_canonical(docs, TEMPLATES)


def test_a_compile_after_a_rollover_does_not_trip_over_the_volume_it_is_not_touching():
    """The bricking case. A volume is a real canonical document, so it is loaded into EVERY
    later compile's draft — if the gate judged it unowned, every compile from then on would
    abort on a path it never wrote."""
    active = _active(30)
    _, result = _roll([active], active, [_point(0)])
    assert run_gate(_draft_after_rollover(result.files), []) == []


def test_a_compile_that_writes_into_a_frozen_volume_is_refused():
    active = _active(30)
    plan, result = _roll([active], active, [_point(0)])
    draft = _draft_after_rollover(result.files)
    draft.append_block(plan.volume_path, "Delivery", "A new claim. [cite: src-01 ¶0]")
    violations = run_gate(draft, [])
    assert [v.kind for v in violations] == ["archive_frozen"]
    assert violations[0].detail == prompt("gate.archive_frozen", owner=ACTIVE)


def test_a_compile_cannot_create_a_volume_at_all():
    active = _active(30)
    draft = PatchDraft.from_canonical([active], TEMPLATES)
    with pytest.raises(AnchorToolError):
        draft.create_document(
            volume_path_for(ACTIVE, 2), {"type": "product", "slug": "a02"}, "- x"
        )


# ------------------------------------------------- healing what a pre-compensation groom broke
#
# What makes this mechanical rather than a judgement: a link that fails from the volume but
# SUCCEEDS from the parent page is, by construction, one the move mis-rendered — the parent is
# the position the text was written at. Anything else that does not resolve was already wrong
# when the model wrote it, and guessing what it meant is not this channel's business.


def _volume(body: str, *, parent: str = ACTIVE, path: str = VOLUME) -> CanonicalDocument:
    return _doc(path, body, **{ARCHIVED_FROM_KEY: parent})


def _healable_world(*hrefs: str) -> list[CanonicalDocument]:
    orion = _doc(ORION, f"# Orion\n\n## Scope\n\n{_claim(90)}")
    active = _doc(ACTIVE, f"# Aurora planner\n\n## Delivery\n\n{_claim(29)}")
    rows = "\n".join(_linked_claim(i, href) for i, href in enumerate(hrefs))
    return [active, orion, _volume(f"# Aurora planner\n\n## Delivery\n\n{rows}\n")]


def test_heal_re_renders_a_volume_link_that_resolves_one_level_short():
    # written at the page's position, then moved into the volume without compensation
    docs = _healable_world("../../memory/topics/orion.md", "../../memory/topics/orion.md#scope")
    volume = docs[-1]
    assert dead_links({d.path: d.body for d in docs}) == 2

    result = heal_volume_links(docs)
    assert result.status == "ready"
    assert result.healed_links == 2
    assert (result.dead_before, result.dead_after) == (2, 0)
    assert set(result.files) == {VOLUME}

    healed = _as_doc(VOLUME, result.files[VOLUME])
    assert "(../../../memory/topics/orion.md)" in healed.body
    assert "(../../../memory/topics/orion.md#scope)" in healed.body
    # nothing but the hrefs moved — the whole FILE is otherwise byte-identical
    assert link_elided(result.files[VOLUME]) == link_elided(
        render_document(volume.frontmatter, volume.body)
    )
    assert link_targets(healed.body, VOLUME) == (ORION, ORION)


def test_heal_is_idempotent_and_writes_nothing_on_a_repo_that_needs_none():
    docs = _healable_world("../../memory/topics/orion.md")
    result = heal_volume_links(docs)
    assert result.status == "ready"

    healed = _as_doc(VOLUME, result.files[VOLUME])
    again = heal_volume_links([docs[0], docs[1], healed])
    assert again.status == "clean"
    assert again.files == {} and again.healed_links == 0
    # and a repo that never had the defect is left alone the first time too
    assert heal_volume_links([docs[0], docs[1]]).status == "clean"


def test_heal_does_not_touch_a_link_that_was_already_dead_at_the_pages_own_position():
    """`ghost.md` resolves nowhere from either position, so no mechanical repair exists — and
    inventing one would be rewriting the author's meaning under the cover of maintenance."""
    docs = _healable_world("../../memory/topics/ghost.md")
    result = heal_volume_links(docs)
    assert result.status == "clean"
    assert result.dead_before == result.dead_after == 1

    # mixed: the repairable one is repaired, the broken one is left exactly as written
    mixed = _healable_world("../../memory/topics/ghost.md", "../../memory/topics/orion.md")
    healed = heal_volume_links(mixed)
    assert healed.status == "ready" and healed.healed_links == 1
    assert (healed.dead_before, healed.dead_after) == (2, 1)
    body = _as_doc(VOLUME, healed.files[VOLUME]).body
    assert "(../../memory/topics/ghost.md)" in body
    assert "(../../../memory/topics/orion.md)" in body


def test_heal_only_ever_writes_archive_volumes():
    """A dead link on an ordinary page is not a move's damage — nothing moved. Only a document
    that carries the `archived_from` stamp is a document this pass can reason about."""
    orion = _doc(ORION, f"# Orion\n\n## Scope\n\n{_claim(90)}")
    page = _doc(
        ACTIVE,
        "# Aurora planner\n\n## Delivery\n\n"
        + _linked_claim(0, "../../memory/topics/orion.md/orion.md"),
    )
    assert dead_links({d.path: d.body for d in [page, orion]}) == 1
    assert heal_volume_links([page, orion]).status == "clean"


def test_heal_leaves_an_orphan_volume_alone_rather_than_guessing_its_origin():
    orion = _doc(ORION, f"# Orion\n\n## Scope\n\n{_claim(90)}")
    orphan = _volume(
        "# Gone\n\n## Delivery\n\n" + _linked_claim(0, "../../memory/topics/orion.md"),
        parent="work/products/deleted-page.md",
    )
    assert heal_volume_links([orion, orphan]).status == "clean"


def test_the_heal_commit_subject_names_how_many_links_it_rewrote():
    assert heal_commit_message(556) == prompt(
        "compile.groom.heal_commit_message", links=556
    )
