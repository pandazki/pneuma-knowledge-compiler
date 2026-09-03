"""The ARCHIVE RECORD: the page a retired subject leaves at its live path.

docs/design/archive.md §2.3. Archiving a page used to make its subject VANISH — other live
pages went on mentioning it, and a question about it was answered out of whatever mentions
survived elsewhere, with nothing anywhere saying the owner had retired it. The record is what
stands there instead: what the subject was, the span it covered, how much it held, and the
owner's reason, citing the owner's own statement.

Two halves, tested here:

* the rendering, which is mechanical and must be DETERMINISTIC — same inputs, same bytes,
  same three system anchors — and must carry the page's own definition with the grounding it
  rested on rather than inventing a sentence about a retired subject;
* the record's standing at the compile boundary: it is LIVE (listed in the outline, read by
  `read_document`, retrieved by every lane) and it is READ-ONLY (every write verb refuses it
  at the tool face, and the gate refuses any diff on it over the produced draft).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from pneuma_knowledge_core.archive.record import (
    DEFINITION_FROM_LEDGER,
    GROUNDING_EXEMPT,
    RECORD_SLOTS,
    RecordFacts,
    compute_record_facts,
    facts_line,
    frontmatter_facts,
    note_machinery,
    record_anchors,
    record_doc_id,
    record_reason,
    render_record,
    render_record_body,
    run_archive_record_gate,
    statement_quote,
    unit_facts,
)
from pneuma_knowledge_core.canonical_glance import (
    glance_entry,
    render_canonical_glance,
    render_outline,
)
from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError, anchored_blocks
from pneuma_knowledge_core.compile.documents import parse_document
from pneuma_knowledge_core.compile.gate import archive_refusals, run_gate
from pneuma_knowledge_core.compile.patch import PatchDraft, assign_document_id
from pneuma_knowledge_core.compile.runner import _build_tools
from pneuma_knowledge_core.evolve.gate import run_evolve_gate
from pneuma_knowledge_core.domain.archive import ARCHIVE_RECORD_KEYS, is_archive_record
from pneuma_knowledge_core.domain.canonical import (
    CanonicalDocument,
    iter_canonical_citations,
)
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId, extract_anchors
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.prompts import prompt

from datetime import datetime, timezone

TEMPLATES = ["memory/topics/{slug}.md", "memory/people/{slug}.md"]

SOURCES = [
    NormalizedSource(
        raw=RawSource(
            source_id=SourceId("src-01"),
            user_id=UserId("u-1"),
            kind="conversation",
            title="t",
            mime="text/plain",
            checksum="src-01",
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=i, text=f"b{i}") for i in range(4)],
        structure=StructureMap(),
    )
]

STATEMENT = "src-stmt"
DAY = "2026-09-04"
REASON = "Aurora shipped in June; the team is disbanded."


def _anchor(path: str, index: int) -> str:
    return hashlib.sha256(f"{path}:{index}".encode()).hexdigest()[:8]


def _document(
    path: str,
    *,
    definition: str = "",
    claims: tuple[tuple[str, str], ...] = (),
    body: str = "",
    **frontmatter: str,
) -> CanonicalDocument:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    if not body:
        lines = [f"# {slug.title()}", ""]
        if definition:
            lines += [
                "<!-- overview -->",
                "",
                "<!-- overview:definition -->",
                "### What this is",
                "",
                f"{definition} <!-- c:{_anchor(path, 99)} -->",
                "",
                "<!-- /overview -->",
                "",
            ]
        for index, (text, sid) in enumerate(claims):
            lines.append(
                f"- {text} [cite: {sid} ¶{index}] <!-- c:{_anchor(path, index)} -->"
            )
        body = "\n".join(lines) + "\n"
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{hashlib.sha256(path.encode()).hexdigest()[:10]}"),
        path=path,
        frontmatter={"doc_id": "d-x", "type": "topic", "slug": slug, **frontmatter},
        body=body,
    )


AURORA = _document(
    "memory/topics/aurora.md",
    definition=(
        "Aurora is the delivery programme the team ran through 2026 "
        f"(c:{_anchor('memory/topics/aurora.md', 0)})."
    ),
    claims=(
        ("Aurora ships on a two-week cadence.", "src-a"),
        ("Aurora pays the vendor quarterly.", "src-b"),
    ),
)
ATLAS = _document(
    "memory/topics/atlas.md",
    body=(
        "# Atlas\n\n"
        "- Atlas depends on [Aurora](aurora.md). [cite: src-b ¶0] "
        f"<!-- c:{_anchor('memory/topics/atlas.md', 0)} -->\n"
    ),
)
OCCURRENCE = {"src-a": "2026-01-04", "src-b": "2026-06-30"}


def _facts() -> RecordFacts:
    facts = unit_facts(
        [AURORA, ATLAS], AURORA.path, source_occurrence=OCCURRENCE
    )
    assert facts is not None
    return facts


def _record_document(path: str = AURORA.path) -> CanonicalDocument:
    """The record as it would stand in the tree after the move."""
    facts = _facts()
    rendered = render_record(
        path,
        facts,
        slug=path.rsplit("/", 1)[-1].removesuffix(".md"),
        archived_on=DAY,
        statement_ref=STATEMENT,
        reason=REASON,
        taken=set(extract_anchors(AURORA.body)) | set(extract_anchors(ATLAS.body)),
    )
    frontmatter, body = parse_document(rendered)
    return CanonicalDocument(
        doc_id=DocumentId(frontmatter["doc_id"]),
        path=path,
        frontmatter=frontmatter,
        body=body,
    )


MOVED = CanonicalDocument(
    doc_id=AURORA.doc_id,
    path="archive/" + AURORA.path,
    frontmatter=dict(AURORA.frontmatter),
    body=AURORA.body,
)


# ------------------------------------------------------------------- the computation


def test_the_facts_are_read_off_the_page_and_the_library_around_it():
    facts = _facts()
    assert facts.title == "Aurora"
    assert facts.claims == 2
    assert facts.sources == 2
    assert facts.volumes == 0
    # Atlas links to Aurora, and it is not itself leaving.
    assert facts.inbound == 1
    # The span is min/max `occurred_on` over the sources the CLAIMS cite.
    assert facts.span == ("2026-01-04", "2026-06-30")


def test_a_page_whose_sources_state_no_day_has_no_span_rather_than_a_guessed_one():
    facts = unit_facts([AURORA, ATLAS], AURORA.path, source_occurrence={})
    assert facts.span is None
    body = render_record_body(
        AURORA.path, facts, archived_on=DAY, statement_ref=STATEMENT, reason=REASON
    )
    line = anchored_blocks(body)[1]
    assert "Covered" not in line
    assert line.startswith("ledger claims 2 · sources 2")


def test_a_link_from_a_page_that_is_leaving_too_is_not_inbound():
    """The record is left holding the links that REMAIN. Atlas going into the archive in the
    same commit is not a live page pointing at this one."""
    facts = unit_facts(
        [AURORA, ATLAS],
        AURORA.path,
        moving={ATLAS.path},
        source_occurrence=OCCURRENCE,
    )
    assert facts.inbound == 0


def test_the_ledger_fallback_carries_the_claim_with_its_citation_not_the_display_line():
    """The one thing this fallback must not do is what the glance's `ledger:` line does.

    That line is DISPLAY text and strips the `[cite: …]` span along with the markdown, which
    is right under a title and wrong here: a record's blocks are projected as claims, so a
    stripped line would be an ungrounded assertion about a retired subject standing in every
    default answer (I4). The claim travels whole — its citation included, its list bullet and
    its anchor left behind, since those are the ledger's container and the system's identity
    rather than words the page says.
    """
    plain = _document(
        "memory/topics/plain.md",
        claims=(("Plain holds exactly one fact.", "src-a"),),
    )
    facts = unit_facts([plain], plain.path, source_occurrence={})
    assert facts.definition == "Plain holds exactly one fact. [cite: src-a ¶0]"
    assert facts.definition_source == DEFINITION_FROM_LEDGER
    # And the rendered block carries it, so the gate's grounding floor is satisfied by the
    # page's own evidence rather than by an exemption.
    body = render_record_body(
        plain.path, facts, archived_on=DAY, statement_ref=STATEMENT, reason=REASON
    )
    assert "[cite: src-a ¶0]" in anchored_blocks(body)[0]


def test_a_page_with_neither_a_definition_nor_a_claim_states_its_title_and_is_exempt():
    """The ONE case with nothing to ground on — named, not inferred, and documented."""
    empty = _document("memory/topics/empty.md", body="# Empty\n")
    facts = unit_facts([empty], empty.path, source_occurrence={})
    assert facts.definition == "Empty"
    assert facts.definition_source == GROUNDING_EXEMPT

    body = render_record_body(
        empty.path, facts, archived_on=DAY, statement_ref=STATEMENT, reason=REASON
    )
    first = anchored_blocks(body)[0]
    assert "[cite:" not in first and "c:" not in first.split("<!--")[0]
    frontmatter, rendered_body = parse_document(
        render_record(
            empty.path,
            facts,
            slug="empty",
            archived_on=DAY,
            statement_ref=STATEMENT,
            reason=REASON,
        )
    )
    assert run_archive_record_gate(
        path=empty.path,
        frontmatter=frontmatter,
        body=rendered_body,
        facts=facts,
        statement_ref=STATEMENT,
        moved_body=empty.body,
        base_body=empty.body,
    ) == []


def test_an_ungrounded_first_block_is_refused_for_every_other_page():
    """Check 3 only says the block KEPT what its source carried; it is silent about a source
    that carried nothing. The floor is what closes that, and it exempts exactly one case."""
    facts = _facts()
    stripped = RecordFacts(
        **{
            **facts.as_dict(),
            "span": facts.span,
            "definition": "Aurora is the delivery programme the team ran through 2026.",
        }
    )
    frontmatter, body = parse_document(
        render_record(
            AURORA.path,
            stripped,
            slug="aurora",
            archived_on=DAY,
            statement_ref=STATEMENT,
            reason=REASON,
        )
    )
    violations = run_archive_record_gate(
        path=AURORA.path,
        frontmatter=frontmatter,
        body=body,
        facts=stripped,
        statement_ref=STATEMENT,
        moved_body=AURORA.body,
        base_body=AURORA.body,
    )
    assert [v.kind for v in violations] == ["archive_record"]
    assert "rests on nothing" in violations[0].detail


def test_the_record_and_the_copy_it_stands_in_front_of_are_two_document_ids():
    """`read(user, doc_id)` has to answer with one document. The page keeps the id it has
    always carried on the other side of the move; the record's is derived from its own key."""
    assert record_doc_id(AURORA.path) != assign_document_id(AURORA.path)
    record = _record_document()
    assert record.frontmatter["doc_id"] == str(record_doc_id(AURORA.path))

    # And the gate says so mechanically, against every id the tree already holds.
    violations = run_archive_record_gate(
        path=AURORA.path,
        frontmatter=record.frontmatter,
        body=record.body,
        facts=_facts(),
        statement_ref=STATEMENT,
        moved_body=AURORA.body,
        base_body=AURORA.body,
        repository_doc_ids={record.frontmatter["doc_id"]},
    )
    assert [v.kind for v in violations] == ["archive_record"]
    assert "already belongs to another document" in violations[0].detail


