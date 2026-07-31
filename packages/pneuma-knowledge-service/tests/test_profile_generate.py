"""POST /v1/profile/generate: sentence → full UserProfile via a stub model.

Keyless — the stub ctx carries a fake chat model whose `.with_structured_output` yields a
fixed ProfileDraft, and a `langfuse_handler` returning None. It never touches PG/Meili/
Qdrant or the network. Asserts the draft→UserProfile overlay: enum-valid, source="ai",
avatar.initial recomputed from the draft name, id honored/derived.
"""

from __future__ import annotations

from types import SimpleNamespace

from pneuma_knowledge_core.domain.user import INDUSTRIES, LEVELS, ROLES
from pneuma_knowledge_core.persona import ProfileDraft
from pneuma_knowledge_service.api.routes.v1 import root_router
import httpx
from fastapi import FastAPI


def _draft(**over) -> ProfileDraft:
    base = dict(
        display_name="测试用户 Test User",
        gender="male",
        birth_year=1992,
        industry="tech",
        role="engineering",
        level="senior",
        occupation="AI 产品独立开发者",
        bio="我在杭州独立开发 AI 产品，用 agent 协作完成研究、工程和运营。",
        interests=["开源", "智能体", "产品实验"],
        locale={
            "city": "杭州",
            "country": "中国",
            "timezone": "Asia/Shanghai",
            "language": "zh-CN",
        },
        preferences={
            "response_language": "zh-CN",
            "units": "metric",
            "privacy_level": "standard",
        },
        workspace={
            "operating_mode": "independent",
            "primary_stack": "TypeScript + Python",
            "automation_level": "agentic",
            "active_since": "2024-05-01",
        },
        user_id="u-profile-test",
    )
    base.update(over)
    return ProfileDraft(**base)


class _FakeStructured:
    def __init__(self, draft: ProfileDraft) -> None:
        self._draft = draft

    async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
        return self._draft


class _FakeModel:
    def __init__(self, draft: ProfileDraft) -> None:
        self._draft = draft

    def with_structured_output(self, schema):  # noqa: ANN001, ARG002
        return _FakeStructured(self._draft)


def _app(draft: ProfileDraft) -> FastAPI:
    app = FastAPI()
    app.include_router(root_router)
    app.state.ctx = SimpleNamespace(
        get_chat_model=lambda role="default": _FakeModel(draft),
        langfuse_handler=lambda: None,
    )
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """An ASGI-transport client for `app`. Everything stays on ONE event loop — the
    test's — which is what keeps the loop-bound resources (PG pool, httpx clients inside
    the adapters) valid. Starlette's TestClient would run the app on a separate portal
    thread with its own loop, so any object built there could not be awaited from here."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_generate_overlays_draft_onto_valid_profile():
    client = _client(_app(_draft()))
    resp = await client.post("/v1/profile/generate", json={"sentence": "杭州做 AI 产品的独立开发者"})
    assert resp.status_code == 200
    body = resp.json()

    # Provenance + semantic overlay from the draft.
    assert body["source"] == "ai"
    assert body["display_name"] == "测试用户 Test User"
    assert body["occupation"] == "AI 产品独立开发者"
    assert body["locale"]["timezone"] == "Asia/Shanghai"
    assert body["preferences"]["units"] == "metric"
    assert body["workspace"]["operating_mode"] == "independent"
    assert body["workspace"]["automation_level"] == "agentic"
    assert body["interests"] == ["开源", "智能体", "产品实验"]

    # Enum-valid picture; computed level_style serialized.
    assert body["industry"] in INDUSTRIES
    assert body["role"] in ROLES
    assert body["level"] in LEVELS
    assert body["level_style"]

    # avatar.initial recomputed from the draft name; color kept from the mock base.
    assert body["avatar"]["initial"] == "测"
    assert body["avatar"]["color"].startswith("#")

    # Non-semantic scaffolding supplied by the deterministic base.
    assert body["joined_at"]

    # No explicit id → the draft's suggested slug is honored.
    assert body["user_id"] == "u-profile-test"


async def test_explicit_id_wins_over_draft_slug():
    client = _client(_app(_draft()))
    resp = await client.post(
        "/v1/profile/generate",
        json={"sentence": "上海销售", "user_id": "u-my-typed-id"},
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "u-my-typed-id"


async def test_invalid_draft_slug_falls_back_to_random_id():
    # A draft slug that is not URL/fs-safe is rejected → random u-xxxxxx.
    client = _client(_app(_draft(user_id="不合法 slug!")))
    resp = await client.post("/v1/profile/generate", json={"sentence": "随便一个人"})
    assert resp.status_code == 200
    uid = resp.json()["user_id"]
    assert uid.startswith("u-") and uid[2:].isalnum()


async def test_avatar_initial_tracks_display_name():
    client = _client(_app(_draft(display_name="测试用户 Test User")))
    resp = await client.post("/v1/profile/generate", json={"sentence": "SF backend eng"})
    assert resp.json()["avatar"]["initial"] == "测"
