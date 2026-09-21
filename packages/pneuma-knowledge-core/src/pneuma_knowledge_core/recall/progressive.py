"""A partial lookup followed by a grounded subtask result for the conversational agent.

The lookup owns evidence, scope and unresolved aspects. It does not see dialogue history or
decide what the voice has already said. Citation admission checks addresses, not entailment.
"""
from __future__ import annotations

import re
import unicodedata

from dataclasses import dataclass, field
from typing import Annotated, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, create_model

from ..prompts import prompt
from ..domain.consultation import parse_span_ref
from .call import speakable
from .citation_alias import iter_answer_citations, parse_citation_markers
from .evidence_context import render_candidate_context
from .fast import RetrievedClaim, FastEvidence, evidence_manifest, extract_usage, invoke_config, zero_usage


class FirstDecision(BaseModel):
    disposition: Literal["ready", "needs_review", "no_answer"]
    index: int = Field(default=-1, description="Index of the record supporting an early answer")
    subject: Literal["unambiguous", "ambiguous", "unknown"]
    support: Literal["direct", "indirect", "none"]
    record_kind: Literal["subject_fact", "test_or_usage_instruction", "question_or_hypothesis", "other"]
    quote: str = Field(default="", max_length=300,
        description="Exact complete sentence(s) from the selected record, including necessary qualifications; no rewriting")


class KnowledgeFact(BaseModel):
    text: str = Field(max_length=600, description="A self-contained factual result of the lookup, preserving its qualifiers")
    citations: list[str]


class KnowledgeDecision(BaseModel):
    status: Literal["answered", "partial", "unresolved"]
    facts: list[KnowledgeFact] = Field(max_length=6, description="Supported answers to the standalone subtask, not a script for the user")
    scope: str = Field(max_length=300, description="What the supplied evidence establishes about subject, time and coverage; no unverified library-wide completeness")
    limitations: list[Annotated[str, Field(max_length=200)]] = Field(max_length=4, description="Requested aspects still unestablished; no dialogue instructions or suggested utterances")


@dataclass(frozen=True)
class FirstFinding:
    text: str = ""
    usage: dict[str, int] = field(default_factory=zero_usage)
    locator: str = ""
    disposition: Literal["ready", "needs_review", "no_answer"] = "no_answer"
    reason: str = "no_candidates"


@dataclass(frozen=True)
class RefinedAnswer:
    answer: str
    result_text: str
    status: Literal["answered", "partial", "unresolved"]
    scope: str
    limitations: tuple[str, ...]
    facts: tuple[KnowledgeFact, ...]
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
    # Keep context whole for the admission decision; only an exact, bounded passage
    # can leave this phase. A paraphrase cannot turn a test question into a definition.
    candidates = first_candidates(evidence, max_bytes=6000)
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
    result = await model.with_structured_output(FirstDecision, include_raw=True).ainvoke(
        [SystemMessage(content=prompt("call.progressive.pick")),
         HumanMessage(content=prompt("call.progressive.pick_input",
             question=prompt("recall.retrieval.question_context", question=question,
                             as_of=evidence.as_of.isoformat(), zone=zone),
             candidates="\n".join(rendered)))],
        config=invoke_config("call.first", callbacks, trace_metadata),
    )
    parsed, usage = unpack(result)
    if not isinstance(parsed, FirstDecision):
        return FirstFinding(usage=usage, disposition="needs_review", reason="invalid_decision")
    if parsed.disposition != "ready":
        return FirstFinding(usage=usage, disposition=parsed.disposition, reason="not_ready")
    if (parsed.subject != "unambiguous" or parsed.support != "direct"
            or parsed.record_kind != "subject_fact"):
        return FirstFinding(usage=usage, disposition="needs_review", reason="admission_failed")
    if not 0 <= parsed.index < len(candidates):
        return FirstFinding(usage=usage, disposition="needs_review", reason="invalid_index")
    text, locator = candidates[parsed.index]
    quote = parsed.quote.strip()
    # Verbatim admission prevents novel subject/predicate constructions. Complete
    # sentence boundaries prevent clipping a clause off its negation or condition.
    starts = [match.start() for match in re.finditer(re.escape(quote), text)] if quote else []
    def bounded(start: int) -> bool:
        before, after = text[:start].rstrip(), text[start + len(quote):].lstrip()
        return ((not before or before[-1] in ".!?。！？\n")
                and (not after or quote[-1] in ".!?。！？"))
    if not starts or not any(bounded(start) for start in starts):
        return FirstFinding(usage=usage, disposition="needs_review", reason="invalid_quote")
    return FirstFinding(text=quote, usage=usage, locator=locator,
                        disposition="ready", reason="direct_record")


