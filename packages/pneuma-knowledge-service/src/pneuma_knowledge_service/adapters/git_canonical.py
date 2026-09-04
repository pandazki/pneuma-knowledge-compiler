"""CanonicalStore over a per-user git repo (ADR-001, architecture.md §5, §6).

The only non-rebuildable layer (invariant I2): patch = commit, snapshot = tag,
rollback = revert — all free from git. Each user gets a repo at
`<canonical_root>/<sanitized user_id>/`, lazily `git init`-ed. The repo path is
derived from user_id ONLY (invariant I1); no caller-supplied path is ever honored.
git is driven via subprocess — no new dependency.

**Honesty note about async here.** The CanonicalStore port is `async def`, but git has no
async client: every operation below is `git` in a subprocess plus local filesystem I/O.
Each public method therefore runs its whole synchronous body inside a single
`asyncio.to_thread` hop — a THREAD POOL, not real async I/O. This is deliberate and is the
right shape for it: one hop per port call keeps a multi-command sequence (add → status →
commit → rev-parse) atomic within one thread instead of interleaving with other requests
mid-commit, and it keeps the event loop free while git runs. Do not read the `async def`
as "this is non-blocking at the OS level" — it is blocking work, moved off the loop.

**One advisory lock per repository.** The per-user job queue serializes the writers that
arrive through it (one in-flight job per user, §5), but not every writer does: `write_meta`
— the skill manifest — is written from the API process, off the queue and off the compile
face, and a manifest write staging its path while a move has its renames staged would be
committed by whichever `git commit` ran next, each absorbing the other's paths into one
commit nobody wrote. So every mutating method takes `flock(LOCK_EX)` on
`<repo_path>/.git/pneuma.lock` for the whole of its git sequence (`_locked`). The file
lives inside `.git/` so it never enters the tree, and never appears in `git status`.

The lock is held on the OPEN FILE DESCRIPTION, so it serializes threads within one process
(the `to_thread` pool) and processes on one host alike — which is exactly the shipped
topology: one API and one worker over one filesystem. A multi-host deployment is NOT
covered: two hosts hold two independent locks over two mounts of the same tree, and
serializing them needs a shared canonical adapter rather than an advisory file lock. That
is a KNOWN RESIDUAL of this adapter, not of the design.

Reads do not lock. `list`, `read_meta`, `snapshots` and their kin run one git process that
reads a committed ref, so the worst a concurrent write can do to them is decide which
commit they see — and either answer is a real state of the library.

**Do not re-enter the lock.** `flock` from a second `open()` in the same process conflicts
with the first, so a `_locked` block that reaches for another one deadlocks against itself.
`_repo` takes and releases the lock around initialization only, before any caller's block
begins; nothing inside a `_locked` body may call it.

**A dirty tree at the entry of a mutating method is recovered ONLY when this adapter can
prove it made it, AND ONLY WHERE THAT PROOF REACHES.** The proof is an IN-FLIGHT MARKER:
`<repo_path>/.git/pneuma.inflight`, written first thing under the lock and before the first
mutating git command, removed after the commit (or after a no-op return). It holds the
operation, the pid, a timestamp AND THE OPERATION'S FOOTPRINT — `paths`, every repo-relative
path this operation may touch, known before it touches any of them. It lives inside `.git/`
beside the lock file, so git never reports it and no commit can carry it.

The branches at the entry of every mutating sequence (`_begin_mutation`):

1. **Clean tree.** Any leftover marker is stale — a previous call that failed after its
   rollback got the tree back — so it is removed and the sequence proceeds.
2. **Dirty tree WITH a marker whose CLAIMANT IS PROVABLY DEAD, AND EVERY DIRTY PATH INSIDE
   THAT MARKER'S FOOTPRINT.** This adapter was mid-write and the process died: the marker
   names which operation and exactly which paths it was entitled to write, and nothing
   outside that list is dirty. The residue is its own, and leaving it would be worse than
   discarding it — every write here stages under a pathspec of its own paths, but `git
   commit` commits the whole INDEX, so a crashed archive's STAGED renames would ride into an
   unrelated compile's commit, attributed to it, under its message. So the paths and the operation are LOGGED at WARNING, then THE FOOTPRINT AND
   NOTHING ELSE is put back (`reset` and `checkout` under a pathspec, the untracked files
   inside it unlinked, the directories that empties pruned), then it is re-read and a
   footprint that is still dirty raises.
3. **Dirty tree with a marker and NO PROOF of a death.** Refused (below).
3b. **Dirty tree, a proven death, and A DIRTY PATH OUTSIDE THE FOOTPRINT.** Refused (below),
   naming the outsiders.
4. **Dirty tree with NO marker.** Somebody else wrote here — a person editing
   `data/canonical/<user>/`, a coding agent with a shell in the project directory — and this
   adapter has no licence over their work. It REFUSES (`CanonicalDirtyError`, naming every
   path) and touches nothing.

**A CLAIM IS A LICENCE ONLY ONCE ITS CLAIMANT IS PROVABLY GONE.** Branch 2 is a statement
about a DEATH, so it demands POSITIVE PROOF of one (`_claimant_is_gone`): the marker parsed
as an object, it carries an integer pid above zero, and that pid answers `kill(pid, 0)` with
`ProcessLookupError`. THE QUESTION IS NOT "IS IT ALIVE?" BUT "IS IT PROVABLY DEAD?" — asked
the first way, every ambiguity answered "not alive" and what stood behind that answer was
`reset --hard` + `clean -fd` over somebody's working tree. So a live pid, an unparseable or
truncated marker, a marker naming no pid or a non-integer one or a pid ≤ 0, a `PermissionError`
or any other `OSError` out of the probe are ALL refused (`CanonicalDirtyError`, naming the
paths, with the operation and what could and could not be read out of the claim in the
message only). A genuinely dead writer whose marker got corrupted therefore refuses too, and
that is the intended direction: an operator then looks at a mess nobody can prove the shape
of, which is exactly the state no automatic recovery is entitled to interpret. Our own pid
counts as alive and is the likeliest live answer: it means a `_clear_marker` in this very
process could neither unlink nor replace the file. The lock already excludes a second live
adapter process on this repository, so a live pid is either ourselves or an unrelated process
holding a reused number — and pid reuse can only push this toward REFUSING, never toward
deleting.

**AND A CLAIM ALONE IS NOT ENOUGH: IT MUST SAY WHAT THE DEAD WRITER WAS TOUCHING.** A pid
identifies a writer, not their work, and a repository is not one writer's: a dead writer's
own residue and a person's later untracked file land in the same `git status`, and the
whole-tree `reset --hard` + `clean -fd` that used to stand behind branch 2 took them
together. A mixed tree is the ordinary case, not a corner one — a stale claim plus a later
`git add`, a crashed archive plus an agent's scratch file — and neither the pid nor the index
says which paths belong to whom. The claim now says it, mechanically, because every mutating
body here KNOWS ITS PATHS BEFORE IT WRITES ANY OF THEM: `commit_patch` has the patch's file
map, `move_documents` has both sides of every pair plus its writes and removals, `write_meta`
has its one path, and the ref-only operations (`branch_commit`, `delete_branch`, `tag`,
`init_repository`) touch no working-tree path at all and record an EMPTY footprint. So branch
2 requires a provably dead claimant AND every dirty path — staged, unstaged and untracked
alike — inside that claim's footprint, and the recovery then reaches only the footprint. One
path outside it is branch 3b and refuses whole, naming the outsiders; a ref-only claim covers
nothing and licenses nothing; a claim with no readable footprint likewise covers nothing. The
restore states the inverse of a footprint for the same purpose — `pre_existing`, what the
target held before it began — because nobody can enumerate what a `git clone` will
materialize until it has. THE ACCEPTED RESIDUAL, stated rather than hidden: a footprint that
failed to name something its writer touched leaves residue OUTSIDE itself, which is REFUSED
rather than cleaned. That is the safe direction — an operator looks — and the opposite
direction has no window at all, because the claim is written before the work.

**THE CLAIM IS WRITTEN BEFORE THE TREE IS READ, AND THE DECISION IS MADE FROM THE CLAIM THAT
WAS THERE BEFORE IT.** Every mutating entry runs in one order: read the previous marker →
write our own (`_write_marker`, which raises `CanonicalMarkerError` on a `.git/` that will not
take it, at an instant when nothing has been touched) → read the tree → decide, weighing the
marker we READ and never the one we just wrote. Writing the claim first is what proves this
filesystem takes claims at all, and the consequence is the point: where the claim cannot be
written, NO MUTATION PROCEEDS, so the one state that leaves a whole claim standing after an
orderly exit — a clear whose unlink AND replace both failed — can never later authorize a
destruction, because the next mutation dies before it reads the tree.

Branch 3 is the correction to what this file used to assume. "Only this adapter writes" was
never true of a git repository sitting in a working directory: under that premise a
`reset --hard` at the entry of the next compile silently erased an afternoon of somebody's
edits, and the only trace was one WARNING line. The lock licenses branch 2 and no more — it
proves no OTHER PROCESS OF THIS FRAMEWORK is mid-sequence, which says nothing at all about a
text editor. The marker is what turns "the tree is dirty" into "*I* left it dirty".

The residue in branch 2 is discarded rather than surfaced because it is not work anyone can
resume: it is the leftovers of an operation whose caller already failed, on paths that
operation had declared before it began, and the record of it is the warning line, which names
every path it took and every path the claim covered.

**The marker is MANDATORY, not best effort.** A mutation that cannot write it does not run
(`CanonicalMarkerError`): unmarked, its own crash residue would arrive at the next writer as
branch 3 — somebody else's work, refused, and refused again until a person intervenes. So the
claim is written by every sequence that writes into the repository, initialization
(`_repo`) and the prebuilt restore included, and the only failure that is merely logged is
the CLEAR at the end of a body, which is over by then (and which degrades the claim rather
than leaving it whole — below).

**A LIVE PROCESS ALWAYS RELEASES ITS CLAIM.** Every mutating body runs inside `_mutation`
(or, where there is no repository to read a status out of yet, `_claimed`), which clears the
marker in a `finally` — so the claim is released on the success path AND on every orderly
refusal, its own entry refusals included, since the claim is now written before those are
decided: a preflight that rejected a destination, a `CanonicalDirtyError`, a rollback that
put the tree back and re-raised. The marker is therefore not "this call is writing"; it is
**"a process died here"** — which branch 2 then VERIFIES against the claimant's pid rather
than taking on trust. Cleared on
the way out of a refusal, it cannot become the licence that destroys a person's later edit:
without this, a refused move left its claim standing, and the hand edit made an hour after it
read as "my own residue" and went under `reset --hard`.

A CLEAR THAT CANNOT UNLINK DEGRADES THE CLAIM instead of leaving it whole: it replaces the
marker ATOMICALLY (a temp file in the same directory, then `os.replace`) with
`{"released": true}`, which `_read_marker` — and so branch 2 and the restore — read as no
claim at all. Atomically, because a release written in place could itself be interrupted, and
the truncated marker that left would be one more claim nobody can read a death out of.
Swallowing the failure and leaving a whole claim standing was the hole this closes: the file
would have outlived an orderly refusal and authorized the next writer's `reset --hard` over a
human's later edits, which is the one deletion this whole
mechanism exists to prevent. Only unlink AND rewrite both failing leaves a whole claim, which
is logged at ERROR; for as long as that process lives the next mutation refuses
(`canonical_dirty`) on the pid check rather than recovering, and after it exits the surviving
claim still reaches no further than the footprint it recorded — a later hand edit is outside
it and is refused.

The one case worth naming, because it looks like an exception and is not: when the rollback
itself could not get the tree clean (`CanonicalMoveError("rollback left the repository
dirty")`), the claim is STILL released, so the next call meets a dirty tree with no marker
and REFUSES (`CanonicalDirtyError`) rather than auto-cleaning a mess nobody proved was
residue. That mess is half this call's renames and half whatever git would not undo — a
state no automatic recovery is entitled to interpret, and an operator has to look at it.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from pneuma_knowledge_core.compile.documents import DOC_ID_KEY, parse_document
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.ports.canonical_store import (
    CanonicalDirtyError,
    CanonicalMarkerError,
    CanonicalMoveError,
)

_log = logging.getLogger(__name__)

_UID_SAFE = re.compile(r"[^a-zA-Z0-9_-]")
_GIT_ID = ("-c", "user.email=pneuma_knowledge@local", "-c", "user.name=pneuma-knowledge")
#: Inside `.git/` on purpose: git never reports its own directory, so the lock is invisible
#: to `git status`, to every commit, and to anyone reading the repository as a library.
_LOCK_NAME = "pneuma.lock"

#: The in-flight marker, beside the lock and inside `.git/` for the same reason. Its
#: PRESENCE beside a dirty tree is the whole proof that the uncommitted work is this
#: adapter's own dead writer's residue and may be discarded; its absence is the proof that it
#: is somebody else's and may not be (module docstring). Written before the first mutating
#: git command of a sequence, removed after that sequence's commit.
_INFLIGHT_NAME = "pneuma.inflight"


@contextlib.contextmanager
def _locked(repo: Path) -> Iterator[None]:
    """Hold the exclusive per-repository advisory lock for the whole of a git sequence.

    Every MUTATING sequence in this adapter runs inside one of these; reads do not (see the
    module docstring). The lock is `flock(LOCK_EX)`, so it is released by the OS when the
    process dies — a writer that crashes mid-write leaves a dirty tree AND its in-flight
    marker for the next writer to recover at its lock entry (`_begin_mutation`), never a
    lock nobody can take.

    NOT re-entrant: a second `open()` in the same process is a second open file description
    and blocks against the first. Nothing inside a `_locked` body may take it again.
    """
    lock_path = repo / ".git" / _LOCK_NAME
    with open(lock_path, "a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class GitCanonicalStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    # --- repo plumbing --------------------------------------------------------

    def repo_path(self, user_id: UserId) -> Path:
        """Where this user's canonical repository lives — without creating it.

        Public because restoring a library that ships prebuilt has to write the repository
        before this store ever reads it, and the addressing (I1: derived from user_id only)
        must have exactly one implementation."""
        return self._root / _UID_SAFE.sub("_", str(user_id))

    @staticmethod
    def _initialized(repo: Path) -> bool:
        # `.git/HEAD` and not `.git/` itself: the lock lives inside `.git/`, so the directory
        # exists from the moment anyone reaches for the lock — before `git init` has run.
        # HEAD is what git itself writes, and it is there in a cloned repository too (the
        # prebuilt restore path), so this reads "a repository is here", not "we made one".
        return (repo / ".git" / "HEAD").is_file()

    def _repo(self, user_id: UserId) -> Path:
        # I1: path derived from user_id only.
        repo = self.repo_path(user_id)
        if self._initialized(repo):
            return repo
        # Creating the repository is itself a mutation two callers can race, so it runs under
        # the same lock as every other write. Taken and RELEASED here, before any caller's
        # own `_locked` block opens — the lock is not re-entrant (see the module docstring).
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        with _locked(repo):
            if not self._initialized(repo):
                # CLAIMED like every other mutation, and for the same reason: `git init` plus
                # the two configs write into `.git/`, and a process killed between them leaves
                # a half-made repository. Marked, the next writer knows whose it is; unmarked,
                # it would be indistinguishable from somebody else's directory.
                # `_begin_mutation` cannot run here — there is no repository to read a status
                # out of yet — so the claim is taken directly, and `_claimed` releases it on
                # every exit including a failed `git init`: a live process never leaves one.
                # Its FOOTPRINT IS EMPTY, and said so rather than left out: `git init` and the
                # two configs write inside `.git/` and touch not one working-tree path, so
                # this claim covers nothing and can license discarding nothing.
                with self._claimed(repo, "init_repository", paths=()):
                    self._run(repo, "init", "-q")
                    self._run(repo, "config", "user.email", "pneuma_knowledge@local")
                    self._run(repo, "config", "user.name", "pneuma-knowledge")
        return repo

    @staticmethod
    def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def _has_head(self, repo: Path) -> bool:
        return (
            subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
                capture_output=True,
                text=True,
            ).returncode
            == 0
        )

    # --- reads ----------------------------------------------------------------

    def _ref(self, at: SnapshotRef | None) -> str:
        return at.ref if at is not None else "HEAD"

    def _list(
        self, user_id: UserId, at: SnapshotRef | None
    ) -> list[CanonicalDocument]:
        repo = self._repo(user_id)
        ref = self._ref(at)
        if at is None and not self._has_head(repo):
            return []

        # Read the complete selected tree in one bounded Git process. The previous
        # ls-tree + one show per document implementation preserved completeness but
        # turned a 60-document Library open into 62 subprocesses. We parse the tar
        # stream in memory and never extract caller-controlled paths to disk.
        archive = subprocess.run(
            ["git", "-C", str(repo), "archive", "--format=tar", ref],
            capture_output=True,
            check=True,
        ).stdout
        docs: list[CanonicalDocument] = []
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tree:
            for member in tree.getmembers():
                if not member.isfile() or not member.name.endswith(".md"):
                    continue
                stream = tree.extractfile(member)
                if stream is None:
                    continue
                docs.append(
                    self._to_document(member.name, stream.read().decode("utf-8"))
                )
        return sorted(docs, key=lambda d: d.path)

    async def list(
        self, user_id: UserId, *, at: SnapshotRef | None = None
    ) -> list[CanonicalDocument]:
        # to_thread: git subprocess + filesystem, no async client exists (see module docstring).
        return await asyncio.to_thread(self._list, user_id, at)

    async def read(
        self,
        user_id: UserId,
        document_id: DocumentId,
        *,
        at: SnapshotRef | None = None,
    ) -> CanonicalDocument | None:
        for doc in await self.list(user_id, at=at):
            if doc.doc_id == document_id:
                return doc
        return None

    def _written_on(self, user_id: UserId, prefix: str) -> dict[str, str]:
        repo = self._repo(user_id)
        if not self._has_head(repo):
            return {}
        args = ["log", "--format=%x00%cs", "--name-only", "--no-renames", "HEAD"]
        if prefix:
            args += ["--", prefix]
        out = self._run(repo, *args).stdout
        written: dict[str, str] = {}
        day = ""
        for line in out.splitlines():
            if line.startswith("\x00"):
                day = line[1:].strip()
                continue
            path = line.strip()
            # Newest first, so the FIRST commit that names a path is the last one that
            # wrote it — later (older) mentions are its earlier history and are skipped.
            if path and day and path not in written:
                written[path] = day
        return written

    async def written_on(
        self, user_id: UserId, *, prefix: str = ""
    ) -> dict[str, str]:
        """path → the day its last commit was made, over one history walk.

        `%cs` is the committer date in the commit's OWN recorded timezone, so the answer is
        a property of the commit and not of whoever reads it — two machines asking this
        question get the same day. One `git log --name-only` walk answers it for every path
        at once; `prefix` is a pathspec, so a caller that only cares about one family walks
        only the commits that touched it.
        """
        # to_thread: git subprocess, no async client exists (see module docstring).
        return await asyncio.to_thread(self._written_on, user_id, prefix)

    @staticmethod
    def _to_document(path: str, text: str) -> CanonicalDocument:
        # `parse_document` folds the pre-rename `pneuma_id` key onto `doc_id`, so a commit
        # made before the rename loads with its id intact and needs no history rewrite.
        frontmatter, body = parse_document(text)
        return CanonicalDocument(
            doc_id=DocumentId(str(frontmatter.get(DOC_ID_KEY, ""))),
            path=path,
            frontmatter=frontmatter,
            body=body,
        )

    # --- writes ---------------------------------------------------------------

    def _commit_patch(
        self, user_id: UserId, files: dict[str, str], message: str
    ) -> SnapshotRef:
        repo = self._repo(user_id)
        with _locked(repo):
            # FIRST, before a byte of this patch is written: somebody else's uncommitted
            # edits are refused here rather than swept (module docstring). It also CLAIMS the
            # tree, so a crash between here and the commit below is recognizable as this
            # adapter's own on the next call — and `_mutation` releases that claim on every
            # exit a live process reaches, refusals included.
            # THE FOOTPRINT IS THE PATCH'S OWN FILE MAP — every path this call will write,
            # known before it writes any of them, and therefore the only thing a recovery
            # after this process's death is allowed to touch.
            paths = sorted(files)
            with self._mutation(repo, "commit_patch", paths=paths):
                for rel, content in files.items():
                    target = repo / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                if paths:
                    # THE PATHSPEC IS THE FOOTPRINT, and staging is scoped to it for the same
                    # reason the recovery is: this call may commit what it wrote and nothing
                    # else. A bare `add -A` stages the WHOLE TREE, and the clean tree
                    # `_begin_mutation` established is a statement about the instant the lock
                    # was taken, not about the instants after it — the lock excludes this
                    # framework's writers, not a person or an agent with a shell in the
                    # library. A file that appeared in that window would be swept into this
                    # compile's commit under this compile's message, which is the one thing a
                    # commit must never say. Scoped, it stays untracked, the next mutation
                    # meets it outside every footprint, and refuses by name.
                    #
                    # `-A` IS KEPT, and only the pathspec is new. Under a pathspec it means
                    # "make the index match the working tree FOR THESE PATHS", so one of them
                    # that is absent is staged as a DELETION rather than skipped. Git 2.0
                    # made that a plain `add`'s behaviour too, which is exactly why the flag
                    # stays: what the index ends up holding for these paths must not depend on
                    # a default that has changed once already. `:(literal)` because these
                    # paths are file names, not patterns (see `_literal`).
                    self._run(repo, "add", "-A", "--", *self._literal(paths))
                # Scoped to the same pathspec as the `add`: the question is whether THIS
                # patch changed anything, and a whole-tree read would answer it with
                # somebody else's mid-flight file — then reach a `commit` with nothing
                # staged. Emptiness is all that is read here, so the quoted form is fine.
                status = ""
                if paths:
                    status = self._run(
                        repo, "status", "--porcelain", "--", *self._literal(paths)
                    ).stdout.strip()
                if status:
                    self._run(repo, *_GIT_ID, "commit", "-q", "-m", message)
                sha = self._run(repo, "rev-parse", "HEAD").stdout.strip()
        return SnapshotRef(ref=sha)

    async def commit_patch(
        self, user_id: UserId, files: dict[str, str], *, message: str
    ) -> SnapshotRef:
        # to_thread: one hop for the whole write sequence, so add → status → commit →
        # rev-parse stays atomic in a single thread (see module docstring).
        return await asyncio.to_thread(self._commit_patch, user_id, files, message)

    def _move_documents(
        self,
        user_id: UserId,
        moves: Sequence[tuple[str, str]],
        message: str,
        writes: dict[str, str],
        removals: Sequence[str],
    ) -> SnapshotRef:
        repo = self._repo(user_id)
        with _locked(repo):
            # The claim goes on the way out of ALL of them: the commit, the no-op return,
            # the preflight refusal, and the rollback that put the tree back. It goes on the
            # way out of the rollback that DIDN'T, too — see `_mutation`: the next call then
            # refuses `canonical_dirty` over a tree no automatic recovery may interpret.
            # BOTH SIDES OF EVERY PAIR, plus every write and every removal: the footprint
            # is what this call MAY touch, so a rename's source (which it vacates) and its
            # destination (which it creates) are both on it. Nothing else it does reaches the
            # working tree.
            footprint = sorted(
                {path for pair in moves for path in pair}
                | set(writes)
                | set(removals)
            )
            with self._mutation(repo, "move_documents", paths=footprint):
                return self._move_documents_locked(
                    repo, moves, message, writes, removals
                )

    def _move_documents_locked(
        self,
        repo: Path,
        moves: Sequence[tuple[str, str]],
        message: str,
        writes: dict[str, str] | None = None,
        removals: Sequence[str] = (),
    ) -> SnapshotRef:
        # Runs under the repository lock (`_move_documents`), after `_begin_mutation` has
        # established a clean tree and claimed it, so the preflight below and the renames
        # see one tree that no other writer on this host can change between them. Nothing
        # here may take the lock again.
        writes = dict(writes or {})
        removals = list(removals)
        if not moves and not writes and not removals:
            # Nothing to move is not an error; it is a set the Owner narrowed to empty.
            # Answer with the ref the tree already has rather than an empty commit.
            if not self._has_head(repo):
                return SnapshotRef(ref="")
            return SnapshotRef(ref=self._run(repo, "rev-parse", "HEAD").stdout.strip())

        # EVERY refusal is decided before the first `git mv`, so a rejected move leaves the
        # working tree and HEAD byte-for-byte as they were. Checking as we go would leave the
        # first half applied and the second half not — the one state a move must never
        # produce, and the state nothing downstream could name.
        #
        # The tree's own state is not among these checks any more: `_begin_mutation` ran at
        # the lock entry above and either established a clean tree or raised, so what is
        # left to rule out is what the MOVE SET says — a source that is not there, a
        # destination that is taken.
        # The preflight SIMULATES the whole sequence rather than checking each part against
        # the filesystem alone, because the parts depend on each other: the record's write
        # target is a path the move is about to vacate, and the page an unarchive moves back
        # lands on a path the removal is about to free. A check that only ever asked the disk
        # would refuse both of the two sequences this verb exists for.
        overlay: dict[str, bool] = {}

        def _present(path: str) -> bool:
            if path in overlay:
                return overlay[path]
            return (repo / path).exists()

        for path in removals:
            if not _present(path):
                raise CanonicalMoveError("path is not in the library", path)
            overlay[path] = False
        for from_path, to_path in moves:
            if not _present(from_path) or not (repo / from_path).is_file():
                raise CanonicalMoveError("source path is not in the library", from_path)
            if _present(to_path):
                raise CanonicalMoveError("destination path already exists", to_path)
            overlay[from_path] = False
            overlay[to_path] = True
        for path in sorted(writes):
            if _present(path):
                raise CanonicalMoveError("write path already exists", path)
            overlay[path] = True

        # Past this point renames are being applied, so ANY failure — a later `git mv`, the
        # status read, the commit itself — leaves earlier renames staged in a tree that is
        # neither the old set nor the new one. The preflight above cannot rule that out: it
        # states what was true before the first rename, and the filesystem can refuse a
        # later one anyway. So the failure path UNDOES exactly the renames this call made,
        # in reverse, and touches nothing else: `performed` is the list of what actually
        # landed, and it is the whole authority for what the rollback may move.
        #
        # `created` is the second, separate authority: the directories this call brought into
        # existence. It is NOT derivable from `performed`, because the pair whose `git mv`
        # failed had its destination directory created a moment before the failure — that
        # directory is this call's litter and nothing else will ever remove it.
        performed: list[tuple[str, str]] = []
        created: list[Path] = []
        removed: list[str] = []
        written: list[str] = []
        try:
            # REMOVALS, then moves, then writes — the one order in which both directions of
            # the archive express themselves without an intermediate state ever existing on
            # disk (see the port's docstring).
            for path in removals:
                # `:(literal)`: these paths came from a proposal, not from a user typing a
                # pattern, so each must match ITSELF (see `_literal`).
                self._run(repo, "rm", "-q", "--", *self._literal([path]))
                removed.append(path)
            for from_path, to_path in moves:
                self._make_parents(repo, repo / to_path, created)
                # NOT `_literal`: `git mv` takes plain paths, not pathspecs — it reads them
                # literally already, and REFUSES `:(literal)` ("bad source"). The glob
                # hazard the other calls here guard against does not exist for this verb.
                self._run(repo, "mv", "--", from_path, to_path)
                performed.append((from_path, to_path))
            for path in sorted(writes):
                self._make_parents(repo, repo / path, created)
                (repo / path).write_text(writes[path], encoding="utf-8")
                # RECORDED BEFORE the `add`, not after: the file is on disk the moment
                # `write_text` returns, so it is this call's litter from that moment on. An
                # `add` that fails with the append below it would leave the rollback's one
                # authority silent about a file only this call could have created — the
                # record of a page that was never archived, sitting untracked at the live
                # path the move did not vacate.
                written.append(path)
                self._run(repo, "add", "--", *self._literal([path]))
            # `git rm` / `git mv` / the `add` above stage exactly their own paths, as
            # `commit_patch` does; a bare `add -A` would additionally sweep in whatever else
            # happens to be dirty, which this verb has no business committing. Stage nothing
            # further and commit exactly these.
            status = self._run(repo, "status", "--porcelain").stdout.strip()
            if status:
                self._run(repo, *_GIT_ID, "commit", "-q", "-m", message)
        except Exception as exc:
            left_dirty = self._rollback(repo, performed, created, removed, written)
            if left_dirty is not None:
                # The rollback did not get the tree back. Saying so is the point: an
                # operator told "the move failed" over a repository that is still
                # half-renamed would be reading a clean lie, and the next writer would
                # inherit the mess without a name for it. The original failure rides along
                # as `__cause__`.
                raise CanonicalMoveError(
                    "rollback left the repository dirty", left_dirty
                ) from exc
            raise
        # AFTER the commit, and outside the try, on purpose. The commit is the operation;
        # this is housekeeping over what the commit left on disk, and a failure to remove an
        # empty folder must never roll back a move that landed.
        self._prune_empty_parents(repo, moves)
        sha = self._run(repo, "rev-parse", "HEAD").stdout.strip()
        return SnapshotRef(ref=sha)

    @staticmethod
    def _prune_empty_parents(repo: Path, moves: Sequence[tuple[str, str]]) -> None:
        """Remove the directories this move drained, from each source path upwards.

        git tracks files, not directories, so the `archive/threads/` an unarchive emptied
        stays on disk as a shell: `git status` is clean, nothing mechanical is affected, and
        the working tree still reads as a library with a `threads` folder under the archive
        that holds nothing. The repository is meant to be readable BY A PERSON — that is the
        whole argument for canonical being a git tree — so a directory that names a subject
        the library no longer keeps there is a small lie in the one layer that is supposed to
        be self-evident.

        This is the only place the adapter removes something it did not create, so it is
        bounded three ways and by nothing softer: it walks up only from paths this call moved
        OUT of; it stops the moment `rmdir` refuses, which is the moment the directory is not
        empty, so a sibling page or anyone's untracked file keeps its folder; and it never
        goes past the repository root, nor touches `.git`. Every failure is swallowed —
        a folder that could not be removed is exactly the state that existed before.
        """
        for from_path, _to_path in moves:
            GitCanonicalStore._prune_upwards(repo, from_path)

    @staticmethod
    def _prune_upwards(repo: Path, rel: str) -> None:
        """Remove the directories that emptying `rel` left empty, upwards, and stop at the
        first that is not.

        The one walk shared by the move's own pruning and the crash recovery's, so both are
        bounded the same way: `rmdir` succeeds only while a directory holds nothing, so a
        sibling page or anybody's untracked file keeps its folder; the walk never passes the
        repository root and never enters `.git`; every failure is swallowed, because a
        directory that could not be removed is exactly the state that existed before.
        """
        directory = (repo / rel).parent
        while (
            directory != repo
            and directory.is_relative_to(repo)
            and directory.name != ".git"
        ):
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent

    @staticmethod
    def _make_parents(repo: Path, target: Path, created: list[Path]) -> None:
        """`mkdir -p` for `target`'s parent, recording the directories that did not exist.

        The record is what makes the cleanup exact. `mkdir(parents=True, exist_ok=True)`
        cannot say afterwards which levels it brought into existence, and a rollback that
        guessed would either leave its own litter behind or remove a directory that was
        already part of the library.
        """
        missing: list[Path] = []
        directory = target.parent
        while (
            directory != repo
            and directory.is_relative_to(repo)
            and not directory.exists()
        ):
            missing.append(directory)
            directory = directory.parent
        target.parent.mkdir(parents=True, exist_ok=True)
        created.extend(missing)

    def _dirty_paths(self, repo: Path) -> list[str]:
        """Every path `git status` reports, in its order; empty when the tree is clean.

        Paths rather than a bool because both callers have to NAME what they saw — a
        refusal without the file, or a recovery without the paths it discarded, is a line an
        operator cannot act on.

        FAILS CLOSED. A status read that errors or exits non-zero is not evidence that the
        tree is clean; it is evidence that this call cannot tell. Reporting clean there
        would let a write run against a repository whose state is unknown, which is the one
        thing this read exists to prevent — so it raises instead, with no path to name.

        `--porcelain -z` and not `--porcelain`: the NUL-separated form is the only one that
        is unambiguous. The default form QUOTES and C-escapes any path with a space, a
        quote or a non-ASCII byte in it, and writes a rename as `old -> new` in the same
        field, so a library with a Chinese page title parses back as something no filesystem
        ever held. In `-z` every path is verbatim, and a rename's source rides as its own
        NUL-terminated field after the destination — and BOTH are reported, because a
        rename's source is a path the tree is dirty at (staged-deleted) exactly as its
        destination is (`_parse_status`).

        `--untracked-files=all` and `--ignored=no` are passed rather than left to default,
        and both are about what this read is FOR. `status.showUntrackedFiles=no`, set in the
        repository's own config or in the operator's `~/.gitconfig`, would hide every
        untracked file from this read — and hide it only HERE: an `add` over those same paths
        stages them regardless, so a repository configured that way would let a writer commit
        residue this read had just declared absent. Asking for `all` also stops git
        COLLAPSING a wholly untracked directory to `notes/`: every file under it is named
        individually, so the footprint comparison weighs real paths instead of a directory
        shorthand it would have to expand for itself. `--ignored=no` is already the default,
        pinned for the mirror-image reason — no config may turn this read into a listing of
        everything `.gitignore` covers, which would refuse every write in a library that has
        one.
        """
        try:
            proc = self._run(
                repo,
                "status",
                "--porcelain",
                "-z",
                "--untracked-files=all",
                "--ignored=no",
            )
        except Exception as exc:  # noqa: BLE001 — see the docstring
            raise CanonicalMoveError("could not read repository status", "") from exc
        return self._parse_status(proc.stdout)

    @staticmethod
    def _parse_status(stdout: str) -> list[str]:
        """The one parser for `git status --porcelain -z`.

        EVERY entry counts — staged, unstaged and untracked alike — because the question the
        recovery asks is not "what did a writer stage?" but "is anything dirty OUTSIDE what
        the claim recorded?", and a path is a path whichever column it is dirty in.

        `-z` is the whole reason this is a function: the default form quotes and C-escapes
        any path with a space, a quote or a non-ASCII byte, and writes a rename as
        `old -> new` inside one field, so a library with a Chinese page title parses back as
        something no filesystem ever held. Here every path is verbatim, and a rename's source
        rides as its own NUL-terminated field after the destination.

        **A RENAME OR COPY REPORTS BOTH HALVES, and that is a safety property rather than
        completeness for its own sake.** `R  <dest>\\0<src>\\0` is ONE entry naming TWO paths,
        and the source half is a path this tree is dirty at just as much as the destination:
        it is staged-DELETED there. Reading only the destination made a foreign staged rename
        whose destination happened to land inside a dead writer's footprint read as fully
        covered — the recovery would restore the destination, leave the source staged-deleted,
        and the next commit would carry that deletion under an unrelated message, since `git
        commit` commits the whole index however narrowly the staging was scoped. Both halves, so a rename with either end outside the footprint is
        an outsider and the whole call refuses (`_begin_mutation`). The destination is
        emitted FIRST, because it is the path on disk an operator goes and looks at, and
        `_first_dirty_path` reports it.
        """
        paths: list[str] = []
        fields = stdout.split("\0")
        index = 0
        while index < len(fields):
            entry = fields[index]
            index += 1
            if not entry:
                continue
            code, path = entry[:2], entry[3:]
            source: str | None = None
            if "R" in code or "C" in code:
                # `XY <new>\0<old>\0`: the next field is the source, and it counts.
                if index < len(fields):
                    source = fields[index]
                index += 1
            if path:
                paths.append(path)
            if source:
                paths.append(source)
        return paths

    def _first_dirty_path(self, repo: Path) -> str | None:
        """The first path `git status` reports, or None when the tree is clean."""
        paths = self._dirty_paths(repo)
        return paths[0] if paths else None

    # --- the in-flight marker ------------------------------------------------
    #
    # The whole of the licence this adapter has over uncommitted work. See the module
    # docstring: the lock proves no other process OF THIS FRAMEWORK is mid-sequence, and
    # says nothing about a text editor; the marker is what turns "the tree is dirty" into
    # "*I* left it dirty".

    @staticmethod
    def _marker_path(repo: Path) -> Path:
        return repo / ".git" / _INFLIGHT_NAME

    def _read_marker(self, repo: Path) -> dict[str, object] | None:
        """The in-flight marker, or None when there is none.

        A marker that will not parse still COUNTS as present, and is answered with an empty
        mapping rather than None: the file's existence is the claim ("this adapter was
        writing here"), and its contents are only the operator's half of it. The two are no
        longer a difference in what may be DESTROYED — an unreadable claim is not proof of a
        death (`_claimant_is_gone`), so a dirty tree under one is refused exactly as an
        unclaimed one is. They differ in what the refusal can TELL somebody: present-but-
        unreadable is a fact about this adapter's own file, and the restore reads the claim's
        `operation` to decide which files it may delete at all.

        The ONE content that is read as absence is `{"released": true}`, which is what
        `_clear_marker` degrades a claim to when it cannot unlink the file. A released marker
        is a claim its own writer gave up in an orderly way, on the record — the opposite of
        a claim a death left standing — so every reader here (`_begin_mutation`, the
        restore) must see exactly what a successful unlink would have shown it: nothing.
        """
        path = self._marker_path(repo)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return None if parsed.get("released") is True else parsed

    @staticmethod
    def _claimant_is_gone(marker: Mapping[str, object] | None) -> bool:
        """POSITIVE PROOF that the claimant died — the only thing that licenses a recovery.

        True ONLY when all three hold: the marker parsed as an object, it carries an integer
        `pid > 0`, and that pid answers `kill(pid, 0)` with `ProcessLookupError`. Everything
        else is False — content that would not parse, a truncated or non-object marker, a
        missing or non-integer pid, a pid ≤ 0, `PermissionError` (the process exists and
        belongs to somebody else), any other `OSError` out of the probe, and of course a pid
        that is simply alive.

        THE QUESTION IS NOT "IS IT ALIVE?" BUT "IS IT PROVABLY DEAD?", and the difference is
        the whole of this function. The first question answers every ambiguity with "not
        alive", and what stands behind that answer is `reset --hard` + `clean -fd` over a
        working tree: a marker truncated by a crash, a marker caught half-written, a pid the
        OS would not let this process probe — under the first question each of them read as a
        death and licensed a deletion. The second question fails the other way, in the
        refusing direction, on every one of them.

        SO A GENUINELY DEAD WRITER WHOSE MARKER GOT CORRUPTED REFUSES TOO, and that is the
        intended direction and not a gap in it: what is on disk then is a mess nobody can
        prove the shape of, which is exactly the state no automatic recovery is entitled to
        interpret. An operator looks at it, and the cost is one `canonical_dirty` plus a `git
        status`; the cost of guessing the other way is somebody's afternoon.

        PID REUSE can likewise only push this toward refusing: a reused number makes a dead
        writer look alive. The flock already excludes a second live adapter process on this
        repository, so a live pid is either ourselves — a `_clear_marker` that could neither
        unlink nor replace the file — or an unrelated process holding the number.
        """
        pid = (marker or {}).get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            # `PermissionError` (the process is somebody else's) and every other errno alike:
            # not an answer, therefore not proof. Only `ProcessLookupError` is.
            return False
        return False

    @staticmethod
    def _claim_reading(marker: Mapping[str, object] | None) -> str:
        """What the claim itself says — WHAT COULD AND COULD NOT BE READ OUT OF IT.

        The refusal's message half of `_claimant_is_gone`, and it reads the marker ONLY: it
        never probes, so the sentence an operator gets can never disagree with the verdict
        that was already reached (a pid that died between two probes would otherwise be
        described as gone in the message of a refusal that happened because it was not).
        """
        if marker is None:
            return "there is no claim left to read"
        if not marker:
            return "its content could not be read at all — unreadable, truncated, or not JSON"
        pid = marker.get("pid")
        if pid is None:
            return "it names no pid, so there is no process to ask about"
        if isinstance(pid, bool) or not isinstance(pid, int):
            return f"its pid is not an integer ({pid!r})"
        if pid <= 0:
            return f"its pid is {pid}, which names no process"
        return (
            f"it names pid {pid}, and `kill(pid, 0)` did not answer that that process is gone"
        )

    @staticmethod
    def _is_claimable_path(item: object) -> bool:
        """Is one recorded string a path this adapter may act on AT ALL?

        The claim is a JSON file on disk, and everything downstream of it treats its strings
        as two dangerous things at once: LIVE GIT PATHSPECS (`reset`/`checkout`/`rm --`) and
        FILESYSTEM JOINS (`repo / rel`, then `unlink`). Neither reading is safe for an
        arbitrary string, and the file is not this process's own — a crash wrote it, an
        editor may have touched it, a filesystem may have half-written it. So the shape is
        checked at the READ, once, rather than trusted at each of the four places it is used.

        A claimable path is: a non-empty `str`; RELATIVE (no leading `/`); POSIX-spelled (no
        backslash, which is a legal byte in a POSIX filename and would make the two readings
        disagree on a path that is one segment to git and two to a Windows-ish reader); free
        of NUL and of every other control byte, so it can never be split or lost inside the
        NUL-separated forms this adapter parses; and made only of segments that are neither
        empty nor `.` nor `..`. `..` is the one that matters most — `repo / "../x"` resolves
        OUTSIDE the repository, and an unlink there reaches a path no claim could ever have
        licensed.

        REJECTING THE TRAILING SLASH is deliberate and does a second job. `notes/` is not a
        path any writer of this adapter records — every footprint is built from file paths
        (a patch's map, a move's pairs, a meta write's one path) — it is `git status`'s
        COLLAPSED spelling for a wholly untracked directory. Admitting it would let a claim
        cover a directory wholesale, whatever somebody has since put in it, which is the
        licence `_within_footprint` exists to withhold.

        **AND NO SEGMENT MAY BE `.git`, IN ANY CASING.** `.git` is not part of the library:
        it is the repository's own machinery, and the claim itself lives inside it. A claim
        naming `.git/config`, `.git/HEAD` or `work/.git/x` would hand the recovery a licence
        to `checkout` over, or UNLINK, the index, a hook, a ref — or the lock file another
        writer is blocked on — none of which any writer of this adapter ever records in a
        footprint, all of which a corrupted or hostile claim could name. The comparison is
        case-folded because a case-insensitive filesystem (macOS, Windows) resolves `.GIT/`
        and `.Git/` to the same directory git uses, so a byte-exact check would refuse the
        spelling and admit the path. One such segment makes the whole list unreadable
        (`_claim_list`), which is to say: refuse, and let an operator look.
        """
        if not isinstance(item, str) or not item:
            return False
        if item.startswith("/") or "\\" in item:
            return False
        if any(ord(char) < 32 or ord(char) == 127 for char in item):
            return False
        parts = item.split("/")
        if any(part.casefold() == ".git" for part in parts):
            return False
        return all(part and part not in (".", "..") for part in parts)

    @staticmethod
    def _claim_list(
        marker: Mapping[str, object] | None, key: str
    ) -> tuple[str, ...] | None:
        """A claim's recorded path list — `paths` (a footprint) or `pre_existing` — or None.

        **None and `()` ARE DIFFERENT ANSWERS, and the difference is the whole licence.** `()`
        is a claim that recorded a list and the list was empty: a ref-only operation that
        touches no working-tree path, a restore into a directory that held nothing. None is a
        claim that recorded NO list at all — an old-shape marker, or one whose list is not a
        list of strings — and it covers nothing, because a list nobody can read is not a
        statement about what a writer was touching. Reading it as "everything" is the
        assumption this whole mechanism exists to remove, so every caller refuses on it.

        **AND A LIST HOLDING ONE UNCLAIMABLE STRING READS AS None WHOLE**, not as the rest of
        itself. Every string here is about to be used as a live git pathspec and as a
        filesystem join (`_is_claimable_path`), so `../x`, `/etc/x`, `a/../../b`, `notes/`,
        an empty string or anything carrying a control byte is not a path this adapter may
        act on — and a claim carrying one is a claim whose shape nobody can vouch for. Taking
        the readable remainder would be this adapter deciding which half of a corrupted claim
        to believe, which is the same move it refuses everywhere else: the whole list is
        unreadable, so it covers nothing, so the caller refuses and an operator looks.
        """
        raw = (marker or {}).get(key)
        if not isinstance(raw, list) or not all(
            GitCanonicalStore._is_claimable_path(item) for item in raw
        ):
            return None
        return tuple(raw)

    def _write_marker(
        self,
        repo: Path,
        operation: str,
        *,
        paths: Sequence[str],
        pre_existing: Sequence[str] | None = None,
    ) -> None:
        """Claim the tree for `operation` AND ITS FOOTPRINT, before the first mutating command.

        **`paths` IS THE FOOTPRINT: every repo-relative path this operation may touch.** It is
        required, and required as a keyword, because a claim without one covers nothing and a
        claim that silently defaulted to "everything" is precisely the bug this argument
        removes. Every caller knows its paths before it writes any of them — the patch's file
        map, the move's pairs and its writes and removals, the manifest's one path — and the
        ref-only operations (`branch_commit`, `delete_branch`, `tag`, `init_repository`) pass
        `()`, because they touch no working-tree path at all. The recovery at the next
        writer's entry then runs ONLY where every dirty path is inside this list, and touches
        ONLY this list (`_begin_mutation`, `_recover_footprint`).

        `pre_existing` is the restore's inverse of it, and only the restore passes it: a
        restore cannot enumerate what a `git clone` will materialize, so its claim records
        what the target held BEFORE it started — the files it did NOT create, and which a
        later recovery may therefore never delete.

        A FAILURE HERE STOPS THE WRITE (`CanonicalMarkerError`). The marker is the whole
        proof that residue under this repository is this adapter's own (module docstring), so
        a mutation that could not write it would, on a crash, leave a dirty tree that reads
        as somebody else's work: unrecoverable by the next `_begin_mutation` and refused by
        it (`CanonicalDirtyError`) until a person intervenes. Refusing now costs a write that
        was about to fail anyway — `.git/` is where the commit is going.

        AND IT IS CALLED FIRST, before the tree is read and before any recovery is weighed
        (`_mutation`, `_restore_repository`). Landing this file is what proves the filesystem
        takes a claim at all, and failing at that instant is a refusal that has touched
        nothing — which is what keeps a repository where clears cannot land from ever
        reaching the branch that deletes.

        Best effort about the CONTENT and never about the file: the operation, the pid and
        the instant are what an operator reads out of a recovery's warning line, and an
        empty marker still proves authorship, which is the only thing the entry check asks of
        it. So the body is written unconditionally and the FILE is what must land.
        """
        body: dict[str, object] = {
            "operation": operation,
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            # Sorted and de-duplicated, so the claim reads the same however the caller built
            # it and an operator meets a list rather than a trace.
            "paths": sorted({str(item) for item in paths}),
        }
        if pre_existing is not None:
            body["pre_existing"] = sorted({str(item) for item in pre_existing})
        path = self._marker_path(repo)
        try:
            path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            _log.error(
                "canonical %s: could not write the in-flight marker at %s (%s); "
                "nothing was written",
                operation,
                path,
                exc,
            )
            raise CanonicalMarkerError(str(path)) from exc

    def _clear_marker(self, repo: Path, operation: str | None = None) -> None:
        """Release the claim. Called on EVERY exit of a claimed body — success or refusal.

        A failure LOGS and raises nothing, and the asymmetry with `_write_marker` is the
        point: by here the body is over, so failing the call would report a write that
        succeeded as one that did not.

        **A CLEAR THAT CANNOT UNLINK DEGRADES THE CLAIM RATHER THAN LEAVING IT WHOLE.** The
        residue of a swallowed failure is not harmless: a whole claim standing over a tree
        somebody later edits is what used to authorize the next writer's `reset --hard` +
        `clean -fd` over their work, which is the exact deletion the marker exists to
        prevent. So
        the unlink has a second half — overwrite the file with `{"released": true}`, which
        `_read_marker` and therefore `_begin_mutation` and the restore all read as ABSENT.
        Unlink and rewrite fail independently (a read-only directory defeats the first, a
        read-only file the second), so trying both is a real second chance and not a retry.

        **THE REWRITE IS ATOMIC** — a temporary file in the same directory, then `os.replace`
        — and that is a safety property, not tidiness. A release written in place can be
        interrupted (a kill, a full disk) partway through, and what it leaves is a TRUNCATED
        marker: unparseable, therefore not proof of anything, therefore refused by the next
        writer for as long as it stands. Under a recovery that asked "is it alive?" it was
        worse still — the half-written release read as a dead claimant and licensed a
        deletion. Rename or nothing means the file on disk is only ever the whole old claim
        or the whole release.

        WHEN BOTH FAIL, a whole claim survives an orderly exit — and that is now an
        OPERATIONAL WARNING rather than a hazard. It used to be the last trap in this
        mechanism: once this process exits, the surviving claim's pid reads as dead, so a
        human's or an agent's later edit under the same repository would arrive at
        `_begin_mutation` looking like positive proof of a death. That is closed at the other
        end, and mechanically: the claim records the FOOTPRINT of the body that wrote it, and
        the recovery reaches nothing outside it — a later edit is somewhere else by
        definition, so it is refused, not cleaned. So a surviving claim can no longer license
        a deletion over anybody's work; what it costs is one stale file in `.git/`. It is still logged at ERROR, naming the repository and the
        operation, because a `.git/` this process could neither write nor rewrite is a fault
        an operator should see — and while this process is alive the next mutation refuses on
        the pid check anyway (`_begin_mutation` reads a live pid, ours included, as no proof).
        """
        path = self._marker_path(repo)
        named = operation or "an unnamed operation"
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as unlink_exc:
            unlink_error = unlink_exc
        # Written beside the marker and renamed onto it: `os.replace` is atomic within a
        # directory, so no reader — and no crash — can ever meet a half-written release.
        staging = path.with_name(f"{path.name}.release-{uuid.uuid4().hex}")
        try:
            staging.write_text(
                json.dumps(
                    {
                        "released": True,
                        "operation": named,
                        "pid": os.getpid(),
                        "released_at": datetime.now(timezone.utc).isoformat(),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            os.replace(staging, path)
        except OSError as rewrite_exc:
            with contextlib.suppress(OSError):
                staging.unlink(missing_ok=True)
            _log.error(
                "canonical %s: could not clear the in-flight marker at %s under %s — the "
                "unlink failed (%s) AND the release rewrite failed (%s). The body itself is "
                "over; what is left is a WHOLE claim standing over this repository. No "
                "recovery can run on it alone — the next writer also requires every dirty "
                "path to be inside the FOOTPRINT this claim recorded, and nobody else's work "
                "is on those paths — so uncommitted work under "
                "%s is not at risk; what is at risk is a `.git/` this process could neither "
                "write nor rewrite. Remove the file by hand and look at the directory.",
                named,
                path,
                repo,
                unlink_error,
                rewrite_exc,
                repo,
            )
        else:
            _log.warning(
                "canonical %s: could not unlink the in-flight marker at %s (%s); it was "
                "rewritten as released, which every reader treats as no claim at all",
                named,
                path,
                unlink_error,
            )

    @contextlib.contextmanager
    def _claimed(
        self,
        repo: Path,
        operation: str,
        *,
        paths: Sequence[str],
        pre_existing: Sequence[str] | None = None,
    ) -> Iterator[None]:
        """Hold the in-flight claim for the whole of a body, and release it on EVERY exit.

        The lower half of `_mutation`, and the one the two sequences that cannot read a `git
        status` yet use directly: `_repo`'s initialization and `_restore_repository`.

        The `finally` is the mechanism, not tidiness. A claim released only on success would
        outlive every orderly refusal, and a marker that outlives a live process no longer
        means "a process died here" — it means "something went wrong here once", which is not
        a licence to discard anything. The next writer would read a person's later edit as
        this adapter's own residue and `reset --hard` it away. Released on the way out, the
        marker survives exactly one event: process death.

        `paths` and `pre_existing` are the claim's footprint and the restore's inverse of one;
        see `_write_marker`. Both sequences that use this directly record an EMPTY footprint —
        initialization touches only `.git/`, and the restore states what it must NOT delete
        instead, because it cannot enumerate what its own clone will create.
        """
        self._write_marker(repo, operation, paths=paths, pre_existing=pre_existing)
        try:
            yield
        finally:
            self._clear_marker(repo, operation)

    @contextlib.contextmanager
    def _mutation(
        self, repo: Path, operation: str, *, paths: Sequence[str]
    ) -> Iterator[None]:
        """Claim the tree, decide the entry branches, release the claim on every exit.

        THE ORDER IS THE MECHANISM: read the PREVIOUS claim → write OUR OWN → only then read
        the tree and decide what may happen to it (`_begin_mutation`).

        **The claim is written before anything is read, because writing it is the proof that
        this filesystem will take a claim at all.** `_write_marker` raises
        `CanonicalMarkerError` when `.git/` will not take the file, and at that instant
        nothing has been touched: no status has been read, no recovery considered, nothing
        deleted. So on a filesystem where the claim cannot be written, NO MUTATION PROCEEDS —
        which is what closes the last way the destructive branch could be reached without
        anybody's death. A `_clear_marker` that could neither unlink nor replace its file
        leaves a whole claim standing; if that same repository were then writable enough to
        run a mutation but not to write a marker, the old order (decide first, claim last)
        would have let the surviving claim be weighed. Now the next mutation dies before it
        reads the tree.

        **The decision is made from the marker we READ, never from the one we just wrote.**
        Our own claim is fresh and names a live process — ourselves — so weighing it would be
        a call asking itself for permission. `previous` is passed down and is the only claim
        `_begin_mutation` ever looks at.

        Our claim replaces whatever stood there, and that is sound under the lock: no other
        live body of this adapter can be inside a mutation on this repository, so a claim
        still standing here belongs to a process that is gone or to a body of ours that is
        already over. The `finally` then releases ours on EVERY exit — success, refusal, or
        any exception — so a refusal never leaves a claim behind to license the next call.

        Two consequences worth stating, both in the refusing direction. A recovery that could
        not clean the tree (`crash residue could not be cleaned`) now leaves the residue with
        NO claim beside it, so the next call refuses (`canonical_dirty`) instead of retrying
        the recovery over a mess git would not undo. And `move_documents` raising `rollback
        left the repository dirty` releases the claim like every other exit, for the same
        reason and to the same effect.
        """
        # Read first, then claim: `_begin_mutation` must weigh the claim that was standing
        # here, and one line below there is only ours.
        previous = self._read_marker(repo)
        self._write_marker(repo, operation, paths=paths)
        try:
            self._begin_mutation(repo, operation, previous)
            yield
        finally:
            self._clear_marker(repo, operation)

    def _begin_mutation(
        self, repo: Path, operation: str, previous: Mapping[str, object] | None
    ) -> None:
        """Establish a clean tree. Runs UNDER the lock and UNDER THIS CALL'S OWN CLAIM.

        Called from `_mutation`, which has already read `previous` — the claim that was
        standing here — and written this call's own over it, so that a filesystem which
        cannot take a claim stops the call before anything is read or destroyed. `previous`
        is the ONLY claim weighed below; the marker now on disk is ours and proves nothing.

        This is the one place the entry branches of the module docstring are decided:

        - **clean** — nothing to weigh: any claim that was left over is stale (a previous
          call that failed after its rollback got the tree back) and has already been
          replaced by ours;
        - **dirty, claimed BY A CLAIMANT THAT IS PROVABLY GONE, AND EVERY DIRTY PATH INSIDE
          THAT CLAIM'S FOOTPRINT** — this adapter's own dead writer, named by the claim and
          bounded by the list it recorded before it wrote anything: the residue is LOGGED at
          WARNING and put back PATH BY PATH (`_recover_footprint`), then the footprint is
          re-read, and one still dirty raises rather than reporting a clean lie;
        - **dirty and claimed by a provably gone claimant, BUT SOMETHING IS DIRTY OUTSIDE
          THE FOOTPRINT** — refused (below), naming the outsiders;
        - **dirty and claimed, BUT THE DEATH IS NOT PROVEN** — `_claimant_is_gone` says so:
          the claimant is still running, or the claim cannot be read as naming a death at all
          (truncated, no pid, a nonsensical pid, a pid the OS would not let us probe). The
          recovery's whole premise is a death, and this is that premise unproven, so it is
          REFUSED, naming the paths and — in the message only — the operation and what could
          and could not be read out of the claim. A dead writer whose marker was corrupted
          refuses here too: see `_claimant_is_gone` on why that is the direction to fail in;
        - **dirty and unclaimed** — somebody else's work, and not this adapter's to touch:
          `CanonicalDirtyError`, naming every path, having written nothing.

        **THE CLAIM ANSWERS *WHO DIED* AND *WHAT THEY WERE TOUCHING*, AND THE RECOVERY NEVER
        REACHES OUTSIDE THE SECOND ANSWER.** A pid alone identifies a writer, not their work,
        and a repository is not one writer's: a dead writer's staged residue and a person's
        later untracked file land in the same `git status`, and a whole-tree `reset --hard` +
        `clean -fd` took both. Every mutating body here KNOWS ITS PATHS BEFORE IT WRITES ANY
        OF THEM, so the claim records them (`_write_marker(..., paths=...)`), and this entry
        is bounded by that list twice: it recovers only when every dirty path — staged,
        unstaged and untracked alike — is inside the footprint, and `_recover_footprint` then
        touches only the footprint. A ref-only operation records an EMPTY footprint, so its
        claim covers nothing and licenses nothing; a claim with no readable list at all
        (`_claim_list` answers None) likewise covers nothing, because a list nobody can read
        is not a statement about what a writer was touching.

        That is also what closes the last way a claim could be a licence without a death. A
        `_clear_marker` whose unlink AND atomic replace BOTH fail leaves a whole claim standing
        after an ORDERLY exit, and once that process exits its pid reads as dead — so a
        human's or an agent's later edit under that repository arrives here holding what looks
        like positive proof of a death. It is refused all the same, because that edit is not in
        the dead call's footprint. And a MIXED tree — the dead writer's own residue plus
        somebody's later file — is refused whole rather than cleaned in part: this is not a
        filter over the residue, it is a precondition on all of it.

        THE ACCEPTED RESIDUAL, stated rather than hidden: a footprint that did not name
        everything its writer touched leaves residue OUTSIDE itself, which is REFUSED and not
        cleaned — one `canonical_dirty` an operator resolves with a `git status`, never a
        deletion. The other direction has no window at all: the claim, footprint and all, is
        written before the work, so there is no instant in which this adapter has written a
        file it did not already declare.

        Recovering in the bounded case is not a convenience, it is the only safe answer.
        Every write here stages under a pathspec of its own paths, but `git commit` commits
        the whole INDEX: STAGED residue left in place lands inside the next commit whatever it
        is, so a crashed archive's renames would ride into an unrelated compile, under its
        message and attributed to its skill version.

        **ANY operation's claim licenses the recovery here, and that is sound — while the
        restore's own destructive branch requires its own.** The difference is what the two
        are allowed to destroy. Here the recovery takes back UNCOMMITTED CHANGES ON THE
        CLAIM'S OWN PATHS in a repository this adapter is committing to: every operation of
        this adapter writes into that same repository, so whichever one left the residue, the
        residue is that operation's, and putting its own paths back reaches nothing a commit
        has accepted. `_restore_repository` is the other case: its marked branch DELETES FILES
        IT DID NOT WRITE, and only one operation ever puts a half-materialized checkout there.
        A crashed `init_repository` (or any other operation) claiming a directory that also
        holds somebody's files would, under a same-any-claim rule, authorize wiping files that
        predate the claim entirely. So restore names the operation it will destroy for, and
        refuses every other.
        """
        residue = self._dirty_paths(repo)
        if not residue:
            return
        if previous is None:
            # NOT OURS. The premise this branch replaces — "only this adapter writes" —
            # was never true of a repository sitting in a working directory, and under
            # it every one of these paths would now be gone.
            raise CanonicalDirtyError(residue)
        if not self._claimant_is_gone(previous):
            # CLAIMED, BUT NO DEATH IS PROVEN. The recovery below says one thing — "the
            # process writing here died mid-write" — and it may only run when that is
            # PROVED: an integer pid above zero that answers `kill(pid, 0)` with
            # `ProcessLookupError`. A live pid refutes it outright; an unreadable claim, a
            # missing or nonsensical pid, a probe the OS refused, none of them establish it.
            # Everything short of the proof lands here and refuses, because what stands
            # behind the other answer is a deletion over these paths — most likely a human's
            # work, since the flock excludes a second live adapter process on this repository.
            raise CanonicalDirtyError(
                residue,
                claimed_by=str(previous.get("operation") or "") or None,
                unproven=self._claim_reading(previous),
            )
        # A DEATH IS PROVEN. What the claim ALSO has to say is what that writer was touching,
        # and every dirty path has to be inside it. A claim with no readable footprint covers
        # nothing, so all of the residue is outside it.
        footprint = self._claim_list(previous, "paths")
        outsiders = (
            list(residue)
            if footprint is None
            else [
                path
                for path in residue
                if not self._within_footprint(repo, path, footprint)
            ]
        )
        if outsiders:
            # THE DEAD WRITER WAS NOT TOUCHING THIS. A tree can hold a dead writer's residue
            # AND somebody's later work at once — a hand edit, an agent's untracked file, a
            # `git add` made after the death — and the whole-tree recovery this replaces took
            # them together. Refused WHOLE rather than cleaned in part: the claim is a
            # precondition on the state of the tree, not a filter over it, and a recovery
            # that ran anyway would be deciding on its own which half of a mess it made.
            raise CanonicalDirtyError(
                residue,
                claimed_by=str(previous.get("operation") or "") or None,
                outside=outsiders,
                covered=footprint,
            )
        _log.warning(
            "canonical %s: discarding crash residue under %s left by %s (pid %s, "
            "started %s) — %d path(s): %s; the claim's footprint was: %s",
            operation,
            repo,
            previous.get("operation") or "an unnamed operation",
            previous.get("pid") or "?",
            previous.get("started_at") or "?",
            len(residue),
            ", ".join(residue),
            ", ".join(footprint or ()) or "(empty)",
        )
        self._recover_footprint(repo, footprint or ())
        left = [
            path
            for path in self._dirty_paths(repo)
            if self._within_footprint(repo, path, footprint or ())
        ]
        if left:
            raise CanonicalMoveError("crash residue could not be cleaned", left[0])

    def _within_footprint(
        self, repo: Path, path: str, footprint: Sequence[str]
    ) -> bool:
        """Is one `git status` path covered by the claim's recorded footprint?

        An exact match, plus the one entry git reports that is not a file: a WHOLLY UNTRACKED
        DIRECTORY, which `--porcelain` collapses to `notes/` rather than listing what is in
        it. That entry counts as covered only when EVERY entry actually under it is named in
        the footprint — the collapsed form must never be read as a licence over whatever else
        somebody happens to have put in there. A directory that cannot be listed, or that
        holds one entry the claim never named, is OUTSIDE, and the whole recovery refuses.

        **THE EXPANSION COUNTS EVERY ENTRY, NOT EVERY *FILE*.** `is_file()` follows symlinks
        and answers False for three things a directory can hold: a symlink to a directory, a
        BROKEN symlink, and a device or fifo. Each of them is somebody's, each survives a
        recovery that never names it, and under a file-only walk `notes/` holding one symlink
        pointing at `/etc` read as fully covered by a footprint that named only the ordinary
        files beside it. So the walk is `os.scandir`, it descends only into REAL directories
        (a symlinked directory is an entry to be named, never a door to walk through), and
        every non-directory entry it meets — link, broken link, socket and all — must be in
        the footprint.

        The collapsed spelling itself can never be the thing that covers: `notes/` is not a
        path any writer of this adapter records, and `_is_claimable_path` refuses it at the
        read, so a claim carrying one is unreadable whole rather than a licence over a
        directory. The exact match above therefore only ever matches a real file path.

        BELT AND BRACES, as of `_dirty_paths` asking for `--untracked-files=all`: the primary
        reader now gets every untracked file named individually and hands this function no
        collapsed entry at all. The expansion stays because the collapsed spelling is a
        property of `git status` rather than of one call site — another producer (a different
        flag set, an older git, a caller that reads status for itself) can still emit
        `notes/`, and the safe reading of one belongs with the comparison rather than with
        whoever happened to ask.
        """
        if path in footprint:
            return True
        if not path.endswith("/"):
            return False
        base = repo / path.rstrip("/")
        if base.is_symlink() or not base.is_dir():
            return False
        named = set(footprint)
        pending = [base]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    children = list(entries)
            except OSError:
                # A directory this process cannot read cannot be accounted for, and an
                # unaccountable directory is outside every footprint.
                return False
            for entry in children:
                child = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(child)
                    continue
                if str(child.relative_to(repo)) not in named:
                    return False
        return True

    def _recover_footprint(self, repo: Path, footprint: Sequence[str]) -> None:
        """Put the dead writer's OWN paths back, and touch nothing else.

        This replaces a whole-tree `git reset --hard HEAD` + `git clean -fd`, which was the
        last unbounded deletion in this adapter: it took the dead writer's residue and, with
        it, every uncommitted edit and every untracked file that happened to share the
        repository. What a claim licenses is exactly the paths it recorded, so exactly those
        run — `reset` and `checkout` under a PATHSPEC of them, and an unlink of the ones the
        dead writer created (they are not in HEAD, so there is nothing to check out over
        them), followed by the directories that leaves empty. No `--hard`, no `clean`, and no
        bare `reset HEAD`, each of which is repository-wide by definition.

        The caller has already established that nothing outside this list is dirty, so the
        scoping is not a second line of defence — it is the same rule applied twice, once to
        decide and once to act, which is what keeps the two from drifting apart.

        Before the first commit there is no HEAD to restore from, so those paths are taken
        out of the index instead and the files themselves removed: that is the whole of what
        a crashed initial `commit_patch` can have left. `.git/` is never reachable from here
        — every path in a footprint is a working-tree path a caller declared.

        **EVERY PATH REACHES GIT AS `:(literal)`, AND THE FILESYSTEM ONLY THROUGH
        `_inside_repo`.** A footprint string is read off a JSON file this process did not
        write, and git's default pathspec is a GLOB: `work/a[1].md` — a perfectly ordinary
        page name — would be read as a character class, match `work/a1.md` instead, and this
        recovery would check out a file the dead writer never touched while failing to
        restore the one it did. `:(literal)` is the pathspec magic that turns each string
        back into the one path it names, and it is preferred over
        `--pathspec-from-file --pathspec-file-nul` (which would say the same thing) for a
        plain reason: it needs no temporary file, so there is no second piece of state to
        write, clean up, or fail to clean up in the middle of a crash recovery.
        `_is_claimable_path` has already refused anything that could not be a repo-relative
        path at all, so the two checks stack: the claim cannot NAME an escape, and the act
        cannot PERFORM one.
        """
        paths = list(dict.fromkeys(footprint))
        if not paths:
            return
        if self._has_head(repo):
            # Unstage exactly these; a pathspec that matches nothing is a no-op, so a path
            # the dead writer never got to is simply skipped.
            self._run(repo, "reset", "-q", "HEAD", "--", *self._literal(paths))
            in_head = {path for path in paths if self._path_in_head(repo, path)}
            if in_head:
                # Only the ones HEAD actually holds: `checkout HEAD -- <missing>` fails the
                # WHOLE command, so an unfiltered call would restore none of them.
                self._run(
                    repo, "checkout", "-q", "HEAD", "--", *self._literal(sorted(in_head))
                )
            doomed = [path for path in paths if path not in in_head]
        else:
            self._run(
                repo,
                "rm",
                "-rq",
                "--cached",
                "--ignore-unmatch",
                "--",
                *self._literal(paths),
            )
            doomed = paths
        for rel in doomed:
            self._unlink_inside(repo, rel)
            self._prune_upwards(repo, rel)

    @staticmethod
    def _literal(paths: Sequence[str]) -> list[str]:
        """Each path as a pathspec that means ITSELF — `:(literal)<path>`.

        git's default pathspec is a glob, so `work/a[1].md` names a character class and
        `work/*.md` names a family. Neither is ever what these paths mean. They come from a
        document — a patch's file map, an archive proposal, a rollback's record of what it
        just moved, a recovery footprint, the skill manifest's name — so each names ONE
        page, and a page named `a[1].md` is an ordinary page. Spelled as a default pathspec
        it would instead match its neighbour `a1.md`: the act would be wider than the
        decision, reaching a path nothing in the library ever named. A pattern from a user
        would be a different thing and would be spelled differently; nothing here is one.

        Applied at every place such a path reaches git AS A PATHSPEC — `add`, `rm`,
        `reset`, `checkout`, `status`. Not at `git mv`, which is not a pathspec verb: it
        reads its two arguments literally already and REFUSES the magic ("bad source").
        """
        return [f":(literal){path}" for path in paths]

    @staticmethod
    def _inside_repo(repo: Path, rel: str) -> Path | None:
        """The filesystem target for a claimed path, or None if it is not honestly inside.

        The last check before an `unlink`, and the one that does not trust the claim. It
        answers with a path ONLY when, after resolving every symlink in it, the target still
        lies under the RESOLVED repository root — so a `..` that slipped through, a claim
        naming a path whose parent directory is a symlink pointing somewhere else, and a
        symlinked repository whose interior is real all get the same honest answer. The
        target itself is resolved WITHOUT following its own last link (`strict=False` on the
        parent, then the name): a symlink the dead writer created is a file to remove, not a
        door to walk through.

        None is not an error here, it is a refusal to act: the caller skips the path, and
        what is left is one dirty path the next status read reports and the next entry
        refuses over — an operator's problem rather than a deletion nobody can account for.
        """
        try:
            root = repo.resolve(strict=False)
            parent = (repo / rel).parent.resolve(strict=False)
        except OSError:
            return None
        target = parent / Path(rel).name
        return target if target.is_relative_to(root) and target != root else None

    def _unlink_inside(self, repo: Path, rel: str) -> None:
        """Remove one claimed path, and only where it is honestly inside the repository."""
        target = self._inside_repo(repo, rel)
        if target is None:
            _log.error(
                "canonical: refusing to remove %r under %s — it does not resolve to a path "
                "inside that repository, so no claim can license removing it",
                rel,
                repo,
            )
            return
        if target.is_symlink() or target.is_file():
            with contextlib.suppress(OSError):
                target.unlink()

    @staticmethod
    def _path_in_head(repo: Path, rel: str) -> bool:
        """Does HEAD hold this path? (`cat-file -e`, so no output and no working-tree read.)"""
        return (
            subprocess.run(
                ["git", "-C", str(repo), "cat-file", "-e", f"HEAD:{rel}"],
                capture_output=True,
            ).returncode
            == 0
        )


    def _rollback(
        self,
        repo: Path,
        performed: Sequence[tuple[str, str]],
        created: Sequence[Path] = (),
        removed: Sequence[str] = (),
        written: Sequence[str] = (),
    ) -> str | None:
        """Undo exactly what this call did, in reverse. Returns a leftover dirty path.

        Three kinds of work, undone in the reverse of the order they were applied — writes,
        then renames, then removals — each with the narrowest inverse that restores it:
        a written file is unlinked and its path unstaged, a rename is renamed back, a
        removal is checked back out of HEAD.

        SCOPED, deliberately, in all three of its parts: `reset --hard` and `clean -fd`
        would put the tree back too, and would take with them any unrelated change or crash
        residue that happened to be in the repository — work this call never touched and has
        no standing to discard. So the rollback moves back only what `performed` says it
        moved, unstages only THOSE paths (`reset HEAD -- <from> <to>`, never a bare
        repository-wide `reset HEAD` that would unstage a concurrent writer's index), and
        removes only the directories `created` says this call brought into existence.

        Per pair the first attempt is the exact inverse, `git mv <to> <from>`, which
        restores both the file and the index in one step. When git refuses that (the
        destination is gone, the index is in a state git will not rename out of) the
        fallback rebuilds the pair from HEAD instead: unstage both sides, check the
        original path back out, and remove the destination if it is still there.

        EVERY DELETION GOES THROUGH `_unlink_inside`, never a bare `(repo / path).unlink()`.
        The paths here are this call's own — `written` and `performed` are what it recorded as
        it went — but "our own" is a claim about provenance and not about where a string
        RESOLVES: a parent directory that is a symlink, or a path with a `..` in it, lands the
        join somewhere outside the library, and this adapter has exactly one place that
        decides that question. Sharing it is what keeps the rollback and the crash recovery
        from drifting into two different answers.

        Individual failures are swallowed — the caller is already raising the reason the
        move failed, and a cleanup's complaint on top of it would replace the diagnosis.
        What is NOT swallowed is the outcome: the final status read decides whether this
        returns None (the tree is back) or the path that is still dirty — and if that read
        itself fails it raises (`_first_dirty_path` fails closed), because "the rollback
        finished and I cannot see the tree" is not an outcome to report as success.
        """
        for path in reversed(list(written)):
            # This call created the file, so the inverse is to remove it and take its path
            # back out of the index. `checkout HEAD -- <path>` would be wrong: HEAD has no
            # such path, and the command would fail rather than undo anything.
            try:
                self._run(repo, "reset", "-q", "HEAD", "--", *self._literal([path]))
            except Exception:  # noqa: BLE001 — see the docstring
                pass
            # `_unlink_inside`, not `(repo / path).unlink()`: same last check as the crash
            # recovery's, so every deletion in this adapter resolves its target and refuses
            # one that does not honestly land inside this repository.
            self._unlink_inside(repo, path)

        for from_path, to_path in reversed(list(performed)):
            (repo / from_path).parent.mkdir(parents=True, exist_ok=True)
            try:
                # Plain paths, as in the forward direction: `git mv` is not a pathspec verb
                # and rejects `:(literal)`.
                self._run(repo, "mv", "--", to_path, from_path)
                continue
            except Exception:  # noqa: BLE001 — see the docstring
                pass
            for args in (
                ("reset", "-q", "HEAD", "--", *self._literal([from_path, to_path])),
                ("checkout", "-q", "HEAD", "--", *self._literal([from_path])),
            ):
                try:
                    self._run(repo, *args)
                except Exception:  # noqa: BLE001 — see the docstring
                    pass
            self._unlink_inside(repo, to_path)

        for path in reversed(list(removed)):
            # `git rm` staged a deletion of a committed file, so HEAD still holds it: one
            # checkout restores both the index entry and the working file.
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            try:
                self._run(repo, "checkout", "-q", "HEAD", "--", *self._literal([path]))
            except Exception:  # noqa: BLE001 — see the docstring
                pass

        # The inverse renames normally leave the index matching HEAD already; only reset
        # when it does not, so a clean index is never rewritten by the cleanup. The reset is
        # bounded by a pathspec of the moved paths: a repository-wide `reset HEAD` would
        # also unstage whatever else is in the index, which after a crash is the only record
        # that another writer got as far as staging.
        moved_paths = [
            *(path for pair in performed for path in pair),
            *removed,
            *written,
        ]
        if moved_paths and self._index_differs(repo):
            try:
                self._run(repo, "reset", "-q", "HEAD", "--", *self._literal(moved_paths))
            except Exception:  # noqa: BLE001 — see the docstring
                pass

        # The directories this call created are untracked and (after the renames came back)
        # empty, so git will not report them and `clean` is not needed to remove them.
        # Deepest first, so a child is gone before its parent is tried; `rmdir` succeeds
        # only while the directory is empty, so one that something else moved into stays.
        for directory in sorted(created, key=lambda path: len(path.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass

        return self._first_dirty_path(repo)

    def _index_differs(self, repo: Path) -> bool:
        if not self._has_head(repo):
            return False
        return (
            subprocess.run(
                ["git", "-C", str(repo), "diff", "--cached", "--quiet", "HEAD"],
                capture_output=True,
            ).returncode
            != 0
        )

    async def move_documents(
        self,
        user_id: UserId,
        moves: Sequence[tuple[str, str]],
        *,
        message: str,
        writes: Mapping[str, str] | None = None,
        removals: Sequence[str] = (),
    ) -> SnapshotRef:
        """Move canonical paths and commit the whole set as one commit (the archive's verb).

        `git mv` per pair, so the blob is never rewritten and `git log --follow` reads
        through the move; the file's bytes, frontmatter, anchors and `doc_id` are the same
        object on the other side. Refuses with `CanonicalMoveError` before touching anything
        when a source is missing or when a destination is taken. A failure AFTER the first
        rename — a later `git mv`, or the commit — undoes exactly the renames this call
        made, in reverse and nothing else, before re-raising; if that does not get the tree
        back, the raised error says so rather than reporting a clean lie. It also refuses
        when the repository's state cannot be READ (`could not read repository status`) —
        an unreadable tree is not a clean one.

        A tree that is dirty when this call takes the lock is RECOVERED only when this
        adapter's in-flight marker is standing beside it, its claimant is provably gone, and
        every dirty path is inside the FOOTPRINT that claim recorded; anything else is REFUSED
        (`CanonicalDirtyError`, naming the paths outside it) (`_begin_mutation`, module
        docstring). The first is its own dead writer's leftovers, which the next commit would
        otherwise carry out of the index under an unrelated message; the second is somebody
        else's work, which is not this adapter's to discard.
        The whole sequence holds the repository lock, so on one host the clean tree the
        preflight saw is the tree the renames are applied to.
        """
        # to_thread: one hop for the whole sequence, so mv → status → commit → rev-parse
        # stays atomic in a single thread (see module docstring).
        return await asyncio.to_thread(
            self._move_documents,
            user_id,
            list(moves),
            message,
            dict(writes or {}),
            list(removals),
        )

    # --- restore (prebuilt library) -------------------------------------------

    def _restore_leftovers(self, repo: Path) -> list[str]:
        """Every ENTRY in the target that is not this adapter's own lock or claim.

        The restore's equivalent of `_dirty_paths`, and it cannot be that read: there is no
        repository yet to ask `git status`. So the tree itself is the evidence — everything
        under the target, relative to it, sorted (directory order is arbitrary and the paths
        are read by a person), minus the two files that live in `.git/` precisely because
        they are not the library's: `pneuma.lock`, which the caller is holding, and
        `pneuma.inflight`, which is the claim this branch is about to read.

        **ENTRY, NOT FILE, and that is the whole point of the walk.** `Path.is_file()` follows
        symlinks and answers False for four things a half-materialized checkout can leave
        behind: a symlink to a directory, a BROKEN symlink, a fifo or socket, and a device
        node. Under a file-only listing each of them was invisible in BOTH readings at once —
        absent from the `pre_existing` a claim records, so a later restore could delete it as
        residue it never made; and absent from the `present_now` that decides, so one that
        appeared in the window between the two could never be noticed. A non-file is
        somebody's exactly as a file is, so every non-directory entry is listed, whatever it
        is, and a symlinked directory is an entry to be NAMED rather than a door to walk
        through (`os.scandir` with `follow_symlinks=False`, as in `_within_footprint`).

        A directory is listed WHEN IT HOLDS NOTHING, and only then. A directory with contents
        is accounted for by those contents — listing it as well would put `.git/` itself in
        every fresh restore's leftovers and refuse the operation this method exists to
        prepare. An EMPTY one is accounted for by nothing else: it is what a graft killed
        between its `mkdir` and its children leaves, and the next graft's `mkdir` collides
        with it (`_graft_collision`). So it is named, which lets the claim keep it when it
        was already here and lets the cleanup remove it when it was not
        (`_clear_restore_target`). A directory that cannot be READ is listed for the
        fail-closed reason the recovery uses everywhere: what cannot be accounted for is
        outside every licence.

        It is read TWICE, for two different questions: once as what this call must decide
        about, and once — before the claim is written — as the `pre_existing` list the claim
        records, which is what a later recovery may never delete (`_restore_repository`).
        """
        keep = {repo / ".git" / _LOCK_NAME, self._marker_path(repo)}
        found: list[str] = []
        pending = [repo]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as scan:
                    children = list(scan)
            except OSError:
                if directory != repo:
                    found.append(str(directory.relative_to(repo)))
                continue
            if not children and directory != repo:
                found.append(str(directory.relative_to(repo)))
                continue
            for entry in children:
                child = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(child)
                    continue
                if child in keep:
                    continue
                found.append(str(child.relative_to(repo)))
        return sorted(found)

    def _clear_restore_target(self, repo: Path, doomed: Sequence[str]) -> None:
        """Remove exactly the listed leftovers, and prune the directories that empties.

        SCOPED, and by the dead restore's own claim: `doomed` is every file the target holds
        that the claim did NOT record as pre-existing — which is to say, everything the dead
        clone materialized itself. What the claim recorded stays, byte for byte, and so does
        anything this list does not name. The whole-directory wipe this replaces could not
        tell the two apart and took both.

        Files, one at a time, and never a directory tree: `.git/` carries the lock file this
        call is holding, so removing it would unlink the inode a waiter is blocked on and two
        writers would then hold locks on two different files. `_prune_upwards` stops at `.git`
        and at the repository root for the same reason.

        Through `_unlink_inside` like the footprint recovery, so the two deleting branches of
        this adapter are bounded the same way at the last step: a path that does not resolve
        to somewhere honestly under this repository is not removed, whatever named it.

        DEEPEST FIRST, because `doomed` can now name a directory: `_restore_leftovers` lists
        an empty one, since nothing else accounts for it, and the only inverse of "this dead
        clone made a directory" is `rmdir`. Ordering by depth means a doomed directory is
        tried after the doomed entries inside it, and `rmdir` refuses while anything the claim
        preserved is still in there — so a directory holding a survivor stays, and the
        licence stays exactly as narrow as it was for files.
        """
        for rel in sorted(doomed, key=lambda path: (path.count("/"), path), reverse=True):
            target = self._inside_repo(repo, rel)
            if target is not None and target.is_dir() and not target.is_symlink():
                with contextlib.suppress(OSError):
                    target.rmdir()
            else:
                self._unlink_inside(repo, rel)
            self._prune_upwards(repo, rel)


    def _restore_repository(self, user_id: UserId, bundle: Path) -> bool:
        repo = self.repo_path(user_id)
        # `.git/` first, exactly as `_repo` does it: the lock file lives inside it, so it has
        # to exist before the lock can be taken — and `_initialized` reads `.git/HEAD`, which
        # only git writes, so making the directory does not make the repository look present.
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        with _locked(repo):
            # THE SAME THREE BRANCHES EVERY OTHER MUTATION DECIDES AT ITS LOCK ENTRY
            # (`_begin_mutation`), decided over the tree itself because there is no
            # repository yet to read a `git status` out of. A restore writes a whole
            # checkout into a directory people can also write, so "what is already here"
            # has to be answered before anything lands, and the claim is what answers it.
            if self._initialized(repo):
                # (i) DONE. `.git/HEAD` is the last thing the graft moves, so its presence
                # means a restore completed — including one killed in the instant between the
                # graft and its own `_clear_marker`, which leaves the claim standing over a
                # whole repository. Drop that stale claim (the first `_begin_mutation`
                # branch, one call early) and report that this restore did nothing.
                self._clear_marker(repo, "restore_repository")
                return False
            # THE SAME ORDER `_mutation` RUNS IN, and for the same reason: read the claim
            # that is standing here, then write OUR OWN — which is where a `.git/` that will
            # not take a claim stops this call (`CanonicalMarkerError`), before a single file
            # has been listed, let alone deleted — and only then look at what is on disk and
            # decide. `previous` is the only claim weighed below; the one now beside it is
            # ours and names a live process.
            previous = self._read_marker(repo)
            # LISTED BEFORE THE CLAIM IS WRITTEN, because the claim has to RECORD it. A
            # restore cannot enumerate its own footprint — nobody knows what a `git clone`
            # will materialize until it has — so its claim states the inverse: what the
            # target held before this call started, which is exactly what this call did NOT
            # create and what a recovery after its death may therefore never delete. Listing
            # is a read of a directory: nothing is decided and nothing is touched until
            # `_claimed` has proved this `.git/` takes a claim at all.
            leftovers = self._restore_leftovers(repo)
            with self._claimed(
                repo, "restore_repository", paths=(), pre_existing=leftovers
            ):
                # CLAIMED BEFORE ANYTHING IS DECIDED — so there is never a moment under the
                # lock where the checkout this call is about to materialize is unclaimed.
                # That claim is exactly what makes branch (iii) possible next time round
                # instead of branch (ii), and `_claimed` releases it on every exit a live
                # process reaches: a failed clone, and every refusal below, leaves no claim
                # standing over a directory the next call would then delete. The footprint is
                # EMPTY and `pre_existing` carries the licence instead (`_write_marker`).
                if leftovers:
                    # THE CLAIM THIS BRANCH DESTROYS FOR MUST BE A RESTORE'S OWN. Every other
                    # branch of this adapter's recovery discards uncommitted CHANGES in a
                    # repository it is committing to, where any operation's claim is proof
                    # enough because every operation writes into that same repository
                    # (`_begin_mutation`). This one deletes a DIRECTORY AND THE FILES IN IT,
                    # and exactly one operation ever puts a half-materialized checkout there.
                    # A crashed `init_repository` — which claims a bare `.git/` and touches
                    # nothing else — would otherwise authorize wiping files that predate the
                    # claim entirely.
                    claimed_by = str((previous or {}).get("operation") or "")
                    if claimed_by != "restore_repository":
                        # (ii) NOT OURS. Files with no claim beside them, or with a claim left
                        # by something that never writes a checkout, are somebody's — a
                        # half-copied library, a directory reused by hand — and a clone that
                        # overwrote them would be this adapter discarding work it did not
                        # make. An unreadable claim lands here too: it names no operation, so
                        # it names no licence.
                        raise CanonicalDirtyError(
                            leftovers,
                            claimed_by=(
                                (claimed_by or "an unnamed operation")
                                if previous is not None
                                else None
                            ),
                        )
                    if not self._claimant_is_gone(previous):
                        # (ii-b) A RESTORE'S CLAIM WITH NO PROVEN DEATH BEHIND IT. Same rule
                        # as `_begin_mutation`, and it bites hardest here because this branch
                        # DELETES FILES: "a dead restore's own half-materialized checkout" is
                        # a statement about a death, and only `ProcessLookupError` on an
                        # integer pid above zero proves one. A live pid refutes it; a pid that
                        # cannot be read or cannot be probed leaves it unproven, which is not
                        # the same as true. Ours counts as live — it would mean a
                        # `_clear_marker` that could neither unlink nor replace the file.
                        raise CanonicalDirtyError(
                            leftovers,
                            claimed_by=claimed_by or None,
                            unproven=self._claim_reading(previous),
                        )
                    kept = self._claim_list(previous, "pre_existing")
                    if kept is None:
                        # (ii-c) A DEAD RESTORE'S CLAIM THAT SAYS NOTHING ABOUT THIS TARGET.
                        # The claim answers who died; `pre_existing` answers which of these
                        # files were already here when they arrived — and this branch DELETES
                        # FILES, so it needs both. A claim with no readable list recorded
                        # nothing, and nothing is not a licence over everything: an old-shape
                        # claim, or one whose list will not read as a list of strings, cannot
                        # separate a dead clone's leftovers from a half-copied library, a
                        # directory somebody reused by hand, or an agent's scratch files. So
                        # refuse, naming every file it cannot account for.
                        raise CanonicalDirtyError(
                            leftovers,
                            claimed_by=claimed_by or None,
                            outside=leftovers,
                            covered=None,
                        )
                    # (iii) A DEAD RESTORE'S OWN CHECKOUT. The claim names it, its claimant is
                    # provably gone, and it recorded what stood here before it began — so what
                    # it did NOT record is what it materialized itself, and only that may go.
                    # It must: `git clone` refuses a non-empty target, and a graft over a
                    # partial one would leave objects from two clones in one `.git/`.
                    #
                    # RE-LISTED IMMEDIATELY BEFORE THE DELETION, because the list that
                    # decided is not the list that acts. `leftovers` was read before the
                    # claim was written and before three branches were weighed, and the lock
                    # excludes only this framework's own writers: a person or an agent with a
                    # shell in the directory can drop a file into it in that window, and
                    # deleting off the stale snapshot would either miss it or — once it fell
                    # outside `kept` — take it. So the target is read again here, and ANYTHING
                    # THAT APPEARED SINCE THE CLAIM IS NOT THE DEAD CLONE'S: it cannot be, the
                    # dead clone stopped writing when it died. It is refused, by name, exactly
                    # as any other work this adapter did not make.
                    present_now = self._restore_leftovers(repo)
                    appeared = [path for path in present_now if path not in leftovers]
                    if appeared:
                        raise CanonicalDirtyError(
                            present_now,
                            claimed_by=claimed_by or None,
                            outside=appeared,
                            covered=kept,
                        )
                    # Off `present_now` and not `leftovers`: a file that VANISHED in the same
                    # window is simply not deleted, rather than named in a warning as
                    # discarded by a call that never touched it.
                    doomed = [path for path in present_now if path not in kept]
                    survivors = [path for path in present_now if path in kept]
                    _log.warning(
                        "canonical restore_repository: discarding a previous restore's "
                        "half-materialized checkout under %s left by %s (pid %s, started "
                        "%s) — %d path(s): %s; kept, because that claim recorded them as "
                        "already here: %s",
                        repo,
                        claimed_by,
                        (previous or {}).get("pid") or "?",
                        (previous or {}).get("started_at") or "?",
                        len(doomed),
                        ", ".join(doomed) or "(none)",
                        ", ".join(survivors) or "(none)",
                    )
                    self._clear_restore_target(repo, doomed)
                    # NARROW OUR OWN CLAIM to what actually survived. From here on everything
                    # else in this target is this call's own clone, and a restore that has to
                    # recover after us must be able to say which is which — a `pre_existing`
                    # still naming the files we just deleted would hand our successor a list
                    # that preserves whatever happens to land on those names next.
                    self._write_marker(
                        repo,
                        "restore_repository",
                        paths=(),
                        pre_existing=survivors,
                    )
                # Cloned into a staging directory and GRAFTED in, rather than cloned straight
                # onto `repo`: `git clone` refuses a non-empty target, and `repo/.git/` already
                # holds the lock file this block is holding. The graft moves the clone's `.git`
                # children in beside the lock instead of replacing the directory that carries it
                # — replacing it would unlink the file a waiter is blocked on, and two writers
                # would then hold locks on two different inodes.
                staging = repo.parent / f".restore-{uuid.uuid4().hex}"
                try:
                    subprocess.run(
                        ["git", "clone", "--quiet", str(bundle), str(staging)],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    # Pinned locally, mirroring what `_repo` writes when it creates a
                    # repository itself, so commits in a restored library never depend on (or
                    # record) the machine's git config.
                    for key, value in (
                        ("user.email", "pneuma_knowledge@local"),
                        ("user.name", "pneuma-knowledge"),
                    ):
                        self._run(staging, "config", key, value)
                    self._graft(staging, repo)
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
        return True

    @staticmethod
    def _graft(staging: Path, repo: Path) -> None:
        """Move a freshly cloned repository into `repo`, keeping `repo/.git/`'s own entries.

        `.git/HEAD` moves LAST, after every other entry — the clone's remaining `.git/`
        children AND its whole checked-out working tree. The ordering is the mechanism, not
        a tidiness: HEAD is not one file among the clone's, it is the marker `_initialized`
        reads, and a READER that finds it never takes the lock at all (`_repo` returns the
        moment `.git/HEAD` is a file). Moved in iteration order, HEAD could land while refs,
        objects and the documents were still arriving, and a concurrent `git archive` would
        read a repository that is present but not yet whole. Moved last, a reader either
        finds no HEAD — an uninitialized repository, so it blocks on the lock this restore
        holds and re-checks inside it — or finds one with everything already in place.

        Writers were already safe and stay so for a different reason: every mutating method
        (and so `_begin_mutation`) runs under the lock this graft is holding. The lock file
        and the in-flight marker both live in `repo/.git/`, and this graft moves the clone's
        entries in BESIDE them rather than replacing the directory that carries them.
        """
        head = staging / ".git" / "HEAD"
        # Listed before anything moves: `_graft_one` unlinks and rmdirs its sources, and a
        # directory being iterated while it is emptied is not a listing anyone can rely on.
        for entry in sorted(staging.iterdir()):
            if entry.name == ".git":
                for inner in sorted(entry.iterdir()):
                    if inner == head:
                        continue
                    GitCanonicalStore._graft_one(inner, repo / ".git" / inner.name, repo)
            else:
                GitCanonicalStore._graft_one(entry, repo / entry.name, repo)
        # Last, and one atomic creation: the repository becomes visible to lock-free readers
        # in one step, already complete.
        GitCanonicalStore._graft_one(head, repo / ".git" / "HEAD", repo)

    @staticmethod
    def _graft_collision(destination: Path, repo: Path) -> CanonicalMoveError:
        return CanonicalMoveError(
            "a path the restore was told to keep stands where the clone must land",
            str(destination.relative_to(repo)),
        )

    @staticmethod
    def _graft_one(source: Path, destination: Path, repo: Path) -> None:
        """Move one clone entry in, and REFUSE rather than land on something already there.

        Normally the target is empty. The one way it is not is the recovery branch above: a
        dead restore's claim can record a file as pre-existing, that file survives the
        clearing, and the clone may carry the same path. Overwriting it would undo, at the
        last step, the whole point of keeping it — so the restore stops and says which path
        it is, having moved whatever it already moved into a target that has no HEAD and is
        therefore still not a repository to anyone.

        **THE REFUSAL IS THE MOVE ITSELF, NOT A CHECK IN FRONT OF IT.** `if
        destination.exists(): raise` followed by a `shutil.move` is two syscalls with a
        window between them, and `shutil.move` (like `os.rename`) CLOBBERS: a file that
        appears in that window — the operator who drops a note into the directory while a
        restore runs, and the lock excludes only this framework's own writers — was silently
        overwritten by the very branch that exists to preserve such files. So each kind of
        entry is moved with the POSIX primitive that fails EEXIST by itself:

        - a **regular file** (and anything else that is not a directory or a symlink):
          `os.link` + `unlink` of the source. `link(2)` is specified to fail with EEXIST when
          the destination exists, and the destination it creates is the SAME inode as the
          source — already whole, so no reader can meet a half-written file, which is what
          makes it the right primitive for `.git/HEAD` in particular;
        - a **symlink**: recreated with `os.symlink`, which likewise fails EEXIST, then the
          source is unlinked. (`os.link(follow_symlinks=False)` would do the same job but is
          not available on every platform Python runs on.);
        - a **directory**: `mkdir`, which fails EEXIST, and then the children are grafted in
          one at a time under the same rules. The mkdir is what makes "the destination
          already existed" a refusal atomically; the recursion is what keeps the guarantee
          all the way down instead of only at the top level.

        `os.rename` is what this cannot use, atomic though it is: POSIX rename REPLACES a
        destination file, and replaces an empty destination directory, which is precisely the
        outcome being refused. EXDEV is the one case link cannot serve — a target mounted
        separately from the staging directory beside it — and it is answered by copying to a
        temporary name inside the destination's own directory and linking THAT into place, so
        the no-clobber step is still a single `link(2)`.
        """
        if source.is_symlink():
            try:
                os.symlink(os.readlink(source), destination)
            except FileExistsError as exc:
                raise GitCanonicalStore._graft_collision(destination, repo) from exc
            source.unlink()
            return
        if source.is_dir():
            try:
                destination.mkdir()
            except FileExistsError as exc:
                raise GitCanonicalStore._graft_collision(destination, repo) from exc
            for child in sorted(source.iterdir()):
                GitCanonicalStore._graft_one(child, destination / child.name, repo)
            source.rmdir()
            return
        try:
            os.link(source, destination)
        except FileExistsError as exc:
            raise GitCanonicalStore._graft_collision(destination, repo) from exc
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            # Across a mount boundary the content has to be copied; the LANDING still is not.
            staged = destination.with_name(f".graft-{uuid.uuid4().hex}")
            try:
                shutil.copy2(source, staged)
                try:
                    os.link(staged, destination)
                except FileExistsError as clash:
                    raise GitCanonicalStore._graft_collision(destination, repo) from clash
            finally:
                with contextlib.suppress(OSError):
                    staged.unlink()
        source.unlink()

    async def restore_repository(self, user_id: UserId, *, bundle: Path) -> bool:
        """Clone a canonical bundle into this user's repository; False if one is already there.

        The prebuilt restore's write verb, and the reason it is HERE rather than in the
        restore script: it writes the same repository every other method on this adapter
        writes, so it has to take the same per-repository lock. Run outside it, a `git clone`
        materializing a working tree beside a live `commit_patch` would be a second writer
        the lock was designed to exclude, and the next `_begin_mutation` could meet a
        half-materialized checkout and have to decide what it was.

        It carries the in-flight marker like every other mutating sequence, and it decides
        the SAME branches at its lock entry that `_begin_mutation` decides for a repository
        that already exists — over the tree itself, because there is none yet to read a `git
        status` out of. Four cases, and the claim is what separates the middle two:

        - **`.git/HEAD` is there** — a restore completed (HEAD is the last thing the graft
          moves), including one killed between the graft and its own marker clear: any stale
          claim is dropped and this call answers False;
        - **files present, and no claim OF A RESTORE'S** — somebody else's, and never
          overwritten: `CanonicalDirtyError` naming every path and the operation the claim (if
          any) belongs to, having written nothing;
        - **a restore's own claim present, no HEAD, and a `pre_existing` LIST recorded on it**
          — a previous restore of this adapter's died mid-graft: everything the target holds
          that the claim did NOT record as already-here is its own half-materialized checkout,
          and exactly that is logged at WARNING and removed, file by file, before this one
          proceeds. What the claim recorded stays. A restore cannot enumerate its own
          footprint the way every other operation does — nobody knows what a clone will
          materialize until it has — so it records the inverse, and the inverse is what bounds
          the deletion. A claim with no readable `pre_existing` accounts for nothing and is
          refused, exactly as an unreadable pid is;
        - **clean** — claim (recording what stood here, normally nothing), clone, graft
          (HEAD last), clear the claim.

        The middle two are separated by the marker's `operation` and not by its mere
        presence, because this branch DELETES FILES IT DID NOT WRITE. Only a restore ever
        materializes a checkout here, so only a restore's claim licenses removing one; a
        crashed `init_repository`, which claims a bare `.git/` and writes nothing else, would
        otherwise authorize wiping files that predate it. Every other recovery in this adapter
        accepts any operation's claim, and may: it puts that claim's OWN paths back in a
        repository each of those operations writes to (`_begin_mutation`).

        Never overwrites: a repository that is already initialized is answered False and left
        byte-for-byte, because canonical is authoritative and a bundle is a copy of someone
        else's build.
        """
        # to_thread: one hop for clone → config → graft, so the whole restore is atomic
        # within one thread and one hold of the lock (see module docstring).
        return await asyncio.to_thread(self._restore_repository, user_id, Path(bundle))

    # --- meta files (skill manifest) -----------------------------------------
    #
    # Off the CanonicalStore compile face: skill/ is NOT a compile product (no gate, no
    # path ownership, no compile_events). It rides the SAME per-user git repo so a per-user
    # skill is versioned/dumped/imported alongside the data it governs (schema-evolve §1.3),
    # but is written through this narrow read_meta/write_meta pair rather than commit_patch.

    def _read_meta(self, user_id: UserId, rel_path: str) -> str | None:
        repo = self._repo(user_id)
        if not self._has_head(repo):
            return None
        proc = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{rel_path}"],
            capture_output=True,
            text=True,
        )
        return proc.stdout if proc.returncode == 0 else None

    async def read_meta(self, user_id: UserId, rel_path: str) -> str | None:
        """Read a non-canonical meta file (e.g. skill/manifest.json) at HEAD, or None."""
        # to_thread: git subprocess (see module docstring).
        return await asyncio.to_thread(self._read_meta, user_id, rel_path)

    def _write_meta(
        self, user_id: UserId, rel_path: str, content: str, message: str
    ) -> SnapshotRef:
        repo = self._repo(user_id)
        # THE writer the job queue does not serialize (module docstring): this one runs in
        # the API process. Staging only `rel_path` keeps it from sweeping another writer's
        # changes into its own commit; the lock keeps another writer's `git commit` from
        # sweeping in THIS one's staged path, which staging narrowly cannot prevent.
        with _locked(repo):
            # One path, and the footprint says exactly that.
            with self._mutation(repo, "write_meta", paths=[rel_path]):
                target = repo / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                # `:(literal)` on both: `rel_path` is a file name the caller handed over
                # (the skill manifest), never a pattern, and the `add` and the `status` that
                # decides whether to commit must scope to the same single path (`_literal`).
                self._run(repo, "add", "--", *self._literal([rel_path]))
                status = self._run(
                    repo, "status", "--porcelain", "--", *self._literal([rel_path])
                ).stdout.strip()
                if status:
                    self._run(repo, *_GIT_ID, "commit", "-q", "-m", message)
                sha = self._run(repo, "rev-parse", "HEAD").stdout.strip()
        return SnapshotRef(ref=sha)

    async def write_meta(
        self, user_id: UserId, rel_path: str, content: str, *, message: str
    ) -> SnapshotRef:
        """Write + commit a single non-canonical meta file (skill/manifest.json)."""
        # to_thread: one hop for write → add → status → commit → rev-parse (see docstring).
        return await asyncio.to_thread(
            self._write_meta, user_id, rel_path, content, message
        )

    # --- branch operations (evolve, schema-evolve §2.3) ----------------------
    #
    # OFF the CanonicalStore Protocol: only the service's evolve flow touches branches, and
    # core never commits — so these live on the concrete adapter, not the port. Implemented
    # with git PLUMBING (hash-object / read-tree into a throwaway index / write-tree /
    # commit-tree / update-ref) rather than a checkout: HEAD and the working tree stay pinned
    # to the main line the whole time, so an evolve branch build never races the concurrent
    # reads / main-line compiles that also drive this one repo (the single-writer queue
    # serializes writes, but the working tree is shared state either way).

    def _branch_commit(
        self,
        user_id: UserId,
        branch: str,
        files: dict[str, str],
        message: str,
        base: SnapshotRef,
    ) -> SnapshotRef:
        repo = self._repo(user_id)
        # A throwaway index seeded from base's tree, kept entirely off the repo's real index
        # (GIT_INDEX_FILE) so nothing touches the working tree or the staged state of main.
        # MUST be absolute: `git -C <repo>` chdirs before resolving GIT_INDEX_FILE, so a
        # relative path (e.g. from canonical_root=./data/canonical) would be re-rooted
        # inside the repo and point at a directory that does not exist.
        index_path = (repo / ".git" / f"evolve-index-{uuid.uuid4().hex}").resolve()
        env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}

        def run_env(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )

        try:
            # Locked like every other write: this one never touches the working tree, but it
            # writes objects and a ref, and `update-ref` is a mutation of the repository.
            # AN EMPTY FOOTPRINT, STATED. This writes objects, a throwaway index inside
            # `.git/` and one ref; it touches no working-tree path at all, so its claim covers
            # nothing — and a claim that covers nothing can never license a recovery.
            with _locked(repo), self._mutation(repo, "branch_commit", paths=()):
                # Seed the temp index from base's tree — every path base carries stays
                # present, so an overlay of `files` leaves untouched paths byte-for-byte.
                run_env("read-tree", base.ref)
                for rel, content in files.items():
                    blob = subprocess.run(
                        ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                        input=content,
                        capture_output=True,
                        text=True,
                        check=True,
                        env=env,
                    ).stdout.strip()
                    run_env(
                        "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}"
                    )
                tree = run_env("write-tree").stdout.strip()
                commit = run_env(
                    *_GIT_ID, "commit-tree", tree, "-p", base.ref, "-m", message
                ).stdout.strip()
                # Force the ref (an evolve re-run for one task overwrites its own branch).
                self._run(repo, "update-ref", f"refs/heads/{branch}", commit)
            return SnapshotRef(ref=commit)
        finally:
            index_path.unlink(missing_ok=True)

    async def branch_commit(
        self,
        user_id: UserId,
        branch: str,
        files: dict[str, str],
        message: str,
        *,
        base: SnapshotRef,
    ) -> SnapshotRef:
        """Overlay `files` onto `base`'s tree and commit it to `refs/heads/<branch>`.

        Plumbing-only: HEAD and the working tree never move (see the section comment). Paths
        not in `files` are carried verbatim from `base`; an existing branch is force-repointed
        at the new commit (an evolve re-run overwrites its own branch)."""
        return await asyncio.to_thread(
            self._branch_commit, user_id, branch, files, message, base
        )

    def _branch_head(
        self, user_id: UserId, branch: str
    ) -> SnapshotRef | None:
        repo = self._repo(user_id)
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
        )
        sha = proc.stdout.strip()
        return SnapshotRef(ref=sha) if proc.returncode == 0 and sha else None

    async def branch_head(
        self, user_id: UserId, branch: str
    ) -> SnapshotRef | None:
        """The commit a branch points at, or None when the branch does not exist."""
        return await asyncio.to_thread(self._branch_head, user_id, branch)

    def _delete_branch(self, user_id: UserId, branch: str) -> None:
        repo = self._repo(user_id)
        # Tolerant: a drop/adopt that runs twice, or a branch that was never created, is a
        # no-op rather than an error (update-ref -d fails when the ref is absent).
        # A ref and nothing else: an empty footprint, said out loud (see `_branch_commit`).
        with _locked(repo), self._mutation(repo, "delete_branch", paths=()):
            subprocess.run(
                ["git", "-C", str(repo), "update-ref", "-d", f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
            )

    async def delete_branch(self, user_id: UserId, branch: str) -> None:
        """Delete an evolve branch; a missing branch is tolerated (no error)."""
        await asyncio.to_thread(self._delete_branch, user_id, branch)

    def _read_meta_at(
        self, user_id: UserId, rel_path: str, ref: str
    ) -> str | None:
        repo = self._repo(user_id)
        proc = subprocess.run(
            ["git", "-C", str(repo), "show", f"{ref}:{rel_path}"],
            capture_output=True,
            text=True,
        )
        return proc.stdout if proc.returncode == 0 else None

    async def read_meta_at(
        self, user_id: UserId, rel_path: str, ref: str
    ) -> str | None:
        """Read a non-canonical meta file (skill/manifest.json) at an arbitrary ref/branch.

        The `at`-based `list` only surfaces `.md` canonical docs; the evolve adopt flow also
        needs the skill manifest that rides the branch tree, so this reads any path at any
        ref. Returns None when the path is absent at that ref."""
        return await asyncio.to_thread(self._read_meta_at, user_id, rel_path, ref)

    def _snapshots(self, user_id: UserId) -> list[SnapshotRef]:
        repo = self._repo(user_id)
        if not self._has_head(repo):
            return []
        log = self._run(repo, "log", "--pretty=%H%x1f%s").stdout
        refs: list[SnapshotRef] = []
        for line in filter(None, (line.strip() for line in log.splitlines())):
            sha, _, subject = line.partition("\x1f")
            refs.append(SnapshotRef(ref=sha, label=subject or None))
        return refs

    async def snapshots(self, user_id: UserId) -> list[SnapshotRef]:
        # to_thread: git subprocess (see module docstring).
        return await asyncio.to_thread(self._snapshots, user_id)

    def _snapshots_page(
        self,
        user_id: UserId,
        limit: int,
        after_ref: str | None,
    ) -> tuple[list[SnapshotRef], int, bool]:
        if limit < 1:
            raise ValueError("snapshot page limit must be positive")
        repo = self._repo(user_id)
        if not self._has_head(repo):
            return [], 0, False

        total = int(self._run(repo, "rev-list", "--count", "HEAD").stdout.strip())
        if after_ref:
            membership = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "merge-base",
                    "--is-ancestor",
                    after_ref,
                    "HEAD",
                ],
                capture_output=True,
                text=True,
            )
            if membership.returncode != 0:
                raise ValueError(
                    "snapshot cursor no longer belongs to the current history"
                )

        start_ref = after_ref or "HEAD"
        skip = ("--skip=1",) if after_ref else ()
        log = self._run(
            repo,
            "log",
            start_ref,
            *skip,
            f"--max-count={limit + 1}",
            "--pretty=%H%x1f%s",
        ).stdout
        refs: list[SnapshotRef] = []
        for line in filter(None, (line.strip() for line in log.splitlines())):
            sha, _, subject = line.partition("\x1f")
            refs.append(SnapshotRef(ref=sha, label=subject or None))
        has_more = len(refs) > limit
        return refs[:limit], total, has_more

    async def snapshots_page(
        self,
        user_id: UserId,
        *,
        limit: int,
        after_ref: str | None = None,
    ) -> tuple[list[SnapshotRef], int, bool]:
        return await asyncio.to_thread(
            self._snapshots_page,
            user_id,
            limit,
            after_ref,
        )

    def _tag(
        self, user_id: UserId, ref: SnapshotRef, label: str
    ) -> SnapshotRef:
        repo = self._repo(user_id)
        # A ref and nothing else: an empty footprint, said out loud (see `_branch_commit`).
        with _locked(repo), self._mutation(repo, "tag", paths=()):
            self._run(repo, "tag", "-f", label, ref.ref)
        return SnapshotRef(ref=label, label=label)

    async def tag(
        self, user_id: UserId, ref: SnapshotRef, label: str
    ) -> SnapshotRef:
        # to_thread: git subprocess (see module docstring).
        return await asyncio.to_thread(self._tag, user_id, ref, label)

    def _commit_trailer(
        self, user_id: UserId, ref: SnapshotRef, key: str
    ) -> str | None:
        repo = self._repo(user_id)
        out = self._run(
            repo,
            "log",
            "-1",
            f"--format=%(trailers:key={key},valueonly=true)",
            ref.ref,
        ).stdout.strip()
        return out or None

    async def commit_trailer(
        self, user_id: UserId, ref: SnapshotRef, key: str
    ) -> str | None:
        """Read a single git trailer value off the commit at `ref` (M5 skill audit).

        Uses git's own trailer parser (`%(trailers:key=…,valueonly=true)`), so the
        `Skill-Version` stamped at compile time reads back with zero bespoke parsing.
        Returns None when the trailer is absent on that commit."""
        # to_thread: git subprocess (see module docstring).
        return await asyncio.to_thread(self._commit_trailer, user_id, ref, key)

    def _find_commit_with_trailer(
        self, user_id: UserId, key: str, value: str, since: str
    ) -> SnapshotRef | None:
        repo = self._repo(user_id)
        if not self._has_head(repo):
            return None
        # `since..HEAD` is EXCLUSIVE of `since`, which is what the caller means: the commit
        # it names is the state it already saw. A ref that no longer resolves in this
        # repository (a rewritten or pruned history) widens the walk to the whole history
        # rather than failing — the trailer VALUE is what identifies the commit, and a
        # superset of the range can only find the same one.
        rev = "HEAD"
        if since and self._resolves(repo, since):
            rev = f"{since}..HEAD"
        # `-z` terminates each record with NUL and `%x00` separates the sha from the value,
        # so the stream is a flat NUL-separated [sha, value, sha, value, …]: neither a sha
        # nor a trailer value can contain a NUL, so nothing here has to be escaped.
        out = self._run(
            repo,
            "log",
            "-z",
            f"--format=%H%x00%(trailers:key={key},valueonly=true)",
            rev,
        ).stdout
        fields = out.split("\0")
        # git log walks newest-first, so the first match IS the newest one.
        for sha, trailer in zip(fields[0::2], fields[1::2]):
            if sha and trailer.strip() == value:
                return SnapshotRef(ref=sha)
        return None

    @staticmethod
    def _resolves(repo: Path, rev: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--verify", "-q", f"{rev}^{{commit}}"],
                capture_output=True,
                text=True,
            ).returncode
            == 0
        )

    async def find_commit_with_trailer(
        self,
        user_id: UserId,
        *,
        key: str,
        value: str,
        since: SnapshotRef | None = None,
    ) -> SnapshotRef | None:
        """The newest commit in `since..HEAD` whose `key` trailer reads exactly `value`.

        One `git log` over a bounded range, using git's own trailer parser — the same one
        `commit_trailer` reads a single commit with. It answers the question a resuming
        writer has and HEAD alone cannot: whether this writer's own commit is in the history,
        even when another writer (the manifest, off the queue) committed above it."""
        # to_thread: git subprocess (see module docstring).
        return await asyncio.to_thread(
            self._find_commit_with_trailer,
            user_id,
            key,
            value,
            since.ref if since is not None else "",
        )
