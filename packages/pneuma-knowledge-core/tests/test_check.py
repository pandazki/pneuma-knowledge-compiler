"""The check: every §3.1 item, over one small synthetic library.

The library below is deliberately HEALTHY — six subjects across the six declared families,
every one reachable and reaching, claims spread evenly, no malformed page — so it produces no
finding at all. Each test then breaks exactly one thing and asserts exactly one item notices.
That shape is the point: an item that fires on a clean library is an item nobody can act on,
and a finding that only appears in a library with five faults is a predicate nobody can read
off the test.

Design authority: docs/design/structure-lens.md §3.
"""

from __future__ import annotations

import pytest
from pneuma_knowledge_core.check import (
    CHECK_IDS,
    CHECK_KIND,
    JUDGEMENT_IDS,
    LEGACY_IDS,
    build_check,
    page_findings,
    render_action,
    render_impact,
)
from pneuma_knowledge_core.check.checks import (
    MENTION_MIN_COUNT,
    SINGLE_SOURCE_MIN_CLAIMS,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_core.prompts import (
    chinese_overlay,
    default_catalog,
    template_fields,
)

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


def healthy() -> list[CanonicalDocument]:
    """Six subjects, every family filled, every page reached and reaching."""
    return [
        doc(
            "projects/aurora/overview.md",
            "# Aurora\n\n## What it is\n\n"
            + claim("A water plant control stack.", "a0000001")
            + "\n\n"
            + claim(
                "Its history is in [the timeline](evolution.md), its parts in "
                "[the pump](features/pump.md) and [the tank choice](decisions/tank.md); "
                "[Mei Lark](../../memory/people/mei.md) runs it and "
                "[flow shaping](../../memory/topics/flow.md) is the idea behind it.",
                "a0000002",
            ),
        ),
        doc(
            "projects/aurora/evolution.md",
            "# Aurora timeline\n\n"
            "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
            "## 2026-02-04\n\n"
            + claim("[The pump](features/pump.md) was rebuilt.", "a0000004")
            + "\n\n"
            "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005"),
        ),
        doc(
            "projects/aurora/features/pump.md",
            "# Pump control\n\n## What it does\n\n"
            + claim("It holds pressure steady.", "a0000006")
            + "\n\n"
            + claim("It belongs to [the plant](../overview.md).", "a0000007"),
        ),
        doc(
            "projects/aurora/decisions/tank.md",
            "# Tank sizing\n\n## The choice\n\n"
            + claim("Two small vessels beat one large one.", "a0000008")
            + "\n\n"
            + claim("It constrains [the pump](../features/pump.md).", "a0000009"),
        ),
        doc(
            "memory/people/mei.md",
            "# Mei Lark\n\n## Who\n\n"
            + claim("An operations lead.", "a000000a")
            + "\n\n"
            + claim("She runs [the plant](../../projects/aurora/overview.md).", "a000000b"),
        ),
        doc(
            "memory/topics/flow.md",
            "# Flow shaping\n\n## What\n\n"
            + claim("Smoothing demand before it reaches a pump.", "a000000c")
            + "\n\n"
            + claim("It shows up in [the plant](../../projects/aurora/overview.md).", "a000000d"),
        ),
    ]


def check(docs, **kwargs):
    return build_check(docs, TEMPLATES, **kwargs)


def ids_of(report) -> set[str]:
    return {finding.id for finding in report.findings}


def replace(docs, path, body):
    """The same library with one page's body swapped."""
    return [doc(d.path, body, **d.frontmatter) if d.path == path else d for d in docs]


# ───────────────────────────────────────────────────────────────────── the clean base


def test_a_healthy_library_produces_no_finding_at_all():
    """The floor under every test below. An item that fires here is an item whose predicate
    says "this library exists", which is a number and not a finding (§1)."""
    report = check(healthy())
    assert report.findings == ()
    assert (report.subjects, report.files, report.claims) == (6, 6, 13)
    assert report.edges == 10


