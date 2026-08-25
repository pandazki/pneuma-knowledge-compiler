"""Every real chat model is built with a request timeout and a retry budget.

A provider call with neither is the failure mode this pins down: a hung OpenRouter
request held a compile job for 25 minutes with no error, no tokens and no way out,
because the client was constructed with langchain's "wait forever" default.
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_chat_model_for


def test_timeout_default_is_generous_and_retries_are_budgeted() -> None:
    """The timeout guards against hangs, not against slowness — so it is minutes, not
    seconds. Shrinking it to a "normal" request latency would kill slow-but-alive calls."""
    settings = Settings()

    assert settings.llm_timeout >= 300.0
    assert settings.llm_max_retries >= 1


def test_openrouter_chat_model_carries_timeout_and_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")
    settings = Settings(
        llm_model="openrouter:vendor/some-model",
        llm_timeout=123.5,
        llm_max_retries=7,
    )

    model = build_chat_model_for(settings, "compile")

    # langchain-openai names the field `request_timeout` and aliases it as `timeout`.
    assert model.request_timeout == 123.5
    assert model.max_retries == 7


def test_every_role_shares_the_same_guardrails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One timeout + one retry budget for compile/recall/deep/live_context/evolve — a
    per-role matrix is a knob nobody can reason about."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-a-real-key")
    settings = Settings(
        llm_model="openrouter:vendor/base",
        llm_model_compile="openrouter:vendor/compile",
        llm_model_answer="openrouter:vendor/answer",
        llm_model_deep="openrouter:vendor/deep",
        llm_timeout=321.0,
        llm_max_retries=4,
    )

    for role in ("default", "compile", "recall", "answer", "deep", "live_context", "evolve"):
        model = build_chat_model_for(settings, role)
        assert (model.request_timeout, model.max_retries) == (321.0, 4), role


def test_non_openrouter_provider_path_is_guarded_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generic `init_chat_model` escape hatch (any `<provider>:…` spec that is not
    `openrouter:`) must not be the one branch that can still hang."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    settings = Settings(
        llm_model="openai:gpt-5.6-luna", llm_timeout=222.0, llm_max_retries=5
    )

    model = build_chat_model_for(settings, "recall")

    assert model.request_timeout == 222.0
    assert model.max_retries == 5


def test_scripted_model_needs_no_provider_guardrails(tmp_path) -> None:
    """Local replay makes no request; the guardrail kwargs must not leak into it."""
    script = tmp_path / "script.json"
    script.write_text('{"turns": []}', encoding="utf-8")

    model = build_chat_model_for(Settings(llm_model=f"scripted:{script}"), "compile")

    assert not hasattr(model, "request_timeout")
