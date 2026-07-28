"""Identity types and anchor extraction.

Anchor marks are the provenance backbone (invariant I4): every canonical claim
carries an anchor id embedded as an HTML comment in the markdown body. The regex
is ported verbatim from Pneuma Compiler and must not be changed.
"""

from __future__ import annotations

import re
from typing import NewType

UserId = NewType("UserId", str)
SourceId = NewType("SourceId", str)
DocumentId = NewType("DocumentId", str)
AnchorId = NewType("AnchorId", str)

# Pneuma Compiler port — do not change.
ANCHOR_MARK_RE = re.compile(r"<!--\s*c:([0-9a-f]{4,})\s*-->")


def extract_anchors(markdown: str) -> list[AnchorId]:
    """Return anchor ids in document order, as they appear in the markdown.

    Duplicates are preserved in order (a re-cited anchor legitimately appears
    more than once); callers dedupe when they need a set.
    """
    return [AnchorId(m.group(1)) for m in ANCHOR_MARK_RE.finditer(markdown)]
