"""Group E: misfit pressure, response verdicts, move fidelity, the monotone floor.

The load-bearing test here is `test_no_change_under_low_pressure_is_aligned_not_penalized`:
restraint is a correct output, and a metric that scored action higher would train the system
toward churn.
"""

from __future__ import annotations

from _fixtures import claim, document, trajectory
from pneuma_knowledge_eval.metrics.evolution import (
    catchall_pressure,
    cross_family_duplication,
    evolution_metrics,
    evolution_response,
    move_fidelity,
    schema_stability,
)


def test_pressure_counts_only_new_claims_and_only_catch_all_families():
    """Round one: one owned claim, one catch-all claim. Round two: two more catch-all claims,
    and the two carried-over claims must not be counted again."""
    files = [
        {
            "memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "aaaa0001")]),
            "memory/topics/misc.md": document("memory/topics/misc.md", [claim("B.", "aaaa0002")]),
        },
        {
            "memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "aaaa0001")]),
            "memory/topics/misc.md": document(
                "memory/topics/misc.md",
                [claim("B.", "aaaa0002"), claim("C.", "aaaa0003"), claim("D.", "aaaa0004")],
            ),
        },
    ]
    report = catchall_pressure(trajectory(files))

    assert report["series"][0]["new_claims"] == 2
    assert report["series"][0]["catchall_share"] == 0.5
    assert report["series"][1]["new_claims"] == 2
    assert report["series"][1]["catchall_share"] == 1.0
    assert report["series"][1]["under_pressure"] is True
    assert report["longest_pressure_run"] == 2


def test_no_change_under_low_pressure_is_aligned_not_penalized():
    """`no_change` is very often the correct evolve output. The verdict must say so."""
    files = [
        {"memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "bbbb0001")])},
        {
            "memory/people/ann.md": document(
                "memory/people/ann.md", [claim("A.", "bbbb0001"), claim("B.", "bbbb0002")]
            )
        },
    ]
    report = evolution_response(trajectory(files))
    assert report["status"] == "no_evolution_events"
    assert report["verdict"] == "aligned_restraint"
    assert report["pressure"]["sustained"] is False
    # the pressure series survives even though no response can be scored
    assert len(report["pressure"]["series"]) == 2


def test_sustained_pressure_with_no_response_is_a_miss():
    catchall = "memory/topics/misc.md"
    files = []
    blocks: list[str] = []
    for index in range(4):
        blocks = blocks + [claim(f"Claim {index}.", f"cccc000{index}")]
        files.append({catchall: document(catchall, blocks)})
    report = evolution_response(trajectory(files))
    assert report["pressure"]["sustained"] is True
    assert report["verdict"] == "missed_pressure"


def test_a_schema_change_without_pressure_reads_as_churn():
    files = [
        {"memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "dddd0001")])},
        {
            "memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "dddd0001")]),
            "memory/people/bob.md": document("memory/people/bob.md", [claim("B.", "dddd0002")]),
        },
    ]
    report = evolution_response(
        trajectory(files, subjects=["compile " + "1" * 32, "schema evolve: reorganized"])
    )
    assert report["status"] == "ok"
    assert report["verdict"] == "churn"
    assert report["evolve_commits"][0]["checkpoint"] == "r02"


def test_move_fidelity_separates_a_verbatim_move_from_a_rewrite_in_flight():
    text = "Deletion evidence must be verifiable within seven days."
    before = {
        "memory/topics/misc.md": document(
            "memory/topics/misc.md",
            [claim(text, "eeee0001"), claim("Second claim.", "eeee0002")],
        )
    }
    after = {
        "memory/topics/misc.md": document("memory/topics/misc.md", [claim("Second claim.", "eeee0002")]),
        "work/operations/pilot.md": document(
            "work/operations/pilot.md", [claim(text, "eeee0001")]
        ),
    }
    report = move_fidelity(trajectory([before, after]))
    assert report["moves_observed"] == 1
    assert report["moves_verbatim"] == 1
    assert report["verbatim_rate"] == 1.0

    rewritten_after = {
        "memory/topics/misc.md": document("memory/topics/misc.md", [claim("Second claim.", "eeee0002")]),
        "work/operations/pilot.md": document(
            "work/operations/pilot.md", [claim("Deletion evidence, rephrased.", "eeee0001")]
        ),
    }
    rewritten = move_fidelity(trajectory([before, rewritten_after]))
    assert rewritten["moves_observed"] == 1
    assert rewritten["moves_verbatim"] == 0
    assert rewritten["rewritten_while_moving"][0]["anchor"] == "eeee0001"


def test_schema_floor_violation_is_reported_when_a_family_disappears():
    first = {
        "memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "ffff0001")]),
        "memory/topics/misc.md": document("memory/topics/misc.md", [claim("B.", "ffff0002")]),
    }
    second = {"memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "ffff0001")])}
    report = schema_stability(trajectory([first, second]))
    assert report["invariants"]["family_floor_is_monotone"] is False
    assert report["invariants"]["anchor_floor_is_monotone"] is False
    assert report["family_churn_events"] == 1


def test_a_growing_schema_keeps_both_floors_monotone():
    first = {"memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "1a1a0001")])}
    second = {
        "memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "1a1a0001")]),
        "work/products/p.md": document("work/products/p.md", [claim("B.", "1a1a0002")]),
    }
    report = schema_stability(trajectory([first, second]))
    assert report["invariants"] == {
        "family_floor_is_monotone": True,
        "anchor_floor_is_monotone": True,
    }
    assert report["series"][1]["families_added"] == 1


def test_cross_family_duplication_flags_a_subject_owned_by_two_families():
    text = "Acceptance runs twenty reviewed questions at the end of week two."
    files = {
        "work/products/p.md": document("work/products/p.md", [claim(text, "2b2b0001")]),
        "work/operations/o.md": document("work/operations/o.md", [claim(text, "2b2b0002")]),
    }
    report = cross_family_duplication(trajectory([files]))
    assert report["head"]["cross_family_clusters"] == 1
    assert report["head_samples"][0]["families"] == [
        "work/operations/{slug}.md",
        "work/products/{slug}.md",
    ]


def test_group_entry_point_returns_all_four_sections():
    files = {"memory/people/ann.md": document("memory/people/ann.md", [claim("A.", "3c3c0001")])}
    report = evolution_metrics(trajectory([files]))
    assert report["group"] == "E_evolution"
    assert set(report) >= {
        "response",
        "cross_family_duplication",
        "move_fidelity",
        "schema_stability",
    }
