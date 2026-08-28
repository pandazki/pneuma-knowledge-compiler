"""The one assumption `split_structured` makes, pinned against the langchain actually installed.

core streams a structured answer by taking `with_structured_output(..., include_raw=True)`
apart — the chat model out of the raw map, the parser out of the tail — because streaming the
whole chain cannot work: its tail is a `RunnableWithFallbacks`, which implements no
`transform`, so the sequence buffers every chunk into one value and yields once. That is a
fact about langchain-openai's construction, and core cannot test it: core has no middleware
dependency (`langchain-openai` lives here, with the adapters that use it).

So it is tested here, keylessly — building the chain needs no network, only a client — and it
fails LOUDLY the day the shape changes. When it does, nothing breaks for a user: the split
returns `(None, None)` and the lane falls back to the historical whole-chain stream, which
costs the deltas and not the answer. This test is what turns that quiet degradation into a
visible one.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from pneuma_knowledge_core.recall.fast import split_structured


class _Answer(BaseModel):
    answer: str
    citations: list[str] = []


def _chain():
    # A placeholder credential: constructing the client and the chain touches no network.
    return ChatOpenAI(model="gpt-4o-mini", api_key="not-a-key").with_structured_output(
        _Answer, include_raw=True
    )


def test_the_split_still_finds_the_model_inside_langchain_openais_structured_chain():
    model, parser = split_structured(_chain())
    assert model is not None and hasattr(model, "astream")
    assert parser is not None and hasattr(parser, "ainvoke")


def test_the_tail_of_that_chain_is_why_the_whole_chain_cannot_be_streamed():
    """`RunnableWithFallbacks` has no `transform`/`atransform`, so `RunnableSequence` falls
    back to buffering its whole input before running it — one output value, at the end."""
    tail = _chain().last
    assert "transform" not in vars(type(tail))
    assert "atransform" not in vars(type(tail))


def test_a_chain_of_any_other_shape_is_refused_rather_than_guessed_at():
    assert split_structured(RunnableLambda(lambda x: x)) == (None, None)
    assert split_structured(None) == (None, None)