def unpack(result) -> tuple[object, dict[str, int]]:
    if not isinstance(result, dict):
        return result, zero_usage()
    raw = result.get("raw")
    return result.get("parsed"), extract_usage(raw) if isinstance(raw, BaseMessage) else zero_usage()


async def refine(model, evidence: FastEvidence, *, callbacks=None, trace_metadata=None) -> RefinedAnswer:
    """Resolve the standalone lookup from its evidence, without conversation or playback state."""
    content = evidence.content
    allowed_text = content if isinstance(content, str) else "\n".join(str(p.get("text", "")) for p in content)
    manifest = evidence.manifest or evidence_manifest(
        claims=evidence.used_claims, windows=evidence.used_windows,
        episode_summaries=evidence.used_episode_summaries,
        component_evidence=evidence.used_component_evidence,
    )
    addresses = {parse_span_ref(item.ref) for item in manifest}
    allowed = {ref for ref in iter_answer_citations(allowed_text)
               if (evidence.handles.get(ref[0]), ref[1], ref[2]) in addresses}
    choices = sorted({f"[cite: {sid}]" for sid, _, _ in allowed})
    choices.extend(f"[cite: {sid} ¶{start}-{end}]" for sid, start, end in sorted(allowed))
    if not choices:
        text = prompt("call.progressive.empty")
        return RefinedAnswer(text, text, "unresolved", "", (text,), (), zero_usage())
    fact_schema = create_model("GroundedKnowledgeFact", __base__=KnowledgeFact,
        citations=(list[Literal[tuple(choices)]], ...))
    schema = create_model("GroundedKnowledgeDecision", __base__=KnowledgeDecision,
        facts=(list[fact_schema], Field(max_length=6)))
    result = await model.with_structured_output(schema, include_raw=True).ainvoke(
        [SystemMessage(content=evidence.system + "\n\n" + prompt("call.progressive.refine")),
         HumanMessage(content=content)],
        config=invoke_config("call.refine", callbacks, trace_metadata),
    )
    parsed, usage = unpack(result)
    if not isinstance(parsed, KnowledgeDecision):
        raise ValueError("invalid_lookup_result")
    if parsed.status == "unresolved":
        # An unresolved result cannot smuggle speculative facts through the empty-result path.
        text = prompt("call.progressive.empty")
        return RefinedAnswer(text, text, "unresolved", parsed.scope,
                             tuple(parsed.limitations) or (text,), (), usage)
    if not parsed.facts:
        raise ValueError("unsupported_refinement")
    facts, full = [], []
    for fact in parsed.facts:
        if not fact.text.strip() or not fact.citations:
            raise ValueError("invalid_refinement_citations")
        citations = []
        for marker in fact.citations:
            if marker not in choices:
                raise ValueError("invalid_refinement_citations")
            source_only = re.fullmatch(r"\[cite:\s*(s\d+)\]", marker.strip())
            spans = sorted(ref for ref in allowed if source_only and ref[0] == source_only[1])
            if spans:
                citations.extend(f"[cite: {sid} ¶{start}-{end}]" for sid, start, end in spans)
            else:
                citations.append(marker)
        citations = list(dict.fromkeys(citations))
        refs = [parse_citation_markers(marker) for marker in citations]
        if any(not ref or any(r not in allowed or r[0] not in evidence.handles for r in ref) for ref in refs):
            raise ValueError("invalid_refinement_citations")
        text = speakable(fact.text).strip()
        if not text:
            raise ValueError("unsupported_refinement")
        facts.append(KnowledgeFact(text=text, citations=citations))
        full.append(text + " " + " ".join(citations))
    return RefinedAnswer(" ".join(full), " ".join(fact.text for fact in facts),
                         parsed.status, parsed.scope, tuple(parsed.limitations), tuple(facts), usage)
