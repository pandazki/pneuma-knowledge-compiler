"""The structure lens: every §4 predicate, over one small synthetic library.

The library below is deliberately HEALTHY — six subjects across the six declared families,
every one reachable and reaching, claims spread evenly, no malformed page — so it produces
no finding at all. Each test then breaks exactly one thing and asserts exactly one lens
notices. That shape is the point: a lens that fires on a clean library is a lens nobody can
act on, and a finding that only appears in a library with five faults is a finding whose
predicate nobody can read off the test.

Design authority: docs/design/structure-lens.md.
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_core.lens import (
    Decision,
    build_report,
    page_findings,
    render_action,
    render_impact,
)
from pneuma_knowledge_core.lens.lenses import (
    LENS_IDS,
    LENS_LEVEL,
    MENTION_MIN_COUNT,
    SESSION_SHAPED_MIN_CLAIMS,
    SINGLE_SOURCE_MIN_CLAIMS,
)
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


def report(docs, **kwargs):
    return build_report(docs, TEMPLATES, **kwargs)


def lenses_of(rep) -> set[str]:
    return {finding.lens for finding in rep.findings}


def replace(docs, path, body):
    """The same library with one page's body swapped."""
    return [doc(d.path, body, **d.frontmatter) if d.path == path else d for d in docs]


# ───────────────────────────────────────────────────────────────────── the clean base


def test_a_healthy_library_produces_no_finding_at_all():
    """The floor under every test below. A lens that fires here is a lens whose predicate
    says "this library exists", which is a number and not a finding (§1)."""
    rep = report(healthy())
    assert rep.findings == ()
    assert rep.score == 100
    assert (rep.subjects, rep.files, rep.claims) == (6, 6, 13)
    assert rep.edges == 10


def test_the_base_counts_and_family_table_describe_the_same_library():
    rep = report(healthy())
    assert [family.name for family in rep.families] == TEMPLATES
    assert sum(family.pages for family in rep.families) == rep.subjects
    assert sum(family.claims for family in rep.families) == rep.claims
    assert pytest.approx(sum(f.share for f in rep.families), abs=1e-3) == 1.0


# ─────────────────────────────────────────────────────────────────── 4.1 navigability


def test_dead_ends_are_one_finding_for_the_whole_library_naming_every_subject():
    """§4.1: on its own this lens says nothing about WHICH link is owed, so a row per page
    is one number repeated a hundred times. One finding, every affected subject in `paths`,
    the count and the share spoken by the sentence."""
    docs = replace(
        healthy(), "memory/topics/flow.md", "# Flow shaping\n\n## What\n\n" + claim("A", "a000000c")
    )
    docs = replace(
        docs,
        "projects/aurora/decisions/tank.md",
        "# Tank sizing\n\n## The choice\n\n"
        + claim("Two small vessels beat one large one.", "a0000008"),
    )
    rep = report(docs)
    dead = [f for f in rep.findings if f.lens == "nav.dead_end"]
    assert len(dead) == 1
    assert dead[0].key.startswith("nav.dead_end:library:")
    assert dead[0].paths == ("memory/topics/flow.md", "projects/aurora/decisions/tank.md")
    assert dead[0].evidence == ()
    assert dead[0].weight == pytest.approx(2 / 6, abs=1e-3)
    assert "2 subjects" in render_impact(dead[0]) and "33%" in render_impact(dead[0])
    assert "2 pages" in render_action(dead[0])


def test_a_subject_nothing_links_to_is_arrival_blind_and_says_what_it_holds():
    # The overview stops naming the topic page; nothing else reaches it either.
    docs = replace(
        healthy(),
        "projects/aurora/overview.md",
        "# Aurora\n\n## What it is\n\n"
        + claim("A water plant control stack.", "a0000001")
        + "\n\n"
        + claim(
            "Its history is in [the timeline](evolution.md), its parts in "
            "[the pump](features/pump.md) and [the tank choice](decisions/tank.md); "
            "[Mei Lark](../../memory/people/mei.md) runs it.",
            "a0000002",
        ),
    )
    rep = report(docs)
    blind = [f for f in rep.findings if f.lens == "nav.arrival_blind"]
    assert len(blind) == 1
    assert blind[0].key.startswith("nav.arrival_blind:library:")
    assert blind[0].paths == ("memory/topics/flow.md",)
    assert blind[0].evidence == ()
    assert "1" in render_impact(blind[0]) and "17%" in render_impact(blind[0])


