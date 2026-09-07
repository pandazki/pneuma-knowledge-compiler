"""The read half of the HTTP API, as commands — the Steward's eyes (§5.1).

Every command here answers a question the browser can already ask, through the SAME service
functions its route calls. Nothing goes over HTTP: a Steward working in the project has the
adapters in hand, and a CLI that shelled out to its own API would be a second deployment to
keep alive. Nothing is added to core that is only about printing, either — what a page looks
like when the compile model reads it is `render_document`, what the lanes open with is
`render_canonical_glance`, and a command that rendered its own would be showing the Steward a
library nobody else sees.

Two output shapes and one rule about them: `--json` is the machine-readable form a workflow
branches on, and the default is prose for a person (and for an agent, which reads prose
perfectly well). Both come out of ONE builder per command, so they cannot describe different
state.

Exit codes are the same vocabulary `pkc draft` uses: 0 ok · 1 nothing to show (no such page,
no such source, an empty answer) · 2 refused (an argument that does not parse, a lane this
deployment cannot run) · 4 findings (`pkc library check` alone).
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, TextIO

from pneuma_knowledge_core.canonical_glance import render_canonical_glance
from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.compile.supersession import block_by_anchor, chains
from pneuma_knowledge_core.domain.archive import (
    any_archived,
    is_archived_path,
    live_documents,
)
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.recall.archive_filter import archive_view
from pneuma_knowledge_core.recall.fast import FastEvidence, fast_recall, message_text
from pneuma_knowledge_core.recall.rag import rag_recall

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_REFUSED = 2

#: `¶3`, `¶3-7`, `3-7` and `3 7` all address the same span. The citation grammar is the one
#: the whole system speaks (I4), so it is what a locator is typed in; the bare forms exist
#: because a shell eats `¶` on some keyboards and refusing over a pilcrow would be theatre.
_SPAN_RE = re.compile(r"^\s*¶?\s*(?P<start>\d+)(?:\s*[-–\s]\s*(?P<end>\d+))?\s*$")


@dataclass
class ReadRuntime:
    """What every read command needs, injected rather than looked up.

    `ctx` is the AppContext the API and the worker run on — the same adapters, resolved from
    the same settings. The tests hand in a stand-in carrying only the ports the command under
    test calls, which is what lets the whole read surface be exercised keyless.
    """

    user_id: UserId
    ctx: Any
    as_json: bool = False
    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)


def _emit(rt: ReadRuntime, payload: Any, lines: list[str]) -> None:
    """One state, two renderings. `--json` prints the payload; the default prints the lines."""
    if rt.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), file=rt.out)
    else:
        for line in lines:
            print(line, file=rt.out)


def _refuse(rt: ReadRuntime, message: str) -> int:
    print(message, file=rt.err)
    return EXIT_REFUSED


def parse_span(text: str) -> tuple[int, int] | None:
    """`¶a-b` → `(a, b)`; None when the argument is not a span at all."""
    match = _SPAN_RE.match(str(text or ""))
    if match is None:
        return None
    start = int(match.group("start"))
    end = int(match.group("end")) if match.group("end") else start
    return (start, end)


# ───────────────────────────────────────────────────────────────────────── glance


async def _glance_text(rt: ReadRuntime, *, include_archived: bool = False) -> str | None:
    """The glance exactly as the answering lanes render it — same documents, same skill,
    same packs, same function. A degradation is silence, not an error: the glance is
    context."""
    ctx = rt.ctx
    documents = await ctx.canonical.list(rt.user_id)
    if not documents:
        return None
    from ..skills import packs_for_user, skill_for_user

    try:
        skill = await skill_for_user(ctx, rt.user_id)
        packs = await packs_for_user(ctx, rt.user_id)
    except Exception:  # noqa: BLE001 — families and blurbs decorate a real document list
        skill, packs = None, []
    # The archive is stated, not inherited: a Steward's glance is the same map every
    # answering lane draws — the present, with a retired subject represented by the record it
    # left, never by its page (docs/design/archive.md §4). `--include-archived` files the
    # archived pages under the family of their LIVE path, after the live ones, labelled —
    # the renderer's own doing, so the flag changes what is passed and never how it is drawn.
    return render_canonical_glance(
        documents, skill, packs=packs, include_archived=include_archived
    )


async def cmd_glance(rt: ReadRuntime, *, include_archived: bool = False) -> int:
    glance = await _glance_text(rt, include_archived=include_archived)
    if not glance:
        print("this library holds no canonical pages yet", file=rt.err)
        return EXIT_NOTHING
    _emit(rt, {"glance": glance, "chars": len(glance)}, [glance])
    return EXIT_OK


# ──────────────────────────────────────────────────────────────────────── canonical


async def cmd_canonical_ls(rt: ReadRuntime, *, include_archived: bool = False) -> int:
    # A document LISTING, so the archive is out by default (docs/design/archive.md §4, second
    # ruling): `canonical.list` reads the whole tree because the compile draft needs it, and
    # this is a face that shows the Owner where knowledge lives NOW. `--include-archived`
    # states the exception and LABELS what it admits, so a listing that holds both is never
    # read as one. `canonical read` and `canonical history` below are unfiltered on purpose —
    # an archived page addressed by name still answers, which is the archive's own promise.
    tree = await rt.ctx.canonical.list(rt.user_id)
    docs = tree if include_archived else live_documents(tree)
    if not docs:
        print("this library holds no canonical pages yet", file=rt.err)
        return EXIT_NOTHING
    items = [
        {
            "path": doc.path,
            "doc_id": str(doc.doc_id),
            "type": str(doc.frontmatter.get("type", "")),
            "chars": len(doc.body),
            # The wire's own field name, on the wire's own terms (`DatasetRecord.archived`):
            # present on every row, true only for a page under `archive/`.
            "archived": is_archived_path(doc.path),
        }
        for doc in sorted(docs, key=lambda d: d.path)
    ]
    _emit(
        rt,
        {"documents": items, "include_archived": include_archived},
        [
            item["path"] + ("  [archived]" if item["archived"] else "")
            for item in items
        ],
    )
    return EXIT_OK


async def cmd_canonical_read(rt: ReadRuntime, path: str) -> int:
    docs = await rt.ctx.canonical.list(rt.user_id)
    doc = next((d for d in docs if d.path == path), None)
    if doc is None:
        print(f"no such page: {path}", file=rt.err)
        return EXIT_NOTHING
    # The compile model's own `read_document` rendering, so the Steward and the model read
    # one page rather than two descriptions of it.
    rendered = render_document(doc.frontmatter, doc.body)
    _emit(rt, {"path": doc.path, "document": rendered}, [rendered])
    return EXIT_OK


async def cmd_canonical_history(
    rt: ReadRuntime, path: str, anchor: str | None = None
) -> int:
    """The supersession chains of one page — or of one anchor on it.

    A chain may cross pages (a claim superseded from another subject's page is still that
    claim's history), so the walk is repository-wide and the FILTER is the page: a chain is
    shown when any link of it lives on `path`.
    """
    docs = await rt.ctx.canonical.list(rt.user_id)
    if not any(d.path == path for d in docs):
        print(f"no such page: {path}", file=rt.err)
        return EXIT_NOTHING
    bodies = {d.path: d.body for d in docs}
    index = block_by_anchor(bodies)
    wanted = str(anchor or "").strip().removeprefix("c:")
    found = []
    for chain in chains(bodies):
        on_page = [a for a in chain if index.get(a, ("", ""))[0] == path]
        if not on_page:
            continue
        if wanted and wanted not in chain:
            continue
        found.append(
            [
                {
                    "anchor": f"c:{a}",
                    "path": index.get(a, ("", ""))[0],
                    "text": index.get(a, ("", ""))[1].strip(),
                }
                for a in chain
            ]
        )
    if not found:
        print(
            f"no supersession chain on {path}"
            + (f" for c:{wanted}" if wanted else "")
            + " — every claim there is its own first statement",
            file=rt.err,
        )
        return EXIT_NOTHING
    lines: list[str] = []
    for chain in found:
        lines.append(" → ".join(link["anchor"] for link in chain))
        for link in chain:
            lines.append(f"  {link['anchor']} [{link['path']}] {link['text']}")
        lines.append("")
    _emit(rt, {"path": path, "chains": found}, lines)
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────── L0


async def cmd_source_ls(
    rt: ReadRuntime,
    *,
    limit: int = 25,
    query: str | None = None,
    kind: str | None = None,
    include_archived: bool = False,
) -> int:
    ctx = rt.ctx
    raws, total, _more = await ctx.store.list_sources_page(
        # The archive-neutral default, stated (docs/design/archive.md §4): a source the Owner
        # retired is excluded from the listing and still answers when addressed by id.
        rt.user_id,
        limit=limit,
        query=query,
        kind=kind,
        include_archived=include_archived,
    )
    if not raws:
        print("no sources match", file=rt.err)
        return EXIT_NOTHING
    ids = [str(r.source_id) for r in raws]
    counts = await ctx.store.block_counts(rt.user_id, ids)
    items = [
        {
            "source_id": str(r.source_id),
            "kind": r.kind,
            "origin": r.origin,
            "title": r.title,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "blocks": counts.get(str(r.source_id), 0),
            # `archived_at` is the mark itself (`SourceOut.archived_at`, present on every row
            # of the HTTP listing); `archived` is the same fact as the boolean every other
            # face on the wire carries, so one reader never has to derive it from the other.
            "archived_at": (
                r.archived_at.isoformat() if getattr(r, "archived_at", None) else None
            ),
            "archived": getattr(r, "archived_at", None) is not None,
        }
        for r in raws
    ]
    _emit(
        rt,
        {"sources": items, "total": total, "include_archived": include_archived},
        [
            f"{i['source_id']}  {i['kind']:<18} ¶0-{max(i['blocks'] - 1, 0)}  {i['title']}"
            + ("  [archived]" if i["archived"] else "")
            for i in items
        ],
    )
    return EXIT_OK


async def cmd_source_show(rt: ReadRuntime, source_id: str) -> int:
    try:
        ns = await rt.ctx.store.get(rt.user_id, SourceId(source_id))
    except KeyError:
        print(f"no such source: {source_id}", file=rt.err)
        return EXIT_NOTHING
    raw = ns.raw
    payload = {
        "source_id": str(raw.source_id),
        "kind": raw.kind,
        "origin": raw.origin,
        "title": raw.title,
        "created_at": raw.created_at.isoformat() if raw.created_at else None,
        "blocks": len(ns.blocks),
        "intake_plan": raw.intake_plan,
        "structure": [
            {
                "path": list(span.path),
                "blocks": [span.start_block, span.end_block],
            }
            for span in ns.structure.sections
        ],
    }
    lines = [
        f"{raw.source_id}  {raw.kind}  {raw.title}",
        f"blocks: ¶0-{max(len(ns.blocks) - 1, 0)}",
    ]
    for span in payload["structure"]:
        lines.append(
            f"  ¶{span['blocks'][0]}-{span['blocks'][1]}  {' / '.join(span['path'])}"
        )
    _emit(rt, payload, lines)
    return EXIT_OK


async def cmd_source_fetch(rt: ReadRuntime, source_id: str, span: str) -> int:
    """Verbatim L0 for one block span. UNCONDITIONAL (I3): no plan, no strategy and no
    visibility state decides whether a cited span resolves."""
    parsed = parse_span(span)
    if parsed is None:
        return _refuse(
            rt, f"not a block span: {span!r} — write it as ¶a-b, or as `a b`"
        )
    start, end = parsed
    try:
        text = await rt.ctx.store.fetch(
            rt.user_id, SourceId(source_id), {"blocks": [start, end]}
        )
    except (KeyError, ValueError) as exc:
        print(str(exc), file=rt.err)
        return EXIT_NOTHING
    _emit(
        rt,
        {"source_id": source_id, "blocks": [start, end], "text": text},
        [text],
    )
    return EXIT_OK


# ────────────────────────────────────────────────────────────────────────── search


async def cmd_search(
    rt: ReadRuntime,
    query: str,
    *,
    mode: str = "fused",
    limit: int = 10,
    include_archived: bool = False,
) -> int:
    """L1, L2 or the RRF fusion the `rag` lane uses — one hit per line, as `sid ¶a-b`.

    `include_archived` rides into each index in the dialect it has (docs/design/archive.md
    §3) and the hits it admits are LABELLED — from the one authority on which source is
    archived, the L0 mark read once per call (`archive_view`), never from a payload flag the
    two backends would each have to be trusted for.
    """
    ctx = rt.ctx
    view = await archive_view(rt.user_id, ctx.store) if include_archived else None
    hits: list[dict[str, Any]] = []
    if mode == "lexical":
        for hit in await ctx.lexical.search(
            rt.user_id, query, limit=limit, include_archived=include_archived
        ):
            hits.append(
                {
                    "source_id": str(hit.source_id),
                    "blocks": [hit.block_index, hit.block_index],
                    "score": float(hit.score),
                    "text": hit.text,
                }
            )
    elif mode == "semantic":
        embedding = (await ctx.embeddings.aembed_documents([query]))[0]
        for hit in await ctx.vectors.search(
            rt.user_id, embedding, limit=limit, include_archived=include_archived
        ):
            hits.append(
                {
                    "source_id": str(hit.source_id),
                    "blocks": [hit.block_start, hit.block_end],
                    "score": float(hit.score),
                    "text": hit.text,
                }
            )
    else:
        for hit in await rag_recall(
            rt.user_id,
            query,
            lexical=ctx.lexical,
            vectors=ctx.vectors,
            embeddings=ctx.embeddings,
            limit=limit,
            include_archived=include_archived,
            # The L0 store, so this mode gets the second half of the archive rule the
            # answering lanes have: the index filters propose, `archive_filter` disposes at
            # assembly (core `recall/rag.py`). Without it the property would rest on a
            # payload flag in two backends.
            content=ctx.store,
        ):
            hits.append(
                {
                    "source_id": str(hit.source_id),
                    "blocks": [hit.block_start, hit.block_end],
                    "score": float(getattr(hit, "score", 0.0)),
                    "text": hit.text,
                }
            )
    if not hits:
        print("nothing found", file=rt.err)
        return EXIT_NOTHING
    for hit in hits:
        hit["archived"] = (
            view.source_archived(hit["source_id"]) if view is not None else False
        )
    _emit(
        rt,
        {
            "mode": mode,
            "query": query,
            "include_archived": include_archived,
            "hits": hits,
        },
        [
            f"{h['source_id']} ¶{h['blocks'][0]}-{h['blocks'][1]}"
            + ("  [archived]" if h["archived"] else "")
            + f"\n  {h['text']}"
            for h in hits
        ],
    )
    return EXIT_OK


# ────────────────────────────────────────────────────────── queue, history, brief


async def cmd_jobs(
    rt: ReadRuntime, *, limit: int = 25, status: str | None = None, kind: str | None = None
) -> int:
    rows, total, _more = await rt.ctx.store.list_jobs_page(
        rt.user_id, limit=limit, status=status, kind=kind
    )
    if not rows:
        print("the queue is empty", file=rt.err)
        return EXIT_NOTHING
    items = [
        {
            "job_id": r["job_id"],
            "kind": r["kind"],
            "status": r["status"],
            "ok": r.get("ok"),
            "detail": r.get("detail"),
            "snapshot_ref": r.get("snapshot_ref"),
            "executor": r.get("executor"),
            # What the round cost, when something counted it. Absent, never zero — and
            # present at all because a job row that stores it and a CLI that does not show it
            # is the same as not storing it (the unattended launcher's whole reason for
            # reading the harness's own counters).
            "token_usage": r.get("token_usage") or None,
            "source_ids": [str(s) for s in (r.get("payload") or {}).get("source_ids", [])],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
        for r in rows
    ]
    _emit(
        rt,
        {"jobs": items, "total": total},
        [
            f"{i['job_id']}  {i['kind']:<10} {i['status']:<8} "
            f"{'' if i['ok'] is None else ('ok' if i['ok'] else 'failed')}  "
            f"{', '.join(i['source_ids'])}"
            + (
                f"  {(i['token_usage'] or {}).get('total_tokens', 0)} tok"
                if i["token_usage"]
                else ""
            )
            for i in items
        ],
    )
    return EXIT_OK


async def cmd_history(rt: ReadRuntime, *, limit: int = 25, kind: str | None = None) -> int:
    rows, counts, _more = await rt.ctx.store.list_history_page(
        rt.user_id, limit=limit, kind=kind
    )
    if not rows:
        print("nothing has happened in this library yet", file=rt.err)
        return EXIT_NOTHING
    items = [
        {
            "kind": row["kind"],
            "ref": row["ref"],
            "ts": row["ts"].isoformat() if row.get("ts") else None,
            "payload": row.get("payload"),
        }
        for row in rows
    ]
    _emit(
        rt,
        {"history": items, "counts": dict(counts)},
        [f"{i['ts']}  {i['kind']:<9} {i['ref']}" for i in items],
    )
    return EXIT_OK


async def cmd_brief(rt: ReadRuntime, version: str) -> int:
    """The post-compile brief of one version — the narration stored on that compile's job.

    `version` is a patch ref as `pkc history` shows it; a unique prefix is enough, because a
    Steward reading a sha off one command and typing it into the next should not have to
    copy forty characters to be understood.
    """
    wanted = str(version or "").strip()
    if not wanted:
        return _refuse(rt, "which version? give a patch ref as `pkc history` shows it")
    rows, _counts, _more = await rt.ctx.store.list_history_page(
        rt.user_id, limit=200, kind="patch"
    )
    row = next(
        (r for r in rows if str(r["ref"]) == wanted or str(r["ref"]).startswith(wanted)),
        None,
    )
    if row is None:
        print(f"no compile version matches {wanted}", file=rt.err)
        return EXIT_NOTHING
    payload = dict(row.get("payload") or {})
    brief = payload.get("brief")
    claims = payload.get("claims") or []
    lines = [f"{row['ref']}  ({payload.get('job_id')})"]
    if brief:
        lines += ["", str(brief)]
    else:
        lines += [
            "",
            "no brief was written for this version "
            "(PNEUMA_KNOWLEDGE_BRIEF_ENABLED is off, or the narration failed)",
        ]
    lines += [""] + [
        f"  {c.get('type')}  {c.get('path')}  c:{(c.get('anchor') or {}).get('anchor')}"
        for c in claims
    ]
    _emit(
        rt,
        {
            "ref": row["ref"],
            "job_id": payload.get("job_id"),
            "brief": brief,
            "changed_paths": payload.get("changed_paths"),
            "claims": claims,
        },
        lines,
    )
    return EXIT_OK


# ───────────────────────────────────────────────────────────── use-side records


async def cmd_consultations(rt: ReadRuntime, *, limit: int = 25) -> int:
    rows, total, _more = await rt.ctx.store.list_consultations_page(
        rt.user_id, limit=limit
    )
    if not rows:
        print("nobody has asked this library anything yet", file=rt.err)
        return EXIT_NOTHING
    items = [
        {
            "consultation_id": r["consultation_id"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "lane": r.get("lane"),
            "visitor_class": r.get("visitor_class"),
            "question": r.get("question"),
            "miss": r.get("miss"),
            "answer_kind": r.get("answer_kind"),
            "evidence_handed": len(r.get("evidence_handed") or []),
            "citations": len(r.get("citations") or []),
        }
        for r in rows
    ]
    _emit(
        rt,
        {"consultations": items, "total": total},
        [
            f"{i['created_at']}  {i['lane']:<12} {'MISS' if i['miss'] else '    '}  "
            f"{i['question']}"
            for i in items
        ],
    )
    return EXIT_OK


async def cmd_spend(rt: ReadRuntime, *, days: int = 30) -> int:
    """What the recorded consultations of the last `days` days spent, in tokens.

    Tokens and not money: a price is a commercial arrangement the record never made, so the
    CLI reports what happened and leaves the arithmetic to whoever declares the rates."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=int(days))
    cells = await rt.ctx.store.consultation_spend(rt.user_id, since=since, until=until)
    total: dict[str, int] = {}
    for cell in cells:
        for name, value in (cell.get("token_usage") or {}).items():
            total[name] = total.get(name, 0) + int(value)
    recorded = sum(int(c.get("consultations", 0)) for c in cells)
    if not cells:
        print(f"nothing was consulted in the last {days} days", file=rt.err)
        return EXIT_NOTHING
    _emit(
        rt,
        {
            "window_days": days,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "consultations": recorded,
            "token_usage": total,
            "cells": cells,
        },
        [
            f"{recorded} consultation(s) in the last {days} days",
            "  " + (", ".join(f"{k}={v}" for k, v in sorted(total.items())) or "no usage reported"),
        ],
    )
    return EXIT_OK


# ────────────────────────────────────────────────────────────────────────── evolve


async def cmd_evolve_ls(rt: ReadRuntime) -> int:
    from ..evolve_service import list_tasks_with_expiry

    tasks = await list_tasks_with_expiry(rt.ctx, rt.user_id)
    if not tasks:
        print("no schema-evolve proposals", file=rt.err)
        return EXIT_NOTHING
    items = [
        {
            "task_id": t.get("task_id"),
            "status": t.get("status"),
            "created_at": str(t.get("created_at") or ""),
            "summary": t.get("summary"),
        }
        for t in tasks
    ]
    _emit(
        rt,
        {"proposals": items},
        [f"{i['task_id']}  {i['status']:<10} {i['summary'] or ''}" for i in items],
    )
    return EXIT_OK


async def cmd_evolve_show(rt: ReadRuntime, task_id: str) -> int:
    from ..evolve_service import get_task_with_expiry

    task = await get_task_with_expiry(rt.ctx, rt.user_id, task_id)
    if task is None:
        print(f"no such proposal: {task_id}", file=rt.err)
        return EXIT_NOTHING
    _emit(
        rt,
        task,
        [json.dumps(task, ensure_ascii=False, indent=2, default=str)],
    )
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────── recall


async def _fast_kwargs(
    rt: ReadRuntime,
    *,
    as_of: datetime,
    style: str | None,
    include_archived: bool = False,
) -> dict:
    """Everything `fast_recall` is called with here — the settings the route reads, read
    once more. What this CANNOT do is choose differently: a lane whose CLI face retrieved
    less than its HTTP face would make `--evidence` a description of a different lane.
    """
    ctx = rt.ctx
    # THE ARCHIVE IS DECIDED HERE, once, exactly as the route decides it in `_glance_inputs`.
    # `documents` is not only the glance's input — it is what the assembly filter pins the
    # claim rows to — so the live set is chosen at the source rather than at each of the
    # lane's doors (docs/design/archive.md §2, §4).
    tree = await ctx.canonical.list(rt.user_id)
    # Read BEFORE the filter, the only order that can answer the question: after it, an
    # archived document is exactly the one thing that is gone. With nothing ever archived the
    # pin never runs and this lane answers byte-for-byte as it did before the archive existed.
    archive_active = any_archived(tree)
    documents = tree if include_archived else live_documents(tree)
    glance_inputs: dict[str, Any] = {}
    if documents or archive_active:
        from ..skills import packs_for_user, skill_for_user

        try:
            glance_inputs = {
                "documents": documents,
                "skill": await skill_for_user(ctx, rt.user_id),
                "packs": await packs_for_user(ctx, rt.user_id),
            }
        except Exception:  # noqa: BLE001 — the glance is context, never a hard dependency
            glance_inputs = {"documents": documents}
    settings = ctx.settings
    return dict(
        as_of=as_of,
        # Stated rather than inherited, because `--evidence` must assemble the same bytes
        # the answering lane would have handed its model: the flag the Steward typed is the
        # one field `/recall` takes, threaded down exactly as the route threads it.
        include_archived=include_archived,
        archive_active=archive_active,
        claim_lexical=ctx.lexical,
        claim_vectors=ctx.vectors,
        lexical=ctx.lexical,
        vectors=ctx.vectors,
        content=ctx.store,
        embeddings=ctx.embeddings,
        # Resolved defensively because `--evidence` is the MODEL-FREE half of this lane: a
        # keyless deployment must still be able to assemble the context, and every pass
        # before the answer that would use a model (the glance pick) is additive and
        # fail-soft by construction. `pkc recall` without `--evidence` has already refused
        # above when either role is unusable, so a None never reaches an answering call.
        model=_optional_model(ctx, "recall"),
        answer_model=_optional_model(ctx, "answer"),
        cap=settings.recall_claim_cap,
        claim_candidate_cap=settings.recall_claim_candidate_cap,
        window_cap=settings.recall_window_cap,
        window_candidate_cap=settings.recall_window_candidate_cap,
        episode_summary_cap=settings.recall_episode_summary_cap,
        evidence_strategy=settings.recall_evidence_strategy,
        all_context_chars=settings.recall_all_context_chars,
        answer_format=settings.recall_answer_format,
        answer_style=style or settings.recall_answer_style,
        plan_queries_cap=settings.recall_plan_queries,
        component_budget_chars=settings.recall_component_budget_chars,
        **glance_inputs,
    )


def _optional_model(ctx: Any, role: str):
    try:
        return ctx.get_chat_model(role)
    except Exception:  # noqa: BLE001 — a keyless deployment has no model for this role
        return None


def _manifest_payload(manifest) -> list[dict[str, str]]:
    return [
        {"kind": ref.kind, "ref": ref.ref, "path": ref.path} for ref in (manifest or ())
    ]


async def cmd_recall_evidence(
    rt: ReadRuntime,
    query: str,
    *,
    handoffs: Any,
    visitor_class: str = "business",
    as_of: str | None = None,
    style: str | None = None,
    include_archived: bool = False,
) -> int:
    """The fast lane's assembled context, and no answering call (§5.1).

    `visitor_class` defaults to `business` here and to `silent` on `cmd_recall`: this face
    hands the context to somebody who is about to answer the Owner with it, which is the
    library being used, while the answering face prints to whoever typed the question. The
    CLI states the same rule in `--visitor-class`'s help (`cli.RECALL_VISITOR_DEFAULTS`).

    It prints what the lane WOULD have handed its model — the bytes, in the lane's own
    rendering, with the lane's own query-local handles — and then records a PENDING HANDOFF:
    the question, the instant, the library ref sampled the way the lane samples it, the
    manifest and the handle map. That is not a consultation yet, and deliberately: a record
    written before the answer exists would have to be rewritten when it arrived, or would
    state a miss the lane never observed. `pkc consult answer <handoff_id>` closes it.
    """
    when = datetime.fromisoformat(as_of) if as_of else datetime.now(timezone.utc)
    evidence = await fast_recall(
        rt.user_id,
        query,
        evidence_only=True,
        **await _fast_kwargs(
            rt, as_of=when, style=style, include_archived=include_archived
        ),
    )
    assert isinstance(evidence, FastEvidence)
    body = message_text(evidence.content)
    handoff_id = uuid.uuid4().hex
    snaps = await rt.ctx.canonical.snapshots(rt.user_id)
    await handoffs.create(
        rt.user_id,
        handoff_id,
        {
            "question": query,
            "as_of": when.isoformat(),
            # Sampled, not pinned — the same word the route's `_library_ref` uses, and the
            # same fact: what the record names is where the reading started.
            "library_ref": snaps[0].ref if snaps else "",
            "visitor_class": visitor_class,
            # THE SCOPE THIS CONTEXT WAS ASSEMBLED UNDER, kept with the handoff. The answer
            # is written from these bytes and recorded against them, so the record has to say
            # which library the reading covered — a consultation over the archive read back as
            # one over the present would be the archive presented as the present, one hop
            # later (docs/design/archive.md §4).
            "include_archived": bool(include_archived),
            "handles": dict(evidence.handles),
            "manifest": _manifest_payload(evidence.manifest),
            "answer_format": evidence.answer_format,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    _emit(
        rt,
        {
            "handoff_id": handoff_id,
            "question": query,
            "as_of": when.isoformat(),
            "system": evidence.system,
            "content": body,
            "handles": dict(evidence.handles),
            "evidence_manifest": _manifest_payload(evidence.manifest),
            "visitor_class": visitor_class,
            "include_archived": bool(include_archived),
        },
        [
            body,
            "",
            f"handoff: {handoff_id}",
            "answer it with: pkc consult answer "
            f"{handoff_id} --text-file <f>   (or `-` for stdin, or --kind no_record)",
            # What the answer will LEAVE BEHIND, said where the instruction is. A `silent`
            # handoff closes without a consultation, so a Steward who followed the printed
            # line and saw nothing in `pkc consultations` was reading a correct ledger of a
            # call that recorded nothing on purpose — stated rather than discovered.
            f"visitor class: {visitor_class}"
            + (
                "  — this call will leave NO consultation record; re-run with "
                "`--visitor-class business` (or `audit`) to record one"
                if visitor_class == "silent"
                else "  — answering it records one consultation"
            ),
        ]
        + (
            ["scope: the archive is INCLUDED in this context, and archived items are labelled"]
            if include_archived
            else []
        ),
    )
    return EXIT_OK


async def cmd_recall(
    rt: ReadRuntime,
    query: str,
    *,
    visitor_class: str = "silent",
    as_of: str | None = None,
    style: str | None = None,
    include_archived: bool = False,
    emit_consultation=None,
) -> int:
    """The fast lane with the configured answer model — exactly what `/recall` runs."""
    from ..wiring import usable_model_name

    for role in ("recall", "answer"):
        if not usable_model_name(rt.ctx.settings, role):
            return _refuse(
                rt,
                f"this deployment has no usable {role} model — it is running keyless. "
                "`pkc recall <q> --evidence` needs no answering model and gives you the "
                "assembled context to answer from yourself.",
            )
    when = datetime.fromisoformat(as_of) if as_of else datetime.now(timezone.utc)
    answer = await fast_recall(
        rt.user_id,
        query,
        **await _fast_kwargs(
            rt, as_of=when, style=style, include_archived=include_archived
        ),
    )
    if emit_consultation is not None:
        await emit_consultation(answer, question=query, as_of=when, visitor_class=visitor_class)
    _emit(
        rt,
        {
            "question": query,
            "as_of": when.isoformat(),
            "answer": answer.answer,
            "answer_text": answer.answer_text,
            "answer_kind": answer.answer_kind,
            "citation_handles": dict(answer.citation_handles),
            "evidence_manifest": _manifest_payload(answer.evidence_manifest),
            # Echoed the way `RecallOut` echoes it: a reader must never have to infer from an
            # empty answer whether the archive was in play.
            "include_archived": bool(include_archived),
        },
        [answer.answer],
    )
    return EXIT_OK
