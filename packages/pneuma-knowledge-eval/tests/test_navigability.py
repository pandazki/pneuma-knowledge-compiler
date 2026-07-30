"""Group D: hit-seeded reachability, growth exponent, structure health, glance."""

from __future__ import annotations

from _fixtures import claim, document, source, trajectory
from pneuma_knowledge_eval.metrics.navigability import (
    glance,
    growth,
    navigability_metrics,
    reachability,
    structure_health,
)


def test_reachability_is_seeded_from_every_document_not_from_a_designated_root():
    """The口径 this metric was re-based onto: nobody enters at a root.

    profile → ann → pilot is a 3-document chain plus one unlinked file. Seeded from profile
    you reach all three; seeded from pilot you reach nothing; seeded from the unlinked file you
    reach nothing. The average is therefore well below 1 while the chain itself works — which
    is the honest reading, and the one a hub-seeded walk from profile (1.0 for 3 of 4 files)
    hid entirely.
    """
    files = {
        "memory/profile.md": document(
            "memory/profile.md", [claim("Owner.", "aaaa0001")], links=["people/ann.md"]
        ),
        "memory/people/ann.md": document(
            "memory/people/ann.md", [claim("Ann leads delivery.", "aaaa0002")],
            links=["../topics/pilot.md"],
        ),
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md", [claim("The pilot is fixed price.", "aaaa0003")]
        ),
        "materials/raw.md": document("materials/raw.md", [claim("Unlinked note.", "aaaa0004")]),
    }
    report = reachability(trajectory([files]), max_hops=2)
    head = report["head"]

    assert report["basis"] == "retrieval_hit_seeded"
    assert head["documents"] == 4
    assert head["edges"] == 2
    # seeds reach: profile 3/4, ann 2/4, pilot 1/4, raw 1/4 → mean 7/16
    assert head["mean_reach_rate"] == 0.4375
    assert head["max_reach_rate"] == 0.75
    assert head["dead_end_documents"] == 2  # pilot and raw lead nowhere
    # profile and raw are linked to by nothing
    assert head["arrival_blind_documents"] == 2
    assert head["isolated_documents"] == 1  # raw is both dead end and arrival-blind
    # profile's two rows (its claim + its link row) and raw's one
    assert head["orphan_claims"] == 3
    assert report["invariants"]["no_dead_end_at_head"] is False
    assert report["invariants"]["every_document_arrivable_at_head"] is False


def test_hop_budget_is_respected():
    files = {
        "memory/profile.md": document(
            "memory/profile.md", [claim("Owner.", "bbbb0001")], links=["people/ann.md"]
        ),
        "memory/people/ann.md": document(
            "memory/people/ann.md", [claim("Ann.", "bbbb0002")], links=["../topics/pilot.md"]
        ),
        "memory/topics/pilot.md": document("memory/topics/pilot.md", [claim("Pilot.", "bbbb0003")]),
    }
    loaded = trajectory([files])
    # From profile: 2 docs at one hop, 3 at two. The seed distribution rises with the budget.
    assert reachability(loaded, max_hops=1)["head"]["max_reach_rate"] == round(2 / 3, 6)
    assert reachability(loaded, max_hops=2)["head"]["max_reach_rate"] == 1.0


def test_a_link_free_snapshot_leaves_every_hit_stranded_on_its_own_document():
    """The quiet failure this metric exists for: nothing is broken, and nothing is navigable."""
    files = {
        "memory/profile.md": document("memory/profile.md", [claim("Owner.", "cccc0001")]),
        "memory/topics/pilot.md": document("memory/topics/pilot.md", [claim("Pilot.", "cccc0002")]),
    }
    report = reachability(trajectory([files]))
    assert report["head"]["edges"] == 0
    assert report["head"]["mean_reach_rate"] == 0.5  # 1/N: only what you landed on
    assert report["head"]["dead_end_documents"] == 2
    assert report["head"]["orphan_claims"] == 2
    assert report["invariants"]["graph_has_edges_at_head"] is False