# ─────────────────────────────────────────────── judgement items: what is not linked


def test_a_hub_that_misses_pages_of_its_own_project_names_every_one_of_them():
    docs = replace(
        healthy(),
        "projects/aurora/overview.md",
        "# Aurora\n\n## What it is\n\n"
        + claim("A water plant control stack.", "a0000001")
        + "\n\n"
        + claim(
            "[Mei Lark](../../memory/people/mei.md) runs it and "
            "[flow shaping](../../memory/topics/flow.md) is the idea.",
            "a0000002",
        ),
    )
    hub = [f for f in check(docs).findings if f.id == "nav.hub_incomplete"]
    assert len(hub) == 1 and hub[0].kind == "judgement"
    assert hub[0].targets == (
        "projects/aurora/decisions/tank.md",
        "projects/aurora/evolution.md",
        "projects/aurora/features/pump.md",
    )
    for target in hub[0].targets:
        assert target in render_action(hub[0])


def test_a_dated_chronology_that_reaches_no_child_page_is_a_finding():
    docs = replace(
        healthy(),
        "projects/aurora/evolution.md",
        "# Aurora timeline\n\n"
        "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n" + claim("It was rebuilt.", "a0000004") + "\n\n"
        "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005"),
    )
    assert "nav.chronology_unlinked" in ids_of(check(docs))


def test_a_decision_page_with_no_outbound_link_is_a_finding():
    docs = replace(
        healthy(),
        "projects/aurora/decisions/tank.md",
        "# Tank sizing\n\n## The choice\n\n"
        + claim("Two small vessels beat one large one.", "a0000008"),
    )
    assert "nav.decision_unlinked" in ids_of(check(docs))


def test_a_subject_named_over_and_over_and_never_linked_is_a_mention():
    named = " ".join(["Flow shaping matters."] * MENTION_MIN_COUNT)
    docs = replace(
        healthy(),
        "projects/aurora/decisions/tank.md",
        "# Tank sizing\n\n## The choice\n\n"
        + claim(named, "a0000008")
        + "\n\n"
        + claim("It constrains [the pump](../features/pump.md).", "a0000009"),
    )
    mention = [f for f in check(docs).findings if f.id == "nav.mention_unlinked"]
    assert len(mention) == 1
    assert mention[0].targets == ("memory/topics/flow.md",)
    assert "Flow shaping" in render_impact(mention[0])


def test_a_link_to_a_path_no_document_has_is_a_dead_link():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    dead = [f for f in check(docs).findings if f.id == "nav.dead_link"]
    assert len(dead) == 1 and dead[0].kind == "judgement"
    assert dead[0].targets == ("projects/aurora/features/ghost.md",)
    assert "ghost.md" in render_impact(dead[0])


# ──────────────────────────────────────────── judgement items: identity and evidence


def test_two_live_subjects_in_different_directories_under_one_name():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Mei Lark\n\n## What\n\n"
        + claim("Smoothing demand.", "a000000c")
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    duplicate = [f for f in check(docs).findings if f.id == "id.title_duplicate"]
    assert len(duplicate) == 1
    assert duplicate[0].paths == ("memory/people/mei.md", "memory/topics/flow.md")
    assert duplicate[0].evidence == ("Mei Lark",)


def test_one_directory_is_the_gates_business_and_not_the_checks():
    """§3.1: `id.title_duplicate` is about DIFFERENT directories. A same-directory pair is
    what `title_sibling_collision` refuses at the write, and — between two pages nobody has
    touched — what the hub-shared and child-collision items say something useful about."""
    docs = replace(
        healthy(),
        "projects/aurora/evolution.md",
        "# Aurora\n\n"
        "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n"
        + claim("[The pump](features/pump.md) was rebuilt.", "a0000004")
        + "\n\n"
        "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005"),
    )
    found = ids_of(check(docs))
    assert "id.title_shared_with_hub" in found
    assert "id.title_duplicate" not in found


