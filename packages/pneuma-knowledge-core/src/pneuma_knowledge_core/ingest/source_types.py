"""Typed source plugins: the vertical seam for structured context streams.

WHY THIS EXISTS (design intent)
-------------------------------
Developer tools, meeting bots, agents, and local recorders emit structured, high-context
streams. The generic upload path is universal precisely because it discards structure;
typed context data is the opposite — its structure IS the signal. Each stream is therefore
a vertical plugin that preserves and
exploits structure end-to-end, instead of being flattened into the generic document path.

A `FirstPartySourceType` bundles the FIVE places one stream differs from another:

  1. load    — fetch/deserialize from the stream's transport (an API, local file, or hook).
  2. format  — normalize the raw capture into addressable blocks + a CitationSpec that
               fixes what an anchor/¶span means for this type, so a cited span can be
               REPLAYED / RELOCATED as raw evolves; large captures are split here.
  3. compile — per-type guidance injected into the compile task, in TWO parts the compiler
               cannot infer from the bytes:
                 · data_context — what the fields/roles mean (self = owner, …),
                 · app_context  — what the FEATURE is for → hence what is memory-worthy.
  4. index   — how the raw is chunked/embedded (L2) and lexically indexed (L1) for
               Meilisearch/Qdrant recall, per the stream's shape.
  5. describe — the source's provenance as one owner-subject sentence for the compile task
               (who / when / the owner's role), phrased in the medium's own vocabulary.

UNCERTAINTY IS FIRST-CLASS. Real capture is lossy whatever it is made of — an upstream
recognizer, a partial export, an editor's half-finished draft — and no type targets
byte-perfect extraction. Every concern degrades gracefully: never fabricate structure the
capture didn't provide; mark or drop noise rather than assert it. Success is "the owner's
high-value memory is captured and correctly attributed more often, with uncertainty
preserved", not zero error.

The generic `upload` path is the degenerate type (no loader beyond the posted body, plain
formatter, no per-type compile guidance, settings-driven indexing); first-party types are
an ADDITIVE plugin layer over it, so adding a source integration never touches the core
compile/recall engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..domain.source import ConversationTurn, NormalizedSource, RawSource, SourceOrigin
from ..domain.time_context import TimeContext
from ..prompts import prompt
from .adapters import ContextStreamAdapter, PlainConversationInput


@dataclass(frozen=True)
class CompileGuidance:
    """The per-type compile context (concern 3). Rides the compile HumanMessage as a
    per-source preface (parallel to the treatment instruction), NEVER the byte-stable
    SystemMessage. Two parts because they answer different questions the transcript can't:
    `data_context` = what the data's fields/roles mean; `app_context` = what the stream
    is for, hence what is worth remembering."""

    data_context: str
    app_context: str

    def render(self) -> str:
        return prompt(
            "source.guidance_header",
            data_context=self.data_context,
            app_context=self.app_context,
        )


@dataclass(frozen=True)
class IndexingSpec:
    """Concern 4: how this type feeds L2 (chunking) and L1 (lexical). `chunk_strategy` is
    a wiring.build_chunker / full_l2_chunks strategy name; L1 always indexes every block
    unconditionally (invariant I3), so only the L2 shape varies per type here."""

    chunk_strategy: str  # "semantic" | "sentence" | "recursive"


@runtime_checkable
class FirstPartySourceType(Protocol):
    """A structured context stream implementing the four concerns above. Registered by
    `origin`; resolved at ingest + compile so every stage sees the type's specialization."""

    origin: SourceOrigin

    def load(self, payload: object) -> list[ConversationTurn]:
        """Concern 1: transport → typed turns. For context_stream the payload arrives in the
        request, but diarization labels may still be raw strings — load
        normalizes them into typed roles. A file/remote-API type would fetch + parse here."""
        ...

    def format(
        self,
        raw: RawSource,
        turns: list[ConversationTurn],
        *,
        time: TimeContext | None = None,
    ) -> NormalizedSource:
        """Concern 2: typed turns → addressable, owner-anchored NormalizedSource.

        `time` is the subject's clock: a type that cuts sections by day resolves each
        timestamp through it so a day means the subject's local day. Absent → UTC.
        """
        ...

    def compile_guidance(self) -> CompileGuidance | None:
        """Concern 3: per-type compile context, or None for the generic path."""
        ...

    def indexing(self) -> IndexingSpec:
        """Concern 4: L2 chunking strategy for this stream."""
        ...

    def describe(self, raw: RawSource, blocks_count: int, owner_name: str) -> str:
        """Concern 5: this source's provenance as ONE sentence with the owner as subject —
        whose material, when it happened, what the owner's role in it was.

        Rendered into the compile task ahead of the blocks. It is a per-TYPE concern because
        only the type knows what its capture medium is called: a chat room, a call, a
        recorded meeting, an email thread. Core must not name any medium, so the built-in
        implementation stays medium-neutral and a deployment that has a specific product
        registers its own type to phrase it properly.
        """
        ...


