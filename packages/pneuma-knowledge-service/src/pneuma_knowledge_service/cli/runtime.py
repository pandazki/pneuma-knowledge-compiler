"""The real `DraftRuntime`: the same adapters the API and the worker run on.

`pkc` reads the deployment exactly as the other two entry points read it — one `get_settings`,
one `build_context` — so a project's `.env` and `engine/` resolve the CLI the way they resolve
the service. What this module adds is only the wiring: which callable answers each of the
runtime's questions, and the fact that every one of them is the worker's own code.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource

from ..adapters.postgres import PostgresDraftStore
from ..coding_agent.backends import backend as backend_manifest
from ..coding_agent.install import installed_hash, steward_skill_hash
from ..persona_profile import is_placeholder, profile_notice
from ..skills import skill_for_user, composed_skill_readonly
from ..source_authorship import load_owner_authored_blocks
from ..wiring import AppContext, executor_for
from ..workers.compile_worker import (
    _search_knowledge_port,
    _search_source_port,
    agent_executor,
    compile_inputs,
    persist_compile_result,
)
from .draft import DraftRuntime


async def build_runtime(
    ctx: AppContext, user_id: UserId, *, executor: str | None = None, kind: str = "compile"
) -> DraftRuntime:
    """One tenant's draft runtime over this deployment's adapters.

    `executor` is what a finished job records about WHO typed the calls. The default reads
    the environment (`agent_executor`), which is the honest answer for a terminal session the
    Owner opened: nothing told this process which harness it is. The WORKER passes the
    resolved spec instead, because in the unattended posture it launched the harness itself
    and knows (§9)."""
    skill = (await composed_skill_readonly(ctx.settings, ctx.canonical, user_id)
             if kind in ("evolve", "episodes") else await skill_for_user(ctx, user_id))
    label = executor or agent_executor(ctx.settings)
    # WHICH WORDS the executor of this round was taught, resolved once here so every command
    # that ends a round states the same one. The shim exports it for a session it started; a
    # process it did not start — the worker finishing a round its harness left open — reads
    # the same fact off the install the harness was pointed at. Only under an agent executor:
    # a langchain round is not taught a skill package, and guessing one for it would be a
    # trailer that claims an executor the commit never had.
    selected = executor_for(ctx.settings, "evolve" if kind == "evolve" else "compile")
    executor_skill = steward_skill_hash()
    if not executor_skill and selected.is_agent:
        executor_skill = installed_hash(os.getcwd(), backend_manifest(str(selected.backend)))
    # Asked once, here, from the same provider the round's own contract is rendered from
    # (`compile_inputs`): does this library's profile name its Owner? A lookup that fails is
    # not a finding — the notice exists to catch the generator's placeholder, not to report
    # on an unreachable store.
    try:
        owner_profile = await ctx.user_info.get_profile(user_id)
        owner_placeholder = is_placeholder(owner_profile)
        owner_notice = profile_notice(owner_profile)
    except Exception:  # noqa: BLE001 — advisory, and never in the way of opening a round
        owner_placeholder = False
        owner_notice = ""

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

    async def record_brief(job_id: str, text: str) -> None:
        await ctx.store.record_compile_brief(user_id, job_id, text, if_missing=True)

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
        executor_skill=executor_skill,
        compile_draft_ttl=ctx.settings.compile_draft_ttl,
        worker_posture="unattended" if ctx.settings.agent_unattended else "interactive",
        kind=kind,
        record_brief=record_brief,
        owner_is_placeholder=owner_placeholder,
        owner_profile_notice=owner_notice,
        owner_authored_blocks=await load_owner_authored_blocks(ctx.store, user_id, skill),
        task_structure_chars=int(ctx.settings.agent_task_structure_chars),
    )
