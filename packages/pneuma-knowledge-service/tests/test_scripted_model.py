"""Scripted model loader + build_chat_model scripted path (keyless, no middleware)."""

from __future__ import annotations

import json

from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel, load_scripted_model
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_chat_model


def test_load_scripted_model_from_file(tmp_path):
    script = tmp_path / "s.json"
    script.write_text(
        json.dumps(
            {"turns": [[{"name": "create_document", "args": {"path": "p"}}, {"name": "finish_compile"}]]}
        ),
        encoding="utf-8",
    )
    model = load_scripted_model(str(script))
    assert isinstance(model, ScriptedChatModel)
    assert model.turns[0][0]["name"] == "create_document"


def test_build_chat_model_scripted_path(tmp_path):
    script = tmp_path / "s.json"
    script.write_text(json.dumps({"turns": []}), encoding="utf-8")
    model = build_chat_model(Settings(llm_model=f"scripted:{script}"))
    assert isinstance(model, ScriptedChatModel)


async def test_scripted_model_emits_tool_calls_then_done():
    # Driven through the ASYNC face (`ainvoke` → `_agenerate`): that is what core's
    # recall/compile loops now use, and this model implements it explicitly rather than
    # inheriting BaseChatModel's thread-pool delegation.
    model = ScriptedChatModel(
        turns=[[{"name": "finish_compile", "args": {}}]]
    )
    first = await model.ainvoke("ignored")
    assert first.tool_calls and first.tool_calls[0]["name"] == "finish_compile"
    second = await model.ainvoke("ignored")
    assert not second.tool_calls and second.content == "done"
