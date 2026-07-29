"""Scripted fake chat model (tests / keyless demos).

`PNEUMA_KNOWLEDGE_LLM_MODEL=scripted:<path>` loads a JSON script and replays it as a langchain
`BaseChatModel` over the compile tool loop — the same mechanism M3a's runner test uses,
lifted here so the worker, integration tests, and the e2e example can drive a real
compile with no provider key.

Script shape::

    {"turns": [
        [ {"name": "create_document", "args": {...}}, {"name": "finish_compile"} ],
        [ ... second (repair) round ... ],
        {"content": "shortest phrase answer"}
    ]}

Each turn is one assistant step. A turn that is a *list* is a set of tool calls emitted
together; a turn that is a *dict with "content"* is a plain text answer with no tool
calls. Which shape a consumer needs:

- list of tool calls, ``name`` = a real tool → the compile / briefing-ask tool loops.
- list of ONE tool call, ``name`` = a **pydantic class name** → a structured-output call
  (``model.with_structured_output(Model)``). langchain implements that over tool calling,
  and it matches the returned call by the schema's class name, so ``name`` must equal the
  class EXACTLY (``"SuggestionBatch"``, not ``"suggestion_batch"``); a mismatch is a hard failure, not a
  parse-to-None. This works because `bind_tools` is overridden below, which is what gets
  past `BaseChatModel`'s NotImplementedError guard. The AI suggestion path uses this shape.
- dict with ``content`` → a plain text answer (M4 fast/deep selector, deep verification
  verdict, briefing-ask final answer, the suggestion ``want_more`` expansion).

After the last scripted turn the model returns a plain ``"done"`` message — which under
``with_structured_output(..., include_raw=True)`` arrives as ``parsed=None``, i.e. an
exhausted script degrades a suggestion evaluation to silence rather than to an error.

Cursor advances across invocations, so one script drives one flow.
"""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

_ids = count()


class ScriptedChatModel(BaseChatModel):
    """Replays a fixed list of tool-call turns; ignores the prompt (mechanism, not a
    real model). `turns[i]` is the list of tool calls for assistant step i."""

    # A turn is either a list of tool-call dicts, or a dict with a "content" text answer.
    turns: list[Any] = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
        return self

    def _next_result(self):
        """The next scripted turn as a ChatResult, advancing the cursor.

        Shared by `_generate` and `_agenerate` so both faces replay ONE cursor — a script
        must produce the same sequence whichever face the caller uses."""
        # Include provider cache fields (zeroed) so recall's cache passthrough is exercised.
        usage = {
            "input_tokens": 12,
            "output_tokens": 6,
            "total_tokens": 18,
            "input_token_details": {"cache_read": 0, "cache_creation": 0},
        }
        if self._cursor < len(self.turns):
            raw = self.turns[self._cursor]
            self._cursor += 1
            if isinstance(raw, dict) and "content" in raw:
                msg = AIMessage(content=str(raw["content"]), usage_metadata=usage)
            else:
                calls = [
                    {
                        "name": c["name"],
                        "args": c.get("args", {}),
                        "id": f"call-{next(_ids)}",
                        "type": "tool_call",
                    }
                    for c in raw
                ]
                msg = AIMessage(content="", tool_calls=calls, usage_metadata=usage)
        else:
            msg = AIMessage(content="done", usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return self._next_result()

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # Explicit async face. BaseChatModel's default `_agenerate` delegates `_generate`
        # to a thread pool; relying on that would make every keyless test's model call a
        # thread hop with a cursor mutated off-loop. This model is pure in-memory replay —
        # there is nothing to await, so answer directly on the caller's loop.
        return self._next_result()


def load_scripted_model(path: str) -> ScriptedChatModel:
    """Build a ScriptedChatModel from a JSON script file (see module docstring)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    turns = data.get("turns", [])
    if not isinstance(turns, list):
        raise ValueError(f"scripted model {path!r}: 'turns' must be a list")
    return ScriptedChatModel(turns=turns)
