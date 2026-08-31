"""Live Context domain: closed vocabularies and grounded suggestion shapes.

A suggestion is what the system volunteers while processing an incoming workstream — nobody
asked. That inverted trigger direction is why this file exists separately
from the recall answer shapes: the output is not one answer string but zero-or-a-few
structured cards, and "zero" is the steady state.

Two closed vocabularies live here, following the `INTAKE_ARCHETYPES` precedent
(`domain/intake.py` + `GET /v1/intake/archetypes`): the enumeration is defined ONCE in
core and served over an endpoint, so the core prompt, the service route and the client
cannot drift into three private copies. Per architecture.md:123-124, adding a value to
either vocabulary needs the project owner's sign-off — it is not a free branch.

`ContextFocus`'s `owner` / `other` reuse `domain/source.py`'s `SpeakerRole` words on
purpose; context_stream already speaks that vocabulary and a second synonym would be a
second thing to keep in sync.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .canonical import Citation

# Where the model points its attention. NOT a transcript filter: the full transcript is
# always sent (filtering by speaker destroys the context needed to understand any of it).
# See recall/suggestion.py's contract for how each value is expressed.
ContextFocus = Literal["general", "owner", "other"]

# HOW LATENT a question discover may write. A real policy field, not a bundle of numbers —
# because the presets never were only numbers. Measured live on the eager preset, a single
# turn handing work to an unnamed role was skipped: the confidence floors were low, and the
# contract still said the same thing about what is worth looking up, so a role named without
# a person was not a question the stage recognised. A density that only moves thresholds
# moves how MUCH gets through, never WHAT is asked.
#
# Under the discover principle — write the one question most worth asking right now — there
# is exactly one thing left for a posture to vary: how far below the surface that question
# may sit. `quiet` takes only questions somebody asked aloud, `balanced` questions the
# conversation clearly implies, `eager` also questions the room does not yet realise it
# should ask. It varies exactly one clause of the discover contract
# (`recall.live.discover.mining.*`) and NOTHING else — not the skip vocabulary, not the
# ledger rule, and deliberately not the pick contract: how honestly a card is delivered is
# not a density matter.
ContextDensity = Literal["eager", "balanced", "quiet"]

#: Ordered, the default in the middle.
CONTEXT_DENSITIES: tuple[ContextDensity, ...] = ("eager", "balanced", "quiet")
DEFAULT_DENSITY: ContextDensity = "balanced"


def coerce_density(value: object) -> ContextDensity:
    """A density value → the vocabulary, `balanced` for anything else.

    Deliberately NOT `focus_option`'s raise-on-unknown. A focus is a choice a client makes
    explicitly and getting it wrong is a bug worth surfacing; a density arrives from a
    preset pill, from an older client that has none, and from a custom setting that carries
    only numbers — and none of those is a reason to fail a connection. The middle posture is
    the honest answer to "no posture was stated"."""
    text = str(value or "").strip().casefold()
    return text if text in CONTEXT_DENSITIES else DEFAULT_DENSITY  # type: ignore[return-value]

# What kind of card this is: an explanation of something named, an answer to something
# asked, or an answer the library did not hold and a web search supplied. The client renders
# the three differently — `web` in particular carries URL citations instead of source spans,
# and says so on its face.
#
# Adding a value to this vocabulary needs the project owner's sign-off (architecture.md:
# 123-124). `web` was added on the owner's instruction to open a supplementary internet
# path; it is a third kind rather than a flag on the other two because everything downstream
# of it differs — where its provenance points, which gate admits it, and what the card
# promises the reader about where the words came from.
# `glance` was added on the owner's instruction, for the same kind of reason `web` was: it
# is a fourth kind rather than a flag, because what it promises the reader differs. A glance
# card is the subject's own overview `definition` verbatim — one sentence, already grounded
# on the ledger anchors it cites — delivered the moment the plan names a subject the library
# holds, WHILE retrieval and the pick are still running. It arrives provisional and says so;
# the full result then upgrades it in place, settles it, or settles it silently.
SuggestionKind = Literal["concept", "fact", "web", "glance"]


class ContextFocusOption(BaseModel):
    key: ContextFocus
    label: str
    summary: str


class SuggestionKindOption(BaseModel):
    key: SuggestionKind
    label: str
    summary: str


# Ordered; `general` first because it is the default posture.
CONTEXT_FOCUSES: list[ContextFocusOption] = [
    ContextFocusOption(
        key="general",
        label="General",
        summary="any concept or fact in the whole workstream worth adding, whoever said it",
    ),
    ContextFocusOption(
        key="owner",
        label="Focus on the owner",
        summary=(
            "cards only for what the owner put in; participants' content is context for "
            "understanding only"
        ),
    ),
    ContextFocusOption(
        key="other",
        label="Focus on collaborators",
        summary=(
            "cards only for what participants put in; the owner's content is context for "
            "understanding only"
        ),
    ),
]

SUGGESTION_KINDS: list[SuggestionKindOption] = [
    SuggestionKindOption(
        key="concept",
        label="Concept",
        summary=(
            "a concept, person or matter the knowledge base already holds appeared in the "
            "stream; the card explains what it is"
        ),
    ),
    SuggestionKindOption(
        key="fact",
        label="Fact",
        summary=(
            "a question the knowledge base can answer directly appeared in the stream; the "
            "card gives the answer"
        ),
    ),
    SuggestionKindOption(
        key="glance",
        label="Glance",
        summary=(
            "the plan named a subject whose page carries a one-sentence definition, so that "
            "sentence is shown immediately — verbatim, cited to the claims it rests on — "
            "while the full lookup is still running; it is marked provisional until the "
            "pipeline settles, and upgrades in place when the full card is about the same "
            "subject"
        ),
    ),
    SuggestionKindOption(
        key="web",
        label="Web",
        summary=(
            "the knowledge base held nothing on what was asked and the deployment allows a "
            "supplementary internet search; the card gives that search's answer, cited to "
            "the pages it came from rather than to the owner's own sources"
        ),
    ),
]

_FOCUS_BY_KEY = {f.key: f for f in CONTEXT_FOCUSES}
_KIND_BY_KEY = {k.key: k for k in SUGGESTION_KINDS}


def focus_option(key: str) -> ContextFocusOption:
    """The ContextFocusOption for a key. Raises ValueError on an unknown value — a focus the
    vocabulary does not contain is a bug in the caller, never a silent fallback."""
    option = _FOCUS_BY_KEY.get(key)
    if option is None:
        raise ValueError(f"unknown suggestion focus: {key!r}")
    return option


def kind_option(key: str) -> SuggestionKindOption:
    """The SuggestionKindOption for a key. Raises ValueError on an unknown value."""
    option = _KIND_BY_KEY.get(key)
    if option is None:
        raise ValueError(f"unknown suggestion kind: {key!r}")
    return option


# ------------------------------------------------------------------- the card shapes


class WebCitation(BaseModel):
    """One page a web-search card rests on: a title and a URL, and nothing else.

    A SECOND citation shape on the wire, deliberately kept apart from `Citation` rather than
    squeezed into it. `Citation` is the one addressing scheme over the owner's own material
    (I4: `source_id` + block span, one parser for gate and projection), and a URL is not an
    address in it — a `Citation` carrying a URL as its `source_id` would be fetchable by
    nothing, would fail every gate that resolves a span, and would quietly make the phrase
    "all knowledge links back to a source block" false. So a web card carries this instead,
    the library citation gate does not apply to it, and its own gate is that it must carry
    at least one of these or it is never built."""

    title: str = ""
    url: str


class ContextSuggestion(BaseModel):
    """One card, exactly as the model emits it (body still carries `[cite: …]` markers).

    This is the structured-output schema — the class NAME reaches the provider as the tool
    name, so renaming it changes the wire contract."""

    kind: SuggestionKind
    title: str  # the concept named, or the question being answered
    body: str  # the explanation / answer, with inline `[cite: …]` markers
    trigger: str  # the transcript fragment that set this card off (UI highlight)
    confidence: int = Field(ge=1, le=10)


class SuggestionBatch(BaseModel):
    """The model's whole emission for one evaluation.

    `max_length=5` is a MECHANICAL ceiling on what the model can physically emit (a longer
    list becomes a `parsing_error` under `include_raw=True`, i.e. silence). It is a
    different thing from the server-side `max_suggestions` cap, which sorts by confidence and
    truncates AFTER the gates — that one is tunable per request, this one is not."""

    suggestions: list[ContextSuggestion] = Field(default_factory=list, max_length=5)


class ResolvedSuggestion(BaseModel):
    """A suggestion as it leaves the server: handles gone, citations structured.

    `body` has every `[cite: …]` marker STRIPPED and the provenance lifted into
    `citations` with real source ids. The client never sees an `sNN` handle — handles are
    query-local and are re-assigned every evaluation, so a handle that outlived its
    evaluation would point at a different source (see recall/citation_alias.py)."""

    kind: SuggestionKind
    title: str
    body: str
    trigger: str
    confidence: int = Field(ge=1, le=10)
    citations: list[Citation] = Field(default_factory=list)
    #: The verbatim evidence the card rests on, rendered MECHANICALLY from the claims and
    #: spans that were retrieved — never authored by a model. `body` is the guessed need;
    #: this is what the library actually says, and the client shows it collapsed under the
    #: card. Empty on the briefing path, which has no candidate behind it.
    evidence: str = ""
    #: The session-scoped identity of what this card is ABOUT — a canonical document path, a
    #: source id, or a path call key. The (subject, kind) pair is what stops the same
    #: introduction being delivered twice in one conversation. Empty when unknown.
    subject: str = ""
    #: A short human label for `subject`, for the ledger digest and the debug surface.
    subject_label: str = ""
    #: The pages a `web` card rests on. Empty on every library card, and the only provenance
    #: a `web` card has — `citations` is empty there, because there is no source block to
    #: point at. See `WebCitation` for why the two shapes stay separate.
    web_citations: list[WebCitation] = Field(default_factory=list)
    #: A `glance` card that was delivered BEFORE the pipeline settled. The reader is being
    #: shown a true sentence early, not a guess — the definition is verbatim and cited — and
    #: this says the tick is not finished, so the bubble can show it as still filling in. It
    #: is cleared on the frame that settles or upgrades the card, and is never set on any
    #: other kind.
    provisional: bool = False


# ────────────────────────────────────────────────── the three-stage pipeline shapes
#
# The full-scope Live Context lane is not one round any more. It is discover → retrieve →
# pick, and the two model calls each have a structured shape of their own. Both live here,
# beside the card shapes, for the same reason those do: the class NAME reaches the provider
# as the tool name, so these are wire contract and belong with the other wire contracts.


class PlanArg(BaseModel):
    """One `name = value` argument of a plan entry.

    A list of pairs rather than a free-form object because core knows no component: the
    argument NAMES belong to whichever path a component registered, and a schema that
    enumerated them would be core hard-coding `alias` / `since` / `until`. It is also the
    shape strict structured output accepts — an open-ended object is not."""

    name: str
    value: str


class PlanEntry(BaseModel):
    """One retrieval the discover stage asks for.

    `kind` is a registered path's name (`person`, `timespan`, …) or the built-in
    `semantic`. It stays a plain string and is validated MECHANICALLY against the paths
    actually enabled — a kind naming nothing is dropped and counted, never guessed at."""

    kind: str
    query: str = ""  # `semantic` only: the one query to retrieve on
    args: list[PlanArg] = Field(default_factory=list)


class DiscoverResult(BaseModel):
    """The discover stage's whole emission: retrieve this, or say why not.

    One model with a `skip` flag rather than a union: a union costs the small model a
    discrimination it does not need, and every field here is cheap to leave empty. `worth`
    is the pre-gate — below the deployment's floor NOTHING is retrieved, which is the
    entire point of spending a small call before the retrieval instead of after it."""

    skip: bool = False
    #: Why no question worth asking could be written: `small_talk` | `already_mined` |
    #: `nothing_new`. Free text so a model is never forced to mislabel; the counters group
    #: what arrives.
    reason: str = ""
    #: THE QUESTION — the one most worth asking on the room's behalf right now, phrased the
    #: way somebody in the room could have asked it aloud. It becomes the delivered card's
    #: `trigger`, so the owner reads it as the reason the card appeared, and it is what the
    #: pick stage scores every candidate against.
    intent: str = ""
    plan: list[PlanEntry] = Field(default_factory=list, max_length=2)
    worth: int = 0


class PickResult(BaseModel):
    """The pick stage's whole emission: which candidate, why it matters, how sure.

    `choice` is 1-based; **0 means none of them is worth showing** and is a first-class
    outcome, not a failure. The stage NEVER rewrites a candidate — `lede` frames the guessed
    need in the reader's own present tense, and `citations` prunes by INDEX into the
    candidate's own citation list, so provenance stays copy-by-reference."""

    choice: int = 0
    lede: str = ""
    citations: list[int] = Field(default_factory=list)
    confidence: int = 0