# ------------------------------------------------------- the owner's note is words


@pytest.mark.parametrize(
    "note",
    [
        "Shipped <!-- c:aaaa1111 -->",
        "Shipped <!-- supersedes: c:aaaa1111 -->",
        "Shipped __AUTO__ and done",
    ],
)
def test_a_note_carrying_the_system_s_machinery_is_named_by_the_predicate(note):
    """The same predicate the compile gate refuses a claim on, applied where a person can
    still fix it: `plan` and `confirm` answer 422 `note_machinery` off exactly this."""
    assert note_machinery(note) is not None
    assert note_machinery("Aurora shipped in June; the team is disbanded.") is None


def test_the_renderer_sanitizes_a_note_so_nothing_slips_past_the_face():
    """Defence in depth over a row written before that refusal existed. The words survive;
    the machinery does not, and the reason block keeps exactly ONE citation — the one the
    renderer appends."""
    body = render_record_body(
        AURORA.path,
        _facts(),
        archived_on=DAY,
        statement_ref=STATEMENT,
        reason="Done <!-- c:aaaa1111 --> and cited [cite: src-x ¶4] too",
    )
    reason_block = anchored_blocks(body)[2]
    assert "<!--" not in reason_block.split("<!-- c:")[0]
    assert "Done" in reason_block and "and cited" in reason_block
    # The bracket marker lost its brackets, so exactly one citation parses out of the block.
    assert "[cite: src-x" not in reason_block
    assert "cite: src-x ¶4" in reason_block
    assert [str(c.source_id) for c in iter_canonical_citations(reason_block)] == [STATEMENT]


