"""Assemble canonical + PG audit into the M2 four-view dataset (architecture.md §4, M3b).

The apps/web viewer reads one Dataset shape (workspace / documents / graph / timeline /
journal). This module projects a user's canonical git tree (at an optional snapshot) plus
the PG compile audit (jobs + events) and source inventory into exactly that shape, so the
Library / Graph / History / Process views light up with zero UI rewrite. Everything here
is derived (invariant I2) — fully rebuildable from canonical + PG.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from pneuma_knowledge_core.domain.canonical import (
    CanonicalDocument,
    iter_canonical_citations,
)
from pneuma_knowledge_core.domain.ids import ANCHOR_MARK_RE, UserId, extract_anchors
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.skill import claim_labels_for, load_skill_base

from .skills import read_manifest
from .wiring import AppContext, resolve_model_name

_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_HEADING_RE = re.compile(r"^(#{1,6})\s+")
_MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")


# --------------------------------------------------------------------------- claims


def _anchor_block(lines: list[str], anchor_line: int) -> tuple[int, int]:
    """The natural block [start, end) holding the anchor at anchor_line (mirrors the
    claim-block rule used by anchor_ops)."""
    end = anchor_line + 1
    if _LIST_ITEM_RE.match(lines[anchor_line]):
        return anchor_line, end
    start = anchor_line
    while start > 0:
        prev = lines[start - 1]
        if not prev.strip() or _HEADING_RE.match(prev):
            break
        start -= 1
        if _LIST_ITEM_RE.match(prev):
            break
    return start, end


def _parse_claims(body: str) -> list[dict[str, Any]]:
    """Body markdown → ordered claim records (anchor + kind + text + citations)."""
    lines = body.split("\n")
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        for anchor in ANCHOR_MARK_RE.findall(line):
            if anchor in seen:
                continue
            seen.add(anchor)
            start, end = _anchor_block(lines, i)
            text = "\n".join(lines[start:end]).strip()
            kind = "list_item" if _LIST_ITEM_RE.match(lines[start]) else "paragraph"
            citations = [
                {
                    "source_id": str(citation.source_id),
                    "from": citation.block_start,
                    "to": citation.block_end,
                    "snippet": "",
                    "redaction_state": "included",
                }
                for citation in iter_canonical_citations(text)
            ]
            claims.append(
                {
                    "anchor": anchor,
                    "kind": kind,
                    "text": text,
                    "citations": citations,
                    "flags": [],
                    "notes": {},
                }
            )
    return claims


def _doc_title(doc: CanonicalDocument) -> str:
    slug = str(doc.frontmatter.get("slug", "")).strip()
    if slug:
        return slug
    base = doc.path.rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".md") else base


def _document_record(doc: CanonicalDocument) -> dict[str, Any]:
    return {
        "document_id": str(doc.doc_id) if doc.doc_id else None,
        "path": doc.path,
        "title": _doc_title(doc),
        "frontmatter": dict(doc.frontmatter),
        "body": doc.body,
        "claims": _parse_claims(doc.body),
    }


# ---------------------------------------------------------------------------- graph


def _resolve_link(from_path: str, href: str) -> str:
    clean = href.split("#")[0]
    base = from_path.split("/")[:-1]
    stack = list(base)
    for part in clean.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if stack:
                stack.pop()
        else:
            stack.append(part)
    return "/".join(stack)


def _build_graph(
    docs: list[CanonicalDocument], sources: list[Any]
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    by_path: dict[str, str] = {}
    for doc in docs:
        did = str(doc.doc_id) if doc.doc_id else doc.path
        by_path[doc.path] = did
        nodes.append(
            {
                "id": did,
                "type": str(doc.frontmatter.get("type") or "") or None,
                "path": doc.path,
                "title": _doc_title(doc),
            }
        )
    # source cards
    cited: set[str] = set()
    for doc in docs:
        cited.update(
            str(citation.source_id) for citation in iter_canonical_citations(doc.body)
        )
    for raw in sources:
        sid = str(raw.source_id)
        nodes.append(
            {
                "id": f"src:{sid}",
                "type": "source",
                "path": raw.title,
                "title": raw.title,
            }
        )

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(src: str, tgt: str, etype: str) -> None:
        key = (src, tgt, etype)
        if key in seen:
            return
        seen.add(key)
        edges.append({"source": src, "target": tgt, "type": etype})

    for doc in docs:
        did = by_path[doc.path]
        # inter-document markdown links
        for m in _MD_LINK_RE.finditer(doc.body):
            target = _resolve_link(doc.path, m.group(1))
            if target in by_path and by_path[target] != did:
                add_edge(did, by_path[target], "link")
        # citations → source cards
        for citation in iter_canonical_citations(doc.body):
            add_edge(did, f"src:{citation.source_id}", "relationship")

    return {"schema_version": 2, "nodes": nodes, "edges": edges}


# ------------------------------------------------------------------------- timeline


def _job_status(job: dict[str, Any]) -> str:
    if job["status"] != "done":
        return "running"
    return "compiled" if job.get("ok") else "failed"


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None else None


async def _build_timeline(
    ctx: AppContext,
    user_id: UserId,
    sources: list[Any],
    by_path: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    jobs_raw = await ctx.store.list_jobs(user_id)
    events = await ctx.store.list_compile_events(user_id)

    snapshots = [
        {
            "source_id": str(r.source_id),
            "source_type": r.kind,
            "captured_at": _iso(r.created_at) or "",
            "checksum": r.checksum,
            "source_class": r.source_class,
        }
        for r in sources
    ]

    jobs = [
        {
            "job_id": j["job_id"],
            "status": _job_status(j),
            "patch_id": j.get("snapshot_ref"),
            "ts": _iso(j.get("completed_at")) or _iso(j.get("created_at")),
        }
        for j in jobs_raw
    ]

    # events grouped by job, in stored order.
    events_by_job: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        events_by_job.setdefault(e["job_id"], []).append(e)

    job_meta = {j["job_id"]: j for j in jobs_raw}
    # chronological (oldest first) so first-touch = created.
    ordered_jobs = sorted(
        (jid for jid in events_by_job),
        key=lambda jid: (job_meta[jid].get("completed_at") or job_meta[jid]["created_at"]),
    )
    path_seen: set[str] = set()
    patches: list[dict[str, Any]] = []
    journal: list[dict[str, Any]] = []

    for jid in ordered_jobs:
        jevents = events_by_job[jid]
        meta = job_meta[jid]
        snapshot_ref = meta.get("snapshot_ref") or jevents[0]["snapshot_ref"]
        ts = _iso(meta.get("completed_at")) or _iso(meta["created_at"])
        source_ids = [str(s) for s in (meta.get("payload") or {}).get("source_ids", [])]

        # documents touched, with change_type (first-ever touch = created).
        doc_changes: list[dict[str, Any]] = []
        changed_paths: list[str] = []
        for path in dict.fromkeys(e["path"] for e in jevents):
            changed_paths.append(path)
            change_type = "modified" if path in path_seen else "created"
            path_seen.add(path)
            doc_changes.append(
                {
                    "document_id": by_path.get(path),
                    "path": path,
                    "change_type": change_type,
                }
            )

        claims = [
            {
                "anchor": {"document_id": by_path.get(e["path"]), "anchor": e["anchor"]},
                "flags": [],
                "note": e["type"],
            }
            for e in jevents
        ]

        patches.append(
            {
                "patch_id": snapshot_ref,
                "job_id": jid,
                "ts": ts,
                "base_commit": None,
                "changed_paths": changed_paths,
                "documents": doc_changes,
                "sources_consumed": source_ids,
                "skill_version": None,
                "effort": None,
                "claims": claims,
                "escalations": [],
                "merges": [],
                "flag_counts": {},
                "lineage": {
                    "model": resolve_model_name(ctx.settings, "compile"),
                    "tokens": None,
                },
            }
        )

        for idx, e in enumerate(jevents):
            journal.append(
                {
                    "event_id": f"{jid}-{idx}",
                    "ts": _iso(e["created_at"]) or ts or "",
                    "job_id": jid,
                    "patch_id": snapshot_ref,
                    "type": e["type"],
                    "payload": {"path": e["path"], "anchor": e["anchor"]},
                }
            )
        journal.append(
            {
                "event_id": f"{jid}-commit",
                "ts": ts or "",
                "job_id": jid,
                "patch_id": snapshot_ref,
                "type": "patch_committed",
                "payload": {"documents": len(changed_paths), "claims": len(jevents)},
            }
        )

    timeline = {
        "schema_version": 2,
        "snapshots": snapshots,
        "jobs": jobs,
        "patches": patches,
        "bundle_versions": [],
    }
    return timeline, journal


# ------------------------------------------------------------------------ assemble


async def build_dataset(
    ctx: AppContext,
    user_id: UserId,
    *,
    at: str | None = None,
    audit: bool = True,
) -> dict[str, Any]:
    """Project canonical (at optional snapshot ref) + PG audit into the viewer Dataset."""
    ref = SnapshotRef(ref=at) if at else None
    docs, sources = await asyncio.gather(
        ctx.canonical.list(user_id, at=ref),
        ctx.store.list(user_id),
    )

    by_path = {
        d.path: (str(d.doc_id) if d.doc_id else d.path) for d in docs
    }

    documents = {
        "schema_version": 2,
        "documents": [_document_record(d) for d in docs],
    }
    graph = _build_graph(docs, sources)
    if audit:
        timeline, journal = await _build_timeline(ctx, user_id, sources, by_path)
    else:
        # Library / Graph consume only canonical state. Full audit remains available
        # through the paged History endpoint, so do not duplicate its unbounded job
        # and event lists into this read.
        timeline = {
            "schema_version": 2,
            "snapshots": [],
            "jobs": [],
            "patches": [],
            "bundle_versions": [],
        }
        journal = []

    types = sorted({str(d.frontmatter.get("type") or "") for d in docs} - {""})
    ontology = types + (["source"] if sources else [])
    workspace = {
        "schema_version": 2,
        "workspace_id": str(user_id),
        "export_policy": "full",
        "domains": [
            {
                "domain_id": "personal-knowledge",
                "skill_version": None,
                "ontology": ontology,
            }
        ],
    }

    # Claim-prefix vocabulary the owner's effective skill declares (§5 strength tiers). Rides
    # the dataset top-level meta so the dataset-driven Library/History can lift the literal
    # prefix into a structured badge without a second /skill request. Resolved off the base
    # version (from a persisted manifest, else the settings default) rather than the full
    # skill_for_user path — a read projection must not materialize a manifest or derive
    # packs. Packs are additive, so the base's declaration equals the composed skill's
    # (matches GET /skill's claim_labels).
    manifest = await read_manifest(ctx, user_id)
    base_version = str(
        (manifest or {}).get("base_version") or ctx.settings.user_schema_base_version
    )
    skill = load_skill_base(base_version)
    claim_labels = [label.model_dump() for label in claim_labels_for(skill)]

    return {
        "workspace": workspace,
        "documents": documents,
        "graph": graph,
        "timeline": timeline,
        "journal": journal,
        "claim_labels": claim_labels,
    }
