"""Inter-document markdown links: the one grammar, and the one pair of coordinates.

A canonical link is an ordinary relative markdown href. That makes it readable in any
markdown viewer and MOVABLE — but only if "where does this href point" and "how does that
target render from here" are stated once. They are stated here.

The pair lives in its own module rather than in the gate because three write paths need it
and they cannot all import the gate: the gate validates link targets, `compile.rollover`
re-renders hrefs when a claim changes depth, and `compile.documents` renders the overview's
connection links. `compile.gate` re-exports all three names, so every existing importer
(rollover, the eval metrics) keeps reading them from where they have always been.
"""

from __future__ import annotations

import re

# Inter-document markdown links — the form the projection layer reads to build graph edges
# (service dataset._MD_LINK_RE). Kept identical here so the gate validates exactly what the
# graph will later try to resolve.
_MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _resolve_relative(from_path: str, href: str) -> str:
    """Resolve `href` against the linking document's directory (mirrors dataset._resolve_link)."""
    stack = from_path.split("/")[:-1]
    for part in href.split("#")[0].split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if stack:
                stack.pop()
        else:
            stack.append(part)
    return "/".join(stack)


def _render_relative(from_path: str, target: str) -> str:
    """The href that renders `target` from a document at `from_path` — the inverse above.

    Its law is the round trip: `_resolve_relative(from_path, _render_relative(from_path, t))
    == t` for every repo-relative `t`. That is what makes a relative link MOVABLE: the href
    is only a rendering of a target from one position, so a document that changes position
    keeps its links by re-rendering them (compile.rollover), never by leaving the bytes alone.

    It lives next to the resolver because an inverse stated somewhere else is a second
    spelling of the same fact, and the two would drift.
    """
    from_dir = from_path.split("/")[:-1]
    parts = target.split("/")
    common = 0
    while (
        common < len(from_dir)
        and common < len(parts) - 1
        and from_dir[common] == parts[common]
    ):
        common += 1
    return "/".join([".."] * (len(from_dir) - common) + parts[common:])


__all__ = ["_MD_LINK_RE", "_render_relative", "_resolve_relative"]
