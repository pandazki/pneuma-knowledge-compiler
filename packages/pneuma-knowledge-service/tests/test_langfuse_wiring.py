"""build_langfuse_handler / llm_call_config — keyless degrade + has-key build branch.

Keyless (all three LANGFUSE_* empty) → None, so every core call site runs callbacks-free
(the existing 139 tests are unaffected). Has-key → a handler is built; that branch is
exercised hermetically by monkeypatching the lazy langfuse import (no client, no network).
"""

from __future__ import annotations

from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_langfuse_handler, llm_call_config
import pneuma_knowledge_service.wiring as wiring


# The fields use validation_alias="LANGFUSE_*" and read `.env`; construct hermetically
# via `_env_file=None` (ignore the dev box's .env) + alias kwargs.
def _empty_settings() -> Settings:
    return Settings(_env_file=None)


def _keyed_settings() -> Settings:
    return Settings(
        _env_file=None,
        LANGFUSE_SECRET_KEY="sk-test",
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_BASE_URL="http://localhost:3000",
    )


def test_build_langfuse_handler_none_without_keys():
    assert build_langfuse_handler(_empty_settings()) is None


def test_build_langfuse_handler_none_on_partial_keys():
    partial = Settings(
        _env_file=None,
        LANGFUSE_SECRET_KEY="sk-test",
        LANGFUSE_PUBLIC_KEY="",  # missing → still off
        LANGFUSE_BASE_URL="http://localhost:3000",
    )
    assert build_langfuse_handler(partial) is None


def test_build_langfuse_handler_builds_with_keys(monkeypatch):
    built = {}

    class FakeLangfuse:
        def __init__(self, **kwargs):
            built["init"] = kwargs

    class FakeHandler:
        pass

    monkeypatch.setattr(wiring, "_import_langfuse", lambda: (FakeLangfuse, FakeHandler))
    handler = build_langfuse_handler(_keyed_settings())
    assert isinstance(handler, FakeHandler)
    # Client initialized with public/secret key + host (no network in the fake).
    assert built["init"] == {
        "public_key": "pk-test",
        "secret_key": "sk-test",
        "host": "http://localhost:3000",
    }


def test_llm_call_config_off_gives_empty_callbacks():
    # A minimal stand-in ctx: only langfuse_handler() is exercised here.
    class StubCtx:
        settings = _empty_settings()
        _langfuse_built = False
        _langfuse_handler = None

        def langfuse_handler(self):
            return None

    cfg = llm_call_config(
        StubCtx(), operation="recall.fast", user_id="u-it-1", extra={"snapshot_ref": "abc"}
    )
    assert cfg["callbacks"] == []
    md = cfg["trace_metadata"]
    assert md["operation"] == "recall.fast"
    assert md["user_id"] == "u-it-1"
    assert md["env"] == "local"
    assert md["app"] == "pneuma-knowledge-compiler"
    assert md["snapshot_ref"] == "abc"


def test_llm_call_config_drops_none_extras_and_injects_handler():
    sentinel = object()

    class StubCtx:
        def langfuse_handler(self):
            return sentinel

    cfg = llm_call_config(
        StubCtx(),
        operation="compile",
        user_id="u-it-2",
        extra={"skill_version": "v1", "snapshot_ref": None},
    )
    assert cfg["callbacks"] == [sentinel]  # handler injected as a callback
    md = cfg["trace_metadata"]
    assert md["skill_version"] == "v1"
    assert "snapshot_ref" not in md  # None-valued extra dropped


def test_openrouter_provider_pin_rides_extra_body(monkeypatch):
    """The provider pin must reach the request payload; empty setting adds nothing."""
    from pneuma_knowledge_service.settings import Settings
    from pneuma_knowledge_service.wiring import _build_from_name

    captured: dict = {}

    def fake_init_chat_model(model, **kwargs):
        captured.clear()
        captured.update(kwargs)
        return object()

    import pneuma_knowledge_service.wiring as wiring
    import langchain.chat_models as lcm

    monkeypatch.setattr(lcm, "init_chat_model", fake_init_chat_model)

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    pinned = Settings(
        openrouter_provider_order="openai",
        user_schema_base_version="v1",
    )
    _build_from_name("openrouter:openai/gpt-5.6-luna", pinned)
    assert captured["extra_body"] == {
        "provider": {"order": ["openai"], "allow_fallbacks": False}
    }

    unpinned = Settings(user_schema_base_version="v1")
    _build_from_name("openrouter:openai/gpt-5.6-luna", unpinned)
    assert "extra_body" not in captured
