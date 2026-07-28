#!/usr/bin/env python
"""Repair deterministic canonical Markdown drift, then reconcile derived claims.

The migration is intentionally narrow: it repairs repeated heading markers such as
``## ## 行动项`` and normalizes accepted citation spellings such as ``¶1-¶3`` to
``¶1-3``. A truncated source id is expanded only when it uniquely prefixes one source
owned by the same user. Claim prose, anchors, block spans and frontmatter remain unchanged.
Canonical Git makes the repair recoverable; the derived projection is reconciled from
the resulting snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401

from pneuma_knowledge_core.compile.anchor_ops import (
    normalize_repeated_heading_markers,
)
from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.domain.canonical import (
    normalize_canonical_citation_markers,
    resolve_canonical_citation_source_prefixes,
)
from pneuma_knowledge_core.domain.ids import UserId, extract_anchors
from pneuma_knowledge_core.recall.projection import project_snapshot_claims
from pneuma_knowledge_service.experiments.opc_84d_evaluation import canonical_quality
from pneuma_knowledge_service.projection import sync_projection
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context


def _projected_rows(documents: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "document_path": claim.document_path,
            "anchor": str(claim.anchor),
            "section_path": list(claim.section_path),
            "text": claim.text,
            "citations": [
                citation.model_dump(mode="json") for citation in claim.citations
            ],
        }
        for claim in project_snapshot_claims(documents)
    ]


async def run(user_id: str, *, apply: bool) -> dict[str, Any]:
    user = UserId(user_id)
    ctx = await build_context(Settings(evolve_auto_trigger=False))
    try:
        documents = await ctx.canonical.list(user)
        postgres_before = await ctx.store.list_canonical_claims(user)
        source_bounds = await ctx.store.block_counts(user)
        files: dict[str, str] = {}
        changes_by_path: dict[str, dict[str, int]] = {}
        unresolved_by_path: dict[str, list[str]] = {}
        for document in documents:
            repaired, heading_changes = normalize_repeated_heading_markers(
                document.body
            )
            repaired, citation_changes = normalize_canonical_citation_markers(
                repaired
            )
            repaired, source_prefix_changes, unresolved = (
                resolve_canonical_citation_source_prefixes(
                    repaired, source_bounds
                )
            )
            if unresolved:
                unresolved_by_path[document.path] = sorted(unresolved)
            if not heading_changes and not citation_changes and not source_prefix_changes:
                continue
            if extract_anchors(repaired) != extract_anchors(document.body):
                raise RuntimeError(
                    f"heading repair changed anchors unexpectedly: {document.path}"
                )
            files[document.path] = render_document(document.frontmatter, repaired)
            changes_by_path[document.path] = {
                "heading_markers": heading_changes,
                "citation_markers": citation_changes,
                "citation_source_prefixes": source_prefix_changes,
            }

        result: dict[str, Any] = {
            "schema": "pneuma.canonical-format-repair/v1",
            "user_id": user_id,
            "apply": apply,
            "documents_scanned": len(documents),
            "documents_changed": len(files),
            "heading_markers_repaired": sum(
                row["heading_markers"] for row in changes_by_path.values()
            ),
            "citation_markers_normalized": sum(
                row["citation_markers"] for row in changes_by_path.values()
            ),
            "citation_source_prefixes_repaired": sum(
                row["citation_source_prefixes"] for row in changes_by_path.values()
            ),
            "unresolved_citation_source_ids": dict(sorted(unresolved_by_path.items())),
            "changes_by_path": dict(sorted(changes_by_path.items())),
            "snapshot_ref": None,
            "projection": None,
            "before": {
                "canonical": canonical_quality(_projected_rows(documents)),
                "postgres": canonical_quality(postgres_before),
            },
            "after": None,
        }
        if not apply:
            return result

        if unresolved_by_path:
            raise RuntimeError(
                "refusing ambiguous or unknown citation source repair: "
                + json.dumps(unresolved_by_path, ensure_ascii=False, sort_keys=True)
            )

        if files:
            snapshot = await ctx.canonical.commit_patch(
                user,
                files,
                message="repair deterministic canonical formatting and citation prefixes",
            )
            snapshot_ref = snapshot.ref
        else:
            snapshots, _, _ = await ctx.canonical.snapshots_page(user, limit=1)
            snapshot_ref = snapshots[0].ref if snapshots else None

        if snapshot_ref is not None:
            projection = await sync_projection(ctx, user, snapshot_ref)
            result["snapshot_ref"] = snapshot_ref
            result["projection"] = asdict(projection)
            repaired_documents = await ctx.canonical.list(user)
            postgres_after = await ctx.store.list_canonical_claims(user)
            result["after"] = {
                "canonical": canonical_quality(
                    _projected_rows(repaired_documents)
                ),
                "postgres": canonical_quality(postgres_after),
            }
        return result
    finally:
        await ctx.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the recoverable canonical repair and reconcile projections",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    result = asyncio.run(run(args.user, apply=args.apply))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
