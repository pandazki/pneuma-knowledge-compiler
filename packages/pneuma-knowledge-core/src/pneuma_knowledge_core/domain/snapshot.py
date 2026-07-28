"""Snapshot reference.

A snapshot is a git commit/tag (architecture.md §5): free from the canonical
authority layer. `ref` is an opaque git ref (commit sha or tag name); adapters
resolve it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotRef:
    ref: str
    label: str | None = None
