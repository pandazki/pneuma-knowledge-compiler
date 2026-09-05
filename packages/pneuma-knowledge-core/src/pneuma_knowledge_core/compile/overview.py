"""The overview's own mechanical checks — the pure half of gate steps 4c–4f.

WHAT THE OVERVIEW IS, AND WHY IT NEEDS ITS OWN CHECKS
-----------------------------------------------------
The ledger is append-only and anchor-immutable because a claim is a piece of judged
knowledge with an identity: losing one loses something. The overview is the opposite kind of
object — a bounded head the compile model may replace WHOLESALE while the ledger keeps its
bytes. Its contract is to summarize the ledger; the checks below validate its references
and structure, not whether a sentence faithfully restates what its evidence says.

The mechanical checks are:

- **grounding** — every overview block references a ledger claim (`c:<anchor>`) or cites a
  source span. A block that references neither is not a reading of the ledger, it is a new
  uncited assertion in the one non-rebuildable layer, and it is refused. The referenced
  anchor may live in ANY document's ledger: an overview legitimately says "she owns the
  supplier contracts" on the strength of a claim filed under the product. Every declared
  anchor reference must resolve, even beside a valid source citation or ledger reference.
- **budget** — the region is bounded in characters. Unbounded, "the current picture" grows
  into a second ledger that nothing keeps in step with the first.
- **slots** — the region has four slots and no others, and `definition` is one short block:
  it is the line the compile outline and the recall glance show under every document, so its
  size is a property of those two surfaces, not a stylistic preference.
- **required** — past a threshold of ledger claims, a document this round TOUCHED must have
  one. The budget keeps a head from becoming a ledger; this keeps a ledger from going on
  without a head. A model maintains an overview that exists and never starts one, so the
  first one has to be asked for mechanically (`check_overview_required`).

- **connections** — a connection is a relation to ANOTHER subject page, so its target must
  be a document that exists. The gate's dead-link check covers this repository-wide; the
  tool face states it early, because a dead connection is the one an overview writes most.

Changed overview regions are fully validated. Unchanged regions retain historical defects,
but an operation retiring a previously referenced ledger claim must repair its dependants.
Omit the base snapshot to audit every region, including historical defects.

`overview_write_problems` validates a candidate at the write-tool boundary, so the model can
repair it within its current turn. `check_overviews` validates the final draft again because
other operations can invalidate an earlier successful write.

Everything here is pure and returns `(kind, path, detail)` triples rather than `Violation`s —
the gate owns that type, and a module the gate imports cannot import it back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Protocol

from ..domain.canonical import CANONICAL_CITATION_MARKER_RE
from ..domain.ids import ANCHOR_MARK_RE, extract_anchors
from ..prompts import prompt
from .anchor_ops import anchored_blocks
from .documents import (
    OVERVIEW_SLOTS,
    overview_region,
    overview_slot_by_line,
    parse_overview,
    strip_overview,
)
from .links import _MD_LINK_RE, _resolve_relative
from .supersession import SUPERSEDES_MARK_RE

#: The rendered region's character ceiling. A framework constant, not a contract rule: how
#: much head a document may carry is a property of the mechanism (what a prompt and a glance
#: can afford), not of what a business writes about. A deployment moves it with
#: `PNEUMA_KNOWLEDGE_OVERVIEW_BUDGET_CHARS`.
OVERVIEW_BUDGET_CHARS = 2_000

#: `definition` is one sentence, and it is the line every glance and outline shows.
DEFINITION_MAX_CHARS = 200

#: How many ledger claims a document may accumulate before it MUST carry an overview. The
#: other half of the budget: the ceiling says a head may not grow into a ledger, and this
#: floor says a ledger past a certain size may not go on without a head. Measured, not
#: guessed — on a real library 41 of 85 pages had no overview at all (some of them holding
#: 20–31 claims) while the 44 that had one had been maintained ~8× each: a model maintains a
#: head that exists and does not start one. Asking for it in prose is exactly the "please
#: remember to X" the project forbids, so it is a write-time refusal. A deployment moves it
#: with `PNEUMA_KNOWLEDGE_OVERVIEW_REQUIRED_AFTER_CLAIMS`; 0 disables the rule.
OVERVIEW_REQUIRED_AFTER_CLAIMS = 8

#: An anchor REFERENCE written in prose (`c:1a2b3c4d`) — the overview's way of pointing at
#: the ledger claim it restates. Deliberately not `ANCHOR_MARK_RE`: that one matches the HTML
#: comment carrying a block's OWN identity, which is exactly what must not count as grounding.
ANCHOR_REFERENCE_RE = re.compile(r"c:([0-9a-f]{4,})")

#: One or more anchor references and nothing else — the payload of a reference wrapper.
#: Separators include the full-width punctuation a Chinese-language deployment types, for
#: the same reason the wrapper is stripped at all: the spelling is not the point.
_REFERENCE_LIST = r"c:[0-9a-f]{4,}(?:[ \t]*[;,、；，][ \t]*c:[0-9a-f]{4,})*"

#: A ledger reference the model dressed up as a source citation: `[cite: c:1a2b3c4d]`,
#: `[cite: c:1a2b3c4d; c:5e6f]`. The payload must be anchors and separators ONLY, so a real
#: locator (`[cite: <sid> ¶a-b]`, whose inner text carries a `¶` and a source id) can never
#: match and is left byte-for-byte.
_WRAPPED_IN_CITE_RE = re.compile(
    rf"\[[ \t]*cite:[ \t]*(?P<refs>{_REFERENCE_LIST})[ \t]*\]"
)

#: The same reference dressed up as a parenthetical: `(c:1a2b3c4d; c:5e6f)`, or its
#: full-width twin. A markdown link target (`](memory/people/ada.md)`) never matches — its
#: payload is not an anchor list.
_WRAPPED_IN_PARENS_RE = re.compile(
    rf"\([ \t]*(?P<refs>{_REFERENCE_LIST})[ \t]*\)"
    rf"|（[ \t]*(?P<wide>{_REFERENCE_LIST})[ \t]*）"
)


def normalize_grounding_references(text: str) -> str:
    """Reduce every dressed-up ledger reference in `text` to a bare `c:xxxx`.

    The overview grounds on the ledger by NAMING an anchor in prose; the bracket form
    `[cite: …]` is the source-locator grammar and means something else entirely. A model
    that has just written a dozen real citations reaches for the same brackets here, and the
    gate is right to refuse `[cite: c:1a2b3c4d]` — it is a locator that resolves to no
    source. But refusing it is the wrong END of the mechanism when the intent is
    unambiguous: an anchor list inside the wrapper is an anchor list, whatever it is wrapped
    in. So the wrapper is stripped at the write boundary (discipline 1: mechanism, not a
    reminder), and what reaches canonical is the one spelling the gate reads.

    Strictly a shape normalization, never a repair of meaning: only a wrapper whose whole
    payload is anchors and separators is touched. A real `[cite: <source-id> ¶a-b]` in an
    overview block is a legitimate second way to ground it and survives byte-for-byte; a
    malformed locator that is NOT an anchor list still reaches the gate, which is the only
    thing that can judge it.
    """

    def _bare(match: re.Match[str]) -> str:
        payload = match.group("refs") or match.groupdict().get("wide") or ""
        return "; ".join(f"c:{anchor}" for anchor in ANCHOR_REFERENCE_RE.findall(payload))

    return _WRAPPED_IN_PARENS_RE.sub(_bare, _WRAPPED_IN_CITE_RE.sub(_bare, text))


def overview_anchors(body: str) -> set[str]:
    """The anchors living inside `body`'s overview region (empty when it has none)."""
    return set(extract_anchors(overview_region(body)))


