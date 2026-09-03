"""One pure builder per answering lane: a lane's answer object → a `ConsultationRecord`.

These live beside the lanes rather than beside the record because they are the only code
that has to know a lane's result shape, and that shape changes when a lane does. A caller —
the service, which is the only thing that writes a record — hands over the answer and the
identity fields it assigned, and picks no fields of its own; when a lane grows a face, one
of these three functions is where the record learns about it.

Pure: no I/O, no clock, no ids. Every system-assigned value (`consultation_id`,
`created_at`, `library_ref`, the visitor class) is a required keyword argument, so a record
never invents its own provenance.

Two mechanical rules hold across all three:

- **A query-local `sNN` handle never reaches a record.** The fast lane and the briefing ask
  alias source ids at the model boundary; a handle is valid for exactly one call, so
  persisting one would produce an address that resolves to nothing an hour later. Answers
  are written back through `resolve_handles`, and a cited handle the map does not know is
  DROPPED — which is the same rule the fast lane's own citation filter already applies.
  The RECORDED prose is cleaned too (`drop_unresolved_brackets`): a bracket that still
  names an unresolvable handle after the rewrite is removed from it. The answer on the wire
  is untouched — the caller sees what the model wrote; only the record is cleaned.
- **`citations` is a subset of `evidence_handed`, by construction.** A marker is admitted
  only when its resolved address is IN the lane's manifest — a claim by anchor equality, a
  span by containment inside a span the lane handed over for that same source. A real
  source id with an invented interval on it is prose, not provenance, and stays out.
- **The record carries what the lane exposes, and nothing reconstructed.** Where a lane has
  no such face (deep and the briefing ask publish no `answer_kind`), the record's field is
  empty rather than inferred. All three lanes now expose a manifest, the briefing ask
  included — the pack it answers over is its evidence, so the lane publishes it rather than
  the record naming the fetches alone and calling that the whole context.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ..domain.consultation import (
    ConsultationRecord,
    EvidenceRef,
    dedup_evidence,
    degraded_flags,
    is_miss,
    parse_span_ref,
    span_ref,
)
from ..domain.pricing import usage_pairs
from .citation_alias import (
    drop_unresolved_brackets,
    iter_answer_citations,
    resolve_handles,
)

if TYPE_CHECKING:  # pragma: no cover — typing only
    from .briefing import AskAnswer
    from .deep import DeepAnswer
    from .fast import FastAnswer

#: The fast lane's degradation flags, in the order `FastAnswer` declares them.
_FAST_DEGRADED = (
    "glance_degraded",
    "plan_degraded",
    "rerank_degraded",
    "evidence_selection_degraded",
    "answer_format_degraded",
    "route_degraded",
    "component_rerank_degraded",
)


def _admitted(
    manifest: tuple[EvidenceRef, ...],
) -> tuple[dict[str, str], dict[str, list[tuple[int, int, str]]]]:
    """The manifest indexed for admission: claim anchors by ref, spans by source id.

    Both maps hold the manifest entry's KIND as the value, so an admitted citation is
    recorded as the thing it was reached through (a window, an episode, a routed lookup, a
    page read in full) rather than as an untyped span.
    """
    anchors: dict[str, str] = {}
    spans: dict[str, list[tuple[int, int, str]]] = {}
    for ref in manifest:
        address = str(getattr(ref, "ref", "") or "")
        parsed = parse_span_ref(address)
        if parsed is None:
            if address.startswith("c:"):
                anchors.setdefault(address, str(getattr(ref, "kind", "claim")))
            continue
        source_id, start, end = parsed
        spans.setdefault(source_id, []).append((start, end, str(getattr(ref, "kind", ""))))
    return anchors, spans


def _cited_spans(
    answer: str, handles: dict[str, str], manifest: tuple[EvidenceRef, ...]
) -> tuple[EvidenceRef, ...]:
    """The answer's own citation markers as addresses — resolved, then ADMITTED.

    Two filters, and the second is the one that makes the field mean something. Resolution:
    `handles` empty means the lane never aliased (deep) and the ids in the markers are
    already real; `handles` non-empty means every legitimate marker names a handle in it, so
    an id the map does not know is one the lane itself would have refused. Admission: the
    resolved address must be IN the manifest — a claim by anchor equality, a span by
    containment inside a span the lane actually handed over for that same source. A model
    that copies a real source id and invents an interval on it (`[cite: s01 ¶999]` where
    blocks 1-2 were supplied) writes prose, not provenance, and the record says so by
    leaving it out.

    Containment rather than equality because citing part of what was shown is legitimate: a
    `¶2` out of a handed `¶1-3` is the answer being more precise than the evidence, not less
    grounded than it.
    """
    anchors, spans = _admitted(manifest)
    refs: list[EvidenceRef] = []
    for sid, start, end in iter_answer_citations(answer):
        if handles:
            real = handles.get(sid)
            if real is None:
                continue
        else:
            real = sid
        if real.startswith("c:"):
            kind = anchors.get(real)
            if kind is not None:
                refs.append(EvidenceRef(kind=kind, ref=real))
            continue
        for handed_start, handed_end, kind in spans.get(real, ()):
            if handed_start <= start and end <= handed_end:
                refs.append(span_ref(real, start, end, kind=kind or "window"))
                break
    return dedup_evidence(refs)


def consultation_from_fast(
    answer: "FastAnswer",
    *,
    user_id: str,
    lane: str,
    visitor_class: str,
    question: str,
    as_of: datetime | None,
    library_ref: str,
    consultation_id: str,
    created_at: datetime,
) -> ConsultationRecord:
    """The fast lane: ranked claims, episode summaries, body windows, component lookups.

    `evidence_handed` is COPIED from the lane's own manifest
    (`recall/fast.py:evidence_manifest`), never rebuilt out of the telemetry fields. Those
    fields report the ranked faces and nothing else: a claim the annotation join moved under
    its window, a claim the timeline section carries, a page the glance asked to be read in
    full — all of them were in front of the model and none of them are in `used_claims`. A
    recall with no ranked hits that answered out of one whole document used to record an
    empty `evidence_handed`, which the miss rule then read as an unanswered question.

    The component faces reach the manifest as `component` items addressed by whatever they
    actually are underneath (a claim anchor, a source span) — a routed lookup is a different
    ROUTE to evidence, not a different kind of evidence.
    """
    evidence_handed = dedup_evidence(list(getattr(answer, "evidence_manifest", ()) or ()))
    handles = dict(getattr(answer, "citation_handles", {}) or {})
    answer_kind = getattr(answer, "answer_kind", None)
    return ConsultationRecord(
        consultation_id=consultation_id,
        user_id=user_id,
        created_at=created_at,
        lane=lane,
        visitor_class=visitor_class,
        question=question,
        as_of=as_of,
        library_ref=library_ref,
        evidence_handed=evidence_handed,
        answer_kind=answer_kind,
        # Fast aliases unconditionally (`_alias_human_content` runs on every answering
        # call), so an unresolvable bracket here is always a handle that resolves to
        # nothing — including when the map is empty because the lane surfaced no source.
        answer=drop_unresolved_brackets(
            resolve_handles(answer.answer, handles), set(handles.values())
        ),
        citations=_cited_spans(answer.answer, handles, evidence_handed),
        miss=is_miss(answer_kind, evidence_handed),
        degraded=degraded_flags(answer, _FAST_DEGRADED),
        token_usage=usage_pairs(getattr(answer, "token_usage", None)),
    )


def consultation_from_deep(
    answer: "DeepAnswer",
    *,
    user_id: str,
    lane: str,
    visitor_class: str,
    question: str,
    as_of: datetime | None,
    library_ref: str,
    consultation_id: str,
    created_at: datetime,
) -> ConsultationRecord:
    """The deep lane: every claim and window the agentic loop surfaced, seed and search.

    Deep does not alias source ids (its loop re-retrieves across rounds, so one source would
    get different handles in different turns), so the answer's markers are already real and
    the handle map is empty by construction. It publishes no `answer_kind` and no
    degradation flags either — both stay empty rather than being guessed from the text.

    `evidence_handed` is the loop's own manifest, copied: the seed context plus everything
    its tools returned into the transcript, including the pages `read_document` opened in
    full — which `used_claims` and `used_windows` do not mention at all.
    """
    evidence_handed = dedup_evidence(list(getattr(answer, "evidence_manifest", ()) or ()))
    return ConsultationRecord(
        consultation_id=consultation_id,
        user_id=user_id,
        created_at=created_at,
        lane=lane,
        visitor_class=visitor_class,
        question=question,
        as_of=as_of,
        library_ref=library_ref,
        evidence_handed=evidence_handed,
        answer_kind=None,
        answer=answer.answer,
        citations=_cited_spans(answer.answer, {}, evidence_handed),
        miss=is_miss(None, evidence_handed),
        degraded=(),
        token_usage=usage_pairs(getattr(answer, "token_usage", None)),
    )


def consultation_from_briefing_ask(
    answer: "AskAnswer",
    *,
    user_id: str,
    lane: str,
    visitor_class: str,
    question: str,
    as_of: datetime | None,
    library_ref: str,
    consultation_id: str,
    created_at: datetime,
) -> ConsultationRecord:
    """The briefing ask: the frozen pack, what `search_knowledge` showed, what was fetched.

    `evidence_handed` is COPIED from the lane's own manifest (`recall/briefing.py`,
    `_ask_manifest`), like the other two lanes. It used to hold the loop's verbatim fetches
    alone, on the reasoning that the pack was assembled before the question existed and the
    lane did not republish it — but the pack IS this lane's evidence, and a record that
    named only the fetches said a smaller thing than the ask rested on. Worse, it left the
    citations with nothing to be admitted against: every marker the model wrote was copied
    into the record, so an invented span on a real source id was stored as provenance.

    Now the pack is published, and the citations are ADMITTED against it exactly as fast
    and deep admit theirs — a claim by anchor, a span by containment in a span the lane
    handed over. What the pack never showed (the library glance, a source's structure
    outline) is not in the manifest and so cannot be cited; that is the point.

    The recorded prose is cleaned of unresolvable brackets ONLY when the ask aliased. An
    unaliased ask (`citation_alias` off) writes real source ids, and those are addresses
    that still resolve tomorrow — the cleaning rule is about query-local handles outliving
    the query that minted them, and there are none.

    The miss rule is the common one now, with no lane exception: an ask that reaches this
    builder with an empty manifest was answered over an empty pack, with nothing searched
    and nothing fetched, which is the library being asked something it had nothing for.
    """
    handles = dict(getattr(answer, "citation_handles", {}) or {})
    # Whether this ask aliased at all is a DEPLOYMENT setting (`citation_alias`), so the
    # lane declares it rather than the record inferring it from an empty handle map: with
    # aliasing off the answer's markers are already real source ids and every one of them
    # must survive into the record; with it on and nothing surfaced, the map is empty in
    # exactly the same way and every marker must go.
    aliased = bool(getattr(answer, "aliased", False))
    evidence_handed = dedup_evidence(
        list(getattr(answer, "evidence_manifest", ()) or ())
    )
    return ConsultationRecord(
        consultation_id=consultation_id,
        user_id=user_id,
        created_at=created_at,
        lane=lane,
        visitor_class=visitor_class,
        question=question,
        as_of=as_of,
        library_ref=library_ref,
        evidence_handed=evidence_handed,
        answer_kind=None,
        answer=(
            drop_unresolved_brackets(
                resolve_handles(answer.answer, handles), set(handles.values())
            )
            if aliased
            else answer.answer
        ),
        citations=_cited_spans(answer.answer, handles if aliased else {}, evidence_handed),
        miss=is_miss(None, evidence_handed),
        degraded=(),
        token_usage=usage_pairs(getattr(answer, "token_usage", None)),
    )


__all__ = [
    "consultation_from_briefing_ask",
    "consultation_from_deep",
    "consultation_from_fast",
]