def test_a_link_to_a_path_no_document_has_is_a_dead_link_shape_finding():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    rep = report(docs)
    dead = [f for f in rep.findings if f.lens == "nav.dead_link"]
    assert len(dead) == 1
    assert dead[0].level == "shape" and dead[0].actor == "mechanism"
    assert dead[0].targets == ("projects/aurora/features/ghost.md",)
    assert "ghost.md" in render_impact(dead[0])


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
    rep = report(docs)
    hub = [f for f in rep.findings if f.lens == "nav.hub_incomplete"]
    assert len(hub) == 1
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
    rep = report(docs)
    assert "nav.chronology_unlinked" in lenses_of(rep)


def test_a_decision_page_with_no_outbound_link_is_a_finding():
    docs = replace(
        healthy(),
        "projects/aurora/decisions/tank.md",
        "# Tank sizing\n\n## The choice\n\n"
        + claim("Two small vessels beat one large one.", "a0000008"),
    )
    rep = report(docs)
    assert "nav.decision_unlinked" in lenses_of(rep)


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
    rep = report(docs)
    mention = [f for f in rep.findings if f.lens == "nav.mention_unlinked"]
    assert len(mention) == 1
    assert mention[0].targets == ("memory/topics/flow.md",)
    assert "Flow shaping" in render_impact(mention[0])


def test_a_project_nothing_outside_reaches_is_an_island_addressed_to_the_owner():
    docs = [
        d
        for d in healthy()
        if d.path not in {"memory/people/mei.md", "memory/topics/flow.md"}
    ]
    docs = replace(
        docs,
        "projects/aurora/overview.md",
        "# Aurora\n\n## What it is\n\n"
        + claim("A water plant control stack.", "a0000001")
        + "\n\n"
        + claim(
            "Its history is in [the timeline](evolution.md), its parts in "
            "[the pump](features/pump.md) and [the tank choice](decisions/tank.md).",
            "a0000002",
        ),
    )
    docs = docs + [
        doc(
            "memory/topics/flow.md",
            "# Flow shaping\n\n## What\n\n" + claim("An idea about demand.", "a000000c"),
        )
    ]
    rep = report(docs)
    island = [f for f in rep.findings if f.lens == "nav.island"]
    assert len(island) == 1
    assert island[0].level == "principle" and island[0].actor == "owner"
    assert island[0].paths == (
        "projects/aurora/decisions/tank.md",
        "projects/aurora/evolution.md",
        "projects/aurora/features/pump.md",
        "projects/aurora/overview.md",
    )


# ────────────────────────────────────────────────────────────────────── 4.2 identity


def test_two_live_subjects_under_one_name_is_a_principle_finding():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Mei Lark\n\n## What\n\n"
        + claim("Smoothing demand.", "a000000c")
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    rep = report(docs)
    duplicate = [f for f in rep.findings if f.lens == "id.title_duplicate"]
    assert len(duplicate) == 1
    assert duplicate[0].level == "principle"
    assert duplicate[0].paths == ("memory/people/mei.md", "memory/topics/flow.md")


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
    rep = report(docs)
    collision = [f for f in rep.findings if f.lens == "id.title_child_collision"]
    assert len(collision) == 1
    assert collision[0].level == "shape"
    assert collision[0].targets == ("projects/aurora/decisions/tank.md",)
    # …and the same pair is NOT also reported as a library-wide duplicate.
    assert "id.title_duplicate" not in lenses_of(rep)


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
    rep = report(docs)
    degenerate = [f for f in rep.findings if f.lens == "id.title_degenerate"]
    assert [f.paths[0] for f in degenerate] == ["projects/aurora/evolution.md"]
    # The hub is called `Aurora`, which IS the project's name — and stays uncalled-out.
    assert "projects/aurora/overview.md" not in {f.paths[0] for f in degenerate}


