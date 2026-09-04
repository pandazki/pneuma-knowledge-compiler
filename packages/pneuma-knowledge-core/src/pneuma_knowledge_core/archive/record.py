"""The ARCHIVE RECORD: what a subject leaves behind when its page moves into the archive.

WHY THIS EXISTS
---------------
Moving a page under `archive/` retires it from every default retrieval — which is the whole
point — but it also makes the subject *vanish*, and a subject that vanishes from a library
that still mentions it everywhere else is worse than one that is merely out of date. Other
live pages go on linking to it; a question about it returns whatever partial mentions
survived on its neighbours; nothing anywhere says the owner retired it. The answer is a
partial truth, and the library has no way to say so.

So the move leaves a RECORD standing at the live path: a short, machine-written page saying
what the subject was, the span it covered, how much it held, and the owner's reason. The
record is ordinary live knowledge — it is in the glance, its blocks are projected as claims,
every lane retrieves it by default — so any question about the subject is answered *this was
X; it covered A–B; the owner archived it on D because R*, with a citation for the last part.

WHAT MAKES IT SAFE
------------------
The same thing that makes rollover safe: no model. This is a NARROW MECHANICAL WRITE CHANNEL
with its own gate (`run_archive_record_gate` below), exactly as the groom channel is
(`compile/rollover.py`). Every byte of a record is derived — from the page being archived,
from the owner's own statement, and from a clock — and the channel writes nothing else.

Three anchored blocks, in this order:

1. **What the subject was.** The page's own overview `definition`, verbatim, with its
   grounding references carried over (they name anchors that now live under `archive/`,
   still unique repository-wide), followed by the marker "— archived". A page with no
   definition contributes its first CURRENT ledger claim instead — also verbatim, its
   `[cite: …]` markers included, because this block is projected as a claim and a sentence
   that arrived here with its provenance removed would be an ungrounded assertion in the
   library's default answering set. A page with NEITHER contributes its title, and that one
   case — and only that one — is exempt from the gate's grounding floor: nothing in such a
   page exists to ground on, and inventing a reference would be the fabrication.
2. **What it held.** One mechanical line: the span its sources cover, its claim count, its
   source count, its closed volumes, and how many live pages link to it. This block CITES
   NOTHING, and that is a stated rule rather than an oversight (`FACTS_EXEMPT`): its
   provenance is the record's own frontmatter, which carries every one of those numbers as
   a machine key, and the gate exempts exactly this block from the citation requirement.
3. **Why it left.** The owner's reason, citing the `owner-dialogue/v1` statement the archive
   job ingested for this proposal — so the one sentence a reader will quote back is the one
   sentence that rests on evidence, in the ordinary addressing scheme.

The anchors are SYSTEM-ASSIGNED and deterministic per `(path, slot)`, the rollover way, so a
record rendered twice from the same inputs is byte-identical and a rebuild is a no-op.

The record is READ-ONLY to every other channel. Compile refuses it at the tool face and at
the gate; the owner unmakes it by unarchiving, which replaces it with the full page again.

Pure and sync: no port, no I/O, no clock. The caller reads the tree, the source occurrence
dates and the day, and hands them in.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..canonical_glance import (
    claim_count,
    document_title,
    first_current_claim,
    repository_superseded,
)
from ..compile.anchor_ops import (
    anchored_blocks,
    assign_anchor,
    block_text,
    text_machinery_in,
    text_machinery_problems,
)
from ..compile.documents import render_document, strip_overview
from ..compile.overview import ANCHOR_REFERENCE_RE, parse_overview
from ..compile.patch import assign_document_id
from ..compile.rollover import link_targets
from ..domain.archive import (
    ARCHIVE_CLAIMS_KEY,
    ARCHIVE_INBOUND_KEY,
    ARCHIVE_OF_KEY,
    ARCHIVE_RECORD_KEYS,
    ARCHIVE_RECORD_TYPE,
    ARCHIVE_SOURCES_KEY,
    ARCHIVE_SPAN_KEY,
    ARCHIVE_STATEMENT_KEY,
    ARCHIVE_VOLUMES_KEY,
    ARCHIVED_ON_KEY,
    archived_path,
    is_archive_record,
    is_archived_path,
)
from ..domain.canonical import (
    CANONICAL_CITATION_MARKER_RE,
    HTML_COMMENT_RE,
    CanonicalDocument,
    iter_canonical_citations,
)
from ..domain.ids import DocumentId, extract_anchors
from ..prompts import prompt

#: The record's three slots, in body order. The slot NAME is what the anchor is derived
#: from, so it is machinery and stays English in every language pack — exactly like a
#: frontmatter key.
RECORD_SLOTS = ("definition", "facts", "reason")

#: The one block of a record that carries no citation, named so the exemption is a rule and
#: not a gap. Its provenance is the frontmatter: every number it states is a machine key on
#: the same document, written by the same channel in the same commit.
FACTS_EXEMPT = "facts"

#: What joins the clauses of the facts line. One separator, stated once, so the line reads
#: the same in both languages.
FACTS_JOINER = " · "

#: The span key's own separator: `2026-01-04/2026-06-30`. A frontmatter value, so it is
#: machine punctuation and not display prose.
SPAN_SEPARATOR = "/"

#: Where the record's first block got its sentence, in decreasing order of how much the page
#: said about its own subject. Machinery — the value travels in the kept preview and is read
#: by the gate — so it stays English, exactly like a frontmatter key.
DEFINITION_FROM_OVERVIEW = "overview"
DEFINITION_FROM_LEDGER = "ledger"
DEFINITION_FROM_TITLE = "title"

#: The ONE case the gate's grounding floor exempts, named so the exemption is a rule and not
#: a gap. Every other first block rests on something: an overview definition is grounded by
#: the compile gate (every overview block cites a ledger claim or a source span) and a ledger
#: claim is grounded by the provenance rule (a `[cite: …]` span, or the `c:` anchor it was
#: derived from). A page with NEITHER — no definition and not one current claim — has nothing
#: in it to ground on, and the block is then its title and the archived marker: a name and a
#: fact about the library, which is the honest floor. Inventing a reference there would be the
#: fabrication; refusing the archive of an empty page would retire nothing and help nobody.
GROUNDING_EXEMPT = DEFINITION_FROM_TITLE

#: What the record's own document id is derived from. A record and the full copy it stands in
#: front of are TWO documents at two paths, and `assign_document_id` is a function of a path
#: alone — so deriving the record's id from the live path would mint the id the moved page is
#: already carrying, and `read(user, doc_id)` would answer with whichever of the two the
#: listing happened to reach first. The suffix is the distinct key, and it is stated once.
RECORD_ID_SUFFIX = " archive-record"

#: `[cite: …]` as a bracket marker, captured so the renderer can reduce one inside the
#: Owner's own words to plain text without deleting a word of what they wrote.
_CITE_BRACKET_RE = re.compile(r"\[[ \t]*(cite[ \t]*:[^\]]*)\]")

#: The two placeholders a model invents when it means "assign me an id here". They are the
#: system's vocabulary and never a word anybody wrote, so a note carrying one loses it.
_PLACEHOLDER_RE = re.compile(r"__AUTO__|__NEW__")


def record_doc_id(path: str) -> DocumentId:
    """The record's own document id — derived, deterministic, and distinct from the page's.

    Through the same `assign_document_id` every other channel mints an id with, over a key
    that no path can equal (`RECORD_ID_SUFFIX`). The page keeps the id it has always had on
    the other side of the move, so the pair is two documents with two ids and an unarchive
    restores exactly one of them.
    """
    return assign_document_id(f"{path}{RECORD_ID_SUFFIX}")


def note_machinery(note: str) -> str | None:
    """The claim-text machinery in an Owner's note, or None when it carries none.

    The predicate the request faces refuse on (`422 note_machinery`), and it is the compile
    gate's own (`compile/gate.py: check_claim_text_machinery`, via `text_machinery_in`) rather
    than a second reading of the same idea: a note is interpolated verbatim into a block that
    the projection then indexes as a claim, so text that would be refused inside a claim has
    to be refused before it becomes one. Refusing at the REQUEST is what makes the Owner the
    one who fixes it — a sanitizer alone would silently rewrite their words.
    """
    return text_machinery_in(note or "")


def record_text(text: str) -> str:
    """Canonical text carried into a record: comments out, whitespace folded, words untouched.

    Applied to the sentence the first block copies, from wherever it came. An HTML comment is
    the system's machinery in every spelling it has — an anchor, a supersedes mark, a model's
    invented `__AUTO__` separator — and never a word the page says, so it does not travel into
    a new document. `[cite: …]` spans and `c:` references DO travel: they are the grounding
    the block rests on, and dropping them is the one thing this whole channel must not do.
    """
    return " ".join(HTML_COMMENT_RE.sub("", text or "").split())


def sanitize_note(note: str) -> str:
    """The Owner's own words, with the system's machinery taken back out of them.

    The second half of the note defence, and it is defence in depth rather than the main
    mechanism: `plan` and `confirm` refuse a note `note_machinery` flags, so by the time a
    note reaches here it is already clean and this is a no-op. It stands anyway because the
    renderer is the last thing between a stored note and a committed claim, and a row written
    before that refusal existed must not be able to put an anchor comment, a supersedes mark
    or a second `[cite: …]` into the one block of a record that carries a citation.

    Nothing is deleted except machinery: comments go, the two id placeholders go, and a
    `[cite: …]` loses its BRACKETS and keeps its text — so a reader still sees every word the
    Owner typed, while the citation parser sees exactly one marker in that block, the one the
    renderer appends.
    """
    text = HTML_COMMENT_RE.sub("", note or "")
    text = text.replace("<!--", "").replace("-->", "")
    text = _PLACEHOLDER_RE.sub("", text)
    text = _CITE_BRACKET_RE.sub(r"\1", text)
    return " ".join(text.split())


def record_reason(note: str = "", titles: Sequence[str] = ()) -> str:
    """The Owner's words: their note, or the default sentence naming what they archived.

    ONE string with two jobs — it is the TEXT of the `owner-dialogue/v1` statement the job
    ingests AND the sentence the record's third block quotes — because those two must be the
    same words. A record quoting something its cited source does not say would be the one
    fabrication this framework makes impossible everywhere else.

    Here in core, and not in the job that calls it, because the request faces need it too:
    the plan-time preview shows the Owner the exact line that will be quoted, and a preview
    computed by a second implementation of "what will be quoted" is a preview of something
    else. The note is sanitized on the way through, so the preview, the statement and the
    record are three appearances of one string.
    """
    cleaned = sanitize_note(note)
    if cleaned:
        return cleaned
    return prompt(
        "archive.statement.default",
        titles=", ".join(str(title) for title in titles if str(title or "").strip()),
    )


def owner_turn_prefix() -> str:
    """The label an `owner-dialogue/v1` block puts in front of an owner's words.

    Derived from the very prompts the ingest normalizer renders the turn line with, so it
    holds in every language pack rather than in the one this file was written in.
    """
    return prompt(
        "ingest.turn_line", label=prompt("ingest.owner_label"), text=""
    ).rstrip()


def statement_quote(block: str) -> str:
    """The Owner's own words inside a statement's block 0 — the turn line, label removed.

    What the record's reason block QUOTES when the Owner supplied a `statement_ref` of their
    own. Taking it from the source, rather than from a note typed beside it, is what makes
    `[cite: <sid> ¶0]` true: the sentence a reader quotes back is the sentence the block they
    are pointed at actually contains.

    The quote is deliberately NOT byte-verbatim, and the two departures are named. The ingest
    label (`owner_turn_prefix`) is stripped: `owner-dialogue/v1` renders a turn as
    `<label>: <text>`, so the label is the CONTRACT's framing of who is speaking and never a
    word the Owner typed — quoting it back would put the transport into the Owner's mouth.
    Whitespace is folded because a record block is one line. Nothing else is touched, and no
    word is dropped.
    """
    text = " ".join(str(block or "").split())
    prefix = owner_turn_prefix()
    if prefix and text.startswith(prefix):
        text = text[len(prefix) :].strip()
    return text


# ----------------------------------------------------------------------------- the facts


@dataclass(frozen=True)
class RecordFacts:
    """Everything a record states, computed from the page and the library around it.

    Computed at PLAN time so the console can preview the record the owner is about to
    create, and computed AGAIN by the job at execution over the set the Owner finally
    confirmed. Two callers, one function (`record_facts_in_move`): the plan-time copy kept on
    the item is a PREVIEW, and the numbers the page states are the ones that were true of the
    tree the commit is about to change. They agree whenever nothing was unticked — which is
    the ordinary case — and when something was, the page is right rather than the preview.
    """

    #: The page's own name, which the record keeps.
    title: str = ""
    #: The page's `definition` — verbatim, grounding references included — or its first
    #: current ledger claim (also verbatim, `[cite: …]` included), or (when it has neither)
    #: its title. Never generated.
    definition: str = ""
    #: WHICH of those three the definition is: `overview` / `ledger` / `title`. Machinery, not
    #: display — the gate reads it to decide whether the first block is allowed to rest on
    #: nothing, which exactly one of the three cases is (`GROUNDING_EXEMPT`).
    definition_source: str = DEFINITION_FROM_OVERVIEW
    #: `(first, last)` `occurred_on` over the sources the page's claims cite, or None when
    #: no cited source states a date. Omitted from the line rather than guessed.
    span: tuple[str, str] | None = None
    #: Ledger claims, the page and its closed volumes together.
    claims: int = 0
    #: Distinct sources those claims cite.
    sources: int = 0
    #: Closed volumes travelling with the page.
    volumes: int = 0
    #: LIVE pages, outside the set this proposal moves, whose bodies link to this path.
    inbound: int = 0

    def as_dict(self) -> dict:
        """The wire/kept shape — a plain mapping, so a proposal row round-trips as JSON."""
        return {
            "title": self.title,
            "definition": self.definition,
            "definition_source": self.definition_source,
            "span": list(self.span) if self.span is not None else None,
            "claims": self.claims,
            "sources": self.sources,
            "volumes": self.volumes,
            "inbound": self.inbound,
        }

    @staticmethod
    def from_dict(data: Mapping | None) -> "RecordFacts | None":
        if not data:
            return None
        span = data.get("span")
        return RecordFacts(
            title=str(data.get("title") or ""),
            definition=str(data.get("definition") or ""),
            definition_source=str(
                data.get("definition_source") or DEFINITION_FROM_OVERVIEW
            ),
            span=(str(span[0]), str(span[1])) if span else None,
            claims=int(data.get("claims") or 0),
            sources=int(data.get("sources") or 0),
            volumes=int(data.get("volumes") or 0),
            inbound=int(data.get("inbound") or 0),
        )


def record_definition(
    doc: CanonicalDocument, superseded: Iterable[str] = ()
) -> tuple[str, str]:
    """`(the line a record leads with, where it came from)`. Three fallbacks and no fourth.

    In decreasing order of how much the page itself said about its own subject, and every one
    of them VERBATIM: the overview `definition`, else the page's first CURRENT ledger claim,
    else its title. The grounding rides along in both of the first two — `c:` references and
    `[cite: …]` spans are kept exactly as the page carried them, and they still resolve,
    because the anchors they name travel into `archive/` with the page and stay unique
    repository-wide.

    The ledger fallback is the claim ITSELF and not the glance's `ledger:` line, and the
    difference is the whole point of this being a separate function. The glance line is
    DISPLAY text: it strips the citations along with the markdown, because a person reading a
    line under a title is not reading addresses. Copying that stripped line into a record
    would put an ungrounded sentence — a claim by every mechanical definition, since the
    projection indexes a record's blocks like any other — into the library's default
    answering set, which is invariant I4 broken by the one channel written to protect it.

    Nothing here is generated: a record that invented a sentence about a retired subject
    would be the one fabrication this whole framework exists to make impossible.
    """
    overview, _ = parse_overview(doc.body)
    if overview is not None and overview.definition.strip():
        return record_text(overview.definition), DEFINITION_FROM_OVERVIEW
    claim = first_current_claim(doc, superseded)
    if claim:
        return record_text(claim), DEFINITION_FROM_LEDGER
    return document_title(doc), DEFINITION_FROM_TITLE


def compute_record_facts(
    doc: CanonicalDocument,
    *,
    volumes: Sequence[CanonicalDocument] = (),
    live_bodies: Mapping[str, str] | None = None,
    source_occurrence: Mapping[str, str] | None = None,
    superseded: Iterable[str] = (),
) -> RecordFacts:
    """Everything the record for `doc` will state. Pure; the caller supplies the library.

    `volumes` are the page's closed volumes (they move with it and count towards its
    claims and sources). `live_bodies` is `path → body` over the live pages whose links
    count as INBOUND — the caller excludes the page's own unit and the rest of the set this
    proposal moves, because a link from a page that is leaving too is not a link this record
    is left holding. `source_occurrence` is `source_id → occurred_on` for every source the
    library holds; a source absent from it, or carrying an empty day, contributes no span.
    """
    bodies = [doc.body, *(volume.body for volume in volumes)]
    claims = sum(claim_count(volume) for volume in (doc, *volumes))
    cited = {
        str(citation.source_id)
        for body in bodies
        for citation in iter_canonical_citations(strip_overview(body))
    }
    days = sorted(
        day
        for day in (
            str((source_occurrence or {}).get(source_id) or "").strip()
            for source_id in cited
        )
        if day
    )
    inbound = 0
    for path, body in sorted((live_bodies or {}).items()):
        if doc.path in link_targets(body, path):
            inbound += 1
    definition, definition_source = record_definition(doc, superseded)
    return RecordFacts(
        title=document_title(doc),
        definition=definition,
        definition_source=definition_source,
        span=(days[0], days[-1]) if days else None,
        claims=claims,
        sources=len(cited),
        volumes=len(volumes),
        inbound=inbound,
    )


def unit_facts(
    documents: Sequence[CanonicalDocument],
    path: str,
    *,
    volumes: Sequence[str] = (),
    moving: Collection[str] = (),
    source_occurrence: Mapping[str, str] | None = None,
) -> RecordFacts | None:
    """`compute_record_facts` over a whole tree, addressed by path. None when absent.

    The convenience the planner and the job both call, so "which pages count as inbound" is
    decided in ONE place: every live page except the archived page itself, its own volumes,
    and everything else `moving` names.
    """
    by_path = {doc.path: doc for doc in documents}
    doc = by_path.get(path)
    if doc is None:
        return None
    own = {path, *volumes}
    excluded = own | {str(ref) for ref in moving}
    live_bodies = {
        other.path: other.body
        for other in documents
        if other.path not in excluded
        and not is_archived_path(other.path)
        and not is_archive_record(other)
    }
    return compute_record_facts(
        doc,
        volumes=[by_path[v] for v in volumes if v in by_path],
        live_bodies=live_bodies,
        source_occurrence=source_occurrence,
        superseded=repository_superseded(documents),
    )


def record_facts_in_move(
    documents: Sequence[CanonicalDocument],
    path: str,
    *,
    volumes: Sequence[str] = (),
    moving: Mapping[str, Sequence[str]] | None = None,
    source_occurrence: Mapping[str, str] | None = None,
) -> RecordFacts | None:
    """`unit_facts` with the ONE definition of what "leaving in this move" means.

    `moving` is `path → its volumes` for every unit the move takes. The unit at `path` is
    dropped from it before the count is made — a page is not its own inbound link, and its own
    volumes are part of it rather than pages that link to it.

    This exists so the PLANNER and the JOB compute a record's facts by calling one function
    with one argument shape. They must, because they compute over different sets: the planner
    over the set it just closed, the job over the set the Owner finally CONFIRMED. A confirm
    may untick a box, and unticking a page that linked to another page in the same set changes
    the second one's `inbound` — so a job that wrote the plan-time number would commit a
    sentence that was true of a move that did not happen. The plan-time copy is a preview; the
    page states what was true of the tree the commit is about to change.
    """
    units = dict(moving or {})
    units.pop(path, None)
    leaving = {other for other in units}
    leaving |= {volume for own in units.values() for volume in own}
    return unit_facts(
        documents,
        path,
        volumes=tuple(volumes),
        moving=leaving,
        source_occurrence=source_occurrence,
    )


# -------------------------------------------------------------------------- the rendering


def record_anchors(path: str, taken: Collection[str] = ()) -> dict[str, str]:
    """`slot → anchor` for one record, deterministic per `(path, slot)`.

    The rollover derivation, applied to this channel's own slot names: the id is a function
    of the path and the slot, so re-rendering the same record produces the same three ids
    and a rebuild is byte-identical. `taken` is every anchor the repository already holds,
    which is what keeps them unique repository-wide — including against the anchors of the
    full copy the same commit is putting under `archive/`.
    """
    used = set(taken)
    out: dict[str, str] = {}
    for slot in RECORD_SLOTS:
        anchor = assign_anchor(path, f"archive-record-{slot}", used)
        used.add(anchor)
        out[slot] = anchor
    return out


def facts_line(facts: RecordFacts) -> str:
    """The record's second block, in words. Mechanical, and the same numbers as the frontmatter.

    LABELLED NUMBERS, one clause each, the number LAST. A mechanical channel cannot inflect —
    there is no model here to write `1 source` beside `2 sources`, and asking a language pack
    to carry plural forms for a line four numbers wide would put grammar machinery in the
    prompt catalog. So no clause counts a noun: each names what it counts and then states the
    figure, which reads the same at 0, 1 and 4 in both languages.

    And each label names WHICH count it is. `claims` here is the LEDGER's — this page and its
    closed volumes (`RecordFacts.claims`) — while the library view states a number for the
    same page that includes the overview's projected blocks. Two different numbers about one
    page both stood in front of the owner unlabelled; the label is what makes them readable
    side by side.
    """
    clauses = []
    if facts.span is not None:
        clauses.append(
            prompt(
                "archive.record.facts_span", start=facts.span[0], end=facts.span[1]
            )
        )
    clauses.append(
        prompt(
            "archive.record.facts",
            claims=facts.claims,
            sources=facts.sources,
            volumes=facts.volumes,
            inbound=facts.inbound,
        )
    )
    return FACTS_JOINER.join(clauses)


def record_frontmatter(
    path: str,
    facts: RecordFacts,
    *,
    slug: str,
    archived_on: str,
    statement_ref: str,
) -> dict:
    """The record's frontmatter: a complete document, plus the machine facts.

    Every number the second block states in words is here as a key, and that is what makes
    that block's exemption from the citation rule a mechanism rather than a courtesy: the
    line's provenance is the same document's own frontmatter, written in the same commit by
    the same channel. Values are strings, like every other frontmatter value this repository
    writes, so a round-trip through git is byte-stable.

    `doc_id` is the RECORD's own (`record_doc_id`), not the page's. The move puts two
    documents into the tree — the full copy under `archive/<path>` and this record at `<path>`
    — and an id derived from the live path alone would be the same id on both, which makes
    `read(user, doc_id)` answer with whichever the listing reached first. The copy keeps the
    id it has carried all along; an unarchive removes this one with the record it belongs to.
    """
    frontmatter = {
        "doc_id": str(record_doc_id(path)),
        "type": ARCHIVE_RECORD_TYPE,
        "slug": slug,
        "title": facts.title,
        ARCHIVE_OF_KEY: archived_path(path),
        ARCHIVED_ON_KEY: archived_on,
        ARCHIVE_STATEMENT_KEY: statement_ref,
        ARCHIVE_CLAIMS_KEY: str(facts.claims),
        ARCHIVE_SOURCES_KEY: str(facts.sources),
        ARCHIVE_VOLUMES_KEY: str(facts.volumes),
        ARCHIVE_INBOUND_KEY: str(facts.inbound),
    }
    if facts.span is not None:
        frontmatter[ARCHIVE_SPAN_KEY] = SPAN_SEPARATOR.join(facts.span)
    return frontmatter


def frontmatter_facts(frontmatter: Mapping) -> RecordFacts:
    """The numbers a record's frontmatter states, back as the facts the line is rendered from.

    The inverse of `record_frontmatter` over exactly the keys the second block puts into
    words, and it exists for ONE caller: the gate, which has to read the body against the
    frontmatter rather than reading both against the same in-memory object. Comparing the
    keys and the line to the `facts` a render was made from says nothing about a record that
    arrived from anywhere else — a hand-edited file, a row repaired by an operator, a second
    implementation — and `FACTS_EXEMPT` is the promise that the frontmatter IS that line's
    provenance. So the line is re-rendered from the keys and required to be the one on the
    page (docs/design/archive.md §2.3).

    A malformed value is read as its floor (`0`, no span) rather than raised over: the gate
    is a comparison, and a key that will not parse is a disagreement it must be able to
    STATE. The completeness of the keys is check 4's own first half.
    """
    def _count(key: str) -> int:
        try:
            return int(str(frontmatter.get(key) or "").strip())
        except ValueError:
            return 0

    span_parts = str(frontmatter.get(ARCHIVE_SPAN_KEY) or "").split(SPAN_SEPARATOR)
    return RecordFacts(
        title=str(frontmatter.get("title") or ""),
        span=(span_parts[0], span_parts[1]) if len(span_parts) == 2 else None,
        claims=_count(ARCHIVE_CLAIMS_KEY),
        sources=_count(ARCHIVE_SOURCES_KEY),
        volumes=_count(ARCHIVE_VOLUMES_KEY),
        inbound=_count(ARCHIVE_INBOUND_KEY),
    )


def render_record_body(
    path: str,
    facts: RecordFacts,
    *,
    archived_on: str,
    statement_ref: str,
    reason: str,
    taken: Collection[str] = (),
) -> str:
    """The record's three anchored blocks under the page's own title.

    `reason` is the owner's own words — the block 0 of the statement this record cites, which
    is the confirm-time note or the default sentence when they wrote none — and it is quoted
    rather than paraphrased. It passes through `sanitize_note` on the way in: the words are
    the owner's, the machinery is the system's, and the one block of a record that carries a
    citation must carry exactly the one this renderer appends. The citation is appended HERE
    rather than written into the prompt, because `[cite: …]` is the addressing scheme and its
    placement must not vary with the language the deployment reads.
    """
    anchors = record_anchors(path, taken)
    blocks = [
        prompt("archive.record.definition", text=facts.definition),
        facts_line(facts),
        prompt("archive.record.reason", date=archived_on, note=sanitize_note(reason))
        + f" [cite: {statement_ref} ¶0]",
    ]
    lines = [f"# {facts.title}", ""]
    for slot, block in zip(RECORD_SLOTS, blocks):
        lines.append(f"{block.rstrip()} <!-- c:{anchors[slot]} -->")
        lines.append("")
    return "\n".join(lines).strip("\n") + "\n"


def render_record(
    path: str,
    facts: RecordFacts,
    *,
    slug: str,
    archived_on: str,
    statement_ref: str,
    reason: str,
    taken: Collection[str] = (),
) -> str:
    """One record, serialized exactly as it is committed. Deterministic in every input."""
    return render_document(
        record_frontmatter(
            path,
            facts,
            slug=slug,
            archived_on=archived_on,
            statement_ref=statement_ref,
        ),
        render_record_body(
            path,
            facts,
            archived_on=archived_on,
            statement_ref=statement_ref,
            reason=reason,
            taken=taken,
        ),
    )


# ------------------------------------------------------------------ the channel's own gate


@dataclass(frozen=True)
class RecordViolation:
    """One refusal from the archive channel's gate. Any violation abandons the whole write."""

    kind: str  # archive_record
    path: str
    detail: str

    def render(self) -> str:
        return f"[{self.kind}] {self.path}: {self.detail}"


