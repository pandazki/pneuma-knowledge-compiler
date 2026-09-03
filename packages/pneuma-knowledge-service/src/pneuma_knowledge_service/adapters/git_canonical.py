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

**A dirty tree at the entry of a mutating method is crash residue, and is recovered.** Every
writer here commits what it wrote and the lock excludes a live concurrent writer, so once a
mutating sequence holds the lock and has not yet written anything, an uncommitted change can
only be what a process that died mid-write left behind — most often a half-applied set of
`git mv` renames, staged and belonging to nobody. Leaving it would be worse than removing
it: the next `commit_patch` runs `git add -A` and would sweep those renames into an
unrelated compile's commit, so a crashed archive would land inside a compile, attributed to
it, under its message. So `_recover_residue` runs first thing inside every mutating
`_locked` body: it LOGS the paths and the operation at WARNING, then `git reset --hard HEAD`
+ `git clean -fd` (never touching `.git`), then re-checks and raises if the tree is still
not clean.

The lock is the whole licence for that. Outside it, "uncommitted" could equally be another
writer mid-sequence, and discarding it would destroy work in flight. Under it, and only
under it, the tree between operations is clean by construction — so a dirty one is a fault
with exactly one explanation. The residue is discarded rather than surfaced because it is
not work anyone can resume: it is the leftovers of an operation whose caller already failed,
and the record of it is the warning line, which names every path.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import io
import logging
import os
import re
import shutil
import subprocess
import tarfile
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

from pneuma_knowledge_core.compile.documents import DOC_ID_KEY, parse_document
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.ports.canonical_store import CanonicalMoveError

_log = logging.getLogger(__name__)

_UID_SAFE = re.compile(r"[^a-zA-Z0-9_-]")
_GIT_ID = ("-c", "user.email=pneuma_knowledge@local", "-c", "user.name=pneuma-knowledge")
#: Inside `.git/` on purpose: git never reports its own directory, so the lock is invisible
#: to `git status`, to every commit, and to anyone reading the repository as a library.
_LOCK_NAME = "pneuma.lock"


