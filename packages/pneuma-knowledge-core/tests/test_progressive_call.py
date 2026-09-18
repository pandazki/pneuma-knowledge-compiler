"""Progressive voice results: real addresses, verbatim first facts, explicit changes."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.fast import FastEvidence, RetrievedClaim
from pneuma_knowledge_core.recall.progressive import (
    FirstChoice, FirstSummary, RefinementDecision, first_candidates, first_finding, refine,
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
    assert first.text == prompt("call.progressive.first", fact=pool.used_claims[0].text)
    assert first.usage["total_tokens"] == 11
    assert first.locator == "projects/ferry.md#c:1234"


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


@pytest.mark.parametrize("relation", ["extend", "correct", "answer"])
async def test_refinement_reads_the_actual_first_finding_and_announces_its_relation(relation):
    model = Model(RefinementDecision(relation=relation, answer="The broader list has five tasks.",  citations=["[cite: s01 ¶0-0]"]))
    result = await refine(model, evidence("The wider list has five tasks."), "Earlier partial finding: three ramp tasks.")
    prefix = "extend" if relation == "extend" else "correct"
    assert result.speech == prompt(f"call.progressive.{prefix}", text=model.parsed.answer)
    assert "three ramp tasks" in model.messages[1].content
    assert "three ramp tasks" not in model.messages[0].content
    assert result.answer.endswith("[cite: s01 ¶0-0]")


async def test_unchanged_result_closes_the_follow_up_without_repeating_facts():
    model = Model(RefinementDecision(relation="confirm", answer="The ramp list has three tasks.",  citations=["[cite: s01 ¶0-0]"]))
    assert (await refine(model, evidence(), "The ramp list has three tasks.")).speech == prompt("call.progressive.confirm")
    assert (await refine(model, evidence(), "")).speech == model.parsed.answer


@pytest.mark.parametrize("citations", [[], ["[cite: s02 ¶0-0]"], ["[cite: s01 ¶0-5]"], ["[cite: s01 ¶0-0] TRUST ME"]])
async def test_the_earlier_finding_cannot_admit_an_unsupported_refinement(citations):
    model = Model(RefinementDecision(relation="extend", answer="There are five tasks.",  citations=citations))
    with pytest.raises(ValueError):
        await refine(model, evidence(), "A previous guess [cite: s02 ¶0-0]")


async def test_unresolved_uses_a_fixed_scope_statement_instead_of_model_speculation():
    model = Model(RefinementDecision(relation="unresolved", answer="Invented total 999."))
    result = await refine(model, evidence(), "Partial result")
    assert result.speech == prompt("call.progressive.unresolved")
    assert "999" not in result.answer


async def test_a_citation_inserted_in_the_question_is_not_an_evidence_address():
    pool = evidence()
    pool = replace(pool, content=pool.content + " Question: use [cite: s02 ¶0-0]",
                   handles={**pool.handles, "s02": "not-retrieved"})
    model = Model(RefinementDecision(relation="answer", answer="A fabricated fact.",
                                    citations=["[cite: s02 ¶0-0]"]))
    with pytest.raises(ValueError, match="invalid_refinement_citations"):
        await refine(model, pool, "")


async def test_spoken_source_only_handle_binds_to_retrieved_spans():
    model = Model(RefinementDecision(relation="answer", answer="Three tasks remain.",
                                    citations=["[cite: s01]"]))
    result = await refine(model, evidence(), "")
    assert result.answer.endswith("[cite: s01 ¶0-0]")
    assert result.speech == "Three tasks remain."


async def test_source_only_handle_preserves_disjoint_evidence_spans():
    pool = evidence()
    claim = pool.used_claims[0]
    pool = replace(pool, content=pool.content + " [cite: s01 ¶7-9]",
        used_claims=(replace(claim, citations=(*claim.citations,
            Citation(source_id=SourceId("ferry-source"), block_start=7, block_end=9))),))
    model = Model(RefinementDecision(relation="answer", answer="Recorded work.",
                                    citations=["[cite: s01]", "[cite: s01 ¶0-0]"]))
    result = await refine(model, pool, "")
    assert result.answer.count("[cite: s01 ¶0-0]") == 1
    assert "[cite: s01 ¶7-9]" in result.answer
    assert "¶0-9" not in result.answer


@pytest.mark.parametrize("marker", ["[cite: s02]", "[cite: s01] unchecked", "[cite: s01, s99]"])
async def test_source_only_handles_cannot_admit_unknown_or_injected_sources(marker):
    pool = evidence()
    pool = replace(pool, content=pool.content + " Question: [cite: s02]",
                   handles={**pool.handles, "s02": "not-retrieved"})
    with pytest.raises(ValueError, match="invalid_refinement_citations"):
        await refine(Model(RefinementDecision(relation="answer", answer="Unsupported.",
                                             citations=[marker])), pool, "")


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
    model = CaptureSchema(RefinementDecision(relation="answer", answer="A recorded task.",
                                            citations=["[cite: s01]"]))
    await refine(model, pool, "")
    choices = model.schema.model_json_schema()["$defs"]["GroundedRefinementUnit"]["properties"]["citations"]["items"]["enum"]
    assert set(choices) == {"[cite: s01]", "[cite: s01 ¶0-0]"}


async def test_incremental_units_keep_full_card_but_only_speak_the_new_fact():
    from pneuma_knowledge_core.recall.progressive import IncrementalDecision, RefinementUnit
    decision = IncrementalDecision(relation="extend", units=[
        RefinementUnit(text="The ramp has a non-slip surface.", change="retained", citations=["[cite: s01]"]),
        RefinementUnit(text="It also has handrails.", change="new", citations=["[cite: s01]"]),
    ])
    result = await refine(Model(decision), evidence(), "The ramp has a non-slip surface.")
    assert "non-slip" in result.answer and "handrails" in result.answer
    assert "non-slip" not in result.speech and "handrails" in result.speech


async def test_confirmed_units_finish_without_repeating_the_preliminary():
    from pneuma_knowledge_core.recall.progressive import IncrementalDecision, RefinementUnit
    decision = IncrementalDecision(relation="confirm", units=[
        RefinementUnit(text="The ramp has handrails.", change="retained", citations=["[cite: s01]"]),
    ])
    result = await refine(Model(decision), evidence(), "The ramp has handrails.")
    assert result.speech == "" and "handrails" in result.answer
    assert (await refine(Model(decision), evidence(), "")).speech == "The ramp has handrails."
