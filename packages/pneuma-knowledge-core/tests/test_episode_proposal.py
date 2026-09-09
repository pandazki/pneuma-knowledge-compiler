"""Agent omissions opt out of coverage alone, never the other semantic interval gates."""

import pytest

from pneuma_knowledge_core.ingest.episodes import parse_episode_proposal, uncovered_blocks
from pneuma_knowledge_core.ingest.semantic import decode_manifest_episodes, interval_rejections, overlap_rejection


def episode(start, end, **fields):
    return {"start": start, "end": end, "title": "Synthetic subject", "description": "A synthetic topic unit.", **fields}


def test_sparse_real_indices_and_three_shared_blocks_are_accepted():
    indices = [10, 20, 30, 40, 50, 60, 70]
    selected = parse_episode_proposal([episode(20, 50), episode(30, 60)], indices)
    assert uncovered_blocks(selected, indices) == [10, 70]


def test_all_violations_are_reported_together():
    with pytest.raises(ValueError) as error:
        parse_episode_proposal([episode(0, 5, title=""), episode(1, 5, description=""), episode(0, 5)], list(range(6)))
    for kind in ("title", "description", "starts", "overlap"):
        assert f"episodes.{kind}" in str(error.value)


def test_api_gate_keeps_coverage_and_agent_gate_removes_only_coverage():
    assert overlap_rejection([(1, 2), (4, 4)], 0, 5)
    assert interval_rejections([(1, 2), (4, 4)], 0, 5, require_cover=False) == []
    assert overlap_rejection([], 0, 5) == "no segments returned"
    assert interval_rejections([], 0, 5, require_cover=False) == []


def test_only_an_explicit_agent_manifest_can_record_no_episodes():
    manifest = {"version": 3, "overlap": "smart", "episodes": []}
    assert decode_manifest_episodes(manifest, block_indices=[0]) is None
    manifest.update(producer="agent", coverage="partial")
    assert decode_manifest_episodes(manifest, block_indices=[0]) == ([], "smart")
