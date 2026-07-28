"""The async migration's whole point, guarded by tests.

The stack went full-async for one concrete reason: GKE runs a SINGLE uvicorn process with
no `--workers` (deploy/gke/base/app-deployment.yaml), so one event loop serves the entire
API. Any blocking call inside an async route stalls every other request on that loop — the
`/healthz` liveness probe included, which is how a slow LLM call turns into a pod restart.

That property is easy to miss because ordinary functional tests remain green,
because every other test drives one request at a time and cannot tell an overlapped stack
from a serialized one. Without the tests below, a later refactor could reintroduce blocking
I/O and nothing would go red.

The stub sleeps with `asyncio.sleep` rather than `time.sleep` deliberately — it models a
slow *network* port (PG / Meili / Qdrant / OpenRouter), which is what the real adapters now
are. A `time.sleep` stub would test the stub, not the stack.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from types import SimpleNamespace

import httpx
from fastapi.routing import APIRoute

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.user_info_mock import MockUserInfoProvider
from pneuma_knowledge_service.api.app import create_app

# Long enough that serialization is unmistakable against scheduler noise, short enough that
# the whole module stays well under a second.
_DELAY = 0.2


class _SlowUserInfo:
    """A UserInfoProvider whose port method takes `_DELAY` to answer, then delegates.

    Delegating to the real mock (instead of hand-building a UserProfile) keeps the route's
    serialization path honest — these tests are about concurrency, so the response body has
    to be the genuine article or a shape change elsewhere would surface here as noise."""

    def __init__(self) -> None:
        self._inner = MockUserInfoProvider()
        self.calls = 0

    async def get_profile(self, user_id: UserId):  # noqa: ANN201
        self.calls += 1
        await asyncio.sleep(_DELAY)
        return await self._inner.get_profile(user_id)


def _app(user_info: _SlowUserInfo):
    """The real app (so `/healthz` and the real router are wired), with a slow port stubbed.

    `httpx.ASGITransport` does not run lifespan, so `app.state.ctx` is never populated by
    `build_context` — assigning it here is the sanctioned way these tests inject a context
    without standing up middleware."""
    app = create_app()
    app.state.ctx = SimpleNamespace(user_info=user_info)
    return app


def _client(app) -> httpx.AsyncClient:  # noqa: ANN001
    """ASGI-transport client: the app runs on the TEST's event loop, so loop-bound resources
    stay valid and overlap is measurable. Starlette's TestClient drives the app from a
    separate portal thread with its own loop and would hide exactly what we are asserting."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_concurrent_requests_overlap_instead_of_serializing():
    """N slow requests must cost ~1x the delay, not Nx."""
    n = 5
    user_info = _SlowUserInfo()
    client = _client(_app(user_info))

    started = time.perf_counter()
    responses = await asyncio.gather(
        *(client.get(f"/v1/users/u-probe-{i}/profile") for i in range(n))
    )
    elapsed = time.perf_counter() - started

    assert [r.status_code for r in responses] == [200] * n
    assert user_info.calls == n
    # Serialized: n * _DELAY = 1.0s. Overlapped: ~_DELAY. The 2x headroom absorbs scheduler
    # jitter while still failing loudly at even 2-of-5 serialization (0.4s).
    assert elapsed < _DELAY * 2, (
        f"{n} concurrent requests took {elapsed:.3f}s; overlapped should be ~{_DELAY}s, "
        f"fully serialized would be ~{n * _DELAY}s — the event loop is being blocked"
    )


async def test_healthz_overtakes_a_slow_request_already_in_flight():
    """The liveness-probe scenario that motivated the migration.

    A blocked loop does not merely make `/healthz` slow — it makes Kubernetes conclude the
    pod is dead and restart it mid-request.

    Asserted as COMPLETION ORDER, not latency. The obvious version of this test — start the
    slow request, sleep, then time `/healthz` — is vacuous: under a genuinely blocking
    handler the loop cannot return to the test until the block is over, so the slow request
    has already finished and `/healthz` is measured against an idle loop. It passes whether
    or not the stack blocks. Ordering has no such hole: `gather` starts the slow request
    first, so `/healthz` can only finish first if the slow one yielded the loop."""
    client = _client(_app(_SlowUserInfo()))
    finished: list[str] = []

    async def slow_request():
        response = await client.get("/v1/users/u-probe/profile")
        finished.append("slow")
        return response

    async def health_request():
        response = await client.get("/healthz")
        finished.append("health")
        return response

    slow_response, health_response = await asyncio.gather(
        slow_request(), health_request()
    )

    assert slow_response.status_code == 200
    assert health_response.status_code == 200
    assert finished == ["health", "slow"], (
        f"completion order was {finished}; /healthz was started second yet had to wait for "
        f"the slow request — the probe is queued behind application work, which is what "
        f"gets pods restarted"
    )


def test_every_route_handler_is_a_coroutine():
    """Structural guard: a sync `def` route is not a bug FastAPI will surface.

    FastAPI silently runs sync handlers in its anyio threadpool, so one added later would
    pass every other test while quietly reintroducing thread-per-request — the model this
    migration replaced. Only an explicit assertion catches that."""
    offenders = [
        f"{route.path} -> {route.endpoint.__name__}"
        for route in create_app().routes
        if isinstance(route, APIRoute)
        and not inspect.iscoroutinefunction(route.endpoint)
    ]
    assert not offenders, "sync route handlers found: " + ", ".join(offenders)
