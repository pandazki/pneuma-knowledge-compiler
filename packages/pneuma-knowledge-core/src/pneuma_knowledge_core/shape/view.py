"""The LIBRARY VIEW: subjects, edges, claims and titles, computed once for every tier.

The check (tier two) and the lens (tier three) read the same library and must not read it
two ways: a dead end the check counts and a dead end the lens bands have to be the same
observation, or the two faces disagree in front of the same Owner
(docs/design/structure-lens.md §4.1). So the fold happens here, once — a closed volume's
claims and links belong to the page it was cut out of, an archived document leaves the
counts without leaving the map — and both tiers take the result.

Pure and sync: documents and path templates in, a value out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..compile.documents import TITLE_KEY, derived_title
from ..domain.archive import is_archive_record, is_archived_path
from .families import subject_of
from .links import Edge, in_degree, out_degree, subject_claims, subject_edges


@dataclass(frozen=True)
class LibraryView:
    """One reading of the library, computed once and handed to every predicate.

    `documents` is what is JUDGED — live, record-free, volumes included. `known_paths` is
    what links RESOLVE against and is deliberately wider: it holds the archived documents and
    the archive records too, so a link to a subject the Owner retired is not reported as a
    dead link. The archive is out of the counts, not out of the map.
    """

    documents: Mapping[str, object]
    known_paths: frozenset[str]
    path_templates: tuple[str, ...]
    subjects: tuple[str, ...]
    claims: Mapping[str, int]
    titles: Mapping[str, str]
    edges: tuple[Edge, ...]
    in_degree: Mapping[str, int] = field(default_factory=dict)
    out_degree: Mapping[str, int] = field(default_factory=dict)

    @property
    def total_claims(self) -> int:
        return sum(self.claims.values())

    def body(self, path: str) -> str:
        doc = self.documents.get(path)
        return str(getattr(doc, "body", "") or "") if doc is not None else ""

    def frontmatter(self, path: str) -> Mapping[str, object]:
        doc = self.documents.get(path)
        return dict(getattr(doc, "frontmatter", {}) or {}) if doc is not None else {}

    def files_of(self, subject: str) -> list[str]:
        """Every FILE a subject is written in: the open page and its closed volumes."""
        present = set(self.documents)
        return sorted(
            path for path in present if subject_of(path, present) == subject
        )


def written_title(doc: object) -> str:
    """A page's name AS WRITTEN: its leading `# ` heading, else its frontmatter `title`, else
    the empty string.

    Deliberately not `canonical_glance.document_title`, which falls back to the filename stem
    so that every read face has something to print. That fallback is right for a display name
    and wrong for a judgement: a page with no heading and no stored title has no NAME, the
    check says so (`id.title_degenerate`), and a fallback would quietly answer `flow` for a
    page nobody ever named. The two readings agree everywhere a name exists, because both are
    `compile.documents.derived_title` over the same heading.
    """
    body = str(getattr(doc, "body", "") or "")
    heading = derived_title(body)
    if heading:
        return heading
    frontmatter = dict(getattr(doc, "frontmatter", {}) or {})
    return str(frontmatter.get(TITLE_KEY, "") or "").strip()


def _by_path(documents: Sequence[object] | Mapping[str, object]) -> dict[str, object]:
    """`{path: document}` from either shape. A document is anything carrying `.path`,
    `.frontmatter` and `.body` — `CanonicalDocument` and the gate's `DraftDoc` both do, and
    nothing here has any business knowing which of the two it was handed."""
    if isinstance(documents, Mapping):
        return {str(path): doc for path, doc in documents.items()}
    return {
        str(getattr(doc, "path", "")): doc
        for doc in documents
        if getattr(doc, "path", "")
    }


def judged_documents(
    documents: Sequence[object] | Mapping[str, object],
) -> tuple[dict[str, object], frozenset[str]]:
    """`(what is judged, every path a link resolves against)`.

    Two sets, deliberately different. What is JUDGED is the live library minus the archive
    records: an archived document is out of every count, and a record is a page a mechanical
    channel wrote and no compile may touch, so a finding about one would name an action
    nobody can take. What links RESOLVE against is every path handed in — the archive
    included.
    """
    by_path = _by_path(documents)
    judged = {
        path: doc
        for path, doc in by_path.items()
        if not is_archived_path(path) and not is_archive_record(doc)
    }
    return judged, frozenset(by_path)


def build_view(
    documents: Sequence[object] | Mapping[str, object],
    path_templates: Sequence[str],
    *,
    known_paths: frozenset[str] | None = None,
) -> LibraryView:
    """The shared view over the documents handed in, archive folded out of the counts."""
    judged, known = judged_documents(documents)
    if known_paths is not None:
        known = frozenset(known_paths) | known
    present = set(judged)
    edges = tuple(subject_edges(judged))
    claims = subject_claims(judged)
    subjects = tuple(
        sorted(path for path in present if subject_of(path, present) == path)
    )
    titles = {subject: written_title(judged[subject]) for subject in subjects}
    return LibraryView(
        documents=dict(judged),
        known_paths=known,
        path_templates=tuple(str(t) for t in path_templates),
        subjects=subjects,
        claims=claims,
        titles=titles,
        edges=edges,
        in_degree=in_degree(edges),
        out_degree=out_degree(edges),
    )


__all__ = ["LibraryView", "build_view", "judged_documents", "written_title"]
