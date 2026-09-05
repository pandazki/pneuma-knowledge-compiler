"""The document OVERVIEW: a bounded, grounded head over the append-only ledger.

The overview is the one region a compile may rewrite WHOLE, and every test here exists to
hold one half of why that is safe: the ledger below it never moves, and nothing in it is
allowed to say something the ledger does not already carry.
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_core.canonical_glance import (
    claim_count,
    document_definition,
    render_canonical_glance,
    render_outline,
)
from pneuma_knowledge_core.compile.anchor_ops import (
    AnchorToolError,
    assign_document_anchors,
    unanchored_blocks,
)
from pneuma_knowledge_core.compile.documents import (
    Connection,
    Overview,
    overview_region,
    parse_overview,
    render_overview,
    set_overview_region,
    strip_overview,
)
from pneuma_knowledge_core.compile.gate import run_gate
from pneuma_knowledge_core.compile.overview import (
    DEFINITION_MAX_CHARS,
    OVERVIEW_BUDGET_CHARS,
    ledger_anchors,
    overview_anchors,
)
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.rollover import plan_rollover, render_active_body
from pneuma_knowledge_core.compile.transitions import derive_events
from pneuma_knowledge_core.components import (
    BaseComponent,
    register_component,
    reset_components,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, extract_anchors
from pneuma_knowledge_core.recall.projection import project_document_claims

TEMPLATES = ["memory/people/{slug}.md", "work/products/{slug}.md"]

PERSON = "memory/people/mei-lin.md"
PRODUCT = "work/products/aurora.md"

PERSON_BODY = (
    "# Mei Lin\n"
    "\n"
    "## Role\n"
    "\n"
    "- Mei Lin has led supplier qualification for the Aurora line since 2025-03. "
    "[cite: s01 ¶2-3] <!-- c:11aa22bb -->\n"
    "\n"
    "## Working style\n"
    "\n"
    "- She wants a written decision record before a supplier review. "
    "[cite: s01 ¶7] <!-- c:33cc44dd -->\n"
)

PRODUCT_BODY = (
    "# Aurora\n"
    "\n"
    "## Supply\n"
    "\n"
    "- Aurora's supplier shortlist was cut to three in 2026-01. "
    "[cite: s01 ¶11] <!-- c:55ee66ff -->\n"
)


def _doc(path: str, body: str, doc_id: str) -> CanonicalDocument:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    return CanonicalDocument(
        path=path,
        doc_id=DocumentId(doc_id),
        frontmatter={"doc_id": doc_id, "type": "person", "slug": slug},
        body=body,
    )


def _base() -> list[CanonicalDocument]:
    return [
        _doc(PERSON, PERSON_BODY, "a1b2c3d4e5f6"),
        _doc(PRODUCT, PRODUCT_BODY, "f6e5d4c3b2a1"),
    ]


def _from_canonical(*args, **kwargs) -> PatchDraft:
    """A draft whose every document counts as READ this round.

    These tests drive the write faces directly; marking a path read is `read_document`'s
    job inside the compile loop, and the refusal that enforces it has its own test below.
    """
    draft = PatchDraft.from_canonical(*args, **kwargs)
    for path in draft.list_paths():
        draft.mark_read(path)
    return draft


def _draft() -> PatchDraft:
    return _from_canonical(_base(), TEMPLATES)


def _poke_overview(draft: PatchDraft, path: str, overview: Overview) -> str:
    """Write a region straight into the draft, around the write tool.

    The tool face refuses these regions now, which is the point of it — so the only way left
    to ask "does the GATE still refuse this?" is to splice the region in by hand. That is not
    an artificial question: an evolve merge, a rollover, a restored repository and any future
    write path all reach the gate without passing through `rewrite_overview`, and the gate is
    the final arbiter precisely for them.
    """
    doc = draft.read(path)
    region = assign_document_anchors(
        render_overview(overview, document_path=path), path
    )
    doc.body = set_overview_region(doc.body, region)
    return doc.body


def _overview(**kwargs) -> Overview:
    fields = {
        "definition": "Mei Lin leads supplier qualification for Aurora. c:11aa22bb",
        "summary": "She has run qualification since 2025-03. c:11aa22bb",
        "introduction": "She entered the record through the Aurora supply thread. c:33cc44dd",
        "connections": (Connection(PRODUCT, "she qualifies its suppliers. c:55ee66ff"),),
    }
    fields.update(kwargs)
    return Overview(**fields)


@pytest.mark.parametrize("basis", ["c:11aa22bb", "[cite: s01 ¶2-3]"])
@pytest.mark.parametrize("channel", ["compile", "evolve"])
async def test_every_overview_reference_must_resolve_even_beside_valid_provenance(basis, channel):
    draft = _draft()
    overview = _overview(definition=f"Mei Lin leads qualification. {basis} c:deadbeef")
    with pytest.raises(AnchorToolError, match="deadbeef"):
        draft.rewrite_overview(PERSON, overview)
    _poke_overview(draft, PERSON, overview)
    if channel == "compile":
        violations = run_gate(draft, [])
    else:
        from pneuma_knowledge_core.evolve.gate import run_evolve_gate

        async def bounds(source_id):
            assert source_id == "s01"
            return 12

        violations, _ = await run_evolve_gate(draft, source_bounds=bounds, path_templates=TEMPLATES)
    assert any(v.kind == "overview" and "deadbeef" in v.detail for v in violations)


def test_untouched_overview_with_dangling_reference_blocks_commit():
    draft = _draft()
    body = _poke_overview(draft, PERSON, _overview(definition="Legacy head. c:deadbeef"))
    draft = _from_canonical([_doc(PERSON, body, "a1b2c3d4e5f6")], TEMPLATES)
    draft.edit_claim(PERSON, "11aa22bb", "Mei Lin leads qualification. [cite: s01 ¶2-3]")
    assert any(v.kind == "overview" and "deadbeef" in v.detail for v in run_gate(draft, []))


# ───────────────────────────────────────────────────────── documents: (de)serialization


def test_render_and_parse_round_trip_through_the_region():
    overview = _overview()
    region = render_overview(overview, document_path=PERSON)
    body = set_overview_region(PERSON_BODY, region)
    parsed, ledger = parse_overview(body)
    assert parsed == overview
    assert ledger == PERSON_BODY


def test_a_document_without_the_region_parses_as_none_and_is_untouched():
    parsed, ledger = parse_overview(PERSON_BODY)
    assert parsed is None
    assert ledger == PERSON_BODY
    assert overview_region(PERSON_BODY) == ""
    assert strip_overview(PERSON_BODY) == PERSON_BODY


def test_the_region_markers_are_structure_and_never_orphan_claims():
    """A marker line carries no anchor. If a block walker treated it as content, every
    document with an overview would fail the gate's anchor-coverage check."""
    draft = _draft()
    doc = draft.rewrite_overview(PERSON, _overview())
    assert unanchored_blocks(doc.body) == []
    assert run_gate(draft, []) == []


