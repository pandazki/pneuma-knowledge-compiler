"""Post-compile coverage audit: blind question generation + claims-face reflection.

An optional stage that mechanizes the acceptance loop's "ask real questions" step
(docs/guides/compile-contract.md §8) right after a compile:

1. **Blind question generation.** A model sees the raw source material and the compile
   contract — deliberately NOT the compiled result — and asks the questions the
   material's implied uses would need answered. Blindness is the point: a generator that
   sees its own output tends to conclude everything is covered.
2. **Claims-face reflection.** For each question, the closest recorded claims are
   retrieved from the library's claim face and judged against the material as ground
   truth. A gap exists only when the material supports an answer AND the recorded claims
   do not carry the needed fact — which separates "not recorded" (a compile problem, and
   the only thing this audit reports) from "not retrieved" (a recall problem, out of
   scope here).

The audit only POINTS. Anything it finds flows into an ordinary compensation compile
whose writes pass the same citation gate as any other — the no-fabrication floor stays
mechanical; this stage adds judgement about coverage, nothing more.

Middleware-free like the rest of core: models enter as `BaseChatModel`, claim retrieval
results enter as plain strings; the service owns the ports and the job orchestration.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..domain.source import NormalizedSource
from ..prompts import prompt
from ..recall.fast import invoke_config
from ..skill.version import SkillVersion

# Per-source cap on the material rendered into a prompt. Challenge rounds read the same
# material the compile just read; the cap only bounds pathological single sources.
MATERIAL_CHAR_BUDGET = 24_000


class ChallengeQuestions(BaseModel):
    """The blind generator's output: question angles worth probing, or a stop."""

    questions: list[str] = Field(default_factory=list)
    # True when, beyond what was already asked, no valuable angle remains.
    exhausted: bool = False


class ChallengeGap(BaseModel):
    """One confirmed coverage gap: the probing question and the concrete missing fact."""

    question: str
    missing_fact: str


class ChallengeReflection(BaseModel):
    gaps: list[ChallengeGap] = Field(default_factory=list)
    # True when no valuable question angles remain beyond what is already recorded.
    exhausted: bool = False


def render_material(sources: list[NormalizedSource]) -> str:
    """The sources as numbered verbatim blocks — the same addressing the compile saw."""
    parts: list[str] = []
    for source in sources:
        title = str(source.raw.meta.get("title") or source.raw.source_id)
        lines = [f"### source {source.raw.source_id} — {title}"]
        used = 0
        for block in source.blocks:
            text = block.text
            if used + len(text) > MATERIAL_CHAR_BUDGET:
                lines.append(f"…({len(source.blocks) - block.index} blocks truncated)")
                break
            lines.append(f"¶{block.index}: {text}")
            used += len(text)
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def generate_challenge_questions(
    *,
    model: BaseChatModel,
    skill: SkillVersion,
    sources: list[NormalizedSource],
    max_questions: int = 6,
    asked: list[str] | None = None,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> ChallengeQuestions:
    """Blind generation: material + contract in, question angles out.

    The system message is byte-stable per skill version (I5); the material and the
    already-asked list ride the human message.
    """
    system = SystemMessage(
        prompt("compile.challenge.questions_system", contract=skill.instructions)
    )
    sections = [render_material(sources)]
    if asked:
        joined = "\n".join(f"- {q}" for q in asked)
        sections.append(f"Already asked (do not repeat these angles):\n{joined}")
    sections.append(f"Propose at most {max_questions} questions.")
    human = HumanMessage("\n\n".join(sections))
    # include_raw so a prose reply / missing tool call degrades to "no questions this
    # round" (the challenge is a best-effort audit — one malformed model reply must
    # never kill the job; observed live as a `'NoneType' object is not iterable` death).
    structured = model.with_structured_output(ChallengeQuestions, include_raw=True)
    envelope = await structured.ainvoke(
        [system, human],
        config=invoke_config("compile.challenge.questions", callbacks, trace_metadata),
    )
    result = envelope.get("parsed") if isinstance(envelope, dict) else envelope
    if result is None:
        return ChallengeQuestions(questions=[], exhausted=True)
    result.questions = [q.strip() for q in result.questions or [] if q.strip()][:max_questions]
    return result


async def judge_challenge_gaps(
    *,
    model: BaseChatModel,
    sources: list[NormalizedSource],
    probes: list[tuple[str, list[str]]],
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> ChallengeReflection:
    """Reflection: per question, the closest recorded claims vs the material as truth.

    `probes` is [(question, claim_texts_retrieved_for_it)]. Claims arrive as plain
    strings so the caller decides the retrieval face; an empty list renders as an
    explicit "no recorded claim found".
    """
    system = SystemMessage(prompt("compile.challenge.reflect_system"))
    lines: list[str] = [render_material(sources), "## Questions and the recorded claims closest to each"]
    for question, claims in probes:
        lines.append(f"Q: {question}")
        if claims:
            lines.extend(f"  claim: {text}" for text in claims)
        else:
            lines.append("  (no recorded claim found)")
    human = HumanMessage("\n\n".join(lines))
    # Same soft-degrade shape as the question pass: parsed None → "no gaps confirmed,
    # stop the loop" instead of a dead job.
    structured = model.with_structured_output(ChallengeReflection, include_raw=True)
    envelope = await structured.ainvoke(
        [system, human],
        config=invoke_config("compile.challenge.reflect", callbacks, trace_metadata),
    )
    result = envelope.get("parsed") if isinstance(envelope, dict) else envelope
    if result is None:
        return ChallengeReflection(gaps=[], exhausted=True)
    result.gaps = list(result.gaps or [])
    return result


def render_compensation_guidance(gaps: list[ChallengeGap]) -> str:
    """The gap list as compile guidance for the compensation round.

    Rendered through the prompt catalog so a deployment can reword it; the writes it
    leads to still pass the ordinary citation gate.
    """
    joined = "\n".join(f"- {g.question}\n  missing: {g.missing_fact}" for g in gaps)
    return prompt("compile.challenge.compensation_preamble", gaps=joined)
