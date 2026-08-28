"""The shared canonical-shape renderer: the compile outline and the recall glance.

Two things are locked here. First, that the compile outline is UNCHANGED by having been moved
into the shared module — the extraction was a refactor, and the compile prompt's bytes are
part of a byte-stable surface nobody asked to change. Second, that the glance renders the
things the answering side actually needs from it: the declared families (so a model knows
where things live even when a family is empty), a blurb per family read off pack structure,
mechanical per-document lines, and honest truncation at both the per-family and whole-render
bounds.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from pneuma_knowledge_core.canonical_glance import (
    LEDGER_LINE_JOINER,
    archive_volume_counts,
    document_ledger_line,
    document_title,
    family_blurbs,
    markdown_display_text,
    render_canonical_glance,
    render_outline,
)
from pneuma_knowledge_core.compile.documents import derived_title
from pneuma_knowledge_core.compile.overview import DEFINITION_MAX_CHARS
from pneuma_knowledge_core.compile.runner import _render_outline, _render_task
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill import SchemaPack, SkillVersion

TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "memory/topics/{slug}.md",
    "materials/{slug}.md",
]


def _skill(templates: list[str] | None = None) -> SkillVersion:
    templates = templates if templates is not None else TEMPLATES
    return SkillVersion(
        skill_id="test-skill",
        version="t1",
        instructions="body",
        path_templates=list(templates),
        content_hash="0" * 64,
    )


def _doc(path: str, body: str, **frontmatter: str) -> CanonicalDocument:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=path,
        frontmatter={"doc_id": f"d-{slug}", "type": "topic", "slug": slug, **frontmatter},
        body=body,
    )


def _anchor(path: str, index: int) -> str:
    """A valid anchor: `[0-9a-f]{4,}` (domain.ids.ANCHOR_MARK_RE), stable per (path, index)."""
    return hashlib.sha256(f"{path}:{index}".encode()).hexdigest()[:8]


def _people_doc(slug: str, name: str, claims: int = 1) -> CanonicalDocument:
    path = f"memory/people/{slug}.md"
    rows = "\n".join(
        f"- {name} owns workstream {i}. [cite: src-01 ¶{i}] <!-- c:{_anchor(path, i)} -->"
        for i in range(claims)
    )
    return _doc(path, f"# {name}\n\n## Role\n{rows}\n", type="person")


# ------------------------------------------------------- the compile face is unchanged


def test_compile_outline_is_the_shared_renderer_and_keeps_its_document_line_grammar():
    docs = [
        _people_doc("ada-quill", "Ada Quill", claims=2),
        _doc(
            "memory/topics/delta-pilot.md",
            "# Delta pilot\n\n## Scope\n- Fixed price. <!-- c:1a2b3c4d -->\n\n## Risks\n",
            type="topic",
        ),
    ]
    assert _render_outline(docs) == render_outline(docs)
    # The exact document-line grammar the compile task has always emitted: path, frontmatter
    # type, claim count, then the section headings joined — plus, under each, the one line at
    # the level below the title. These pages carry no overview, so that line is their own
    # ledger (`ledger:`, never `definition:` — see test_overview.py).
    assert render_outline(docs) == [
        "- `memory/people/ada-quill.md` (type=person, 2 claim(s)): Role",
        "    ledger: Ada Quill owns workstream 0. · Ada Quill owns workstream 1.",
        "- `memory/topics/delta-pilot.md` (type=topic, 1 claim(s)): Scope / Risks",
        "    ledger: Fixed price.",
    ]


def test_compile_outline_states_an_empty_base_rather_than_rendering_nothing():
    assert render_outline([]) == [prompt("compile.task.outline_empty")]


def test_compile_task_still_carries_the_outline_and_not_the_glance():
    """The compile prompt must not silently acquire the recall face's rendering: it is a
    byte-stable surface, and its line carries the fields a WRITER needs (type, headings)."""
    source = NormalizedSource(
        raw=RawSource(
            source_id=SourceId("src-01"),
            user_id=UserId("u-1"),
            kind="document",
            title="sync",
            mime="text/markdown",
            checksum="src-01",
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=0, text="body")],
        structure=StructureMap(),
    )
    task = _render_task([source], [_people_doc("ada-quill", "Ada Quill")])
    assert "- `memory/people/ada-quill.md` (type=person, 1 claim(s)): Role" in task
    assert prompt("recall.glance.header") not in task


# ----------------------------------------------------------------- mechanical per-doc


def test_title_prefers_the_first_heading_then_frontmatter_then_the_filename():
    assert document_title(_doc("memory/topics/a.md", "# Real Title\n\n## S\n")) == "Real Title"
    assert document_title(_doc("memory/topics/a.md", "## S\n", title="From FM")) == "From FM"
    # frontmatter always carries a slug in this fixture, which is the next fallback
    assert document_title(_doc("memory/topics/delta.md", "no headings")) == "delta"


def test_updated_is_rendered_from_the_callers_map_and_never_invented():
    docs = [_people_doc("ada-quill", "Ada Quill")]
    without = render_canonical_glance(docs, _skill())
    assert "updated" not in without
    with_dates = render_canonical_glance(
        docs, _skill(), updated={"memory/people/ada-quill.md": "2026-07-28"}
    )
    assert "updated 2026-07-28" in with_dates


# --------------------------------------------------------------------- the glance body


def test_glance_groups_documents_under_declared_families_including_empty_ones():
    docs = [
        _people_doc("ada-quill", "Ada Quill", claims=3),
        _people_doc("bo-marsh", "Bo Marsh"),
    ]
    text = render_canonical_glance(docs, _skill())

    assert text.startswith(prompt("recall.glance.header"))
    # every declared family is named, so the model knows the slots that exist
    for template in TEMPLATES:
        assert f"## {template}" in text
    assert "- `memory/people/ada-quill.md` — Ada Quill (3 claim(s))" in text
    assert "- `memory/people/bo-marsh.md` — Bo Marsh (1 claim(s))" in text
    # an unused family says so instead of silently vanishing
    assert text.count(prompt("recall.glance.family_empty")) == 3


def test_family_blurbs_come_from_pack_structure_not_from_skill_prose():
    pack = SchemaPack(
        pack_id="role-delivery",
        origin="matrix",
        extra_instructions=(
            "## Extra filing slots: engagements\n\n"
            "An engagement collects one client delivery and its commitments."
        ),
        extra_path_templates=["work/engagements/{slug}.md"],
    )
    # the blurb pairs with each template the pack declares, read off the fields
    assert family_blurbs([pack]) == {
        "work/engagements/{slug}.md": "Extra filing slots: engagements"
    }

    docs = [_doc("work/engagements/delta.md", "# Delta\n\n## Scope\n")]
    text = render_canonical_glance(
        docs, _skill(["work/engagements/{slug}.md"]), packs=[pack]
    )
    assert "  ↳ Extra filing slots: engagements" in text
    # a base family the skill declares itself has no structured blurb, and none is invented
    bare = render_canonical_glance(docs, _skill(["work/engagements/{slug}.md"]))
    assert "↳" not in bare


def test_documents_outside_every_family_are_listed_rather_than_dropped():
    docs = [_doc("stray/note.md", "# Stray\n\n## S\n")]
    text = render_canonical_glance(docs, _skill())
    assert prompt("recall.glance.unfiled_heading") in text
    assert "- `stray/note.md`" in text


def test_with_no_declared_families_the_glance_is_one_flat_list():
    docs = [_doc("memory/topics/a.md", "# A\n")]
    text = render_canonical_glance(docs, _skill([]))
    assert prompt("recall.glance.flat_heading") in text
    assert "- `memory/topics/a.md`" in text


def test_an_empty_base_still_shows_the_families_it_will_file_into():
    text = render_canonical_glance([], _skill())
    assert prompt("recall.glance.empty") in text
    assert "## memory/people/{slug}.md" in text


# ------------------------------------------------------------------------- truncation


def test_a_large_family_keeps_its_head_and_states_how_many_it_dropped():
    docs = [_people_doc(f"person-{i:02d}", f"Person {i:02d}") for i in range(12)]
    text = render_canonical_glance(docs, _skill(), top_k=5)
    assert text.count("- `memory/people/person-") == 5
    assert prompt("recall.glance.family_more", count=7) in text
    # sorted, so the head is deterministic rather than whatever order the store returned
    assert "- `memory/people/person-00.md`" in text
    assert "- `memory/people/person-11.md`" not in text


def test_the_whole_render_stops_at_the_budget_on_a_line_boundary():
    docs = [_people_doc(f"person-{i:02d}", f"Person {i:02d}") for i in range(40)]
    text = render_canonical_glance(docs, _skill(), top_k=40, budget=600)
    assert len(text) <= 600 + len(prompt("recall.glance.truncated", count=0)) + 8
    assert "more line(s) omitted" in text
    # no line is cut mid-path: every rendered entry names a document that can be opened
    for line in text.splitlines():
        if line.startswith("- `memory/"):
            assert line.count("`") == 2


# ------------------------------------------------------------------- rollover collapse


def _volume(
    active_path: str, number: int, claims: int = 4, *, stamped: bool = True
) -> CanonicalDocument:
    """A frozen archive volume of `active_path` — one file inside its same-name directory."""
    path = f"{active_path.removesuffix('.md')}/a{number:02d}.md"
    rows = "\n".join(
        f"- Archived fact {i}. [cite: src-01 ¶{i}] <!-- c:{_anchor(path, i)} -->"
        for i in range(claims)
    )
    frontmatter = (
        {"archived_from": active_path, "rollover_volume": f"{number:02d}"}
        if stamped
        else {}
    )
    return _doc(path, f"# Archived\n\n## History\n{rows}\n", **frontmatter)


def test_archive_volumes_are_counted_on_their_document_rather_than_listed_as_peers():
    """Listing every volume would let one long-lived subject crowd out every other family —
    the exact degradation rollover exists to fix. The count plus the active document's own
    volume links keep the archive one hop away."""
    active = _people_doc("ada-quill", "Ada Quill", claims=3)
    docs = [active, _volume(active.path, 1), _volume(active.path, 2)]
    text = render_canonical_glance(docs, _skill())

    assert "- `memory/people/ada-quill.md` — Ada Quill (3 claim(s), +2 archived volume(s))" in text
    assert "/a01.md" not in text and "/a02.md" not in text
    # counted, mechanically, off the volumes' own frontmatter
    assert archive_volume_counts(docs) == {active.path: 2}


def test_a_volume_is_recognized_by_its_directory_even_without_its_frontmatter_stamp():
    """Two agreeing signals identify a volume — the layout and the stamp — so a volume whose
    stamp went missing still collapses instead of reappearing as a peer document."""
    active = _people_doc("ada-quill", "Ada Quill")
    docs = [active, _volume(active.path, 1, stamped=False)]
    assert archive_volume_counts(docs) == {active.path: 1}
    assert "/a01.md" not in render_canonical_glance(docs, _skill())


def test_a_document_without_volumes_renders_exactly_as_before():
    docs = [_people_doc("bo-marsh", "Bo Marsh")]
    text = render_canonical_glance(docs, _skill())
    assert "- `memory/people/bo-marsh.md` — Bo Marsh (1 claim(s))" in text
    assert "archived volume" not in text


def test_an_orphaned_volume_is_listed_rather_than_folded_into_a_document_that_is_gone():
    """A volume whose origin document no longer exists must stay visible: silently hiding it
    would make its claims unreachable through the glance."""
    orphan = _volume("memory/people/ada-quill.md", 1)
    text = render_canonical_glance([orphan], _skill())
    assert f"- `{orphan.path}`" in text
    assert archive_volume_counts([orphan]) == {}


def test_the_compile_outline_lists_a_volume_but_marks_it_frozen_and_read_only():
    """A compiler still needs to see the volumes it may read — but the outline is the
    compiler's working-set map, and a volume line that reads like an editable peer document
    is how a compile ends up path-addressing frozen history. The line itself must state the
    freeze and name the active page that takes writes."""
    active = _people_doc("ada-quill", "Ada Quill")
    volume = _volume(active.path, 1)
    lines = render_outline([active, volume])
    volume_lines = [line for line in lines if volume.path in line]
    assert volume_lines == [
        prompt(
            "compile.task.outline_entry_volume",
            path=volume.path,
            owner=active.path,
            claims=4,
        )
    ]
    assert "frozen archive volume" in volume_lines[0]
    assert active.path in volume_lines[0]
    # the active page's own line is untouched — it still renders as an ordinary document
    assert any(line.startswith(f"- `{active.path}` (type=person") for line in lines)


def test_an_unstamped_volume_is_still_marked_frozen_in_the_outline_by_its_directory():
    """Same two agreeing signals as the glance collapse: a volume whose `archived_from`
    stamp went missing must not resurface in the compile outline as an editable peer."""
    active = _people_doc("ada-quill", "Ada Quill")
    volume = _volume(active.path, 1, stamped=False)
    lines = render_outline([active, volume])
    assert any(
        volume.path in line and "frozen archive volume" in line for line in lines
    )


def test_the_same_inputs_render_the_same_bytes():
    docs = [_people_doc("ada-quill", "Ada Quill"), _people_doc("bo-marsh", "Bo Marsh")]
    skill = _skill()
    assert render_canonical_glance(docs, skill) == render_canonical_glance(
        list(reversed(docs)), skill
    )


# ---------------------------------------- the ledger stands in for a missing definition
#
# The owner's rule: when a page holds little, those few claims ARE its overview — you take
# them in at a glance, and a rendered "no summary yet" would say less than the two sentences
# it is standing in front of. So the slot below the title is never empty when the ledger has
# anything in it: `definition:` when someone stated what the subject is, `ledger:` when the
# page is simply showing what it holds. The two labels are different on purpose.


def _with_overview(doc: CanonicalDocument, definition: str) -> CanonicalDocument:
    """`doc` with a system-delimited overview region carrying one definition slot."""
    region = (
        "<!-- overview -->\n\n<!-- overview:definition -->\n### What this is\n\n"
        f"{definition}\n\n<!-- /overview -->"
    )
    head, _, tail = doc.body.partition("\n")
    return CanonicalDocument(
        doc_id=doc.doc_id,
        path=doc.path,
        frontmatter=doc.frontmatter,
        body=f"{head}\n\n{region}\n{tail}",
    )


def _ledger_lines(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip().startswith("ledger:")]


def test_a_page_with_a_definition_renders_the_definition_and_no_ledger_line():
    doc = _with_overview(
        _people_doc("ada-quill", "Ada Quill", claims=2),
        "Ada Quill runs the Delta pilot. c:1a2b3c4d",
    )
    lines = render_outline([doc])
    assert lines[1].strip() == "definition: Ada Quill runs the Delta pilot."
    assert _ledger_lines(lines) == []
    glance = render_canonical_glance([doc], _skill())
    assert "    definition: Ada Quill runs the Delta pilot." in glance
    assert "ledger:" not in glance


def test_a_page_without_a_definition_shows_its_own_ledger_stripped_of_machinery():
    doc = _doc(
        "memory/topics/delta-pilot.md",
        "# Delta pilot\n\n## Scope\n"
        "- **Fixed price** for the first quarter. [cite: src-01 ¶3-4] <!-- c:1a2b3c4d -->\n"
        "- Ada Quill signs off each milestone. [cite: src-01 ¶7] <!-- c:2b3c4d5e -->\n"
        "- The pilot ends in March. [cite: src-02 ¶1] <!-- c:3c4d5e6f -->\n",
    )
    expected = (
        "Fixed price for the first quarter."
        f"{LEDGER_LINE_JOINER}Ada Quill signs off each milestone."
        f"{LEDGER_LINE_JOINER}The pilot ends in March."
    )
    lines = render_outline([doc])
    assert lines[1].strip() == f"ledger: {expected}"
    # the label is the point: this page was never defined, it is only being shown
    assert "definition:" not in "\n".join(lines)
    # nothing of the addressing machinery reaches a line a person reads
    for machinery in ("[cite:", "<!--", "c:1a2b3c4d", "**", "- "):
        assert machinery not in lines[1]
    assert f"    ledger: {expected}" in render_canonical_glance([doc], _skill())


def test_a_superseded_predecessor_is_not_shown_on_the_ledger_line():
    doc = _doc(
        "memory/people/bo-marsh.md",
        "# Bo Marsh\n\n## Role\n"
        "- Bo Marsh is the print liaison. [cite: src-01 ¶2] <!-- c:aa11bb22 -->\n"
        "- Bo Marsh is head of sourcing since May. [cite: src-02 ¶5] <!-- c:cc33dd44 -->"
        " <!-- supersedes: c:aa11bb22 -->\n",
        type="person",
    )
    line = document_ledger_line(doc, {"aa11bb22"})
    assert line == "Bo Marsh is head of sourcing since May."
    # and the renderers derive that dead set themselves, from the whole repository
    assert _ledger_lines(render_outline([doc])) == [f"ledger: {line}"]
    assert f"    ledger: {line}" in render_canonical_glance([doc], _skill())
    # without the successor the predecessor is simply the current state again
    assert document_ledger_line(doc).startswith("Bo Marsh is the print liaison.")


def test_a_successor_in_another_document_still_retires_its_predecessor_here():
    """The dead set is repository-wide: an active page routinely supersedes a claim that now
    lives in a frozen volume, so a per-document reading would show a retired state."""
    volume = _volume("memory/people/ada-quill.md", 1)
    volume = CanonicalDocument(
        doc_id=volume.doc_id,
        path=volume.path,
        frontmatter=volume.frontmatter,
        body="# Ada Quill (archive)\n\n## Role\n"
        "- Ada Quill was the pilot lead. [cite: src-01 ¶1] <!-- c:99aa88bb -->\n",
    )
    active = _doc(
        "memory/people/ada-quill.md",
        "# Ada Quill\n\n## Role\n"
        "- Ada Quill now leads sourcing. [cite: src-09 ¶2] <!-- c:77cc66dd -->"
        " <!-- supersedes: c:99aa88bb -->\n",
        type="person",
    )
    glance = render_canonical_glance([active, volume], _skill())
    assert "    ledger: Ada Quill now leads sourcing." in glance
    assert "was the pilot lead" not in glance


def test_the_ledger_line_stops_at_the_definitions_own_ceiling_on_a_claim_boundary():
    claims = [
        f"Milestone {i} was accepted by the review board without any recorded objection."
        for i in range(6)
    ]
    doc = _doc(
        "memory/topics/milestones.md",
        "# Milestones\n\n## Log\n"
        + "\n".join(
            f"- {text} [cite: src-01 ¶{i}] <!-- c:{_anchor('milestones', i)} -->"
            for i, text in enumerate(claims)
        )
        + "\n",
    )
    line = document_ledger_line(doc)
    assert len(line) <= DEFINITION_MAX_CHARS
    # it ended on a whole claim, not mid-sentence, and therefore needs no ellipsis
    assert line.endswith(claims[1])
    assert not line.endswith("…")
    assert claims[2] not in line

    # the one case with no boundary to stop on: a single claim longer than the whole line.
    # There is no honest line to render, so there is NO line — a claim cut at a character is
    # a different claim, and this slot is read as fact.
    long_claim = "A " + "very " * 80 + "long claim."
    solo = _doc(
        "memory/topics/one.md",
        f"# One\n\n## Log\n- {long_claim} [cite: src-01 ¶0] <!-- c:1a2b3c4d -->\n",
    )
    assert document_ledger_line(solo) is None
    assert _ledger_lines(render_outline([solo])) == []
    assert "ledger:" not in render_canonical_glance([solo], _skill())


def test_an_oversized_first_claim_is_dropped_whole_rather_than_shown_as_its_own_opposite():
    """The reason the character cut had to go: what lands past the ceiling is often the part
    that decides what the claim MEANS — a negation, a qualifier, an outcome. Rendering the
    prefix would put the claim's opposite in the one line a reader takes at face value."""
    qualified = (
        "The Delta pilot budget increase to 2.4M was proposed by the sourcing group and "
        "circulated to every workstream lead for comment ahead of the March review, "
        "with the finance office recording it as a planning figure only, "
        "but the board did not approve it."
    )
    assert len(qualified) > DEFINITION_MAX_CHARS
    assert len(qualified[:DEFINITION_MAX_CHARS]) > 0 and "but the board" not in (
        qualified[:DEFINITION_MAX_CHARS]
    )
    doc = _doc(
        "memory/topics/delta-budget.md",
        f"# Delta budget\n\n## Log\n- {qualified} [cite: src-01 ¶0] <!-- c:1a2b3c4d -->\n",
    )
    assert document_ledger_line(doc) is None
    # not a truncated fact, and not the SECOND claim standing in for the head of the ledger
    # either: a page whose first current claim cannot be shown shows no ledger line.
    two = _doc(
        "memory/topics/delta-budget.md",
        f"# Delta budget\n\n## Log\n- {qualified} [cite: src-01 ¶0] <!-- c:1a2b3c4d -->\n"
        "- The pilot ends in March. [cite: src-02 ¶1] <!-- c:2b3c4d5e -->\n",
    )
    assert document_ledger_line(two) is None
    glance = render_canonical_glance([two], _skill())
    assert "ledger:" not in glance
    assert "The pilot ends in March." not in glance
    # the page itself is still there, still countable, still one hop away
    assert "`memory/topics/delta-budget.md`" in glance


