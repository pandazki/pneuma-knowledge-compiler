"""The structure lens's service face: one report, two readers.

The lens itself is pure core (`pneuma_knowledge_core.lens`) — a model-free reading of the
canonical library's shape. What this module adds is the only thing core cannot do for
itself: resolving WHICH documents and WHICH path templates the report is computed over, out
of the adapters this deployment wired. Both readers — `GET /v1/users/{uid}/lens` and
`pkc lens` — come through here, so the score the Owner sees in the console is the score a
Steward sees at the terminal, computed once in one place (docs/design/structure-lens.md §5).

It reads and nothing else. No table, no job, no registration: this version of the lens keeps
no state of its own and reaches no compile task (§9 is where that is designed, and it is not
built here). The read is the whole feature.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.lens import Report, build_report

from .skills import path_templates_for


async def read_lens(
    ctx, user_id: UserId, *, at: str | None = None
) -> tuple[Report, list[CanonicalDocument]]:
    """The report at one ref, and the documents it was computed over.

    The documents come back because a caller that addresses ONE page (`pkc lens --path`) has
    to be able to say "no such page" rather than "no findings" — a clean page and a typo must
    not render the same. Nothing else reads them.

    `path_templates_for` is the read-only resolution of the user's families: it never writes
    a manifest and never calls a model, which is what makes it usable from a read face.
    """
    ref = SnapshotRef(ref=at) if at else None
    documents, templates = await asyncio.gather(
        ctx.canonical.list(user_id, at=ref),
        path_templates_for(ctx.settings, ctx.canonical, user_id),
    )
    documents = list(documents)
    # `read_at` is stamped HERE and not in core: the lens is a pure function of (documents,
    # templates) and reading a clock inside it would make two reports of one ref differ. It
    # is also why `read_at` is not part of a finding's key — the report says when it was
    # taken, and says nothing different because of when.
    #
    # `decisions=None`: a decline is a kept record this version does not have (§9), so every
    # finding is open and `Finding.decision` is null on every reader.
    report = build_report(
        documents,
        templates,
        ref=(at or "").strip(),
        read_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return report, documents


async def lens_report(ctx, user_id: UserId, *, at: str | None = None) -> Report:
    """The report alone — the HTTP route's whole body."""
    report, _documents = await read_lens(ctx, user_id, at=at)
    return report
