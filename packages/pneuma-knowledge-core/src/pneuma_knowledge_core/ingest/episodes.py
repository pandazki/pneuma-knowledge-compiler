"""The agent's episode contract: explicit omissions, otherwise the semantic chunker gates.

This is a judgement about retrieval, never a write of source or canonical knowledge.
Titles and descriptions remain derived search aids grounded by their real L0 interval.
"""

from __future__ import annotations

from ..prompts import prompt
from .semantic import (
    MAX_EPISODE_DESCRIPTION_CHARS,
    MAX_EPISODE_TITLE_CHARS,
    MAX_OVERLAP_BLOCKS,
    SemanticEpisode,
    interval_rejections,
)


def episode_rules() -> str:
    """The volatile-free system face, shared by attended and unattended opens (I5)."""
    return prompt(
        "steward.episodes.rules", overlap=MAX_OVERLAP_BLOCKS,
        title_limit=MAX_EPISODE_TITLE_CHARS,
        description_limit=MAX_EPISODE_DESCRIPTION_CHARS,
    )


def parse_episode_proposal(
    value, block_indices: list[int], *, window: tuple[int, int] | None = None,
) -> list[SemanticEpisode]:
    """Normalize a whole proposal or name every violation; never repair its boundaries.

    `block_indices` are the blocks this judgement is over: the whole source, or one window
    of it. With `window` stated, an endpoint that is a block number outside that window is
    named as leaving the window rather than as unreal, so the round reads which rule it broke.
    """
    if not isinstance(value, list):
        raise ValueError(prompt("steward.episodes.shape"))
    order = sorted(block_indices)
    positions = {index: pos for pos, index in enumerate(order)}
    findings: list[str] = []
    episodes: list[SemanticEpisode] = []
    spans: list[tuple[int, int]] = []
    for number, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"start", "end", "title", "description"}:
            findings.append(prompt("steward.episodes.shape") + f" (episode {number})")
            continue
        start, end = item["start"], item["end"]
        valid = all(type(i) is int and i in positions for i in (start, end))
        if not valid:
            outside = window is not None and any(
                type(i) is int and not window[0] <= i <= window[1] for i in (start, end)
            )
            findings.append(
                prompt("steward.episodes.window", episode=number, start=window[0], end=window[1])
                if outside else prompt("steward.episodes.endpoints", episode=number)
            )
        else:
            spans.append((positions[start], positions[end]))
        fields = {}
        for key, limit in (("title", MAX_EPISODE_TITLE_CHARS), ("description", MAX_EPISODE_DESCRIPTION_CHARS)):
            raw = item[key]
            text = " ".join(raw.split()) if isinstance(raw, str) else ""
            if not text or len(text) > limit:
                findings.append(prompt("steward.episodes.text", episode=number, field=key, limit=limit))
            fields[key] = text
        if valid:
            episodes.append(SemanticEpisode(start=start, end=end, **fields))
    violations = interval_rejections(spans, 0, len(order) - 1, require_cover=False)
    if len(value) > len(order) and not any(kind == "count" for kind, _ in violations):
        violations.append(("count", f"{len(value)} segments over {len(order)} blocks"))
    findings.extend(f"episodes.{kind}: {detail}" for kind, detail in violations)
    if findings:
        raise ValueError("\n".join(findings))
    return episodes


def uncovered_blocks(episodes: list[SemanticEpisode], block_indices: list[int]) -> list[int]:
    """The explicit L0/L1-only residue, in source order."""
    return [i for i in sorted(block_indices) if not any(e.start <= i <= e.end for e in episodes)]


# ─────────────────────────────────────────────── windows: one long source, several rounds


def episode_windows(
    costs: list[tuple[int, int]], bound: int, *, opening=None,  # noqa: ANN001
) -> list[tuple[int, int]]:
    """`(block index, cost)` pairs → consecutive windows of whole blocks, as inclusive spans.

    Each window costs at most `bound`; a block is never cut, so one block whose own cost is
    over the bound is a window by itself. `opening(index)` is what a window opening at that
    block carries before its first block — the enclosing sections a window's structure map
    repeats — and counts against the same bound. The windows tile the blocks in index order
    with no gap and no overlap, and they are a pure function of their inputs, so the same
    source under the same bound always yields the same windows. `bound <= 0` is one window.
    """
    ordered = sorted(costs)
    if not ordered:
        return []
    if bound <= 0:
        return [(ordered[0][0], ordered[-1][0])]
    carry = opening or (lambda index: 0)
    windows: list[tuple[int, int]] = []
    start = previous = ordered[0][0]
    spent = carry(start)
    for index, cost in ordered:
        if index != start and spent + cost > bound:
            windows.append((start, previous))
            start, spent = index, carry(index)
        spent += cost
        previous = index
    windows.append((start, previous))
    return windows


def window_chain(
    recorded: list[tuple[int, int]], block_indices: list[int]
) -> list[tuple[int, int]] | None:
    """The recorded windows that tile the whole source, in block order — or None.

    Walks from the source's first block: each next window must open at exactly the block
    after the previous one closed, and the last must close at the source's last block. A
    source with any stretch no recorded window covers has no complete judgement, and None is
    the only honest answer; a window recorded under some other windowing that does not fall
    on the chain is simply not part of it. At most one window opens at a block, so the chain
    is unique when it exists.
    """
    order = sorted(block_indices)
    if not order:
        return None
    by_start = {start: (start, end) for start, end in recorded}
    chain: list[tuple[int, int]] = []
    expected: int | None = order[0]
    while expected is not None:
        window = by_start.get(expected)
        if window is None or window[1] < window[0]:
            return None
        chain.append(window)
        if window[1] >= order[-1]:
            return chain if window[1] == order[-1] else None
        expected = next((i for i in order if i > window[1]), None)
    return None
