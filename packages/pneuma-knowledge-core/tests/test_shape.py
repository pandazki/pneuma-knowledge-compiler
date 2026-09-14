"""The shared SHAPE module: what all three tiers read the library through.

Roles off the path templates, the subject fold, edges and claims through the framework's own
parsers, the two title predicates the gate and the check share, and the view that folds the
archive out of the counts without folding it out of the map.

If any of this is wrong, the gate refuses the wrong write, the check lists the wrong page and
the lens bands the wrong library — which is exactly why it is one module and one test.

Design authority: docs/design/structure-lens.md §4.1, §5.
"""

from __future__ import annotations

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_core.shape import (
    ROLE_CHILD,
    ROLE_CHRONOLOGY,
    ROLE_HUB,
    ROLE_OTHER,
    ROLE_PEOPLE,
    ROLE_TOPICS,
    family_role,
    hub_of,
    is_degenerate_title,
    path_allowed,
    project_dir,
    role_of,
    roles,
    shares_hub_title,
    subject_of,
    template_of,
)
from pneuma_knowledge_core.shape.links import subject_claims, subject_edges
from pneuma_knowledge_core.shape.text import (
    citation_sources,
    claim_blocks,
    claim_words,
    dated_sections,
    stray_headings,
)
from pneuma_knowledge_core.shape.view import build_view, judged_documents

TEMPLATES = [
    "projects/{slug}/overview.md",
    "projects/{slug}/evolution.md",
    "projects/{slug}/features/{slug}.md",
    "projects/{slug}/decisions/{slug}.md",
    "memory/people/{slug}.md",
    "memory/topics/{slug}.md",
]


def doc(path: str, body: str, **frontmatter) -> CanonicalDocument:
    frontmatter.setdefault("type", "page")
    frontmatter.setdefault("slug", path.rsplit("/", 1)[-1].removesuffix(".md"))
    return CanonicalDocument(
        doc_id=DocumentId(path[-12:].rjust(12, "x")),
        path=path,
        frontmatter=frontmatter,
        body=body,
    )


def claim(text: str, anchor: str) -> str:
    return f"{text} [cite: s01 ¶0-1] <!-- c:{anchor} -->"


# ──────────────────────────────────────────────────────────────────────── the roles


def test_a_family_role_is_read_off_the_templates_name_and_nothing_else():
    assert family_role("projects/{slug}/overview.md") == ROLE_HUB
    assert family_role("projects/{slug}/evolution.md") == ROLE_CHRONOLOGY
    assert family_role("projects/{slug}/features/{slug}.md") == ROLE_CHILD
    assert family_role("projects/{slug}/decisions/{slug}.md") == ROLE_CHILD
    assert family_role("memory/people/{slug}.md") == ROLE_PEOPLE
    assert family_role("memory/topics/{slug}.md") == ROLE_TOPICS
    # A contract using none of the table's names is told nothing about a layout nobody
    # described: an honest `other` rather than a guess.
    assert family_role("notes/{slug}.md") == ROLE_OTHER
    assert roles(TEMPLATES)["memory/people/{slug}.md"] == ROLE_PEOPLE


def test_a_paths_family_is_the_gates_own_ownership_predicate():
    assert template_of("projects/aurora/overview.md", TEMPLATES) == (
        "projects/{slug}/overview.md"
    )
    assert path_allowed("projects/aurora/overview.md", TEMPLATES)
    assert template_of("notes/loose.md", TEMPLATES) is None
    assert role_of("notes/loose.md", TEMPLATES) == ROLE_OTHER


def test_a_project_directory_is_the_segment_the_template_varies():
    for path in (
        "projects/aurora/overview.md",
        "projects/aurora/evolution.md",
        "projects/aurora/decisions/tank.md",
    ):
        assert project_dir(path, TEMPLATES) == "projects/aurora"
    # A family that declares no project has none — not a guess off the path's shape.
    assert project_dir("memory/people/mei.md", TEMPLATES) == ""


def test_a_closed_volume_folds_onto_the_page_it_was_cut_out_of():
    present = {"memory/topics/flow.md", "memory/topics/flow/a01.md"}
    assert subject_of("memory/topics/flow/a01.md", present) == "memory/topics/flow.md"
    # …and a volume whose page is gone is a subject of its own: folding it onto a path no
    # document has would make its claims belong to nothing.
    assert subject_of("memory/topics/flow/a01.md", {"memory/topics/flow/a01.md"}) == (
        "memory/topics/flow/a01.md"
    )


# ───────────────────────────────────────────────────────────────── edges and claims


def test_an_edge_is_a_link_inside_a_claim_or_an_overview_and_folds_onto_subjects():
    docs = [
        doc(
            "memory/topics/flow.md",
            "# Flow\n\n## What\n\n"
            + claim("It runs [the plant](../../projects/aurora/overview.md).", "a0000001")
            + "\n\nA heading link to [the pump](../../projects/aurora/features/pump.md)\n",
        ),
        doc("projects/aurora/overview.md", "# Aurora\n\n## A\n\n" + claim("A.", "a0000002")),
        doc(
            "projects/aurora/features/pump.md",
            "# Pump\n\n## A\n\n" + claim("B.", "a0000003"),
        ),
    ]
    edges = subject_edges({d.path: d for d in docs})
    # Only the link written inside an anchored claim is an edge: a line nobody cited is not
    # knowledge pointing anywhere.
    assert [(edge.subject, edge.target) for edge in edges] == [
        ("memory/topics/flow.md", "projects/aurora/overview.md")
    ]