# ─────────────────────────────────────────────────────────────────── patch: the write


def test_rewrite_overview_replaces_the_region_and_leaves_the_ledger_byte_identical():
    draft = _draft()
    first = draft.rewrite_overview(PERSON, _overview())
    first_anchors = overview_anchors(first.body)
    assert first_anchors and len(first_anchors) == 4

    second = draft.rewrite_overview(
        PERSON, _overview(summary="She now also owns the audit trail. c:33cc44dd")
    )
    # The region was written whole and re-anchored from scratch. Anchors are
    # content-addressed, so the three untouched slots land on the ids they already had and
    # only the rewritten one changes — a rewrite is not obliged to churn identity it did not
    # actually change.
    assert "She now also owns the audit trail." in second.body
    assert len(overview_anchors(second.body) - first_anchors) == 1
    assert len(first_anchors - overview_anchors(second.body)) == 1
    # … and the ledger below is byte-for-byte what it was before either call
    assert parse_overview(second.body)[1] == PERSON_BODY
    assert ledger_anchors(second.body) == {"11aa22bb", "33cc44dd"}


def test_rewrite_overview_creates_the_region_under_the_title():
    draft = _draft()
    doc = draft.rewrite_overview(PERSON, _overview())
    lines = doc.body.split("\n")
    assert lines[0] == "# Mei Lin"
    assert "<!-- overview -->" in lines[:4]
    assert lines.index("## Role") > lines.index("<!-- /overview -->")


def test_rewrite_overview_refuses_a_rollover_volume():
    volume = CanonicalDocument(
        path="work/products/aurora/a01.md",
        doc_id=DocumentId("v1"),
        frontmatter={"doc_id": "v1", "type": "product", "slug": "a01"},
        body="# Aurora\n\n- old. [cite: s01 ¶1] <!-- c:99887766 -->\n",
    )
    draft = _from_canonical([*_base(), volume], TEMPLATES)
    with pytest.raises(AnchorToolError) as err:
        draft.rewrite_overview("work/products/aurora/a01.md", _overview())
    assert "closed volume" in str(err.value)


def test_an_entirely_empty_rewrite_removes_the_region_and_keeps_the_ledger():
    """The fourth outcome. A picture the round decided the subject no longer has is DROPPED —
    the region goes, the claims below it do not, and the document is still a document."""
    draft = _draft()
    ledger = [
        line for line in draft.read(PERSON).body.splitlines() if line.startswith("- ")
    ]
    draft.rewrite_overview(PERSON, _overview())
    assert overview_region(draft.read(PERSON).body)
    doc = draft.rewrite_overview(
        PERSON, Overview(definition="", summary="", introduction="", connections=())
    )
    assert overview_region(doc.body) == ""
    assert [line for line in doc.body.splitlines() if line.startswith("- ")] == ledger
    assert doc.body.startswith("# ")
    # dropping the picture IS a rewrite of it — the document still reports one event
    committed = _from_canonical(_base(), TEMPLATES)
    committed.mark_read(PERSON)
    committed.rewrite_overview(PERSON, _overview())
    with_region = dict(committed.new_bodies())
    committed.rewrite_overview(PERSON, Overview())
    events = derive_events(with_region, committed.new_bodies())
    assert [e.type for e in events] == ["overview_rewritten"]
    assert events[0].path == PERSON and not events[0].after
    # …and the same empty call WITH fields is a fields-only write: the region stands.
    draft.rewrite_overview(PERSON, _overview())
    doc = draft.rewrite_overview(PERSON, Overview(), fields={"employer": "Northwind"})
    assert doc.frontmatter["employer"] == "Northwind"
    assert overview_region(doc.body)