def test_machinery_reaching_a_record_from_anywhere_abandons_the_write():
    """The arbiter over the produced page, behind the two faces that refuse before it."""
    facts = _facts()
    frontmatter, body = parse_document(
        render_record(
            AURORA.path,
            facts,
            slug="aurora",
            archived_on=DAY,
            statement_ref=STATEMENT,
            reason=REASON,
        )
    )
    smuggled = body.replace("Covered", "<!-- c:dead --> Covered")
    violations = run_archive_record_gate(
        path=AURORA.path,
        frontmatter=frontmatter,
        body=smuggled,
        facts=facts,
        statement_ref=STATEMENT,
        moved_body=AURORA.body,
        base_body=AURORA.body,
    )
    assert any("machinery" in v.detail for v in violations)


def test_the_reason_and_the_statement_are_one_string_read_two_ways():
    """`record_reason` writes the statement's text; `statement_quote` reads it back off the
    block the record cites. A round trip through the ingest turn line changes nothing."""
    reason = record_reason("Aurora shipped in June.")
    block = prompt(
        "ingest.turn_line", label=prompt("ingest.owner_label"), text=reason
    )
    assert statement_quote(block) == reason


def test_the_framework_composes_no_reason_when_the_owner_wrote_none():
    """No note, no sentence. The archive keeps the reason as an `owner-dialogue/v1` source —
    L0 labelled as the owner SPEAKING — so a sentence composed here would stand there as
    words the owner never said, indistinguishable to every later reader from a real
    statement. The empty answer is what the request faces refuse on (`note_required`) and
    what the job refuses on (`statement_missing`); whitespace is not words either."""
    assert record_reason("") == ""
    assert record_reason("   \n\t ") == ""
    assert record_reason(None) == ""  # type: ignore[arg-type]