# ── context_stream: the first concrete first-party type ─────────────────────────────────────

# Diarization channel → owner/other. `self/*` represents the knowledge owner;
# `others/*` are participants. Multiple `self/N` channels belong to the same owner.
def parse_diarized_turns(turns: list[ConversationTurn]) -> list[ConversationTurn]:
    """Normalize raw diarized `speaker` strings (`self/3`, `others/2`) into typed roles,
    unless the caller already set them. Anything not matching the diarization convention
    stays `unknown` (rendered verbatim) — we never guess the owner from content."""
    out: list[ConversationTurn] = []
    for t in turns:
        if t.role != "unknown":
            out.append(t)
            continue
        head = t.speaker.split("/", 1)[0].strip().lower() if t.speaker else ""
        if head == "self":
            out.append(t.model_copy(update={"role": "owner", "speaker_id": t.speaker}))
        elif head == "others":
            out.append(t.model_copy(update={"role": "other", "speaker_id": t.speaker}))
        else:
            out.append(t)  # un-diarized → left unknown, no owner/other claim
    return out


def _context_stream_guidance() -> CompileGuidance:
    """The built-in context-stream compile guidance, resolved from the catalog.

    Deliberately medium-neutral: it says "a structured work-context stream" and "an upstream
    recognizer", never naming a capture device or a product. A deployment that has a specific
    medium overrides `source.context_stream.*` (or registers its own type)."""
    return CompileGuidance(
        data_context=prompt("source.context_stream.data_context"),
        app_context=prompt("source.context_stream.app_context"),
    )


class ContextStreamSourceType:
    """Structured context stream source. Implements all four
    concerns; `format` reuses the owner-aware ContextStreamAdapter (concern 2), `load`
    types the diarization (concern 1), and it carries meeting-capture compile guidance
    (concern 3) + semantic chunking so a coherent turn/topic is one L2 unit (concern 4)."""

    origin: SourceOrigin = "context_stream"

    def __init__(self) -> None:
        self._adapter = ContextStreamAdapter()

    def load(self, payload: object) -> list[ConversationTurn]:
        turns = list(payload)  # already ConversationTurn; type the roles
        return parse_diarized_turns(turns)

    def format(
        self,
        raw: RawSource,
        turns: list[ConversationTurn],
        *,
        time: TimeContext | None = None,
    ) -> NormalizedSource:
        return self._adapter.normalize(
            PlainConversationInput(raw=raw, turns=turns), time=time
        )

    def compile_guidance(self) -> CompileGuidance | None:
        return _context_stream_guidance()

    def indexing(self) -> IndexingSpec:
        return IndexingSpec(chunk_strategy="semantic")

    def describe(self, raw: RawSource, blocks_count: int, owner_name: str) -> str:
        """Medium-neutral: a diarized stream with turn counts and the owner's involvement.
        A deployment whose capture has a NAME (a chat room, a call) subclasses and overrides
        this — see `register_source_type`."""
        return _context_stream_preamble(raw, blocks_count, owner_name)


