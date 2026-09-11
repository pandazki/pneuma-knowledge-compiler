"""The pure window arithmetic behind episodes over a long source, and the window gate."""

import pytest

from pneuma_knowledge_core.ingest.episodes import episode_windows, parse_episode_proposal, window_chain

EPISODE = {"start": 2, "end": 3, "title": "Synthetic topic", "description": "A synthetic description."}


def test_windows_tile_whole_blocks_under_the_bound():
    costs = [(i, 10) for i in range(10)]
    assert episode_windows(costs, 30) == [(0, 2), (3, 5), (6, 8), (9, 9)]
    assert episode_windows(costs, 1000) == [(0, 9)]
    assert episode_windows(costs, 0) == [(0, 9)]
    assert episode_windows([], 30) == []


def test_a_block_over_the_bound_stands_alone_and_sparse_indices_keep_their_numbers():
    assert episode_windows([(0, 5), (4, 50), (9, 5), (12, 5)], 20) == [(0, 0), (4, 4), (9, 12)]


def test_what_a_window_carries_at_its_opening_counts_against_the_bound():
    costs = [(i, 10) for i in range(6)]
    assert episode_windows(costs, 30, opening=lambda i: 0) == [(0, 2), (3, 5)]
    assert episode_windows(costs, 30, opening=lambda i: 15 if i else 0) == [(0, 2), (3, 3), (4, 4), (5, 5)]


def test_the_chain_is_complete_only_when_the_windows_tile_the_source():
    blocks = list(range(10))
    assert window_chain([(0, 4), (5, 9)], blocks) == [(0, 4), (5, 9)]
    assert window_chain([(5, 9), (0, 4)], blocks) == [(0, 4), (5, 9)]
    assert window_chain([(0, 4)], blocks) is None
    assert window_chain([(0, 3), (5, 9)], blocks) is None
    assert window_chain([(0, 4), (5, 11)], blocks) is None
    # A window from another windowing that is not on the chain is not part of it.
    assert window_chain([(0, 4), (5, 9), (7, 9)], blocks) == [(0, 4), (5, 9)]
    # Sparse indices: the next window opens at the next REAL block.
    assert window_chain([(0, 3), (7, 12)], [0, 3, 7, 12]) == [(0, 3), (7, 12)]
    assert window_chain([], blocks) is None


@pytest.mark.parametrize("item", [{**EPISODE, "start": 1}, {**EPISODE, "end": 5}])
def test_the_window_gate_names_a_boundary_that_leaves_the_window(item):
    with pytest.raises(ValueError, match=r"episodes\.window: episode 0 .*¶2-4"):
        parse_episode_proposal([item], [2, 3, 4], window=(2, 4))


def test_the_window_gate_keeps_every_other_rule():
    assert [e.start for e in parse_episode_proposal([EPISODE], [2, 3, 4], window=(2, 4))] == [2]
    assert parse_episode_proposal([], [2, 3, 4], window=(2, 4)) == []
    with pytest.raises(ValueError, match=r"episodes\.endpoints"):
        parse_episode_proposal([{**EPISODE, "start": True}], [2, 3, 4], window=(2, 4))
    with pytest.raises(ValueError, match=r"episodes\.endpoints"):
        parse_episode_proposal([{**EPISODE, "start": 1}], [2, 3, 4])
