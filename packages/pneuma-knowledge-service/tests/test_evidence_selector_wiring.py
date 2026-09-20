"""Who selects `select`'s evidence: the four settings, the build, and the lane kwargs.

Off is the whole point of the default, so the first thing pinned is that a deployment which
says nothing gets the model selector and a `None` scorer on the lane — byte-for-byte the
path the fast lane has always taken. The rest is the misconfiguration: asking for a scorer
without naming one (or naming a provider nothing implements, or having no key for it) must
raise with the setting named, because a misconfiguration that silently answers with the
OTHER selector is the expensive kind.

Keyless: no adapter here opens a connection, and the scorer is built but never called.
"""

from __future__ import annotations

import textwrap
from datetime import datetime, timezone

import pytest

from pneuma_knowledge_core.domain.ids import UserId

from pneuma_knowledge_service.adapters.typesafe_scorer import TypeSafeEvidenceScorer
from pneuma_knowledge_service.engine.resolve import resolve_engine
from pneuma_knowledge_service.settings import Settings, get_settings
from pneuma_knowledge_service.wiring import AppContext


def _ctx(**overrides) -> AppContext:
    settings = Settings(llm_model="scripted:unused", **overrides)
    return AppContext(
        settings=settings, store=None, canonical=None, lexical=None,
        vectors=None, embeddings=None, registry=None,
    )


# ------------------------------------------------------------------ the default is off


def test_a_deployment_that_says_nothing_keeps_the_model_selector():
    settings = Settings(llm_model="scripted:unused")
    assert settings.recall_evidence_selector == "model"
    assert settings.recall_evidence_scorer == ""
    assert settings.recall_select_score_floor == 0.5
    assert settings.recall_selection_timeout_s == 30.0
    assert _ctx().get_evidence_scorer() is None
    # Even with a scorer named: the selector switch is what decides, so a deployment can
    # keep the spec around while it is measuring without the lane changing under it.
    assert _ctx(recall_evidence_scorer="typesafe:jev-1.13-20260917").get_evidence_scorer() is None


# ------------------------------------------------------------------ building the scorer


def test_the_typesafe_spec_builds_one_adapter_and_reuses_it():
    ctx = _ctx(
        recall_evidence_selector="scorer",
        recall_evidence_scorer="typesafe:jev-1.13-20260917",
        OPENROUTER_API_KEY="k",
    )
    scorer = ctx.get_evidence_scorer()
    assert isinstance(scorer, TypeSafeEvidenceScorer)
    # The vendor prefix is the adapter's, not the setting's: the deployment names the model.
    assert scorer._model == "typesafe/jev-1.13-20260917"
    assert ctx.get_evidence_scorer() is scorer  # built once; it holds an httpx client


@pytest.mark.parametrize(
    "overrides",
    [
        {"recall_evidence_selector": "scorer", "OPENROUTER_API_KEY": "k"},
        {
            "recall_evidence_selector": "scorer",
            "recall_evidence_scorer": "somebody-else:model-1",
            "OPENROUTER_API_KEY": "k",
        },
        {
            "recall_evidence_selector": "scorer",
            "recall_evidence_scorer": "typesafe:",
            "OPENROUTER_API_KEY": "k",
        },
        {
            "recall_evidence_selector": "scorer",
            "recall_evidence_scorer": "typesafe:jev-1.13-20260917",
            "OPENROUTER_API_KEY": "",
        },
    ],
)
def test_asking_for_a_scorer_the_deployment_cannot_build_raises_naming_the_setting(overrides):
    with pytest.raises(RuntimeError) as exc:
        _ctx(**overrides).get_evidence_scorer()
    assert "recall_evidence_scorer" in str(exc.value)


async def test_the_context_closes_the_scorer_it_built():
    ctx = _ctx(
        recall_evidence_selector="scorer",
        recall_evidence_scorer="typesafe:jev-1.13-20260917",
        OPENROUTER_API_KEY="k",
    )
    scorer = ctx.get_evidence_scorer()
    client = scorer._ensure_client()
    await scorer.aclose()
    assert client.is_closed