# ------------------------------------------------- markdown is form, and form is not the claim


def test_markdown_display_text_keeps_a_links_label_and_drops_its_destination():
    assert markdown_display_text("See [Delta](../delta.md) for the rest.") == (
        "See Delta for the rest."
    )
    assert markdown_display_text("[Ada Quill](memory/people/ada-quill.md) signs off.") == (
        "Ada Quill signs off."
    )
    # an image is a link's cousin and its alt text is the only readable half
    assert markdown_display_text("![the burndown chart](assets/burndown.png) was flat.") == (
        "the burndown chart was flat."
    )


def test_markdown_display_text_removes_emphasis_code_strikethrough_and_quoting():
    assert markdown_display_text("**Fixed price** for the quarter.") == (
        "Fixed price for the quarter."
    )
    assert markdown_display_text("The pilot is *paused*.") == "The pilot is paused."
    assert markdown_display_text("The pilot is _paused_.") == "The pilot is paused."
    assert markdown_display_text("Severity `P0` until Friday.") == "Severity P0 until Friday."
    assert markdown_display_text("~~old figure~~ 2.4M.") == "old figure 2.4M."
    assert markdown_display_text("> Ada Quill signs off.") == "Ada Quill signs off."
    assert markdown_display_text("### Scope\n- The pilot ends in March.") == (
        "Scope The pilot ends in March."
    )
    # an underscore inside a word is not emphasis: a claim may name a real identifier
    assert markdown_display_text("The `chunk_manifests` table is replayed.") == (
        "The chunk_manifests table is replayed."
    )


