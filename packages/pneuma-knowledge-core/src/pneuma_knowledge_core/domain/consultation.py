"""The consultation record — one answering-lane call, as the audit chain needs it.

USE-SIDE L0
-----------
Knowledge L0 is what the owner put there. A consultation is the other kind of record: what
the system OBSERVED — a question was asked, this evidence was put in front of a model, this
came back. Kept rather than re-derived, and never an authority over knowledge: canonical
derives from knowledge L0 and from nothing else, and no gate, contract or projection reads a
consultation to decide what is true.

Kept is not the same as untouched. A lane that aliases source ids into query-local handles
resolves them back before the answer is recorded, and a bracket still naming a handle that
resolves to nothing is dropped from the recorded prose; `citations` is filtered by the same
map and then admitted only against `evidence_handed`. The builders below are where that
happens, one per lane, and the answer on the wire is never touched — the caller sees what the
model wrote, and the record carries addresses that resolve.

WHAT THE RECORD IS ALLOWED TO CARRY
-----------------------------------
Addresses and the lane's own output, and no prose the lane did not already emit. Evidence is
named by the one addressing scheme the rest of the system uses (I4): a claim is `c:<anchor>`
with the page it lives on, a source span is `<source_id> ¶a-b` in the spelling
`domain/canonical.py` normalizes markers to. A record therefore stays small, stays joinable
against canonical and L0, and cannot become a second copy of the library.

WHERE IT LIVES
--------------
Not here. Core defines the type and the pure mapping from a lane's answer to one; the
SERVICE decides whether to write it, writes it, and owns the table. That split is
deliberate: the record belongs to the steward that answered, not to the library it read, so
core holds no consultation port and reads no consultation. The builders below are the whole
of core's involvement — one per lane, so a caller does no field-picking of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .canonical import format_citation_span

#: The answering lanes that produce a record. `rag` is absent on purpose: it runs no model,
#: so there is no "what was handed to it" for a record to be about.
LANE_VALUES = ("fast", "deep", "briefing_ask")

#: Recording and influence are two axes; these are the three points on them the framework
#: ships. `silent` is the default everywhere, so an unchanged caller leaves no trace.
VISITOR_CLASS_VALUES = ("silent", "audit", "business")

#: What an evidence item IS, not where it came from: a compiled claim, a verbatim source
#: window, a derived episode description, an item a component's routed path contributed, or
#: a whole canonical page the lane opened and read in full.
#:
#: `document` is the honest address for the last of those. A fully-expanded page is neither
#: a claim nor a span — it is the page itself, and the two dishonest alternatives were to
#: name one of its claims (which claim?) or to invent a span for a thing that has no source
#: interval. It maps 1:1 onto the `document` target the attention ledger already counts.
EVIDENCE_KIND_VALUES = ("claim", "window", "episode", "component", "document")

Lane = Literal["fast", "deep", "briefing_ask"]
VisitorClass = Literal["silent", "audit", "business"]
EvidenceKind = Literal["claim", "window", "episode", "component", "document"]


@dataclass(frozen=True)
class EvidenceRef:
    """One address, and nothing else — no text, no score, no rank.

    `ref` is the existing address in its existing grammar: `c:<anchor>` for a claim,
    `<source_id> ¶a-b` for a span. `path` is the canonical page a claim lives on, and is
    empty for every other kind (a span has no page; it has a source).
    """

    kind: str
    ref: str
    path: str = ""


@dataclass(frozen=True)
class ConsultationRecord:
    """One consultation, as its lane emitted it. Frozen: a record of what happened is not
    editable."""

    #: Identity — all three system-assigned by the caller, never by the model or the client.
    consultation_id: str
    user_id: str
    created_at: datetime
    lane: str
    visitor_class: str
    #: The question as it was asked, and the instant the lane resolved relative time against.
    question: str
    as_of: datetime | None
    #: The canonical HEAD SAMPLED WHEN THE CONSULTATION BEGAN — the snapshot id instead
    #: when the call was pinned, which is the exact form of the same field.
    #:
    #: A sample, and the word is doing work. The evidence faces read LIVE state: a compile
    #: landing mid-answer moves HEAD, and the canonical and claim-index reads that follow
    #: the sample are unversioned, so what the model saw may have advanced past the ref
    #: recorded here. What the field says is where the reading started; what it does not say
    #: is that every face came from that one state. Only a pinned call can promise that, and
    #: a pinned call says so by naming a snapshot. The audit chain's other half all the
    #: same — the answer alone does not say which library it came out of.
    library_ref: str
    #: Every address the lane put in front of the model, and nothing else. The lane
    #: publishes it as a manifest at the moment each face is rendered; the builder copies
    #: it. It carries both the evidence ITEMS (a claim, a window, an episode, a routed
    #: lookup, a page read in full) and the provenance spans rendered WITH them — a claim
    #: note carries its own `[cite: …]` marker, and the contract tells the model to copy
    #: exactly those markers, so a span named there is an address that reached the model.
    #: `citations` is a subset of this by construction.
    evidence_handed: tuple[EvidenceRef, ...] = ()
    answer_kind: str | None = None
    answer: str = ""
    #: The addresses the answer actually cited, after the lane's own citation filter.
    citations: tuple[EvidenceRef, ...] = ()
    #: `is_miss` over the two fields above it. Stored rather than recomputed at read time so
    #: a replay of the records cannot disagree with what was recorded.
    miss: bool = False
    #: The lane's degradation flags, copied as `(field, value)` pairs in field order — only
    #: the ones that fired, so an undegraded run carries an empty tuple.
    degraded: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    #: What this consultation SPENT, in tokens: the lane's own `token_usage` mapping as
    #: field-ordered pairs (`domain/pricing.py:usage_pairs`).
    #:
    #: Tokens and not money, deliberately. The token count is what happened and stays true;
    #: a price is a commercial arrangement that moves without asking this record, so money
    #: is computed when someone reads — out of the rates the deployment declares then — and
    #: a stored amount would be a number nobody can reproduce a quarter later.
    token_usage: tuple[tuple[str, int], ...] = field(default_factory=tuple)


def is_miss(answer_kind: str | None, evidence_handed: tuple[EvidenceRef, ...]) -> bool:
    """Did this consultation come back with nothing?

    Two ways, and they are different failures: the model said so (`no_record`), or the
    retrieval put nothing in front of it at all. Both are the library being asked something
    it could not answer, which is the one signal a use-side record exists to keep.

    ONE RULE, EVERY LANE. There used to be a `lane` exception here: a `briefing_ask`
    answers over a pack that was assembled and frozen when the briefing was built, and the
    lane republished only the fetches the loop made mid-answer — so an ask the pack answered
    on its own handed back an empty manifest and would have been recorded as a miss for
    having had its evidence in advance. That was a symptom of the manifest being wrong, not
    of the rule being wrong: the ask now publishes the pack it was given (`_ask_manifest`),
    so an empty manifest there means what it means everywhere — the pack was empty, nothing
    was searched, nothing was fetched. Everything downstream of this (a component counting
    what the library was asked and could not answer) is only as truthful as this predicate,
    and it is more truthful with one rule than with an exception standing in for a gap.
    """
    return answer_kind == "no_record" or not evidence_handed


# --------------------------------------------------------------- address construction


def claim_ref(anchor: str, document_path: str, *, kind: str = "claim") -> EvidenceRef:
    """A claim's address. `c:` is added here — `RetrievedClaim.anchor` is the bare id, and
    every renderer in the system prefixes it at the point of rendering."""
    bare = str(anchor).strip().removeprefix("c:")
    return EvidenceRef(kind=kind, ref=f"c:{bare}", path=str(document_path or ""))


def span_ref(
    source_id: str, block_start: int, block_end: int, *, kind: str = "window"
) -> EvidenceRef:
    """A source span's address, in the canonical citation grammar."""
    return EvidenceRef(
        kind=kind,
        ref=format_citation_span(str(source_id), int(block_start), int(block_end)),
    )