def test_a_volume_s_claims_and_sources_count_towards_the_page_that_owns_it():
    volume = _document(
        "memory/topics/aurora/a01.md",
        claims=(("Aurora ran a pilot in January.", "src-c"),),
        archived_from=AURORA.path,
    )
    facts = unit_facts(
        [AURORA, ATLAS, volume],
        AURORA.path,
        volumes=(volume.path,),
        source_occurrence={**OCCURRENCE, "src-c": "2025-11-02"},
    )
    assert (facts.claims, facts.sources, facts.volumes) == (3, 3, 1)
    assert facts.span == ("2025-11-02", "2026-06-30")


# -------------------------------------------------------------------- the rendering


def test_the_same_inputs_render_the_same_bytes():
    first = _record_document().body
    second = _record_document().body
    assert first == second
    assert first + "\n" == render_record_body(
        AURORA.path,
        _facts(),
        archived_on=DAY,
        statement_ref=STATEMENT,
        reason=REASON,
        taken=set(extract_anchors(AURORA.body)) | set(extract_anchors(ATLAS.body)),
    )


def test_the_anchors_are_system_assigned_per_path_and_slot():
    anchors = record_anchors(AURORA.path)
    assert list(anchors) == list(RECORD_SLOTS)
    assert anchors == record_anchors(AURORA.path)
    # A different path is a different record, so different ids.
    assert set(anchors.values()).isdisjoint(
        record_anchors("memory/topics/atlas.md").values()
    )
    # And a seed of taken ids moves them off a collision rather than reusing one.
    collided = record_anchors(AURORA.path, {anchors["definition"]})
    assert collided["definition"] != anchors["definition"]


def test_the_three_blocks_say_what_the_subject_was_what_it_held_and_why_it_left():
    record = _record_document()
    blocks = anchored_blocks(record.body)
    assert len(blocks) == 3

    # 1. the page's own definition, verbatim, with its grounding carried over.
    assert AURORA.body.split("\n")[6].split(" <!--")[0] in blocks[0]
    assert f"c:{_anchor(AURORA.path, 0)}" in blocks[0]
    assert blocks[0].split(" <!--")[0].endswith("— archived")

    # 2. the machine facts, in words, citing NOTHING (`FACTS_EXEMPT`).
    assert "[cite:" not in blocks[1]
    # Labelled numbers, the figure last: nothing in this line inflects for number (a channel
    # with no model cannot), and `ledger claims` names WHICH count it is — the page and its
    # closed volumes, not the library view's number that also counts the overview.
    assert blocks[1].startswith(
        "Covered 2026-01-04–2026-06-30 · ledger claims 2 · sources 2 · closed volumes 0 "
        "· linked from live pages 1"
    )

    # 3. the owner's reason, quoted, resting on the owner's own statement.
    assert prompt("archive.record.reason", date=DAY, note=REASON) in blocks[2]
    assert f"[cite: {STATEMENT} ¶0]" in blocks[2]


