"""Checkpoint extraction: a compiled knowledge base read back as a trajectory.

WHAT A CHECKPOINT IS
--------------------
Canonical is a per-user git repository and every compile commits exactly once, so the
history IS a free, already-recorded checkpoint sequence — no instrumentation, no replay,
no cost. One `Checkpoint` = one commit = the whole canonical file table at that moment,
plus what that round consumed.

WHY THE LOADERS ARE PURE FILE WORK
----------------------------------
The preset loader reads a shipped bundle: `canonical.tar.gz` unpacks to a real git repo
(walked with `git archive`, one call per commit) and `pg/*.json.gz` are plain table dumps.
Nothing here needs Postgres, Qdrant or Meilisearch to be online, and nothing here calls a
model — which is what makes the mechanical mode CI-runnable and byte-deterministic.

A live stack lands on the SAME `Trajectory` type: `load_git_trajectory` takes the canonical
repo directory as it sits under `settings.canonical_root`, and `build_trajectory` takes
already-materialized snapshots (the seam a live loader or a test fixture uses). The metric
functions therefore cannot tell the two apart — they evaluate artifacts, not the process
that produced them.

L0 IS OPTIONAL, AND SAYS SO
---------------------------
Citation resolvability and the compression ratio need the raw sources. A preset bundle
ships them; a bare canonical repo does not. `Trajectory.sources` is then empty and the
metrics that need it report `unavailable` with a reason instead of quietly reporting a rate
computed against nothing.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from pneuma_knowledge_core.compile.documents import parse_document
from pneuma_knowledge_core.compile.patch import path_allowed
from pneuma_knowledge_core.domain.canonical import (
    CANONICAL_CITATION_MARKER_RE,
    CanonicalDocument,
)
from pneuma_knowledge_core.domain.ids import ANCHOR_MARK_RE, DocumentId, extract_anchors
from pneuma_knowledge_core.recall.projection import (
    ProjectedClaim,
    project_snapshot_claims,
)
from pneuma_knowledge_core.skill import load_builtin_skill

from .errors import EvalInputError

# The two families that exist to catch what no other family owns. Their intake share is the
# misfit-pressure signal in group E: a schema that fits its material keeps them small.
CATCHALL_TEMPLATES = ("memory/topics/{slug}.md", "materials/{slug}.md")

# `compile <job_id>` is the commit subject the compile runner writes.
_COMPILE_SUBJECT_RE = re.compile(r"^compile\s+([0-9a-f]{8,})\s*$")
_TRAILER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_UNIT = "\x1f"
_RECORD = "\x1e"


# ─────────────────────────────────────────────────────────────────────────── artifacts


@dataclass(frozen=True)
class SourceRecord:
    """One L0 source with its ¶ block table — the addressing every citation resolves into."""

    source_id: str
    kind: str
    title: str
    created_at: datetime | None
    blocks: tuple[str, ...]

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def char_count(self) -> int:
        return sum(len(block) for block in self.blocks)


@dataclass(frozen=True)
class Snapshot:
    """A raw canonical file table at one moment: path → file bytes (as text).

    The loader-agnostic input to `build_trajectory`. `files` holds whole documents,
    frontmatter fence included, exactly as committed.
    """

    ref: str
    files: Mapping[str, str]
    committed_at: datetime | None = None
    subject: str = ""
    trailers: Mapping[str, str] = field(default_factory=dict)
    job_id: str | None = None
    consumed_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Checkpoint:
    """One compile checkpoint: the whole canonical snapshot plus what the round consumed."""

    index: int
    ref: str
    label: str
    files: Mapping[str, str]
    committed_at: datetime | None = None
    subject: str = ""
    trailers: Mapping[str, str] = field(default_factory=dict)
    job_id: str | None = None
    consumed_source_ids: tuple[str, ...] = ()

    @cached_property
    def documents(self) -> tuple[CanonicalDocument, ...]:
        """Parsed canonical documents, by path. Frontmatter id spellings are normalized by
        `parse_document`, so a legacy `pneuma_id` document reads as `doc_id` here too."""
        docs: list[CanonicalDocument] = []
        for path in sorted(self.files):
            frontmatter, body = parse_document(self.files[path])
            docs.append(
                CanonicalDocument(
                    doc_id=DocumentId(str(frontmatter.get("doc_id") or path)),
                    path=path,
                    frontmatter=frontmatter,
                    body=body,
                )
            )
        return tuple(docs)

    @cached_property
    def claims(self) -> tuple[ProjectedClaim, ...]:
        """The claim list the L3 index would hold at this checkpoint.

        Reuses the production projection (`recall.projection`) rather than re-segmenting
        markdown here, so "a claim" means exactly what it means at retrieval time."""
        return tuple(project_snapshot_claims(list(self.documents)))

    @cached_property
    def bodies(self) -> Mapping[str, str]:
        return {doc.path: doc.body for doc in self.documents}

    @cached_property
    def anchors_by_path(self) -> Mapping[str, tuple[str, ...]]:
        return {doc.path: tuple(extract_anchors(doc.body)) for doc in self.documents}

    @cached_property
    def anchor_set(self) -> frozenset[str]:
        return frozenset(
            anchor for anchors in self.anchors_by_path.values() for anchor in anchors
        )

    @property
    def canonical_chars(self) -> int:
        """Body characters only: frontmatter is machine bookkeeping, not compiled prose."""
        return sum(len(body) for body in self.bodies.values())

    @cached_property
    def prose_chars(self) -> int:
        """Body characters with the machine markup removed — the honest compression numerator.

        A citation marker (`[cite: <32 hex> ¶0]`) plus an anchor comment (`<!-- c:xxxxxxxx -->`)
        costs ~40 characters per claim and is addressing, not prose. On a small knowledge base
        that overhead alone can dominate the raw body size, so a compression ratio measured
        against `canonical_chars` would report the compiler as verbose when it is in fact the
        provenance backbone being counted.
        """
        total = 0
        for body in self.bodies.values():
            stripped = CANONICAL_CITATION_MARKER_RE.sub("", body)
            stripped = ANCHOR_MARK_RE.sub("", stripped)
            total += len(stripped.strip())
        return total


@dataclass(frozen=True)
class Trajectory:
    """A checkpoint sequence plus the evidence needed to audit it.

    `sources` may be empty (a bare canonical repo carries no L0); metrics that need it say
    so instead of dividing by zero. `events` / `evolve_tasks` are the raw table rows when a
    bundle ships them — evaluation reads them, never writes them.
    """

    bundle_id: str
    checkpoints: tuple[Checkpoint, ...]
    sources: Mapping[str, SourceRecord] = field(default_factory=dict)
    path_templates: tuple[str, ...] = ()
    events: tuple[Mapping[str, Any], ...] = ()
    evolve_tasks: tuple[Mapping[str, Any], ...] = ()
    origin: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.checkpoints:
            raise EvalInputError(
                f"trajectory {self.bundle_id!r} has no checkpoints: nothing to evaluate"
            )

    @property
    def head(self) -> Checkpoint:
        return self.checkpoints[-1]

    @property
    def has_l0(self) -> bool:
        return bool(self.sources)

    def source_bounds(self) -> Mapping[str, int]:
        """source_id → block count, the interval every citation must fall inside."""
        return {sid: record.block_count for sid, record in self.sources.items()}

    def l0_chars_through(self, index: int) -> int | None:
        """Raw characters of every source consumed up to and including checkpoint `index`.

        None when L0 is absent, or when no checkpoint declares what it consumed — the
        compression ratio has no honest denominator in either case.
        """
        if not self.sources:
            return None
        consumed: set[str] = set()
        for checkpoint in self.checkpoints[: index + 1]:
            consumed.update(checkpoint.consumed_source_ids)
        if not consumed:
            return None
        return sum(
            self.sources[sid].char_count for sid in sorted(consumed) if sid in self.sources
        )


# ───────────────────────────────────────────────────────────────── structure helpers


def family_of(path: str, path_templates: Sequence[str]) -> str | None:
    """The path template `path` belongs to, or None when it is owned by no family.

    Uses the gate's own template matcher (`compile.patch`) so "which family" here means
    exactly what path ownership means at write time.
    """
    for template in path_templates:
        if path_allowed(path, [template]):
            return template
    return None


def is_catchall(template: str | None) -> bool:
    return template in CATCHALL_TEMPLATES


def unowned_paths(checkpoint: Checkpoint, path_templates: Sequence[str]) -> tuple[str, ...]:
    """Documents matching no template — a gate violation today, possible in old history."""
    if not path_templates:
        return ()
    return tuple(
        path for path in sorted(checkpoint.files) if not path_allowed(path, list(path_templates))
    )


# ───────────────────────────────────────────────────────────────────────── builders


def build_trajectory(
    bundle_id: str,
    snapshots: Sequence[Snapshot],
    *,
    sources: Mapping[str, SourceRecord] | None = None,
    path_templates: Sequence[str] | None = None,
    events: Sequence[Mapping[str, Any]] = (),
    evolve_tasks: Sequence[Mapping[str, Any]] = (),
    origin: Mapping[str, Any] | None = None,
) -> Trajectory:
    """Assemble a Trajectory from already-materialized snapshots (the loader-agnostic seam).

    Checkpoint labels are `r01`, `r02`, … — the round ordinal, which is the axis every
    metric series is reported on.
    """
    checkpoints = tuple(
        Checkpoint(
            index=index,
            ref=snapshot.ref,
            label=f"r{index + 1:02d}",
            files=dict(snapshot.files),
            committed_at=snapshot.committed_at,
            subject=snapshot.subject,
            trailers=dict(snapshot.trailers),
            job_id=snapshot.job_id,
            consumed_source_ids=tuple(snapshot.consumed_source_ids),
        )
        for index, snapshot in enumerate(snapshots)
    )
    templates = tuple(path_templates) if path_templates is not None else _templates_for(checkpoints)
    return Trajectory(
        bundle_id=bundle_id,
        checkpoints=checkpoints,
        sources=dict(sources or {}),
        path_templates=templates,
        events=tuple(events),
        evolve_tasks=tuple(evolve_tasks),
        origin=dict(origin or {}),
    )


def _templates_for(checkpoints: Sequence[Checkpoint]) -> tuple[str, ...]:
    """The skill families in force at HEAD, taken from the commit trailer when present.

    The trailer records `Skill-Version`, so a bundle compiled under v1 is judged against
    v1's families rather than whatever the current default happens to be. An unknown or
    absent version falls back to v1 (the only version whose family list every later version
    is a superset of).
    """
    version = "v1"
    for checkpoint in reversed(checkpoints):
        declared = str(checkpoint.trailers.get("Skill-Version") or "").strip()
        if declared:
            version = declared
            break
    try:
        return tuple(load_builtin_skill(version).path_templates)
    except ValueError:
        return tuple(load_builtin_skill("v1").path_templates)


# ─────────────────────────────────────────────────────────────────────── git loading


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise EvalInputError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return result.stdout


def _commit_records(repo: Path) -> list[tuple[str, datetime | None, str, dict[str, str]]]:
    raw = _git(
        repo,
        "log",
        "--reverse",
        "--topo-order",
        f"--format=%H{_UNIT}%cI{_UNIT}%s{_UNIT}%B{_RECORD}",
    ).decode("utf-8")
    records: list[tuple[str, datetime | None, str, dict[str, str]]] = []
    for chunk in raw.split(_RECORD):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, iso, subject, body = chunk.split(_UNIT, 3)
        committed_at: datetime | None
        try:
            committed_at = datetime.fromisoformat(iso)
        except ValueError:
            committed_at = None
        trailers = {
            key: value
            for key, value in _TRAILER_RE.findall(body)
            # The subject line is not a trailer even when it happens to contain a colon.
            if f"{key}: {value}" != subject.strip()
        }
        records.append((sha, committed_at, subject.strip(), trailers))
    if not records:
        raise EvalInputError(f"canonical repo {repo} has no commits")
    return records


def _snapshot_files(repo: Path, sha: str) -> dict[str, str]:
    """Every canonical markdown file at `sha`, read in one `git archive` call."""
    blob = _git(repo, "archive", "--format=tar", sha)
    files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.endswith(".md"):
                continue
            handle = tar.extractfile(member)
            if handle is None:  # pragma: no cover - tar members are regular files
                continue
            files[member.name] = handle.read().decode("utf-8")
    return files


def _job_id_of(subject: str) -> str | None:
    match = _COMPILE_SUBJECT_RE.match(subject)
    return match.group(1) if match else None


def load_git_trajectory(
    repo: Path | str,
    *,
    bundle_id: str | None = None,
    sources: Mapping[str, SourceRecord] | None = None,
    consumed_by_job: Mapping[str, Sequence[str]] | None = None,
    events: Sequence[Mapping[str, Any]] = (),
    evolve_tasks: Sequence[Mapping[str, Any]] = (),
    origin: Mapping[str, Any] | None = None,
) -> Trajectory:
    """Walk a canonical git repo into a Trajectory. Read-only; never writes to the repo."""
    repo = Path(repo)
    if not (repo / ".git").exists():
        raise EvalInputError(f"not a canonical git repository: {repo}")
    snapshots: list[Snapshot] = []
    for sha, committed_at, subject, trailers in _commit_records(repo):
        job_id = _job_id_of(subject)
        consumed = tuple((consumed_by_job or {}).get(job_id or "", ()))
        snapshots.append(
            Snapshot(
                ref=sha,
                files=_snapshot_files(repo, sha),
                committed_at=committed_at,
                subject=subject,
                trailers=trailers,
                job_id=job_id,
                consumed_source_ids=consumed,
            )
        )
    return build_trajectory(
        bundle_id or repo.name,
        snapshots,
        sources=sources,
        events=events,
        evolve_tasks=evolve_tasks,
        origin=origin,
    )


# ──────────────────────────────────────────────────────────────────── preset loading


def _read_gz_json(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with gzip.open(path, "rb") as handle:
        payload = json.loads(handle.read())
    if not isinstance(payload, list):  # pragma: no cover - dumps are row lists
        raise EvalInputError(f"preset dump {path.name} is not a row list")
    return payload


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _sources_from_dumps(pg_dir: Path) -> dict[str, SourceRecord]:
    block_rows = _read_gz_json(pg_dir / "blocks.json.gz")
    by_source: dict[str, dict[int, str]] = {}
    for row in block_rows:
        by_source.setdefault(str(row["source_id"]), {})[int(row["block_index"])] = str(
            row["text"]
        )
    records: dict[str, SourceRecord] = {}
    for row in _read_gz_json(pg_dir / "sources.json.gz"):
        sid = str(row["source_id"])
        blocks = by_source.get(sid, {})
        # Index by position: a gap would silently shift every later ¶ locator, so a
        # non-contiguous block table is a loud input error rather than a padded list.
        if blocks and sorted(blocks) != list(range(len(blocks))):
            raise EvalInputError(
                f"source {sid} has a non-contiguous block table: {sorted(blocks)[:8]}…"
            )
        records[sid] = SourceRecord(
            source_id=sid,
            kind=str(row.get("kind") or ""),
            title=str(row.get("title") or ""),
            created_at=_parse_timestamp(row.get("created_at")),
            blocks=tuple(blocks[index] for index in range(len(blocks))),
        )
    return records


def load_preset_trajectory(bundle: Path | str) -> Trajectory:
    """Load a shipped preset bundle (`examples/data/preset/<friendly>`) into a Trajectory.

    Pure file work: the canonical tar is extracted to a temporary directory, walked, and
    discarded; the `pg/*.json.gz` dumps are read straight off disk. No middleware, no
    network, no model.
    """
    bundle = Path(bundle)
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise EvalInputError(f"no preset manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tar_path = bundle / "canonical.tar.gz"
    if not tar_path.is_file():
        raise EvalInputError(f"no canonical archive at {tar_path}")

    pg_dir = bundle / "pg"
    sources = _sources_from_dumps(pg_dir)
    jobs = _read_gz_json(pg_dir / "compile_jobs.json.gz")
    consumed_by_job = {
        str(job["id"]): tuple(str(sid) for sid in (job.get("payload") or {}).get("source_ids", ()))
        for job in jobs
        if job.get("kind") == "compile"
    }
    events = tuple(_read_gz_json(pg_dir / "compile_events.json.gz"))
    evolve_tasks = tuple(_read_gz_json(pg_dir / "evolve_tasks.json.gz"))

    with tempfile.TemporaryDirectory(prefix="pkc-eval-canonical-") as workdir:
        repo = Path(workdir) / "canonical"
        repo.mkdir(parents=True)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(repo, filter="data")
        trajectory = load_git_trajectory(
            repo,
            bundle_id=str(manifest.get("friendly_id") or bundle.name),
            sources=sources,
            consumed_by_job=consumed_by_job,
            events=events,
            evolve_tasks=evolve_tasks,
            origin={
                "kind": "preset_bundle",
                "bundle_path": str(bundle),
                "source_user_id": manifest.get("source_user_id"),
                "manifest_counts": manifest.get("counts", {}),
            },
        )
    _reconcile_preset(trajectory, manifest)
    return trajectory


def _reconcile_preset(trajectory: Trajectory, manifest: Mapping[str, Any]) -> None:
    """Fail loud when the loaded bundle does not match its own manifest counts.

    A silently short history (a truncated tar, a partial dump) would still produce a
    plausible-looking scorecard — with every rate computed over the wrong denominator.
    """
    counts = manifest.get("counts") or {}
    expected_commits = counts.get("canonical_commits")
    if expected_commits is not None and len(trajectory.checkpoints) != int(expected_commits):
        raise EvalInputError(
            f"preset {trajectory.bundle_id}: manifest declares {expected_commits} canonical "
            f"commits but the archive holds {len(trajectory.checkpoints)}"
        )
    expected_claims = (counts.get("pg") or {}).get("canonical_claims")
    if expected_claims is not None and len(trajectory.head.claims) != int(expected_claims):
        raise EvalInputError(
            f"preset {trajectory.bundle_id}: manifest declares {expected_claims} canonical "
            f"claims but HEAD projects {len(trajectory.head.claims)}"
        )
