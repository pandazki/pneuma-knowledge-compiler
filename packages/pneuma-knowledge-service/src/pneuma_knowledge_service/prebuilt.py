"""Restore a library that ships prebuilt — from its authorities, with no model calls.

A project may ship its compiled library alongside its material (the scaffold's demo mode and
`examples/opc` both do). Only the AUTHORITIES are shipped, because they are the only
things that cannot be recomputed (architecture.md §2):

  1. the canonical library — a git bundle, cloned into `<canonical_root>/<user>/`;
  2. L0 — the build-time `NormalizedSource` rows verbatim, so the source ids and block spans
     are exactly the ones the restored canonical cites. Re-ingesting the material instead
     could never reproduce them: source ids are system-assigned at ingest, and any change to
     the parsing machinery would shift block boundaries out from under cited spans.
  3. when L0 contains images, their immutable original bytes under `media/sha256/`.

Everything else is DERIVED and rebuilt here exactly as a rebuild would: L1 lexical, L2
chunks (per each source's own IntakePlan), L3 projection. Nothing in this module calls a
chat model, so a restore works with no API key at all — which is the point: browsing a
compiled library must not depend on a credential.

Restored sources are marked digested and their queued work is settled rather than drained: the
shipped canonical already covers them, and compiling them again would spend real money redoing
a finished build.

Those authorities are scoped to THIS bundle. A restore is a load, not a migration: it refuses a
tenant that holds anything it did not ship (`restore_refusal`), and it only ever settles jobs
and stamps sources that are in the dump. Marking somebody's own uncompiled material as
digested would tell them a compile happened that never did — the one failure mode a restore
must not have.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import NormalizedSource

from .media_ingest import matches_declared_image_type
from .projection import rebuild_projection
from .wiring import AppContext, embed_l2_chunks, plan_l2_chunks

BUNDLE_NAME = "canonical.bundle"
L0_DUMP_NAME = "l0.jsonl.gz"
L0_MEDIA_DIR_NAME = "media"
SETTLED_DETAIL = "prebuilt library"


class PrebuiltUnavailable(RuntimeError):
    """The directory is not a prebuilt library (missing or incomplete authorities)."""


@dataclass(frozen=True)
class PrebuiltRestore:
    """What one restore actually did — reported, never inferred by the caller."""

    canonical_cloned: bool
    sources: int
    jobs_settled: int
    indexed: int
    documents: int
    claims: int
    images: int


def prebuilt_authorities(directory: Path) -> tuple[Path, Path]:
    """(canonical bundle, L0 dump) — or a loud failure naming what is missing.

    Both or neither: half a prebuilt library restores into claims whose citations point at
    sources that do not exist, which is exactly the fabrication the architecture forbids."""
    bundle = Path(directory) / BUNDLE_NAME
    dump = Path(directory) / L0_DUMP_NAME
    missing = [str(p) for p in (bundle, dump) if not p.is_file()]
    if missing:
        raise PrebuiltUnavailable(
            "not a prebuilt library — missing: " + ", ".join(missing)
        )
    return bundle, dump


def bundle_head(bundle: Path) -> str | None:
    """The commit a canonical bundle carries, or None when it cannot be read as a bundle.

    The identity of a prebuilt library: two restores of the same bundle name the same commit, so
    an already-restored tenant can be recognized as an idempotent re-run rather than guessed at.
    """
    result = subprocess.run(
        ["git", "bundle", "list-heads", str(bundle)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        sha = line.split()[0] if line.split() else ""
        if len(sha) == 40:
            return sha
    return None


def repo_head(repo: Path) -> str | None:
    """A canonical repository's HEAD sha, or None when it has none."""
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def restore_refusal(
    *,
    canonical_head: str | None,
    bundle_head: str | None,
    existing_source_ids: set[str],
    dump_source_ids: set[str],
) -> str | None:
    """Why this tenant must not be restored into — or None when it may be.

    A restore writes one authority and settles work against it. That is only ever correct on an
    empty tenant or on a provable re-run of the SAME bundle; on anything else it would mix two
    unrelated bodies of work and report the mixture as finished. Pure on purpose: the decision is
    the interesting part and it is testable without a database.
    """
    foreign = sorted(existing_source_ids - dump_source_ids)
    if foreign:
        shown = ", ".join(foreign[:3]) + (" …" if len(foreign) > 3 else "")
        return (
            f"this tenant already holds {len(foreign)} source(s) this prebuilt library does not "
            f"ship ({shown}). A restore settles queued work as done and marks sources digested, "
            "which would claim a compile happened for material that was never compiled. Restore "
            "into an empty tenant (wipe `data/` and the tenant's rows) or compile your own "
            "material instead."
        )
    if canonical_head is None:
        return None  # nothing of anyone's is here yet
    if bundle_head is None:
        return (
            "a canonical library is already here and the bundle's head cannot be read, so this "
            "cannot be shown to be a re-run of the same prebuilt library. Refusing rather than "
            "layering one build's L0 under another build's canonical."
        )
    if canonical_head != bundle_head:
        return (
            f"a different canonical library is already here (HEAD {canonical_head[:12]}, bundle "
            f"{bundle_head[:12]}). Canonical is authoritative and is never overwritten, so a "
            "restore would leave claims from one build citing L0 from another."
        )
    return None  # same bundle, already restored — an idempotent re-run


