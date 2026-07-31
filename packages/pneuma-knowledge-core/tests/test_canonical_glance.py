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
    archive_volume_counts,
    document_title,
    family_blurbs,
    render_canonical_glance,
    render_outline,
)
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


def test_compile_outline_is_the_shared_renderer_and_its_bytes_are_the_old_ones():
    docs = [
        _people_doc("ada-quill", "Ada Quill", claims=2),
        _doc(
            "memory/topics/delta-pilot.md",
            "# Delta pilot\n\n## Scope\n- Fixed price. <!-- c:1a2b3c4d -->\n\n## Risks\n",
            type="topic",
        ),
    ]
    assert _render_outline(docs) == render_outline(docs)
    # The exact line grammar the compile task has always emitted: path, frontmatter type,
    # claim count, then the section headings joined.
    assert render_outline(docs) == [
        "- `memory/people/ada-quill.md` (type=person, 2 claim(s)): Role",
        "- `memory/topics/delta-pilot.md` (type=topic, 1 claim(s)): Scope / Risks",
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


def test_the_collapse_does_not_touch_the_compile_outline():
    """The compile face is a byte-stable surface and rollover was not asked to change it: a
    compiler still needs to see the volumes it must not write into."""
    active = _people_doc("ada-quill", "Ada Quill")
    volume = _volume(active.path, 1)
    assert any(volume.path in line for line in render_outline([active, volume]))


def test_the_same_inputs_render_the_same_bytes():
    docs = [_people_doc("ada-quill", "Ada Quill"), _people_doc("bo-marsh", "Bo Marsh")]
    skill = _skill()
    assert render_canonical_glance(docs, skill) == render_canonical_glance(
        list(reversed(docs)), skill
    )
