"""Pagination for the deep lane's component tools: a cap that is never a dead end.

The fast lane can afford a hard cap because the framework ranks the candidates against the
question first and states what it did not show. The deep lane cannot: it is agentic, its
tool calls carry no question the tool could rank against, and a model that receives the
first forty lines of a record with no way to ask for the rest will answer from the forty.

So every deep component tool paginates, and every response ends with ONE navigation line
that carries three things: how much exists, what part of it this is, and the EXACT call
that fetches more (plus, where the material has structure, a call that jumps straight at
one part of it). The model never has to guess an argument name.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

#: One page of a person's record. Large enough that most pages arrive whole, small enough
#: that a long one leaves room for the rest of the agentic turn.
PROFILE_PAGE_LIMIT = 40
#: One page of a timeline digest, counted in buckets (days or weeks).
TIMELINE_PAGE_LIMIT = 20
#: One page of a verbatim day, counted in L0 blocks.
VERBATIM_PAGE_LIMIT = 60


def call_text(tool: str, **args: object) -> str:
    """`person_profile(alias="Caroline", offset=40)` — a call the model can copy verbatim.

    Empty strings and zeroes are omitted: a navigation line offering `section=""` teaches
    the model an argument that means nothing."""
    parts = [
        f"{key}={json.dumps(value, ensure_ascii=False)}"
        for key, value in args.items()
        if value not in ("", 0, None)
    ]
    return f"{tool}({', '.join(parts)})"


def section_counts(items: Sequence, *, key: str = "section_path") -> tuple[tuple[str, int], ...]:
    """`(section, count)` over items carrying a section path, in first-appearance order."""
    counts: dict[str, int] = {}
    for item in items:
        path = getattr(item, key, ()) or ()
        name = " › ".join(path) if path else "(no section)"
        counts[name] = counts.get(name, 0) + 1
    return tuple(counts.items())


def navigation_line(
    *,
    total: int,
    offset: int,
    shown: int,
    unit: str,
    sections: Sequence[tuple[str, int]] = (),
    more: str = "",
    narrow: str = "",
) -> str:
    """The one line every paginated component response ends with.

    It states the whole even when the whole did not fit, which is the point: a response that
    simply stops reads as "that was everything", and the deep lane's whole promise is
    completeness over caps."""
    head = f"— {shown} of {total} {unit} shown"
    if total and shown:
        head += f" (positions {offset + 1}-{offset + shown})"
    parts = [head]
    if sections:
        parts.append("sections: " + " · ".join(f"{name} ×{count}" for name, count in sections))
    if more and offset + shown < total:
        parts.append(f"the rest: {more}")
    if narrow:
        parts.append(f"one section: {narrow}")
    return "\n".join(parts)


#: The sentence every paginated component tool description ends with. One shape, so a model
#: that has read one of them has read all of them.
PAGINATED_NOTE = (
    "Results are paginated: pass offset/limit to page through them, and every response ends "
    "with the exact call that fetches the rest."
)


__all__ = [
    "PAGINATED_NOTE",
    "PROFILE_PAGE_LIMIT",
    "TIMELINE_PAGE_LIMIT",
    "VERBATIM_PAGE_LIMIT",
    "call_text",
    "navigation_line",
    "section_counts",
]