def ledger_anchors(body: str) -> set[str]:
    """The anchors of `body`'s LEDGER — every anchor that is not in the overview region."""
    return set(extract_anchors(strip_overview(body)))


def grounding_references(block: str) -> set[str]:
    """The ledger anchors an overview block claims to rest on.

    The block's own anchor comment and its supersedes marker are removed first: an
    identity is not a reference, and a block that grounded itself would ground nothing.
    """
    text = ANCHOR_MARK_RE.sub("", block)
    text = SUPERSEDES_MARK_RE.sub("", text)
    return {m.group(1) for m in ANCHOR_REFERENCE_RE.finditer(text)}


def overview_blocks(body: str) -> list[tuple[str, str]]:
    """`(slot, block text)` for every anchored block inside `body`'s overview region."""
    span_slots = overview_slot_by_line(body)
    if not span_slots:
        return []
    lines = body.split("\n")
    slot_of_anchor: dict[str, str] = {}
    for index, slot in span_slots.items():
        for anchor in extract_anchors(lines[index]):
            slot_of_anchor[anchor] = slot
    out: list[tuple[str, str]] = []
    for block in anchored_blocks(overview_region(body)):
        anchors = extract_anchors(block)
        slot = next((slot_of_anchor[a] for a in anchors if a in slot_of_anchor), "")
        out.append((slot, block))
    return out


#: A markdown link, collapsed to its label. A connection block leads with a relative href
#: long enough to fill a preview on its own, and the href is the least identifying thing in
#: it: the model wrote the RELATION, and the relation is what it needs quoted back.
_LINK_LABEL_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")

#: The leading list marker of a rendered connection line — structure, not the model's words.
_LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d+[.)])[ \t]+")