def test_the_frontmatter_carries_every_machine_key_and_the_page_s_own_identity():
    record = _record_document()
    for key in ARCHIVE_RECORD_KEYS:
        assert record.frontmatter.get(key), key
    assert record.frontmatter["type"] == "archived"
    assert record.frontmatter["archive_of"] == MOVED.path
    assert record.frontmatter["title"] == "Aurora"
    assert record.frontmatter["archive_span"] == "2026-01-04/2026-06-30"
    assert record.frontmatter["archive_claims"] == "2"
    assert is_archive_record(record)


# --------------------------------------------------------- the channel's own gate


def _gate(**overrides):
    record = _record_document()
    kwargs = dict(
        path=AURORA.path,
        frontmatter=dict(record.frontmatter),
        body=record.body,
        facts=_facts(),
        statement_ref=STATEMENT,
        moved_body=AURORA.body,
        base_body=AURORA.body,
        repository_anchors=set(extract_anchors(AURORA.body))
        | set(extract_anchors(ATLAS.body)),
    )
    kwargs.update(overrides)
    return run_archive_record_gate(**kwargs)


def test_a_well_formed_record_passes_its_own_gate():
    assert _gate() == []


def test_the_gate_refuses_a_reason_that_does_not_cite_the_owner_s_statement():
    violations = _gate(statement_ref="src-other")
    assert [v.kind for v in violations] == ["archive_record"]
    assert "src-other" in violations[0].detail


def test_the_gate_refuses_a_definition_that_dropped_its_grounding():
    record = _record_document()
    stripped = record.body.replace(f" (c:{_anchor(AURORA.path, 0)})", "")
    violations = _gate(body=stripped)
    assert violations and _anchor(AURORA.path, 0) in violations[0].detail


def test_the_gate_refuses_an_incomplete_frontmatter():
    record = _record_document()
    frontmatter = dict(record.frontmatter)
    frontmatter.pop("archive_statement")
    violations = _gate(frontmatter=frontmatter)
    assert violations
    assert violations[0].detail == prompt(
        "gate.archive_record.frontmatter", key="archive_statement"
    )


def test_the_gate_refuses_frontmatter_that_disagrees_with_the_uncited_line():
    """The facts line cites nothing BECAUSE the frontmatter is its provenance, so the two
    disagreeing would leave it resting on nothing at all."""
    record = _record_document()
    frontmatter = dict(record.frontmatter)
    frontmatter["archive_claims"] = "99"
    violations = _gate(frontmatter=frontmatter)
    assert violations and "archive_claims" in violations[0].detail


def test_the_gate_refuses_a_body_line_that_disagrees_with_the_frontmatter():
    """The same promise read the other way round, and the direction that matters.

    Checking only the keys against the `facts` a render was made from is blind to a page
    whose BODY came from anywhere else — a hand edit, an operator's repair, a second
    implementation of the line. `FACTS_EXEMPT` is a promise about what stands on the page,
    so the page is what is read.
    """
    record = _record_document()
    tampered = record.body.replace("ledger claims 2", "ledger claims 99")
    assert tampered != record.body
    violations = _gate(body=tampered)
    assert violations
    assert violations[0].detail == prompt(
        "gate.archive_record.facts_body",
        stated=facts_line(frontmatter_facts({**record.frontmatter, "archive_claims": "99"})),
        expected=facts_line(frontmatter_facts(record.frontmatter)),
    )


def test_the_gate_refuses_a_body_span_that_disagrees_with_the_frontmatter():
    """The span travels in the same line and is checked by the same reading."""
    record = _record_document()
    violations = _gate(body=record.body.replace("2026-06-30", "2026-12-31"))
    assert violations and "2026-12-31" in violations[0].detail


