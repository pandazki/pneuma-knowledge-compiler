"""The startup reminder when the embedding model needs a key nobody set.

L2 is not optional equipment (docs/design/coding-agent-mode.md §3.1): a coding agent replaces
the compile model, an embedding key is still required, and the system says so at startup
rather than at the first embed call. What is pinned here is the shape of that saying — one
pure function that decides, one WARNING, once — because the thing a reminder can go wrong in
is being either absent or endless.
"""

from __future__ import annotations

import logging

import pytest
from pneuma_knowledge_service import wiring
from pneuma_knowledge_service.embedding_key import (
    EMBEDDING_SETTING,
    embedding_key_notice,
    embedding_key_requirement,
    missing_embedding_key,
)
from pneuma_knowledge_service.settings import Settings


@pytest.fixture(autouse=True)
def _forget_what_this_process_already_said():
    """The once-per-process guard is process state, and a test that inherited it would be
    asserting about the test before it."""
    wiring._EMBEDDING_KEY_WARNED.clear()  # noqa: SLF001
    yield
    wiring._EMBEDDING_KEY_WARNED.clear()  # noqa: SLF001


# ────────────────────────────────────────────────────────────────── the pure function


def test_which_specs_need_a_key_and_which_variable():
    assert embedding_key_requirement("openrouter:openai/text-embedding-3-small") == (
        "OPENROUTER_API_KEY",
        "openrouter_api_key",
    )
    # The keyless spec, and the spec of a deployment that named nothing: neither needs a key,
    # so neither can be missing one.
    assert embedding_key_requirement("fake:384") is None
    assert embedding_key_requirement("") is None


def test_a_spec_that_needs_a_key_only_reports_it_when_nobody_set_it():
    spec = "openrouter:openai/text-embedding-3-small"
    assert missing_embedding_key(spec, "sk-real") == ""
    # Whitespace is not a key: a variable set to spaces is a variable nobody set.
    assert missing_embedding_key(spec, "   ") == "OPENROUTER_API_KEY"
    assert missing_embedding_key(spec, "") == "OPENROUTER_API_KEY"
    assert missing_embedding_key("fake:384", "") == ""


def test_the_reminder_names_the_setting_the_variable_and_what_fails():
    notice = embedding_key_notice("openrouter:openai/text-embedding-3-small", "")
    assert EMBEDDING_SETTING in notice
    assert "OPENROUTER_API_KEY" in notice
    assert "L2" in notice
    # A reminder, not a refusal: nothing here tells anyone the deployment will not start.
    assert "refus" not in notice.lower()
    assert embedding_key_notice("fake:384", "") == ""


# ───────────────────────────────────────────────────────────────────────── the warning


def _settings() -> Settings:
    """The default generated projects carry, resolved the way the process resolves it — the
    key rides `OPENROUTER_API_KEY` in the environment, which is what the tests monkeypatch."""
    return Settings(embedding_model="openrouter:openai/text-embedding-3-small")


def test_a_keyless_openrouter_spec_warns_exactly_once(caplog, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = _settings()
    with caplog.at_level(logging.WARNING, logger=wiring.log.name):
        first = wiring.warn_missing_embedding_key(settings)
        second = wiring.warn_missing_embedding_key(settings)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "OPENROUTER_API_KEY" in warnings[0].getMessage()
    # The text is returned either way, so a caller with a face of its own can print it; only
    # the LOG is once.
    assert first == second != ""


def test_a_keyless_configuration_says_nothing_at_all(caplog, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger=wiring.log.name):
        assert wiring.warn_missing_embedding_key(Settings(embedding_model="fake:384")) == ""
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_a_key_that_is_set_says_nothing_either(caplog, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-real")
    with caplog.at_level(logging.WARNING, logger=wiring.log.name):
        assert wiring.warn_missing_embedding_key(_settings()) == ""
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
