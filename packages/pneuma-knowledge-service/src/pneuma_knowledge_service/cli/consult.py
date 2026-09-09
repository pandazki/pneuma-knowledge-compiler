"""`pkc consult answer` / `record` — recording an agent answer (§5.1).

`pkc recall --evidence` gave the Steward the fast lane's assembled context and made no
answering call, so what exists at that moment is a question, an instant, a library ref and an
evidence manifest — and no answer. The kept opening already records that use. This command
appends the answer event once under its id. `record` uses the same path without a hand-over, with lane `direct`.

Three things it does NOT do, and each is the point:

- **it does not build the record itself.** `consultation_from_fast` builds it — the fast
  lane's own builder, the same one `/recall` calls — over a stand-in carrying exactly the
  fields that builder reads. Under an agent executor the agent's reading IS retrieval,
  so manifest membership is no longer a proxy for resolution. Every citation must resolve
  through the hand-over's handle map or as a real address in this tenant's L0 or canonical:
  the source must exist with `1 <= a <= b <= block count`, or the canonical anchor must
  exist. Handed citations keep `origin: "handed"`; resolving addresses outside the manifest
  carry `origin: "direct"`, without expanding `evidence_handed`. An unresolved marker refuses
  the answer with exit 4, naming the address and leaving the hand-over open for correction.
- **it does not write the row itself.** `_spawn_recording` writes it — the same emission the
  answering routes use, so a `business` answer enqueues its one `recall_projection` job in
  the same transaction and a `silent` one is never written at all.
- **it does not rewrite an opening or an answer.** A hand-over nobody answers expires,
  but its kept opening remains unanswered. A refused answer leaves that state unchanged.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, TextIO

from pneuma_knowledge_core.domain.consultation import (
    VISITOR_CLASS_VALUES,
    EvidenceRef,
    parse_span_ref,
)
from pneuma_knowledge_core.domain.ids import UserId, extract_anchors
from pneuma_knowledge_core.recall.consultation import consultation_from_fast
from pneuma_knowledge_core.recall.direct_citations import (
    UnresolvedCitation,
    admit_resolving_citations,
    answer_addresses,
)

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_REFUSED = 2
EXIT_FINDINGS = 4

#: What a Steward may say a consultation WAS. The same two values a structured fast answer
#: reports, and no third: `answer` came back with something, `no_record` came back with
#: nothing, and `is_miss` reads exactly this field.
ANSWER_KINDS = ("answer", "no_record")


@dataclass
class _AnsweredHandoff:
    """The shape `consultation_from_fast` reads — nothing more, nothing invented.

    A `FastAnswer` is what that builder normally receives. This is the same surface with the
    lane's own values restored from the hand-over (`evidence_manifest`, `citation_handles`)
    and the Steward's answer in the one field the lane would have filled. Every degradation
    flag is absent rather than guessed: no lane ran, so no lane degraded.
    """

    answer: str
    answer_kind: str | None
    evidence_manifest: tuple[EvidenceRef, ...] = field(default_factory=tuple)
    citation_handles: dict[str, str] = field(default_factory=dict)
    #: Tokens. A Steward on its own subscription reports none, and a zero would be a claim —
    #: so this is empty, and the record carries an empty usage rather than a false free.
    token_usage: dict[str, int] = field(default_factory=dict)


def _manifest(rows: Any) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(
            kind=str(row.get("kind") or ""),
            ref=str(row.get("ref") or ""),
            path=str(row.get("path") or ""),
        )
        for row in (rows or ())
    )


async def cmd_consult_answer(
    ctx: Any,
    user_id: UserId,
    handoff_id: str,
    *,
    handoffs: Any,
    text: str,
    kind: str = "answer",
    emit: Any = None,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    if kind not in ANSWER_KINDS:
        print(
            f"unknown answer kind {kind!r} — it is one of: {', '.join(ANSWER_KINDS)}",
            file=err,
        )
        return EXIT_REFUSED
    state = await handoffs.get(user_id, handoff_id)
    if state is None:
        recorded = await ctx.store.get_consultation(user_id, handoff_id)
        if recorded is not None and recorded.state == "answered":
            print(f"consultation {handoff_id} is already answered", file=err)
            return EXIT_FINDINGS
        print(
            f"no pending handoff {handoff_id} — it was answered already, or it expired "
            "(PNEUMA_KNOWLEDGE_RECALL_HANDOFF_TTL)",
            file=err,
        )
        return EXIT_NOTHING
    state = {**state, "consultation_id": handoff_id}
    if state.get("opening_recorded"):
        opening = await ctx.store.get_consultation(user_id, handoff_id)
        if opening is None or opening.state == "answered":
            reason = "has no opening" if opening is None else "is already answered"
            print(f"consultation {handoff_id} {reason}", file=err)
            return EXIT_FINDINGS
        # The kept event supplies its own immutable context, including timestamps in
        # the store's normalized timezone. The expiring row supplies prose and handles.
        state.update(
            question=opening.question, visitor_class=opening.visitor_class,
            created_at=opening.created_at.isoformat(),
            as_of=opening.as_of.isoformat() if opening.as_of else None,
            library_ref=opening.library_ref,
            manifest=[{"kind": r.kind, "ref": r.ref, "path": r.path}
                      for r in opening.evidence_handed],
        )
    code = await _record_answer(
        ctx, user_id, state, text=text, kind=kind, lane="fast", emit=emit,
        as_json=as_json, out=out, err=err,
    )
    if code == EXIT_OK:
        await handoffs.delete(user_id, handoff_id)
    return code


async def cmd_consult_record(
    ctx: Any,
    user_id: UserId,
    *,
    question: str,
    text: str,
    kind: str = "answer",
    visitor_class: str = "business",
    emit: Any = None,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Close direct reading without inventing a hand-over or running a retrieval lane."""
    out = out or sys.stdout
    err = err or sys.stderr
    if not question.strip():
        print("a consultation requires a question", file=err)
        return EXIT_REFUSED
    if kind not in ANSWER_KINDS or visitor_class not in VISITOR_CLASS_VALUES:
        print("unknown answer kind or visitor class", file=err)
        return EXIT_REFUSED
    snaps = await ctx.canonical.snapshots(user_id)
    state = {
        "question": question,
        "visitor_class": visitor_class,
        # With no hand-over there is no earlier sample or relative-time reference. This
        # names HEAD at recording, not a reconstructed snapshot of the agent's reading.
        "library_ref": snaps[0].ref if snaps else "",
    }
    return await _record_answer(
        ctx, user_id, state, text=text, kind=kind, lane="direct", emit=emit,
        as_json=as_json, out=out, err=err,
    )