def test_markdown_display_text_drops_html_comments_without_eating_the_words_around_them():
    assert markdown_display_text("Ada <!-- c:1a2b3c4d --> signs off.") == "Ada signs off."
    assert markdown_display_text("Ada signs off. <!-- supersedes: c:2b3c4d5e -->") == (
        "Ada signs off."
    )
    assert markdown_display_text("Ada <!--\nan editorial note\n--> signs off.") == (
        "Ada signs off."
    )


def test_the_ledger_line_is_the_claim_in_plain_words_with_none_of_its_markdown():
    doc = _doc(
        "memory/topics/delta-pilot.md",
        "# Delta pilot\n\n## Scope\n"
        "- The *paused* [Delta](../delta.md) pilot is `P0` and ~~2.4M~~ 1.8M. "
        "[cite: src-01 ¶3] <!-- c:1a2b3c4d -->\n",
    )
    line = document_ledger_line(doc)
    assert line == "The paused Delta pilot is P0 and 2.4M 1.8M."
    for markup in ("](", "../delta.md", "*", "`", "~~", "<!--", "[cite:"):
        assert markup not in line
    assert f"    ledger: {line}" in render_canonical_glance([doc], _skill())


# ------------------------------------------- one title, stored and displayed, on any heading


def test_the_displayed_title_is_the_stored_one_on_an_annotated_heading():
    """`derived_title` (what a write STORES) and `document_title` (what every render SHOWS)
    read the same heading, so an anchor mark or a trailing comment can never leak into an
    outline, a glance, or the name a component reserves for the subject."""
    annotated = [
        "# Mei <!-- c:1a2b3c4d -->",
        "# Mei   <!-- c:1a2b3c4d -->",
        "# Mei <!-- c:1a2b3c4d --> <!-- supersedes: c:2b3c4d5e -->",
        "#   Mei  ",
        "# Mei <!-- an editorial note -->",
    ]
    for heading in annotated:
        doc = _doc("memory/people/mei.md", f"{heading}\n\n## Role\n", type="person")
        assert derived_title(doc.body) == "Mei"
        assert document_title(doc) == "Mei"
        assert document_title(doc) == derived_title(doc.body)
    # and it is the DISPLAYED name everywhere the title is rendered
    doc = _doc(
        "memory/people/mei.md",
        "# Mei <!-- c:1a2b3c4d -->\n\n## Role\n",
        type="person",
    )
    glance = render_canonical_glance([doc], _skill())
    assert "Mei" in glance and "c:1a2b3c4d" not in glance