def test_the_gate_refuses_a_frontmatter_span_the_facts_do_not_cover():
    """The span is the one stated fact that is not a count, and it was the one unchecked.

    Every number the second block says in words is read against `facts`; the span travelled
    only in the body-vs-frontmatter reading, so a key stating a range nobody computed passed
    as long as the line under it agreed. The inventory reports a record off its frontmatter
    alone (`GET /archive`), which makes that key a fact in its own right.
    """
    record = _record_document()
    frontmatter = {**record.frontmatter, "archive_span": "2020-01-01/2020-02-02"}
    details = [v.detail for v in _gate(frontmatter=frontmatter)]
    assert (
        prompt(
            "gate.archive_record.span",
            stated="2020-01-01/2020-02-02",
            expected="2026-01-04/2026-06-30",
        )
        in details
    )


def test_the_gate_refuses_a_span_key_that_is_missing_from_a_page_that_has_one():
    """Absent when the facts state one: the record would report no span it in fact covers."""
    record = _record_document()
    frontmatter = {k: v for k, v in record.frontmatter.items() if k != "archive_span"}
    details = [v.detail for v in _gate(frontmatter=frontmatter)]
    assert (
        prompt(
            "gate.archive_record.span", stated="-", expected="2026-01-04/2026-06-30"
        )
        in details
    )


def test_the_gate_refuses_a_span_key_on_a_page_whose_sources_state_no_day():
    """And present when the facts state none — the direction `ARCHIVE_RECORD_KEYS` allows.

    `archive_span` is deliberately not a required key: a page whose sources name no day has
    no span, and a key stating an empty one would be a fact nobody has. That absence is only
    honest if a PRESENT key is checked, which is what makes this the other half of the same
    reading rather than a second rule.
    """
    details = [v.detail for v in _gate(facts=replace(_facts(), span=None))]
    assert (
        prompt(
            "gate.archive_record.span", stated="2026-01-04/2026-06-30", expected="-"
        )
        in details
    )


def test_the_gate_refuses_a_statement_key_that_names_something_else_than_the_reason_cites():
    """`archive_statement` was checked for PRESENCE and nothing else.

    Two faces read two halves of one record: a reader follows the `[cite: …]` in the reason
    block, and the inventory reads this key without opening the body at all. A key naming one
    source while the block quotes another would have them answer differently about whose
    words the record is quoting — which is the fabrication the citation exists to prevent,
    moved up into the frontmatter.
    """
    record = _record_document()
    frontmatter = {**record.frontmatter, "archive_statement": "src-other"}
    details = [v.detail for v in _gate(frontmatter=frontmatter)]
    assert (
        prompt(
            "gate.archive_record.statement_mismatch",
            stated="src-other",
            cited=STATEMENT,
        )
        in details
    )
    # The reason block itself is untouched, so the citation check has nothing to say: this
    # refusal is the frontmatter's own, and it is the only one raised.
    assert details == [
        prompt(
            "gate.archive_record.statement_mismatch",
            stated="src-other",
            cited=STATEMENT,
        )
    ]


def test_the_gate_refuses_a_doc_id_this_channel_did_not_derive():
    """A collision check alone would pass ANY id — including the one the moved copy carries.

    The id is a function of the path (`record_doc_id`), so the record and the full copy are
    two documents with two ids; an id from anywhere else puts `read(user, doc_id)` back in
    front of two answers.
    """
    record = _record_document()
    frontmatter = {**record.frontmatter, "doc_id": str(AURORA.doc_id)}
    violations = _gate(frontmatter=frontmatter)
    assert violations
    assert violations[0].detail == prompt(
        "gate.archive_record.doc_id",
        stated=str(AURORA.doc_id),
        expected=str(record_doc_id(AURORA.path)),
    )
    # And the collision half still fires on its own, over the id this channel DOES derive.
    taken = _gate(repository_doc_ids={str(record_doc_id(AURORA.path))})
    assert taken and taken[0].detail == prompt(
        "gate.archive_record.doc_id_taken", doc_id=str(record_doc_id(AURORA.path))
    )


def test_the_gate_refuses_a_copy_that_is_not_the_page_that_stood_there():
    violations = _gate(moved_body=AURORA.body + "\n- Snuck in.\n")
    assert violations
    assert violations[0].detail == prompt("gate.archive_record.copy", path=MOVED.path)


def test_the_gate_refuses_an_anchor_the_repository_already_holds():
    anchors = record_anchors(AURORA.path)
    violations = _gate(
        repository_anchors={anchors[slot] for slot in RECORD_SLOTS}
    )
    # The seed pushes the derivation off the collision, so the rendered body's ids no longer
    # match the ones the gate derives from the same seed — which is the check firing.
    assert violations