def test_a_volumes_links_and_claims_belong_to_its_page():
    docs = {
        "memory/topics/flow.md": doc(
            "memory/topics/flow.md", "# Flow\n\n## A\n\n" + claim("A.", "a0000001")
        ),
        "memory/topics/flow/a01.md": doc(
            "memory/topics/flow/a01.md",
            "## Earlier\n\n"
            + claim("It once ran [the plant](../../../projects/aurora/overview.md).", "a0000002"),
            type="archive",
            archived_from="memory/topics/flow.md",
        ),
        "projects/aurora/overview.md": doc(
            "projects/aurora/overview.md", "# Aurora\n\n## A\n\n" + claim("B.", "a0000003")
        ),
    }
    assert subject_claims(docs)["memory/topics/flow.md"] == 2
    edges = subject_edges(docs)
    assert [(e.subject, e.target, e.source_path) for e in edges] == [
        (
            "memory/topics/flow.md",
            "projects/aurora/overview.md",
            "memory/topics/flow/a01.md",
        )
    ]


def test_the_text_derivations_read_what_the_write_faces_wrote():
    body = (
        "# Flow\n\n## 2026-01-04\n\n"
        + claim("First. [cite: s02 ¶1-2]", "a0000001")
        + "\n\n## 2026-03-04\n\n# A second name\n\n"
        + claim("Later.", "a0000002")
    )
    assert [date for _, date in dated_sections(body)] == ["2026-01-04", "2026-03-04"]
    assert [heading for _, heading in stray_headings(body)] == ["A second name"]
    assert len(claim_blocks(body)) == 2
    assert citation_sources(claim_blocks(body)[0]) == ["s02", "s01"]  # first-seen order
    assert "cite:" not in claim_words(claim_blocks(body)[0])


# ───────────────────────────────────────────────────────────────── the title rules


def test_a_degenerate_title_names_a_place_in_the_layout_and_a_hub_keeps_its_project_name():
    assert is_degenerate_title("projects/aurora/evolution.md", "Evolution", TEMPLATES)
    assert is_degenerate_title("projects/aurora/evolution.md", "演进", TEMPLATES)
    assert is_degenerate_title("memory/topics/flow.md", "", TEMPLATES)
    # The project's own slug, on a page that is not its hub…
    assert is_degenerate_title("projects/aurora/evolution.md", "aurora", TEMPLATES)
    # …and the hub itself IS the project, so its carrying that name is right.
    assert not is_degenerate_title("projects/aurora/overview.md", "aurora", TEMPLATES)
    assert not is_degenerate_title("projects/aurora/evolution.md", "Aurora timeline", TEMPLATES)


def test_a_chronology_wearing_its_hubs_name_is_reported_against_that_hub():
    titles = {
        "projects/aurora/overview.md": "Aurora",
        "projects/aurora/evolution.md": "Aurora",
        "memory/topics/flow.md": "Aurora",
    }
    assert hub_of("projects/aurora/evolution.md", list(titles), TEMPLATES) == (
        "projects/aurora/overview.md"
    )
    assert shares_hub_title("projects/aurora/evolution.md", titles, TEMPLATES) == (
        "projects/aurora/overview.md"
    )
    # Only a chronology is judged: a topic page that happens to share the name is the
    # check's `id.title_duplicate`, which says which page keeps it.
    assert shares_hub_title("memory/topics/flow.md", titles, TEMPLATES) == ""


# ─────────────────────────────────────────────────────────────────────── the view


def _library() -> list[CanonicalDocument]:
    return [
        doc(
            "memory/topics/flow.md",
            "# Flow\n\n## What\n\n"
            + claim("It runs [the plant](../../projects/aurora/overview.md).", "a0000001"),
        ),
        doc("projects/aurora/overview.md", "# Aurora\n\n## A\n\n" + claim("A.", "a0000002")),
        doc(
            "memory/topics/flow/a01.md",
            "## Earlier\n\n" + claim("Older.", "a0000003"),
            type="archive",
            archived_from="memory/topics/flow.md",
        ),
        doc("archive/memory/topics/old.md", "# Old\n\n## A\n\n" + claim("Gone.", "a0000004")),
    ]


def test_the_archive_leaves_the_counts_without_leaving_the_map():
    judged, known = judged_documents(_library())
    assert set(judged) == {
        "memory/topics/flow.md",
        "projects/aurora/overview.md",
        "memory/topics/flow/a01.md",
    }
    assert "archive/memory/topics/old.md" in known
    view = build_view(_library(), TEMPLATES)
    assert view.subjects == ("memory/topics/flow.md", "projects/aurora/overview.md")
    assert view.total_claims == 3  # the volume's claim belongs to its page
    assert view.titles["memory/topics/flow.md"] == "Flow"
    assert "archive/memory/topics/old.md" in view.known_paths


def test_the_view_counts_degree_over_subjects():
    view = build_view(_library(), TEMPLATES)
    assert view.out_degree == {"memory/topics/flow.md": 1}
    assert view.in_degree == {"projects/aurora/overview.md": 1}
    assert view.files_of("memory/topics/flow.md") == [
        "memory/topics/flow.md",
        "memory/topics/flow/a01.md",
    ]
