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

One rule about work an implementation did not make: it never discards it. Some canonical
stores sit where people and their tools can also write — the shipped one is a git repository
in a working directory — so an implementation that recovers its own dead writer's leftovers
must be able to PROVE they are its own, and must refuse (`CanonicalDirtyError`) when it
cannot. The proof is a claim written before the first mutating command, and it names both
halves of the question: WHO was writing, and WHICH PATHS they were entitled to write. Every
write of this port knows its paths before it writes any of them, so a recovery runs only
while nothing outside that list is dirty and reaches nothing outside it when it runs — a tree
holding a dead writer's leftovers AND somebody's later file is refused whole, never cleaned
in part. The claim is MANDATORY: a write that cannot mark the tree does not proceed
(`CanonicalMarkerError`), because an unmarked crash leaves residue that reads as somebody
else's and is then refused by every later writer.
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


class CanonicalMarkerError(CanonicalMoveError):
    """A mutation could not CLAIM the tree, so it did not run at all.

    In the `CanonicalMoveError` family because every caller that reports a refused write
    already catches that, and this is one: nothing was written, and the tree is byte-for-byte
    what it was.

    WHY IT IS FATAL RATHER THAN BEST EFFORT. An implementation that recovers its own dead
    writer's leftovers may only do so on PROOF that they are its own (see the module
    docstring), and the proof is the claim it writes before its first mutating command. A
    write that proceeded without one would, if it then died, leave a dirty tree that reads as
    somebody else's work — recoverable by nothing and refused by every later writer
    (`CanonicalDirtyError`) until a human intervenes. Refusing up front costs one write that
    was going to fail; proceeding unmarked costs the library's next writer.

    `path` is the claim file the implementation could not write.
    """

    def __init__(self, path: str) -> None:
        super().__init__("could not claim the repository for this write", path)


