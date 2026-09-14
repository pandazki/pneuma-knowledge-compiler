"""What makes a page's NAME wrong, stated once for the gate and for the check.

A title can be wrong in three ways no single page can see on its own, and two of them are
decidable from the page and the path templates alone: a name that is a family ROLE rather
than a subject (`Overview`, `演进`, or the project's own slug on a page that is not its hub),
and a chronology page carrying its hub's name. The gate refuses either from now on
(docs/design/structure-lens.md §2); the check lists what a library already holds of them
(§3.1). The predicate is here so the two agree by construction: a title the gate accepts is
never one the check reports, which is the whole of the tier ruling in one function.

Pure path and string arithmetic, as `families` is: no document is read here beyond the title
string a caller already has.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..domain.archive import normalize_title
from .families import ROLE_CHILD, ROLE_CHRONOLOGY, ROLE_HUB, project_dir, role_of

#: Titles that name a family role instead of a subject. Compared under `normalize_title`, so
#: case, spacing and punctuation cannot dodge the table. Both shipped languages are in it
#: because the name is written by whichever language the deployment compiles in.
DEGENERATE_TITLE_WORDS: tuple[str, ...] = (
    "overview",
    "evolution",
    "features",
    "feature",
    "decisions",
    "decision",
    "people",
    "topics",
    "概览",
    "总览",
    "综述",
    "演进",
    "项目演进",
    "演进历程",
    "演化",
    "特性",
    "功能",
    "决策",
    "决定",
    "人物",
    "主题",
)

_DEGENERATE_KEYS: frozenset[str] = frozenset(
    normalize_title(word) for word in DEGENERATE_TITLE_WORDS
)


def is_degenerate_title(path: str, title: str, path_templates: Sequence[str]) -> bool:
    """Is `title` a name that says where the page sits rather than what it is about?

    Empty is degenerate: a page with no leading heading has no name at all. A role word is
    degenerate: every page of the family would answer to it. The project slug is degenerate
    on a page that is NOT its project's hub — the hub IS the project, so its carrying the
    project's name is the right outcome, and calling that a fault would make every
    well-named project one.
    """
    key = normalize_title(title)
    if not key:
        return True
    if key in _DEGENERATE_KEYS:
        return True
    if role_of(path, path_templates) in (ROLE_CHRONOLOGY, ROLE_CHILD):
        directory = project_dir(path, path_templates)
        slug = directory.rsplit("/", 1)[-1] if directory else ""
        return bool(slug) and key == normalize_title(slug)
    return False


def hub_of(path: str, paths: Sequence[str], path_templates: Sequence[str]) -> str:
    """The hub page of `path`'s project, or `""` when the family declares no project."""
    directory = project_dir(path, path_templates)
    if not directory:
        return ""
    prefix = directory + "/"
    return next(
        (
            other
            for other in sorted(paths)
            if other != path
            and other.startswith(prefix)
            and role_of(other, path_templates) == ROLE_HUB
        ),
        "",
    )


def shares_hub_title(
    path: str, titles: Mapping[str, str], path_templates: Sequence[str]
) -> str:
    """The hub `path` has taken the name of, or `""`.

    Only a CHRONOLOGY page is judged: it is the page that reads as the project itself and
    keeps being given the project's name, which leaves one name standing over two pages —
    the hub that says what the project is, and the timeline that says what happened to it.
    """
    if role_of(path, path_templates) != ROLE_CHRONOLOGY:
        return ""
    key = normalize_title(titles.get(path, ""))
    if not key:
        return ""
    hub = hub_of(path, list(titles), path_templates)
    if hub and normalize_title(titles.get(hub, "")) == key:
        return hub
    return ""


__all__ = [
    "DEGENERATE_TITLE_WORDS",
    "hub_of",
    "is_degenerate_title",
    "shares_hub_title",
]
