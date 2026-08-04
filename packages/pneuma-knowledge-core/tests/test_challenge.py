"""Post-compile coverage challenge (compile/challenge.py): blind generation, reflection.

Fully keyless — a fake model whose `.with_structured_output(...)` returns fixed objects
and records every invoke, mirroring test_semantic_chunking. Pins the stage's shape: the
generator is blind (no compiled claims in its prompt), the system message is byte-stable
per skill (I5), the reflection sees claims verbatim, and the compensation guidance is a
catalog-rendered string.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pneuma_knowledge_core.compile.challenge import (
    ChallengeGap,
    ChallengeQuestions,
    ChallengeReflection,
    generate_challenge_questions,
    judge_challenge_gaps,
    render_compensation_guidance,
    render_material,
)
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.skill import SkillVersion


def _source(*texts: str, sid: str = "s-ch-1", title: str = "meeting notes") -> NormalizedSource:
    raw = RawSource(
        source_id=SourceId(sid),
        user_id=UserId("u-ch"),
        kind="document",
        title=title,
        mime="text/plain",
        checksum="x",
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        meta={"title": title},
    )
    blocks = [NormalizedBlock(index=i, text=t) for i, t in enumerate(texts)]
    return NormalizedSource(raw=raw, blocks=blocks, structure=StructureMap(sections=[]))


def _skill() -> SkillVersion:
    return SkillVersion.from_parts(
        skill_id="t",
        version="t1",
        instructions="Record decisions and handovers.",
        path_templates=["notes/{slug}.md"],
    )


class _FakeStructured:
    def __init__(self, result) -> None:
        self._result = result
        self.calls: list[tuple] = []

    async def ainvoke(self, messages, config=None):
        self.calls.append((messages, config))
        return self._result


class _FakeModel:
    def __init__(self, result) -> None:
        self.structured = _FakeStructured(result)
        self.schemas: list[type] = []

    def with_structured_output(self, schema, *, include_raw=False):
        self.schemas.append(schema)
        self.include_raw = include_raw
        return self.structured


async def test_generation_is_blind_and_byte_stable():
    model = _FakeModel(ChallengeQuestions(questions=["  Who took over QA?  ", ""], exhausted=False))
    source = _source("Alice hands QA to Bob on Friday.")
    result = await generate_challenge_questions(
        model=model, skill=_skill(), sources=[source], asked=["When did QA start?"]
    )
    # Post-processing: trimmed, empties dropped.
    assert result.questions == ["Who took over QA?"]
    assert model.schemas == [ChallengeQuestions]
    (messages, config), = model.structured.calls
    system, human = messages
    # The contract rides the system message; two calls render it byte-identically (I5).
    assert "Record decisions and handovers." in system.content
    model2 = _FakeModel(ChallengeQuestions())
    await generate_challenge_questions(model=model2, skill=_skill(), sources=[source])
    assert model2.structured.calls[0][0][0].content == system.content
    # Blindness: the material and the asked list ride the human message; no claims enter.
    assert "Alice hands QA to Bob" in human.content
    assert "When did QA start?" in human.content
    assert "claim" not in human.content.lower()
    assert config["run_name"] == "compile.challenge.questions"


async def test_generation_caps_questions_at_the_budget():
    many = ChallengeQuestions(questions=[f"q{i}" for i in range(10)])
    model = _FakeModel(many)
    result = await generate_challenge_questions(
        model=model, skill=_skill(), sources=[_source("text")], max_questions=3
    )
    assert result.questions == ["q0", "q1", "q2"]


async def test_reflection_sees_claims_verbatim_and_absence_explicitly():
    reflection = ChallengeReflection(
        gaps=[ChallengeGap(question="Who took over QA?", missing_fact="Bob took QA over on Friday.")],
        exhausted=True,
    )
    model = _FakeModel(reflection)
    result = await judge_challenge_gaps(
        model=model,
        sources=[_source("Alice hands QA to Bob on Friday.")],
        probes=[
            ("Who took over QA?", []),
            ("What was decided?", ["【firm】Ship on Friday."]),
        ],
    )
    assert result is reflection
    (messages, config), = model.structured.calls
    human = messages[1].content
    assert "(no recorded claim found)" in human
    assert "【firm】Ship on Friday." in human
    assert "Alice hands QA to Bob" in human  # material is the ground truth
    assert config["run_name"] == "compile.challenge.reflect"


async def test_parsed_none_degrades_to_exhausted_instead_of_dying():
    """2026-08-05: a prose reply (include_raw envelope with parsed=None) killed a live
    500-day build via `'NoneType' object is not iterable`. Both passes must degrade to
    an empty, exhausted result — the audit skips a round, the job survives."""
    source = _source("Alice hands QA to Bob on Friday.")
    model = _FakeModel({"raw": object(), "parsed": None, "parsing_error": None})
    result = await generate_challenge_questions(model=model, skill=_skill(), sources=[source])
    assert result.questions == [] and result.exhausted is True
    assert model.include_raw is True

    model2 = _FakeModel({"raw": object(), "parsed": None, "parsing_error": None})
    reflection = await judge_challenge_gaps(
        model=model2, sources=[source], probes=[("Who took over QA?", [])]
    )
    assert reflection.gaps == [] and reflection.exhausted is True


def test_material_render_is_addressed_and_bounded():
    source = _source("first block", "second block")
    text = render_material([source])
    assert "¶0: first block" in text and "¶1: second block" in text
    assert "s-ch-1" in text and "meeting notes" in text
    # A pathological source truncates with an explicit note instead of silently.
    big = _source(*["x" * 5_000 for _ in range(10)])
    rendered = render_material([big])
    assert "blocks truncated" in rendered


def test_compensation_guidance_renders_all_gaps_through_the_catalog():
    gaps = [
        ChallengeGap(question="Q1", missing_fact="F1"),
        ChallengeGap(question="Q2", missing_fact="F2"),
    ]
    text = render_compensation_guidance(gaps)
    assert "Q1" in text and "F1" in text and "Q2" in text and "F2" in text
    assert "coverage audit" in text
    assert "with citations" in text  # the floor stays with the gate