# ------------------------------------------------------- the compile boundary


def _draft(*docs: CanonicalDocument) -> PatchDraft:
    return PatchDraft.from_canonical(list(docs), TEMPLATES)


def _tools(draft: PatchDraft) -> dict:
    return {t.name: t for t in _build_tools(draft)}


def test_an_untouched_record_passes_the_gate():
    assert run_gate(_draft(_record_document(), MOVED, ATLAS), SOURCES) == []


@pytest.mark.parametrize(
    "op,call",
    [
        ("append_block", dict(heading="Notes", text="- New. [cite: src-01 ¶0]")),
        ("set_fields", dict(fields={"status": "revived"})),
        ("rewrite_overview", dict(definition="Aurora is back.")),
    ],
)
def test_every_write_verb_refuses_a_record_at_the_tool_face(op, call):
    record = _record_document()
    tools = _tools(_draft(record, MOVED, ATLAS))
    with pytest.raises(AnchorToolError) as err:
        tools[op].func(path=record.path, **call)
    assert str(err.value) == prompt(
        "compile.patch.archived_record",
        op=op,
        path=record.path,
        archived=MOVED.path,
    )


def test_edit_claim_refuses_a_record_s_own_block():
    record = _record_document()
    tools = _tools(_draft(record, MOVED, ATLAS))
    anchor = record_anchors(record.path)["reason"]
    with pytest.raises(AnchorToolError) as err:
        tools["edit_claim"].func(
            path=record.path, anchor_id=anchor, new_text="- Not archived after all."
        )
    assert "read-only" in str(err.value)


def test_the_gate_refuses_any_diff_on_a_record():
    record = _record_document()
    draft = _draft(record, MOVED, ATLAS)
    draft.documents()[record.path].frontmatter["status"] = "revived"
    violations = run_gate(draft, SOURCES)
    hit = next(v for v in violations if v.path == record.path)
    assert hit.kind == "archived_path"
    assert hit.detail == prompt("gate.archive_record", archived=MOVED.path)


def test_a_refused_write_on_a_record_reaches_the_owner_as_its_own_signal():
    record = _record_document()
    draft = _draft(record, MOVED, ATLAS)
    draft.documents()[record.path].frontmatter["status"] = "revived"
    violations = run_gate(draft, SOURCES)
    refusals = archive_refusals(violations, draft)
    assert [r["kind"] for r in refusals] == ["record"]
    assert refusals[0]["path"] == record.path
    assert refusals[0]["archived"] == MOVED.path
    assert refusals[0]["title"] == "Aurora"


def test_the_title_shadow_rule_still_refuses_the_subject_under_another_slug():
    """The record holds the PATH; the archived copy still holds the NAME. A model refused at
    the record's path must not rebuild the subject at the next free slug."""
    record = _record_document()
    tools = _tools(_draft(record, MOVED, ATLAS))
    with pytest.raises(AnchorToolError) as err:
        tools["create_document"].func(
            path="memory/topics/aurora-programme.md",
            frontmatter={"type": "topic", "slug": "aurora-programme"},
            body="# Aurora\n\n- Rebuilt. [cite: src-01 ¶0]",
        )
    assert str(err.value) == prompt(
        "compile.patch.archived_title_shadowed",
        path="memory/topics/aurora-programme.md",
        title="Aurora",
        archived=MOVED.path,
    )


# ----------------------------------------------------------------- the read faces


def test_the_outline_lists_the_record_and_states_that_it_is_one():
    record = _record_document()
    lines = render_outline([record, MOVED, ATLAS])
    entry = next(line for line in lines if record.path in line)
    assert entry == prompt(
        "compile.task.outline_entry_record",
        path=record.path,
        archived=MOVED.path,
        archived_on=DAY,
    )
    # And the archive itself is still not rendered as a document of its own — the record's
    # line NAMES the copy, which is the point, but no line offers it as a page to write to.
    assert not any(line.startswith(f"- `{MOVED.path}`") for line in lines)


def test_read_document_answers_with_the_record_under_a_read_only_notice():
    record = _record_document()
    tools = _tools(_draft(record, MOVED, ATLAS))
    out = tools["read_document"].func(path=record.path)
    assert out.startswith(
        prompt("compile.tool.read_document_record_notice", archived=MOVED.path)
    )
    assert "Archived by the owner" in out


