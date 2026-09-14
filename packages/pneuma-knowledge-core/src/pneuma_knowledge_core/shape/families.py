"""Family ROLES — what a contract expects of a family, read off its path templates.

The framework holds no opinion about what a project is. What it does hold is a small table
of names a contract may use, and what each name means for layout: a family whose template
ends in `overview.md` is a hub and is expected to reach its own subtree; one ending in
`evolution.md` is a chronology and is expected to run in time; `features` / `decisions`
directories are child families of the project the hub heads.

The table is the whole of the framework's domain knowledge about layout
(docs/design/structure-lens.md §2), and all three tiers read it here: the GATE refuses a
degenerate or hub-shared title by it, the CHECK judges a hub and a chronology by it, and the
LENS reads the library's shape by it. A contract that uses none of these names gets only the
family-agnostic readings, and that is the honest outcome: nothing here speaks about a layout
it was never told the shape of.

This module is a LEAF on purpose — path arithmetic over templates and paths, nothing that
reads a document, nothing that reads canonical — because the gate imports it, and a gate that
had to import a reading of the whole library to judge one title would be a gate with a
library-sized dependency.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"

#: A closed volume's filename inside a page's volume directory: `a01.md`, `a02.md`, …
#: The naming itself belongs to `compile.rollover`; the GRAMMAR lives here, beside path
#: ownership, because both answer "which page does this path belong to" and one question
#: answered in two modules is two answers waiting to disagree.
VOLUME_FILE_RE = re.compile(r"^a(\d{2,})\.md$")


def _template_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{slug\})", template)
    body = "".join(_SLUG if p == "{slug}" else re.escape(p) for p in parts)
    return re.compile(f"^{body}$")


def path_allowed(path: str, path_templates: Sequence[str]) -> bool:
    """True iff `path` matches one of the skill's path templates (path ownership).

    This is the WRITE ownership predicate: what `create_document` will accept. It deliberately
    does NOT recognize a page's volume directory (see `compile.patch.history_volume_owner`) —
    a rollover volume must be unreachable from the compile tool face.
    """
    return any(_template_regex(t).match(path) for t in path_templates)

#: The roles. `OTHER` is a declared family the table has no name for — a real answer, and
#: the reason the family-agnostic readings exist.
ROLE_HUB = "hub"
ROLE_CHRONOLOGY = "chronology"
ROLE_CHILD = "child"
ROLE_OWNER_VIEW = "owner_view"
ROLE_PEOPLE = "people"
ROLE_TOPICS = "topics"
ROLE_OTHER = "other"

#: The filename a family hub's template ends in.
HUB_FILENAME = "overview.md"
#: The filename a chronology's template ends in.
CHRONOLOGY_FILENAME = "evolution.md"
#: Directory segments that make a template a CHILD family of the project above it.
CHILD_SEGMENTS: frozenset[str] = frozenset({"features", "decisions"})
#: The first segment of the Owner's own views.
OWNER_SEGMENT = "owner"
#: The two memory families, by their leading segments.
PEOPLE_PREFIX = ("memory", "people")
TOPICS_PREFIX = ("memory", "topics")


def family_role(template: str) -> str:
    """The role one path template plays, by name alone."""
    segments = [s for s in str(template or "").split("/") if s]
    if not segments:
        return ROLE_OTHER
    last = segments[-1]
    if last == HUB_FILENAME:
        return ROLE_HUB
    if last == CHRONOLOGY_FILENAME:
        return ROLE_CHRONOLOGY
    if any(segment in CHILD_SEGMENTS for segment in segments[:-1]):
        return ROLE_CHILD
    if segments[0] == OWNER_SEGMENT:
        return ROLE_OWNER_VIEW
    if tuple(segments[:2]) == PEOPLE_PREFIX:
        return ROLE_PEOPLE
    if tuple(segments[:2]) == TOPICS_PREFIX:
        return ROLE_TOPICS
    return ROLE_OTHER


def roles(path_templates: Sequence[str]) -> dict[str, str]:
    """template → role, for every declared family."""
    return {str(template): family_role(str(template)) for template in path_templates}


def template_of(path: str, path_templates: Sequence[str]) -> str | None:
    """The declared family owning `path`, or None. The gate's own ownership predicate, so
    "which family" here means exactly what path ownership means at write time."""
    for template in path_templates:
        if path_allowed(path, [str(template)]):
            return str(template)
    return None


def role_of(path: str, path_templates: Sequence[str]) -> str:
    """The role of the family owning `path`; `ROLE_OTHER` for a path no family owns."""
    template = template_of(path, path_templates)
    return family_role(template) if template is not None else ROLE_OTHER


def project_dir(path: str, path_templates: Sequence[str]) -> str:
    """The project directory `path` belongs to, or `""` when its family declares none.

    A project is the directory a hub heads: `projects/{slug}/overview.md`,
    `projects/{slug}/evolution.md` and `projects/{slug}/decisions/{slug}.md` all belong to
    `projects/<slug>`. Derived from the TEMPLATE rather than from the path's shape — the
    project segment is the first `{slug}` the template does not end on, which is exactly the
    segment the contract varies per project.
    """
    template = template_of(path, path_templates)
    if template is None:
        return ""
    parts = template.split("/")
    for index, segment in enumerate(parts[:-1]):
        if segment == "{slug}":
            return "/".join(path.split("/")[: index + 1])
    return ""


def subject_of(path: str, documents: Iterable[str] | Mapping[str, object]) -> str:
    """The open page `path` belongs to: itself, or the page a closed volume was cut out of.

    `<doc>/aNN.md` folds onto `<doc>.md`, which is the same derivation
    `compile/patch.py::history_volume_owner` makes. It is MIRRORED rather than called
    because that function answers a write question — "is the owner a page a compile may
    write" — and takes the path templates to answer it. The lens is reading a committed
    tree, where the fact that matters is that the owner is REALLY THERE: a volume whose page
    is gone is a subject of its own, and folding it onto a path no document has would make
    its claims belong to nothing.
    """
    present = set(documents)
    directory, _, filename = path.rpartition("/")
    if not directory or VOLUME_FILE_RE.match(filename) is None:
        return path
    owner = f"{directory}.md"
    return owner if owner in present else path


__all__ = [
    "CHILD_SEGMENTS",
    "CHRONOLOGY_FILENAME",
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
    "path_allowed",
    "project_dir",
    "role_of",
    "roles",
    "subject_of",
    "template_of",
]