async def assert_restorable(
    ctx: AppContext, user_id: UserId, bundle: Path, dump_source_ids: set[str]
) -> None:
    """Refuse a restore into a tenant that holds anything this bundle did not ship."""
    target = ctx.canonical.repo_path(user_id)
    head = (
        await asyncio.to_thread(repo_head, target) if (target / ".git").is_dir() else None
    )
    existing = {str(raw.source_id) for raw in await ctx.store.list(user_id)}
    refusal = restore_refusal(
        canonical_head=head,
        bundle_head=await asyncio.to_thread(bundle_head, bundle),
        existing_source_ids=existing,
        dump_source_ids=dump_source_ids,
    )
    if refusal is not None:
        raise PrebuiltUnavailable(refusal)


async def clone_canonical(ctx: AppContext, user_id: UserId, bundle: Path) -> bool:
    """Clone the canonical bundle into this user's canonical repository.

    Returns False when a repository is already there: a restore never overwrites a canonical
    library, because canonical is authoritative and this function's input is a copy of
    someone's build. Wipe `data/` first if that is what you meant.

    The repository's git identity is pinned locally, mirroring what `GitCanonicalStore`
    writes when it creates a repository itself, so later commits in the restored library
    never depend on (or record) the machine's git config."""
    target = ctx.canonical.repo_path(user_id)
    if (target / ".git").is_dir():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)

    def _clone() -> None:
        subprocess.run(
            ["git", "clone", "--quiet", str(bundle), str(target)],
            capture_output=True,
            text=True,
            check=True,
        )
        for key, value in (
            ("user.email", "pneuma_knowledge@local"),
            ("user.name", "pneuma-knowledge"),
        ):
            subprocess.run(
                ["git", "-C", str(target), "config", key, value],
                capture_output=True,
                text=True,
                check=True,
            )

    await asyncio.to_thread(_clone)
    return True


def read_dump(dump: Path) -> list[NormalizedSource]:
    """The build-time L0 rows, verbatim. Read once and passed on: the ids in it are both what
    gets loaded and what bounds everything this restore is allowed to touch."""
    with gzip.open(dump, "rt", encoding="utf-8") as handle:
        return [
            NormalizedSource.model_validate(json.loads(line))
            for line in handle
            if line.strip()
        ]


