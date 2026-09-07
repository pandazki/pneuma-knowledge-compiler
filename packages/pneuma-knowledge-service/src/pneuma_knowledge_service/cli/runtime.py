"""The real `DraftRuntime`: the same adapters the API and the worker run on.

`pkc` reads the deployment exactly as the other two entry points read it — one `get_settings`,
one `build_context` — so a project's `.env` and `engine/` resolve the CLI the way they resolve
the service. What this module adds is only the wiring: which callable answers each of the
runtime's questions, and the fact that every one of them is the worker's own code.
"""

from __future__ import annotations

from collections.abc import Sequence

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource

from ..adapters.postgres import PostgresDraftStore
from ..persona_profile import is_placeholder
from ..skills import skill_for_user
from ..wiring import AppContext
from ..workers.compile_worker import (
    _search_knowledge_port,
    _search_source_port,
    agent_executor,
    compile_inputs,
    persist_compile_result,
)
from .draft import DraftRuntime


async def build_runtime(
    ctx: AppContext, user_id: UserId, *, executor: str | None = None
) -> DraftRuntime:
    """One tenant's draft runtime over this deployment's adapters.

    `executor` is what a finished job records about WHO typed the calls. The default reads
    the environment (`agent_executor`), which is the honest answer for a terminal session the
    Owner opened: nothing told this process which harness it is. The WORKER passes the
    resolved spec instead, because in the unattended posture it launched the harness itself
    and knows (§9)."""
    skill = await skill_for_user(ctx, user_id)
    label = executor or agent_executor(ctx.settings)
    # Asked once, here, from the same provider the round's own contract is rendered from
    # (`compile_inputs`): does this library's profile name its Owner? A lookup that fails is
    # not a finding — the notice exists to catch the generator's placeholder, not to report
    # on an unreachable store.
    try:
        owner_placeholder = is_placeholder(await ctx.user_info.get_profile(user_id))
    except Exception:  # noqa: BLE001 — advisory, and never in the way of opening a round
        owner_placeholder = False

    async def load_inputs(job):  # noqa: ANN001
        # `caption`: an agent reads a terminal, so native image blocks have nowhere to go.
        return await compile_inputs(ctx, user_id, job, image_mode="caption")

    async def load_sources(ids: Sequence[str]) -> list[NormalizedSource]:
        out: list[NormalizedSource] = []
        for sid in ids:
            try:
                out.append(await ctx.store.get(user_id, SourceId(str(sid))))
            except KeyError:
                continue  # source deleted since the round opened; the gate says so
        return out

    async def load_bounds() -> dict[str, int]:
        return await ctx.store.block_counts(user_id)

    async def persist(job, result) -> None:  # noqa: ANN001
        # The worker's own tail, called with the worker's own inputs: an agent-compiled job
        # leaves the same events, the same projection delta, the same digestion and the same
        # job row behind as a model-compiled one.
        inputs = await compile_inputs(ctx, user_id, job, image_mode="caption")
        await persist_compile_result(
            ctx,
            user_id,
            getattr(job, "job_id"),
            getattr(job, "payload", {}) or {},
            inputs,
            result,
            executor=label,
        )

    return DraftRuntime(
        user_id=user_id,
        canonical=ctx.canonical,
        drafts=PostgresDraftStore(ctx.store),
        jobs=ctx.store,
        skill=skill,
        load_inputs=load_inputs,
        load_sources=load_sources,
        load_bounds=load_bounds,
        overview_budget_chars=ctx.settings.overview_budget_chars,
        overview_required_after_claims=ctx.settings.overview_required_after_claims,
        max_tool_calls=ctx.settings.compile_max_tool_calls,
        search_knowledge=_search_knowledge_port(ctx, user_id),
        search_source=_search_source_port(ctx, user_id),
        persist=persist,
        executor=label,
        owner_is_placeholder=owner_placeholder,
    )