def test_a_developed_subject_resting_on_one_source_is_reported_with_that_source():
    blocks = "\n\n".join(
        claim(f"Fact {n}.", f"e{n:07d}") for n in range(SINGLE_SOURCE_MIN_CLAIMS)
    )
    docs = replace(
        healthy(), "memory/topics/flow.md", "# Flow shaping\n\n## What\n\n" + blocks
    )
    single = [f for f in check(docs).findings if f.id == "corr.single_source"]
    assert len(single) == 1
    assert single[0].evidence == ("s01",)
    assert str(SINGLE_SOURCE_MIN_CLAIMS) in render_impact(single[0])
    assert "s01" in render_action(single[0])


def _with_overview(definition: str, extra: str = "") -> str:
    return (
        "# Flow shaping\n\n"
        "<!-- overview -->\n\n"
        "<!-- overview:definition -->\n### Definition\n\n"
        f"{definition} <!-- c:a000000e -->\n\n"
        "<!-- /overview -->\n\n"
        f"{extra}"
        "## What\n\n" + claim("Smoothing demand before a pump.", "a000000c") + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d")
    )


def test_a_page_with_an_overview_head_and_the_old_four_sections_holds_one_picture_twice():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        _with_overview("An idea about demand.", extra="## Summary\n\n## Connections\n\n"),
    )
    legacy = [f for f in check(docs).findings if f.id == "form.legacy_sections"]
    assert len(legacy) == 1 and legacy[0].evidence == ("Summary", "Connections")


# ───────────────────────────────── legacy items: the tier-one faults, as they stand


def test_a_heading_below_the_top_of_a_body_is_a_stray_heading_with_its_line():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("Smoothing demand.", "a000000c")
        + "\n\n# Something else\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    stray = [f for f in check(docs).findings if f.id == "form.stray_heading"]
    assert len(stray) == 1 and stray[0].kind == "legacy"
    # Evidence is the heading, verbatim; the line number is a field the sentence speaks.
    assert stray[0].evidence == ("Something else",)
    assert "line 7" in render_impact(stray[0])
    assert "retitle" in render_action(stray[0])


def test_a_body_written_as_one_run_of_characters_is_a_collapsed_body():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("x" * 1_200, "a000000c")
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    collapsed = [f for f in check(docs).findings if f.id == "form.collapsed_body"]
    assert len(collapsed) == 1 and collapsed[0].kind == "legacy"


def test_a_title_that_names_a_family_role_is_degenerate_and_a_hub_keeps_its_project_name():
    docs = replace(
        healthy(),
        "projects/aurora/evolution.md",
        "# Evolution\n\n"
        "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n"
        + claim("[The pump](features/pump.md) was rebuilt.", "a0000004")
        + "\n\n"
        "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005"),
    )
    degenerate = [f for f in check(docs).findings if f.id == "id.title_degenerate"]
    assert [f.paths[0] for f in degenerate] == ["projects/aurora/evolution.md"]
    # The hub is called `Aurora`, which IS the project's name — and stays uncalled-out.
    assert "projects/aurora/overview.md" not in {f.paths[0] for f in degenerate}


def test_a_page_with_no_leading_heading_has_no_name_and_the_check_is_where_it_is_listed():
    """The gate refuses a name that says where a page sits; it does NOT refuse a page with no
    `# ` line at all, because that would abort every round whose model opens a body on a
    `## ` section. So the untitled pages a library already holds are listed here, with
    `retitle` as their repair."""
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "## What\n\n"
        + claim("Smoothing demand.", "a000000c")
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    degenerate = [f for f in check(docs).findings if f.id == "id.title_degenerate"]
    assert [f.paths[0] for f in degenerate] == ["memory/topics/flow.md"]
    assert "Retitle" in render_action(degenerate[0])