def read_prebuilt_media(
    directory: Path, rows: list[NormalizedSource]
) -> dict[str, tuple[bytes, str]]:
    """Read and verify every original image required by a prebuilt L0 dump.

    Validation completes before restore writes anything. The dump's old tenant-scoped object
    keys are deliberately ignored: restored objects receive keys owned by the target tenant.
    """

    declared: dict[str, tuple[str, int]] = {}
    for row in rows:
        for block in row.blocks:
            for image in block.images:
                value = (image.mime_type, image.size_bytes)
                previous = declared.setdefault(image.sha256, value)
                if previous != value:
                    raise PrebuiltUnavailable(
                        f"image {image.sha256} has conflicting MIME type or size declarations"
                    )
    if not declared:
        return {}

    root = Path(directory) / L0_MEDIA_DIR_NAME / "sha256"
    result: dict[str, tuple[bytes, str]] = {}
    for digest, (mime_type, size_bytes) in declared.items():
        payload = root / digest[:2] / digest
        if not payload.is_file():
            raise PrebuiltUnavailable(
                f"image-bearing prebuilt library is missing {payload}"
            )
        data = payload.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise PrebuiltUnavailable(f"prebuilt media sha256 mismatch: {payload}")
        if len(data) != size_bytes:
            raise PrebuiltUnavailable(f"prebuilt media size mismatch: {payload}")
        if not matches_declared_image_type(data, mime_type):
            raise PrebuiltUnavailable(
                f"prebuilt media does not match declared MIME type {mime_type!r}: {payload}"
            )
        result[digest] = (data, mime_type)
    return result


async def materialize_prebuilt_media(
    ctx: AppContext,
    user_id: UserId,
    rows: list[NormalizedSource],
    objects: dict[str, tuple[bytes, str]],
) -> list[NormalizedSource]:
    """Store verified originals for the target tenant and retarget every L0 manifest."""

    if not objects:
        return rows
    if ctx.media is None:
        raise PrebuiltUnavailable(
            "image-bearing prebuilt library requires a configured media store"
        )
    keys: dict[str, str] = {}
    for digest, (data, mime_type) in objects.items():
        keys[digest] = await ctx.media.put(
            user_id, data, sha256=digest, mime_type=mime_type
        )

    retargeted: list[NormalizedSource] = []
    for row in rows:
        blocks = []
        for block in row.blocks:
            images = [
                image.model_copy(update={"storage_key": keys[image.sha256]})
                for image in block.images
            ]
            blocks.append(block.model_copy(update={"images": images}))
        retargeted.append(row.model_copy(update={"blocks": blocks}))
    return retargeted


async def load_l0(
    ctx: AppContext, user_id: UserId, rows: list[NormalizedSource]
) -> int:
    """Load the build-time L0 rows verbatim. Returns how many sources were loaded.

    The store deduplicates on content checksum and returns the existing id on a hit, so a
    repeated restore is idempotent. An id that comes back DIFFERENT from the dumped one is
    fatal: every citation in the restored canonical addresses the dumped id, so a shifted id
    would silently unbind the whole library."""
    loaded = 0
    for normalized in rows:
        stored = await ctx.store.add(user_id, normalized)
        if str(stored) != str(normalized.raw.source_id):
            raise PrebuiltUnavailable(
                f"source {normalized.raw.source_id} was stored as {stored} — the restored "
                "canonical's citations would no longer bind to it"
            )
        loaded += 1
    return loaded


def settleable_jobs(jobs: list[dict], source_ids: set[str]) -> list[str]:
    """The ids of pending jobs this restore covers — and no others.

    A job is covered when it is still pending and every source it names is in the dump. A job
    over material the bundle does not ship is somebody's real, unfinished work: settling it would
    report a compile that never ran. A pending job that names no source at all (an `evolve`
    round) is likewise not this restore's business.
    """
    out: list[str] = []
    for job in jobs:
        if job.get("status") not in ("queued", "claimed"):
            continue
        payload = job.get("payload") or {}
        named = {str(sid) for sid in payload.get("source_ids", [])}
        if "source_id" in payload:
            named.add(str(payload["source_id"]))
        if named and named <= source_ids:
            out.append(job["job_id"])
    return out


