"""Snapshot tenant identity + write protection — a pure module, no I/O.

WHY THE CONVENTION AND NOT A REGISTRY LOOKUP
--------------------------------------------
A snapshot is a frozen tenant, so the single most important property in the system is that
NOTHING EVER WRITES TO ONE. That guard has to hold at every write entry point, in every
process (API, compile worker, example scripts), including the ones that hold no PG pool at the
moment they need to decide. So the guard is a TOTAL FUNCTION on the tenant id: a snapshot
tenant is any id carrying the reserved `kbsnap-` prefix, and `assert_writable` is a string
test with no round trip and no failure mode of its own.

The registry (`kb_snapshots`) remains the source of truth for a snapshot's METADATA — owner,
label, canonical ref, status, counts. It is deliberately not the source of truth for
writability: a registry read can fail, time out, or find nothing (a half-deleted snapshot), and
every one of those outcomes would have to fall back to "assume writable" to keep working —
i.e. fail-OPEN on exactly the invariant that must fail closed.

WHY THIS PREFIX SHAPE
---------------------
`kbsnap-<32 hex>` uses only characters that survive every id sanitizer in the stack: the
Meilisearch index uid (`[^A-Za-z0-9_-]` → `_`) and the git repo directory name apply the same
substitution, so a tenant id built from `[a-z0-9-]` maps one-to-one onto its physical
namespaces. An id containing `@`, `:` or `~` would not: two different snapshot tenants could
collapse onto one Meilisearch index.

The prefix is RESERVED: `assert_writable` refuses it for any caller, which also means an
ordinary user id may not begin with it. That is the cost of a lookup-free guard, and it is
stated rather than assumed — see `RESERVED_PREFIX`.
"""

from __future__ import annotations

import uuid

from pneuma_knowledge_core.domain.ids import UserId

#: Reserved tenant-id prefix. No user-facing id may start with this; every id that does is a
#: frozen snapshot tenant and is read-only forever.
RESERVED_PREFIX = "kbsnap-"


class SnapshotTenantWriteError(RuntimeError):
    """A write was attempted against a frozen snapshot tenant.

    Its own type, not a bare ValueError: the API maps it to 409 Conflict (the target is in a
    state that forbids the operation), and the wording tells the caller which tenant and what
    to do instead. Loud by construction — there is no code path that swallows it into a no-op,
    because a silently-dropped write to a snapshot would look exactly like a successful one.
    """

    def __init__(self, user_id: object) -> None:
        self.tenant_id = str(user_id)
        super().__init__(
            f"{self.tenant_id!r} is a frozen knowledge-base snapshot and is read-only. "
            "Snapshots exist to be asked questions, never written to — address the owning "
            "user instead, or take a new snapshot once the owner's base has changed."
        )


def new_snapshot_id() -> str:
    """A fresh snapshot id: 32 hex characters, safe in every namespace (see module docstring)."""
    return uuid.uuid4().hex


def snapshot_tenant_id(snapshot_id: str) -> UserId:
    """The tenant a snapshot's frozen copy lives under.

    Derived from the snapshot id ALONE — not from the owner. The owner link lives in the
    registry row, so a tenant id can never be assembled out of caller-supplied text, and no
    owner id (which may contain `.`, `:` or `_`) can leak into a physical namespace name."""
    return UserId(f"{RESERVED_PREFIX}{snapshot_id}")


def is_snapshot_tenant(user_id: object) -> bool:
    """Is this id a frozen snapshot tenant? A pure string test (see module docstring)."""
    return str(user_id).startswith(RESERVED_PREFIX)


def assert_writable(user_id: object) -> None:
    """Raise `SnapshotTenantWriteError` when `user_id` names a frozen snapshot tenant.

    Call at every write entry point — ingest, compile enqueue, evolve. Cheap enough
    (one `startswith`) that there is no reason to guard it behind a condition, which is the
    point: a guard people skip "because it costs a query" is not a guard."""
    if is_snapshot_tenant(user_id):
        raise SnapshotTenantWriteError(user_id)


__all__ = [
    "RESERVED_PREFIX",
    "SnapshotTenantWriteError",
    "assert_writable",
    "is_snapshot_tenant",
    "new_snapshot_id",
    "snapshot_tenant_id",
]