def test_a_heading_that_is_only_machinery_is_no_title_and_falls_back_like_a_missing_one():
    """`# <!-- c:1a2b3c4d -->` says nothing a reader can use, so it is not a name — the
    frontmatter/filename fallback stands behind it exactly as behind a page with no heading."""
    doc = _doc("memory/topics/delta.md", "# <!-- c:1a2b3c4d -->\n\n## S\n")
    assert derived_title(doc.body) == ""
    assert document_title(doc) == "delta"  # the fixture's frontmatter slug
    assert document_title(doc) == (
        derived_title(doc.body) or doc.frontmatter["slug"]
    )


def test_a_page_with_no_claims_at_all_gets_no_line():
    empty = _doc("memory/topics/blank.md", "")
    headings_only = _doc("memory/topics/scaffold.md", "# Scaffold\n\n## Scope\n\n## Risks\n")
    for doc in (empty, headings_only):
        assert document_ledger_line(doc) is None
        assert _ledger_lines(render_outline([doc])) == []
        assert "ledger:" not in render_canonical_glance([doc], _skill())


def test_the_ledger_line_reads_the_ledger_only_and_never_the_overview_region():
    doc = _with_overview(
        _people_doc("ada-quill", "Ada Quill", claims=1),
        "",  # a region whose definition slot is empty is a page with no definition
    )
    line = document_ledger_line(doc)
    assert line == "Ada Quill owns workstream 0."
    assert "What this is" not in line