async def settle_queue(ctx: AppContext, user_id: UserId, source_ids: set[str]) -> int:
    """Settle the pending work this bundle covers, and mark ITS sources digested.

    Loading L0 enqueues nothing (it writes the store directly), but a restore may land on a
    library that already had work queued for these same sources — and every restored source must
    read as compiled, or the next `compile` treats a finished library as pending and pays to redo
    it. Draining that queue would need a chat model; deleting it would erase the record. Settling
    is the honest third option, and the reason lands in each job's detail.

    Scoped to `source_ids`, which is the dump's own id set. The tenant is already known to hold
    nothing else (`assert_restorable`), so this is belt and braces — and it is the belt that
    keeps "this bundle's work" and "the user's work" separable if that ever changes.
    """
    jobs = await ctx.store.list_jobs(user_id)
    settled = 0
    for job_id in settleable_jobs(jobs, source_ids):
        await ctx.store.complete(user_id, job_id, ok=True, detail=SETTLED_DETAIL)
        settled += 1
    await ctx.store.mark_digested(
        user_id, sorted(source_ids), datetime.now(timezone.utc)
    )
    return settled


async def rebuild_source_indexes(ctx: AppContext, user_id: UserId) -> int:
    """Rebuild L1 + L2 for every source in the store. Returns the source count.

    Same shape as `scripts/ops/rebuild_derived.py`: delete the user's derived state first,
    then rebuild per source through the shared plan dispatch, so a restore and a rebuild
    produce the same indexes."""
    await ctx.lexical.delete_user(user_id)
    await ctx.vectors.delete_chunks(user_id)
    sources = await ctx.store.list(user_id)
    for raw in sources:
        normalized = await ctx.store.get(user_id, raw.source_id)
        await ctx.lexical.index_blocks(user_id, raw.source_id, normalized.blocks)
        chunks = await plan_l2_chunks(ctx, raw.source_id, normalized, user_id)
        if not chunks:
            continue
        await ctx.vectors.upsert_chunks(
            user_id,
            await embed_l2_chunks(ctx, chunks, normalized),
        )
    return len(sources)


async def restore_prebuilt(
    ctx: AppContext,
    user_id: UserId,
    directory: Path,
    *,
    log: Callable[[str], None] | None = None,
) -> PrebuiltRestore:
    """Restore the prebuilt library in `directory` for `user_id`, and report what it did.

    Step order is the correctness argument: the tenant is proven restorable, canonical and L0
    (the authorities) land first, the queue is settled against them, and only then is derived
    state rebuilt — a projection built before L0 existed would have nothing to bind its claims
    to."""
    bundle, dump = prebuilt_authorities(Path(directory))
    note = log or (lambda _message: None)

    rows = await asyncio.to_thread(read_dump, dump)
    media_objects = await asyncio.to_thread(read_prebuilt_media, Path(directory), rows)
    dump_ids = {str(row.raw.source_id) for row in rows}
    # Before anything is written: this bundle's work and the tenant's own work must not be the
    # same restore. A refusal here is the whole guard — every step below assumes it passed.
    await assert_restorable(ctx, user_id, bundle, dump_ids)

    cloned = await clone_canonical(ctx, user_id, bundle)
    note(
        f"  canonical restored from {bundle.name}"
        if cloned
        else "  canonical already present at this bundle's commit — kept as it is (authoritative)"
    )
    rows = await materialize_prebuilt_media(ctx, user_id, rows, media_objects)
    if media_objects:
        note(f"  L0 media loaded: {len(media_objects)} immutable image object(s)")
    sources = await load_l0(ctx, user_id, rows)
    note(f"  L0 loaded: {sources} source(s), ids bound to the canonical's citations")
    settled = await settle_queue(ctx, user_id, dump_ids)
    note(f"  queue settled: {settled} job(s) completed as '{SETTLED_DETAIL}'")
    indexed = await rebuild_source_indexes(ctx, user_id)
    note(f"  L1/L2 rebuilt for {indexed} source(s)")
    claims = await rebuild_projection(ctx, user_id, allow_wipe=True)
    documents = len(await ctx.canonical.list(user_id))
    note(f"  L3 projection rebuilt: {claims} claim(s) from {documents} document(s)")
    return PrebuiltRestore(
        canonical_cloned=cloned,
        sources=sources,
        jobs_settled=settled,
        indexed=indexed,
        documents=documents,
        claims=claims,
        images=len(media_objects),
    )