# ------------------------------------------------------------------ what the lane is handed


async def test_the_fast_lane_kwargs_carry_the_selector_the_deployment_chose(monkeypatch):
    from types import SimpleNamespace

    from pneuma_knowledge_service.api.routes import v1

    async def _no_profile(ctx, user):  # noqa: ANN001
        return None

    monkeypatch.setattr(v1, "_render_profile", _no_profile)

    def ctx_for(settings: Settings, scorer):
        return SimpleNamespace(
            settings=settings,
            lexical=object(),
            vectors=object(),
            store=object(),
            embeddings=object(),
            media=None,
            get_chat_model=lambda role="default": f"model:{role}",
            get_reranker=lambda: None,
            get_evidence_scorer=lambda: scorer,
            langfuse_handler=lambda: None,
        )

    plane = v1.ReadPlane(
        retrieval_user=UserId("u-1"),
        owner=UserId("u-1"),
        canonical_at=None,
        scope=None,
        snapshot=None,
    )

    async def kwargs_for(settings: Settings, scorer):
        return await v1._fast_recall_kwargs(
            ctx_for(settings, scorer),
            v1.RecallIn(query="q", mode="fast"),
            plane,
            user_id="u-1",
            as_of=datetime(2026, 9, 20, tzinfo=timezone.utc),
            snapshot_ref=None,
            glance_inputs={"documents": []},
        )

    off = await kwargs_for(Settings(llm_model="scripted:unused"), None)
    assert off["evidence_scorer"] is None
    assert off["select_score_floor"] == 0.5
    assert off["evidence_selection_timeout"] == 30.0

    sentinel = object()
    on = await kwargs_for(
        Settings(
            llm_model="scripted:unused",
            recall_select_score_floor=0.62,
            recall_selection_timeout_s=8.0,
        ),
        sentinel,
    )
    assert on["evidence_scorer"] is sentinel
    assert on["select_score_floor"] == 0.62
    assert on["evidence_selection_timeout"] == 8.0


# ------------------------------------------------------------------ the engine round trip


def test_the_four_keys_resolve_from_an_engine_recall_yaml(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "PNEUMA_KNOWLEDGE_RECALL_EVIDENCE_SELECTOR",
        "PNEUMA_KNOWLEDGE_RECALL_EVIDENCE_SCORER",
        "PNEUMA_KNOWLEDGE_RECALL_SELECT_SCORE_FLOOR",
        "PNEUMA_KNOWLEDGE_RECALL_SELECTION_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)
    engine = tmp_path / "engine"
    (engine / "recall").mkdir(parents=True)
    (engine / "recall" / "recall.yaml").write_text(
        textwrap.dedent(
            """\
            evidence_selector: scorer
            evidence_scorer: "typesafe:jev-1.13-20260917"
            select_score_floor: 0.62
            selection_timeout_s: 8
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", str(engine))

    settings = get_settings()
    assert settings.recall_evidence_selector == "scorer"
    assert settings.recall_evidence_scorer == "typesafe:jev-1.13-20260917"
    assert settings.recall_select_score_floor == 0.62
    assert settings.recall_selection_timeout_s == 8.0

    resolved = resolve_engine(engine, {})
    assert resolved.resolution["recall.evidence_selector"] == "engine"
    assert resolved.values["recall.select_score_floor"] == 0.62


def test_process_env_still_outranks_the_engine_file_for_these_keys(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    engine = tmp_path / "engine"
    (engine / "recall").mkdir(parents=True)
    (engine / "recall" / "recall.yaml").write_text(
        "evidence_selector: scorer\nselect_score_floor: 0.62\n", encoding="utf-8"
    )
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", str(engine))
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_RECALL_SELECT_SCORE_FLOOR", "0.8")
    settings = get_settings()
    assert settings.recall_evidence_selector == "scorer"
    assert settings.recall_select_score_floor == 0.8