async def _record_answer(
    ctx: Any, user_id: UserId, state: dict, *, text: str, kind: str, lane: str,
    emit: Any, as_json: bool, out: TextIO, err: TextIO,
) -> int:
    body = text.rstrip("\n")
    if kind == "answer" and not body.strip():
        print(
            "an empty answer is not an answer — say `--kind no_record` when the library "
            "held nothing",
            file=err,
        )
        return EXIT_REFUSED

    manifest = _manifest(state.get("manifest"))
    handles = dict(state.get("handles") or {})
    try:
        refs = answer_addresses(body, handles)
        source_ids = list(dict.fromkeys(
            parsed[0] for ref in refs if (parsed := parse_span_ref(ref.ref)) is not None
        ))
        counts = await ctx.store.block_counts(user_id, source_ids) if source_ids else {}
        anchor_paths = {}
        if any(ref.kind == "claim" for ref in refs):
            documents = await ctx.canonical.list(user_id)
            anchor_paths = {
                str(anchor): doc.path
                for doc in documents
                for anchor in extract_anchors(doc.body)
            }
        citations = admit_resolving_citations(
            refs, manifest, block_counts=counts, anchor_paths=anchor_paths,
        )
    except UnresolvedCitation as exc:
        print(str(exc), file=err)
        return EXIT_FINDINGS

    as_of = state.get("as_of")
    record = consultation_from_fast(
        _AnsweredHandoff(
            answer=body,
            answer_kind=kind,
            evidence_manifest=manifest,
            citation_handles=handles,
        ),
        user_id=str(user_id),
        lane=lane,
        visitor_class=str(state.get("visitor_class") or "silent"),
        question=str(state.get("question") or ""),
        as_of=datetime.fromisoformat(as_of) if as_of else None,
        library_ref=str(state.get("library_ref") or ""),
        consultation_id=state.get("consultation_id") or uuid.uuid4().hex,
        created_at=(datetime.fromisoformat(state["created_at"])
                    if state.get("created_at") else datetime.now(timezone.utc)),
        resolved_citations=citations,
    )
    record = replace(
        record, answered_at=datetime.now(timezone.utc),
        event="answer" if state.get("opening_recorded") else "complete",
    )
    # `silent` leaves no trace at all — not a row, not a job, not a task. The class was fixed
    # at hand-over, so a Steward cannot make a silent question recordable after the fact by
    # answering it differently.
    if str(state.get("visitor_class") or "silent") != "silent":
        writer = emit or _default_emit
        try:
            await writer(ctx, user_id, record)
        except ValueError as exc:
            print(str(exc), file=err)
            return EXIT_FINDINGS
    payload = {
        "consultation_id": record.consultation_id,
        "recorded": str(state.get("visitor_class") or "silent") != "silent",
        # THE SCOPE THE ANSWER WAS WRITTEN OVER, carried from the hand-over rather than
        # decided here. `--evidence` assembled the context under `include_archived` and the
        # Steward answered out of those bytes; a close that said nothing about it would leave
        # a consultation over the archive indistinguishable from one over the present
        # (docs/design/archive.md §4).
        "include_archived": bool(state.get("include_archived")),
        "lane": record.lane,
        "visitor_class": record.visitor_class,
        "question": record.question,
        "state": record.state,
        "created_at": record.created_at.isoformat(),
        "answered_at": record.answered_at.isoformat(),
        "answer_kind": record.answer_kind,
        "miss": record.miss,
        "citations": [
            {"kind": c.kind, "ref": c.ref, "path": c.path, "origin": c.origin}
            for c in record.citations
        ],
        "evidence_handed": len(record.evidence_handed),
        "citations_direct": record.citations_direct,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
    else:
        if payload["recorded"]:
            print(f"consultation {record.consultation_id}", file=out)
        else:
            print(
                "silent visitor — nothing was recorded",
                file=out,
            )
        print(
            f"  evidence handed: {len(record.evidence_handed)}  ·  "
            f"citations: {len(record.citations)}  ·  direct: {record.citations_direct}"
            + ("  ·  recorded as a miss" if record.miss else "")
            + ("  ·  the archive was included" if payload["include_archived"] else ""),
            file=out,
        )
    return EXIT_OK


async def _default_emit(ctx: Any, user_id: UserId, record) -> None:
    """Emit an opening, answer, or both; await persistence and propagate any refusal.

    Each business event and its projection delivery commit together. CLI success means
    the event is durable; a failed write must not consume the retained handoff.
    """
    from ..api.routes.v1 import _spawn_recording

    task = _spawn_recording(ctx, user_id, record, strict=True)
    if task is not None:
        # A CLI process has no lifespan left to drain its detached write after exit.
        await task


async def cmd_consult_pending(
    ctx: Any,
    user_id: UserId,
    *,
    handoffs: Any,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """The hand-overs still waiting for an answer — what a resumed session comes back to."""
    out = out or sys.stdout
    err = err or sys.stderr
    rows = await handoffs.list_pending(user_id)
    if not rows:
        print("no handoff is waiting for an answer", file=err)
        return EXIT_NOTHING
    items = [
        {
            "handoff_id": handoff_id,
            "question": state.get("question"),
            "created_at": state.get("created_at"),
            "visitor_class": state.get("visitor_class"),
            "include_archived": bool(state.get("include_archived")),
            "evidence_handed": len(state.get("manifest") or []),
        }
        for handoff_id, state in rows
    ]
    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2), file=out)
    else:
        for item in items:
            print(f"{item['handoff_id']}  {item['created_at']}  {item['question']}", file=out)
    return EXIT_OK
