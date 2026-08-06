"""The challenge's completion budget: a runaway generation must fail cheaply.

2026-08-05, observed live: a challenge reflection ran to the provider ceiling
(65,536 completion tokens) before failing to parse — soft-degraded, but paid in full.
The budget is pinned at model construction for the challenge role only; roles sharing
the same spec keep their uncapped instance, and scripted models keep one shared
replay cursor.
"""

from __future__ import annotations

from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import AppContext


def _settings(**over) -> Settings:
    return Settings(
        _env_file=None,
        OPENROUTER_API_KEY="test-key-not-real",
        llm_model="openrouter:test/model",
        **over,
    )


def _ctx(settings: Settings) -> AppContext:
    ctx = AppContext.__new__(AppContext)
    ctx.settings = settings
    ctx._chat_models = {}
    return ctx


def test_challenge_role_is_built_with_the_output_budget():
    ctx = _ctx(_settings())
    challenge = ctx.get_chat_model("challenge")
    assert challenge.max_tokens == 32768


def test_other_roles_sharing_the_spec_stay_uncapped_and_separate():
    ctx = _ctx(_settings())
    compile_model = ctx.get_chat_model("compile")
    challenge = ctx.get_chat_model("challenge")
    assert compile_model is not challenge
    assert compile_model.max_tokens is None
    # Same role again → same cached capped instance.
    assert ctx.get_chat_model("challenge") is challenge


def test_zero_budget_means_provider_default():
    ctx = _ctx(_settings(challenge_max_output_tokens=0))
    challenge = ctx.get_chat_model("challenge")
    assert challenge.max_tokens is None
    # And with no cap in play, the spec cache is shared across roles as before.
    assert ctx.get_chat_model("compile") is challenge