def test_a_chronology_carrying_its_hubs_name_names_the_hub_it_took_it_from():
    docs = replace(
        healthy(),
        "projects/aurora/evolution.md",
        "# Aurora\n\n"
        "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n"
        + claim("[The pump](features/pump.md) was rebuilt.", "a0000004")
        + "\n\n"
        "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005"),
    )
    shared = [f for f in check(docs).findings if f.id == "id.title_shared_with_hub"]
    assert len(shared) == 1
    assert shared[0].targets == ("projects/aurora/overview.md",)


def test_a_page_sharing_a_name_with_a_page_below_it_is_a_child_collision():
    docs = replace(
        healthy(),
        "projects/aurora/evolution.md",
        "# Tank sizing\n\n"
        "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n"
        + claim("[The pump](features/pump.md) was rebuilt.", "a0000004")
        + "\n\n"
        "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005"),
    )
    report = check(docs)
    collision = [f for f in report.findings if f.id == "id.title_child_collision"]
    assert len(collision) == 1
    assert collision[0].targets == ("projects/aurora/decisions/tank.md",)
    # …and the same pair is NOT also reported as a library-wide duplicate.
    assert "id.title_duplicate" not in ids_of(report)


def test_two_pages_in_one_directory_under_one_name_are_a_sibling_collision():
    """The legacy half of the gate's `title_sibling_collision`. The hook judges only the
    pages a round touched, so a pair two feature pages have carried since before the rule
    reaches a reader through nothing else: `id.title_duplicate` is the cross-directory case,
    and a child collision needs one page to sit below the other. A real 250-subject library
    held exactly this pair."""
    docs = healthy() + [
        doc(
            "projects/aurora/features/pump-two.md",
            "# Pump control\n\n## What it does\n\n"
            + claim("It holds pressure steady too.", "a000000f")
            + "\n\n"
            + claim("It belongs to [the plant](../overview.md).", "a0000010"),
        )
    ]
    report = check(docs)
    sibling = [f for f in report.findings if f.id == "id.title_sibling_collision"]
    assert len(sibling) == 1 and sibling[0].kind == "legacy"
    assert sibling[0].paths == (
        "projects/aurora/features/pump-two.md",
        "projects/aurora/features/pump.md",
    )
    assert sibling[0].evidence == ("Pump control",)
    assert "Retitle" in render_action(sibling[0])
    # One observation, one finding: the cross-directory item says nothing about this pair.
    assert "id.title_duplicate" not in ids_of(report)


def test_a_chronology_and_its_hub_under_one_name_stay_the_hub_items_observation():
    """They are siblings in the file tree — `overview.md` and `evolution.md` sit in one
    directory — and the hub item is the one that says which of the two keeps the name."""
    docs = replace(
        healthy(),
        "projects/aurora/evolution.md",
        "# Aurora\n\n"
        "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n"
        + claim("[The pump](features/pump.md) was rebuilt.", "a0000004")
        + "\n\n"
        "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005"),
    )
    found = ids_of(check(docs))
    assert "id.title_shared_with_hub" in found
    assert "id.title_sibling_collision" not in found


def test_dated_sections_that_do_not_run_forward_name_the_verb_that_reorders_them():
    docs = replace(
        healthy(),
        "projects/aurora/evolution.md",
        "# Aurora timeline\n\n"
        "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005") + "\n\n"
        "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n"
        + claim("[The pump](features/pump.md) was rebuilt.", "a0000004"),
    )
    unordered = [f for f in check(docs).findings if f.id == "form.unordered_chronology"]
    assert len(unordered) == 1
    assert unordered[0].evidence == ("2026-03-04", "2026-01-04")
    assert "reorder_chronology" in render_action(unordered[0])
    assert "2026-03-04 → 2026-01-04" in render_action(unordered[0])


def test_an_overview_slot_that_repeats_a_ledger_claim_says_nothing_new():
    docs = replace(
        healthy(), "memory/topics/flow.md", _with_overview("Smoothing demand before a pump.")
    )
    restates = [f for f in check(docs).findings if f.id == "form.overview_restates"]
    assert len(restates) == 1 and restates[0].evidence == ("definition",)


