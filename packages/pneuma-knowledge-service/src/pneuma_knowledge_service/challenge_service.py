"""Post-compile coverage challenge job (opt-in): orchestration around compile/challenge.

The core stage (pneuma_knowledge_core.compile.challenge) owns the judgement; this module
owns the ports: loading the job's sources, probing the library's claim face per question,
and routing confirmed gaps into ONE ordinary compensation compile whose writes pass the
same citation gate as any other. The audit points; the gate enforces.

Recursion is prevented by data, not convention: the compensation compile's payload
carries `challenge_compensation`, and the trigger refuses to fire on such jobs — one
audit round-trip per original compile, never a loop.
"""

from __future__ import annotations

import json
import logging

from langchain_core.language_models.chat_models import BaseChatModel
from pneuma_knowledge_core.compile.challenge import (
    ChallengeGap,
    generate_challenge_questions,
    judge_challenge_gaps,
    render_compensation_guidance,
)
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_core.skill.version import SkillVersion

from .wiring import AppContext, llm_call_config

log = logging.getLogger(__name__)

CHALLENGE_JOB_KIND = "challenge"

# Claims retrieved per question and per face (lexical / vector). Generous on purpose:
# the reflection judges "not recorded", and a stingy probe would report retrieval
# misses as coverage gaps.
_CLAIMS_PER_QUESTION = 6


async def maybe_trigger_challenge(
    ctx: AppContext, user_id: UserId, payload: dict, source_ids: list[str]
) -> None:
    """Enqueue one challenge job after a committed compile, when enabled.

    Never fires on a compensation compile (payload flag) — the audit gets one
    round-trip per original compile, not a loop.
    """
    if not ctx.settings.challenge_enabled:
        return
    if payload.get("challenge_compensation"):
        return
    if not source_ids:
        return
    await ctx.store.enqueue(
        user_id, CHALLENGE_JOB_KIND, {"source_ids": list(source_ids)}
    )


async def _probe_claims(ctx: AppContext, user_id: UserId, question: str) -> list[str]:
    """The recorded claims closest to one question, over both claim faces, deduped."""
    texts: dict[str, None] = {}
    try:
        for hit in await ctx.lexical.search_claims(
            user_id, question, limit=_CLAIMS_PER_QUESTION
        ):
            texts.setdefault(hit.text, None)
    except Exception:  # noqa: BLE001 — a missing face degrades the probe, not the job
        pass
    try:
        embedding = await ctx.embeddings.aembed_query(question)
        for hit in await ctx.vectors.search_claims(
            user_id, embedding, limit=_CLAIMS_PER_QUESTION
        ):
            texts.setdefault(hit.text, None)
    except Exception:  # noqa: BLE001
        pass
    return list(texts)


async def run_challenge_job(
    ctx: AppContext,
    model: BaseChatModel,
    skill: SkillVersion,
    user_id: UserId,
    job,
) -> None:
    """Blind questions → claim-face probes → reflection, up to the round budget.

    Ends early when either stage declares exhaustion. Confirmed gaps enqueue one
    compensation compile carrying the rendered guidance; the job detail records what
    happened either way.
    """
    payload = getattr(job, "payload", {}) or {}
    source_ids = [str(s) for s in payload.get("source_ids", [])]
    sources: list[NormalizedSource] = []
    for sid in source_ids:
        try:
            sources.append(await ctx.store.get(user_id, SourceId(sid)))
        except Exception:  # noqa: BLE001 — a deleted source is not this job's failure
            log.warning("challenge: source %s gone, skipping", sid)
    if not sources:
        await ctx.store.complete(user_id, job.job_id, ok=True, detail="challenge: sources gone")
        return

    cfg = llm_call_config(
        ctx, operation="compile.challenge", user_id=str(user_id), extra={"job_id": job.job_id}
    )
    asked: list[str] = []
    gaps: list[ChallengeGap] = []
    rounds = 0
    exhausted = False
    degraded: str | None = None
    # The challenge is a best-effort audit: a model/network/parsing failure mid-round
    # degrades to "audit incomplete" (keeping any gaps already confirmed, still
    # compensating for them) and NEVER fails the job. A failed challenge job wedges the
    # queue's tail — observed live as `'NoneType' object is not iterable` killing a
    # 500-day build at day 100.
    try:
        while rounds < ctx.settings.challenge_max_rounds and not exhausted:
            rounds += 1
            generated = await generate_challenge_questions(
                model=model,
                skill=skill,
                sources=sources,
                max_questions=ctx.settings.challenge_max_questions,
                asked=asked,
                **cfg,
            )
            if not generated.questions:
                exhausted = True
                break
            asked.extend(generated.questions)
            probes = [
                (question, await _probe_claims(ctx, user_id, question))
                for question in generated.questions
            ]
            reflection = await judge_challenge_gaps(
                model=model, sources=sources, probes=probes, **cfg
            )
            gaps.extend(reflection.gaps)
            exhausted = generated.exhausted or reflection.exhausted
    except Exception as exc:  # noqa: BLE001 — see the degradation note above
        degraded = f"{type(exc).__name__}: {exc}"
        log.warning("challenge degraded for %s: %s", job.job_id, degraded)

    compensated = False
    if gaps and ctx.settings.challenge_compensate:
        await ctx.store.enqueue(
            user_id,
            "compile",
            {
                "source_ids": source_ids,
                "challenge_guidance": render_compensation_guidance(gaps),
                "challenge_compensation": True,
            },
        )
        compensated = True

    payload_out = {
        "rounds": rounds,
        "questions": len(asked),
        "gaps": [g.question for g in gaps],
        "exhausted": exhausted,
        "compensation_enqueued": compensated,
    }
    if degraded:
        payload_out["degraded"] = degraded
    detail = json.dumps(payload_out, ensure_ascii=False)
    await ctx.store.complete(user_id, job.job_id, ok=True, detail=detail)