def test_growth_exponent_detects_sublinear_and_superlinear_trajectories():
    sources = {
        "s1": source("s1", ["x" * 1000]),
        "s2": source("s2", ["y" * 3000]),
    }
    small_growth = [
        {"memory/topics/a.md": document("memory/topics/a.md", [claim("A" * 100, "dddd0001")])},
        {
            "memory/topics/a.md": document(
                "memory/topics/a.md",
                [claim("A" * 100, "dddd0001"), claim("B" * 20, "dddd0002")],
            )
        },
    ]
    sublinear = growth(trajectory(small_growth, sources=sources, consumed=[["s1"], ["s1", "s2"]]))
    assert sublinear["status"] == "ok"
    assert sublinear["sublinear"] is True

    big_growth = [
        {"memory/topics/a.md": document("memory/topics/a.md", [claim("A" * 100, "eeee0001")])},
        {
            "memory/topics/a.md": document(
                "memory/topics/a.md",
                [claim("A" * 100, "eeee0001"), claim("B" * 4000, "eeee0002")],
            )
        },
    ]
    superlinear = growth(trajectory(big_growth, sources=sources, consumed=[["s1"], ["s1", "s2"]]))
    assert superlinear["sublinear"] is False


def test_growth_is_unavailable_without_l0():
    files = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "ffff0001")])}
    assert growth(trajectory([files]))["status"] == "unavailable"


def test_structure_health_measures_aggregation_dated_slugs_and_family_use():
    first = {
        "memory/topics/pilot.md": document("memory/topics/pilot.md", [claim("A.", "1a1a0001")]),
        "memory/topics/pilot-2026-03-02.md": document(
            "memory/topics/pilot-2026-03-02.md", [claim("B.", "1a1a0002")]
        ),
    }
    second = {
        # the undated document grows (aggregation); the dated one never does
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md", [claim("A.", "1a1a0001"), claim("C.", "1a1a0003")]
        ),
        "memory/topics/pilot-2026-03-02.md": document(
            "memory/topics/pilot-2026-03-02.md", [claim("B.", "1a1a0002")]
        ),
    }
    report = structure_health(trajectory([first, second]))

    assert report["documents_at_head"] == 2
    assert report["documents_growing_across_rounds"] == 1
    assert report["aggregation_rate"] == 0.5
    assert report["dated_slug_documents"] == 1
    assert report["dated_slug_rate"] == 0.5
    assert report["families_in_use"] == 1
    assert report["family_utilization"] < 1.0
    assert report["claims_in_unowned_paths"] == 0


def test_claims_outside_every_family_are_counted():
    files = {"stray/note.md": document("stray/note.md", [claim("A.", "2b2b0001")])}
    report = structure_health(trajectory([files]))
    assert report["claims_in_unowned_paths"] == 1
    assert report["families_in_use"] == 0


def test_glance_reports_the_layout_the_answering_side_would_receive():
    files = {
        "memory/profile.md": document("memory/profile.md", [claim("Owner.", "4d4d0001")]),
        "memory/topics/pilot.md": document("memory/topics/pilot.md", [claim("Pilot.", "4d4d0002")]),
    }
    report = glance(trajectory([files]))
    assert report["present"] is True
    assert report["documents_at_head"] == 2
    assert report["documents_listed"] == 2
    assert report["documents_omitted_by_truncation"] == 0
    assert report["families_declared"] == report["families_rendered"] > 0
    assert report["families_missing_from_glance"] == []
    assert report["within_budget"] is True


def test_glance_is_not_present_for_an_empty_head():
    """A base with nothing in it has no bird's-eye view to offer, and must say so rather than
    report a rendered header as a working layout."""
    report = glance(trajectory([{}]))
    assert report["present"] is False
    assert report["documents_listed"] == 0


def test_group_entry_point_returns_all_four_sections():
    files = {"memory/profile.md": document("memory/profile.md", [claim("A.", "3c3c0001")])}
    report = navigability_metrics(trajectory([files]))
    assert report["group"] == "D_navigability"
    assert set(report) >= {"reachability", "growth", "structure", "glance"}