@contextlib.contextmanager
def _locked(repo: Path) -> Iterator[None]:
    """Hold the exclusive per-repository advisory lock for the whole of a git sequence.

    Every MUTATING sequence in this adapter runs inside one of these; reads do not (see the
    module docstring). The lock is `flock(LOCK_EX)`, so it is released by the OS when the
    process dies — a writer that crashes mid-write leaves a dirty tree for the next writer
    to recover at its lock entry (`_recover_residue`), never a lock nobody can take.

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
            # FIRST, before a byte of this patch is written: `add -A` below would otherwise
            # sweep a crashed writer's leftovers into this commit (see the module docstring).
            self._recover_residue(repo, "commit_patch")
            for rel, content in files.items():
                target = repo / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            self._run(repo, "add", "-A")
            status = self._run(repo, "status", "--porcelain").stdout.strip()
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
            self._recover_residue(repo, "move_documents")
            return self._move_documents_locked(repo, moves, message, writes, removals)

    def _move_documents_locked(
        self,
        repo: Path,
        moves: Sequence[tuple[str, str]],
        message: str,
        writes: dict[str, str] | None = None,
        removals: Sequence[str] = (),
    ) -> SnapshotRef:
        # Runs under the repository lock (`_move_documents`), after `_recover_residue` has
        # established a clean tree, so the preflight below and the renames that follow it
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
        # The tree's own state is not among these checks any more: `_recover_residue` ran at
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
                self._run(repo, "rm", "-q", "--", path)
                removed.append(path)
            for from_path, to_path in moves:
                self._make_parents(repo, repo / to_path, created)
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
                self._run(repo, "add", "--", path)
            # `git rm` / `git mv` / the `add` above stage exactly their own paths; `add -A`
            # would additionally sweep in whatever else happens to be dirty, which this verb
            # has no business committing. Stage nothing further and commit exactly these.
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
            directory = (repo / from_path).parent
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
        NUL-terminated field after the destination.
        """
        try:
            proc = self._run(repo, "status", "--porcelain", "-z")
        except Exception as exc:  # noqa: BLE001 — see the docstring
            raise CanonicalMoveError("could not read repository status", "") from exc
        paths: list[str] = []
        fields = proc.stdout.split("\0")
        index = 0
        while index < len(fields):
            entry = fields[index]
            index += 1
            if not entry:
                continue
            code, path = entry[:2], entry[3:]
            if "R" in code or "C" in code:
                # `XY <new>\0<old>\0`: skip the source field. The path ON DISK — the one an
                # operator has to look at — is the destination, which is the first field.
                index += 1
            if path:
                paths.append(path)
        return paths

    def _first_dirty_path(self, repo: Path) -> str | None:
        """The first path `git status` reports, or None when the tree is clean."""
        paths = self._dirty_paths(repo)
        return paths[0] if paths else None

    def _recover_residue(self, repo: Path, operation: str) -> None:
        """Discard crash residue at the entry of a mutating sequence. Runs UNDER the lock.

        Called first thing inside every mutating `_locked` body, before that body has
        written anything. At that instant a dirty tree has exactly one explanation (module
        docstring): every writer here commits what it wrote, and the lock excludes a live
        concurrent writer — so what is uncommitted is what a process that died mid-write
        left behind, most often a half-applied set of staged renames belonging to nobody.

        Recovering is not a convenience, it is the only safe answer. `commit_patch` stages
        with `git add -A`, so residue left in place is swept into the NEXT commit whatever
        it is: a crashed archive's renames would land inside an unrelated compile, under its
        message and attributed to its skill version. Refusing every subsequent write instead
        would wedge the library on a fault no caller can clear.

        Whole-tree, because the residue's extent is unknown — the crashed writer got as far
        as it got. `reset --hard HEAD` + `clean -fd` is therefore the sequence, and it never
        reaches `.git` (git does not clean its own directory, and the lock file lives
        there). Before an initial commit there is no HEAD to reset to, so the index is
        emptied instead and `clean` removes the files. The paths are LOGGED at WARNING
        before anything is discarded — that line is the whole record of what was there — and
        the tree is re-read afterwards: a recovery that did not get it clean raises, because
        "recovered" over a still-dirty tree is exactly the clean lie this adapter refuses to
        tell anywhere else.
        """
        residue = self._dirty_paths(repo)
        if not residue:
            return
        _log.warning(
            "canonical %s: discarding crash residue under %s — %d path(s): %s",
            operation,
            repo,
            len(residue),
            ", ".join(residue),
        )
        if self._has_head(repo):
            self._run(repo, "reset", "-q", "--hard", "HEAD")
        else:
            # No commit to reset to: the index is the only thing holding the residue, and
            # `clean` takes the files themselves.
            self._run(repo, "rm", "-rq", "--cached", "--ignore-unmatch", "--", ".")
        self._run(repo, "clean", "-qfd")
        left = self._first_dirty_path(repo)
        if left is not None:
            raise CanonicalMoveError("crash residue could not be cleaned", left)

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
                self._run(repo, "reset", "-q", "HEAD", "--", path)
            except Exception:  # noqa: BLE001 — see the docstring
                pass
            target = repo / path
            if target.is_file():
                try:
                    target.unlink()
                except OSError:
                    pass

        for from_path, to_path in reversed(list(performed)):
            (repo / from_path).parent.mkdir(parents=True, exist_ok=True)
            try:
                self._run(repo, "mv", "--", to_path, from_path)
                continue
            except Exception:  # noqa: BLE001 — see the docstring
                pass
            for args in (
                ("reset", "-q", "HEAD", "--", from_path, to_path),
                ("checkout", "-q", "HEAD", "--", from_path),
            ):
                try:
                    self._run(repo, *args)
                except Exception:  # noqa: BLE001 — see the docstring
                    pass
            target = repo / to_path
            if target.is_file():
                try:
                    target.unlink()
                except OSError:
                    pass

        for path in reversed(list(removed)):
            # `git rm` staged a deletion of a committed file, so HEAD still holds it: one
            # checkout restores both the index entry and the working file.
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            try:
                self._run(repo, "checkout", "-q", "HEAD", "--", path)
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
                self._run(repo, "reset", "-q", "HEAD", "--", *moved_paths)
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

        A tree that is dirty when this call takes the lock is RECOVERED rather than refused
        (`_recover_residue`, module docstring): under the lock, uncommitted work can only be
        a crashed writer's leftovers, and leaving them for `commit_patch`'s `add -A` to
        sweep into an unrelated commit is the worse outcome. The whole sequence holds the
        repository lock, so on one host the clean tree the preflight saw is the tree the
        renames are applied to.
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

    def _restore_repository(self, user_id: UserId, bundle: Path) -> bool:
        repo = self.repo_path(user_id)
        # `.git/` first, exactly as `_repo` does it: the lock file lives inside it, so it has
        # to exist before the lock can be taken — and `_initialized` reads `.git/HEAD`, which
        # only git writes, so making the directory does not make the repository look present.
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        with _locked(repo):
            if self._initialized(repo):
                return False
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
                # Pinned locally, mirroring what `_repo` writes when it creates a repository
                # itself, so commits in a restored library never depend on (or record) the
                # machine's git config.
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
        (and so `_recover_residue`) runs under the lock this graft is holding.
        """
        head = staging / ".git" / "HEAD"
        for entry in staging.iterdir():
            if entry.name == ".git":
                for inner in entry.iterdir():
                    if inner == head:
                        continue
                    shutil.move(str(inner), str(repo / ".git" / inner.name))
            else:
                shutil.move(str(entry), str(repo / entry.name))
        # Last, and a rename within one directory tree: the repository becomes visible to
        # lock-free readers in one step, already complete.
        shutil.move(str(head), str(repo / ".git" / "HEAD"))

    async def restore_repository(self, user_id: UserId, *, bundle: Path) -> bool:
        """Clone a canonical bundle into this user's repository; False if one is already there.

        The prebuilt restore's write verb, and the reason it is HERE rather than in the
        restore script: it writes the same repository every other method on this adapter
        writes, so it has to take the same per-repository lock. Run outside it, a `git clone`
        materializing a working tree beside a live `commit_patch` would be a second writer
        the lock was designed to exclude, and `_recover_residue` — which reads an uncommitted
        change as a dead writer's residue and discards it — could meet a half-materialized
        checkout and read it as exactly that.

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
            self._recover_residue(repo, "write_meta")
            target = repo / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self._run(repo, "add", "--", rel_path)
            status = self._run(
                repo, "status", "--porcelain", "--", rel_path
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
            with _locked(repo):
                self._recover_residue(repo, "branch_commit")
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
        with _locked(repo):
            self._recover_residue(repo, "delete_branch")
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
        with _locked(repo):
            self._recover_residue(repo, "tag")
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
