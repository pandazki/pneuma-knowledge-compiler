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
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import uuid
from pathlib import Path

from pneuma_knowledge_core.compile.documents import parse_document
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef

_UID_SAFE = re.compile(r"[^a-zA-Z0-9_-]")
_GIT_ID = ("-c", "user.email=pneuma_knowledge@local", "-c", "user.name=pneuma-knowledge")


class GitCanonicalStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    # --- repo plumbing --------------------------------------------------------

    def _repo(self, user_id: UserId) -> Path:
        # I1: path derived from user_id only.
        repo = self._root / _UID_SAFE.sub("_", str(user_id))
        if not (repo / ".git").is_dir():
            repo.mkdir(parents=True, exist_ok=True)
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
        tree = self._run(repo, "ls-tree", "-r", "--name-only", ref).stdout
        docs: list[CanonicalDocument] = []
        for path in filter(None, (line.strip() for line in tree.splitlines())):
            if not path.endswith(".md"):
                continue
            text = self._run(repo, "show", f"{ref}:{path}").stdout
            docs.append(self._to_document(path, text))
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
            if doc.pneuma_id == document_id:
                return doc
        return None

    @staticmethod
    def _to_document(path: str, text: str) -> CanonicalDocument:
        frontmatter, body = parse_document(text)
        return CanonicalDocument(
            pneuma_id=DocumentId(str(frontmatter.get("pneuma_id", ""))),
            path=path,
            frontmatter=frontmatter,
            body=body,
        )

    # --- writes ---------------------------------------------------------------

    def _commit_patch(
        self, user_id: UserId, files: dict[str, str], message: str
    ) -> SnapshotRef:
        repo = self._repo(user_id)
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
        target = repo / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        # Stage ONLY this path so a meta write never sweeps in unrelated pending changes.
        self._run(repo, "add", "--", rel_path)
        status = self._run(repo, "status", "--porcelain", "--", rel_path).stdout.strip()
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
            # Seed the temp index from base's tree — every path base carries stays present,
            # so an overlay of `files` leaves untouched paths byte-for-byte intact.
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
            # Force the ref (an evolve re-run for the same task overwrites its own branch).
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

    def _tag(
        self, user_id: UserId, ref: SnapshotRef, label: str
    ) -> SnapshotRef:
        repo = self._repo(user_id)
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
