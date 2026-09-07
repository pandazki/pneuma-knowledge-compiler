"""`pkc consult answer` — closing a hand-over into a consultation (§5.1).

`pkc recall --evidence` gave the Steward the fast lane's assembled context and made no
answering call, so what exists at that moment is a question, an instant, a library ref and an
evidence manifest — and no answer. This command supplies the answer and turns the pair into a
`ConsultationRecord`.

Three things it does NOT do, and each is the point:

- **it does not build the record itself.** `consultation_from_fast` builds it — the fast
  lane's own builder, the same one `/recall` calls — over a stand-in carrying exactly the
  fields that builder reads. So the citation rule is the lane's rule, not a second copy of
  it: a marker is resolved through the hand-over's handle map and admitted only if the
  resolved address is inside the manifest, and a real source id with an invented interval on
  it stays out.
- **it does not write the row itself.** `_spawn_recording` writes it — the same emission the
  answering routes use, so a `business` answer enqueues its one `recall_projection` job in
  the same transaction and a `silent` one is never written at all.
- **it does not backfill a missing answer.** A hand-over nobody answered expires and leaves
  no consultation. That is honest: the library was asked something and nothing was recorded
  as having come back, which is exactly what happened.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TextIO

from pneuma_knowledge_core.domain.consultation import EvidenceRef
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.consultation import consultation_from_fast

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_REFUSED = 2

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
        print(
            f"no pending handoff {handoff_id} — it was answered already, or it expired "
            "(PNEUMA_KNOWLEDGE_RECALL_HANDOFF_TTL)",
            file=err,
        )
        return EXIT_NOTHING
    body = text.rstrip("\n")
    if kind == "answer" and not body.strip():
        print(
            "an empty answer is not an answer — say `--kind no_record` when the library "
            "held nothing",
            file=err,
        )
        return EXIT_REFUSED

    as_of = state.get("as_of")
    record = consultation_from_fast(
        _AnsweredHandoff(
            answer=body,
            answer_kind=kind,
            evidence_manifest=_manifest(state.get("manifest")),
            citation_handles=dict(state.get("handles") or {}),
        ),
        user_id=str(user_id),
        lane="fast",
        visitor_class=str(state.get("visitor_class") or "silent"),
        question=str(state.get("question") or ""),
        as_of=datetime.fromisoformat(as_of) if as_of else None,
        library_ref=str(state.get("library_ref") or ""),
        consultation_id=uuid.uuid4().hex,
        created_at=datetime.now(timezone.utc),
    )
    # `silent` leaves no trace at all — not a row, not a job, not a task. The class was fixed
    # at hand-over, so a Steward cannot make a silent question recordable after the fact by
    # answering it differently.
    if str(state.get("visitor_class") or "silent") != "silent":
        writer = emit or _default_emit
        await writer(ctx, user_id, record)
    await handoffs.delete(user_id, handoff_id)

    payload = {
        "consultation_id": record.consultation_id,
        "recorded": str(state.get("visitor_class") or "silent") != "silent",
        # THE SCOPE THE ANSWER WAS WRITTEN OVER, carried from the hand-over rather than
        # decided here. `--evidence` assembled the context under `include_archived` and the
        # Steward answered out of those bytes; a close that said nothing about it would leave
        # a consultation over the archive indistinguishable from one over the present
        # (docs/design/archive.md §4).
        "include_archived": bool(state.get("include_archived")),
        "visitor_class": record.visitor_class,
        "question": record.question,
        "answer_kind": record.answer_kind,
        "miss": record.miss,
        "citations": [
            {"kind": c.kind, "ref": c.ref, "path": c.path} for c in record.citations
        ],
        "evidence_handed": len(record.evidence_handed),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
    else:
        if payload["recorded"]:
            print(f"consultation {record.consultation_id}", file=out)
        else:
            print(
                "silent visitor — nothing was recorded, and the handoff is closed",
                file=out,
            )
        print(
            f"  cited {len(record.citations)} of {len(record.evidence_handed)} handed "
            f"address(es)"
            + ("  ·  recorded as a miss" if record.miss else "")
            + ("  ·  the archive was included" if payload["include_archived"] else ""),
            file=out,
        )
    return EXIT_OK


async def _default_emit(ctx: Any, user_id: UserId, record) -> None:
    """The answering routes' own emission: the row, and for a `business` visitor the one
    `recall_projection` job, in the same transaction the store writes them in."""
    await ctx.store.create_consultation(user_id, record)


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
