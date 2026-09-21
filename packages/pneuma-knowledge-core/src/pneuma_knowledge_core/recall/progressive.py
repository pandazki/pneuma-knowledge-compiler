"""A bounded verbatim first finding followed by an evidence-based refinement.

The first model selects a short record or summarizes one complete longer record. The second sees exactly what
was offered first, classifies its relationship, and writes one factual answer shared
by the card and voice. Citation admission checks addresses, not semantic entailment or Live playback.
"""
from __future__ import annotations

import re
import unicodedata

from dataclasses import dataclass, field
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, create_model

from ..prompts import prompt
from ..domain.consultation import parse_span_ref
from .call import speakable
from .citation_alias import iter_answer_citations, parse_citation_markers
from .evidence_context import render_candidate_context
from .fast import RetrievedClaim, FastEvidence, evidence_manifest, extract_usage, invoke_config, zero_usage


class FirstChoice(BaseModel):
    index: int = Field(description="Index of one relevant self-contained record, or -1 when none is safe")


class FirstSummary(BaseModel):
    index: int = Field(description="One relevant record index, or -1 if none answers the question")
    summary: str = Field(default="", max_length=200, description="One brief supported partial answer; no totals or claims of completeness")


class RefinementDecision(BaseModel):
    relation: Literal["answer", "extend", "correct", "confirm", "unresolved"]
    answer: str = Field(description="Complete standalone answer for the screen, without citation markers")
    citations: list[str] = Field(default_factory=list, description="Exact evidence citation markers supporting the answer")


class RefinementUnit(BaseModel):
    text: str = Field(description="One self-contained factual sentence for the full answer")
    change: Literal["retained", "new", "correction"]
    citations: list[str]


class IncrementalDecision(BaseModel):
    relation: Literal["answer", "extend", "correct", "confirm", "unresolved"]
    units: list[RefinementUnit] = Field(description="Ordered full-answer sentences; classify each against the earlier result")


@dataclass(frozen=True)
class FirstFinding:
    text: str = ""
    usage: dict[str, int] = field(default_factory=zero_usage)
    locator: str = ""


@dataclass(frozen=True)
class RefinedAnswer:
    answer: str
    speech: str
    relation: str
    usage: dict[str, int]


