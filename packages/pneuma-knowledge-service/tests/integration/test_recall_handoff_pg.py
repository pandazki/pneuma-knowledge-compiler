"""The pending recall hand-over's home in Postgres (coding-agent-mode §5.1).

The keyless suite proves `pkc recall --evidence` and `pkc consult answer` against the
in-memory stand-in; this is the same set of claims against real SQL — the row round-trips, it
is per-tenant, it is deleted when the answer arrives, and one nobody came back to is swept by
the same startup self-heal that reclaims abandoned drafts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.postgres import PostgresRecallHandoffStore
from pneuma_knowledge_service.workers.compile_worker import sweep_recall_handoffs

STATE = {
    "question": "what do seats cost?",
    "as_of": "2026-09-01T00:00:00+00:00",
    "library_ref": "abc123",
    "visitor_class": "business",
    "handles": {"s01": "src-1"},
    "manifest": [{"kind": "window", "ref": "src-1 ¶1-2", "path": ""}],
}


async def _age(pg_store, user, handoff_id: str, *, seconds: int) -> None:
    async with pg_store._pool.connection() as conn:
        await conn.execute(
            "UPDATE recall_handoffs SET created_at = now() - make_interval(secs => %s) "
            "WHERE user_id = %s AND handoff_id = %s",
            (float(seconds), str(user), handoff_id),
        )


async def test_a_handoff_round_trips_and_is_gone_once_it_is_answered(pg_store, user):
    handoffs = PostgresRecallHandoffStore(pg_store)

    assert await handoffs.get(user, "h-1") is None
    assert await handoffs.list_pending(user) == []

    await handoffs.create(user, "h-1", STATE)
    assert await handoffs.get(user, "h-1") == STATE
    assert [h for h, _ in await handoffs.list_pending(user)] == ["h-1"]

    # Another tenant's store answers about its own rows and nothing else (I1).
    other = UserId(f"{user}-other")
    assert await handoffs.get(other, "h-1") is None
    assert await handoffs.list_pending(other) == []

    await handoffs.delete(user, "h-1")
    assert await handoffs.get(user, "h-1") is None
    await handoffs.delete(user, "h-1")  # idempotent: an answered hand-over is not an error


async def test_the_self_heal_sweeps_the_handoff_nobody_came_back_to(pg_store, user):
    handoffs = PostgresRecallHandoffStore(pg_store)
    await handoffs.create(user, "h-fresh", STATE)
    await handoffs.create(user, "h-stale", STATE)
    await _age(pg_store, user, "h-stale", seconds=48 * 60 * 60)

    ctx = SimpleNamespace(
        store=pg_store, settings=SimpleNamespace(recall_handoff_ttl=24 * 60 * 60)
    )
    swept = await sweep_recall_handoffs(ctx, label="test")
    assert swept >= 1

    assert await handoffs.get(user, "h-stale") is None
    # A round still being worked on is left alone.
    assert await handoffs.get(user, "h-fresh") == STATE

    # A TTL of 0 disables the sweep entirely.
    await _age(pg_store, user, "h-fresh", seconds=48 * 60 * 60)
    ctx.settings.recall_handoff_ttl = 0
    assert await sweep_recall_handoffs(ctx, label="test") == 0
    assert await handoffs.get(user, "h-fresh") == STATE

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await handoffs.sweep(cutoff) >= 1
