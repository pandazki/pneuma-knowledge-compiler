"""Builders for hand-written trajectories.

The metric tests construct 2-3 checkpoints by hand rather than compiling anything: a metric
is a pure function of artifacts, so the cheapest honest test is a snapshot sequence whose
answer is obvious by inspection. `build_trajectory` is the same seam a live loader uses, so
these fixtures exercise the production path, not a test-only shortcut.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pneuma_knowledge_eval.artifacts import (
    Snapshot,
    SourceRecord,
    Trajectory,
    build_trajectory,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PRESET_BUNDLE = REPO_ROOT / "examples" / "data" / "preset" / "u-opc-lin"
CORPUS_84D = REPO_ROOT / "examples" / "data" / "opc-84d"
FROZEN_V2_TRUTH = (
    REPO_ROOT / "docs" / "experiments" / "opc-84d-v2" / "qa" / "evaluation-v2-truth.json"
)

EPOCH = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


def claim(text: str, anchor: str, *, cite: str | None = None) -> str:
    """One claim block: prose, optional citation marker, mandatory anchor comment."""
    marker = f" [cite: {cite}]" if cite else ""
    return f"{text}{marker} <!-- c:{anchor} -->"


def document(
    path: str,
    blocks: Sequence[str],
    *,
    type_: str = "topic",
    section: str = "Notes",
    links: Sequence[str] = (),
) -> str:
    """A canonical file: frontmatter fence, a heading, one section of claim blocks."""
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    doc_id = hashlib.sha256(f"doc:{path}".encode("utf-8")).hexdigest()[:12]
    body_blocks = list(blocks)
    for target in links:
        digest = hashlib.sha256(f"{path}:{target}".encode("utf-8")).hexdigest()[:8]
        body_blocks.append(claim(f"See [related]({target}).", digest))
    return (
        f"---\ndoc_id: {doc_id}\nslug: {slug}\ntype: {type_}\n---\n\n"
        f"# {slug}\n\n## {section}\n\n" + "\n\n".join(body_blocks) + "\n"
    )


def source(source_id: str, blocks: Sequence[str]) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        kind="meeting",
        title=f"source {source_id}",
        created_at=EPOCH,
        blocks=tuple(blocks),
    )


def trajectory(
    snapshots: Sequence[Mapping[str, str]],
    *,
    bundle_id: str = "fixture",
    sources: Mapping[str, SourceRecord] | None = None,
    consumed: Sequence[Sequence[str]] | None = None,
    subjects: Sequence[str] | None = None,
    evolve_tasks: Sequence[Mapping[str, object]] = (),
) -> Trajectory:
    """Build a Trajectory from file tables, one per round.

    `consumed` declares which source ids each round compiled (the compression denominator);
    `subjects` overrides the commit subject, which is how a non-compile (evolve) commit is
    expressed — the loader identifies those structurally, by the absence of a job id.
    """
    built: list[Snapshot] = []
    for index, files in enumerate(snapshots):
        subject = subjects[index] if subjects is not None else f"compile {index:032x}"
        job_id = subject.split(" ", 1)[1] if subject.startswith("compile ") else None
        built.append(
            Snapshot(
                ref=f"{index:040x}",
                files=dict(files),
                committed_at=EPOCH + timedelta(days=7 * index),
                subject=subject,
                trailers={"Skill-Version": "v1"},
                job_id=job_id,
                consumed_source_ids=tuple(consumed[index]) if consumed else (),
            )
        )
    return build_trajectory(bundle_id, built, sources=sources, evolve_tasks=list(evolve_tasks))
