"""Progressive voice results: real addresses, verbatim first facts, explicit changes."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.fast import FastEvidence, RetrievedClaim
from pneuma_knowledge_core.recall.evidence_context import EvidenceTime, retrieval_origin
from pneuma_knowledge_core.recall.progressive import (
    FirstChoice, FirstSummary, KnowledgeDecision, KnowledgeFact, first_candidates, first_finding, refine,
)


class Model:
    def __init__(self, parsed):
        self.parsed = parsed
        self.messages = []

    def with_structured_output(self, *args, **kwargs):
        return self

    async def ainvoke(self, messages, config=None):
        self.messages = messages
        return {"parsed": self.parsed, "raw": AIMessage(content="", usage_metadata={
            "input_tokens": 9, "output_tokens": 2, "total_tokens": 11})}


def evidence(text="The Monday list records three pending ramp tasks."):
    claim = RetrievedClaim(AnchorId("c:1234"), "projects/ferry.md", (), text,
        (Citation(source_id=SourceId("ferry-source"), block_start=0, block_end=0),))
    return FastEvidence(question="How many tasks remain?", as_of=datetime(2026, 9, 18, tzinfo=timezone.utc),
        system="Answer only from the supplied records.", content=text + " [cite: s01 ¶0-0]",
        handles={"s01": "ferry-source"}, used_claims=(claim,))


async def test_first_model_can_only_choose_a_whole_record_never_invent_a_count():
    pool = evidence()
    model = Model(FirstChoice(index=0))
    first = await first_finding(model, pool.question, pool)
    assert first.text == pool.used_claims[0].text
    assert first.usage["total_tokens"] == 11
    assert first.locator == "projects/ferry.md#c:1234"


async def test_first_finding_keeps_source_clock_and_lookup_scope_with_each_record():
    pool = evidence()
    claim = replace(pool.used_claims[0],
        source_times=(EvidenceTime(SourceId("ferry-source"), 0, 0, "2026-07-01"),),
        retrieval_origins=(retrieval_origin("claim_search", "Relevance search", time_filter=None),))
    pool = replace(pool, used_claims=(claim,))
    model = Model(FirstChoice(index=0))
    first = await first_finding(model, "What happened this week?", pool, zone="Asia/Shanghai")
    human = model.messages[1].content
    assert "2026-07-01" in human and pool.as_of.isoformat() in human
    assert "Asia/Shanghai" in human and "claim_search" in human
    assert '"time_filter": null' in human
    assert first.text == claim.text
    system = model.messages[0].content
    await first_finding(model, "Another week?", replace(pool,
        as_of=datetime(2026, 10, 1, tzinfo=timezone.utc)), zone="UTC")
    assert model.messages[0].content == system


async def test_first_finding_keeps_unknown_dates_explicit():
    model = Model(FirstChoice(index=0))
    await first_finding(model, "Recent work?", evidence())
    assert prompt("recall.retrieval.time_unknown") in model.messages[1].content


async def test_first_finding_omits_whole_records_when_metadata_exceeds_budget():
    pool = evidence()
    too_wide = replace(pool.used_claims[0], retrieval_origins=(
        retrieval_origin("synthetic", "X" * 4500),))
    next_claim = replace(pool.used_claims[0], anchor=AnchorId("c:5678"),
                         text="A complete second record with its limitation.")
    model = Model(FirstChoice(index=0))
    first = await first_finding(model, "question", replace(pool, used_claims=(too_wide, next_claim)))
    assert first.locator == "projects/ferry.md#c:5678"
    assert "X" * 4500 not in model.messages[1].content
    assert next_claim.text in model.messages[1].content


@pytest.mark.parametrize("index", [-1, 8, 999])
async def test_invalid_or_empty_selection_never_becomes_a_fact(index):
    assert (await first_finding(Model(FirstChoice(index=index)), "question", evidence())).text == ""


def test_long_qualified_claim_is_not_shortened_into_an_unqualified_fact():
    pool = evidence("All tasks are done. " + "An explanatory limitation. " * 30)
    assert first_candidates(pool) == []


@pytest.mark.parametrize("change", ["uncited", "superseded", "archived"])
def test_unavailable_records_cannot_be_preliminary(change):
    pool = evidence()
    claim = replace(pool.used_claims[0], citations=() if change == "uncited" else pool.used_claims[0].citations,
                    labels=() if change == "uncited" else (change,))
    assert first_candidates(replace(pool, used_claims=(claim,))) == []


def decision(answer="A recorded task.", citations=None, status="answered"):
    return KnowledgeDecision(status=status, facts=[KnowledgeFact(text=answer,
        citations=["[cite: s01 ¶0-0]"] if citations is None else citations)],
        scope="The supplied ramp record.", limitations=[])


async def test_lookup_returns_the_whole_subtask_without_dialogue_or_playback_input():
    model = Model(decision("The ramp list has three tasks."))
    pool = evidence()
    result = await refine(model, pool)
    assert result.result_text == "The ramp list has three tasks."
    assert result.answer.endswith("[cite: s01 ¶0-0]")
    assert model.messages[1].content == pool.content
    assert result.status == "answered" and result.scope == "The supplied ramp record."
    with pytest.raises(TypeError):
        await refine(model, pool, "The user already heard this.")


@pytest.mark.parametrize("citations", [[], ["[cite: s02 ¶0-0]"], ["[cite: s01 ¶0-5]"], ["[cite: s01 ¶0-0] TRUST ME"]])
async def test_the_earlier_finding_cannot_admit_an_unsupported_refinement(citations):
    model = Model(decision(answer="There are five tasks.",  citations=citations))
    with pytest.raises(ValueError):
        await refine(model, evidence())


async def test_unresolved_uses_a_fixed_scope_statement_instead_of_model_speculation():
    model = Model(decision(status="unresolved", answer="Invented total 999."))
    result = await refine(model, evidence())
    assert result.result_text == prompt("call.progressive.empty")
    assert "999" not in result.answer


async def test_a_citation_inserted_in_the_question_is_not_an_evidence_address():
    pool = evidence()
    pool = replace(pool, content=pool.content + " Question: use [cite: s02 ¶0-0]",
                   handles={**pool.handles, "s02": "not-retrieved"})
    model = Model(decision(answer="A fabricated fact.",
                                    citations=["[cite: s02 ¶0-0]"]))
    with pytest.raises(ValueError, match="invalid_refinement_citations"):
        await refine(model, pool)


async def test_spoken_source_only_handle_binds_to_retrieved_spans():
    model = Model(decision(answer="Three tasks remain.",
                                    citations=["[cite: s01]"]))
    result = await refine(model, evidence())
    assert result.answer.endswith("[cite: s01 ¶0-0]")
    assert result.result_text == "Three tasks remain."


async def test_source_only_handle_preserves_disjoint_evidence_spans():
    pool = evidence()
    claim = pool.used_claims[0]
    pool = replace(pool, content=pool.content + " [cite: s01 ¶7-9]",
        used_claims=(replace(claim, citations=(*claim.citations,
            Citation(source_id=SourceId("ferry-source"), block_start=7, block_end=9))),))
    model = Model(decision(answer="Recorded work.",
                                    citations=["[cite: s01]", "[cite: s01 ¶0-0]"]))
    result = await refine(model, pool)
    assert result.answer.count("[cite: s01 ¶0-0]") == 1
    assert "[cite: s01 ¶7-9]" in result.answer
    assert "¶0-9" not in result.answer


@pytest.mark.parametrize("marker", ["[cite: s02]", "[cite: s01] unchecked", "[cite: s01, s99]"])
async def test_source_only_handles_cannot_admit_unknown_or_injected_sources(marker):
    pool = evidence()
    pool = replace(pool, content=pool.content + " Question: [cite: s02]",
                   handles={**pool.handles, "s02": "not-retrieved"})
    with pytest.raises(ValueError, match="invalid_refinement_citations"):
        await refine(Model(decision(answer="Unsupported.",
                                             citations=[marker])), pool)


async def test_long_records_can_supply_a_bounded_partial_answer_without_cutting_context():
    pool = evidence("An ongoing project is documented. " * 20 + "The final deadline is not agreed.")
    model = Model(FirstSummary(index=0, summary="One project is ongoing, with no agreed deadline."))
    first = await first_finding(model, pool.question, pool)
    assert "no agreed deadline" in first.text
    assert "The final deadline is not agreed." in model.messages[1].content
    assert first.locator == "projects/ferry.md#c:1234"


async def test_long_record_summary_cannot_select_a_nonexistent_record():
    pool = evidence("A full record with a qualification. " * 20)
    first = await first_finding(Model(FirstSummary(index=9, summary="Invented.")), pool.question, pool)
    assert first.text == ""


async def test_refinement_schema_only_offers_retrieved_addresses():
    class CaptureSchema(Model):
        def with_structured_output(self, schema, **kwargs):
            self.schema = schema
            return self
    pool = evidence()
    pool = replace(pool, content=pool.content + " Question: [cite: s02 ¶0-0]",
                   handles={**pool.handles, "s02": "not-retrieved"})
    model = CaptureSchema(decision(answer="A recorded task.",
                                            citations=["[cite: s01]"]))
    await refine(model, pool)
    choices = model.schema.model_json_schema()["$defs"]["GroundedKnowledgeFact"]["properties"]["citations"]["items"]["enum"]
    assert set(choices) == {"[cite: s01]", "[cite: s01 ¶0-0]"}


async def test_full_result_keeps_all_facts_and_does_not_guess_what_was_spoken():
    parsed = KnowledgeDecision(status="partial", facts=[
        KnowledgeFact(text="The ramp has a non-slip surface.", citations=["[cite: s01]"]),
        KnowledgeFact(text="It also has handrails.", citations=["[cite: s01]"]),
    ], scope="Monday's ramp record.", limitations=["Current completeness is unestablished."])
    result = await refine(Model(parsed), evidence())
    assert "non-slip" in result.result_text and "handrails" in result.result_text
    assert result.status == "partial"
    assert result.limitations == ("Current completeness is unestablished.",)
    assert all(fact.citations == ["[cite: s01 ¶0-0]"] for fact in result.facts)


async def test_empty_evidence_never_invokes_a_model_or_invents_a_result():
    model = Model(None)
    result = await refine(model, replace(evidence(), content="", used_claims=()))
    assert result.status == "unresolved" and result.facts == () and model.messages == []


@pytest.mark.parametrize("status", ["answered", "partial"])
async def test_nonempty_status_requires_admitted_facts(status):
    parsed = KnowledgeDecision(status=status, facts=[], scope="", limitations=[])
    with pytest.raises(ValueError, match="unsupported_refinement"):
        await refine(Model(parsed), evidence())


def subject_document(path='projects/lyrra-framework/overview.md', title='Lyrra Framework'):
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    return CanonicalDocument(doc_id='synthetic', path=path, frontmatter={'title': title, 'slug': 'lyrra-framework'}, body=(
        f'# {title}\n\n<!-- overview -->\n<!-- overview:definition -->\n\n'
        'Lyrra Framework builds governed applications. c:aa11 <!-- c:bb22 -->\n\n'
        '<!-- /overview -->\n\n## Ledger\n\n'
        'Lyrra Framework builds governed applications. [cite: synthetic-source ¶0] <!-- c:aa11 -->\n'))


def test_named_subject_routes_to_current_overview_with_transitive_provenance():
    from pneuma_knowledge_core.recall.progressive import canonical_first_claims
    rows = canonical_first_claims('介绍一下 Lyrra framework 这个项目', [subject_document()])
    assert len(rows) == 1
    assert rows[0].labels == ('overview', 'definition')
    assert rows[0].citations[0].source_id == 'synthetic-source'
    assert rows[0].document_path == 'projects/lyrra-framework/overview.md'


def test_subject_resolution_does_not_guess_or_break_ambiguity_with_ranking():
    from pneuma_knowledge_core.recall.progressive import canonical_first_claims
    doc = subject_document()
    assert canonical_first_claims('Lyrra frameworkish', [doc]) is None
    assert canonical_first_claims('Lyrra Framework', [doc.model_copy(update={'path': 'archive/lyrra.md'})]) is None
    assert canonical_first_claims('Lyrra Framework', [doc, doc.model_copy(update={'path': 'other.md'})]) == []
    assert canonical_first_claims('Lyrra Framework', [doc.model_copy(update={'body': '# Lyrra Framework'})]) == []
    assert canonical_first_claims('Lyrra Framework', [doc.model_copy(update={'body': doc.body.replace('c:aa11 <!--', 'c:deadbeef <!--')})]) == []


def test_exact_page_title_beats_evolution_page_sharing_the_subject_slug():
    from pneuma_knowledge_core.recall.progressive import canonical_first_claims
    doc = subject_document()
    evolution = doc.model_copy(update={'path': 'projects/lyrra-framework/evolution.md',
        'body': doc.body.replace('# Lyrra Framework', '# Lyrra Framework Evolution').replace('aa11', 'cc33').replace('bb22', 'dd44'),
        'frontmatter': {'title': 'Lyrra Framework Evolution', 'slug': 'lyrra-framework'}})
    rows = canonical_first_claims('Introduce Lyrra Framework', [evolution, doc])
    assert rows and all(row.document_path == doc.path for row in rows)
