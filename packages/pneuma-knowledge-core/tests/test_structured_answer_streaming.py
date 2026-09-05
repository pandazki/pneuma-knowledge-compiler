"""A structured answer must stream like any other — one delta per token, not one at the end.

A `text` answer streams because the lane hands the model's own `astream` to the sink. A
`structured` answer used to arrive as ONE "delta" carrying the finished JSON, and the reason
was mechanical rather than accidental: `with_structured_output(..., include_raw=True)` returns
`RunnableMap(raw=llm) | RunnableWithFallbacks(parser)`, and `RunnableWithFallbacks` implements
no `transform`/`atransform`. Streaming that CHAIN therefore falls back to the default "buffer
the whole input stream, then run" — the model's chunks are folded into one message before the
parser is even tried, and the chain yields exactly one value, at the very end. A reader
watching it saw nothing for the whole answer and then the whole answer.

The fix streams the MODEL and hands the merged message to the chain's own parser, so the
deltas are real and the parsing is byte-for-byte the code the non-streaming branch runs.
`split_structured` is what takes the chain apart, and both halves of it are pinned here: the
shape it expects (against the langchain version actually installed, in the service tests where
langchain-openai lives), and its refusal to crash on any other shape.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from operator import itemgetter

import pytest

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda, RunnableMap, RunnablePassthrough

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.fast import (
    StructuredRecallAnswer,
    fast_recall,
    message_text,
    split_structured,
)

from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings
from test_fast_stage_timing import _Model

_USER = UserId("u-structured-stream")
_AS_OF = datetime(2026, 8, 26, 9, 0, 0, tzinfo=timezone.utc)

#: What the provider writes, token by token. `answer_kind` comes FIRST on purpose: it is the
#: field the real schema puts before the answer, and a reader looking for `"answer"` must not
#: mistake `"answer_kind"` for it.
_PAYLOAD = json.dumps(
    {"answer_kind": "fact", "answer": "林薇负责采购", "citations": []},
    ensure_ascii=False,
)


class _JsonStreamingModel(_Model):
    """A model that writes JSON one character at a time, wearing langchain-openai's shape.

    `with_structured_output(include_raw=True)` is rebuilt here exactly as langchain-openai
    builds it — a raw map, then a passthrough-assign parser behind fallbacks — because the
    thing under test is precisely how that shape streams. A fake that returned some simpler
    runnable would pass while the real one hung.
    """

    payload: str = _PAYLOAD
    streamed: int = 0

    async def _astream(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001, ARG002
        self.streamed += 1
        for index, piece in enumerate(self.payload):
            last = index == len(self.payload) - 1
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=piece,
                    usage_metadata=(
                        {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
                        if last
                        else None
                    ),
                )
            )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.payload))]
        )

    def with_structured_output(self, schema, *, include_raw=False, **kw):  # noqa: ANN001, ARG002
        parser = RunnableLambda(
            lambda message: schema.model_validate_json(message_text(message.content))
        )
        if not include_raw:
            return self | parser
        assign = RunnablePassthrough.assign(
            parsed=itemgetter("raw") | parser, parsing_error=lambda _: None
        )
        none = RunnablePassthrough.assign(parsed=lambda _: None)
        return RunnableMap(raw=self) | assign.with_fallbacks(
            [none], exception_key="parsing_error"
        )


class _OpaqueStructuredModel(_JsonStreamingModel):
    """A structured chain of a shape nothing here recognises — a future langchain, say."""

    def with_structured_output(self, schema, *, include_raw=False, **kw):  # noqa: ANN001, ARG002
        model = self

        async def whole(_messages):  # noqa: ANN001
            merged = None
            async for chunk in model._astream(_messages):
                message = chunk.message
                merged = message if merged is None else merged + message
            return {
                "raw": merged,
                "parsed": schema.model_validate_json(message_text(merged.content)),
                "parsing_error": None,
            }

        return RunnableLambda(whole)


def _kwargs(model):
    index = FakeClaimIndex(
        [ClaimStub("a1f3", "memory/people/lin-wei.md", "林薇负责恒印印刷的对接")]
    )
    return dict(
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=model,
        fast_paths=(),
    )


# ------------------------------------------------------------------ the chain, taken apart


def test_the_split_finds_the_model_and_the_parser_inside_the_structured_chain():
    model = _JsonStreamingModel()
    chain = model.with_structured_output(StructuredRecallAnswer, include_raw=True)
    inner, parser = split_structured(chain)
    assert inner is model
    assert parser is not None


def test_an_unrecognised_chain_degrades_instead_of_crashing():
    """A langchain that reorganises this internally must cost the deltas, never the answer."""
    chain = _OpaqueStructuredModel().with_structured_output(
        StructuredRecallAnswer, include_raw=True
    )
    assert split_structured(chain) == (None, None)


# ------------------------------------------------------------------ the lane


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("citations,kind,expected", [
    (["[cite: s99 ¶0]"], "fact", "invalid_citations"),
    ([], "fact", None),
    ([], "no_record", None),
    ([], "inference", None),
])
async def test_rejected_citations_are_visible_without_a_second_answer_call(stream, citations, kind, expected):
    model = _JsonStreamingModel(payload=json.dumps({
        "answer_kind": kind, "answer": "Synthetic answer", "citations": citations,
    }))
    result = await fast_recall(
        _USER, "Synthetic question", answer_format="structured",
        on_token=(lambda token: None) if stream else None, **_kwargs(model),
    )
    assert result.answer == "Synthetic answer"
    assert result.answer_kind == kind
    assert result.answer_format_degraded == expected
    stage = next(stage for stage in result.stages if stage.name == "answer")
    assert stage.preview["turns"] == 1
    assert stage.detail == expected
    assert stage.status == ("degraded" if expected else "ran")


async def test_a_structured_answer_streams_one_delta_per_token():
    tokens: list[str] = []
    fa = await fast_recall(
        _USER,
        "林薇现在负责什么",
        answer_format="structured",
        on_token=tokens.append,
        **_kwargs(_JsonStreamingModel()),
    )
    # N deltas in, N frames out — and joined, they are the raw JSON the provider wrote.
    assert len(tokens) == len(_PAYLOAD)
    assert "".join(tokens) == _PAYLOAD
    # Parsed exactly as the non-streaming branch parses it: the answer, not the JSON.
    assert fa.answer_text == "林薇负责采购"
    assert fa.answer_format_degraded is None


async def test_an_unrecognised_chain_still_answers_with_one_late_delta():
    """The fall-back is the historical whole-chain stream: one value, at the end. Worse to
    watch, identical to read — which is the right way for an unknown shape to fail."""
    tokens: list[str] = []
    fa = await fast_recall(
        _USER,
        "林薇现在负责什么",
        answer_format="structured",
        on_token=tokens.append,
        **_kwargs(_OpaqueStructuredModel()),
    )
    assert tokens == [_PAYLOAD]
    assert fa.answer_text == "林薇负责采购"


async def test_a_structured_answer_with_no_sink_never_streams_at_all():
    """`on_token=None` must not quietly become "stream and re-join": the historical lane
    makes one `ainvoke`, and that is what a deployment that asked for nothing still gets."""
    model = _JsonStreamingModel()
    await fast_recall(
        _USER, "q", answer_format="structured", **_kwargs(model)
    )
    assert model.streamed == 0


async def test_a_structured_call_that_hangs_still_honours_its_timeout():
    """The timeout wraps the streamed drain exactly as it wrapped the invoke, so a provider
    that stalls mid-JSON degrades to the text contract instead of holding the lane open."""

    class _Hanging(_JsonStreamingModel):
        async def _astream(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001, ARG002
            yield ChatGenerationChunk(message=AIMessageChunk(content='{"answer":"林'))
            # Long enough that the 50 ms timeout is what ends the drain, short enough that
            # the text fall-back — which runs on this same model — does not slow the suite.
            await asyncio.sleep(0.3)

    fa = await fast_recall(
        _USER,
        "林薇现在负责什么",
        answer_format="structured",
        structured_answer_timeout=0.05,
        on_token=lambda _t: None,
        **_kwargs(_Hanging()),
    )
    assert fa.answer_format_degraded == "timeout"


@pytest.mark.parametrize("stream", [False, True])
async def test_inline_citations_cannot_bypass_structured_validation(stream):
    model = _JsonStreamingModel(payload=json.dumps({
        "answer_kind": "fact", "answer": "Synthetic answer [cite: s99 ¶0]",
        "citations": [],
    }))
    result = await fast_recall(
        _USER, "Synthetic question", answer_format="structured",
        on_token=(lambda token: None) if stream else None, **_kwargs(model),
    )
    assert result.answer_text == result.answer == "Synthetic answer"
    assert result.answer_format_degraded == "invalid_citations"
    assert next(stage for stage in result.stages if stage.name == "answer").preview["turns"] == 1