def test_list_documents_lists_the_record_and_not_the_archived_copy():
    record = _record_document()
    tools = _tools(_draft(record, MOVED, ATLAS))
    listed = tools["list_documents"].func().splitlines()
    assert record.path in listed
    assert MOVED.path not in listed


def test_the_glance_marks_the_record_without_being_asked_to():
    record = _record_document()
    line = glance_entry(record).splitlines()[0]
    assert line.endswith(prompt("recall.glance.entry_tail_in_archive") + ")")
    glance = render_canonical_glance([record, ATLAS], templates=TEMPLATES)
    entry = next(l for l in glance.splitlines() if record.path in l)
    assert entry.endswith(prompt("recall.glance.entry_tail_in_archive") + ")")


def test_compute_record_facts_needs_no_library_at_all():
    """Pure: a document in, facts out. Nothing here reads a port or a clock."""
    facts = compute_record_facts(AURORA)
    assert (facts.claims, facts.sources, facts.inbound, facts.span) == (2, 2, 0, None)


# -------------------------------------------------------- the evolve boundary
#
# The whole-library reorganization is the one channel that can move a claim between
# documents, and a record is not material it may re-file: it stays byte-for-byte where the
# archive job left it, like a closed volume and like `archive/` itself. The evolve draft
# holds live documents only, so `MOVED` is absent from every draft below.


async def _bounds(source_id: str) -> int | None:
    return 4


def test_the_evolve_channel_refuses_to_move_a_claim_out_of_a_record():
    record = _record_document()
    draft = _draft(record, ATLAS)
    anchor = record_anchors(record.path)["reason"]
    with pytest.raises(AnchorToolError) as err:
        draft.move_claim(record.path, anchor, ATLAS.path, "Notes")
    assert str(err.value) == prompt(
        "compile.patch.archived_record",
        op="move_claim",
        path=record.path,
        archived=MOVED.path,
    )


def test_the_evolve_channel_refuses_to_move_a_claim_into_a_record():
    record = _record_document()
    draft = _draft(record, ATLAS)
    with pytest.raises(AnchorToolError) as err:
        draft.move_claim(
            ATLAS.path, _anchor(ATLAS.path, 0), record.path, "Notes"
        )
    assert str(err.value) == prompt(
        "compile.patch.archived_record",
        op="move_claim",
        path=record.path,
        archived=MOVED.path,
    )
    # And the claim it refused to take is still where it was.
    assert _anchor(ATLAS.path, 0) in extract_anchors(draft.read(ATLAS.path).body)


def test_the_evolve_channel_refuses_to_merge_a_record_s_claim_away():
    record = _record_document()
    draft = _draft(record, ATLAS)
    with pytest.raises(AnchorToolError) as err:
        draft.delete_claim(record.path, record_anchors(record.path)["facts"])
    assert str(err.value) == prompt(
        "compile.patch.archived_record",
        op="delete_claim",
        path=record.path,
        archived=MOVED.path,
    )


async def test_the_evolve_gate_says_nothing_about_a_record_the_round_carried_through():
    """Every evolve run holds the records the library has; not one of them is a finding."""
    violations, dropped = await run_evolve_gate(
        _draft(_record_document(), ATLAS),
        source_bounds=_bounds,
        path_templates=TEMPLATES,
    )
    assert violations == []
    assert dropped == []


async def test_the_evolve_gate_refuses_a_diff_on_a_record():
    record = _record_document()
    draft = _draft(record, ATLAS)
    draft.documents()[record.path].frontmatter["status"] = "revived"
    violations, _dropped = await run_evolve_gate(
        draft, source_bounds=_bounds, path_templates=TEMPLATES
    )
    hit = next(v for v in violations if v.path == record.path)
    assert hit.kind == "archived_path"
    assert hit.detail == prompt("gate.archive_record", archived=MOVED.path)


def test_the_gate_refuses_a_present_but_empty_span_key_on_a_page_with_no_span():
    """Present-and-empty is not absent. When the facts state no span the KEY must be gone;
    `archive_span: ""` is a fact nobody has, written down, and the inventory would read it as
    a span it cannot render."""
    record = _record_document()
    frontmatter = {**record.frontmatter, "archive_span": ""}
    details = [
        v.detail
        for v in _gate(frontmatter=frontmatter, facts=replace(_facts(), span=None))
    ]
    assert (
        prompt("gate.archive_record.span", stated="(empty)", expected="-") in details
    )