def test_a_chronology_carrying_its_hubs_name_is_reported_against_the_hub():
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
    rep = report(docs)
    shared = [f for f in rep.findings if f.lens == "id.title_shared_with_hub"]
    assert len(shared) == 1
    assert shared[0].targets == ("projects/aurora/overview.md",)
    # …and the same pair is NOT also reported as a library-wide duplicate: one observation,
    # one finding. A real library showed the Owner four projects twice over.
    assert "id.title_duplicate" not in lenses_of(rep)


# ────────────────────────────────────────────────────────────────────────── 4.3 form


def test_a_body_written_as_one_run_of_characters_is_a_collapsed_body():
    long_claim = "x" * 1_200
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim(long_claim, "a000000c")
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    rep = report(docs)
    collapsed = [f for f in rep.findings if f.lens == "form.collapsed_body"]
    assert len(collapsed) == 1 and collapsed[0].level == "shape"


def test_a_heading_below_the_top_of_a_body_is_a_stray_heading_with_its_line():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("Smoothing demand.", "a000000c")
        + "\n\n# Something else\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    rep = report(docs)
    stray = [f for f in rep.findings if f.lens == "form.stray_heading"]
    assert len(stray) == 1
    # Evidence is the heading, verbatim; the line number is a field the sentence speaks.
    assert stray[0].evidence == ("Something else",)
    assert "line 7" in render_impact(stray[0])


def test_a_cited_line_with_no_anchor_never_enters_the_claim_index():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("Smoothing demand.", "a000000c")
        + "\n\nAn orphan sentence. [cite: s01 ¶2-2]\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    rep = report(docs)
    orphan = [f for f in rep.findings if f.lens == "form.unanchored_citation"]
    assert len(orphan) == 1 and orphan[0].evidence == ()
    assert "1 cited lines" in render_impact(orphan[0])


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


def test_an_overview_slot_that_repeats_a_ledger_claim_says_nothing_new():
    docs = replace(
        healthy(), "memory/topics/flow.md", _with_overview("Smoothing demand before a pump.")
    )
    rep = report(docs)
    restates = [f for f in rep.findings if f.lens == "form.overview_restates"]
    assert len(restates) == 1 and restates[0].evidence == ("definition",)


def test_a_page_with_an_overview_head_and_the_old_four_sections_holds_one_picture_twice():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        _with_overview("An idea about demand.", extra="## Summary\n\n## Connections\n\n"),
    )
    rep = report(docs)
    legacy = [f for f in rep.findings if f.lens == "form.legacy_sections"]
    assert len(legacy) == 1 and legacy[0].evidence == ("Summary", "Connections")


def test_a_definition_holding_only_references_says_nothing():
    docs = replace(healthy(), "memory/topics/flow.md", _with_overview("c:a000000c"))
    rep = report(docs)
    empty = [f for f in rep.findings if f.lens == "form.definition_empty"]
    assert len(empty) == 1 and empty[0].level == "shape"


def test_dated_sections_that_do_not_run_forward_are_reported_with_the_first_inversion():
    docs = replace(
        healthy(),
        "projects/aurora/evolution.md",
        "# Aurora timeline\n\n"
        "## 2026-03-04\n\n" + claim("The plant went live.", "a0000005") + "\n\n"
        "## 2026-01-04\n\n" + claim("The first prototype ran.", "a0000003") + "\n\n"
        "## 2026-02-04\n\n"
        + claim("[The pump](features/pump.md) was rebuilt.", "a0000004"),
    )
    rep = report(docs)
    unordered = [f for f in rep.findings if f.lens == "form.unordered_chronology"]
    assert len(unordered) == 1
    assert unordered[0].evidence == ("2026-03-04", "2026-01-04")
    assert "2026-03-04 → 2026-01-04" in render_action(unordered[0])