def _block_preview(block: str, limit: int = 64) -> str:
    """A short, single-line quote of a block — enough to find it, never enough to re-read."""
    text = _LINK_LABEL_RE.sub(r"\1", ANCHOR_MARK_RE.sub("", block))
    return _LIST_MARKER_RE.sub("", " ".join(text.split()))[:limit]


def _connection_targets(block: str) -> list[str]:
    """The `.md` link targets a connection block points at, repo-relative.

    Read with the same grammar and the same resolver the gate's dead-link check uses, so
    the tool face cannot refuse a link the gate would accept, or accept one it would refuse.
    """
    out: list[str] = []
    for match in _MD_LINK_RE.finditer(block):
        href = match.group(1).strip()
        if not href or "://" in href or not href.split("#")[0].endswith(".md"):
            continue
        out.append(href)
    return out


def _invalid_reference_problem(block: str, ledger: set[str]) -> str | None:
    """A valid reference must not mask an invalid one in the same block."""
    invalid = grounding_references(block) - ledger
    if not invalid:
        return None
    return prompt(
        "gate.overview_invalid_references",
        references=", ".join(f"c:{anchor}" for anchor in sorted(invalid)),
    )


def overview_write_problems(
    path: str,
    body: str,
    *,
    ledger: set[str],
    documents: set[str],
    budget: int = OVERVIEW_BUDGET_CHARS,
) -> list[str]:
    """Everything wrong with the overview region of the CANDIDATE `body`, in model-facing prose.

    Pure, and deliberately the same judgements `check_overviews` makes — stated at the write
    tool face, where the corrective action is still one call away. `body` is the document as
    it WOULD be: the region already rendered, normalized and anchored, so every number in a
    refusal (the rendered length, the definition length) is the number the gate would report.

    `ledger` is every ledger anchor reachable in the draft — an overview may rest on a claim
    filed under any document, and on no overview. `documents` is the draft's path set, which
    is what makes a connection target resolvable: a document created earlier in this same
    round counts, and one the model merely believes ought to exist does not.

    An empty list means the write is allowed. The caller raises; deciding is not this
    module's job, and neither is writing.
    """
    problems: list[str] = []
    region = overview_region(body)
    if not region:
        return problems

    if len(region) > budget:
        problems.append(
            prompt("compile.overview.refuse_budget", size=len(region), budget=budget)
        )

    definition_blocks: list[str] = []
    for slot, block in overview_blocks(body):
        if slot == "definition":
            definition_blocks.append(block)
        preview = _block_preview(block)
        invalid = _invalid_reference_problem(block, ledger)
        if invalid:
            problems.append(invalid)
        if not CANONICAL_CITATION_MARKER_RE.search(block) and not (
            grounding_references(block) & ledger
        ):
            problems.append(
                prompt(
                    "compile.overview.refuse_ungrounded",
                    slot=slot or OVERVIEW_SLOTS[0],
                    preview=preview,
                )
            )
        if slot != "connections":
            continue
        for href in _connection_targets(block):
            target = _resolve_relative(path, href)
            if target == path:
                problems.append(
                    prompt(
                        "compile.overview.refuse_self_connection",
                        preview=preview,
                        path=path,
                    )
                )
            elif target not in documents:
                problems.append(
                    prompt(
                        "compile.overview.refuse_dead_connection",
                        preview=preview,
                        target=target,
                    )
                )

    if len(definition_blocks) > 1:
        problems.append(
            prompt(
                "compile.overview.refuse_definition_blocks",
                count=len(definition_blocks),
            )
        )
    for block in definition_blocks:
        text = " ".join(
            CANONICAL_CITATION_MARKER_RE.sub("", ANCHOR_MARK_RE.sub("", block)).split()
        )
        if len(text) > DEFINITION_MAX_CHARS:
            problems.append(
                prompt(
                    "compile.overview.refuse_definition_length",
                    size=len(text),
                    budget=DEFINITION_MAX_CHARS,
                )
            )
    return problems