class CanonicalDirtyError(RuntimeError):
    """The canonical repository holds uncommitted changes this framework did not make.

    Declared beside the port, next to `CanonicalMoveError`, so the callers that have to
    report it — the worker jobs, and the API surfaces above them — can catch it without
    importing a storage implementation.

    WHY IT EXISTS. An implementation may only discard uncommitted work it can PROVE is its
    own dead writer's residue. The git adapter proves it with an in-flight marker written
    before its first mutating command and removed after its commit: a dirty tree with the
    marker present is a crash it caused, and is recovered; a dirty tree with NO marker is
    somebody else's — a person editing the library by hand, a coding agent with a shell in
    the project directory — and is refused with this error, having touched nothing.

    The premise the refusal replaces was "this adapter is the only writer", which was never
    true of a git repository sitting in a working directory. Under it, a `reset --hard` at
    the entry of the next compile silently erased an afternoon of somebody's edits, and the
    only trace was one WARNING line.

    `paths` names every path `git status` reported, so the operator can see what was saved
    by the refusal. `detail` is the machine form a job completion states
    (`canonical_dirty:<paths>`); the message opens with it, so a caller that only has the
    string still names the fault and the files.

    `claimed_by` is for the refusals that meet a claim and still refuse, and there are three.
    One: an implementation whose recovery would DELETE files rather than roll changes back
    may only do so for the operation that wrote them, so a claim left by any other one is
    refused. Two — `unproven` — the claim is not PROOF THAT ITS CLAIMANT DIED, and a claim is
    a licence only once its claimant is provably gone. That covers a claimant still running,
    and equally every claim nobody can read a death out of: a truncated or unparseable
    marker, one naming no pid or a nonsensical one, a pid the OS would not let this process
    probe. `unproven` carries what could and could not be read, because "there is a marker
    and it was still refused" is otherwise unreadable — a genuinely dead writer whose marker
    got corrupted refuses here too, and the operator has to be able to see why.

    Three — `outside`, with `covered` beside it — the claim proves a DEATH but names paths
    other than these. A claim answers WHO DIED; on its own it cannot answer WHAT THEY WERE
    TOUCHING, and a repository is not one writer's: a dead writer's own residue and somebody's
    later file sit in the same listing, so a recovery that took "there was a death here" as a
    licence over the whole tree deleted both. So an implementation records the FOOTPRINT of
    each write — the paths it may touch, known before it touches any of them — recovers only
    when every dirty path is inside it, and reaches only inside it when it does. `outside`
    names the paths that are not, and `covered` is what the claim did account for: a list of
    paths, or None when it recorded none at all, which covers nothing. A ref-only operation
    records an empty footprint, and an empty footprint is a licence over nothing.

    All of these ride in the MESSAGE only; `detail` stays exactly `canonical_dirty:<paths>`
    so the machine face is one string.
    """

    #: The one machine code every face spells this fault with: a job's completion detail, a
    #: proposal's `error`, and the API's `409` body.
    code = "canonical_dirty"

    def __init__(
        self,
        paths: Sequence[str],
        *,
        claimed_by: str | None = None,
        unproven: str | None = None,
        outside: Sequence[str] | None = None,
        covered: Sequence[str] | None = None,
    ) -> None:
        self.paths = tuple(str(p) for p in paths)
        self.claimed_by = claimed_by
        self.unproven = unproven
        self.outside = tuple(str(p) for p in outside) if outside is not None else None
        self.covered = tuple(str(p) for p in covered) if covered is not None else None
        self.detail = f"{self.code}:{','.join(self.paths)}"
        named = claimed_by or "an unnamed operation"
        if unproven is not None:
            claim = (
                f" The claim standing here was left by {named}, and it is NOT PROOF that a "
                f"writer died: {unproven}. A claim licenses discarding uncommitted work only "
                "once its claimant is PROVABLY gone — an integer pid above zero whose "
                "process answers `kill(pid, 0)` with ProcessLookupError — and anything less "
                "than that proof refuses."
            )
        elif outside is not None:
            if self.covered is None:
                accounted = (
                    "That claim recorded NO paths at all, so it accounts for nothing here."
                )
            elif not self.covered:
                accounted = (
                    "That claim recorded an EMPTY footprint — the operation it names touches "
                    "no file in the working tree — so it accounts for nothing here."
                )
            else:
                accounted = f"That claim covered: {', '.join(self.covered)}."
            claim = (
                f" The claim standing here was left by {named} and its claimant is provably "
                "gone — but a claim says who died AND WHAT THEY WERE TOUCHING, and these "
                f"paths are OUTSIDE what it recorded: {', '.join(self.outside or ())}. "
                f"{accounted} A recovery never reaches outside the footprint its claim "
                "recorded, and it does not run at all while anything else is dirty: a tree "
                "holding a dead writer's residue AND somebody's later work is refused whole "
                "rather than cleaned in part."
            )
        elif claimed_by:
            claim = (
                f" The only claim standing here was left by {claimed_by}, which does not "
                "write a checkout, so it is not a licence over these files."
            )
        else:
            claim = ""
        super().__init__(
            f"{self.detail} — the canonical repository has uncommitted changes this "
            "framework did not make, so they are not a crashed writer's residue and are "
            f"not this framework's to discard.{claim} Nothing was written. Commit them, "
            "stash them or revert them, and run this again."
        )


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

        Work left uncommitted by THIS IMPLEMENTATION'S OWN dead writer is its to recover
        before it writes, not the caller's to hear about: it commits what it wrote, so its
        own pending changes at the start of a write are residue, and an implementation that
        stages broadly would otherwise fold them into the next unrelated commit. It is
        discarded, and named in the log. If that recovery cannot get the tree back the move
        is refused (`crash residue could not be cleaned`) — the one case where the library
        needs a human.

        Uncommitted work the implementation CANNOT PROVE is its own is a different thing and
        gets the opposite answer: `CanonicalDirtyError`, having touched nothing. A canonical
        store may sit in a directory people and their tools can also write — the shipped git
        adapter does — so "uncommitted" is not a synonym for "residue", and an implementation
        that treats it as one destroys work it did not make. Proving it is the
        implementation's business (the git adapter writes an in-flight marker); refusing when
        the proof is absent is the port's requirement.

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
