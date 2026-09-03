"""CanonicalStore port — per-user git canonical authority (ADR-001, §5, §6).

The only non-rebuildable layer (invariant I2). patch = commit, snapshot = tag,
rollback = revert — all free from git. Reads accept an optional snapshot
(`at: SnapshotRef`) for snapshot Q&A (§7).

Per-user write serialization is the JobQueue's (one in-flight job per user), and this port
states no lock. It does not state the absence of one either: not every writer arrives
through the queue — the skill manifest is written from the API process — so an
implementation whose storage can have two writes interleave is expected to serialize them
itself, on its own terms. What the port requires is only the OUTCOME: each of these methods
either lands whole or lands not at all, and never absorbs another writer's work into its own
unit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from ..domain.canonical import CanonicalDocument
from ..domain.ids import DocumentId, UserId
from ..domain.snapshot import SnapshotRef


class CanonicalMoveError(RuntimeError):
    """A `move_documents` was refused before anything was committed.

    Declared beside the port rather than inside an adapter so the caller that has to report
    it — the archive job, and the API surface above it — can catch it without importing a
    storage implementation. `path` is the one that made the move impossible: a source that is
    not there, or a destination that already is. A move is all-or-nothing (one commit), so a
    refusal means the tree is byte-for-byte what it was.

    Two reasons name the library's own state rather than a bad move. `could not read
    repository status` says the implementation could not establish the state it refuses or
    proceeds on — a refusal, and a deliberate one: a state that cannot be read is never
    reported as clean. `crash residue could not be cleaned` says an implementation that
    recovers a dead writer's leftovers before it writes (see `move_documents`) tried and did
    not get the tree back; nothing was moved, and the library needs a human.

    One reason is not a refusal but a report: `rollback left the repository dirty` says the
    move failed AND the undo did not get the tree back. It carries the original failure as
    `__cause__`, and the caller must treat the library as needing a human — this is the one
    case where the tree is not what the error's other reasons promise.
    """

    def __init__(self, reason: str, path: str) -> None:
        self.reason = reason
        self.path = path
        super().__init__(f"{reason}: {path}")


class CanonicalStore(Protocol):
    async def read(
        self,
        user_id: UserId,
        document_id: DocumentId,
        *,
        at: SnapshotRef | None = None,
    ) -> CanonicalDocument | None: ...

    async def list(
        self, user_id: UserId, *, at: SnapshotRef | None = None
    ) -> list[CanonicalDocument]: ...

    async def commit_patch(
        self, user_id: UserId, files: dict[str, str], *, message: str
    ) -> SnapshotRef:
        """Write the given path→content file set and commit it; return the resulting
        snapshot ref. The file set is the compiler's produced document table (paths
        relative to the per-user repo root); this replaces those paths' content."""
        ...

    async def move_documents(
        self,
        user_id: UserId,
        moves: Sequence[tuple[str, str]],
        *,
        message: str,
        writes: Mapping[str, str] | None = None,
        removals: Sequence[str] = (),
    ) -> SnapshotRef:
        """Move `(from_path, to_path)` pairs and commit them as ONE commit; return the ref.

        `removals` and `writes` are the archive RECORD's half of the same commit, and they
        are on this verb rather than on a second call for the reason the moves are one
        commit: the record and the move are one act. Applied in a fixed order — removals,
        then moves, then writes — which is what makes both directions expressible with no
        intermediate state ever committed. Archiving MOVES `work/x.md` to `archive/work/x.md`
        and then WRITES the record onto the path the move just vacated; unarchiving REMOVES
        the record and then moves the page back onto it. A write onto a path that still
        exists after the removals and moves is refused (`write path already exists`): the
        record only ever lands where the move made room for it, and an implementation that
        would overwrite a page is one that could lose one.

        The archive's write verb (docs/design/archive.md §2.1). It is a MOVE and not a
        rewrite: the file's bytes, frontmatter, body, anchors and `doc_id` are untouched and
        its git history follows it, so `git log --follow` reads straight through the archive
        boundary and unarchiving is the same call with the pairs reversed.

        Refuses with `CanonicalMoveError`, having committed NOTHING, when a source path is
        missing or a destination path already exists — two documents at one id is the single
        thing a move must never produce, and a half-applied move would produce exactly that.
        It refuses the same way when the library's state cannot be READ at all, rather than
        reading an unanswerable library as a clean one.

        Work left uncommitted by a WRITER THAT DIED is an implementation's to recover before
        it writes, not the caller's to hear about: every writer on this port commits what it
        wrote, so pending changes at the start of a write are residue, and an implementation
        that stages broadly would otherwise fold them into the next unrelated commit. It is
        discarded, and named in the log. If that recovery cannot get the tree back the move
        is refused (`crash residue could not be cleaned`) — the one case where the library
        needs a human.

        Recovery from a failure part-way through THIS call is by contrast SCOPED — an
        implementation undoes exactly what it did (the renames it made, the files it wrote,
        the files it removed) and nothing else; it never restores the whole tree. One commit
        for the whole set because the set is what the Owner confirmed; `message` is the
        caller's, trailers included.
        """
        ...

    async def written_on(
        self, user_id: UserId, *, prefix: str = ""
    ) -> dict[str, str]:
        """path → the day (`YYYY-MM-DD`) that path was last written by a committed patch.

        Free from git, like everything else here: the commit history already records when
        each file last changed, so nothing has to be stored to answer it. It states what was
        COMMITTED — a round that failed the gate wrote nothing and appears nowhere in it —
        which is what makes it usable as the "has this page answered yet" clock a derived
        projection is measured against. `prefix` bounds the walk to one path prefix.
        """
        ...

    async def snapshots(self, user_id: UserId) -> list[SnapshotRef]: ...

    async def snapshots_page(
        self,
        user_id: UserId,
        *,
        limit: int,
        after_ref: str | None = None,
    ) -> tuple[list[SnapshotRef], int, bool]:
        """Read a bounded newest-first git-history page.

        ``after_ref`` is the last item from the preceding page. Continuation walks
        that commit's ancestors, so newer HEAD commits do not shift the page. A ref
        that is no longer in the user's current history is rejected.
        """
        ...

    async def tag(
        self, user_id: UserId, ref: SnapshotRef, label: str
    ) -> SnapshotRef: ...

    async def commit_trailer(
        self, user_id: UserId, ref: SnapshotRef, key: str
    ) -> str | None:
        """Read a git trailer value (e.g. `Skill-Version`) off the commit at `ref`.

        The canonical audit face for M5: which skill version compiled a snapshot is
        stamped into the commit message trailer at compile time — a free, immutable git
        trace. Returns None when the trailer is absent."""
        ...

    async def find_commit_with_trailer(
        self,
        user_id: UserId,
        *,
        key: str,
        value: str,
        since: SnapshotRef | None = None,
    ) -> SnapshotRef | None:
        """The newest commit in `since..HEAD` whose `key` trailer reads exactly `value`.

        `commit_trailer` asks "what did THIS commit decide"; this asks the question a
        resuming writer actually has — "is my own commit in the history at all". They are not
        the same question, and reading HEAD's trailer to answer the second one is wrong
        whenever another writer commits above it. Not every writer arrives through the queue
        (the skill manifest is written from the API process, see the module docstring), so a
        job killed after its commit can find a manifest write standing on top of it, and a
        HEAD-only check would call its own landed work someone else's drift.

        `since` bounds the walk to what happened after the state the caller planned against
        and is EXCLUSIVE — the commit it names is the one the caller already saw. None or an
        empty ref walks the whole history. Returns None when no commit in the range carries
        that trailer value, which is the honest answer to "it never landed".
        """
        ...