def test_the_whole_region_writes_refuse_a_document_this_round_never_read():
    """Keep / merge / rewrite / drop is a judgement over what already stands there — so the
    two whole-region writes refuse a path this compile has not looked at. `create_document`
    counts as reading: its author has the document in hand."""
    draft = PatchDraft.from_canonical(_base(), TEMPLATES)
    for call in (
        lambda: draft.rewrite_overview(PERSON, _overview()),
        lambda: draft.set_fields(PERSON, {"employer": "Northwind"}),
    ):
        with pytest.raises(AnchorToolError) as err:
            call()
        assert "was not read in this compile" in str(err.value)
        assert "read_document" in str(err.value)
    draft.mark_read(PERSON)
    assert overview_region(draft.rewrite_overview(PERSON, _overview()).body)
    fresh = PatchDraft.from_canonical(_base(), TEMPLATES)
    fresh.create_document(
        "memory/people/lin-jia.md", {"type": "person", "slug": "lin-jia"}, "# Lin Jia\n"
    )
    assert fresh.set_fields("memory/people/lin-jia.md", {"employer": "Northwind"})


def test_a_dressed_up_ledger_reference_is_stored_as_a_bare_anchor():
    """`[cite: c:xxxx]` is a ledger reference wearing the source-locator's brackets.

    A real model wrote exactly that, collected `citation_anchor_in_marker` from the gate and
    burned four repair turns on it. The intent is unambiguous — an anchor list inside a
    wrapper is an anchor list — so the wrapper comes off at the write boundary and the gate
    never sees it.
    """
    draft = _draft()
    doc = draft.rewrite_overview(
        PERSON,
        Overview(
            definition="Mei Lin qualifies Aurora's suppliers. [cite: c:11aa22bb]",
            summary="She has run it since 2025-03. [cite: c:11aa22bb; c:33cc44dd]",
            # Full-width parentheses too: the wrapper is not the point in either script.
            introduction="She entered through the supply thread. （c:33cc44dd）",
            connections=(Connection(PRODUCT, "she qualifies its suppliers. c:55ee66ff"),),
        ),
    )
    region = overview_region(doc.body)
    assert "[cite: c:" not in region
    assert "(c:" not in region and "（c:" not in region
    assert "suppliers. c:11aa22bb" in region
    assert "since 2025-03. c:11aa22bb; c:33cc44dd" in region
    assert "supply thread. c:33cc44dd" in region
    assert run_gate(draft, []) == []


def test_a_real_source_citation_in_an_overview_survives_byte_for_byte():
    """The normalization is a shape fix, never a repair of meaning: a locator is a locator.

    Citing a source span is a legitimate second way to ground an overview block, and a
    malformed one must still reach the gate — the only thing that can judge it.
    """
    draft = _draft()
    doc = draft.rewrite_overview(
        PERSON,
        Overview(
            definition="Mei Lin qualifies Aurora's suppliers. [cite: s01 ¶2-3]",
            summary="Written decisions first. [cite: s01 ¶7]",
        ),
    )
    region = overview_region(doc.body)
    assert "[cite: s01 ¶2-3]" in region
    assert "[cite: s01 ¶7]" in region


def test_overview_anchors_never_collide_with_another_document():
    draft = _draft()
    draft.rewrite_overview(PERSON, _overview())
    draft.rewrite_overview(
        PRODUCT,
        Overview(definition="Aurora is a product line. c:55ee66ff"),
    )
    seen: set[str] = set()
    for doc in draft.documents().values():
        for anchor in extract_anchors(doc.body):
            assert anchor not in seen
            seen.add(anchor)


# ───────────────────────────────────────────────────────────── patch: set_fields


def test_set_fields_writes_extras_and_refuses_the_system_owned_ones():
    draft = _draft()
    doc = draft.set_fields(PERSON, {"employer": "Northwind", "updated": "2026-08-01"})
    assert doc.frontmatter["employer"] == "Northwind"
    for reserved in ("doc_id", "type", "slug"):
        with pytest.raises(AnchorToolError) as err:
            draft.set_fields(PERSON, {reserved: "x"})
        assert "assigned by the system" in str(err.value)