def check_overviews(
    bodies: Mapping[str, str],
    *,
    base_bodies: Mapping[str, str] | None = None,
    budget: int = OVERVIEW_BUDGET_CHARS,
) -> list[tuple[str, str, str]]:
    """Judge changed regions and newly dangling references; without a base, audit all.

    Grounding is judged against the LEDGER anchors of the WHOLE repository, minus every
    overview region's own anchors: an overview may rest on a claim this round added, and on a
    claim filed in another document, but never on another overview — a head that grounds a
    head grounds nothing.

    An unchanged region's pre-existing defects do not block unrelated writes, including
    writes that cannot repair a closed volume or archive. Its references that resolved in
    the base must still resolve now: the operation retiring them owns that repair.
    """
    findings: list[tuple[str, str, str]] = []
    ledger = {anchor for body in bodies.values() for anchor in ledger_anchors(body)}
    base_ledger = {anchor for body in (base_bodies or {}).values() for anchor in ledger_anchors(body)}

    for path in sorted(bodies):
        body = bodies[path]
        region = overview_region(body)
        if not region:
            continue

        if base_bodies is not None and region == overview_region(base_bodies.get(path, "")):
            for _, block in overview_blocks(body):
                # Ignore only references that were already absent, not newly broken ones.
                historical_missing = grounding_references(block) - base_ledger
                invalid = _invalid_reference_problem(block, ledger | historical_missing)
                if invalid:
                    findings.append(("overview", path, invalid))
            continue

        if len(region) > budget:
            findings.append(
                (
                    "overview",
                    path,
                    prompt("gate.overview_budget", size=len(region), budget=budget),
                )
            )

        slots = sorted(set(overview_slot_by_line(body).values()))
        for slot in slots:
            if slot not in OVERVIEW_SLOTS:
                findings.append(
                    (
                        "overview",
                        path,
                        prompt(
                            "gate.overview_unknown_slot",
                            slot=slot,
                            slots=", ".join(OVERVIEW_SLOTS),
                        ),
                    )
                )

        definition_blocks = []
        for slot, block in overview_blocks(body):
            if slot == "definition":
                definition_blocks.append(block)
            invalid = _invalid_reference_problem(block, ledger)
            if invalid:
                findings.append(("overview", path, invalid))
            if CANONICAL_CITATION_MARKER_RE.search(block):
                continue
            if grounding_references(block) & ledger:
                continue
            preview = " ".join(
                ANCHOR_MARK_RE.sub("", block).split()
            )[:48]
            findings.append(
                ("overview", path, prompt("gate.overview_ungrounded", preview=preview))
            )

        if len(definition_blocks) > 1:
            findings.append(
                (
                    "overview",
                    path,
                    prompt(
                        "gate.overview_definition_blocks", count=len(definition_blocks)
                    ),
                )
            )
        for block in definition_blocks:
            text = " ".join(
                CANONICAL_CITATION_MARKER_RE.sub(
                    "", ANCHOR_MARK_RE.sub("", block)
                ).split()
            )
            if len(text) > DEFINITION_MAX_CHARS:
                findings.append(
                    (
                        "overview",
                        path,
                        prompt(
                            "gate.overview_definition_length",
                            size=len(text),
                            budget=DEFINITION_MAX_CHARS,
                        ),
                    )
                )
    return findings


class _DocumentLike(Protocol):
    """What `check_overview_required` needs of a draft document, and nothing more.

    Structural, so core's dependency direction holds: the gate and the patch draft import
    this module, and a module they import may not import them back.
    """

    body: str
    frontmatter: dict


def has_definition(body: str) -> bool:
    """Does `body` carry an overview region whose `definition` slot says something?

    `definition` and not merely "a region": it is the one slot every glance and outline
    shows, so a region without it leaves the document exactly as headless as before on the
    surfaces where a head is what a reader gets.
    """
    overview, _ = parse_overview(body)
    return overview is not None and bool(overview.definition.strip())


def check_overview_required(
    documents: Mapping[str, _DocumentLike],
    base_documents: Mapping[str, _DocumentLike],
    *,
    threshold: int = OVERVIEW_REQUIRED_AFTER_CLAIMS,
) -> list[tuple[str, str]]:
    """Pages this round TOUCHED that carry enough ledger to owe a head. `(path, detail)`.

    A page with enough ledger claims must gain an overview when it is next changed.
    This presence requirement is incremental; reference validity for existing overviews is
    repository-wide. `threshold <= 0` disables the presence requirement only.

    Duck-typed on `.body` and `.frontmatter` (the compile draft's document records) so this
    module stays where it is in the dependency direction: the gate and the patch draft
    import it, never the other way. `threshold <= 0` disables the rule entirely.
    """
    if threshold <= 0:
        return []
    findings: list[tuple[str, str]] = []
    for path in sorted(documents):
        doc = documents[path]
        base = base_documents.get(path)
        if base is not None and (
            doc.body == base.body and doc.frontmatter == base.frontmatter
        ):
            continue
        count = len(ledger_anchors(doc.body))
        if count < threshold or has_definition(doc.body):
            continue
        findings.append(
            (path, prompt("compile.overview.refuse_missing", path=path, count=count))
        )
    return findings


__all__ = [
    "ANCHOR_REFERENCE_RE",
    "DEFINITION_MAX_CHARS",
    "OVERVIEW_BUDGET_CHARS",
    "OVERVIEW_REQUIRED_AFTER_CLAIMS",
    "check_overview_required",
    "check_overviews",
    "grounding_references",
    "has_definition",
    "ledger_anchors",
    "normalize_grounding_references",
    "overview_anchors",
    "overview_blocks",
    "overview_write_problems",
]