def document_ref(path: str, *, kind: str = "document") -> EvidenceRef:
    """A whole canonical page's address: the path, which is what the page IS.

    `ref` is the path rather than the path being tucked into `path` with an empty `ref`,
    because every consumer of a record addresses an item by `ref` and a document read in
    full is an item."""
    return EvidenceRef(kind=kind, ref=str(path or ""))


def parse_span_ref(ref: str) -> tuple[str, int, int] | None:
    """`<source_id> ¶a-b` → `(source_id, a, b)`; `None` for an address of any other shape.

    The inverse of `format_citation_span`, and the only place a record's own grammar is
    read back — a claim anchor (`c:xxxx`) and a page path both return `None` here, which is
    what makes "is this address a span?" one question with one answer.
    """
    source_id, separator, span = str(ref or "").partition(" ¶")
    if not separator or not source_id.strip():
        return None
    start, _dash, end = span.partition("-")
    try:
        first = int(start)
        last = int(end) if end else first
    except ValueError:
        return None
    return source_id.strip(), first, last


def dedup_evidence(refs: list[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    """First-appearance order, one entry per ADDRESS — `(ref, path)`, first kind wins.

    A lane can surface the same claim twice: a ranked face and a component lookup that
    corroborated it, the same span as a shown window and as some claim's provenance. The
    record answers "what was this consultation shown", which is a set of addresses; a
    projection counting attention over these must not count one item twice because two
    faces reached it.

    `kind` is deliberately NOT in the key. It says how a lane reached an item, not what the
    item is — the same claim arrives as `claim` from the ranked face and as `component` from
    a routed lookup — so keying on it kept both copies of one address and doubled that
    claim's heat, in a projection that dispatches on the address shape and never looks at
    `kind` at all. The first kind is the one that survives, which is why a manifest lists
    the evidence ITEMS before the provenance spans rendered with them: a span that is both
    a shown window and a claim's marker keeps `window`, the kind that says more about it.
    """
    seen: set[tuple[str, str]] = set()
    out: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.ref, ref.path)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return tuple(out)


def degraded_flags(answer: object, fields: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """The lane's `*_degraded` fields that actually fired, in the order listed."""
    out: list[tuple[str, str]] = []
    for name in fields:
        value = getattr(answer, name, None)
        if value:
            out.append((name, str(value)))
    return tuple(out)