def test_a_component_refuses_a_field_it_can_prove_wrong_at_both_write_faces():
    """The component's say over structured fields. It judges FACTS, not the model's picture:
    what it cannot prove wrong goes straight in, and the same door serves both writes."""

    class People(BaseComponent):
        name = "people"

        def validate_fields(self, path, fields, docs):
            return [
                f"identity {value} is already bound to `work/people/other.md`."
                for key, value in fields.items()
                if key == "identities"
            ]

    register_component(People())
    try:
        draft = _draft()
        for call in (
            lambda: draft.set_fields(PERSON, {"identities": "im:1"}),
            lambda: draft.rewrite_overview(PERSON, _overview(), {"identities": "im:1"}),
        ):
            with pytest.raises(AnchorToolError) as err:
                call()
            assert "already bound to `work/people/other.md`" in str(err.value)
        assert "identities" not in draft.read(PERSON).frontmatter
        # nothing written by the refused rewrite either — the region is still absent
        assert overview_region(draft.read(PERSON).body) == ""
        # a field it says nothing about lands, on both faces
        assert draft.set_fields(PERSON, {"employer": "Northwind"}).frontmatter[
            "employer"
        ] == "Northwind"
        assert draft.rewrite_overview(
            PERSON, _overview(), {"aliases": "Mei"}
        ).frontmatter["aliases"] == "Mei"
    finally:
        reset_components()


# ──────────────────────────────────────── the tool face: the overview's rules, early
#
# The same rules the gate arbitrates, refused at `rewrite_overview` before a byte is written.
# The gate learning them for the first time costs a whole repair round and often the compile;
# these tests hold the early refusal to three things: it names the rule, it names every
# failing block at once, and it writes NOTHING.


def test_the_tool_face_refuses_a_connection_item_that_rests_on_nothing():
    """The single most common miss in a live build: a connection written as a bare link and a
    relation, grounded on nothing. It is overview prose like any other and grounds like it."""
    draft = _draft()
    before = draft.read(PERSON).body
    with pytest.raises(AnchorToolError) as err:
        draft.rewrite_overview(
            PERSON,
            Overview(
                definition="Mei Lin leads supplier qualification. c:11aa22bb",
                connections=(Connection(PRODUCT, "she qualifies its suppliers."),),
            ),
        )
    message = str(err.value)
    assert "connections: " in message
    assert "she qualifies its suppliers." in message
    assert "rests on nothing" in message
    assert "c:xxxx" in message
    # nothing was written: the head is exactly as it stood
    assert draft.read(PERSON).body == before


def test_the_tool_face_refuses_an_over_budget_overview_and_states_both_numbers():
    """The refusal is only teachable if it says how big the region came out and how big it
    may be — a model told "too long" writes something else too long."""
    over = _overview(summary=("She reviews suppliers. c:11aa22bb " * 100))
    # the region the call WOULD have written, measured the way the gate measures it
    measured = overview_region(_poke_overview(_draft(), PERSON, over))
    assert len(measured) > OVERVIEW_BUDGET_CHARS

    draft = _draft()
    before = draft.read(PERSON).body
    with pytest.raises(AnchorToolError) as err:
        draft.rewrite_overview(PERSON, over)
    message = str(err.value)
    assert f"renders to {len(measured)} characters" in message
    assert f"over the {OVERVIEW_BUDGET_CHARS}-character budget" in message
    assert draft.read(PERSON).body == before


def test_the_tool_face_refuses_by_the_configured_budget_not_the_default():
    """One ceiling for the region. A deployment that moved the knob moved it at both ends —
    otherwise the tool face refuses what the gate would have accepted, or the reverse."""
    overview = _overview(summary="She has run qualification since 2025-03. c:11aa22bb")
    tight = _from_canonical(_base(), TEMPLATES, overview_budget_chars=200)
    with pytest.raises(AnchorToolError) as err:
        tight.rewrite_overview(PERSON, overview)
    assert "over the 200-character budget" in str(err.value)
    # and the same call at the default ceiling is an ordinary write
    assert overview_region(_draft().rewrite_overview(PERSON, overview).body)


def test_the_tool_face_refuses_an_over_long_definition():
    draft = _draft()
    before = draft.read(PERSON).body
    with pytest.raises(AnchorToolError) as err:
        draft.rewrite_overview(
            PERSON,
            Overview(
                definition="Mei Lin "
                + ("leads supplier qualification " * 12)
                + "c:11aa22bb"
            ),
        )
    message = str(err.value)
    assert f"over the {DEFINITION_MAX_CHARS}-character limit" in message
    assert message.count("definition: ") == 1
    assert draft.read(PERSON).body == before


def test_the_tool_face_refuses_a_definition_that_is_more_than_one_block():
    draft = _draft()
    with pytest.raises(AnchorToolError) as err:
        draft.rewrite_overview(
            PERSON,
            Overview(
                definition=(
                    "Mei Lin leads supplier qualification. c:11aa22bb\n"
                    "\n"
                    "She has done so since 2025-03. c:11aa22bb"
                )
            ),
        )
    assert "definition: it is 2 blocks" in str(err.value)


def test_the_tool_face_refuses_a_connection_to_a_document_that_does_not_exist():
    """A connection to a subject the model believes ought to exist is the dead link the gate
    used to catch a whole round later. The refusal names the resolved target and the fix."""
    draft = _draft()
    before = draft.read(PERSON).body
    with pytest.raises(AnchorToolError) as err:
        draft.rewrite_overview(
            PERSON,
            Overview(
                definition="Mei Lin leads supplier qualification. c:11aa22bb",
                connections=(
                    Connection("work/products/nowhere.md", "she owns it. c:11aa22bb"),
                ),
            ),
        )
    message = str(err.value)
    assert "`work/products/nowhere.md`" in message
    assert "create it first" in message
    assert draft.read(PERSON).body == before


