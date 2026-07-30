"""Group A on hand-built snapshots: citation replay, anchor continuity, link integrity."""

from __future__ import annotations

from _fixtures import claim, document, source, trajectory
from pneuma_knowledge_eval.metrics.grounded import (
    anchor_continuity,
    citation_integrity,
    grounded_metrics,
    link_integrity,
)

SOURCES = {"s1": source("s1", ["block zero", "block one", "block two"])}


def test_citation_replay_separates_the_three_failure_modes():
    files = {
        "memory/topics/a.md": document(
            "memory/topics/a.md",
            [
                claim("Inside bounds.", "aaaa0001", cite="s1 ¶0-1"),
                claim("Past the end.", "aaaa0002", cite="s1 ¶9"),
                claim("Unknown source.", "aaaa0003", cite="s9 ¶0"),
                claim("No provenance at all.", "aaaa0004"),
            ],
        )
    }
    report = citation_integrity(trajectory([files], sources=SOURCES, consumed=[["s1"]]))
    head = report["head"]

    assert head["claims_total"] == 4
    assert head["claims_with_citations"] == 3
    assert head["citations_total"] == 3
    assert head["citations_resolvable"] == 1
    assert head["out_of_range"] == 1
    assert head["unknown_source"] == 1
    assert report["invariants"]["head_claim_coverage_is_total"] is False


def test_malformed_marker_is_counted_as_residue_not_as_a_citation():
    """Text that looks like a citation but does not parse resolves to nothing; that is worse
    than no citation, so it must not disappear from the report."""
    files = {
        "memory/topics/a.md": document(
            "memory/topics/a.md", [claim("Broken. [cite: s1 page 3]", "bbbb0001")]
        )
    }
    report = citation_integrity(trajectory([files], sources=SOURCES, consumed=[["s1"]]))
    assert report["head"]["unparsable_marker_residue"] == 1
    assert report["head"]["citations_total"] == 0
    assert report["invariants"]["no_unparsable_residue_at_head"] is False


def test_citation_resolvability_is_unavailable_without_l0():
    """A null in a series row is not a declaration. Replay gets its own `unavailable` node with
    a reason and a cause, which is what puts it in the scorecard's list of what did not run."""
    files = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "cccc0001", cite="s1 ¶0")])}
    report = citation_integrity(trajectory([files]))
    assert report["l0_available"] is False
    assert report["head"]["citations_resolvable"] is None
    assert report["invariants"]["head_all_citations_resolvable"] is None
    assert report["locator_replay"]["status"] == "unavailable"
    assert report["locator_replay"]["cause"] == "l0_absent"
    # the half that needs canonical alone is still measured, and the reason says which is which
    assert report["head"]["claims_with_citations"] == 1
    assert "claim coverage" in report["locator_replay"]["reason"]


def test_citation_replay_reports_its_numbers_when_l0_is_present():
    files = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "cccc0002", cite="s1 ¶0")])}
    report = citation_integrity(trajectory([files], sources=SOURCES, consumed=[["s1"]]))
    replay = report["locator_replay"]
    assert replay["status"] == "ok"
    assert replay["citations_total"] == 1
    assert replay["citations_resolvable"] == 1
    assert replay["resolvable_rate"] == 1.0
    assert replay["unknown_source"] == 0 and replay["out_of_range"] == 0


def test_a_moved_claim_is_not_an_anchor_loss_but_a_deleted_one_is():
    first = {
        "memory/topics/a.md": document(
            "memory/topics/a.md",
            [claim("Stays.", "dddd0001"), claim("Moves away.", "dddd0002")],
        )
    }
    moved = {
        "memory/topics/a.md": document("memory/topics/a.md", [claim("Stays.", "dddd0001")]),
        "memory/topics/b.md": document("memory/topics/b.md", [claim("Moves away.", "dddd0002")]),
    }
    deleted = {
        "memory/topics/a.md": document("memory/topics/a.md", [claim("Stays.", "dddd0001")]),
        "memory/topics/b.md": document("memory/topics/b.md", [claim("Something else.", "dddd0003")]),
    }

    report = anchor_continuity(trajectory([first, moved, deleted]))
    first_transition, second_transition = report["series"]

    assert first_transition["per_document_vanished"] == 1
    assert first_transition["repo_wide_vanished"] == 0
    assert first_transition["moved_not_lost"] == 1
    assert second_transition["repo_wide_vanished"] == 1
    assert report["invariants"]["no_repo_wide_anchor_loss"] is False


def test_dropped_document_is_reported_explicitly():
    first = {
        "memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "eeee0001")]),
        "memory/topics/b.md": document("memory/topics/b.md", [claim("B.", "eeee0002")]),
    }
    second = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "eeee0001")])}
    report = anchor_continuity(trajectory([first, second]))
    assert report["documents_dropped"] == [
        {"from": "r01", "to": "r02", "paths": ["memory/topics/b.md"]}
    ]
    assert report["invariants"]["no_document_dropped"] is False


def test_links_are_classified_with_the_gate_resolution():
    files = {
        "memory/topics/a.md": document(
            "memory/topics/a.md",
            [claim("A.", "ffff0001")],
            links=["b.md", "missing.md", "a.md"],
        ),
        "memory/topics/b.md": document("memory/topics/b.md", [claim("B.", "ffff0002")]),
    }
    report = link_integrity(trajectory([files]))
    head = report["head"]
    assert head["links_total"] == 3
    assert head["resolved"] == 1
    assert head["dead"] == 1
    assert head["self"] == 1
    assert report["invariants"]["no_dead_links_at_head"] is False
    assert report["invariants"]["head_has_any_link"] is True


def test_a_link_free_snapshot_reports_zero_links_rather_than_a_clean_bill():
    files = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "1a1a0001")])}
    report = link_integrity(trajectory([files]))
    assert report["head"]["links_total"] == 0
    assert report["head"]["dead"] == 0
    assert report["invariants"]["head_has_any_link"] is False


def test_group_entry_point_returns_all_three_sections():
    files = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "2b2b0001", cite="s1 ¶0")])}
    report = grounded_metrics(trajectory([files], sources=SOURCES, consumed=[["s1"]]))
    assert report["group"] == "A_grounded"
    assert set(report) >= {"citations", "anchors", "links"}
