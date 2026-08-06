"""L2 dispatch degrades `semantic` mechanically when no compile model resolves.

2026-08-05: the scaffold's keyless path used to pin CHUNK_STRATEGY=sentence into the
process environment, which the console then honestly displayed as an env lock over the
engine file's `semantic`. The pin is gone; this is the dispatch-level guarantee that
replaced it — a keyless process (every model role resolved empty) must take the
mechanical branch on its own, leaving the engine file the visible truth.
"""

from __future__ import annotations

from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_service.wiring import full_l2_chunks


def _ctx(**settings_over) -> SimpleNamespace:
    values = dict(
        chunk_strategy="semantic",
        chunk_size=768,
        chunk_overlap=128,
        # Keyless: no base model, every role override empty, no key.
        openrouter_api_key="",
        llm_model="",
        llm_model_compile="",
        llm_model_recall="",
        llm_model_deep="",
        llm_model_skill="",
        llm_model_evolve="",
        llm_model_live_context="",
        llm_model_challenge="",
    )
    values.update(settings_over)
    ctx = SimpleNamespace(settings=SimpleNamespace(**values))
    # A keyless dispatch must never ask for a chat model; make doing so loud.
    def _boom(role="default"):
        raise AssertionError("keyless dispatch must not build a chat model")
    ctx.get_chat_model = _boom
    return ctx


async def test_semantic_without_any_model_takes_the_mechanical_branch():
    blocks = [
        NormalizedBlock(index=0, text="One short block about the project."),
        NormalizedBlock(index=1, text="Another short block about the plan."),
    ]
    structure = StructureMap(
        sections=[SectionSpan(path=["S"], start_block=0, end_block=1)]
    )
    chunks = await full_l2_chunks(
        _ctx(),
        SourceId("11111111-1111-1111-1111-111111111111"),
        blocks,
        structure,
        UserId("u-1"),
    )
    assert chunks, "mechanical chunking still produces chunks"


async def test_openrouter_spec_without_a_key_is_equally_keyless():
    """The engine file may keep naming its openrouter models — without a key this
    process still takes the mechanical branch instead of crashing on model build."""
    ctx = _ctx(
        llm_model="openrouter:test/model",
        llm_model_compile="openrouter:test/strong",
        openrouter_api_key="",
    )
    blocks = [NormalizedBlock(index=0, text="A block about the plan.")]
    structure = StructureMap(sections=[SectionSpan(path=["S"], start_block=0, end_block=0)])
    chunks = await full_l2_chunks(
        ctx, SourceId("11111111-1111-1111-1111-111111111111"), blocks, structure, UserId("u-1")
    )
    assert chunks


def test_usable_model_name_reports_the_keyless_state():
    from pneuma_knowledge_service.wiring import usable_model_name

    keyless = _ctx(llm_model="openrouter:test/model", openrouter_api_key="").settings
    assert usable_model_name(keyless, "compile") == ""
    keyed = _ctx(llm_model="openrouter:test/model", openrouter_api_key="k").settings
    assert usable_model_name(keyed, "compile") == "openrouter:test/model"
    local = _ctx(llm_model="ollama:llama3", openrouter_api_key="").settings
    assert usable_model_name(local, "compile") == "ollama:llama3"