def test_the_tool_face_accepts_a_connection_to_a_document_created_this_round():
    """"Exists" is judged against the DRAFT, so a page created earlier in the same round is a
    legal target — the model does not have to compile it twice to link to it."""
    draft = _draft()
    draft.create_document(
        "work/products/beacon.md",
        {"type": "product", "slug": "beacon"},
        "# Beacon\n\n## Supply\n\n- Beacon shares Aurora's shortlist. [cite: s01 ¶12]\n",
    )
    doc = draft.rewrite_overview(
        PERSON,
        Overview(
            definition="Mei Lin leads supplier qualification. c:11aa22bb",
            connections=(
                Connection("work/products/beacon.md", "she qualifies its suppliers. c:11aa22bb"),
            ),
        ),
    )
    assert "work/products/beacon.md" in overview_region(doc.body)


def test_the_tool_face_refuses_a_connection_to_the_document_itself():
    draft = _draft()
    with pytest.raises(AnchorToolError) as err:
        draft.rewrite_overview(
            PERSON,
            Overview(
                definition="Mei Lin leads supplier qualification. c:11aa22bb",
                connections=(Connection(PERSON, "she is herself. c:11aa22bb"),),
            ),
        )
    assert "itself" in str(err.value)


def test_the_tool_face_lists_every_failing_block_in_one_refusal():
    """One rule per round is three rounds. The whole call is refused, and every failing block
    is named at once with its slot and a quote of it."""
    draft = _draft()
    before = draft.read(PERSON).body
    with pytest.raises(AnchorToolError) as err:
        draft.rewrite_overview(
            PERSON,
            Overview(
                definition="Mei Lin is widely respected.",
                summary="She reviews every supplier personally.",
                introduction="She entered through the supply thread. c:33cc44dd",
                connections=(
                    Connection("work/products/nowhere.md", "she owns it."),
                ),
            ),
        )
    message = str(err.value)
    assert "was NOT written" in message
    for quoted in (
        "Mei Lin is widely respected.",
        "She reviews every supplier personally.",
        "she owns it.",
    ):
        assert quoted in message
    # the one grounded block is not named
    assert "She entered through the supply thread." not in message
    # four failing points: three ungrounded blocks and one dead connection target
    assert len([line for line in message.split("\n") if line.startswith("- ")]) == 4
    assert draft.read(PERSON).body == before


def test_a_valid_rewrite_still_writes_and_still_passes_the_gate():
    """The refusals must not have narrowed what a legal overview is: the one the contract
    describes — four grounded slots and a live connection — writes and clears the gate."""
    draft = _draft()
    doc = draft.rewrite_overview(PERSON, _overview())
    region = overview_region(doc.body)
    assert "Mei Lin leads supplier qualification for Aurora." in region
    assert "work/products/aurora.md" in region
    assert strip_overview(doc.body) == PERSON_BODY
    assert run_gate(draft, []) == []


# ─────────────────────────────────────────────────────────────────────── the gate


def test_an_overview_may_ground_on_a_claim_in_another_document():
    draft = _draft()
    draft.rewrite_overview(
        PERSON,
        Overview(definition="Mei Lin qualifies Aurora's suppliers. c:55ee66ff"),
    )
    assert run_gate(draft, []) == []


def test_an_ungrounded_overview_block_is_rejected():
    draft = _draft()
    _poke_overview(
        draft, PERSON, Overview(definition="Mei Lin is widely respected in the industry.")
    )
    violations = run_gate(draft, [])
    assert [v.kind for v in violations] == ["overview"]
    assert "rests on nothing" in violations[0].detail


def test_an_overview_may_not_ground_on_another_overview():
    draft = _draft()
    draft.rewrite_overview(PRODUCT, Overview(definition="Aurora is a line. c:55ee66ff"))
    borrowed = next(iter(overview_anchors(draft.read(PRODUCT).body)))
    _poke_overview(draft, PERSON, Overview(definition=f"Mei Lin leads it. c:{borrowed}"))
    assert any(
        v.kind == "overview" and "rests on nothing" in v.detail
        for v in run_gate(draft, [])
    )


def test_an_over_budget_overview_is_rejected():
    draft = _draft()
    _poke_overview(
        draft,
        PERSON,
        Overview(
            definition="Mei Lin leads qualification. c:11aa22bb",
            summary=("She reviews suppliers. c:11aa22bb " * 100),
        ),
    )
    violations = run_gate(draft, [])
    assert any(str(OVERVIEW_BUDGET_CHARS) in v.detail for v in violations)


def test_an_over_long_definition_is_rejected():
    draft = _draft()
    _poke_overview(
        draft,
        PERSON,
        Overview(
            definition="Mei Lin " + ("leads supplier qualification " * 12) + "c:11aa22bb"
        ),
    )
    violations = run_gate(draft, [])
    assert any(str(DEFINITION_MAX_CHARS) in v.detail for v in violations)


