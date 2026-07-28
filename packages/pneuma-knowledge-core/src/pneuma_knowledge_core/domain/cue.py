"""AI Cue domain: the closed vocabularies + the card shapes for context_stream 提词.

A cue is what the system volunteers while listening to a live conversation — nobody
asked. That inverted trigger direction is the whole reason this file exists separately
from the recall answer shapes: the output is not one answer string but zero-or-a-few
structured cards, and "zero" is the steady state.

Two closed vocabularies live here, following the `INTAKE_ARCHETYPES` precedent
(`domain/intake.py` + `GET /v1/intake/archetypes`): the enumeration is defined ONCE in
core and served over an endpoint, so the core prompt, the service route and the client
cannot drift into three private copies. Per architecture.md:123-124, adding a value to
either vocabulary needs the project owner's sign-off — it is not a free branch.

`CueFocus`'s `owner` / `other` reuse `domain/source.py`'s `SpeakerRole` words on
purpose; context_stream already speaks that vocabulary and a second synonym would be a
second thing to keep in sync.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .canonical import Citation

# Where the model points its attention. NOT a transcript filter: the full transcript is
# always sent (filtering by speaker destroys the context needed to understand any of it).
# See recall/cue.py's contract for how each value is expressed.
CueFocus = Literal["general", "owner", "other"]

# What kind of card this is: an explanation of something named, or an answer to something
# asked. The client renders the two differently.
CueKind = Literal["concept", "fact"]


class CueFocusOption(BaseModel):
    key: CueFocus
    label: str
    summary: str


class CueKindOption(BaseModel):
    key: CueKind
    label: str
    summary: str


# Ordered; `general` first because it is the default posture.
CUE_FOCUSES: list[CueFocusOption] = [
    CueFocusOption(
        key="general",
        label="通用",
        summary="整段对话里任何值得提示的概念或事实，不区分是谁说的",
    ),
    CueFocusOption(
        key="owner",
        label="仅我说的",
        summary="只为本人说出的内容提词，参与者发言仅作理解上下文",
    ),
    CueFocusOption(
        key="other",
        label="仅对方说的",
        summary="只为参与者说出的内容提词，本人发言仅作理解上下文",
    ),
]

CUE_KINDS: list[CueKindOption] = [
    CueKindOption(
        key="concept",
        label="概念解释",
        summary="对话里出现了知识库里有的概念/人/事，卡片解释它是什么",
    ),
    CueKindOption(
        key="fact",
        label="事实问答",
        summary="对话里出现了知识库能直接回答的问题，卡片给出答案",
    ),
]

_FOCUS_BY_KEY = {f.key: f for f in CUE_FOCUSES}
_KIND_BY_KEY = {k.key: k for k in CUE_KINDS}


def focus_option(key: str) -> CueFocusOption:
    """The CueFocusOption for a key. Raises ValueError on an unknown value — a focus the
    vocabulary does not contain is a bug in the caller, never a silent fallback."""
    option = _FOCUS_BY_KEY.get(key)
    if option is None:
        raise ValueError(f"unknown cue focus: {key!r}")
    return option


def kind_option(key: str) -> CueKindOption:
    """The CueKindOption for a key. Raises ValueError on an unknown value."""
    option = _KIND_BY_KEY.get(key)
    if option is None:
        raise ValueError(f"unknown cue kind: {key!r}")
    return option


# ------------------------------------------------------------------- the card shapes


class Cue(BaseModel):
    """One card, exactly as the model emits it (body still carries `[cite: …]` markers).

    This is the structured-output schema — the class NAME reaches the provider as the tool
    name, so renaming it changes the wire contract."""

    kind: CueKind
    title: str  # the concept named, or the question being answered
    body: str  # the explanation / answer, with inline `[cite: …]` markers
    trigger: str  # the transcript fragment that set this card off (UI highlight)
    confidence: int = Field(ge=1, le=10)


class CueBatch(BaseModel):
    """The model's whole emission for one evaluation.

    `max_length=5` is a MECHANICAL ceiling on what the model can physically emit (a longer
    list becomes a `parsing_error` under `include_raw=True`, i.e. silence). It is a
    different thing from the server-side `max_cues` cap, which sorts by confidence and
    truncates AFTER the gates — that one is tunable per request, this one is not."""

    cues: list[Cue] = Field(default_factory=list, max_length=5)


class ResolvedCue(BaseModel):
    """A cue as it leaves the server: handles gone, citations structured.

    `body` has every `[cite: …]` marker STRIPPED and the provenance lifted into
    `citations` with real source ids. The client never sees an `sNN` handle — handles are
    query-local and are re-assigned every evaluation, so a handle that outlived its
    evaluation would point at a different source (see recall/citation_alias.py)."""

    kind: CueKind
    title: str
    body: str
    trigger: str
    confidence: int = Field(ge=1, le=10)
    citations: list[Citation] = Field(default_factory=list)