# ── per-source preamble: metadata → a sentence with the OWNER as its subject ────────────
#
# `CompileGuidance` above answers "what is this KIND of data" — it is a per-origin constant,
# so it is said once per job. This layer answers the other half, per source: WHOSE material
# is this, WHEN did it happen, and what was the owner's role in it. Without it the compiler
# sees only a source id, a title and a wall of ¶ blocks, and has to infer authorship and
# time from the prose — the two things it is least allowed to guess.
#
# Every example below uses a neutral synthetic role ("the owner", "a teammate"). Never
# illustrate with real captured material.
#
# The occurrence time comes from the source's own metadata, NEVER from `RawSource.created_at`
# (that is the INGEST wall-clock: a conversation from 2026-07-21 ingested today would be
# announced as happening today).


_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff"
_CJK_THEN_ASCII = re.compile(rf"([{_CJK}])([A-Za-z0-9@\[])")
_ASCII_THEN_CJK = re.compile(rf"([A-Za-z0-9\)\]])([{_CJK}])")


_QUOTED = re.compile(r"「[^」]*」")


def _spaced(text: str) -> str:
    """Insert the conventional space between CJK and adjacent Latin/digits, and collapse
    accidental double spaces.

    A no-op on the English defaults (there is no CJK to butt against Latin), and kept in the
    framework because it is a pure typography function: the moment a deployment overrides
    these preambles with CJK templates, the assembled sentence mixes CJK skeleton with Latin
    names and dates, and doing this once at the end beats hand-tuning every seam.

    Spans inside CJK corner quotes are left byte-for-byte alone: those are DATA (a document
    title, a room name), not prose. Re-spacing them would silently rewrite a proper noun
    whose exact form callers may rely on.
    """

    def normalize(chunk: str) -> str:
        chunk = _CJK_THEN_ASCII.sub(r"\1 \2", chunk)
        chunk = _ASCII_THEN_CJK.sub(r"\1 \2", chunk)
        return re.sub(r" {2,}", " ", chunk).replace(" 。", "。").replace(" ，", "，")

    out, cursor = [], 0
    for m in _QUOTED.finditer(text):
        out.append(normalize(text[cursor : m.start()]))
        out.append(m.group(0))  # verbatim
        cursor = m.end()
    out.append(normalize(text[cursor:]))
    return "".join(out)


