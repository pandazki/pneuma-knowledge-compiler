"""The read half of the HTTP API, as commands — the Steward's eyes (§5.1).

Every command here answers a question the browser can already ask, through the SAME service
functions its route calls. Nothing goes over HTTP: a Steward working in the project has the
adapters in hand, and a CLI that shelled out to its own API would be a second deployment to
keep alive. Nothing is added to core that is only about printing, either — what a page looks
like when the compile model reads it is `render_document`, what the lanes open with is
`render_canonical_glance`, and the complete `outline` reuses that map's metadata derivations
without its top-K or character budget.

Two output shapes and one rule about them: `--json` is the machine-readable form a workflow
branches on, and the default is prose for a person (and for an agent, which reads prose
perfectly well). Both come out of ONE builder per command, so they cannot describe different
state.

Exit codes are the same vocabulary `pkc draft` uses: 0 ok · 1 nothing to show (no such page,
no such source, an empty answer) · 2 refused (an argument that does not parse, a lane this
deployment cannot run) · 4 findings (`pkc library check`, or an unresolved consult citation).
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, TextIO

from pneuma_knowledge_core.canonical_glance import (
    claim_count,
    closed_volume_counts,
    document_definition,
    document_title,
    family_of,
    render_canonical_glance,
    volume_origin,
)
from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.compile.supersession import block_by_anchor, chains, superseded_index
from pneuma_knowledge_core.domain.archive import (
    any_archived,
    is_archive_record,
    is_archived_path,
    live_documents,
    live_path,
    split_archived,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument, Citation, iter_canonical_citations
from pneuma_knowledge_core.domain.ids import SourceId, UserId, extract_anchors
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.archive_filter import archive_view
from pneuma_knowledge_core.recall.fast import FastEvidence, fast_recall, message_text
from pneuma_knowledge_core.recall.rag import rag_recall

from .reader_signals import (
    SourceSignals,
    calendar_header,
    calendar_metadata,
    evidence_lines,
    evidence_tally,
    one_line,
    recorded_day,    span_speaker_text,
    source_index_lines,
)

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_REFUSED = 2

#: `¶3`, `¶3-7` and `3-7` address block spans. The citation grammar is the one
#: the whole system speaks (I4), so it is what a locator is typed in; the bare forms exist
#: because a shell eats `¶` on some keyboards and refusing over a pilcrow would be theatre.
_SPAN_RE = re.compile(r"^\s*¶?\s*(?P<start>\d+)(?:\s*[-–]\s*(?P<end>\d+))?\s*$")


PAGE_CHARS = 8000


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
    # Prose output is paged: a reader with a context window asked for one page and gets one,
    # with a footer saying how much more there is. JSON lists page by whole items.
    page: int = 1
    page_chars: int = PAGE_CHARS
    all_pages: bool = False



def paginate(text: str, page_chars: int) -> list[str]:
    """Cut `text` into pages of at most `page_chars` characters at line boundaries — a line
    longer than a page is cut hard rather than dropped. Pure, so the paging is testable
    without a command behind it."""
    if page_chars <= 0 or len(text) <= page_chars:
        return [text]
    pages: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        while len(line) > page_chars:
            if current:
                pages.append("\n".join(current))
                current, size = [], 0
            pages.append(line[:page_chars])
            line = line[page_chars:]
        extra = len(line) + (1 if current else 0)
        if current and size + extra > page_chars:
            pages.append("\n".join(current))
            current, size = [], 0
            extra = len(line)
        current.append(line)
        size += extra
    if current:
        pages.append("\n".join(current))
    return pages


def page_items(payload: Any, page: int, page_chars: int) -> Any:
    """Page a top-level list (wrapped as `items`) or the largest serialized list in a dict.

    Item boundaries are never cut. Scalars and payloads that fit are returned whole.
    """
    if page_chars <= 0 or not isinstance(payload, (dict, list)):
        return payload
    dump = lambda value: json.dumps(value, ensure_ascii=False, indent=2, default=str)  # noqa: E731
    if len(dump(payload)) <= page_chars:
        return payload
    payload = {"items": payload} if isinstance(payload, list) else payload
    lists = [key for key, value in payload.items() if isinstance(value, list)]
    if not lists:
        return payload
    key = max(lists, key=lambda key: len(dump(payload[key])))
    items = payload[key]
    pages: list[list[Any]] = []
    current: list[Any] = []
    size = 0
    for item in items:
        length = len(dump(item))
        if current and size + length > page_chars:
            pages.append(current)
            current, size = [], 0
        current.append(item)
        size += length
    if current or not pages:
        pages.append(current)
    index = min(max(page, 1), len(pages))
    return {
        **payload,
        key: pages[index - 1],
        "paging": {
            "list": key,
            "page": index, "pages": len(pages), "items": len(items),
            "next": f"--page {index + 1}" if index < len(pages) else None,
            "all": "--all-pages",
        },
    }


def _emit(
    rt: ReadRuntime, payload: Any, lines: list[str], *, json_paging: bool = True,
    header: list[str] | None = None,
) -> None:
    """One state, two renderings. `--json` prints the payload; the default prints the lines,
    one page of them at a time (`page` / `all_pages` on the runtime)."""
    if rt.as_json:
        if json_paging and not rt.all_pages:
            payload = page_items(payload, rt.page, rt.page_chars)
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), file=rt.out)
        return
    if header:
        print("\n".join(header), file=rt.out)
    text = "\n".join(lines)
    pages = [text] if rt.all_pages else paginate(text, rt.page_chars)
    if len(pages) == 1:
        print(text, file=rt.out)
        return
    index = min(max(rt.page, 1), len(pages))
    print(pages[index - 1], file=rt.out)
    footer = f"[page {index}/{len(pages)} · {len(pages[index - 1]):,} of {len(text):,} chars"
    if index < len(pages):
        footer += f" · --page {index + 1} for the next"
    footer += " · --all-pages for everything · " + prompt("steward.read.json_paging") + "]"
    print(footer, file=rt.out)


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


# ───────────────────────────────────────────────────────────────────────── outline


def _outline_tree(
    documents: list[CanonicalDocument],
    templates: list[str],
    *,
    family: str | None,
    definitions: bool,
    include_archived: bool,
) -> dict[str, Any]:
    """The complete page map, derived from the one listing already in hand.

    Reuse the glance's title, claim, definition, volume and family derivations without its
    top-K or character budget. Unfiled pages have a null template, so a contract change can
    never make an existing page disappear from the complete map.
    """
    grouped: dict[str | None, list[dict[str, Any]]] = {
        template: [] for template in templates if family is None or template == family
    }
    live, archived = split_archived(documents)
    # Resolve volumes within each side of the archive boundary. An archived volume's old
    # owning-page stamp names a live path now occupied by a record; it belongs to the moved
    # page, not to that record. Each family's archived pages follow all its live pages.
    for scope in (live, archived) if include_archived else (live,):
        present = {doc.path for doc in scope}
        volumes = closed_volume_counts(scope)
        for doc in sorted(scope, key=lambda d: d.path):
            if volume_origin(doc, present) is not None:
                continue
            template = family_of(live_path(doc.path), templates)
            if family is not None and template != family:
                continue
            item = {
                "path": doc.path,
                "title": " ".join(document_title(doc).split()),
                "claims": claim_count(doc),
                "volumes": volumes.get(doc.path, 0),
                "kind": "record" if is_archive_record(doc) else "page",
                "archived": is_archived_path(doc.path),
            }
            if definitions:
                definition = document_definition(doc)
                if definition:
                    item["definition"] = definition
            grouped.setdefault(template, []).append(item)
    return {
        "families": [
            {"template": template, "documents": members}
            for template, members in grouped.items()
        ],
        "documents": sum(len(members) for members in grouped.values()),
    }


def _outline_lines(tree: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for family in tree["families"]:
        if lines:
            lines.append("")
        lines.append(f"## {family['template'] or '(outside every declared family)'}")
        if not family["documents"]:
            lines.append("(empty)")
        for doc in family["documents"]:
            line = f"{doc['path']} — {doc['title']} ({doc['claims']} claims)"
            if doc["volumes"]:
                line += f" +{doc['volumes']} volumes"
            if doc["kind"] == "record":
                line += " [record]"
            if doc["archived"]:
                line += " [archived]"
            lines.append(line)
            if doc.get("definition"):
                lines.append(f"  definition: {doc['definition']}")
    return lines or ["this library holds no canonical pages yet"]


async def cmd_outline(
    rt: ReadRuntime,
    *,
    family: str | None = None,
    definitions: bool = False,
    include_archived: bool = False,
) -> int:
    from ..skills import composed_skill_readonly

    skill = await composed_skill_readonly(rt.ctx.settings, rt.ctx.canonical, rt.user_id)
    templates = list(skill.path_templates)
    if family is not None and family not in templates:
        print(f"no such family: {family}", file=rt.err)
        return EXIT_REFUSED
    documents = await rt.ctx.canonical.list(rt.user_id)
    tree = _outline_tree(
        documents,
        templates,
        family=family,
        definitions=definitions,
        include_archived=include_archived,
    )
    _emit(rt, tree, _outline_lines(tree))
    return EXIT_OK


# ───────────────────────────────────────────────────────────────────────── glance


async def _glance_text(rt: ReadRuntime, *, include_archived: bool = False) -> str | None:
    """The glance exactly as the answering lanes render it — same documents, same skill,
    same packs, same function. A degradation is silence, not an error: the glance is
    context."""
    ctx = rt.ctx
    documents = await ctx.canonical.list(rt.user_id)
    if not documents:
        return None
    from ..skills import composed_skill_readonly, packs_for_user

    try:
        skill = await composed_skill_readonly(ctx.settings, ctx.canonical, rt.user_id)
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


async def cmd_canonical_read(rt: ReadRuntime, path: str | list[str]) -> int:
    """One page, or several in one process: every `pkc` call builds its context, so a
    reader wanting three pages should not pay for three."""
    paths = [path] if isinstance(path, str) else list(path)
    snapshots = await rt.ctx.canonical.snapshots(rt.user_id)
    at = snapshots[0] if snapshots else None
    docs = await rt.ctx.canonical.list(rt.user_id, at=at)
    by_path = {d.path: d for d in docs}
    successors = superseded_index({d.path: d.body for d in docs})
    signals = await SourceSignals.for_runtime(rt.ctx, rt.user_id)
    _jobs, pending, _more = await rt.ctx.store.list_jobs_page(
        rt.user_id, limit=1, status=("queued", "claimed"), kind="compile"
    )
    _jobs, failed, _more = await rt.ctx.store.list_jobs_page(
        rt.user_id, limit=1, status="failed", kind="compile"
    )
    found = []
    lines = []
    for wanted in paths:
        doc = by_path.get(wanted)
        if doc is None:
            print(f"no such page: {wanted}", file=rt.err)
            continue
        # The compile model's own `read_document` rendering, so the Steward and the model
        # read one page rather than two descriptions of it.
        sources = await signals.index(iter_canonical_citations(doc.body))
        written = await rt.ctx.canonical.last_commit(rt.user_id, doc.path, at=at)
        anchors = extract_anchors(doc.body)
        replaced = [
            {"predecessor": f"c:{anchor}", "successor": f"c:{successors[anchor][1]}",
             "path": successors[anchor][0]}
            for anchor in dict.fromkeys(anchors) if anchor in successors
        ]
        latest = signals.latest_source(sources)
        status = {
            "last_changed": recorded_day(written[1], signals.time) if written else None,
            "last_changed_at": written[1] if written else None,
            "commit": written[0] if written else None,
            "claims": claim_count(doc),
            "overview_blocks": len(anchors) - claim_count(doc),
            "superseded": len(replaced),
            "sources_cited": len(sources),
            "latest_cited_source": latest["date"] if latest else None,
            "latest_cited_source_at": latest.get("at") if latest else None,
            "queue_pending": pending,
            "queue_failed": failed,
        }
        item = {"path": doc.path, "calendar": calendar_metadata(signals.time),
                "document": render_document(doc.frontmatter, doc.body),
                "status": status, "supersessions": replaced, "sources": sources}
        found.append(item)
        display = {key: value if value is not None else prompt("steward.read.unknown")
                   for key, value in status.items()}
        display["commit"] = status["commit"][:7] if status["commit"] else display["commit"]
        lines.extend([
            prompt("steward.read.page", path=doc.path),
            prompt("steward.read.status", **display),
            *([prompt("steward.read.superseded", count=len(replaced), successors=" · ".join(
                f"{link['predecessor']} → {link['successor']} "
                f"({prompt('steward.read.this_page') if link['path'] == doc.path else link['path']})"
                for link in replaced
            ))] if replaced else []),
            prompt("steward.read.compile_jobs", pending=pending, failed=failed),
            "", item["document"], "", *source_index_lines(sources), "",
        ])
    if not found:
        return EXIT_NOTHING
    if len(paths) == 1:
        _emit(rt, found[0], lines, header=[calendar_header(signals.time)])
    else:
        _emit(rt, {"pages": found}, lines, header=[calendar_header(signals.time)])
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
    from pneuma_knowledge_core.domain.authorship import block_authorship

    raw = ns.raw
    authorship = block_authorship(raw)
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
    if authorship:
        payload["block_authorship"] = authorship
        lines.extend(
            f"  ¶{row['index']}  {row['role']}"
            + (f" / {row['kind']}" if "kind" in row else "")
            for row in authorship
        )
    for span in payload["structure"]:
        lines.append(
            f"  ¶{span['blocks'][0]}-{span['blocks'][1]}  {' / '.join(span['path'])}"
        )
    _emit(rt, payload, lines)
    return EXIT_OK


async def cmd_source_fetch(rt: ReadRuntime, source_id: str, span: str | list[str]) -> int:
    """Verbatim L0 for one or more spans. UNCONDITIONAL (I3): no plan, no strategy and no
    visibility state decides whether a cited span resolves."""
    tokens = [span] if isinstance(span, str) else list(span)
    groups: list[tuple[str, list[str]]] = [(source_id, [])]
    for index, token in enumerate(tokens):
        if parse_span(token) is not None:
            groups[-1][1].append(token)
        elif groups[-1][1] and index + 1 < len(tokens) and parse_span(tokens[index + 1]):
            groups.append((token, []))
        else:
            return _refuse(
                rt, f"not a block span: {token!r} — write ¶a-b, ¶a or a-b; "
                "exactly two bare integers `a b` mean one span; another source id needs a span"
            )
    items = []
    signals = await SourceSignals.for_runtime(rt.ctx, rt.user_id)
    try:
        for sid, tokens in groups:
            spans = (
                [(int(tokens[0]), int(tokens[1]))]
                if len(tokens) == 2 and all(re.fullmatch(r"\d+", token) for token in tokens)
                else [parse_span(token) for token in tokens]
            )
            for start, end in spans:
                text = await rt.ctx.store.fetch(
                    rt.user_id, SourceId(sid), {"blocks": [start, end]}
                )
                summary = await signals.summary(sid)
                items.append({"source_id": sid, "blocks": [start, end],
                              **await signals.span(sid, start, end),
                              "date": summary["date"], **({"at": summary["at"]} if "at" in summary else {}),
                              "calendar": calendar_metadata(signals.time), "text": text})
    except (KeyError, ValueError) as exc:
        print(str(exc), file=rt.err)
        return EXIT_NOTHING
    _emit(
        rt,
        items,
        # The source's day closes the line only when a block carries no day of its own;
        # a span whose every block is dated already says when it was spoken.
        [f"{item['source_id']} {span_speaker_text(item)}"
         + ("" if item["speakers"] and all(row.get("date") for row in item["speakers"])
            else f" · {item['date'] or prompt('steward.read.unknown')}")
         + f"\n{item['text']}"
         for item in items],
        header=[calendar_header(signals.time)],
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
    terms: dict[str, str] = {}
    if mode != "semantic":
        # Preserve the index query spelling even for a quoted single word; quotes disable
        # prefix matching in Meilisearch. Apostrophes inside words are ordinary text.
        lexer = shlex.shlex(query, posix=False)
        lexer.whitespace_split, lexer.commenters, lexer.quotes, lexer.escape = True, "", '"', ""
        try:
            for token in lexer:
                term = token[1:-1] if token.startswith('"') and token.endswith('"') else token
                terms.setdefault(term, token)
        except ValueError as exc:
            return _refuse(rt, str(exc))
    hits: list[dict[str, Any]] = []
    total = None
    if mode == "lexical":
        lexical_hits, total = await ctx.lexical.search_with_total(
            rt.user_id, query, limit=limit, include_archived=include_archived
        )
        for hit in lexical_hits:
            hits.append(
                {
                    "source_id": str(hit.source_id),
                    "blocks": [hit.block_index, hit.block_index],
                    "score": float(hit.score),
                    "text": hit.text,
                }
            )
    elif mode == "semantic":
        if ctx.embeddings is None or ctx.vectors is None:
            print(
                "semantic retrieval is off; use `pkc search --mode lexical` or enable "
                "it with `pkc config set semantic_retrieval on` and rebuild derived indexes",
                file=rt.err,
            )
            return EXIT_NOTHING
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
    signals = await SourceSignals.for_runtime(ctx, rt.user_id)
    for hit in hits:
        hit["archived"] = (
            view.source_archived(hit["source_id"]) if view is not None else False
        )
        speaker = await signals.span(hit["source_id"], *hit["blocks"])
        hit["speakers"] = speaker["speakers"]
        if "speaker" in speaker:
            hit["speaker"] = speaker["speaker"]
    payload = {
        "mode": mode, "query": query, "include_archived": include_archived, "hits": hits,
        "showing": len(hits), "total": total, "calendar": calendar_metadata(signals.time),
    }
    lines = [prompt("steward.read.query", query=one_line(query)), calendar_header(signals.time)]
    if mode != "semantic":
        counts = await asyncio.gather(*(
            ctx.lexical.count(rt.user_id, term_query, all_terms=True,
                              include_archived=include_archived)
            for term_query in [query, *terms.values()]
        ))
        payload["counts"] = {"all_terms": counts[0], "per_term": dict(zip(terms, counts[1:]))}
        lines.append(prompt("steward.read.search_counts", all_terms=counts[0], terms=" · ".join(
            f"{json.dumps(term, ensure_ascii=False)}: {count}"
            for term, count in payload["counts"]["per_term"].items()
        )))
        _jobs, index_pending, _more = await ctx.store.list_jobs_page(
            rt.user_id, limit=1, status=("queued", "claimed"), kind="index"
        )
        _jobs, index_failed, _more = await ctx.store.list_jobs_page(
            rt.user_id, limit=1, status="failed", kind="index"
        )
        payload["index_queue_pending"] = index_pending
        payload["index_queue_failed"] = index_failed
        lines.append(prompt("steward.read.index_jobs", pending=index_pending, failed=index_failed))
        if mode == "fused":
            # A fused candidate cap is not an index-wide total. Keep the lexical estimate
            # separately named; pretending it counted vector-only hits can yield 10 of 0.
            payload["lexical_total"] = await ctx.lexical.count(
                rt.user_id, query, include_archived=include_archived
            )
            lines.append(prompt("steward.read.lexical_total", total=payload["lexical_total"]))
    lines.append(prompt(
        "steward.read.showing" if mode == "lexical" else f"steward.read.showing_{mode}",
        showing=len(hits), total=total,
    ))
    _emit(
        rt,
        payload,
        [
            f"{h['source_id']} {span_speaker_text(h)}"
            + ("  [archived]" if h["archived"] else "")
            + f"\n  {h['text']}"
            for h in hits
        ],
        header=lines,
    )
    if not hits:
        print("nothing found", file=rt.err)
        return EXIT_NOTHING
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
            # What the harness said when it refused, for the one question `detail` cannot
            # answer on its own: exit 1 with the words that came with it.
            "harness_output": r.get("harness_output") or None,
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
            "state": r.get("state", "answered"),
            "answered_at": r["answered_at"].isoformat() if r.get("answered_at") else None,
            "answer_kind": r.get("answer_kind"),
            "evidence_handed": r["evidence_count"],
            "citations": r["citation_count"],
            "citations_direct": r["citations_direct"],
        }
        for r in rows
    ]
    _emit(
        rt,
        {"consultations": items, "total": total},
        [
            f"{i['consultation_id']}  {i['created_at']}  {i['lane']:<12} "
            f"{prompt('steward.read.unanswered') if i['state'] == 'unanswered' else prompt('steward.read.miss' if i['miss'] else 'steward.read.answered')}  "
            f"{i['question']}  ·  evidence handed: {i['evidence_handed']}  ·  "
            f"citations: {i['citations']}  ·  direct: {i['citations_direct']}"
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
    evidence_only: bool = False,
) -> dict:
    """The fast lane's configured retrieval and rendering, with optional chat assistance.

    Evidence-only calls supply no chat models: the agent performs the judgements itself.
    The lane's deterministic fallbacks still assemble and render the evidence context.
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
        from ..skills import composed_skill_readonly, packs_for_user

        try:
            glance_inputs = {
                "documents": documents,
                "skill": await composed_skill_readonly(ctx.settings, ctx.canonical, rt.user_id),
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
        # Evidence uses the lane's deterministic retrieval and rendering. Model-assisted
        # planning, routing and selection fall back without constructing a chat model,
        # even when a deployment has credentials. The agent does those judgements itself.
        model=None if evidence_only else _optional_model(ctx, "recall"),
        answer_model=None if evidence_only else _optional_model(ctx, "answer"),
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


def _emit_evidence(rt: ReadRuntime, retained: dict[str, Any], *, new_retrieval: bool) -> None:
    """Serve the same handoff's saved text; the header is outside the body page budget."""
    payload = retained["payload"]
    if rt.as_json:
        _emit(rt, payload, [], json_paging=False)
        return
    text = retained["text"]
    pages = [text] if rt.all_pages else paginate(text, retained["page_chars"])
    index = min(max(rt.page, 1), len(pages))
    handoff_id = payload["handoff_id"]
    command = f"pkc --user {shlex.quote(str(rt.user_id))} recall --evidence --handoff {handoff_id}"
    header = list(retained["header"])
    if index < len(pages):
        header.insert(3, prompt("steward.read.next_page", command=f"{command} --page {index + 1}"))
    else:
        header.insert(3, prompt("steward.read.result_end", command=command + " --all-pages"))
    if new_retrieval:
        header.insert(4, prompt("steward.read.new_retrieval", handoff_id=handoff_id))
    print("\n".join([*header, "", pages[index - 1]]), file=rt.out)
    if len(pages) > 1:
        print(
            f"[page {index}/{len(pages)} · {len(pages[index - 1]):,} of {len(text):,} chars · "
            f"{command} --all-pages · {prompt('steward.read.json_paging')}]",
            file=rt.out,
        )


async def cmd_recall_evidence(
    rt: ReadRuntime,
    query: str | None,
    *,
    handoffs: Any,
    handoff_id: str | None = None,
    visitor_class: str = "business",
    as_of: str | None = None,
    style: str | None = None,
    include_archived: bool = False,
) -> int:
    """Retrieve once and retain both reader prose and unchanged lane JSON with the handoff.

    Reading a retained page only reads this tenant's handoff. Silent handoffs have the same
    retention, but answering them still leaves no consultation record.
    """
    if handoff_id:
        state = await handoffs.get(rt.user_id, handoff_id)
        if state is None:
            print(f"no retained handoff: {handoff_id}", file=rt.err)
            return EXIT_NOTHING
        retained = state.get("retained_result")
        if retained is None:
            return _refuse(rt, f"handoff {handoff_id} has no retained result; retrieve again")
        _emit_evidence(rt, retained, new_retrieval=False)
        return EXIT_OK
    if not query:
        return _refuse(rt, "recall requires a query or --evidence --handoff <id>")
    when = datetime.fromisoformat(as_of) if as_of else datetime.now(timezone.utc)
    opened_at = datetime.now(timezone.utc)
    snaps = await rt.ctx.canonical.snapshots(rt.user_id)
    evidence = await fast_recall(
        rt.user_id, query, evidence_only=True,
        **await _fast_kwargs(
            rt, as_of=when, style=style, include_archived=include_archived, evidence_only=True
        ),
    )
    assert isinstance(evidence, FastEvidence)
    arms = [
        {"name": stage.name, "status": stage.status, "detail": stage.detail}
        for stage in evidence.stages
    ]
    body = message_text(evidence.content)
    tally = evidence_tally(evidence)
    signals = await SourceSignals.for_runtime(rt.ctx, rt.user_id)
    # The rendered content includes annotated and component claims as well as ordinary
    # claims/windows. Add explicit claim provenance too; never infer citations from titles.
    citations = [citation for _kind, section in evidence.sections
                 for citation in iter_canonical_citations(section)]
    for claim in evidence.used_claims:
        citations.extend(claim.citations)
        citations.extend(iter_canonical_citations(claim.text))
    citations.extend(
        Citation(source_id=window.source_id, block_start=window.block_start, block_end=window.block_end)
        for window in (*evidence.used_windows, *evidence.used_episode_summaries)
    )
    sources = await signals.index(citations, handles=evidence.handles)
    handoff_id = uuid.uuid4().hex
    payload = {
        "handoff_id": handoff_id, "question": query, "as_of": when.isoformat(),
        "as_of_day": recorded_day(when, signals.time), "calendar": calendar_metadata(signals.time),
        "system": evidence.system, "content": body, "tally": tally, "sources": sources,
        "handles": dict(evidence.handles), "evidence_manifest": _manifest_payload(evidence.manifest),
        "arms": arms, "visitor_class": visitor_class, "include_archived": bool(include_archived),
    }
    header, lines = evidence_lines(evidence, tally, signals.time)
    recording = prompt("steward.read.handoff_silent" if visitor_class == "silent"
                       else "steward.read.handoff_recorded")
    header.insert(2, f"handoff: {handoff_id} · {visitor_class} · {recording}")
    header.extend([
        "answer it with: pkc consult answer "
        f"{handoff_id} --text-file <f>   (or `-` for stdin, or --kind no_record)",
        f"visitor class: {visitor_class}" + (
            "  — this call will leave NO consultation record; re-run with "
            "`--visitor-class business` (or `audit`) to record one"
            if visitor_class == "silent" else f"  — {recording}"
        ),
    ])
    if include_archived:
        header.append("scope: the archive is INCLUDED in this context, and archived items are labelled")
    lines += source_index_lines(sources) + [
        "", "arms: " + "; ".join(
            f"{arm['name']}: {arm['status']}"
            + (f" ({arm['detail']})" if arm['detail'] else "") for arm in arms
        ),
    ]
    retained = {"payload": payload, "header": header, "text": "\n".join(lines),
                "page_chars": rt.page_chars}
    state = {
        "question": query, "as_of": when.isoformat(),
        # Sampled, not pinned: the same library-ref semantics as the answering route.
        "library_ref": snaps[0].ref if snaps else "", "visitor_class": visitor_class,
        "include_archived": bool(include_archived), "handles": dict(evidence.handles),
        "manifest": _manifest_payload(evidence.manifest), "answer_format": evidence.answer_format,
        "created_at": opened_at.isoformat(), "retained_result": retained,
        "opening_recorded": visitor_class != "silent",
    }
    if visitor_class != "silent":
        from pneuma_knowledge_core.domain.consultation import ConsultationRecord, dedup_evidence
        from .consult import _default_emit

        opening = ConsultationRecord(
            consultation_id=handoff_id, user_id=str(rt.user_id), created_at=opened_at,
            lane="fast", visitor_class=visitor_class, question=query, as_of=when,
            library_ref=state["library_ref"], evidence_handed=dedup_evidence(list(evidence.manifest)),
            event="opening", miss=None,
        )
        # Persist use before publishing retained pages that claim it was recorded. If
        # retaining prose fails, the completed retrieval still leaves its kept opening.
        await _default_emit(rt.ctx, rt.user_id, opening)
    await handoffs.create(rt.user_id, handoff_id, state)
    _emit_evidence(rt, retained, new_retrieval=True)
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