# ──────────────────────────────────────────────────────── 4.4 concentration and balance


def test_one_subject_swallowing_the_library_is_a_catch_all():
    blocks = "\n\n".join(claim(f"Fact {n}.", f"b{n:07d}") for n in range(30))
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + blocks
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    rep = report(docs)
    catch_all = [f for f in rep.findings if f.lens == "conc.catch_all"]
    assert len(catch_all) == 1
    assert catch_all[0].paths == ("memory/topics/flow.md",)
    assert catch_all[0].level == "principle"


def test_a_declared_family_no_page_was_ever_filed_under_is_a_principle_finding():
    docs = [d for d in healthy() if d.path != "memory/people/mei.md"]
    rep = report(docs)
    empty = [f for f in rep.findings if f.lens == "bal.family_empty"]
    assert [f.evidence for f in empty] == [("memory/people/{slug}.md",)]


def test_a_family_carrying_far_more_claims_than_pages_is_heavy():
    blocks = "\n\n".join(claim(f"Fact {n}.", f"c{n:07d}") for n in range(24))
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + blocks
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    rep = report(docs)
    heavy = [f for f in rep.findings if f.lens == "bal.family_heavy"]
    assert len(heavy) == 1
    # A family finding names the family, never a page: no one page is the imbalance.
    assert heavy[0].paths == () and heavy[0].level == "principle"
    assert "memory/topics/{slug}.md" in render_impact(heavy[0])


def test_a_subject_of_dated_single_source_entries_is_shaped_like_a_log():
    entries = "\n\n".join(
        claim(f"2026-01-0{n}，did a thing.", f"d{n:07d}")
        for n in range(1, SESSION_SHAPED_MIN_CLAIMS + 1)
    )
    docs = replace(
        healthy(), "memory/topics/flow.md", "# Flow shaping\n\n## Log\n\n" + entries
    )
    rep = report(docs)
    shaped = [f for f in rep.findings if f.lens == "bal.session_shaped"]
    assert len(shaped) == 1 and shaped[0].level == "drift"
    assert "100%" in render_impact(shaped[0])


# ───────────────────────────────────────────────────────────────── 4.5 corroboration


def test_a_developed_subject_resting_on_one_source_is_reported_with_that_source():
    blocks = "\n\n".join(
        claim(f"Fact {n}.", f"e{n:07d}") for n in range(SINGLE_SOURCE_MIN_CLAIMS)
    )
    docs = replace(
        healthy(), "memory/topics/flow.md", "# Flow shaping\n\n## What\n\n" + blocks
    )
    rep = report(docs)
    single = [f for f in rep.findings if f.lens == "corr.single_source"]
    assert len(single) == 1
    assert single[0].evidence == ("s01",)
    assert str(SINGLE_SOURCE_MIN_CLAIMS) in render_impact(single[0])
    assert "s01" in render_action(single[0])


# ─────────────────────────────────────────────────────────── the report's own mechanics


def test_a_key_is_stable_under_the_same_evidence_and_moves_when_the_evidence_moves():
    """The key is what a decision is made ABOUT (§3, §5.2). It has to survive a rebuild of
    the same library and it has to change when the observation changes — otherwise an answer
    given about one state silently stands over another."""
    broken = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    first = report(broken).findings
    again = report(list(reversed(broken))).findings
    assert [f.key for f in first] == [f.key for f in again]

    moved = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the phantom](../../projects/aurora/features/phantom.md).", "a000000c"),
    )
    dead_first = next(f for f in first if f.lens == "nav.dead_link")
    dead_moved = next(f for f in report(moved).findings if f.lens == "nav.dead_link")
    assert dead_first.key != dead_moved.key