def test_a_definition_holding_only_references_says_nothing():
    docs = replace(healthy(), "memory/topics/flow.md", _with_overview("c:a000000c"))
    empty = [f for f in check(docs).findings if f.id == "form.definition_empty"]
    assert len(empty) == 1 and empty[0].kind == "legacy"


def test_a_cited_line_with_no_anchor_never_enters_the_claim_index():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("Smoothing demand.", "a000000c")
        + "\n\nAn orphan sentence. [cite: s01 ¶2-2]\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    orphan = [f for f in check(docs).findings if f.id == "form.unanchored_citation"]
    assert len(orphan) == 1 and orphan[0].evidence == ()
    assert "1 cited lines" in render_impact(orphan[0])


# ─────────────────────────────────────────────────────── the report's own mechanics


def test_findings_are_ordered_legacy_first_then_judgement_by_id_and_path():
    docs = replace(
        healthy(),
        # one legacy (a stray heading) and one judgement (a link to nothing)…
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c")
        + "\n\n# A second name\n",
    )
    docs = replace(
        docs,
        # …and one more judgement: a decision page that links to nothing.
        "projects/aurora/decisions/tank.md",
        "# Tank sizing\n\n## The choice\n\n"
        + claim("Two small vessels beat one large one.", "a0000008"),
    )
    report = check(docs)
    kinds = [0 if f.kind == "legacy" else 1 for f in report.findings]
    assert kinds == sorted(kinds)
    assert {"legacy", "judgement"} == {f.kind for f in report.findings}
    judgement = [f.id for f in report.findings if f.kind == "judgement"]
    assert judgement == sorted(judgement)


def test_a_key_is_stable_under_the_same_evidence_and_moves_when_the_evidence_moves():
    """The key is what a decision is made ABOUT (§5.1). It has to survive a rebuild of the
    same library and it has to change when the observation changes — otherwise an answer given
    about one state silently stands over another."""
    broken = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    first = check(broken).findings
    again = check(list(reversed(broken))).findings
    assert [f.key for f in first] == [f.key for f in again]

    moved = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the phantom](../../projects/aurora/features/phantom.md).", "a000000c"),
    )
    dead_first = next(f for f in first if f.id == "nav.dead_link")
    dead_moved = next(f for f in check(moved).findings if f.id == "nav.dead_link")
    assert dead_first.key != dead_moved.key