def test_a_connection_to_a_document_that_does_not_exist_is_a_dead_link():
    draft = _draft()
    _poke_overview(
        draft,
        PERSON,
        Overview(
            definition="Mei Lin leads qualification. c:11aa22bb",
            connections=(
                Connection("work/products/nowhere.md", "she has never touched it. c:11aa22bb"),
            ),
        ),
    )
    assert any(v.kind == "link" for v in run_gate(draft, []))


def test_overview_anchors_are_exempt_from_continuity_but_ledger_anchors_are_not():
    base = _base()
    with_region = _from_canonical(base, TEMPLATES)
    with_region.rewrite_overview(PERSON, _overview())
    committed = [
        CanonicalDocument(
            path=p, doc_id=d.doc_id, frontmatter=d.frontmatter, body=d.body
        )
        for p, d in with_region.documents().items()
    ]

    # a second round replaces the whole region: its base anchors vanish and the gate agrees
    second = _from_canonical(committed, TEMPLATES)
    second.rewrite_overview(PERSON, _overview(definition="Mei Lin leads it. c:11aa22bb"))
    assert run_gate(second, []) == []

    # the same disappearance in the LEDGER is still a hard rejection
    third = _from_canonical(committed, TEMPLATES)
    doc = third.read(PERSON)
    doc.body = doc.body.replace(
        "- She wants a written decision record before a supplier review. "
        "[cite: s01 ¶7] <!-- c:33cc44dd -->\n",
        "",
    )
    assert any(v.kind == "anchor_continuity" for v in run_gate(third, []))


# ───────────────────────────────────────── the floor: a ledger that owes a head
#
# The budget above says a head may not grow into a ledger. These say a ledger past a certain
# weight may not go on without a head — the failure a real library showed: 41 of 85 pages
# never got an overview (some holding 20-31 claims) while every page that had one was
# maintained again and again. A model maintains a head that exists and never starts one.

NEWCOMER = "memory/people/ada-vos.md"


def _ledger_body(count: int, *, title: str = "# Ada Vos") -> str:
    """A body of `count` cited claims and nothing else — no overview region."""
    lines = [title, "", "## Record", ""]
    for index in range(count):
        lines.append(f"- Ada Vos reviewed supplier lot {index}. [cite: s01 ¶{index}]")
    return "\n".join(lines) + "\n"


def _overview_violations(draft: PatchDraft, **kwargs) -> list:
    """The overview findings only — these drafts cite a source the gate was handed none of."""
    return [v for v in run_gate(draft, [], **kwargs) if v.kind == "overview"]


def test_a_page_created_at_the_threshold_without_an_overview_is_refused():
    draft = _draft()
    draft.create_document(NEWCOMER, {"type": "person", "slug": "ada-vos"}, _ledger_body(8))
    violations = _overview_violations(draft)
    assert [v.path for v in violations] == [NEWCOMER]
    assert "8 ledger claims and no overview" in violations[0].detail
    assert "rewrite_overview" in violations[0].detail


def test_the_same_page_passes_the_moment_it_has_a_definition():
    draft = _draft()
    doc = draft.create_document(
        NEWCOMER, {"type": "person", "slug": "ada-vos"}, _ledger_body(8)
    )
    anchor = extract_anchors(doc.body)[0]
    draft.rewrite_overview(
        NEWCOMER, Overview(definition=f"Ada Vos reviews supplier lots. c:{anchor}")
    )
    assert _overview_violations(draft) == []


def test_a_page_one_claim_short_of_the_threshold_owes_nothing():
    """The rule is a floor, not a habit: the first claims of a subject genuinely do not
    support a picture of it."""
    draft = _draft()
    draft.create_document(NEWCOMER, {"type": "person", "slug": "ada-vos"}, _ledger_body(7))
    assert _overview_violations(draft) == []


def _thirty_claim_library() -> list[CanonicalDocument]:
    body = assign_document_anchors(_ledger_body(30), NEWCOMER)
    return [*_base(), _doc(NEWCOMER, body, "b2c3d4e5f6a1")]


def test_a_page_the_round_never_touched_is_never_judged():
    """A repository-wide floor would let a page nobody touched abort a compile that has
    nothing to do with it — and the one non-rebuildable layer would be closed to writes over
    a head. An untouched page converges on its next touch."""
    draft = _from_canonical(_thirty_claim_library(), TEMPLATES)
    draft.append_block(PERSON, "Role", "She chairs the supplier board. [cite: s01 ¶4]")
    assert _overview_violations(draft) == []


def test_touching_the_page_is_what_asks_for_the_overview():
    draft = _from_canonical(_thirty_claim_library(), TEMPLATES)
    # A frontmatter-only write is a touch: the round had this document in its hands.
    draft.set_fields(NEWCOMER, {"status": "active"})
    violations = _overview_violations(draft)
    assert [v.path for v in violations] == [NEWCOMER]
    assert "30 ledger claims and no overview" in violations[0].detail

    anchor = extract_anchors(draft.read(NEWCOMER).body)[0]
    draft.rewrite_overview(
        NEWCOMER, Overview(definition=f"Ada Vos reviews supplier lots. c:{anchor}")
    )
    assert _overview_violations(draft) == []


