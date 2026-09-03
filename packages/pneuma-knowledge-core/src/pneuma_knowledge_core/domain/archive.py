"""The archive: where the Owner moves knowledge that is no longer worth an answer slot.

See docs/design/archive.md. Two authoritative marks exist and this module states the one
that lives in canonical: a document is archived iff its path sits under `archive/`. Every
reader — glance, outline, projection, gate, the answering lanes — derives "is this archived"
from the path prefix stated here and from nothing else, which is what makes the mark
rebuildable: `rebuild_derived` reads the tree and sees the prefix.

The other mark, a source's `archived_at`, lives on L0 and reaches core as a field on
`RawSource`; `ArchiveView` below is the assembly-time face over both.

This is NOT the rollover mechanism. A rollover volume (`<doc>/aNN.md`) is a document's own
frozen history and is live knowledge; a document goes into the archive together with its
volumes, and comes back with them.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from .canonical import CanonicalDocument
from .ids import SourceId

#: The one reserved root. A contract has no reason to declare a family here, and path
#: templates are exact patterns, so the ordinary ownership predicate already refuses writes
#: into it; the gate's `archived_path` check states the rule explicitly on top.
ARCHIVE_ROOT = "archive"
_ARCHIVE_PREFIX = ARCHIVE_ROOT + "/"

#: The `type` an ARCHIVE RECORD carries. The record is the short live page left standing at
#: `<path>` when the full page moves to `archive/<path>`: what the subject was, the span it
#: covered, how much it held, and the owner's reason. It is ordinary live knowledge — in the
#: glance, indexed as claims, retrieved by default — so a question about the subject is
#: answered "this was X, and the owner archived it on D because R" rather than with silence.
#:
#: Deliberately NOT the `archive` a closed volume falls back to when its page declares no
#: type of its own (`compile/rollover.py: volume_frontmatter`). Two different words for two
#: different things, and the one letter between them is load-bearing: a volume is live
#: knowledge of a page that got long, a record is what a retired subject leaves behind.
ARCHIVE_RECORD_TYPE = "archived"

#: The record's own frontmatter. `archive_of` names the full copy (`archive/<path>`) and is
#: what makes a record recognizable even if its `type` were ever edited by hand; the rest are
#: the MACHINE FACTS the record's second block states in words — its provenance, since that
#: line cites no source of its own.
ARCHIVE_OF_KEY = "archive_of"
ARCHIVED_ON_KEY = "archived_on"
ARCHIVE_STATEMENT_KEY = "archive_statement"
ARCHIVE_SPAN_KEY = "archive_span"
ARCHIVE_CLAIMS_KEY = "archive_claims"
ARCHIVE_SOURCES_KEY = "archive_sources"
ARCHIVE_VOLUMES_KEY = "archive_volumes"
ARCHIVE_INBOUND_KEY = "archive_inbound"

#: Every key a complete record carries. `archive_span` is NOT here: a page whose sources
#: state no date has no span, and a key stating an empty one would be a fact nobody has.
ARCHIVE_RECORD_KEYS = (
    ARCHIVE_OF_KEY,
    ARCHIVED_ON_KEY,
    ARCHIVE_STATEMENT_KEY,
    ARCHIVE_CLAIMS_KEY,
    ARCHIVE_SOURCES_KEY,
    ARCHIVE_VOLUMES_KEY,
    ARCHIVE_INBOUND_KEY,
)


def is_archive_record(doc: object) -> bool:
    """Whether `doc` is an archive record — the live page a moved subject left behind.

    Two agreeing signals, read off the frontmatter alone so the predicate holds for a
    `CanonicalDocument`, a compile `DraftDoc` and anything else carrying one: the declared
    `type`, and the `archive_of` key naming the full copy. Either is enough, because the
    record is written by one mechanical channel and both are written together — the second
    signal exists so a hand-edited `type` cannot turn a record into an editable page.

    A record is LIVE: it is not under `archive/`, every lane retrieves it by default, and
    `is_archived_path` is false for it. What it is not is WRITABLE — every compile write
    verb refuses it and the gate refuses any diff on it, because it states a decision the
    owner made and the owner unmakes it by unarchiving.
    """
    frontmatter = getattr(doc, "frontmatter", None) or {}
    if str(frontmatter.get("type") or "").strip() == ARCHIVE_RECORD_TYPE:
        return True
    return bool(str(frontmatter.get(ARCHIVE_OF_KEY) or "").strip())


def is_archived_path(path: str) -> bool:
    """Whether a canonical path sits in the archive."""
    return path.startswith(_ARCHIVE_PREFIX)


def archived_path(path: str) -> str:
    """The archive path of a live path: `work/x.md` → `archive/work/x.md`. Idempotent."""
    return path if is_archived_path(path) else _ARCHIVE_PREFIX + path


def live_path(path: str) -> str:
    """The live path of an archived path: `archive/work/x.md` → `work/x.md`. Idempotent."""
    return path[len(_ARCHIVE_PREFIX) :] if is_archived_path(path) else path


def split_archived(
    docs: Iterable[CanonicalDocument],
) -> tuple[list[CanonicalDocument], list[CanonicalDocument]]:
    """(live, archived), each in the input order."""
    live: list[CanonicalDocument] = []
    archived: list[CanonicalDocument] = []
    for doc in docs:
        (archived if is_archived_path(doc.path) else live).append(doc)
    return live, archived


def live_documents(docs: Iterable[CanonicalDocument]) -> list[CanonicalDocument]:
    """The documents a default reader sees: everything not under `archive/`."""
    return [doc for doc in docs if not is_archived_path(doc.path)]


def restructurable_documents(
    docs: Iterable[CanonicalDocument],
) -> list[CanonicalDocument]:
    """The documents a whole-library REORGANIZATION may re-file: live, minus the records.

    `live_documents` is what a reader sees; this is the narrower set evolve reasons about and
    rewrites. An archive record is live — every lane retrieves it, the compile draft holds
    it — but it is not material a reorganization has anything to say about: it is a page a
    mechanical channel derived from a decision the owner made, and evolve moves claims
    between pages and renames families. So a record stays byte-for-byte where it stands,
    like a closed volume and like `archive/` itself, and it is not counted as part of the
    shape the proposal reasons about either — a family is not crowded by the subjects that
    left it.
    """
    return [doc for doc in live_documents(docs) if not is_archive_record(doc)]


def retired_paths(docs: Iterable[CanonicalDocument]) -> frozenset[str]:
    """The live paths this tree no longer restructures — both marks of one retirement.

    A path an archived copy shadows (`shadowed_paths`) and a path a record stands on. In a
    finished archive the two name the same path from its two sides; both are read because
    both are written, and either alone would miss a tree caught between them.

    The one caller that needs it is the evolve ADOPT merge, whose three sides can disagree
    about a subject: the branch was built before the owner archived it and still holds the
    live page, current main holds the record. The branch's copy is not the reconciliation's
    to carry — a merge would resurrect a retired subject at the path the record occupies —
    so it is dropped from the sides that predate the decision.
    """
    return shadowed_paths(docs) | frozenset(
        doc.path for doc in docs if is_archive_record(doc)
    )


def any_archived(docs: Iterable[CanonicalDocument]) -> bool:
    """Whether this tree holds an archived document at all.

    Read over the FULL tree — before `live_documents` filters it — because that is the only
    place the fact is visible: a lane is handed the live set, and a live set says nothing
    about whether an archive exists beside it. It is what turns the assembly filter's pin on
    (`ArchiveView.documents_archived`), so the caller that lists the tree is the one that
    must ask.
    """
    return any(is_archived_path(doc.path) for doc in docs)


class LoadedDocuments(NamedTuple):
    """A canonical read that carries BOTH facts a lane needs: the set, and whether an
    archive exists beside it.

    For the one lane that reads canonical through a callable rather than a parameter (live
    context's `load_documents`, awaited only once a tick has a real plan). The callable is
    still free to return a plain sequence — that is what every pre-archive caller returns
    and it reads as "no archive", exactly as `archive_active=False` does everywhere else.
    """

    documents: Sequence[CanonicalDocument]
    archive_active: bool = False


#: The separator and terminal punctuation `normalize_title` drops — ASCII and CJK together,
#: stated once, here.
#:
#: A FIXED list, deliberately, and not "every Unicode `P*` category". Those categories also
#: hold characters that CARRY a name: an archived `C#` under a category rule normalizes to
#: `c` and shadows a live `C`, and `C++` shadows it too. What is listed here is only what
#: SEPARATES or TERMINATES — dashes, connectors, commas, stops, quotes, brackets, slashes.
#: Everything else survives: `#`, `&`, `+`, `@`, `%`, `$`, digits, letters, CJK.
_SEPARATOR_PUNCTUATION = frozenset(
    # ASCII, plus the dashes and curly quotes an editor produces
    "-–—_·,.;:!?'\"()[]<>/\\|~`"
    # CJK. NFKC folds the fullwidth forms onto the ASCII row above before this set is
    # consulted; they are listed anyway so the rule reads as what it is.
    "，。；：！？、「」『』“”‘’（）【】《》〈〉…～"
)


def normalize_title(title: str) -> str:
    """A document title reduced to the form two titles are compared in.

    NFKC (so a fullwidth or compatibility spelling folds onto the plain one), casefold, then
    every whitespace character and every character of `_SEPARATOR_PUNCTUATION` dropped. What
    survives is the name itself — letters, digits, CJK, and any symbol the name is MADE of —
    in order, so `Small-group invitation`, `小范围邀请：首次成功` and `小范围邀请，首次成功` compare
    as the strings a reader would call the same name.

    Only separators go, and that is the whole of the choice: `#`, `&`, `+`, `@` are MEANING,
    not spacing. Dropping every punctuation category would make an archived `C#` shadow a
    live `C` — a page it has nothing to do with — and this rule refuses writes, so a false
    match costs the library a page it was entitled to.

    Deliberately NOT a similarity measure. It is an equality rule, mechanical and
    reproducible, and a PARAPHRASED title escapes it by construction (see
    `compile.patch.PatchDraft._refuse_shadowed_title`).
    """
    folded = unicodedata.normalize("NFKC", title).casefold()
    return "".join(
        ch for ch in folded if not ch.isspace() and ch not in _SEPARATOR_PUNCTUATION
    )


def shadowed_paths(docs: Iterable[CanonicalDocument]) -> frozenset[str]:
    """Live paths an archived document shadows.

    While `archive/work/x.md` exists, `work/x.md` may not be created: a document's id derives
    from its path, and two documents with one id is the one thing a move must never produce.
    The subject comes back by unarchiving, not by rewriting.
    """
    return frozenset(live_path(doc.path) for doc in docs if is_archived_path(doc.path))


@dataclass(frozen=True)
class ArchiveView:
    """The assembly-time face over both marks, for one retrieval.

    `sources` is the set of archived source ids (read once from L0 via
    `ContentStore.archived_source_ids`); document state is read off the path. A lane applies
    this AFTER the index filters, over every evidence face it assembled — claims, windows,
    episodes, component results — so the property holds wherever evidence came from,
    including a component written before the archive existed.

    `documents_archived` is the canonical half of the SAME question `sources` answers for
    L0: does this library hold an archived document at all. It cannot be read off the two
    fields above — a lane is handed the live set, which looks identical whether or not an
    archive stands beside it — so the caller that listed the whole tree states it
    (`any_archived`, `archive_view(..., documents_archived=…)`).

    Together the two make `active`, and `active` is what makes this whole mechanism INERT
    while the archive is empty: see the module docstring of `recall/archive_filter.py` and
    archive.md §3.
    """

    sources: frozenset[SourceId] = field(default_factory=frozenset)
    #: Whether the library this view was built for holds an archived DOCUMENT. Stated by the
    #: caller, never inferred here.
    documents_archived: bool = False

    @staticmethod
    def empty() -> ArchiveView:
        return ArchiveView()

    @property
    def active(self) -> bool:
        """Whether anything has EVER been archived in this library.

        The whole filter is written to be a no-op on an inactive view, and one part of it
        needed this fact to become one: the `live_paths` pin drops a claim whose page the
        lane's document set does not contain, and that is a real drop in a library with no
        archive — a page compiled while the answer was being assembled, an index searched
        live under a past-version `at=` pin. The pin exists to close the window between an
        archive commit and the L3 sync that follows it, so with no archive there is no
        window and no reason for it to run (`archive_filter._pin`).

        Two triggers, either sufficient, because there are two authoritative marks: a
        source with `archived_at` on L0, and a document under `archive/` in canonical.
        """
        return bool(self.sources) or self.documents_archived

    def source_archived(self, source_id: str) -> bool:
        return source_id in self.sources

    def path_archived(self, path: str) -> bool:
        return is_archived_path(path)

    def live_paths(self, paths: Sequence[str]) -> list[str]:
        return [path for path in paths if not is_archived_path(path)]


__all__ = [
    "ARCHIVED_ON_KEY",
    "ARCHIVE_CLAIMS_KEY",
    "ARCHIVE_INBOUND_KEY",
    "ARCHIVE_OF_KEY",
    "ARCHIVE_RECORD_KEYS",
    "ARCHIVE_RECORD_TYPE",
    "ARCHIVE_ROOT",
    "ARCHIVE_SOURCES_KEY",
    "ARCHIVE_SPAN_KEY",
    "ARCHIVE_STATEMENT_KEY",
    "ARCHIVE_VOLUMES_KEY",
    "ArchiveView",
    "LoadedDocuments",
    "any_archived",
    "archived_path",
    "is_archive_record",
    "is_archived_path",
    "live_documents",
    "live_path",
    "normalize_title",
    "restructurable_documents",
    "retired_paths",
    "shadowed_paths",
    "split_archived",
]