def _fmt_when(value: object) -> str:
    """A date/datetime-ish metadata value → `YYYY-MM-DD HH:MM`, or the raw string."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("T", " ")
    return text[:16] if len(text) >= 16 else text[:10]


def occurred_on(raw: RawSource) -> str:
    """The source's AUTHORITATIVE occurrence day, or "" when it genuinely has none.

    One field, one spelling: `meta["occurred_on"]`. Every ingest path in the framework
    stamps it — `ingest.adapters.stamp_occurred_on` computes it from the material's own
    timestamps in the SUBJECT's zone (conversation, context_stream) and every contract
    normalizer (meeting / im / email / document_library) calls that same stamper — and an
    integration that knows the true day may supply it explicitly, in which case it is never
    overwritten. `RawSource.created_at` is deliberately NOT consulted: that is the ingest
    wall clock, so material captured weeks ago would be announced as happening today.

    This is read by the preambles below because the compile task's round-level time frame
    can only state the SPAN of a round. Under a per-day round the span IS the source's day,
    so a missing per-source date was invisible; under a batched round (several days in one
    job) a source whose only date lives here rendered as "supplies no time", and the
    compiler was then asked to resolve relative time against a date it had never been
    shown.
    """
    return str((raw.meta or {}).get("occurred_on") or "").strip()


def _context_stream_preamble(raw: RawSource, blocks_count: int, owner_name: str) -> str:
    """A diarized stream → one sentence with the owner as subject.

    Core stays domain-neutral: it renders the metadata the ingest side supplies and knows
    nothing about what KIND of stream this is. `meta["scene"]` is the business-supplied
    phrase for where this happened (a chat room, a call, a recorded session); absent, the
    sentence degrades to an unqualified one rather than guessing a medium.
    """
    meta = raw.meta or {}
    scene = (
        str(meta.get("scene") or "").strip()
        or prompt("source.preamble.stream_scene_default")
    )
    when = str(meta.get("occurred_on") or "").strip()
    part = ""
    if int(meta.get("part_count") or 1) > 1:
        part = prompt(
            "source.preamble.stream_part",
            part=meta.get("part"),
            part_count=meta.get("part_count"),
        )
    owner_turns = int(meta.get("owner_turns") or 0)
    role = (
        prompt(
            "source.preamble.stream_role_spoke", owner=owner_name, turns=owner_turns
        )
        if owner_turns
        else prompt("source.preamble.stream_role_silent", owner=owner_name)
    )
    mentions = int(meta.get("owner_mentions") or 0)
    if mentions:
        role += prompt("source.preamble.stream_mentions", mentions=mentions)
    replied = int(meta.get("owner_replied_to") or 0)
    if replied:
        role += prompt("source.preamble.stream_replies", replied=replied)
    # Owner-as-subject: "This is <owner> <when> in <scene>…", not "This is <scene>…".
    lead = prompt(
        "source.preamble.stream_lead",
        owner=owner_name,
        when=f"{when} " if when else "",
        scene=scene,
        blocks=blocks_count,
        part=part,
    )
    return prompt("source.preamble.stream_tail", lead=lead, role=role)


def _document_preamble(raw: RawSource, owner_name: str) -> str:
    meta = raw.meta or {}
    kind = (
        meta.get("doc_kind")
        or meta.get("declared_type")
        or prompt("source.preamble.document_kind_default")
    )
    author = str(meta.get("author") or "").strip()
    by_owner = bool(meta.get("authored_by_owner")) or author == owner_name
    created, updated = _fmt_when(meta.get("created_at")), _fmt_when(meta.get("updated_at"))
    who = (
        owner_name
        if by_owner
        else (author or prompt("source.preamble.document_other_author"))
    )
    title_part = (
        prompt("source.preamble.document_title", title=raw.title) if raw.title else ""
    )
    created_part = (
        prompt("source.preamble.document_created", created=created) if created else ""
    )
    updated_part = (
        prompt("source.preamble.document_updated", updated=updated[:10])
        if updated and updated[:10] != created[:10]
        else ""
    )
    if created_part and updated_part:
        when = prompt(
            "source.preamble.document_created_and_updated",
            created=created_part,
            updated=updated_part,
        )
    else:
        when = created_part or updated_part
    # An authored document that carries no authoring timestamp can still have an
    # authoritative occurrence day (this path is reached whenever `author` alone is set).
    # Falling through with an empty `when` would print a dateless sentence about a source
    # whose date the framework is holding. Only used when nothing better was stated — a
    # document that already declares created/updated keeps its wording byte-for-byte.
    if not when:
        occurred = occurred_on(raw)
        if occurred:
            when = prompt("source.preamble.document_occurred", when=occurred)
    parent = (
        prompt("source.preamble.document_parent", parent_title=meta.get("parent_title"))
        if meta.get("parent_title")
        else ""
    )
    stance = (
        prompt("source.preamble.document_stance_owner", owner=owner_name)
        if by_owner
        else prompt(
            "source.preamble.document_stance_other", owner=owner_name, author=who
        )
    )
    lead = prompt(
        "source.preamble.document_lead",
        who=who,
        when=prompt("source.preamble.document_when", when=when) if when else "",
        kind=kind,
        title=title_part,
        parent=parent,
    )
    return f"{lead}{stance}"


def _reference_preamble(raw: RawSource, owner_name: str) -> str:
    """`source_class == "reference"` with no authorship metadata: external material. The
    stance clause matters more than the provenance detail — it must not be read as the
    owner's own words. External material can still be dated, and when it is, the date is
    said: unknown authorship is not a reason to withhold a time the framework holds."""
    when = occurred_on(raw)
    key = (
        "source.preamble.reference_dated" if when else "source.preamble.reference"
    )
    return prompt(key, owner=owner_name, title=_title_part(raw), when=when)


def register_source_type(source_type: FirstPartySourceType) -> None:
    """Register (or replace) the plugin for an origin — the seam for business extension.

    A deployment builds its own knowledge-base strategy on top of this framework: its data
    has a product name, its capture has a medium, and its compile guidance is domain
    specific. Registering a type lets all five concerns be supplied from outside, so
    business vocabulary never has to be pushed down into core. Replacing a built-in origin
    is intentional and supported: subclass the built-in, override just the concerns that
    differ, and register the subclass at startup.
    """
    _FIRST_PARTY_TYPES[str(source_type.origin)] = source_type


def _title_part(raw: RawSource) -> str:
    """The quoted-title fragment, or empty when the source has no title."""
    return (
        prompt("source.preamble.title_quoted", title=raw.title) if raw.title else ""
    )


def describe_source(
    raw: RawSource, blocks_count: int, owner_name: str | None = None
) -> str:
    """One sentence naming whose material this is, when it happened, and the owner's role.

    Dispatches on the source's own shape (origin / kind / source_class) and degrades to a
    minimal but still owner-subject sentence when metadata is thin — a source with no
    metadata should read as "provenance unknown", never as if it were the owner's own.

    `owner_name` defaults to the neutral `source.preamble.owner_default` label, so a caller
    that does not know the owner's display name still gets an owner-subject sentence.

    Shape of the output (neutral synthetic roles only):

      context_stream (scene supplied by the ingest side)
        This is the owner 2026-07-18 in the release review, 12 message(s).
        The owner spoke 4 time(s), was @-mentioned 1 time(s).
      document authored by the owner
        This is a work note by the owner created on 2026-07-18 09:30, titled "Release check".
        The owner is the author, so judgments in it belong to them by default.
      document authored by someone else
        This is a work note by a teammate created on 2026-07-10 14:05, titled "…".
        The owner is a reader and not the author; judgments in it belong to a teammate and
        must not be recorded as their own decisions.
      any source the framework has dated but cannot attribute (`meta["occurred_on"]`)
        This is material from 2026-07-18 in the owner's knowledge base; the material
        supplies no author, so attribution stays pending — but the date above is the
        source's own and relative time in it resolves against that day.
      a source with no date at all — the wording degrades, as it must
        This is a piece of material in the owner's knowledge base; the material supplies no
        provenance and no time, so attribution and time both stay pending.
    """
    if owner_name is None:
        owner_name = prompt("source.preamble.owner_default")
    return _spaced(_describe(raw, blocks_count, owner_name))


def _describe(raw: RawSource, blocks_count: int, owner_name: str) -> str:
    # Concern 5 belongs to the registered type when there is one, so a deployment's own
    # phrasing wins without core knowing anything about its medium.
    plugin = _FIRST_PARTY_TYPES.get(str(raw.origin))
    describe = getattr(plugin, "describe", None)
    if callable(describe):
        return describe(raw, blocks_count, owner_name)
    meta = raw.meta or {}
    # The authoritative day, read ONCE for every branch below: whichever sentence this
    # source ends up with, if the framework holds its date the sentence states it. Only a
    # source that genuinely has no date degrades to the "time stays pending" wording.
    when = occurred_on(raw)
    if raw.kind == "document":
        if meta.get("author") or meta.get("created_at") or meta.get("authored_by_owner"):
            return _document_preamble(raw, owner_name)
        if raw.source_class == "reference":
            return _reference_preamble(raw, owner_name)
        key = (
            "source.preamble.document_unknown_dated"
            if when
            else "source.preamble.document_unknown"
        )
        return prompt(key, owner=owner_name, title=_title_part(raw), when=when)
    # Everything that is not a document: conversation, meeting, im, email, structured,
    # document_library — every one of them is stamped with `occurred_on` at ingest, so this
    # is the branch the batched-round date suppression was actually hiding behind.
    key = "source.preamble.fallback_dated" if when else "source.preamble.fallback"
    return prompt(key, owner=owner_name, title=_title_part(raw), when=when)


# origin → first-party type. `upload` is absent (the generic default path handles it).
_FIRST_PARTY_TYPES: dict[str, FirstPartySourceType] = {
    "context_stream": ContextStreamSourceType(),
}


def first_party_type(origin: str) -> FirstPartySourceType | None:
    """Resolve the first-party plugin for an origin, or None for the generic upload path."""
    return _FIRST_PARTY_TYPES.get(origin)