def test_a_region_without_a_definition_is_still_a_page_without_a_head():
    """`definition` and not merely "a region": it is the line every glance and outline
    shows, so a region without it leaves the page as headless as before where it counts."""
    draft = _from_canonical(_thirty_claim_library(), TEMPLATES)
    anchor = extract_anchors(draft.read(NEWCOMER).body)[0]
    draft.rewrite_overview(
        NEWCOMER, Overview(summary=f"She reviewed thirty lots this quarter. c:{anchor}")
    )
    assert [v.path for v in _overview_violations(draft)] == [NEWCOMER]


def test_the_threshold_is_a_deployment_knob_and_zero_disables_it():
    draft = _from_canonical(_thirty_claim_library(), TEMPLATES)
    draft.set_fields(NEWCOMER, {"status": "active"})
    assert _overview_violations(draft, overview_required_after_claims=0) == []
    assert _overview_violations(draft, overview_required_after_claims=31) == []
    assert len(_overview_violations(draft, overview_required_after_claims=30)) == 1


# ──────────────────────────────────────────────────────────────── outline + glance


def test_the_outline_and_the_glance_carry_the_definition_line():
    draft = _draft()
    draft.rewrite_overview(PERSON, _overview())
    docs = [
        CanonicalDocument(path=p, doc_id=d.doc_id, frontmatter=d.frontmatter, body=d.body)
        for p, d in draft.documents().items()
    ]
    outline = render_outline(docs)
    assert "    definition: Mei Lin leads supplier qualification for Aurora." in outline
    # the grounding reference is machinery and does not reach the line
    assert not any("c:11aa22bb" in line for line in outline)
    glance = render_canonical_glance(docs, templates=TEMPLATES)
    assert "    definition: Mei Lin leads supplier qualification for Aurora." in glance


def test_without_an_overview_the_outline_and_glance_are_byte_identical():
    docs = _base()
    assert render_outline(docs) == render_outline(docs)
    assert all("definition:" not in line for line in render_outline(docs))
    assert "definition:" not in render_canonical_glance(docs, templates=TEMPLATES)
    assert document_definition(docs[0]) is None


def test_the_claim_count_counts_the_ledger_not_the_overview():
    draft = _draft()
    before = claim_count(_base()[0])
    draft.rewrite_overview(PERSON, _overview())
    after = CanonicalDocument(
        path=PERSON,
        doc_id=DocumentId("a1b2c3d4e5f6"),
        frontmatter={},
        body=draft.read(PERSON).body,
    )
    assert claim_count(after) == before == 2


# ─────────────────────────────────────────────────────────────────────── projection


def test_overview_claims_are_labelled_by_slot():
    draft = _draft()
    draft.rewrite_overview(PERSON, _overview())
    doc = CanonicalDocument(
        path=PERSON,
        doc_id=DocumentId("a1b2c3d4e5f6"),
        frontmatter={},
        body=draft.read(PERSON).body,
    )
    claims = project_document_claims(doc)
    by_slot = {c.section_path: c for c in claims if c.labels}
    assert set(by_slot) == {
        ("overview", "definition"),
        ("overview", "summary"),
        ("overview", "introduction"),
        ("overview", "connections"),
    }
    assert by_slot[("overview", "definition")].labels == ("overview", "definition")
    # the ledger's own claims keep their heading stack and carry no label
    ledger = [c for c in claims if not c.labels]
    assert {c.section_path for c in ledger} == {("Mei Lin", "Role"), ("Mei Lin", "Working style")}


# ─────────────────────────────────────────────────────────────────────────── events


def test_a_rewrite_yields_one_overview_event_and_no_claim_churn():
    draft = _draft()
    draft.rewrite_overview(PERSON, _overview())
    events = derive_events(draft.base_bodies(), draft.new_bodies())
    assert [e.type for e in events] == ["overview_rewritten"]
    assert events[0].path == PERSON
    assert events[0].anchor == ""
    assert events[0].before is None
    assert "Mei Lin leads supplier qualification" in events[0].after
    assert "<!-- overview" not in events[0].after


def test_a_second_rewrite_reports_what_the_picture_was():
    first = _draft()
    first.rewrite_overview(PERSON, _overview())
    committed = first.new_bodies()
    second = _from_canonical(
        [
            CanonicalDocument(
                path=p, doc_id=d.doc_id, frontmatter=d.frontmatter, body=d.body
            )
            for p, d in first.documents().items()
        ],
        TEMPLATES,
    )
    second.rewrite_overview(PERSON, _overview(definition="Mei Lin has moved on. c:11aa22bb"))
    events = derive_events(committed, second.new_bodies())
    assert [e.type for e in events] == ["overview_rewritten"]
    assert "Mei Lin leads supplier qualification" in (events[0].before or "")
    assert "Mei Lin has moved on." in events[0].after


# ───────────────────────────────────────────────────────────────────────── rollover


def _long_page() -> CanonicalDocument:
    claims = "\n".join(
        f"- Sprint {i}: the checklist advanced. [cite: s01 ¶{i}] <!-- c:{i:04d}aaaa -->"
        for i in range(40)
    )
    return CanonicalDocument(
        path=PRODUCT,
        doc_id=DocumentId("f6e5d4c3b2a1"),
        frontmatter={"doc_id": "f6e5d4c3b2a1", "type": "product", "slug": "aurora"},
        body=f"# Aurora\n\n## Delivery\n\n{claims}\n",
    )


