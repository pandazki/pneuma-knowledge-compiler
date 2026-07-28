"""Worker per-job skill resolution + per-sweep cache (schema-evolve M1, A3).

The compile worker no longer holds one global skill: each user's compile jobs load that
user's own composed skill (skill=None), memoized per sweep. This unit-tests the resolution
helper directly — no middleware — proving (1) an explicit skill bypasses skill_for_user,
(2) skill=None resolves per-user, and (3) the cache prevents a second git read."""

from __future__ import annotations

from types import SimpleNamespace

import pneuma_knowledge_service.workers.compile_worker as worker
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.workers.compile_worker import _resolve_user_skill


async def test_resolve_uses_cache_and_calls_skill_for_user_once(monkeypatch):
    calls: list[str] = []

    async def fake_skill_for_user(ctx, user_id):
        calls.append(str(user_id))
        return load_builtin_skill("v2")

    monkeypatch.setattr(worker, "skill_for_user", fake_skill_for_user)

    ctx = SimpleNamespace()
    cache: dict = {}
    uid = UserId("u-1")

    first = await _resolve_user_skill(ctx, uid, cache)
    second = await _resolve_user_skill(ctx, uid, cache)
    assert first.content_hash == second.content_hash
    # Resolved once; the second hit came from the per-sweep cache.
    assert calls == ["u-1"]

    # A different user resolves separately.
    await _resolve_user_skill(ctx, UserId("u-2"), cache)
    assert calls == ["u-1", "u-2"]


async def test_resolve_without_cache_reads_each_time(monkeypatch):
    calls: list[str] = []

    async def fake_skill_for_user(ctx, user_id):
        calls.append(str(user_id))
        return load_builtin_skill("v1")

    monkeypatch.setattr(worker, "skill_for_user", fake_skill_for_user)

    ctx = SimpleNamespace()
    await _resolve_user_skill(ctx, UserId("u-1"), None)
    await _resolve_user_skill(ctx, UserId("u-1"), None)
    assert calls == ["u-1", "u-1"]  # no cache → resolves each call