def _grounding(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """`(anchor references, citation markers)` — what a block rests on, in both spellings."""
    return (
        frozenset(ANCHOR_REFERENCE_RE.findall(text)),
        frozenset(m.group(0) for m in CANONICAL_CITATION_MARKER_RE.finditer(text)),
    )


def run_archive_record_gate(
    *,
    path: str,
    frontmatter: Mapping,
    body: str,
    facts: RecordFacts,
    statement_ref: str,
    moved_body: str,
    base_body: str,
    repository_anchors: Collection[str] = (),
    repository_doc_ids: Collection[str] = (),
) -> list[RecordViolation]:
    """The archive channel's gate. Every check hard-rejects; any violation writes nothing.

    `moved_body` is the full copy as it will stand under `archive/<path>`; `base_body` is the
    page that was there before the move. `repository_anchors` is every anchor the tree holds
    EXCLUDING this record's own three — the record is new, so its ids must collide with
    nothing, the full copy's anchors included. `repository_doc_ids` is the same statement one
    level up: every `doc_id` the tree holds, this record's own excluded.

    1. `record_anchors` — the three anchors are exactly the system-assigned ones for
       `(path, slot)`, in slot order, and none of them is taken anywhere in the repository.
       An anchor a channel did not derive is an identity nobody can reproduce on a rebuild.
    2. `record_statement` — the third block cites the owner's statement, by the source id the
       job ingested. The one sentence a reader quotes is the one that rests on evidence.
       What the block quotes is that statement's ¶0 in the form `statement_quote` produces:
       the turn text with its ROLE LABEL stripped and its whitespace folded, deliberately not
       byte-verbatim. The label is `owner-dialogue/v1`'s framing of who is speaking — the
       contract's word, not the Owner's — so quoting it back would put the transport into
       their mouth; the folding is because a record block is one line. No word is dropped,
       which is why the gate can still check the citation without checking the bytes.
       Read a SECOND time against the frontmatter (`statement_mismatch`): `archive_statement`
       must name the source the block actually cites. The inventory reports a record off its
       frontmatter alone and never opens the body, so a key naming one statement while the
       reason quotes another would have the two faces of one record answer differently about
       whose words those are.
    3. `record_grounding` — the first block carries every grounding reference the page's own
       definition carried, in both spellings (`c:` references and `[cite: …]` markers).
       Carrying the definition and dropping what it rested on would turn a grounded sentence
       into an assertion.
    4. `record_frontmatter` — every machine key is present, `archive_of` names the full copy,
       `archive_span` states exactly the span these facts carry (and is ABSENT when they
       carry none, which is why it is not one of the required keys), and each stated number
       equals the one the body's second block says in words. That
       equality is the whole of `FACTS_EXEMPT`: the facts line cites nothing because its
       provenance is these keys, so the two disagreeing would leave it resting on nothing.
       Read in BOTH directions, because the two readings answer different questions: the keys
       are checked against the `facts` this render was made from, and then the body's second
       block is PARSED and required to be the line those keys produce (`frontmatter_facts` →
       `facts_line`). The first alone is blind to a page whose body was written from anything
       but that object — a hand edit, an operator's repair, a second implementation — which
       is exactly the page the promise is about.
    5. `record_conservation` — the full copy under `archive/` is byte-identical to the page
       that stood at the live path. The archive is a MOVE; a channel that also rewrote the
       page it moved would be the one thing `move_documents` exists to make impossible.
    6. `record_grounded` — the first block RESTS on something: a `c:` reference or a
       `[cite: …]` span. Check 3 only says the block kept what its source carried, which is
       silent about a source that carried nothing, and a record's blocks are projected as
       claims like any other page's — so an ungrounded one would be an assertion about a
       retired subject sitting in every default answer (I4). Exactly ONE case is exempt and it
       is named rather than inferred (`GROUNDING_EXEMPT`): a page with no overview definition
       and not one current claim, whose first block is its title and the archived marker,
       because there is nothing in such a page to ground on and inventing a reference would be
       the fabrication.
    7. `record_machinery` — no block's TEXT carries the system's own machinery, judged by the
       compile gate's own predicate (`text_machinery_problems`). The renderer already
       sanitizes the owner's note; this is the arbiter over the produced page, so a comment or
       an `__AUTO__` reaching a record from anywhere at all abandons the write instead of
       being committed inside a claim.
    8. `record_doc_id` — the record's id IS `record_doc_id(path)`, and it is taken by nothing
       else in the tree. Two halves, and the first is what makes the second meaningful: an
       id derived from a key no path can equal is unique by construction, so checking only
       for a collision would pass any id at all — including the one the moved copy is
       carrying, which is the exact failure the suffix exists to prevent. Two documents with
       one id is what the shadowing rules exist to prevent, and this is the one channel that
       writes a document onto a path another document just left.
    """
    violations: list[RecordViolation] = []

    def add(detail: str) -> None:
        violations.append(RecordViolation("archive_record", path, detail))

    # 1. the anchors this channel derived, and nothing else.
    expected = record_anchors(path, repository_anchors)
    blocks = anchored_blocks(body)
    found = [a for block in blocks for a in extract_anchors(block)]
    if found != [expected[slot] for slot in RECORD_SLOTS]:
        add(
            prompt(
                "gate.archive_record.anchors",
                expected=", ".join(expected[slot] for slot in RECORD_SLOTS),
                found=", ".join(found) or "-",
            )
        )
    taken = set(repository_anchors)
    for anchor in sorted(set(found) & taken):
        add(prompt("gate.archive_record.anchor_taken", anchor=anchor))

    # 2. the reason rests on the owner's own statement, and the frontmatter NAMES that same
    # statement. Two readings, because two audiences read two different halves of the page:
    # a reader follows the citation in the block, and the inventory reads `archive_statement`
    # off the frontmatter without opening the body at all. A key naming one source while the
    # block cites another would let the two answer differently about the same record.
    reason_block = blocks[2] if len(blocks) > 2 else ""
    cited = {str(c.source_id) for c in iter_canonical_citations(reason_block)}
    if not statement_ref or statement_ref not in cited:
        add(
            prompt(
                "gate.archive_record.statement",
                statement=statement_ref or "-",
                cited=", ".join(sorted(cited)) or "-",
            )
        )
    stated_statement = str(frontmatter.get(ARCHIVE_STATEMENT_KEY) or "").strip()
    if stated_statement and cited and stated_statement not in cited:
        add(
            prompt(
                "gate.archive_record.statement_mismatch",
                stated=stated_statement,
                cited=", ".join(sorted(cited)),
            )
        )

    # 3. the definition kept what it rested on. Read over the block's TEXT and not over the
    # block: its own trailing anchor is a `c:` reference by shape, so a whole-block reading
    # would find grounding on every block ever written and say nothing at all.
    want_refs, want_marks = _grounding(facts.definition)
    have_refs, have_marks = _grounding(block_text(blocks[0]) if blocks else "")
    for missing in sorted((want_refs - have_refs) | (want_marks - have_marks)):
        add(prompt("gate.archive_record.grounding", reference=missing))

    # 4. the machine keys are complete and agree with the words.
    for key in ARCHIVE_RECORD_KEYS:
        if not str(frontmatter.get(key) or "").strip():
            add(prompt("gate.archive_record.frontmatter", key=key))
    stated = str(frontmatter.get(ARCHIVE_OF_KEY) or "")
    if stated and stated != archived_path(path):
        add(
            prompt(
                "gate.archive_record.archive_of",
                stated=stated,
                expected=archived_path(path),
            )
        )
    for key, value in (
        (ARCHIVE_CLAIMS_KEY, facts.claims),
        (ARCHIVE_SOURCES_KEY, facts.sources),
        (ARCHIVE_VOLUMES_KEY, facts.volumes),
        (ARCHIVE_INBOUND_KEY, facts.inbound),
    ):
        if str(frontmatter.get(key) or "").strip() != str(value):
            add(
                prompt(
                    "gate.archive_record.facts_disagree",
                    key=key,
                    stated=str(frontmatter.get(key) or "-"),
                    expected=str(value),
                )
            )
    # The span is the one stated fact that is not a count, so it is read separately and in
    # BOTH directions at once: present it must equal the rendered span these facts carry, and
    # ABSENT it must be absent, because `ARCHIVE_RECORD_KEYS` deliberately leaves it out — a
    # page whose sources state no day has no span, and a key stating an empty one would be a
    # fact nobody has. Comparing the rendered strings makes both readings one comparison.
    span_present = ARCHIVE_SPAN_KEY in frontmatter
    stated_span = str(frontmatter.get(ARCHIVE_SPAN_KEY) or "").strip()
    if facts.span is None:
        # No day anywhere in the cited sources: the KEY must be absent. A present key stating
        # an empty value is not "no span" — it is a fact nobody has, written down.
        if span_present:
            add(
                prompt(
                    "gate.archive_record.span",
                    stated=stated_span or "(empty)",
                    expected="-",
                )
            )
    else:
        expected_span = SPAN_SEPARATOR.join(facts.span)
        if stated_span != expected_span:
            add(
                prompt(
                    "gate.archive_record.span",
                    stated=stated_span or "-",
                    expected=expected_span,
                )
            )
    # …and the BODY's second block says exactly what those keys say. Parsed and re-rendered
    # from the frontmatter rather than compared against the same `facts` object the loop
    # above used: `FACTS_EXEMPT` promises the frontmatter is this line's provenance, and a
    # body written from anything but that object — a hand edit, a repair, a second
    # implementation — is precisely the page that promise has to hold for.
    said = block_text(blocks[1]).strip() if len(blocks) > 1 else ""
    expected_line = facts_line(frontmatter_facts(frontmatter))
    if said != expected_line:
        add(
            prompt(
                "gate.archive_record.facts_body",
                stated=said or "-",
                expected=expected_line,
            )
        )

    # 5. the move moved; it did not rewrite.
    if moved_body != base_body:
        add(prompt("gate.archive_record.copy", path=archived_path(path)))

    # 6. the first block rests on something, or it is the one case that has nothing to rest on.
    if facts.definition_source != GROUNDING_EXEMPT and not (have_refs | have_marks):
        add(
            prompt(
                "gate.archive_record.ungrounded",
                source=facts.definition_source or "-",
                preview=(blocks[0] if blocks else "")[:60],
            )
        )

    # 7. no block's text carries the system's machinery — the compile gate's own predicate.
    for found, preview in text_machinery_problems(body):
        add(prompt("gate.archive_record.machinery", found=found, preview=preview))

    # 8. the record's id is the one this channel derives, and it belongs to nothing else.
    doc_id = str(frontmatter.get("doc_id") or "")
    expected_doc_id = str(record_doc_id(path))
    if doc_id != expected_doc_id:
        add(
            prompt(
                "gate.archive_record.doc_id",
                stated=doc_id or "-",
                expected=expected_doc_id,
            )
        )
    if doc_id and doc_id in {str(other) for other in repository_doc_ids}:
        add(prompt("gate.archive_record.doc_id_taken", doc_id=doc_id))

    return violations


__all__ = [
    "DEFINITION_FROM_LEDGER",
    "DEFINITION_FROM_OVERVIEW",
    "DEFINITION_FROM_TITLE",
    "FACTS_EXEMPT",
    "FACTS_JOINER",
    "GROUNDING_EXEMPT",
    "RECORD_ID_SUFFIX",
    "RECORD_SLOTS",
    "SPAN_SEPARATOR",
    "RecordFacts",
    "RecordViolation",
    "compute_record_facts",
    "facts_line",
    "frontmatter_facts",
    "note_machinery",
    "record_anchors",
    "record_definition",
    "record_doc_id",
    "record_facts_in_move",
    "record_frontmatter",
    "record_reason",
    "record_text",
    "render_record",
    "render_record_body",
    "owner_turn_prefix",
    "statement_quote",
    "run_archive_record_gate",
    "sanitize_note",
    "unit_facts",
]