def test_no_finding_lists_a_bare_number_as_evidence():
    """The rule §5.1 states, over every item at once: evidence is verbatim library text — a
    path, a title, a heading, a date, an href, a source id — never a count or a share."""
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Mei Lark\n\n## What\n\n"
        + claim("2026-01-01，did a thing.", "a000000c")
        + "\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000d"),
    )
    docs = replace(
        docs,
        "projects/aurora/evolution.md",
        "# Aurora timeline\n\n"
        "## 2026-03-04\n\n" + claim("Live.", "a0000005") + "\n\n"
        "## 2026-01-04\n\n" + claim("First.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n" + claim("Rebuilt.", "a0000004"),
    )
    for finding in check(docs).findings:
        for item in finding.evidence:
            assert not item.replace("%", "").replace(".", "").isdigit(), (
                f"{finding.id} lists a bare number as evidence: {item!r}"
            )


def test_a_closed_volume_belongs_to_its_page_in_every_count_and_in_page_findings():
    docs = healthy() + [
        doc(
            "projects/aurora/features/pump/a01.md",
            "## Earlier\n\n" + claim("It used to run on mains water.", "f0000001"),
            type="archive",
            archived_from="projects/aurora/features/pump.md",
        )
    ]
    report = check(docs)
    assert report.subjects == 6 and report.files == 7
    assert report.claims == 14  # the volume's claim belongs to the subject
    assert report.findings == ()
    # …and a caller asking about the volume is answered about its page.
    stray = check(
        replace(
            docs,
            "memory/topics/flow.md",
            "# Flow shaping\n\n## What\n\n# Twice\n\n" + claim("A", "a000000c"),
        )
    )
    assert page_findings(stray, "memory/topics/flow.md")


def test_the_archive_leaves_the_counts_without_leaving_the_map():
    """An archived document is out of every count and still resolves a link, so a page that
    points at a subject the Owner retired is not reported as a dead link."""
    docs = healthy() + [
        doc("archive/memory/topics/old.md", "# Old idea\n\n" + claim("A", "f0000002"))
    ]
    docs = replace(
        docs,
        "memory/people/mei.md",
        "# Mei Lark\n\n## Who\n\n"
        + claim("An operations lead.", "a000000a")
        + "\n\n"
        + claim(
            "She runs [the plant](../../projects/aurora/overview.md) and once believed "
            "[an old idea](../../archive/memory/topics/old.md).",
            "a000000b",
        ),
    )
    report = check(docs)
    assert (report.subjects, report.files, report.claims) == (6, 6, 13)
    assert report.findings == ()


def test_to_dict_is_the_wire_shape_the_faces_code_against():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    payload = check(docs, ref="HEAD", read_at="2026-03-01T00:00:00Z").to_dict()
    assert set(payload) == {
        "ref",
        "read_at",
        "subjects",
        "files",
        "claims",
        "edges",
        "findings",
    }
    finding = next(f for f in payload["findings"] if f["id"] == "nav.dead_link")
    assert set(finding) == {
        "key",
        "id",
        "kind",
        "paths",
        "targets",
        "evidence",
        "impact",
        "action",
    }
    assert set(finding["impact"]) == {"key", "fields", "text"}
    assert set(finding["impact"]["text"]) == {"en", "zh"}
    assert finding["impact"]["key"] == "check.nav.dead_link.impact"


def test_a_contract_that_declares_none_of_the_family_roles_is_told_nothing_about_layout():
    """The role table is the whole of the framework's domain knowledge about layout (§2): a
    contract using none of those names is told nothing about a layout nobody described."""
    docs = [
        doc("notes/one.md", "# One\n\n## A\n\n" + claim("Alpha.", "a1111111")),
        doc("notes/two.md", "# Two\n\n## A\n\n" + claim("Beta.", "a2222222")),
    ]
    assert build_check(docs, ["notes/{slug}.md"]).findings == ()


# ──────────────────────────────────────────────────── every item has both sentences


@pytest.mark.parametrize("item", CHECK_IDS)
def test_every_item_carries_an_impact_and_an_action_in_both_packs(item):
    """§1's first ruling, mechanically: a number with no consequence and no action is not a
    finding, so an item with no pair of sentences cannot ship."""
    english, chinese = default_catalog(), chinese_overlay()
    for key in (f"check.{item}.impact", f"check.{item}.action"):
        assert key in english and english[key].strip()
        assert key in chinese and chinese[key].strip()
    assert CHECK_KIND[item] in {"legacy", "judgement"}


def test_the_two_kinds_are_exactly_the_designs_two_tables():
    assert set(CHECK_IDS) == set(JUDGEMENT_IDS) | set(LEGACY_IDS)
    assert not set(JUDGEMENT_IDS) & set(LEGACY_IDS)
    # 11 legacy: §2's ten hooks, plus the repeated-date half of the chronology item. It is
    # split from the inversion because the two have different repairs — `reorder_chronology`
    # sorts, and a page whose sections already ascend and merely share a date is sorted.
    assert len(JUDGEMENT_IDS) == 8 and len(LEGACY_IDS) == 11


#: What a finding has to be ABOUT for its sentence to be worth reading: the page, or the
#: title that stands over two of them.
IDENTIFYING_FIELDS = {"path", "title", "paths"}


@pytest.mark.parametrize("item", CHECK_IDS)
def test_both_sentences_of_every_item_name_what_the_finding_is_about(item):
    """A console once showed "This project is an island" with no project and no counts,
    because a face had kept its own copy of these sentences and the copy had no placeholders.
    The rule that makes that unwriteable: each pair must interpolate the thing the finding is
    about, in BOTH packs."""
    english, chinese = default_catalog(), chinese_overlay()
    for pack in (english, chinese):
        declared = template_fields(pack[f"check.{item}.impact"]) | template_fields(
            pack[f"check.{item}.action"]
        )
        assert declared & IDENTIFYING_FIELDS, (
            f"{item}: neither sentence names the page it is about"
        )


def a_library_with_many_faults() -> list[CanonicalDocument]:
    """One library carrying a fault of most kinds at once — the fixture the rendering test
    wants, where the per-item tests deliberately break one thing at a time."""
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Mei Lark\n\n## What\n\n"
        + claim("2026-01-01，did a thing.", "a000000c")
        + "\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000d")
        + "\n\n# A second name\n",
    )
    docs = replace(
        docs,
        "projects/aurora/evolution.md",
        "# Evolution\n\n"
        "## 2026-03-04\n\n" + claim("Live.", "a0000005") + "\n\n"
        "## 2026-01-04\n\n" + claim("First.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n" + claim("Rebuilt.", "a0000004"),
    )
    return replace(
        docs,
        "projects/aurora/decisions/tank.md",
        "# Tank sizing\n\n## The choice\n\n"
        + claim("Two small vessels beat one large one.", "a0000008"),
    )


def test_to_dict_carries_each_sentence_rendered_in_both_packs_with_nothing_left_to_fill():
    """§5.2: the key and the fields stay the authority, and the rendered pair rides beside
    them so no face has to keep — and drift from — its own copy of these sentences."""
    payload = check(a_library_with_many_faults()).to_dict()
    assert len(payload["findings"]) >= 5
    catalog = default_catalog()
    for finding in payload["findings"]:
        for half in ("impact", "action"):
            phrase = finding[half]
            assert set(phrase) == {"key", "fields", "text"}
            for language, rendered in phrase["text"].items():
                assert rendered.strip(), (finding["id"], half, language)
                for name in template_fields(catalog[phrase["key"]]):
                    assert "{" + name + "}" not in rendered, (
                        f"{finding['id']}.{half} ({language}) left {{{name}}} unfilled"
                    )
            # The Chinese sentence is a translation, not the English one repeated.
            assert phrase["text"]["zh"] != phrase["text"]["en"]


def test_the_rendered_pair_ignores_whatever_overlay_this_process_registered():
    """The English half is the CATALOG's sentence and the Chinese half is the PACK's. A
    deployment that rewords a surface reworded its own surface, in its own language; it does
    not get to decide what the other language in this payload says."""
    from pneuma_knowledge_core.prompts import override_prompt, reset_prompt_overrides

    docs = a_library_with_many_faults()
    before = check(docs).findings[0].impact.text()
    try:
        override_prompt("check.form.stray_heading.impact", "OVERRIDDEN {path} {line}")
        override_prompt("check.id.title_degenerate.impact", "OVERRIDDEN {path} {title}")
        after = check(docs).findings[0].impact.text()
    finally:
        reset_prompt_overrides()
    assert after == before
    assert "OVERRIDDEN" not in after["en"] and "OVERRIDDEN" not in after["zh"]


def test_render_impact_and_render_action_answer_in_the_active_pack():
    """The CLI reads one language — the one this process is running in — so the two renderers
    keep going through `prompt()` and keep seeing an override."""
    from pneuma_knowledge_core.prompts import override_prompts, reset_prompt_overrides

    finding = next(
        f for f in check(a_library_with_many_faults()).findings
        if f.id == "form.stray_heading"
    )
    assert render_impact(finding) == finding.impact.text()["en"]
    try:
        override_prompts(chinese_overlay())
        assert render_impact(finding) == finding.impact.text()["zh"]
        assert render_action(finding) == finding.action.text()["zh"]
    finally:
        reset_prompt_overrides()