def canonical_first_claims(question, documents):
    """None permits lexical fallback; [] means a named subject needs the broader answer.

    Exact normalized names only: no fuzzy entity guessing. Only current overview slots
    are eligible, never an incidental mention in a different subject's ledger.
    """
    from ..compile.documents import derived_title
    from ..domain.archive import is_archived_path, is_archive_record
    from .projection import project_document_claims
    from .provenance import CanonicalProvenance

    def normalized(text):
        return re.sub(r"[\s_-]+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()

    docs = [d for d in documents if not is_archived_path(d.path)]
    query = normalized(question)
    title_matches, slug_matches = [], []
    for doc in docs:
        if is_archive_record(doc):
            continue
        title = normalized(derived_title(doc.body) or str(doc.frontmatter.get("title", "")))
        slug = normalized(str(doc.frontmatter.get("slug", "")))
        def mentioned(name):
            return len(name) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", query)
        if mentioned(title):
            title_matches.append((len(title), doc))
        elif mentioned(slug):
            slug_matches.append((len(slug), doc))
    # Related evolution/decision pages can share a slug. A title identity outranks that
    # organizational key; duplicate title identities still require broader retrieval.
    matches = title_matches or slug_matches
    if not matches:
        return None
    # Multiple subjects, including comparisons, need broader retrieval rather than a
    # single-subject first answer. Do not let index ranking break an identity tie.
    if len(matches) != 1:
        return []
    doc = matches[0][1]
    resolver = CanonicalProvenance(docs)
    rows = []
    for claim in project_document_claims(doc):
        if claim.labels not in (("overview", "definition"), ("overview", "summary")):
            continue
        provenance = resolver.resolve(doc.path, str(claim.anchor))
        if not provenance.citations or provenance.missing_anchors or provenance.ambiguous_anchors:
            continue
        rows.append(RetrievedClaim(claim.anchor, doc.path, claim.section_path, claim.text,
                                  provenance.citations, paths=("canonical",), labels=claim.labels))
    return sorted(rows, key=lambda r: r.labels[-1] != "definition")


def first_candidates(evidence: FastEvidence, *, max_bytes: int = 300) -> list[tuple[str, str]]:
    """Keep complete short records with source addresses. Never cut a qualification away."""
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for claim in evidence.used_claims:
        if not claim.citations or {"superseded", "archived"}.intersection(claim.labels):
            continue
        rows.append((speakable(claim.text), f"{claim.document_path}#{claim.anchor}"))
    for window in evidence.used_windows:
        rows.append((speakable(window.text), f"{window.source_id} ¶{window.block_start}-{window.block_end}"))
    out = []
    for text, locator in rows:
        if not text or text in seen or len(text.encode("utf-8")) > max_bytes:
            continue
        seen.add(text)
        out.append((text, locator))
    return out[:8]


async def first_finding(model, question: str, evidence: FastEvidence, *, zone: str = "UTC", callbacks=None, trace_metadata=None) -> FirstFinding:
    candidates = first_candidates(evidence)
    complete = first_candidates(evidence, max_bytes=6000)
    summarize = any(len(text.encode("utf-8")) > 300 for text, _ in complete)
    if summarize:
        # Keep whole records, bounded in aggregate. Long records need a brief answer,
        # not silent rejection or a substring that can drop a qualification.
        candidates = complete
    contexts = {
        f"{claim.document_path}#{claim.anchor}": render_candidate_context(claim, citations=False)
        for claim in evidence.used_claims
    }
    contexts.update({
        f"{window.source_id} ¶{window.block_start}-{window.block_end}":
            render_candidate_context(window, citations=False)
        for window in evidence.used_windows
    })
    # The early answer needs the same lookup scope and source clocks as the broad
    # selector. A historical record without its date must not become "this week".
    # Bound the entire card, retaining records and their qualifications whole.
    bounded, rendered = [], []
    size = 0
    for text, locator in candidates:
        card = f"{len(bounded)}: [{locator}]\n{contexts[locator]}\n{text}"
        if size + len(card) + 1 > 4000:
            continue
        bounded.append((text, locator))
        rendered.append(card)
        size += len(card) + 1
    candidates = bounded
    if not candidates:
        return FirstFinding()
    result = await model.with_structured_output(FirstSummary if summarize else FirstChoice, include_raw=True).ainvoke(
        [SystemMessage(content=prompt("call.progressive.summarize" if summarize else "call.progressive.pick")),
         HumanMessage(content=prompt("call.progressive.pick_input",
             question=prompt("recall.retrieval.question_context", question=question,
                             as_of=evidence.as_of.isoformat(), zone=zone),
             candidates="\n".join(rendered)))],
        config=invoke_config("call.first", callbacks, trace_metadata),
    )
    parsed, usage = unpack(result)
    if not isinstance(parsed, FirstSummary if summarize else FirstChoice) or not 0 <= parsed.index < len(candidates):
        return FirstFinding(usage=usage)
    text, locator = candidates[parsed.index]
    if summarize:
        text = speakable(parsed.summary).strip()
        if not text:
            return FirstFinding(usage=usage)
    return FirstFinding(text=prompt("call.progressive.first", fact=text), usage=usage, locator=locator)


def unpack(result) -> tuple[object, dict[str, int]]:
    if not isinstance(result, dict):
        return result, zero_usage()
    raw = result.get("raw")
    return result.get("parsed"), extract_usage(raw) if isinstance(raw, BaseMessage) else zero_usage()


async def refine(model, evidence: FastEvidence, preliminary: str, *, callbacks=None, trace_metadata=None) -> RefinedAnswer:
    # The earlier result is context, not evidence. Only the new retrieval's addresses can
    # support the final answer; a narrow finding cannot validate itself through repetition.
    content = evidence.content
    previous = prompt("call.progressive.previous", text=preliminary or prompt("call.ask.none"))
    human = content + "\n\n" + previous if isinstance(content, str) else [*content, {"type": "text", "text": previous}]
    allowed_text = content if isinstance(content, str) else "\n".join(str(p.get("text", "")) for p in content)
    manifest = evidence.manifest or evidence_manifest(
        claims=evidence.used_claims, windows=evidence.used_windows,
        episode_summaries=evidence.used_episode_summaries,
        component_evidence=evidence.used_component_evidence,
    )
    addresses = {parse_span_ref(item.ref) for item in manifest}
    # A marker copied into the question or conversation context is not retrieved evidence.
    allowed = {ref for ref in iter_answer_citations(allowed_text)
               if (evidence.handles.get(ref[0]), ref[1], ref[2]) in addresses}
    choices = sorted({f"[cite: {sid}]" for sid, _, _ in allowed})
    choices.extend(f"[cite: {sid} ¶{start}-{end}]" for sid, start, end in sorted(allowed))
    if not choices:
        text = prompt("call.progressive.unresolved" if preliminary else "call.progressive.empty")
        return RefinedAnswer(text, text, "unresolved", zero_usage())
    # Provider-side structured output offers only addresses admitted by this retrieval.
    # The post-check still rejects malformed output from providers ignoring the schema.
    unit_schema = create_model("GroundedRefinementUnit", __base__=RefinementUnit,
        citations=(list[Literal[tuple(choices)]], ...))
    schema = create_model("GroundedIncrementalDecision", __base__=IncrementalDecision,
        units=(list[unit_schema], ...))
    result = await model.with_structured_output(schema, include_raw=True).ainvoke(
        [SystemMessage(content=evidence.system + "\n\n" + prompt("call.progressive.refine")),
         HumanMessage(content=human)],
        config=invoke_config("call.refine", callbacks, trace_metadata),
    )
    parsed, usage = unpack(result)
    if isinstance(parsed, IncrementalDecision):
        if parsed.relation == "unresolved":
            text = prompt("call.progressive.unresolved" if preliminary else "call.progressive.empty")
            return RefinedAnswer(text, text, "unresolved", usage)
        if not parsed.units:
            raise ValueError("unsupported_refinement")
        full, updates = [], []
        for unit in parsed.units:
            if not unit.text.strip() or not unit.citations or any(c not in choices for c in unit.citations):
                raise ValueError("invalid_refinement_citations")
            # One authored sentence feeds both displays; voice selects units, never rewrites them.
            text = speakable(unit.text).strip()
            full.append(text + " " + " ".join(unit.citations))
            if not preliminary or unit.change != "retained":
                updates.append((unit.change, text))
        speech = " ".join(text for _, text in updates)
        if speech and preliminary:
            relation = "correct" if any(change == "correction" for change, _ in updates) else "extend"
            speech = prompt(f"call.progressive.{relation}", text=speech)
        return RefinedAnswer(" ".join(full), speech, parsed.relation, usage)
    if not isinstance(parsed, RefinementDecision):
        raise ValueError("invalid_refinement")
    # Spoken recall also asks for source-only handles. Bind those to the exact spans
    # actually shown for that source; never invent a range or trust a handle in the question.
    citations: list[str] = []
    for marker in parsed.citations:
        source_only = re.fullmatch(r"\[cite:\s*(s\d+)\s*\]", marker.strip())
        spans = sorted(ref for ref in allowed if source_only and ref[0] == source_only[1])
        if source_only and spans:
            citations.extend(f"[cite: {sid} ¶{start}-{end}]" for sid, start, end in spans)
        else:
            citations.append(marker)
    citations = list(dict.fromkeys(citations))
    refs = [parse_citation_markers(marker) for marker in citations]
    if any(not ref or any(r not in allowed or r[0] not in evidence.handles for r in ref) for ref in refs):
        raise ValueError("invalid_refinement_citations")
    if parsed.relation == "unresolved":
        text = prompt("call.progressive.unresolved" if preliminary else "call.progressive.empty")
        return RefinedAnswer(text, text, "unresolved", usage)
    if not refs or not parsed.answer.strip():
        raise ValueError("unsupported_refinement")
    answer = speakable(parsed.answer) + " " + " ".join(citations)
    if not preliminary:
        speech = speakable(parsed.answer)
    elif parsed.relation == "confirm":
        speech = prompt("call.progressive.confirm")
    else:
        # Reuse the one admitted factual answer instead of generating a second paraphrase
        # that can contradict the card or misquote the earlier subset as a total.
        prefix = "correct" if parsed.relation in {"correct", "answer"} else "extend"
        speech = prompt(f"call.progressive.{prefix}", text=speakable(parsed.answer))
    return RefinedAnswer(answer, speech, parsed.relation, usage)