def test_a_rollover_carries_the_overview_region_across_untouched():
    """The two heads must stay disjoint: the region is lifted out before the cut is planned,
    so its blocks are never rolled into a volume, and it is re-emitted under the title."""
    draft = _from_canonical([_long_page()], TEMPLATES)
    draft.rewrite_overview(
        PRODUCT, Overview(definition="Aurora is a product line. c:0000aaaa")
    )
    page = CanonicalDocument(
        path=PRODUCT,
        doc_id=DocumentId("f6e5d4c3b2a1"),
        frontmatter=draft.read(PRODUCT).frontmatter,
        body=draft.read(PRODUCT).body,
    )
    region = overview_region(page.body)
    plan = plan_rollover(page, [page], path_templates=TEMPLATES, keep_recent_chars=400)
    assert plan is not None
    assert plan.overview_region == region
    # not one region anchor may travel into the archive
    assert overview_anchors(page.body).isdisjoint(extract_anchors(plan.closed_body))
    body = render_active_body(plan, [], [])
    assert overview_region(body) == region
    assert body.split("\n")[0] == "# Aurora"


def test_a_rolled_over_document_can_still_receive_a_new_overview():
    page = _long_page()
    plan = plan_rollover(page, [page], path_templates=TEMPLATES, keep_recent_chars=400)
    assert plan is not None
    active = CanonicalDocument(
        path=PRODUCT,
        doc_id=page.doc_id,
        frontmatter=dict(page.frontmatter),
        body=render_active_body(plan, [], []),
    )
    volume = CanonicalDocument(
        path="work/products/aurora/a01.md",
        doc_id=DocumentId("v01"),
        frontmatter={
            "doc_id": "v01",
            "type": "product",
            "slug": "a01",
            "archived_from": PRODUCT,
        },
        body=plan.closed_body,
    )
    draft = _from_canonical([active, volume], TEMPLATES)
    kept = next(iter(extract_anchors(active.body)))
    draft.rewrite_overview(
        PRODUCT, Overview(definition=f"Aurora is a long-running product line. c:{kept}")
    )
    assert run_gate(draft, []) == []
    assert draft.read(volume.path).body == volume.body


def test_a_no_region_rollover_renders_exactly_as_before():
    page = _long_page()
    plan = plan_rollover(page, [page], path_templates=TEMPLATES, keep_recent_chars=400)
    assert plan is not None
    assert plan.overview_region == ""
    body = render_active_body(plan, [], [])
    assert "<!-- overview" not in body
    assert body.startswith("# Aurora\n\n## Delivery\n")


def test_an_unchanged_region_cannot_keep_a_retired_reference():
    """Retiring a ledger claim requires repairing every overview that references it."""
    seeded = _from_canonical(_base(), TEMPLATES)
    seeded.rewrite_overview(
        PERSON, Overview(definition="Mei Lin leads qualification. c:11aa22bb")
    )
    committed = [
        CanonicalDocument(
            path=p, doc_id=d.doc_id, frontmatter=d.frontmatter, body=d.body
        )
        for p, d in seeded.documents().items()
    ]
    # the claim the overview rested on is gone from the ledger (a merge, out of band)
    committed[0] = CanonicalDocument(
        path=committed[0].path,
        doc_id=committed[0].doc_id,
        frontmatter=committed[0].frontmatter,
        body=committed[0].body.replace(
            "- Mei Lin has led supplier qualification for the Aurora line since 2025-03. "
            "[cite: s01 ¶2-3] <!-- c:11aa22bb -->\n",
            "",
        ),
    )
    draft = _from_canonical(committed, TEMPLATES)
    assert any(v.kind == "overview" for v in run_gate(draft, []))
    # but the moment the round rewrites it, the same state is rejected
    _poke_overview(draft, PERSON, Overview(definition="Mei Lin leads it. c:11aa22bb"))
    assert any(v.kind == "overview" for v in run_gate(draft, []))


def test_the_rewrite_overview_tool_schema_survives_provider_conversion():
    """`connections` is the one compile argument that is a list of RECORDS. The scripted model
    in the runner tests ignores tool schemas, so the conversion a real provider performs is
    exercised here instead: the two field names must reach the model, or it is asked for
    "an object" and guesses."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from pneuma_knowledge_core.compile.runner import _build_tools

    tool = next(t for t in _build_tools(_draft()) if t.name == "rewrite_overview")
    schema = convert_to_openai_tool(tool)["function"]
    params = schema["parameters"]
    assert set(params["properties"]) == {
        "path",
        "definition",
        "summary",
        "introduction",
        "connections",
        "fields",
    }
    connections = params["properties"]["connections"]
    assert connections["type"] == "array"
    item = connections["items"]
    item = params.get("$defs", {}).get(item["$ref"].rsplit("/", 1)[-1], item) if "$ref" in item else item
    assert set(item["properties"]) == {"path", "relation"}
