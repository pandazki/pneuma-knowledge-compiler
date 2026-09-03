"""What a `fetch_verbatim` call put in front of the model, as an address.

Both agentic lanes offer the same tool with the same two locators, and both have to publish
what it returned: an answer built on a verbatim fetch is otherwise recorded as a miss, and
the citation copied off the span is rejected for naming an address nothing handed over.

The two locators differ only in who resolves them. `{"blocks": [a, b]}` IS the span — the
lane can name it without asking anyone. `{"section": [...]}` names a section path, and the
block interval behind it lives in the source's structure map; the store resolves it
internally to serve the text, so the lane used to publish nothing at all for a section
fetch and every citation resting on one failed admission. It resolves the same map here, by
the same `StructureMap.resolve` the store used, so the manifest names the interval the model
was actually shown.

That costs one extra read of the source, and only on a section fetch that succeeded. The
alternative was a port method that hands back the interval alongside the text — a wider
contract for every adapter, to avoid a read the lane makes at most a handful of times per
answer.
"""

from __future__ import annotations

from ..domain.consultation import EvidenceRef, span_ref
from ..domain.ids import SourceId, UserId
from ..ports.content_store import ContentStore


async def fetched_span(
    user_id: UserId,
    source_id: str,
    locator: object,
    *,
    content: ContentStore | None = None,
) -> EvidenceRef | None:
    """The address a SUCCESSFUL `fetch_verbatim` returned, or None when it has none.

    `source_id` must already be the real id — a query-local `sNN` handle is valid for one
    call and would be an address that resolves to nothing an hour later.

    Returns None rather than guessing: a malformed locator, a locator of neither shape, or a
    section path this source's structure map does not contain. A fetch that put text in
    front of the model but cannot be addressed contributes nothing, which is the same rule
    the record follows everywhere else.
    """
    if not isinstance(locator, dict):
        return None
    if "blocks" in locator:
        blocks = locator.get("blocks")
        if not blocks or len(blocks) != 2:
            return None
        try:
            return span_ref(source_id, int(blocks[0]), int(blocks[1]))
        except (TypeError, ValueError):
            return None
    if "section" in locator and content is not None:
        try:
            source = await content.get(user_id, SourceId(source_id))
            start, end = source.structure.resolve(locator)
        except (KeyError, ValueError, TypeError, AttributeError):
            return None
        return span_ref(source_id, start, end)
    return None