def test_a_changed_count_yields_a_new_key_even_when_the_evidence_is_unchanged():
    """Evidence holds only verbatim library text (§3), so the numbers that tell one instance
    of a lens from the next live in the fields — and are hashed into the key there. A finding
    whose count moved is a different observation, whichever half of it speaks the number."""
    one = replace(
        healthy(), "memory/topics/flow.md", "# Flow shaping\n\n## What\n\n" + claim("A", "a000000c")
    )
    two = replace(
        one,
        "projects/aurora/decisions/tank.md",
        "# Tank sizing\n\n## The choice\n\n"
        + claim("Two small vessels beat one large one.", "a0000008"),
    )
    first = next(f for f in report(one).findings if f.lens == "nav.dead_end")
    second = next(f for f in report(two).findings if f.lens == "nav.dead_end")
    assert first.evidence == second.evidence == ()
    assert first.key != second.key


def test_no_finding_lists_a_bare_number_as_evidence():
    """The rule §3 states, over every lens at once: evidence is verbatim library text — a
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
    for finding in report(docs).findings:
        for item in finding.evidence:
            assert not item.replace("%", "").replace(".", "").isdigit(), (
                f"{finding.lens} lists a bare number as evidence: {item!r}"
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
    rep = report(docs)
    assert rep.subjects == 6 and rep.files == 7
    assert rep.claims == 14  # the volume's claim belongs to the subject
    assert rep.findings == ()
    # …and a caller asking about the volume is answered about its page.
    stray = report(
        replace(docs, "memory/topics/flow.md", "# Flow shaping\n\n## What\n\n# Twice\n\n"
                + claim("A", "a000000c"))
    )
    assert page_findings(stray, "memory/topics/flow.md")


def test_the_archive_leaves_the_counts_without_leaving_the_map():
    """An archived document is out of every count (§2) and still resolves a link, so a page
    that points at a subject the Owner retired is not reported as a dead link."""
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
    rep = report(docs)
    assert (rep.subjects, rep.files, rep.claims) == (6, 6, 13)
    assert rep.findings == ()
    assert all("archive/" not in path for f in rep.findings for path in f.paths)


def test_the_score_is_the_share_of_subjects_no_open_finding_names():
    """§3.3. Not a weighted sum: a real 250-page library put that at zero and kept it there
    however many pages were repaired. This moves by one page each time one page is fixed."""
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    rep = report(docs)
    named = {path for finding in rep.findings for path in finding.paths}
    assert named == {"memory/topics/flow.md"}
    assert rep.score == round(100 * (rep.subjects - len(named)) / rep.subjects) == 83


def test_a_principle_finding_names_every_page_it_is_about_and_the_score_counts_them_all():
    docs = [
        d
        for d in healthy()
        if d.path not in {"memory/people/mei.md", "memory/topics/flow.md"}
    ]
    docs = replace(
        docs,
        "projects/aurora/overview.md",
        "# Aurora\n\n## What it is\n\n"
        + claim("A water plant control stack.", "a0000001")
        + "\n\n"
        + claim(
            "Its history is in [the timeline](evolution.md), its parts in "
            "[the pump](features/pump.md) and [the tank choice](decisions/tank.md).",
            "a0000002",
        ),
    ) + [
        doc(
            "memory/topics/flow.md",
            "# Flow shaping\n\n## What\n\n" + claim("An idea about demand.", "a000000c"),
        )
    ]
    rep = report(docs)
    island = next(f for f in rep.findings if f.lens == "nav.island")
    assert len(island.paths) == 4
    assert rep.score == 0  # the island names four, the reachability lenses name the fifth


def test_a_decision_gives_the_score_back():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    rep = report(docs)
    assert rep.score < 100
    declined = {
        finding.key: Decision(reason="the page is a stub on purpose", decided_at="2026-03-01")
        for finding in rep.findings
    }
    answered = report(docs, decisions=declined)
    assert answered.score == 100
    assert all(f.decision is not None for f in answered.findings)
    assert answered.findings[0].decision.reason == "the page is a stub on purpose"
    assert answered.to_dict()["findings"][0]["decision"]["decided_at"] == "2026-03-01"


def test_findings_are_ordered_principle_then_drift_then_shape():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        # one principle (a name shared with Mei) and one shape (a link to nothing)…
        "# Mei Lark\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    docs = replace(
        docs,
        # …and one drift: a decision page that links to nothing.
        "projects/aurora/decisions/tank.md",
        "# Tank sizing\n\n## The choice\n\n"
        + claim("Two small vessels beat one large one.", "a0000008"),
    )
    rep = report(docs)
    order = {"principle": 0, "drift": 1, "shape": 2}
    levels = [order[f.level] for f in rep.findings]
    assert levels == sorted(levels)
    assert {"principle", "drift", "shape"} <= {f.level for f in rep.findings}


def test_to_dict_is_the_wire_shape_the_faces_code_against():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("See [the ghost](../../projects/aurora/features/ghost.md).", "a000000c"),
    )
    payload = report(docs, ref="HEAD", read_at="2026-03-01T00:00:00Z").to_dict()
    assert set(payload) == {
        "ref",
        "read_at",
        "subjects",
        "files",
        "claims",
        "edges",
        "score",
        "findings",
        "families",
    }
    finding = next(f for f in payload["findings"] if f["lens"] == "nav.dead_link")
    assert set(finding) == {
        "key",
        "lens",
        "level",
        "actor",
        "paths",
        "targets",
        "evidence",
        "impact",
        "action",
        "weight",
        "decision",
    }
    assert set(finding["impact"]) == {"key", "fields", "text"}
    assert set(finding["impact"]["text"]) == {"en", "zh"}
    assert finding["impact"]["key"] == "lens.nav.dead_link.impact"
    assert finding["decision"] is None
    assert set(payload["families"][0]) == {"name", "pages", "claims", "share"}


def test_a_contract_that_declares_none_of_the_family_roles_gets_only_the_agnostic_lenses():
    """The role table is the whole of the lens's domain knowledge (§2): a contract using
    none of those names is told nothing about a layout nobody described to it."""
    docs = [
        doc("notes/one.md", "# One\n\n## A\n\n" + claim("Alpha.", "a1111111")),
        doc("notes/two.md", "# Two\n\n## A\n\n" + claim("Beta.", "a2222222")),
    ]
    rep = build_report(docs, ["notes/{slug}.md"])
    assert lenses_of(rep) <= {"nav.dead_end", "nav.arrival_blind"}


# ───────────────────────────────────────────────────────── every lens has both sentences


@pytest.mark.parametrize("lens", LENS_IDS)
def test_every_lens_carries_an_impact_and_an_action_in_both_packs(lens):
    """§1's first ruling, mechanically: a number with no consequence and no action is not a
    finding, so a lens with no pair of sentences cannot ship."""
    english, chinese = default_catalog(), chinese_overlay()
    for key in (f"lens.{lens}.impact", f"lens.{lens}.action"):
        assert key in english and english[key].strip()
        assert key in chinese and chinese[key].strip()
    assert LENS_LEVEL[lens] in {"principle", "drift", "shape"}


#: What a finding has to be ABOUT for its sentence to be worth reading: the page, the project
#: or the family it names, or — for the two library-wide reachability lenses — how many.
IDENTIFYING_FIELDS = {"path", "project", "family", "count"}


@pytest.mark.parametrize("lens", LENS_IDS)
def test_both_sentences_of_every_lens_name_what_the_finding_is_about(lens):
    """A console showed "This project is an island" with no project and no counts, because a
    face had kept its own copy of these sentences and the copy had no placeholders. The rule
    that makes that unwriteable: each pair of sentences must interpolate the thing the finding
    is about, in BOTH packs."""
    english, chinese = default_catalog(), chinese_overlay()
    for pack in (english, chinese):
        declared = template_fields(pack[f"lens.{lens}.impact"]) | template_fields(
            pack[f"lens.{lens}.action"]
        )
        assert declared & IDENTIFYING_FIELDS, (
            f"{lens}: neither sentence names the page, project, family or count it is about"
        )


def a_library_with_many_faults() -> list[CanonicalDocument]:
    """One library carrying a fault of most kinds at once — the fixture the rendering tests
    want, where the per-lens tests deliberately break one thing at a time."""
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
    """§3.2: the key and the fields stay the authority, and the rendered pair rides beside
    them so no face has to keep — and drift from — its own copy of these sentences."""
    payload = report(a_library_with_many_faults()).to_dict()
    assert len(payload["findings"]) >= 6
    catalog = default_catalog()
    for finding in payload["findings"]:
        for half in ("impact", "action"):
            phrase = finding[half]
            assert set(phrase) == {"key", "fields", "text"}
            assert set(phrase["text"]) == {"en", "zh"}
            for language, rendered in phrase["text"].items():
                assert rendered.strip(), (finding["lens"], half, language)
                for name in template_fields(catalog[phrase["key"]]):
                    assert "{" + name + "}" not in rendered, (
                        f"{finding['lens']}.{half} ({language}) left {{{name}}} unfilled"
                    )
                assert any(
                    str(value) in rendered for value in phrase["fields"].values()
                ), f"{finding['lens']}.{half} ({language}) names none of its own fields"
            # The Chinese sentence is a translation, not the English one repeated.
            assert phrase["text"]["zh"] != phrase["text"]["en"]


def test_the_island_sentence_names_the_project_directory_in_both_languages():
    docs = [
        d
        for d in healthy()
        if d.path not in {"memory/people/mei.md", "memory/topics/flow.md"}
    ]
    docs = replace(
        docs,
        "projects/aurora/overview.md",
        "# Aurora\n\n## What it is\n\n"
        + claim("A water plant control stack.", "a0000001")
        + "\n\n"
        + claim(
            "Its history is in [the timeline](evolution.md), its parts in "
            "[the pump](features/pump.md) and [the tank choice](decisions/tank.md).",
            "a0000002",
        ),
    ) + [
        doc(
            "memory/topics/flow.md",
            "# Flow shaping\n\n## What\n\n" + claim("An idea about demand.", "a000000c"),
        )
    ]
    island = next(f for f in report(docs).findings if f.lens == "nav.island")
    for language in ("en", "zh"):
        assert "projects/aurora" in island.impact.text()[language]
        assert "projects/aurora" in island.action.text()[language]
    assert "4" in island.impact.text()["en"] and "4" in island.impact.text()["zh"]


def test_the_rendered_pair_ignores_whatever_overlay_this_process_registered():
    """The English half is the CATALOG's sentence and the Chinese half is the PACK's. A
    deployment that rewords a surface reworded its own surface, in its own language; it does
    not get to decide what the other language in this payload says."""
    from pneuma_knowledge_core.prompts import override_prompt, reset_prompt_overrides

    docs = a_library_with_many_faults()
    before = report(docs).findings[0].impact.text()
    try:
        override_prompt("lens.nav.dead_end.impact", "OVERRIDDEN {count} {share}")
        override_prompt("lens.nav.island.impact", "OVERRIDDEN {project} {count} {claims}")
        after = report(docs).findings[0].impact.text()
    finally:
        reset_prompt_overrides()
    assert after == before
    assert "OVERRIDDEN" not in after["en"] and "OVERRIDDEN" not in after["zh"]


def test_render_impact_and_render_action_still_answer_in_the_active_pack():
    """The CLI reads one language — the one this process is running in — so the two
    renderers keep going through `prompt()` and keep seeing an override."""
    from pneuma_knowledge_core.prompts import (
        override_prompts,
        reset_prompt_overrides,
    )

    finding = next(
        f for f in report(a_library_with_many_faults()).findings if f.lens == "nav.dead_end"
    )
    assert render_impact(finding) == finding.impact.text()["en"]
    try:
        override_prompts(chinese_overlay())
        assert render_impact(finding) == finding.impact.text()["zh"]
        assert render_action(finding) == finding.action.text()["zh"]
    finally:
        reset_prompt_overrides()
