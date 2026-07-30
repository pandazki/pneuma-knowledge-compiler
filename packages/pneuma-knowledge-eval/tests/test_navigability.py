"""Group D: hub reachability, growth exponent, structure health."""

from __future__ import annotations

from _fixtures import claim, document, source, trajectory
from pneuma_knowledge_eval.metrics.navigability import (
    growth,
    hub_paths,
    navigability_metrics,
    reachability,
    structure_health,
)


def test_hub_family_is_the_fixed_path_template():
    files = {"memory/profile.md": document("memory/profile.md", [claim("Owner.", "aaaa0001")])}
    assert hub_paths(trajectory([files])) == ("memory/profile.md",)


def test_reachability_follows_links_from_the_hub_and_counts_orphan_claims():
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

    assert head["documents"] == 4
    assert head["edges"] == 2
    assert head["reachable_documents"] == 3  # hub + two hops
    assert head["isolated_documents"] == 1
    assert head["orphan_claims"] == 1  # only the unlinked document's claim
    assert report["invariants"]["every_document_reachable_at_head"] is False


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
    assert reachability(loaded, max_hops=1)["head"]["reachable_documents"] == 2
    assert reachability(loaded, max_hops=2)["head"]["reachable_documents"] == 3


def test_a_link_free_snapshot_reports_zero_edges_and_every_claim_orphaned():
    """The quiet failure this metric exists for: nothing is broken, and nothing is navigable."""
    files = {
        "memory/profile.md": document("memory/profile.md", [claim("Owner.", "cccc0001")]),
        "memory/topics/pilot.md": document("memory/topics/pilot.md", [claim("Pilot.", "cccc0002")]),
    }
    report = reachability(trajectory([files]))
    assert report["head"]["edges"] == 0
    assert report["head"]["reachable_documents"] == 1
    assert report["head"]["orphan_claims"] == 1
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


def test_group_entry_point_returns_all_three_sections():
    files = {"memory/profile.md": document("memory/profile.md", [claim("A.", "3c3c0001")])}
    report = navigability_metrics(trajectory([files]))
    assert report["group"] == "D_navigability"
    assert set(report) >= {"reachability", "growth", "structure"}
