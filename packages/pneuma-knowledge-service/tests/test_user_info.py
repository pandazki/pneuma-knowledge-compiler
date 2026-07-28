"""Public OPC UserInfoProvider mock: one persona + deterministic synthesis + API shape.

Fully keyless — no middleware, no chat model. The API test mounts the router on a
bare app with a stub ctx carrying only `user_info`, so it never touches PG/Meili/
Qdrant.
"""

from __future__ import annotations

from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import LEVELS, LEVEL_STYLES, UserProfile
from pneuma_knowledge_service.adapters.user_info_mock import MockUserInfoProvider
from pneuma_knowledge_service.adapters.user_info_provider_composite import (
    PersistedThenMockUserInfoProvider,
)
from pneuma_knowledge_service.api.routes.v1 import router
import httpx
from fastapi import FastAPI


def _provider() -> MockUserInfoProvider:
    return MockUserInfoProvider()


async def test_named_persona_opc_developer():
    p = await _provider().get_profile(UserId("u-opc-lin"))
    assert isinstance(p, UserProfile)
    assert p.user_id == "u-opc-lin"
    assert p.display_name == "林知远 Lin Zhiyuan"
    assert p.locale.language == "zh-CN"
    assert p.occupation == "AI 产品独立开发者"
    assert p.source == "mock"
    assert p.avatar.initial == "林"
    assert p.avatar.color.startswith("#")
    # Structured onboarding core.
    assert (p.industry, p.role, p.level) == ("tech", "engineering", "senior")
    assert p.level_style == LEVEL_STYLES["senior"]
    assert (
        p.level_style
        == "Prefers concise, context-aware answers that focus on trade-offs and impact."
    )


async def test_synthesis_is_idempotent():
    prov = _provider()
    a = await prov.get_profile(UserId("u-random-9f3a"))
    b = await prov.get_profile(UserId("u-random-9f3a"))
    assert a.model_dump() == b.model_dump()
    # A fresh provider instance yields the same picture (hash-only, no state).
    assert (await _provider().get_profile(UserId("u-random-9f3a"))).model_dump() == a.model_dump()


async def test_synthesis_differs_by_id():
    prov = _provider()
    names = {
        (await prov.get_profile(UserId(f"u-new-{i}"))).display_name for i in range(12)
    }
    # Not all synthesized users collapse to a single name.
    assert len(names) > 1


async def test_synthesis_is_self_consistent_and_complete():
    p = await _provider().get_profile(UserId("u-brand-new-xyz"))
    assert isinstance(p, UserProfile)
    assert p.display_name and p.avatar.initial and p.avatar.color.startswith("#")
    assert p.locale.language == p.preferences.response_language == "zh-CN"
    assert p.preferences.units == "metric"
    assert p.preferences.privacy_level in ("standard", "strict")
    assert 1900 < (p.birth_year or 0) < 2020
    assert p.workspace.operating_mode == "opc"
    assert p.workspace.primary_stack
    assert p.workspace.automation_level == "agentic"
    # joined ISO date parses; active_since is not before it.
    assert p.joined_at <= p.workspace.active_since
    assert p.source == "mock"
    # Structured onboarding enums come from the enum value sets, and level_style tracks.
    assert p.industry == "tech"
    assert p.role == "engineering"
    assert p.level in LEVELS
    assert p.occupation == "AI-Native 独立开发者"
    assert p.level_style == LEVEL_STYLES[p.level]


async def test_level_styles_shape():
    assert list(LEVELS) == [
        "entry",
        "junior",
        "mid",
        "senior",
        "staff",
        "principal",
    ]
    assert (
        LEVEL_STYLES["senior"]
        == "Prefers concise, context-aware answers that focus on trade-offs and impact."
    )
    # Every synthesized/persona level maps to a non-empty style string.
    assert all(LEVEL_STYLES[k] for k in LEVELS)


async def test_avatar_color_deterministic_from_id():
    a = (await _provider().get_profile(UserId("u-color-probe"))).avatar.color
    b = (await _provider().get_profile(UserId("u-color-probe"))).avatar.color
    assert a == b and a.startswith("#") and len(a) == 7


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.ctx = SimpleNamespace(user_info=MockUserInfoProvider())
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """An ASGI-transport client — the app runs on the TEST's event loop, unlike
    Starlette's TestClient which drives it from a separate portal thread."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_api_profile_named_persona():
    client = _client(_app())
    resp = await client.get("/v1/users/u-opc-lin/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "u-opc-lin"
    assert body["display_name"] == "林知远 Lin Zhiyuan"
    assert body["avatar"]["initial"] == "林"
    assert body["industry"] == "tech"
    assert body["role"] == "engineering"
    assert body["level"] == "senior"
    # computed_field is serialized into the response.
    assert body["level_style"] == LEVEL_STYLES["senior"]
    assert set(body) >= {
        "user_id",
        "display_name",
        "avatar",
        "locale",
        "industry",
        "role",
        "level",
        "level_style",
        "occupation",
        "workspace",
        "preferences",
        "joined_at",
        "source",
    }


async def test_api_profile_synthesized_and_stable():
    client = _client(_app())
    r1 = await client.get("/v1/users/u-fresh-abc123/profile")
    r2 = await client.get("/v1/users/u-fresh-abc123/profile")
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["source"] == "mock"
    assert r1.json()["avatar"]["color"].startswith("#")


# ---------------------------------------------- persisted-first composite provider


class _FakeStore:
    """In-memory stand-in for PostgresStore's user_profiles methods (keyless PUT/GET)."""

    def __init__(self) -> None:
        self._profiles: dict[str, dict] = {}

    async def get_user_profile(self, user_id) -> dict | None:
        return self._profiles.get(str(user_id))

    async def upsert_user_profile(self, user_id, profile: dict) -> None:
        self._profiles[str(user_id)] = profile


