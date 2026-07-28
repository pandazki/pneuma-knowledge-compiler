"""Canonical document text (de)serialization.

A canonical document on disk is markdown with a YAML-style frontmatter fence. v1
frontmatter is a flat map of scalar strings (pneuma_id/type/slug + optional extras), so a
minimal deterministic serializer round-trips it without pulling a YAML dependency into
core (kept at pydantic + langchain-core). Keys are emitted sorted for byte-stability.
"""

from __future__ import annotations

_FENCE = "---"


def render_document(frontmatter: dict, body: str) -> str:
    """Serialize (frontmatter, body) to a frontmatter-fenced markdown file."""
    lines = [_FENCE]
    for key in sorted(frontmatter):
        lines.append(f"{key}: {frontmatter[key]}")
    lines.append(_FENCE)
    text = "\n".join(lines) + "\n"
    if body:
        text += "\n" + body.rstrip("\n") + "\n"
    return text


def parse_document(text: str) -> tuple[dict, str]:
    """Parse a frontmatter-fenced markdown file into (frontmatter, body).

    A file without a leading fence parses as empty frontmatter + whole text as body.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FENCE:
        return {}, text.strip("\n")
    frontmatter: dict = {}
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            end = i
            break
        raw = lines[i]
        if ":" in raw:
            key, _, value = raw.partition(":")
            frontmatter[key.strip()] = value.strip()
    if end < 0:
        return {}, text.strip("\n")
    body = "\n".join(lines[end + 1 :]).strip("\n")
    return frontmatter, body
