"""CanonicalStore port — per-user git canonical authority (ADR-001, §5, §6).

The only non-rebuildable layer (invariant I2). patch = commit, snapshot = tag,
rollback = revert — all free from git. Reads accept an optional snapshot
(`at: SnapshotRef`) for snapshot Q&A (§7). Per-user write serialization is
enforced by the JobQueue, not by holding a lock here.
"""

from __future__ import annotations

from typing import Protocol

from ..domain.canonical import CanonicalDocument
from ..domain.ids import DocumentId, UserId
from ..domain.snapshot import SnapshotRef


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
