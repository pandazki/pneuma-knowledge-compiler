"""Compile image delivery is explicit and capability-aware."""

from types import SimpleNamespace

from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.workers.compile_worker import resolve_compile_image_mode


def test_explicit_image_mode_wins_over_model_profile():
    model = SimpleNamespace(profile={"image_inputs": False})

    assert resolve_compile_image_mode(Settings(compile_image_mode="native"), model) == "native"
    assert resolve_compile_image_mode(Settings(compile_image_mode="caption"), model) == "caption"


def test_auto_uses_native_only_when_active_model_declares_image_inputs():
    visual = SimpleNamespace(profile={"image_inputs": True})
    text_only = SimpleNamespace(profile={"image_inputs": False})
    unknown = SimpleNamespace(profile=None)
    settings = Settings(compile_image_mode="auto")

    assert resolve_compile_image_mode(settings, visual) == "native"
    assert resolve_compile_image_mode(settings, text_only) == "caption"
    assert resolve_compile_image_mode(settings, unknown) == "caption"


def test_auto_knows_the_gpt_5_6_family_is_multimodal_even_through_openrouter():
    settings = Settings(
        compile_image_mode="auto",
        llm_model_compile="openrouter:openai/gpt-5.6-terra",
    )

    assert resolve_compile_image_mode(settings, SimpleNamespace(profile=None)) == "native"
