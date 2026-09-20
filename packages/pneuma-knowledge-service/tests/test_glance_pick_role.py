"""The `glance_pick` role: the fast lane's glance pick is its own call, so it is its own role.

Observed on a real library: the pick — one small structured call over an ~8 KB glance —
ran on the `recall` role at that model's default reasoning effort and did not come back
inside `DEFAULT_GLANCE_TIMEOUT_SECONDS`, so the pass degraded and the answer was built on
retrieval alone. The budget was right and the call was wrong. These tests pin the fix:
a role that borrows recall's MODEL but not its reasoning effort, and the two lane entries
that ask for it by name.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import _ROLE_REASONING_EFFORT, resolve_model_name


# ------------------------------------------------------------------ role resolution


def test_the_glance_pick_role_borrows_the_recall_model_when_its_own_field_is_empty():
    """One hop, like every other borrow: a deployment that already pointed recall at a fast
    model does not have to name a second one for this."""
    borrowed = Settings(llm_model="openai:base", llm_model_recall="openrouter:fast-test")
    assert resolve_model_name(borrowed, "glance_pick") == "openrouter:fast-test"


def test_its_own_setting_wins_over_the_recall_fallback():
    split = Settings(
        llm_model="openai:base",
        llm_model_recall="openrouter:fast-test",
        llm_model_glance_pick="openrouter:weak-fast",
    )
    assert resolve_model_name(split, "glance_pick") == "openrouter:weak-fast"
    assert resolve_model_name(split, "recall") == "openrouter:fast-test"  # unchanged


def test_it_falls_all_the_way_back_to_the_base_model():
    base = Settings(llm_model="openai:base")
    assert resolve_model_name(base, "glance_pick") == "openai:base"


def test_a_scripted_base_model_still_hard_overrides_the_role():
    scripted = Settings(
        llm_model="scripted:x.json", llm_model_glance_pick="openrouter:weak-fast"
    )
    assert resolve_model_name(scripted, "glance_pick") == "scripted:x.json"


def test_reasoning_is_pinned_off_and_is_not_a_knob():
    """A pick that has to think is not a glance. The effort is in code, not in Settings, for
    the same reason the Live Context pair's is: an effort a deployment could raise would
    change what the pass costs, and cheapness is the whole argument for running it."""
    assert _ROLE_REASONING_EFFORT["glance_pick"] == "none"
    assert not [f for f in Settings.model_fields if "glance_pick" in f and "model" not in f]


def test_the_pinned_effort_forks_the_model_cache_away_from_recall(monkeypatch):
    """`glance_pick` and `recall` resolve to the SAME spec by default, and the cache is keyed
    by spec — without the effort in the key, whichever built first would hand the other its
    reasoning setting, which is the one property these two differ on."""
    from pneuma_knowledge_service import wiring

    built: list[tuple[str, str | None]] = []

    def fake_build(name, settings, *, reasoning_effort=None, max_tokens=None):  # noqa: ANN001
        built.append((name, reasoning_effort))
        return object()

    monkeypatch.setattr(wiring, "_build_from_name", fake_build)
    ctx = SimpleNamespace(settings=Settings(llm_model="openai:one-model"), _chat_models={})
    get = wiring.AppContext.get_chat_model.__get__(ctx, wiring.AppContext)
    pick, recall = get("glance_pick"), get("recall")

    assert built == [("openai:one-model", "none"), ("openai:one-model", None)]
    assert pick is not recall
    assert get("glance_pick") is pick, "and the fork is still a cache"


def test_the_openrouter_provider_pin_reaches_the_new_role_like_every_other(monkeypatch):
    """The GPT-series pin (provider.order openai, no fallbacks) is applied by
    `_build_from_name` to every openrouter spec, so it cannot be lost by adding a role — and
    it must survive beside the effort rather than replace it."""
    from pneuma_knowledge_service import wiring

    seen: dict = {}

    def fake_init(model, **kwargs):  # noqa: ANN001
        seen["model"] = model
        seen.update(kwargs)
        return object()

    monkeypatch.setattr("langchain.chat_models.init_chat_model", fake_init)
    settings = Settings(
        llm_model="openrouter:openai/gpt-5.6-luna",
        OPENROUTER_API_KEY="k",
        openrouter_provider_order="openai",
        openrouter_allow_fallbacks=False,
    )
    ctx = SimpleNamespace(settings=settings, _chat_models={})
    wiring.AppContext.get_chat_model.__get__(ctx, wiring.AppContext)("glance_pick")

    assert seen["model"] == "openai/gpt-5.6-luna"
    assert seen["extra_body"] == {
        "reasoning": {"effort": "none"},
        "provider": {"order": ["openai"], "allow_fallbacks": False},
    }


# ------------------------------------------------------------------ the call sites


class _RoleRecordingContext(SimpleNamespace):
    """A context that answers `get_chat_model` with the role's own name, so a kwargs dict can
    be asserted on WHICH role each model argument came from."""

    def get_chat_model(self, role: str = "default") -> str:
        self.asked.append(role)
        return f"model:{role}"

    def get_reranker(self):
        return None

    def get_evidence_scorer(self):
        return None

    def langfuse_handler(self):
        return None


def _fake_ctx(**settings_overrides) -> _RoleRecordingContext:
    return _RoleRecordingContext(
        asked=[],
        settings=Settings(llm_model="openrouter:base", **settings_overrides),
        lexical=object(),
        vectors=object(),
        store=object(),
        embeddings=object(),
        media=None,
    )


async def test_the_api_fast_lane_asks_for_the_pick_role_and_passes_it_as_the_glance_model():
    from pneuma_knowledge_service.api.routes import v1

    ctx = _fake_ctx()
    plane = v1.ReadPlane(
        retrieval_user=UserId("u-1"),
        owner=UserId("u-1"),
        canonical_at=None,
        scope=None,
        snapshot=None,
    )
    kwargs = await v1._fast_recall_kwargs(
        ctx,
        v1.RecallIn(query="q", mode="fast"),
        plane,
        user_id="u-1",
        as_of=datetime(2026, 9, 17, tzinfo=timezone.utc),
        snapshot_ref=None,
        glance_inputs={"documents": []},
    )

    assert kwargs["glance_model"] == "model:glance_pick"
    # The answering call keeps its own roles: the pick is additive to this lane, never a
    # replacement for the model that reads the evidence or the one that writes the answer.
    assert kwargs["model"] == "model:recall"
    assert kwargs["answer_model"] == "model:answer"
    assert ctx.asked.count("glance_pick") == 1


class _EmptyCanonical:
    async def list(self, _user_id):  # noqa: ANN001
        return []


async def test_the_cli_fast_lane_asks_for_the_pick_role_too():
    """`pkc recall` runs the same lane, so it must route the same call — and `--evidence`,
    which builds no chat model at all, must still build none."""
    from pneuma_knowledge_service.cli import read as read_cmd

    ctx = _fake_ctx()
    ctx.canonical = _EmptyCanonical()
    rt = SimpleNamespace(ctx=ctx, user_id=UserId("u-1"))
    when = datetime(2026, 9, 17, tzinfo=timezone.utc)

    answering = await read_cmd._fast_kwargs(rt, as_of=when, style=None)
    assert answering["glance_model"] == "model:glance_pick"
    assert answering["model"] == "model:recall"

    ctx.asked.clear()
    evidence = await read_cmd._fast_kwargs(rt, as_of=when, style=None, evidence_only=True)
    assert evidence["glance_model"] is None and evidence["model"] is None
    assert ctx.asked == [], "the evidence path constructs no chat model, for any role"