async def test_composite_mock_fallback_when_not_persisted():
    async def _none(_uid):
        return None

    prov = PersistedThenMockUserInfoProvider(_none, MockUserInfoProvider())
    p = await prov.get_profile(UserId("u-opc-lin"))
    assert p.display_name == "林知远 Lin Zhiyuan"
    assert p.source == "mock"


async def test_composite_persisted_wins():
    mock = MockUserInfoProvider()
    stored = (await mock.get_profile(UserId("u-it-persist"))).model_dump()
    stored.update(display_name="Persisted Name", industry="finance", source="user")
    async def _lookup(uid):
        return stored if uid == "u-it-persist" else None

    prov = PersistedThenMockUserInfoProvider(_lookup, mock)
    p = await prov.get_profile(UserId("u-it-persist"))
    assert p.display_name == "Persisted Name"
    assert p.industry == "finance"
    assert p.source == "user"
    # A different id still falls through to the mock.
    assert (await prov.get_profile(UserId("u-it-other"))).source == "mock"


def _app_with_store() -> tuple[FastAPI, _FakeStore]:
    app = FastAPI()
    app.include_router(router)
    store = _FakeStore()
    app.state.ctx = SimpleNamespace(
        store=store,
        user_info=PersistedThenMockUserInfoProvider(
            store.get_user_profile, MockUserInfoProvider()
        ),
    )
    return app, store


async def test_put_profile_merge_and_persist():
    app, _store = _app_with_store()
    client = _client(app)
    uid = "u-it-onboard-x"

    # Base = mock synthesis for this id; capture the untouched fields.
    base = (await client.get(f"/v1/users/{uid}/profile")).json()
    assert base["source"] == "mock"

    resp = await client.put(
        f"/v1/users/{uid}/profile",
        json={"industry": "tech", "level": "senior", "display_name": "Onboarded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "user"
    assert body["industry"] == "tech"
    assert body["level"] == "senior"
    assert body["display_name"] == "Onboarded"
    # Fields not in the body keep their base value (merge semantics).
    assert body["role"] == base["role"]
    assert body["occupation"] == base["occupation"]
    assert body["locale"] == base["locale"]
    # level_style tracks the new level.
    assert body["level_style"] == LEVEL_STYLES["senior"]

    # GET now returns the persisted picture (source="user").
    after = (await client.get(f"/v1/users/{uid}/profile")).json()
    assert after["source"] == "user"
    assert after["display_name"] == "Onboarded"
    assert after["industry"] == "tech"


async def test_put_profile_nested_merge():
    app, _store = _app_with_store()
    client = _client(app)
    uid = "u-it-nested"
    base = (await client.get(f"/v1/users/{uid}/profile")).json()

    resp = await client.put(
        f"/v1/users/{uid}/profile",
        json={"locale": {"city": "Shenzhen"}, "preferences": {"units": "imperial"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Sub-field merged; sibling sub-fields preserved from base.
    assert body["locale"]["city"] == "Shenzhen"
    assert body["locale"]["country"] == base["locale"]["country"]
    assert body["locale"]["language"] == base["locale"]["language"]
    assert body["preferences"]["units"] == "imperial"
    assert body["preferences"]["privacy_level"] == base["preferences"]["privacy_level"]


async def test_put_profile_rejects_bad_enum():
    app, _store = _app_with_store()
    client = _client(app)
    for field, bad in [("industry", "aerospace"), ("role", "wizard"), ("level", "god")]:
        resp = await client.put(f"/v1/users/u-it-bad/profile", json={field: bad})
        assert resp.status_code == 422, (field, resp.text)
    # A rejected PUT persisted nothing — GET stays mock.
    assert (await client.get("/v1/users/u-it-bad/profile")).json()["source"] == "mock"


async def test_put_profile_user_isolation():
    app, _store = _app_with_store()
    client = _client(app)
    await client.put("/v1/users/u-it-a/profile", json={"display_name": "AAA"})
    # A user who never PUT stays on the mock synthesis, unaffected by the other's write.
    other = (await client.get("/v1/users/u-it-b/profile")).json()
    assert other["source"] == "mock"
    assert other["display_name"] != "AAA"
