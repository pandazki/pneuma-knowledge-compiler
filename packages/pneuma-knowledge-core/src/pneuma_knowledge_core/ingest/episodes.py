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


def parse_episode_proposal(value, block_indices: list[int]) -> list[SemanticEpisode]:
    """Normalize a whole proposal or name every violation; never repair its boundaries."""
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
            findings.append(prompt("steward.episodes.endpoints", episode=number))
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
