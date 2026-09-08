"""Inspect real LangChain/OpenAI HTTP bodies without contacting a provider."""

import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from pneuma_knowledge_core.domain.canonical import Citation
from pneuma_knowledge_core.domain.ids import AnchorId, SourceId
from pneuma_knowledge_core.recall.fast import (
    RetrievedClaim, answer_with_selector, answer_with_structured, select_evidence,
)
from pneuma_knowledge_service.wiring import _build_from_name


@pytest.mark.parametrize("mode", ["text", "structured", "deliberated", "stream", "selection"])
@pytest.mark.parametrize("effort", [None, "high"])
async def test_reasoning_and_provider_controls_reach_the_wire(mode, effort):
    model = _build_from_name("openrouter:openai/synthetic-model", SimpleNamespace(
        llm_timeout=5, llm_max_retries=0,
        openrouter_api_key="synthetic-not-a-credential",
        openrouter_provider_order="openai", openrouter_allow_fallbacks=False,
    ))
    model.extra_body["reasoning"] = {"effort": "low", "exclude": True}
    original = copy.deepcopy(model.extra_body)
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        content = {"answer_kind": "fact", "answer": "Canada", "citations": []}
        if mode == "selection":
            content = {}
        elif mode == "deliberated":
            content["deliberation"] = "The supplied claim names Canada."
        text = "Canada" if mode == "text" else json.dumps(content)
        envelope = {"id": "synthetic", "model": "synthetic-model", "created": 1}
        if payload.get("stream"):
            chunks = [
                {**envelope, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None},
                ]},
                {**envelope, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "stop"},
                ]},
            ]
            data = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, text=data, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={
            **envelope, "object": "chat.completion", "choices": [{
                "index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop",
            }],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model.root_async_client = AsyncOpenAI(
            api_key="synthetic-not-a-credential", base_url="https://synthetic.invalid/v1",
            http_client=client, max_retries=0,
        )
        model.async_client = model.root_async_client.chat.completions
        claims = [RetrievedClaim(
            anchor=AnchorId("aa11"), document_path="people/alice.md", section_path=("Travel",),
            text="Alice visited Canada.", score=1.0,
            citations=(Citation(source_id=SourceId("source-a"), block_start=0, block_end=0),),
        )]
        tokens = []
        if mode == "selection":
            selected, _, degraded = await select_evidence(
                model, "Where did Alice visit?", claims=claims, episode_summaries=[],
                windows=[], reasoning_effort=effort,
            )
            assert selected is not None and degraded is None
        else:
            kwargs = {"as_of": datetime(2026, 1, 1, tzinfo=timezone.utc), "reasoning_effort": effort}
            if mode == "text":
                result = await answer_with_selector(model, "Where did Alice visit?", claims, **kwargs)
            else:
                result = await answer_with_structured(
                    model, "Where did Alice visit?", claims, **kwargs,
                    deliberate=mode == "deliberated", on_token=tokens.append if mode == "stream" else None,
                )
                assert result[5] is None
            assert result[0] == "Canada"
            if mode == "stream":
                assert tokens

    assert len(requests) == 1  # no silent text fallback after a structured failure
    assert requests[0]["provider"] == original["provider"]
    assert requests[0]["reasoning"] == {"effort": effort or "low", "exclude": True}
    assert model.extra_body == original  # the shared model's defaults never change
