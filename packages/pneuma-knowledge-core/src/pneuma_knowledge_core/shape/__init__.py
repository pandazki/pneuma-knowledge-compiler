"""What every tier of docs/design/structure-lens.md shares: the library's SHAPE, derived.

Three tiers read the same canonical library — the write hooks (the gate), the check, and the
structure lens — and a finding belongs to the lowest tier that can see it. What they have in
common is not a finding at all: it is the arithmetic underneath one. Which family a path
belongs to, and what that family's role is (`families`); what makes a page's name wrong
(`titles`); what an edge and a claim are (`links`); what a page's bytes say (`text`); what
the library looks like with volumes folded onto their pages and the archive out of the counts
(`view`); and how a derived sentence is rendered in both packs (`phrase`).

**Only the two LEAVES are re-exported here.** `families` and `titles` are what the GATE
reads, and they import nothing but the standard library and `domain/` — so a gate judging one
title never pulls in a reading of the whole library, and no import cycle can form between the
write path and the tiers that read what it wrote. The other modules are imported from
directly (`from ..shape.view import build_view`), which is also the honest statement of who
depends on what: canonical's glance, the link grammar and the overview parser are behind
them.

Nothing here writes, awaits, or runs a model.
"""

from __future__ import annotations

from .families import (
    CHILD_SEGMENTS,
    CHRONOLOGY_FILENAME,
    HUB_FILENAME,
    OWNER_SEGMENT,
    PEOPLE_PREFIX,
    ROLE_CHILD,
    ROLE_CHRONOLOGY,
    ROLE_HUB,
    ROLE_OTHER,
    ROLE_OWNER_VIEW,
    ROLE_PEOPLE,
    ROLE_TOPICS,
    TOPICS_PREFIX,
    VOLUME_FILE_RE,
    family_role,
    path_allowed,
    project_dir,
    role_of,
    roles,
    subject_of,
    template_of,
)
from .titles import (
    DEGENERATE_TITLE_WORDS,
    hub_of,
    is_degenerate_title,
    shares_hub_title,
)

__all__ = [
    "CHILD_SEGMENTS",
    "CHRONOLOGY_FILENAME",
    "DEGENERATE_TITLE_WORDS",
    "HUB_FILENAME",
    "OWNER_SEGMENT",
    "PEOPLE_PREFIX",
    "ROLE_CHILD",
    "ROLE_CHRONOLOGY",
    "ROLE_HUB",
    "ROLE_OTHER",
    "ROLE_OWNER_VIEW",
    "ROLE_PEOPLE",
    "ROLE_TOPICS",
    "TOPICS_PREFIX",
    "VOLUME_FILE_RE",
    "family_role",
    "hub_of",
    "is_degenerate_title",
    "path_allowed",
    "project_dir",
    "role_of",
    "roles",
    "shares_hub_title",
    "subject_of",
    "template_of",
]
