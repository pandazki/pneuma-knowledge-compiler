"""Live Context, full scope: discover → retrieve → pick.

The lane this replaces retrieved on EVERY quiet-period tick — one embedding round, a claim
face and a window face per transcript turn — and then asked one large model to author cards
out of whatever came back. Two things were wrong with it and neither was a tuning problem:

- **It paid for retrieval before knowing whether anything was worth retrieving.** 「中午吃
  什么」 cost the same four index round trips as a question the library can actually answer.
- **It was semantically blunt.** Per-turn queries are the turns' own words, so a conversation
  hunting for *a person on the Lumenlab team* retrieves *Lumenlab* and delivers a card
  defining what Lumenlab is. Nobody asked what it is; everyone in the room already knows.

So the lane now spends a SMALL reasoning call first, and that call has ONE job, stated as a
principle rather than as a list of cases: **write, on the room's behalf, the one question
most worth asking right now** — or say that no such question can be written.

That one sentence is the whole of stage 1, and everything the lane used to accrete as
separate case-law falls out of it: an unnamed role means the room would ask *who is that*;
a first-mention product means *what is X*; a find-a-person ask means *who here knows X best*;
small talk means no question worth asking, so skip; a subject the room keeps naming and never
asks about is a question it already knows the answer to, so skip again. Once the question
exists, the stages below it are the fast lane's ordinary work — retrieve, select evidence,
answer honestly.

1. **discover** (`live_discover`, small reasoning model, LOW effort, short output). Reads the
   pending window and the session's subject ledger. Emits either `skip(reason)` — and the
   tick ends having touched no index at all — or the question itself as `intent`, a `plan` of
   up to four lookups (how you would go and answer it) over the enabled component paths plus
   `semantic`, and a `worth` score (what the answer would be worth to the room). One lookup
   per distinct thing to find: the bound is on the FAN-OUT and not a target, because a
   `semantic` entry costs one embedding and a question with one clear need still takes one. `intent` doubles as the
   delivered card's trigger line, which is why it is phrased as a question somebody could
   have asked aloud: the owner reads it as the reason the card appeared.
2. **retrieve** (no model). Every plan entry runs CONCURRENTLY: component paths through the
   ordinary `run_paths`, and each `semantic` entry through its own `retrieve_claims` +
   `rag_recall`, all of them embedded in one batched call. Their returns merge into ONE pool,
   deduped and interleaved so no single query can fill the candidate list on its own. What
   comes back is turned into numbered candidate cards MECHANICALLY — claim text verbatim,
   citations attached by construction, never a sentence a model wrote.
3. **pick** (`live_pick`, weak fast model, reasoning off). Sees the conversation and the
   numbered candidates and answers with an index (or `none`), a SHORT lede framing why this
   matters to the reader right now, the subset of the candidate's own citations that carries
   it, and a confidence. It picks, frames, prunes and scores. It never rewrites: the card's
   evidence section is the candidate's mechanical rendering, byte for byte.

**Two doors, one number.** `min_confidence` gates twice: as discover's `worth` floor it
decides whether to retrieve at all (cheap, before any I/O), and as pick's `confidence` floor
it decides whether to deliver. The first door is a guess about a conversation, the second a
judgement about a specific card, and one dial moves both because a deployment that wants
fewer interruptions wants fewer of both.

**Pick has ONE criterion: does this candidate's own text ANSWER the question?** The contract
says so in the only place that can be enforced — the contract itself — because the failure it
fixes is not mechanical. Asked about a release the library had never heard of, the lane
retrieved the nearest internal project, and the pick scored it 9: the candidate was well
written, richly cited and about roughly that area, and every one of those is a fact about the
library rather than an answer to the question. Four consequences of the one criterion carry
the cases that were each once a live failure — text saying it CANNOT answer answers nothing
(choose 0), adjacency is not an answer, a MARKED nearest-fit recommendation is one, and which
pool a candidate came out of is not a ranking. Nothing here second-guesses the model
mechanically — a high score still delivers — because a mechanism that overrode the judgement
would be guessing about language, and the judgement is exactly what the contract buys.

**Repetition is a ledger, not a plea.** A room that keeps naming a project does not want to
be told what the project is a fourth time. `SubjectLedger` counts, per session, what
retrieval touched and what was delivered about it; the digest rides the Human turn so
discover can skip on it, and `held_as_duplicate` is the mechanical backstop underneath —
a second *introduction* about a subject is refused however convincing the models were, while
a *fact* about the same subject is a different card and passes.

I5 holds throughout: both SystemMessages are assembled from the catalog and the enabled path
set, and every volatile thing (the digest, `as_of`, the transcript, the candidates) rides the
Human turn.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from itertools import chain, zip_longest
from typing import TYPE_CHECKING

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from ..canonical_glance import (
    claim_display_text,
    document_definition,
    document_title,
    resolve_subject,
)
from ..compile.documents import OVERVIEW_LABEL, overview_region
from ..compile.overview import ANCHOR_REFERENCE_RE
from ..domain.canonical import Citation
from ..domain.ids import UserId
from ..domain.source import ConversationTurn
from ..domain.suggestion import (
    DEFAULT_DENSITY,
    ContextDensity,
    ContextFocus,
    DiscoverResult,
    PickResult,
    PlanEntry,
    ResolvedSuggestion,
    SuggestionKind,
    WebCitation,
    coerce_density,
)
from ..ports.claim_index import ClaimLexicalIndex, ClaimVectorIndex
from ..ports.content_store import ContentStore
from ..ports.lexical_index import LexicalIndex
from ..ports.vector_index import VectorIndex
from ..ports.web_search import WebSearch, WebSearchAnswer
from ..prompts import prompt
from .assembly import expand_and_merge, order_lost_in_middle
from .projection import project_document_claims
from .fast import (
    RetrievedClaim,
    extract_usage,
    invoke_config,
    retrieve_claims,
    zero_usage,
)
from .paths import ComponentEvidence, FastPath, run_paths
from .rag import RecallHit, _suppress_overlapping, rag_recall
from .stage_timing import StageRecorder, StageTiming, child_name
from .suggestion import label_turns, render_transcript

# ------------------------------------------------------------------------- constants

#: The built-in plan kind, always offered. Every other kind is a registered path's name.
SEMANTIC = "semantic"

#: The supplementary plan kind. Unlike `semantic` it is offered CONDITIONALLY — only when
#: the deployment enabled a web search and the client allowed one on this connection — so
#: the discover SystemMessage has exactly two shapes per enabled path set, and both are
#: byte-pinned. A `web` entry in a plan that was never offered one is rejected mechanically,
#: the same way an unknown component kind is.
WEB = "web"

#: How many transcript turns one tick may read. The window is the PENDING one — everything
#: said since the last tick — and this bounds it; the overflow is not dropped silently but
#: summarised into the digest as a stated count (see `PendingWindow`).
if TYPE_CHECKING:  # pragma: no cover — typing only
    from ..domain.canonical import CanonicalDocument

_log = logging.getLogger(__name__)

DEFAULT_MAX_PENDING_TURNS = 12

#: How many candidate cards the pick stage may be shown. Not a knob: it is the size of a
#: list a weak model can choose from reliably, and a deployment that wants fewer
#: interruptions turns `min_confidence` up, which is the dial that means that.
MAX_CANDIDATES = 6

#: Characters one candidate's mechanically rendered evidence may occupy.
CANDIDATE_BODY_CHARS = 700

#: Characters the pick stage's lede may occupy, truncated on a sentence boundary. The
#: contract also asks for short; this is what makes it true.
LEDE_CHARS = 200

#: The semantic path's own budgets, PER QUERY — the plan's queries, not the transcript's
#: turns, so these can be larger than the per-turn numbers they replace and still cost less.
#: A fan-out multiplies them, and `_interleave` plus `MAX_CANDIDATES` is what bounds the pool
#: that reaches the pick stage.
SEMANTIC_CLAIMS = 8
SEMANTIC_WINDOWS = 4

#: Claims one mechanically built candidate carries.
CLAIMS_PER_CANDIDATE = 3

#: The Live Context lane's stage vocabulary (see `stage_timing.py` — the vocabulary belongs
#: to the lane). `retrieve`'s children are the semantic face and one `retrieve.path:<name>`
#: per routed component path, which is the shared child mechanism unchanged.
#: `glance` sits between discover and retrieve because that is exactly where it happens:
#: the plan is parsed, the provisional card goes out, and everything below it runs on.
STAGE_ORDER: tuple[str, ...] = ("discover", "glance", "retrieve", "pick", "total")
RETRIEVE_CHILDREN: tuple[str, ...] = ("semantic", "web")

#: Seconds the web face may take before the tick stops waiting for it. A constant and not a
#: knob: this is a SUPPLEMENTARY path, and the property that matters is that a dead search
#: never delays a card the library could already have delivered. Fifteen seconds is long
#: enough for a native search with a couple of queries behind it and short enough that a
#: reader mid-conversation does not notice it was tried. A timeout is a degraded face in the
#: tick record, never an error and never a lost tick.
WEB_FACE_TIMEOUT_S = 15.0

#: How many searches one web lookup may run. The provider bills per search.
WEB_MAX_RESULTS = 3

#: WHICH POOL a candidate came out of, as the pick stage is shown it. One pool, one picker:
#: the web result is candidate N in the same numbered list and is chosen (or not) by the
#: same call, and this is the field that lets the contract's source-blind rule be about
#: something. Distinct from `SuggestionCandidate.origin`, which is the fine-grained face
#: name for the debug surface — this one is the two words a model reads.
PROVENANCE_LIBRARY = "library"
PROVENANCE_WEB = "web"

#: How the web face was reached this tick, for the Processing record.
#:   `off`      — never ran: the toggle is off, or nothing needed it.
#:   `planned`  — discover asked for it, so it ran CONCURRENTLY with the library faces.
#:   `fallback` — discover did not ask, the library came back with nothing at all, and the
#:                toggle is on. The one sequential case, and it is sequential because it is
#:                a consequence: nothing was worth paying for until the library was empty.
WEB_OFF = "off"
WEB_PLANNED = "planned"
WEB_FALLBACK = "fallback"

#: Skip reasons the pipeline itself assigns. A model-supplied reason is passed through as
#: written; these are the ones a mechanism produced and they must be spelled one way so the
#: counters can be added up.
SKIP_UNPARSED = "unparsed"
SKIP_LOW_WORTH = "low_worth"
SKIP_NO_PLAN = "no_plan"
SKIP_NO_CANDIDATES = "no_candidates"
#: The pick answered 0 — it read the candidates against the intent and none of them covers
#: it. Distinct from `low_confidence` on purpose: a low score is a weak answer, and this is
#: the library saying it has no answer at all. The two look identical on a silent tick and
#: mean opposite things about whether the lane is working, so the Processing tab gets both.
SKIP_NO_COVERAGE = "no_coverage"
#: The pick named a candidate index that does not exist — a malformed emission, not a
#: judgement. Kept apart from `no_coverage` for the same reason.
SKIP_NONE_CHOSEN = "none_chosen"
SKIP_LOW_CONFIDENCE = "low_confidence"
#: Nothing carried the card: neither the pruned citation subset nor the candidate's own
#: list holds one span or one URL. Belt under a construction that already attaches
#: provenance — the library face gets its citations from retrieval and the web face is
#: refused at build time without a URL, so this should be unreachable, and it is here so
#: that "should be" is a mechanism rather than a hope.
SKIP_UNCITED = "uncited"
SKIP_DUPLICATE = "duplicate"
SKIP_PICK_FAILED = "pick_failed"


# --------------------------------------------------------------------- the contracts


def _path_offer(path: FastPath) -> str:
    """One offered path, as the discover contract advertises it.

    Assembled from the path's OWN `description` and its OWN argument schema — core names no
    component here, so the contract text is a function of the enabled set and nothing else.
    That is what makes it byte-stable per deployment (I5) rather than merely constant."""
    args = ", ".join(path.args_schema.model_fields)
    return prompt(
        "recall.live.discover.path_offer",
        kind=path.name,
        description=" ".join(str(path.description).split()),
        args=args,
    )


def discover_contract(
    focus: ContextFocus = "general",
    paths: Sequence[FastPath] = (),
    *,
    web: bool = False,
    density: ContextDensity = DEFAULT_DENSITY,
) -> str:
    """The discover SystemMessage. Byte-stable per (focus, enabled path set, web on/off,
    density).

    With no component registered the `kinds` section holds `semantic` alone, which is
    exactly the contract this lane had before the seam existed.

    `web` adds ONE line at the end of that section, and it is a parameter rather than a
    setting read in here because the offer has two owners: a deployment enables the search
    and a connection allows it, and the contract may only advertise a lookup that both of
    them said yes to. Advertising it otherwise would spend the small model's attention
    planning a retrieval that `plan_runs` was always going to reject. I5 is untouched — the
    result is still a function of the enabled set and nothing volatile, which is why both
    variants can be (and are) byte-pinned.

    `density` varies ONE clause — HOW LATENT the question may be — and nothing else. Under
    one principle there is only one thing left for a posture to move: quiet takes only
    questions somebody actually asked aloud, balanced takes questions the conversation
    clearly implies, eager also takes questions the room does not yet realise it should ask.
    The three postures were preset numbers before, and numbers alone could only move how MUCH
    got through: on the eager preset a turn handing work to an unnamed role was skipped,
    because a role standing in for a person nobody named was not a question the one shared
    wording recognised, whatever the floors were set to. The principle, the skip vocabulary
    and the three output fields stay shared, which is what keeps these three wordings of one
    contract rather than three contracts. The PICK contract does not vary: how honestly a
    card is delivered is not a density matter."""
    offers = [_path_offer(p) for p in paths]
    offers.append(prompt("recall.live.discover.semantic_offer"))
    if web:
        offers.append(prompt("recall.live.discover.web_offer"))
    return prompt(
        "recall.live.discover.contract",
        focus=prompt(f"recall.suggestion.focus.{focus}"),
        kinds="\n".join(offers),
        mining=prompt(f"recall.live.discover.mining.{coerce_density(density)}"),
    )


def pick_contract() -> str:
    """The pick SystemMessage. One string, no focus axis: the attention posture was already
    spent in discover, and this stage only chooses between cards discover's own plan
    produced. One criterion — does the candidate's own text answer discover's question — with
    the honesty clauses stated as its consequences rather than as coordinate rules.

    The OPEN-QUESTION clause beside the adjacency one is contract text and NOT a mechanism,
    deliberately. What it addresses is a conf-5 card that answered 「应该围绕什么真实痛点设计
    核心工作流？」 with the nearest internal project page — an open product question paired
    with whatever the library happened to hold next to it. A mechanism that recognised "open
    question" and blocked it would be guessing about language, and it would be wrong the
    first time a page really did bear on one. So the clause says what a good delivery looks
    like — the page's own text has to bear on the question, scored by how directly it helps —
    and leaves the judgement where the contract can buy it."""
    return prompt("recall.live.pick.contract")


# --------------------------------------------------------------- the pending window


@dataclass(frozen=True)
class PendingWindow:
    """The turns one tick reads, and the ones it could not fit.

    A tick reads everything said since the last tick — not a fixed last-N slice — because a
    burst that arrived during a slow evaluation is exactly the material the next tick must
    not have missed. `max_pending_turns` bounds that; the overflow is NOT dropped silently:
    `overflowed` is stated in the Human turn, so a reader (and the model) knows the window
    is a tail rather than the whole story."""

    turns: tuple[ConversationTurn, ...]
    overflowed: int = 0


def take_pending(
    turns: Sequence[ConversationTurn], *, max_pending_turns: int = DEFAULT_MAX_PENDING_TURNS
) -> PendingWindow:
    """The newest `max_pending_turns` of a pending run, plus how many did not fit."""
    limit = max(1, int(max_pending_turns))
    kept = list(turns)[-limit:]
    return PendingWindow(turns=tuple(kept), overflowed=max(len(turns) - len(kept), 0))


#: How many already-processed turns ride above the pending window, read-only. A CONSTANT,
#: not a knob: it is the size of a short-term memory, and a deployment that could raise it
#: would be paying the discover call's whole argument — that it is short — for context the
#: stage is forbidden to mine anyway.
DEFAULT_CONTEXT_TURNS = 8


def take_context(
    processed: Sequence[ConversationTurn],
    pending: Sequence[ConversationTurn],
    *,
    max_context_turns: int = DEFAULT_CONTEXT_TURNS,
) -> tuple[ConversationTurn, ...]:
    """The read-only tail: the most recent processed turns, newest-last, bounded.

    TWO ROLES, ONE TRANSCRIPT — and separating them is the whole of this. The pending run
    says WHAT IS NEW TO MINE and is consumed by the tick that reads it (a skip consumes too,
    which is the point: a stretch judged small talk is not re-judged and not re-paid for).
    But intent formation is not mining. A tick whose pending run is 「也可以看看其他团队有没有
    这方面的专家」 and nothing else has to invent what the expertise IS — and it will: measured
    live, four turns about Apple's foldable phone were consumed by a quiet skip tick, and the
    fifth turn alone produced an intent about **Android** foldables. The subject had not
    changed; the window had.

    So the tail rides along, above the new content and labelled as understood-not-evaluated.
    It changes nothing about consumption: the same turns are mined exactly once, and are
    afterwards only readable.
    """
    limit = max(0, int(max_context_turns))
    if not limit:
        return ()
    # Excluded by IDENTITY, not by value: two turns are equal whenever their text is, and a
    # room where somebody says 「好的」 twice would otherwise lose the earlier one out of the
    # tail. What must never be both blocks is the same TURN, and that is what identity says.
    held = {id(t) for t in pending}
    keep = [t for t in processed if id(t) not in held]
    return tuple(keep[-limit:])


# --------------------------------------------------------------- the subject ledger


@dataclass
class SubjectRecord:
    """What one session has done with one subject."""

    key: str
    label: str
    mentions: int = 0
    asked: bool = False
    #: The card kinds already delivered about this subject (`concept` / `fact`).
    delivered: set[str] = field(default_factory=set)


#: Cheap, mechanical "did anyone actually ASK about this". Not NLP and not pretending to be:
#: a question mark, or one of the interrogatives that carry a question in Chinese without
#: one. Its only consequence is a word in the digest, so a false negative costs a nudge and
#: a false positive costs nothing at all.
_QUESTION_RE = re.compile(r"[?？]|谁|哪|什么|怎么|为什么|是不是|有没有|吗\b|吗$|呢$", re.M)


def question_shaped(text: str) -> bool:
    """Whether a stretch of transcript contains a question. See `_QUESTION_RE`."""
    return bool(_QUESTION_RE.search(text))


class SubjectLedger:
    """Per-conversation memory of what has been looked up and what has been said about it.

    Pure: no clock, no I/O, no model. It counts two things — how often retrieval TOUCHED a
    subject (which is a proxy for how often the room named it, and unlike an NLP pass it can
    only ever be right about something that actually happened), and what has been DELIVERED
    about it. Everything else in the repetition mechanism is a function of those two.

    Subjects are normalised by whatever identity the retrieval already carries: a canonical
    document path for a person or a project (so an alias and a full name are one subject,
    because the contact book already resolved them to one page), a source id for a raw
    excerpt, a path call key for a lookup that spans documents."""

    def __init__(self, limit: int = 64) -> None:
        self._by_key: dict[str, SubjectRecord] = {}
        self._limit = max(1, limit)

    # ------------------------------------------------------------------ recording

    def touch(self, key: str, label: str = "", *, asked: bool = False) -> None:
        """Retrieval looked this subject up on this tick."""
        if not key:
            return
        record = self._by_key.get(key)
        if record is None:
            record = SubjectRecord(key=key, label=label or key)
            self._by_key[key] = record
        elif label and record.label == record.key:
            record.label = label
        record.mentions += 1
        if asked:
            record.asked = True
        self._evict()

    def deliver(self, key: str, kind: str, label: str = "") -> None:
        """A card of `kind` about this subject reached the reader."""
        if not key:
            return
        self.touch(key, label)
        self._by_key[key].delivered.add(kind)

    def _evict(self) -> None:
        while len(self._by_key) > self._limit:
            # Least-mentioned first: a subject the room keeps naming is the one the digest
            # exists for, so it is the last thing to fall out.
            victim = min(self._by_key.values(), key=lambda r: (r.mentions, r.key))
            self._by_key.pop(victim.key, None)

    # --------------------------------------------------------------------- reading

    def held_as_duplicate(self, key: str, kind: str) -> bool:
        """Has a card of this kind about this subject already been delivered?

        The mechanical backstop under the whole repetition design: a second `concept`
        introduction of the same subject is refused however convincing the two model calls
        were, and a `fact` about it is a different card and passes."""
        record = self._by_key.get(key)
        return record is not None and kind in record.delivered

    def records(self) -> list[SubjectRecord]:
        """Every subject, most-mentioned first, ties broken by key (deterministic)."""
        return sorted(self._by_key.values(), key=lambda r: (-r.mentions, r.key))

    def digest(self, limit: int = 8) -> str:
        """The ledger as the discover stage reads it: one line per recurring subject.

        Only subjects mentioned more than once appear — a subject seen once carries no
        repetition signal, and a digest listing everything is a digest nobody reads."""
        lines = [
            prompt(
                "recall.live.digest.line",
                label=record.label,
                mentions=record.mentions,
                state=prompt(
                    "recall.live.digest.introduced"
                    if record.delivered
                    else "recall.live.digest.new"
                ),
                asked=prompt(
                    "recall.live.digest.asked"
                    if record.asked
                    else "recall.live.digest.unasked"
                ),
            )
            for record in self.records()[:limit]
            if record.mentions > 1
        ]
        return "\n".join(lines)


# --------------------------------------------------------------------- stage 1: discover


@dataclass(frozen=True)
class DiscoverOutcome:
    """What the discover stage decided, plus what it cost."""

    result: DiscoverResult | None
    token_usage: dict[str, int] = field(default_factory=zero_usage)


def discover_human(
    transcript: str,
    *,
    as_of: datetime,
    delivered: Sequence = (),
    digest: str = "",
    overflowed: int = 0,
    context: str = "",
    context_turns: int = 0,
) -> str:
    """The discover Human turn: mined → ledger → as_of → earlier conversation → the pending
    transcript (LAST).

    Same tail discipline as every other lane here: the live thing sits in the attention-hot
    tail, below whatever it has to be read against — and `context` is precisely "whatever it
    has to be read against", so it sits immediately above the new content and nowhere else.
    Two headers, never one block: the contract tells the stage to understand the first and
    evaluate the second, and a rule about two parts needs the two parts to be visible."""
    sections: list[str] = []
    mined = [line for line in (_mined_line(item) for item in delivered) if line]
    if mined:
        sections.append(
            prompt("recall.live.section.mined_header", count=len(mined))
            + "\n"
            + "\n".join(mined)
        )
    if digest:
        sections.append(prompt("recall.live.section.digest_header") + "\n" + digest)
    header = prompt(
        "recall.live.section.pending_header", turns=transcript.count("\n") + 1
    )
    if overflowed:
        header += prompt("recall.live.section.pending_overflow", count=overflowed)
    earlier = (
        prompt("recall.live.section.context_header", turns=context_turns)
        + "\n"
        + context
        + "\n\n"
        if context
        else ""
    )
    return (
        ("\n\n".join(sections) + "\n\n" if sections else "")
        + f"as_of: {as_of.isoformat()}\n"
        + earlier
        + f"{header}\n"
        + transcript
    )


_CITE_RESIDUE_RE = re.compile(r"\[cite:[^\]]*\]?")
_MINED_BODY_CHARS = 160


def _mined_line(item) -> str | None:
    """`- [kind] title — body head` for one delivered card, or None without a title.

    The BODY is carried now, not only the title: "已挖掘过的内容" is what the discover stage
    weighs `already_mined` against, and a bare title cannot tell it whether the thing the
    room is circling round has already been said. Any `[cite:` residue is stripped
    mechanically — a handle from an older evaluation names a different source in this one."""
    if isinstance(item, Mapping):
        kind = str(item.get("kind") or "").strip()
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
    else:
        kind = str(getattr(item, "kind", "") or "").strip()
        title = str(getattr(item, "title", "") or "").strip()
        body = str(getattr(item, "body", "") or "").strip()
    title = _CITE_RESIDUE_RE.sub("", title).strip()
    if not title:
        return None
    body = " ".join(_CITE_RESIDUE_RE.sub("", body).split())[:_MINED_BODY_CHARS]
    head = f"- [{kind}] {title}" if kind else f"- {title}"
    return f"{head} — {body}" if body else head


def discover_messages(
    transcript: str,
    *,
    as_of: datetime,
    focus: ContextFocus = "general",
    paths: Sequence[FastPath] = (),
    delivered: Sequence = (),
    digest: str = "",
    overflowed: int = 0,
    context: str = "",
    context_turns: int = 0,
    web: bool = False,
    density: ContextDensity = DEFAULT_DENSITY,
) -> list[BaseMessage]:
    return [
        SystemMessage(content=discover_contract(focus, paths, web=web, density=density)),
        HumanMessage(
            content=discover_human(
                transcript,
                as_of=as_of,
                delivered=delivered,
                digest=digest,
                overflowed=overflowed,
                context=context,
                context_turns=context_turns,
            )
        ),
    ]


async def run_discover(
    model: BaseChatModel,
    messages: Sequence[BaseMessage],
    *,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> DiscoverOutcome:
    """One structured call. A parse failure is a SKIP, never an exception: this whole lane
    degrades to silence, which is also its steady state."""
    structured = model.with_structured_output(DiscoverResult, include_raw=True)
    raw = await structured.ainvoke(
        list(messages),
        config=invoke_config("recall.live.discover", callbacks, trace_metadata),
    )
    if isinstance(raw, Mapping):
        parsed, message = raw.get("parsed"), raw.get("raw")
    else:
        parsed, message = raw, None
    if not isinstance(parsed, DiscoverResult):
        parsed = None
    return DiscoverOutcome(
        result=parsed,
        token_usage=extract_usage(message) if message is not None else zero_usage(),
    )


def plan_runs(
    entries: Sequence[PlanEntry],
    paths: Sequence[FastPath],
    *,
    web: bool = False,
) -> tuple[list[tuple[FastPath, BaseModel]], list[str], list[str], list[str]]:
    """A plan → `(component runs, semantic queries, web queries, rejected kinds)`.

    Validation is MECHANICAL and total: a kind naming no enabled path is rejected, and
    arguments that fail the path's own `args_schema` are rejected the same way
    `route_paths` rejects a bad tool call. Nothing is guessed at and nothing half-runs.

    `web` is the same validation applied to the supplementary kind: when it was not offered
    it is not a kind, so a plan naming it is REJECTED and counted rather than quietly run.
    A model that invents an un-offered lookup and a model that mistypes a component name are
    the same event here, and they are treated the same way."""
    by_name = {p.name: p for p in paths}
    runs: list[tuple[FastPath, BaseModel]] = []
    queries: list[str] = []
    web_queries: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        kind = (entry.kind or "").strip()
        if kind == SEMANTIC:
            query = (entry.query or "").strip()
            if query and query not in queries:
                queries.append(query)
            continue
        if kind == WEB:
            if not web:
                rejected.append(kind)
                continue
            query = (entry.query or "").strip()
            if query and query not in web_queries:
                web_queries.append(query)
            continue
        path = by_name.get(kind)
        if path is None:
            rejected.append(kind or "(empty)")
            continue
        raw = {arg.name: arg.value for arg in entry.args if arg.name}
        try:
            args = path.args_schema.model_validate(raw)
        except ValidationError:
            rejected.append(kind)
            continue
        key = f"{kind}:{sorted(raw.items())}"
        if key in seen:
            continue
        seen.add(key)
        runs.append((path, args))
    return runs, queries, web_queries, rejected


# ------------------------------------------------------------------- stage 2: candidates


@dataclass(frozen=True)
class SuggestionCandidate:
    """One card the pick stage may choose, rendered MECHANICALLY.

    `body` is the evidence — claim text and excerpts, verbatim, in the order retrieval put
    them. No model wrote a word of it, and the delivered card carries it unchanged. What a
    model adds later is the lede above it and which of `citations` survive."""

    index: int  # 1-based, exactly as the pick stage is shown it
    kind: SuggestionKind
    title: str
    body: str
    citations: tuple[Citation, ...]
    subject: str
    subject_label: str
    origin: str  # "path:<name>" | "semantic.claims" | "semantic.windows" | "web"
    #: `library` or `web` — the pool, stated on the card the pick stage reads. See
    #: `PROVENANCE_LIBRARY`.
    provenance: str = PROVENANCE_LIBRARY
    #: A `web` candidate's provenance: the pages the search named. Empty on every library
    #: candidate, and the ONLY provenance a web candidate has — the two shapes never mix on
    #: one card, because a card is either the owner's material or it is not.
    web_citations: tuple[WebCitation, ...] = ()


def _clip(text: str, limit: int) -> str:
    """Cut to `limit`, on a sentence boundary when one is near the end, else on a word."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for stop in ("。", "！", "？", ". ", "! ", "? ", "\n"):
        cut = head.rfind(stop)
        if cut >= limit // 2:
            return head[: cut + len(stop)].strip()
    cut = head.rfind(" ")
    return (head[:cut] if cut >= limit // 2 else head).strip() + "…"


def _is_overview(claim: RetrievedClaim) -> bool:
    """Does this claim sit in a document's overview head (definition / summary / …)?

    That is the mechanical difference between an INTRODUCTION and a fact: the overview is
    the bounded head that says what a subject IS, the ledger below it says what happened.
    A card whose lede comes from the head is a `concept` card, and the ledger refuses a
    second one about the same subject."""
    return claim.section_path[:1] == (OVERVIEW_LABEL,)


def _document_label(path: str) -> str:
    """`people/li-wei.md` → `li-wei`. The document's own name, nothing invented."""
    tail = path.rsplit("/", 1)[-1]
    return tail[:-3] if tail.endswith(".md") else tail


def _claim_lines(claims: Sequence[RetrievedClaim]) -> str:
    return "\n".join(
        f"- {claim_display_text(claim.text)}"
        + (f" [{', '.join(claim.labels)}]" if claim.labels else "")
        for claim in claims
    )


def _citations_of(claims: Sequence[RetrievedClaim]) -> tuple[Citation, ...]:
    out: list[Citation] = []
    seen: set[tuple[str, int, int]] = set()
    for claim in claims:
        for cit in claim.citations:
            key = (str(cit.source_id), cit.block_start, cit.block_end)
            if key in seen:
                continue
            seen.add(key)
            out.append(cit)
    return tuple(out)


def _subject_of(claims: Sequence[RetrievedClaim]) -> tuple[str, str]:
    """`(key, label)` for a run of claims: their shared document when they have one.

    A person page and a project page are each ONE document, which is why the document path
    is the normalised subject identity — an alias, a full name and an account handle all
    resolve to the same page upstream, so they arrive here already normalised."""
    docs = {claim.document_path for claim in claims if claim.document_path}
    if len(docs) == 1:
        path = docs.pop()
        return path, _document_label(path)
    return "", ""


def candidate_from_component(
    evidence: ComponentEvidence, index: int
) -> SuggestionCandidate | None:
    """One routed path's result as a card. None when the path found nothing to show."""
    claims = list(evidence.claims[:CLAIMS_PER_CANDIDATE])
    windows = list(evidence.windows[:1])
    if not claims and not windows:
        return None
    args_label = " · ".join(str(v) for v in evidence.args.values() if str(v).strip())
    title = args_label or evidence.path
    body = _clip(
        "\n".join(part for part in (_claim_lines(claims), _window_lines(windows)) if part),
        CANDIDATE_BODY_CHARS,
    )
    subject, label = _subject_of(claims)
    if not subject:
        subject, label = evidence.key(), title
    return SuggestionCandidate(
        index=index,
        kind="concept" if claims and _is_overview(claims[0]) else "fact",
        title=title,
        body=body,
        citations=_citations_of(claims) + _window_citations(windows),
        subject=subject,
        subject_label=label or title,
        origin=f"path:{evidence.path}",
    )


def candidate_from_web(
    answer: WebSearchAnswer, query: str, index: int
) -> SuggestionCandidate | None:
    """One web search as a card, or None when it cannot honestly be one.

    THE GATE IS HERE, at construction, and it is the web face's whole equivalent of the
    library's citation gate: an answer that named no page is not a card. It cannot be
    checked downstream the way a library citation can — there is no source block to resolve
    and nothing to compare a claim against — so the only mechanical thing available is "it
    carried at least one URL", and that is applied where a card is built rather than where
    one is delivered. A search that came back as bare prose is dropped in silence, which is
    the same thing this lane does with every other kind of nothing.

    The body is the provider's answer VERBATIM, under the same character bound every other
    candidate lives under. Nothing is written on top of it here, and the pick stage may not
    rewrite it either."""
    text = " ".join(str(answer.text or "").split())
    citations = tuple(c for c in answer.citations if str(c.url or "").strip())
    if not text or not citations:
        return None
    subject = " ".join(str(query or "").split()).strip().lower()
    return SuggestionCandidate(
        index=index,
        kind="web",
        title=query.strip() or text[:40],
        body=_clip(text, CANDIDATE_BODY_CHARS),
        citations=(),
        subject=f"{WEB}:{subject}" if subject else "",
        subject_label=query.strip(),
        origin=WEB,
        provenance=PROVENANCE_WEB,
        web_citations=citations,
    )


def _window_lines(windows: Sequence) -> str:
    return "\n".join(
        prompt(
            "recall.live.candidate.excerpt",
            title=str(getattr(w, "source_title", "") or getattr(w, "source_id", "")),
            text=_clip(" ".join(str(getattr(w, "text", "")).split()), 320),
        )
        for w in windows
    )


def _window_citations(windows: Sequence) -> tuple[Citation, ...]:
    return tuple(
        Citation(
            source_id=w.source_id, block_start=w.block_start, block_end=w.block_end
        )
        for w in windows
    )


def candidates_from_claims(
    claims: Sequence[RetrievedClaim], start: int
) -> list[SuggestionCandidate]:
    """Semantic claim hits, grouped into one card per document in retrieval order."""
    grouped: dict[str, list[RetrievedClaim]] = {}
    for claim in claims:
        grouped.setdefault(claim.document_path, []).append(claim)
    out: list[SuggestionCandidate] = []
    for path, rows in grouped.items():
        top = rows[:CLAIMS_PER_CANDIDATE]
        out.append(
            SuggestionCandidate(
                index=start + len(out),
                kind="concept" if _is_overview(top[0]) else "fact",
                title=_document_label(path),
                body=_clip(_claim_lines(top), CANDIDATE_BODY_CHARS),
                citations=_citations_of(top),
                subject=path,
                subject_label=_document_label(path),
                origin="semantic.claims",
            )
        )
    return out


def candidates_from_windows(windows: Sequence, start: int) -> list[SuggestionCandidate]:
    """Raw excerpts, one card per source. Always `fact`: an uncompiled excerpt is something
    that was said, never the library's account of what a subject IS."""
    by_source: dict[str, list] = {}
    for window in windows:
        by_source.setdefault(str(window.source_id), []).append(window)
    out: list[SuggestionCandidate] = []
    for source_id, rows in by_source.items():
        title = str(getattr(rows[0], "source_title", "") or source_id)
        out.append(
            SuggestionCandidate(
                index=start + len(out),
                kind="fact",
                title=title,
                body=_clip(_window_lines(rows[:2]), CANDIDATE_BODY_CHARS),
                citations=_window_citations(rows[:2]),
                subject=f"source:{source_id}",
                subject_label=title,
                origin="semantic.windows",
            )
        )
    return out


def build_candidates(
    component: Sequence[ComponentEvidence] = (),
    claims: Sequence[RetrievedClaim] = (),
    windows: Sequence = (),
    web: Sequence[tuple[WebSearchAnswer, str]] = (),
    *,
    limit: int = MAX_CANDIDATES,
) -> list[SuggestionCandidate]:
    """Everything retrieval returned, as numbered cards. Sync — it awaits nothing.

    Component paths come first: they answered a STRUCTURED question the discover stage
    asked deliberately, while the semantic face answered a similarity query. The web face
    comes LAST, and that ordering is the supplement stated as a position: the library is
    read first and the internet is what is offered after it, so when the pick stage is
    weighing an even choice the owner's own material is the one it read first. It is still
    candidate N like any other — nothing here privileges or penalises it in the choice.
    Re-numbered at the end so the indexes the pick stage sees are 1..n with no gaps.

    **A web candidate is never the one truncation drops.** The limit is a bound on what a
    weak model can choose from reliably, and applying it in list order would silently delete
    the supplement exactly when the library was talkative — which is exactly when the room
    asked about something outside it. Measured on the real library: six adjacent project
    pages filled the pool, and the search that had already been run and PAID FOR never
    reached the picker at all. A candidate that was bought and never offered is not a
    ranking decision, it is money spent on nothing, so the web rows are reserved their slots
    and the library rows take what is left. Order is unchanged — the library is still read
    first — because the reserve is about survival, not about rank."""
    reserved: list[SuggestionCandidate] = []
    for answer, query in web:
        card = candidate_from_web(answer, query, 0)
        if card is not None:
            reserved.append(card)
    reserved = reserved[:limit]

    rows: list[SuggestionCandidate] = []
    for evidence in component:
        card = candidate_from_component(evidence, len(rows) + 1)
        if card is not None:
            rows.append(card)
    rows.extend(candidates_from_claims(claims, len(rows) + 1))
    rows.extend(candidates_from_windows(windows, len(rows) + 1))

    seen: set[tuple[str, str]] = {(row.subject, row.kind) for row in reserved}
    unique: list[SuggestionCandidate] = []
    for row in rows:
        key = (row.subject, row.kind)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    ordered = [*unique[: max(limit - len(reserved), 0)], *reserved]
    return [
        SuggestionCandidate(**{**row.__dict__, "index": n})
        for n, row in enumerate(ordered, start=1)
    ]


def render_candidates(candidates: Sequence[SuggestionCandidate]) -> str:
    """The numbered list the pick stage chooses from, citations numbered within each card."""
    blocks: list[str] = []
    for card in candidates:
        cites = "\n".join(
            prompt(
                "recall.live.candidate.citation",
                n=n,
                source_id=str(c.source_id),
                block_start=c.block_start,
                block_end=c.block_end,
            )
            for n, c in enumerate(card.citations, start=1)
        ) or "\n".join(
            # A web card's provenance is a page, so it is numbered the same way and pruned
            # by the same indexes — what changes is what an index points AT, and the pick
            # stage is shown that rather than left to infer it from a card with no citations.
            prompt("recall.live.candidate.web_citation", n=n, title=c.title, url=c.url)
            for n, c in enumerate(card.web_citations, start=1)
        )
        blocks.append(
            prompt(
                "recall.live.candidate.block",
                index=card.index,
                kind=card.kind,
                title=card.title,
                # Stated, never inferred. The contract's rule — where a candidate came from
                # is not a ranking, the match is — needs the two pools to be legible on the
                # card, and a model left to guess from a title would guess.
                provenance=prompt(
                    "recall.live.candidate.provenance_web"
                    if card.provenance == PROVENANCE_WEB
                    else "recall.live.candidate.provenance_library"
                ),
                # The subject line is what tells a person page apart from a project page of
                # the same name. A component path is looked up by ALIAS, and an alias can
                # name a person page while a project page shares the word — measured on a
                # real library, where a candidate list showing only titles left the pick
                # stage guessing which of the two it was choosing.
                subject=card.subject or card.subject_label or card.title,
                body=card.body,
                citations=cites or prompt("recall.live.candidate.no_citations"),
            )
        )
    return "\n\n".join(blocks)


# ------------------------------------------------------------------------ stage 3: pick


def pick_human(
    transcript: str, candidates: Sequence[SuggestionCandidate], *, intent: str = ""
) -> str:
    """Candidates first, the live conversation LAST — the tail discipline again."""
    sections = [
        prompt("recall.live.section.candidates_header", count=len(candidates))
        + "\n"
        + render_candidates(candidates)
    ]
    if intent:
        sections.append(prompt("recall.live.section.intent", intent=intent))
    sections.append(
        prompt("recall.live.section.conversation_header", turns=transcript.count("\n") + 1)
        + "\n"
        + transcript
    )
    return "\n\n".join(sections)


def pick_messages(
    transcript: str, candidates: Sequence[SuggestionCandidate], *, intent: str = ""
) -> list[BaseMessage]:
    return [
        SystemMessage(content=pick_contract()),
        HumanMessage(content=pick_human(transcript, candidates, intent=intent)),
    ]


@dataclass(frozen=True)
class PickOutcome:
    result: PickResult | None
    token_usage: dict[str, int] = field(default_factory=zero_usage)


async def run_pick(
    model: BaseChatModel,
    messages: Sequence[BaseMessage],
    *,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> PickOutcome:
    structured = model.with_structured_output(PickResult, include_raw=True)
    raw = await structured.ainvoke(
        list(messages),
        config=invoke_config("recall.live.pick", callbacks, trace_metadata),
    )
    if isinstance(raw, Mapping):
        parsed, message = raw.get("parsed"), raw.get("raw")
    else:
        parsed, message = raw, None
    if not isinstance(parsed, PickResult):
        parsed = None
    return PickOutcome(
        result=parsed,
        token_usage=extract_usage(message) if message is not None else zero_usage(),
    )


def pick_citations(
    card: SuggestionCandidate, chosen: Sequence[int]
) -> list[Citation]:
    """The pruned citation list: 1-based indexes INTO the candidate's own list.

    Copy-by-reference, never authored — an index is either in range or it is not, and an
    empty or wholly invalid pick falls back to the candidate's full list rather than
    failing the tick. A card that lost its provenance to a typo would be worse than a card
    that shows one span too many."""
    picked = [card.citations[i - 1] for i in chosen if 1 <= i <= len(card.citations)]
    return picked or list(card.citations)


def _web_citations(
    card: SuggestionCandidate, chosen: Sequence[int]
) -> tuple[WebCitation, ...]:
    """A web card's pruned page list — the same copy-by-reference rule as `pick_citations`.

    One function per shape rather than one that guesses, because the two lists are numbered
    independently and a card only ever has one of them."""
    if not card.web_citations:
        return ()
    picked = tuple(
        card.web_citations[i - 1] for i in chosen if 1 <= i <= len(card.web_citations)
    )
    return picked or card.web_citations


# ────────────────────────────────────────────────── the glance short-circuit
#
# The first response used to cost the whole pipeline: discover, then retrieval, then a
# second model call. But by the end of DISCOVER the lane already knows what the room is
# looking for — and where a plan names a subject the library holds, the library already
# holds one grounded sentence about it: the overview `definition`, written by a compile,
# rewritten whenever the picture changes, and resting on ledger anchors (`c:xxxx`) it cites.
#
# So that sentence goes out immediately, verbatim, while stages 2 and 3 keep running. It
# costs NO extra model call — it is a resolution and a parse — and it is not a guess: it is
# the same sentence the full card would have opened with, arriving a retrieval earlier and
# marked provisional so the reader knows the tick has not finished.

#: The plan named a subject whose page carries a definition; a provisional card went out.
GLANCE_HIT = "hit"
#: No subject in the plan resolved to a page with a definition. Nothing was delivered early.
GLANCE_MISS = "miss"
#: …and how it ended: the full card was about the SAME subject, so the provisional card
#: became it in place (the queue does not grow);
GLANCE_UPGRADED = "upgraded"
#: …the full card was about something else, so the glance settled and the new card queued;
GLANCE_SETTLED = "settled"
#: …or nothing else came, so the glance simply stopped being provisional.
GLANCE_ALONE = "alone"


@dataclass(frozen=True)
class GlanceCard:
    """A provisional card and the subject it is about, handed to the caller the moment the
    plan is parsed. `outcome` is filled in on the settled result, never here."""

    suggestion: ResolvedSuggestion
    subject: str


#: A plan value's own words are tried after the whole value. Bounded so a long semantic
#: query cannot turn one dictionary lookup into a hundred.
PLAN_WORDS_MAX = 12
#: …and a word shorter than this is not a name anyone filed a document under.
PLAN_WORD_MIN_CHARS = 2

_PLAN_WORD_RE = re.compile(r"[0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


def plan_subjects(plan: Sequence[PlanEntry]) -> list[str]:
    """Every free-text subject a plan names, whole values first, then their own words.

    A plan entry is a `kind` plus arguments whose NAMES belong to whichever component
    registered the path, so core cannot ask for `subject` or `alias` by name and must not
    try: it takes every non-empty argument value, plus a `semantic` entry's query. Each is
    then offered to an EXACT resolution that answers for almost none of them — which is the
    point. A value that names no document costs one dictionary lookup.

    THE WORDS ARE TRIED TOO, and they have to be. A routed path's argument is often the
    subject exactly (`people_around(Lumenlab)`), but a `semantic` entry's query is a
    sentence — 「lumenlab 是什么？我一直没搞清楚。」 — and a sentence is never equal to a
    document's title, so the one plan shape that most obviously wants an instant definition
    was the one shape that could never get one. Splitting it does not make this a search:
    every word still has to match a document's title, slug or filename EXACTLY under the one
    normalisation, ties still resolve to nothing, and whole values are tried first so a
    document named by the plan outright always wins over a word inside it.
    """
    out: dict[str, None] = {}
    words: dict[str, None] = {}

    def offer(text: str) -> None:
        text = text.strip()
        if not text:
            return
        out.setdefault(text, None)
        for word in _PLAN_WORD_RE.findall(text):
            if len(word) >= PLAN_WORD_MIN_CHARS:
                words.setdefault(word, None)

    for entry in plan:
        for arg in entry.args:
            offer(str(arg.value or ""))
        offer(str(entry.query or ""))
    for word in list(words)[:PLAN_WORDS_MAX]:
        out.setdefault(word, None)
    return list(out)


def build_glance(
    plan: Sequence[PlanEntry],
    documents: Sequence["CanonicalDocument"],
    *,
    trigger: str = "",
    ledger: SubjectLedger | None = None,
    already_shown: Sequence = (),
) -> GlanceCard | None:
    """The provisional card, or None when nothing in the plan names a defined subject.

    Mechanical throughout: resolve, read the definition, take the citations off the claims
    its anchor references carry. Nothing is authored and no model is called, so the card is
    exactly the library's own sentence — which is why it can be shown before anything has
    been verified. It goes through the SAME repetition rules as any other card: a subject
    this session has already introduced gets no second glance.

    A tie resolves to nothing. Two documents equally named is precisely when a one-sentence
    definition delivered instantly would be confidently wrong, and the full pipeline behind
    it is better equipped to choose than a mechanism with no question in hand.
    """
    if not documents:
        return None
    by_path = {doc.path: doc for doc in documents}
    shown = {
        (
            str(i.get("kind") if isinstance(i, Mapping) else getattr(i, "kind", "")).strip(),
            _CITE_RESIDUE_RE.sub(
                "",
                str(i.get("title") if isinstance(i, Mapping) else getattr(i, "title", "")),
            ).strip(),
        )
        for i in already_shown
    }
    for subject in plan_subjects(plan):
        matches = resolve_subject(documents, subject)
        if len(matches) != 1:
            continue
        doc, _how = matches[0]
        definition = document_definition(doc)
        if not definition:
            continue
        title = document_title(doc)
        if ledger is not None and ledger.held_as_duplicate(doc.path, "glance"):
            continue
        if ("glance", title.strip()) in shown:
            continue
        citations = _definition_citations(doc, by_path)
        if not citations:
            # The same mechanical belt every card passes. A definition rests on ledger
            # anchors by gate rule, so this only fires on a page written before that rule —
            # and an uncited sentence is exactly what this feature must not deliver fast.
            continue
        return GlanceCard(
            suggestion=ResolvedSuggestion(
                kind="glance",
                title=title,
                body=definition,
                trigger=trigger,
                confidence=10,
                citations=list(citations),
                evidence=definition,
                subject=doc.path,
                subject_label=_document_label(doc.path),
                provisional=True,
            ),
            subject=doc.path,
        )
    return None


def _definition_citations(doc, by_path: Mapping[str, object]) -> tuple[Citation, ...]:
    """The citations a definition rests on, read off the claims its `c:xxxx` references name.

    The definition is the head of the overview, and the overview's rule is that every block
    rests on a ledger claim or a source span. So its provenance is not a second thing to
    store: it is whatever the claims it points at cite, and following the reference is how
    the glance card gets real citations for free.
    """
    wanted = {m.group(1) for m in ANCHOR_REFERENCE_RE.finditer(overview_region(doc.body))}
    if not wanted:
        return ()
    out: list[Citation] = []
    seen: set[tuple[str, int, int]] = set()
    for claim in project_document_claims(doc):
        if str(claim.anchor) not in wanted:
            continue
        for cit in claim.citations:
            key = (str(cit.source_id), cit.block_start, cit.block_end)
            if key in seen:
                continue
            seen.add(key)
            out.append(cit)
    return tuple(out)


def deliver(
    pick: PickResult | None,
    candidates: Sequence[SuggestionCandidate],
    *,
    trigger: str = "",
    min_confidence: int = 6,
    ledger: SubjectLedger | None = None,
    already_shown: Sequence = (),
) -> tuple[ResolvedSuggestion | None, str]:
    """The pick, gated. Returns `(card or None, reason)` — the reason is why nothing went.

    The gates are the same mechanical shape the lane always had, minus the one the new
    pipeline made impossible: nothing here can be *unparsed into prose*, because the
    evidence is not authored. What is left is a choice of `none` (`no_coverage`), a
    confidence floor, the session's exact-title dedup, the (subject × kind) backstop — and
    the uncited belt, which is a refusal rather than an assumption: citations ARE attached
    by construction, and this is what makes that sentence checkable instead of trusted."""
    if pick is None:
        return None, SKIP_PICK_FAILED
    choice = int(pick.choice or 0)
    if choice == 0:
        # The contract's own first-class answer: it read every candidate against the intent
        # and none of them covers it. NOT `low_confidence` — that is a weak answer, this is
        # no answer, and a reader asking "why did nothing fire" needs the two kept apart.
        return None, SKIP_NO_COVERAGE
    by_index = {card.index: card for card in candidates}
    card = by_index.get(choice)
    if card is None:
        return None, SKIP_NONE_CHOSEN
    confidence = max(1, min(10, int(pick.confidence or 0)))
    if confidence < min_confidence:
        return None, SKIP_LOW_CONFIDENCE
    if ledger is not None and ledger.held_as_duplicate(card.subject, card.kind):
        return None, SKIP_DUPLICATE
    shown = {
        (
            str(i.get("kind") if isinstance(i, Mapping) else getattr(i, "kind", "")).strip(),
            _CITE_RESIDUE_RE.sub(
                "",
                str(i.get("title") if isinstance(i, Mapping) else getattr(i, "title", "")),
            ).strip(),
        )
        for i in already_shown
    }
    if (card.kind, card.title.strip()) in shown:
        return None, SKIP_DUPLICATE
    citations = pick_citations(card, pick.citations)
    # The mechanical belt. Nothing here can normally be uncited — a library candidate's
    # citations come from retrieval and a web candidate without a URL is never built — so
    # this is the write-time refusal that keeps "normally" out of it.
    if not citations and not card.web_citations:
        return None, SKIP_UNCITED
    lede = _clip(" ".join(str(pick.lede or "").split()), LEDE_CHARS)
    return (
        ResolvedSuggestion(
            kind=card.kind,
            title=card.title,
            body=lede or card.body,
            trigger=trigger,
            confidence=confidence,
            citations=citations,
            web_citations=list(_web_citations(card, pick.citations)),
            evidence=card.body,
            subject=card.subject,
            subject_label=card.subject_label,
        ),
        "",
    )


# ---------------------------------------------------------------------- the pipeline


@dataclass(frozen=True)
class PipelineResult:
    """One tick, whole: what it delivered or why it did not, and what each stage cost."""

    suggestions: tuple[ResolvedSuggestion, ...] = ()
    token_usage: dict[str, int] = field(default_factory=zero_usage)
    #: "" when a card was delivered; otherwise the skip reason, which is the only thing a
    #: silent tick has to say for itself.
    skipped: str = ""
    intent: str = ""
    worth: int = 0
    plan: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    candidates: tuple[SuggestionCandidate, ...] = ()
    chosen: int = 0
    #: The briefing round's four-gate accounting, empty on the full-scope lane. The pipeline
    #: cannot produce an uncited or unparsed CARD — citations are attached by construction
    #: and no card text is authored — so its equivalent accounting is `skipped`.
    dropped: dict[str, int] = field(default_factory=dict)
    stages: tuple[StageTiming, ...] = ()
    #: Subjects retrieval touched this tick, `(key, label)` — the ledger's input, carried
    #: out so the caller (which owns the session) records them.
    touched: tuple[tuple[str, str], ...] = ()
    asked: bool = False
    #: What the supplementary web face cost this tick: searches actually run and the USD the
    #: provider reported. Both zero when the face did not run, which is the steady state.
    #: Reported rather than gated on — see `ports/web_search.py`.
    web_searches: int = 0
    web_cost: float = 0.0
    #: How many PAGES those searches came back naming. Reported beside the cost because the
    #: two together are the only way to see the one outcome that is otherwise invisible: a
    #: search that ran, was charged for, and named nothing — so its answer was refused at
    #: construction and no candidate ever appeared. Without this the tick shows a cost and
    #: an absent card, and leaves the reader to guess which gate ate it.
    web_pages: int = 0
    #: How the web face was reached: `off` | `planned` | `fallback`. See `WEB_OFF`.
    web_tier: str = WEB_OFF
    #: The provisional card this tick delivered early, if any — the same object the caller
    #: already received through `on_glance`, carried here so a caller that has no callback
    #: (the one-shot transport, a test) still sees it.
    glance: ResolvedSuggestion | None = None
    #: `hit` | `miss` — whether the plan named a subject the library could glance at — and,
    #: when it hit, how it ended: `upgraded` (the full card was the same subject and took
    #: the provisional card's place), `settled` (a different card came and this one merely
    #: stopped being provisional), `alone` (nothing else came).
    glance_state: str = GLANCE_MISS
    glance_outcome: str = ""
    #: Milliseconds from the tick's start to the provisional card leaving. Reported on its
    #: own because the whole claim of this mechanism is WHEN it lands — a card counted in
    #: `total` says nothing about whether it arrived a retrieval early.
    glance_ms: float = 0.0
    #: The mining posture this tick's discover contract was assembled under. Reported so
    #: "why did nothing fire" can be answered with the posture in hand: the same turn is a
    #: skip under `quiet` and a lookup under `eager`, and a record that showed only the skip
    #: would make the difference look like model noise.
    density: ContextDensity = DEFAULT_DENSITY


def _merge_usage(*usages: Mapping[str, int]) -> dict[str, int]:
    out = zero_usage()
    for usage in usages:
        for key, value in usage.items():
            out[key] = out.get(key, 0) + int(value or 0)
    return out


def _interleave(groups: Sequence[Sequence], key) -> list:
    """Round-robin across the per-query returns, FIRST SURFACER OWNING each key.

    Two properties, and the second is the one that makes a multi-query plan worth planning.
    Uniqueness is the obvious half: the same claim reached by two queries is one claim, and
    which query found it first is not a fact about the claim. ORDER is the other half — the
    merged pool is truncated downstream (`MAX_CANDIDATES`), so laying query 1's whole return
    in front of query 2's would let one query of a four-entry plan fill every slot while the
    others reached the pick stage never. That is the fan-out bought and thrown away. Taking
    one row from each query in turn is what buys it back."""
    out: list = []
    seen: set = set()
    for row in chain.from_iterable(zip_longest(*groups)):
        if row is None:
            continue
        marker = key(row)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(row)
    return out


async def _semantic_face(
    user_id: UserId,
    queries: Sequence[str],
    *,
    claim_lexical: ClaimLexicalIndex | None,
    claim_vectors: ClaimVectorIndex | None,
    embeddings,
    lexical: LexicalIndex | None,
    vectors: VectorIndex | None,
    content: ContentStore | None,
) -> tuple[tuple[RetrievedClaim, ...], tuple]:
    """EVERY semantic query the plan asked for, concurrently — not one per turn, and no
    longer only the first of them.

    The discover stage says what the room is looking for, and where it is looking for
    several distinct things it now says so in several entries rather than crushing them into
    one string. Running them is nearly free: the per-query cost is ONE embedding, all of
    them are embedded in a single batched call, and the index round trips overlap. What
    comes back is merged into one pool — deduped and interleaved by `_interleave` — so the
    pick stage still chooses out of one numbered list and never learns which query surfaced
    which card. It MERGES rather than re-fusing (`retrieve_claims_multi`'s job) because each
    face already fuses internally, and because one vector per query is shared between the two
    faces — which is what keeps a fan-out at exactly one batched embedding call."""
    wanted: list[str] = []
    for raw_query in queries:
        text = str(raw_query or "").strip()
        if text and text not in wanted:
            wanted.append(text)
    do_claims = claim_lexical is not None and claim_vectors is not None
    do_windows = lexical is not None and vectors is not None
    if not wanted or (not do_claims and not do_windows):
        return (), ()
    embedded = await embeddings.aembed_documents(wanted)

    async def one(query: str, vector) -> tuple[Sequence[RetrievedClaim], Sequence]:
        claims_job = (
            retrieve_claims(
                user_id,
                query,
                claim_lexical=claim_lexical,
                claim_vectors=claim_vectors,
                embeddings=embeddings,
                limit=SEMANTIC_CLAIMS,
                query_embedding=vector,
            )
            if do_claims
            else _nothing()
        )
        windows_job = (
            rag_recall(
                user_id,
                query,
                lexical=lexical,
                vectors=vectors,
                embeddings=embeddings,
                limit=SEMANTIC_WINDOWS,
                query_embedding=vector,
            )
            if do_windows
            else _nothing()
        )
        return await asyncio.gather(claims_job, windows_job)

    returned = await asyncio.gather(
        *(one(query, vector) for query, vector in zip(wanted, embedded))
    )
    claims = _interleave(
        [got for got, _ in returned], key=lambda c: (c.document_path, str(c.anchor))
    )
    windows: Sequence = _interleave(
        [got for _, got in returned],
        key=lambda h: (str(h.source_id), h.block_start, h.block_end),
    )
    if windows:
        raw: list[RecallHit] = sorted(
            windows, key=lambda h: (-h.score, str(h.source_id), h.block_start)
        )
        merged = _suppress_overlapping(raw)
        windows = (
            order_lost_in_middle(
                await expand_and_merge(merged, content=content, user_id=user_id)
            )
            if content is not None
            else merged
        )
    return tuple(claims), tuple(windows)


async def _nothing() -> list:
    return []


async def evaluate_live_pipeline(
    user_id: UserId,
    turns: Sequence[ConversationTurn],
    *,
    as_of: datetime,
    discover_model: BaseChatModel,
    pick_model: BaseChatModel,
    embeddings=None,
    claim_lexical: ClaimLexicalIndex | None = None,
    claim_vectors: ClaimVectorIndex | None = None,
    lexical: LexicalIndex | None = None,
    vectors: VectorIndex | None = None,
    content: ContentStore | None = None,
    web_search: WebSearch | None = None,
    paths: Sequence[FastPath] = (),
    focus: ContextFocus = "general",
    already_shown: Sequence = (),
    ledger: SubjectLedger | None = None,
    label_map: dict[str, str] | None = None,
    max_pending_turns: int = DEFAULT_MAX_PENDING_TURNS,
    #: Turns this tick has ALREADY processed, newest last. Rendered read-only above the
    #: pending window so intent formation can see what the new content refers back to. The
    #: caller owns them because only the caller knows what "already processed" means for its
    #: transport: a WebSocket session keeps a ring buffer, and a one-shot POST has the head
    #: of its own submitted window (supplied automatically below).
    context_turns: Sequence[ConversationTurn] = (),
    max_context_turns: int = DEFAULT_CONTEXT_TURNS,
    #: How eagerly this connection digs. One clause of the discover contract, nothing else.
    density: ContextDensity = DEFAULT_DENSITY,
    #: Canonical, for the glance short-circuit — the definition of a subject the plan names
    #: goes out the moment the plan is parsed. With none passed there is no short-circuit
    #: and the lane behaves exactly as it did before the mechanism existed.
    documents: Sequence["CanonicalDocument"] = (),
    #: …or a way to FETCH them, awaited only once a real plan exists. That distinction is
    #: the whole reason this parameter is here beside the other: a skip is this lane's steady
    #: state, and a tick that read the whole library before deciding it was small talk would
    #: have made the cheap stage expensive to protect a card it was never going to deliver.
    load_documents: Callable[[], Awaitable[Sequence["CanonicalDocument"]]] | None = None,
    #: Called with the provisional card the instant it is built, so a transport can put it
    #: on the wire while stages 2 and 3 are still running — which is the entire point. It is
    #: awaited, and a callback that raises is logged and ignored: an early convenience must
    #: never be able to fail the tick behind it.
    on_glance: Callable[[ResolvedSuggestion], Awaitable[None]] | None = None,
    min_confidence: int = 6,
    # The web face's bound. A parameter so a test can reach it in milliseconds instead of
    # sleeping fifteen seconds — deliberately NOT a deployment setting: what it protects is
    # the property that a supplement never delays a card, and a deployment that could raise
    # it could turn the supplement back into a blocker.
    web_timeout: float = WEB_FACE_TIMEOUT_S,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> PipelineResult:
    """One tick of the full-scope lane. See the module docstring for the three stages.

    `ledger` is the caller's and is READ here, never written: what to record is handed back
    on the result (`touched`, and the delivered card's own subject), because the session
    that owns the ledger is also the thing that knows whether this tick's result was still
    the current one when it landed."""
    recorder = StageRecorder(STAGE_ORDER, RETRIEVE_CHILDREN)
    started = time.perf_counter()

    posture = coerce_density(density)
    #: Filled by the short-circuit below, then read by every return under it.
    glance: GlanceCard | None = None
    glance_ms = 0.0

    def finish(**fields) -> PipelineResult:
        recorder.record("total", (time.perf_counter() - started) * 1000.0)
        # Which of the three endings happened is decided MECHANICALLY, from what the tick
        # actually delivered — never asserted by a caller and never guessed.
        state, outcome = GLANCE_MISS, ""
        if glance is not None:
            state = GLANCE_HIT
            delivered = fields.get("suggestions") or ()
            if any(card.subject == glance.subject for card in delivered):
                outcome = GLANCE_UPGRADED
            elif delivered:
                outcome = GLANCE_SETTLED
            else:
                outcome = GLANCE_ALONE
        return PipelineResult(
            stages=recorder.emit(),
            density=posture,
            glance=glance.suggestion if glance is not None else None,
            glance_state=state,
            glance_outcome=outcome,
            glance_ms=glance_ms,
            **fields,
        )

    window = take_pending(turns, max_pending_turns=max_pending_turns)
    # The submitted window's own head is context too, and for the same reason: a one-shot
    # POST has no session to remember for it, but the turns it sent that did not fit the
    # pending bound were already there to be read. They ride above, and `overflowed` then
    # states only what reached NEITHER block — a count that says "did not fit" about turns
    # printed two lines higher would be false.
    head = tuple(turns)[: len(turns) - len(window.turns)]
    earlier = take_context(
        (*context_turns, *head), window.turns, max_context_turns=max_context_turns
    )
    shown = {id(t) for t in earlier}
    overflowed = max(window.overflowed - sum(1 for t in head if id(t) in shown), 0)
    # ONE labelling pass over both blocks: a participant number that meant one person above
    # the fold and another below it is worse than no number at all.
    labels = label_turns([*earlier, *window.turns], label_map)
    context = render_transcript(earlier, labels[: len(earlier)])
    transcript = render_transcript(window.turns, labels[len(earlier) :])
    asked = question_shaped(transcript)

    # The supplementary lookup is OFFERED only when something can actually serve it: the
    # caller passed a search (the deployment enabled it AND this connection allowed it) and
    # the search says it is configured. Resolved once, before the contract is assembled,
    # because it decides which of the two pinned SystemMessage variants this tick receives.
    web_offered = web_search is not None and web_search.available()

    # ── stage 1: discover. NOTHING below this line runs when it says skip.
    with recorder.measure("discover"):
        outcome = await run_discover(
            discover_model,
            discover_messages(
                transcript,
                as_of=as_of,
                focus=focus,
                paths=paths,
                delivered=already_shown,
                digest=ledger.digest() if ledger is not None else "",
                overflowed=overflowed,
                context=context,
                context_turns=len(earlier),
                web=web_offered,
                density=posture,
            ),
            callbacks=callbacks,
            trace_metadata=trace_metadata,
        )
    plan = outcome.result
    usage = dict(outcome.token_usage)
    if plan is None:
        return finish(token_usage=usage, skipped=SKIP_UNPARSED, asked=asked)
    if plan.skip:
        return finish(
            token_usage=usage,
            skipped=(plan.reason or "").strip() or SKIP_NO_PLAN,
            intent=plan.intent,
            worth=plan.worth,
            asked=asked,
        )
    if int(plan.worth or 0) < min_confidence:
        return finish(
            token_usage=usage,
            skipped=SKIP_LOW_WORTH,
            intent=plan.intent,
            worth=plan.worth,
            asked=asked,
        )
    runs, queries, web_queries, rejected = plan_runs(plan.plan, paths, web=web_offered)
    intent = (plan.intent or "").strip()
    if not runs and not queries and not web_queries:
        return finish(
            token_usage=usage,
            skipped=SKIP_NO_PLAN,
            intent=intent,
            worth=plan.worth,
            rejected=tuple(rejected),
            asked=asked,
        )
    plan_labels = tuple(
        [f"{p.name}({', '.join(str(v) for v in a.model_dump().values() if v)})" for p, a in runs]
        + [f"{SEMANTIC}({q})" for q in queries]
        + [f"{WEB}({q})" for q in web_queries]
    )

    # ── the glance short-circuit. Between stage 1 and stage 2, costing no model call: the
    # plan names a subject, the library holds one grounded sentence about it, and that
    # sentence goes out NOW while everything below keeps running.
    if not documents and load_documents is not None:
        try:
            documents = await load_documents()
        except Exception:  # noqa: BLE001 — an early convenience never fails the tick
            _log.warning("glance canonical read failed; continuing", exc_info=True)
            documents = ()
    glance = build_glance(
        plan.plan,
        documents,
        trigger=intent,
        ledger=ledger,
        already_shown=already_shown,
    )
    if glance is not None:
        glance_ms = (time.perf_counter() - started) * 1000.0
        recorder.record("glance", glance_ms)
        if on_glance is not None:
            try:
                await on_glance(glance.suggestion)
            except Exception:  # noqa: BLE001 — an early convenience never fails the tick
                _log.warning("on_glance callback failed; continuing", exc_info=True)

    # ── stage 2: retrieve. Every entry of the plan, concurrently.
    #: Only for the web fallback tier below — the semantic face takes the whole list.
    query = queries[0] if queries else intent
    with recorder.measure("retrieve"):
        semantic_started = time.perf_counter()

        async def semantic() -> tuple:
            try:
                return await _semantic_face(
                    user_id,
                    queries,
                    claim_lexical=claim_lexical,
                    claim_vectors=claim_vectors,
                    embeddings=embeddings,
                    lexical=lexical,
                    vectors=vectors,
                    content=content,
                )
            finally:
                recorder.record(
                    "retrieve.semantic", (time.perf_counter() - semantic_started) * 1000.0
                )

        async def web(web_query: str) -> list[tuple[WebSearchAnswer, str]]:
            """The supplementary face. FAIL-SOFT, always: a dead search costs a degraded
            row in the tick record and nothing else.

            On the planned tier it sits inside the same gather as the library faces, so its
            latency overlaps theirs rather than adding to them. On the fallback tier it runs
            alone, after the library came back empty — sequential because it is a
            CONSEQUENCE of that emptiness, and there was nothing worth paying for until it
            was established. Either way `wait_for` bounds it: a supplement that could delay
            a card the library already had would not be a supplement."""
            if not web_query or web_search is None:
                return []
            started = time.perf_counter()
            detail: str | None = None
            answers: list[tuple[WebSearchAnswer, str]] = []
            try:
                answer = await asyncio.wait_for(
                    web_search.search(web_query, max_results=WEB_MAX_RESULTS),
                    web_timeout,
                )
                answers.append((answer, web_query))
            except (asyncio.TimeoutError, TimeoutError):
                detail = "timeout"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a supplement never fails a tick
                detail = type(exc).__name__
            finally:
                recorder.record(child_name(WEB), (time.perf_counter() - started) * 1000.0)
                recorder.degrade(child_name(WEB), detail)
            return answers

        component, (claims, windows), web_answers = await asyncio.gather(
            run_paths(str(user_id), runs, question=intent, as_of=as_of),
            semantic() if embeddings is not None else _empty_face(),
            web(web_queries[0] if web_queries else ""),
        )
    for row in component:
        recorder.record_path(row.path, row.elapsed_ms, detail=row.degraded)

    web_tier = WEB_PLANNED if web_queries else WEB_OFF
    candidates = build_candidates(component, claims, windows, web_answers)

    # ── the fallback tier. The library answered with NOTHING — not a weak card, not a card
    # the gates held, but an empty pool — and this deployment allows a supplement. That is
    # the one condition under which asking the internet is not a guess about what the reader
    # wants: there is no internal answer to compete with, so the only alternatives are a web
    # card and silence. It runs here, after the library, because it is a consequence of the
    # library and paying for it before that was established would be paying for nothing.
    if not candidates and web_tier == WEB_OFF and web_offered:
        web_tier = WEB_FALLBACK
        with recorder.measure("retrieve"):
            web_answers = await web(intent or query)
        candidates = build_candidates(component, claims, windows, web_answers)
        if web_answers:
            plan_labels = (*plan_labels, f"{WEB}({intent or query}) [fallback]")

    web_searches = sum(int(a.searches or 0) for a, _ in web_answers)
    web_cost = sum(float(a.cost or 0.0) for a, _ in web_answers)
    web_pages = sum(len(a.citations) for a, _ in web_answers)
    touched = tuple(
        dict.fromkeys((card.subject, card.subject_label) for card in candidates if card.subject)
    )
    if not candidates:
        return finish(
            token_usage=usage,
            skipped=SKIP_NO_CANDIDATES,
            intent=intent,
            worth=plan.worth,
            plan=plan_labels,
            rejected=tuple(rejected),
            touched=touched,
            asked=asked,
            web_searches=web_searches,
            web_cost=web_cost,
            web_pages=web_pages,
            web_tier=web_tier,
        )

    # ── stage 3: pick. One weak call; it never rewrites what it chose.
    with recorder.measure("pick"):
        picked = await run_pick(
            pick_model,
            pick_messages(transcript, candidates, intent=intent),
            callbacks=callbacks,
            trace_metadata=trace_metadata,
        )
    usage = _merge_usage(usage, picked.token_usage)
    card, reason = deliver(
        picked.result,
        candidates,
        trigger=intent,
        min_confidence=min_confidence,
        ledger=ledger,
        already_shown=already_shown,
    )
    return finish(
        suggestions=(card,) if card is not None else (),
        token_usage=usage,
        skipped=reason,
        # The one gate on this lane that has a counter, because it is the one gate the
        # briefing lane also has: an uncited card held back is the same fact in both, and a
        # reader comparing the two Processing tabs must not have to know which lane drew it.
        dropped={"uncited": 1} if reason == SKIP_UNCITED else {},
        intent=intent,
        worth=plan.worth,
        plan=plan_labels,
        rejected=tuple(rejected),
        candidates=tuple(candidates),
        chosen=int(picked.result.choice) if picked.result is not None else 0,
        touched=touched,
        asked=asked,
        web_searches=web_searches,
        web_cost=web_cost,
        web_pages=web_pages,
        web_tier=web_tier,
    )


async def _empty_face() -> tuple:
    return (), ()
