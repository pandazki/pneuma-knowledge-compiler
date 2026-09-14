"""SourceAdapter protocol + registry + one real M0 adapter.

architecture.md §4: adapters absorb data-type diversity and emit NormalizedSource.
The registry resolves an adapter by (kind, mime). PlainConversationAdapter is the
one real M0 adapter: one block per turn, sections cut by calendar date.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel

from ..domain.source import (
    ConversationTurn,
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)
from ..domain.time_context import TimeContext
from ..prompts import prompt

IntakeHints = dict[str, Any]


class SourceAdapter(Protocol):
    def normalize(
        self, raw_input: Any, *, time: TimeContext | None = None
    ) -> NormalizedSource:
        """Raw input → addressable blocks + structure map.

        `time` is the knowledge subject's clock (domain/time_context.py). An adapter that
        cuts sections by calendar DAY must resolve each timestamp through it, because the
        day a turn belongs to is the subject's local day, not the UTC one. Absent → UTC.
        """
        ...

    def default_intake_hints(self) -> IntakeHints:
        """Declared defaults fed to IntakePolicy (§4 ②): kind / source_class /
        declared_type. IntakePolicy owns the decision; the adapter only declares.
        """
        ...


class AdapterRegistry:
    """Resolve a SourceAdapter by (kind, mime).

    A (kind, mime) registration wins; a (kind, None) registration is the fallback
    for that kind when no mime-specific adapter matches.
    """

    def __init__(self) -> None:
        self._by_kind_mime: dict[tuple[str, str | None], SourceAdapter] = {}

    def register(
        self, adapter: SourceAdapter, *, kind: str, mime: str | None = None
    ) -> None:
        self._by_kind_mime[(kind, mime)] = adapter

    def find(self, kind: str, mime: str | None = None) -> SourceAdapter:
        if (kind, mime) in self._by_kind_mime:
            return self._by_kind_mime[(kind, mime)]
        if (kind, None) in self._by_kind_mime:
            return self._by_kind_mime[(kind, None)]
        raise KeyError(f"no adapter for kind={kind!r} mime={mime!r}")


class PlainConversationInput(BaseModel):
    """Input shape for PlainConversationAdapter: a RawSource plus its turns."""

    raw: RawSource
    turns: list[ConversationTurn]


UNDATED = "undated"


def local_day_keys(
    turns: list[ConversationTurn], time: TimeContext | None
) -> list[str]:
    """Per-turn section key: the turn's calendar day **in the subject's timezone**.

    This is the one place an instant becomes a day for conversation intake. Resolving it
    through the TimeContext is what keeps a subject's late-evening messages in the evening
    they remember: at +08:00 anything sent before 08:00 local carries the previous UTC
    date, so a UTC `.date()` splits one evening across two sections and dates the resulting
    claims a day early. `time=None` means UTC (the historical behaviour).
    """
    keys: list[str] = []
    for turn in turns:
        if turn.at is None:
            keys.append(UNDATED)
        elif time is not None:
            keys.append(time.local_date(turn.at).isoformat())
        else:
            keys.append(turn.at.date().isoformat())
    return keys


def stamp_occurred_on(raw: RawSource, day_keys: list[str]) -> None:
    """Record the source's own occurrence day in `meta["occurred_on"]` — computed here.

    The compile task's time frame and the per-source preamble both need "when did this
    material happen", and `raw.created_at` cannot answer it (that is the INGEST wall clock:
    material captured weeks ago would be announced as happening today). The sectioning pass
    has just computed the answer in the subject's own zone, so the framework stamps it
    instead of leaving every ingest integration to do its own `astimezone`.

    An explicitly supplied value is NEVER overwritten: a business that knows the true
    occurrence day (a backfill, a capture whose own metadata is authoritative) outranks a
    day derived from turn timestamps.
    """
    meta = dict(raw.meta or {})
    if str(meta.get("occurred_on") or "").strip():
        return
    dated = sorted(key for key in day_keys if key != UNDATED)
    if not dated:
        return
    meta["occurred_on"] = dated[0]
    raw.meta = meta


# NUL (U+0000) is the one codepoint that is not text. No medium a source comes from means
# it, and every store L0 feeds refuses it outright — Postgres `text` and `jsonb` both raise
# rather than truncate — so a payload carrying one used to be unwritable: the ingest died at
# the adapter layer's far end and whatever produced the payload retried the same bytes
# forever. It is removed here instead, deterministically, at the point a source becomes a
# NormalizedSource, so L0, L1, L2 and the canonical citations all address the same bytes and
# a rebuild reproduces them.
NUL = "\x00"


def _without_nul(value: Any) -> Any:
    """Strip NUL from every string inside a JSON-shaped value (metadata, section paths)."""
    if isinstance(value, str):
        return value.replace(NUL, "")
    if isinstance(value, dict):
        return {_without_nul(key): _without_nul(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_nul(item) for item in value]
    return value


def strip_nul(source: NormalizedSource) -> NormalizedSource:
    """Remove NUL from every text field of a normalized source, in place.

    Covers what reaches a store: the source title and its metadata envelope, each block's
    text and section path, the structure map's section paths, and the text derived from a
    block's images (which is indexed beside the block).

    NO ANCHOR MOVES. A citation addresses blocks by INDEX (`[cite: <sid> ¶a-b]`) and the
    structure map addresses an inclusive block interval, so removing a character from inside
    a block changes no address. The one layer that does count characters — L2 chunking's
    `char_start`/`char_end` (ingest/chunking.py) — computes them from these block texts
    afterwards and re-derives them on every rebuild from the stored L0, so it addresses the
    stripped string throughout and never a pre-strip one.

    `raw.checksum` is deliberately NOT recomputed: it digests the payload as it arrived, and
    it is the dedup identity of that payload, not of the rendered text.
    """
    raw = source.raw
    raw.title = raw.title.replace(NUL, "")
    raw.meta = _without_nul(raw.meta or {})
    for block in source.blocks:
        block.text = block.text.replace(NUL, "")
        block.section_path = [part.replace(NUL, "") for part in block.section_path]
        for image in block.images:
            image.metadata = _without_nul(image.metadata or {})
            for derived in image.derived:
                derived.text = derived.text.replace(NUL, "")
    for span in source.structure.sections:
        span.path = [part.replace(NUL, "") for part in span.path]
    return source


def _date_spans(day_keys: list[str]) -> list[SectionSpan]:
    """Contiguous runs of the same calendar date → one section span each (turns are
    chronological in practice); timestamp-less turns fall in an 'undated' section."""
    spans: list[SectionSpan] = []
    run_date: str | None = None
    run_start = 0
    for i, date_key in enumerate(day_keys):
        if run_date is None:
            run_date, run_start = date_key, i
        elif date_key != run_date:
            spans.append(SectionSpan(path=[run_date], start_block=run_start, end_block=i - 1))
            run_date, run_start = date_key, i
    if run_date is not None:
        spans.append(
            SectionSpan(path=[run_date], start_block=run_start, end_block=len(day_keys) - 1)
        )
    return spans


class PlainConversationAdapter:
    """Turns → one block per turn (`speaker: text`); sections cut by calendar date.

    The generic (non-first-party) path: `speaker` is rendered verbatim, no owner/other
    semantics. Turns without a timestamp land in the "undated" section.
    """

    def default_intake_hints(self) -> IntakeHints:
        return {"kind": "conversation", "source_class": "workstream", "declared_type": None}

    def normalize(
        self, raw_input: PlainConversationInput, *, time: TimeContext | None = None
    ) -> NormalizedSource:
        day_keys = local_day_keys(raw_input.turns, time)
        blocks = [
            NormalizedBlock(
                index=i,
                text=f"{turn.speaker}: {turn.text}",
                section_path=[day_keys[i]],
            )
            for i, turn in enumerate(raw_input.turns)
        ]
        stamp_occurred_on(raw_input.raw, day_keys)
        return strip_nul(
            NormalizedSource(
                raw=raw_input.raw,
                blocks=blocks,
                structure=StructureMap(sections=_date_spans(day_keys)),
            )
        )


# Mime that routes conversation intake to the first-party context_stream adapter (registry is
# keyed by (kind, mime); (conversation, None) stays the generic PlainConversationAdapter).
CONTEXT_STREAM_MIME = "application/vnd.pneuma.context-stream+json"

# The owner label the compile skill (§9, speaker and attribution) already reasons over.
# Rendering the diarized `owner` role as this exact string binds first-party data to the
# skill's vocabulary, so "the owner is the subject" stops being a guess. It is a prompt
# surface (`ingest.owner_label`), because a deployment whose skill body says "the owner" in
# its own language needs the block text to say the same word.


class ContextStreamAdapter:
    """Structured context stream → owner-anchored blocks.

    Same block/section shape as the plain adapter, but turns carry a diarized `role`, so a
    block is rendered in the skill's own vocabulary: the owner's turns as `Owner: …` and
    each distinct other speaker as a stable `ParticipantN (<speaker_id>): …`. The compiler and
    downstream retrieval now see who owns the knowledge instead of guessing from opaque
    diarization codes. A turn left `unknown` falls back to its raw `speaker` string,
    so a mixed/partial transcript degrades gracefully rather than mislabeling.

    Attribution is never invented here: the role comes from the source boundary, not from
    reading the text. Ambiguous diarization stays whatever role the source assigned.
    """

    def default_intake_hints(self) -> IntakeHints:
        return {"kind": "conversation", "source_class": "workstream", "declared_type": None}

    def normalize(
        self, raw_input: PlainConversationInput, *, time: TimeContext | None = None
    ) -> NormalizedSource:
        # Stable participant numbering per distinct other speaker, first-appearance order.
        other_labels: dict[str, str] = {}

        def label_for(turn: ConversationTurn) -> str:
            if turn.role == "owner":
                return prompt("ingest.owner_label")
            if turn.role == "other":
                key = turn.speaker_id or turn.speaker
                if key not in other_labels:
                    n = len(other_labels) + 1
                    # Keep the raw diarization id as a parenthetical alias so provenance
                    # back to the capture channel is never lost.
                    suffix = (
                        prompt("ingest.speaker_alias", speaker_id=key)
                        if turn.speaker_id
                        else ""
                    )
                    other_labels[key] = prompt(
                        "ingest.other_label", n=n, suffix=suffix
                    )
                return other_labels[key]
            return turn.speaker  # unknown → verbatim, no owner/other claim

        day_keys = local_day_keys(raw_input.turns, time)
        blocks = [
            NormalizedBlock(
                index=i,
                text=prompt("ingest.turn_line", label=label_for(turn), text=turn.text),
                section_path=[day_keys[i]],
            )
            for i, turn in enumerate(raw_input.turns)
        ]
        stamp_occurred_on(raw_input.raw, day_keys)
        return strip_nul(
            NormalizedSource(
                raw=raw_input.raw,
                blocks=blocks,
                structure=StructureMap(sections=_date_spans(day_keys)),
            )
        )


class PlainDocumentInput(BaseModel):
    """Input shape for MarkdownDocumentAdapter: a RawSource plus its raw text.

    `declared_type` (contract | novel | note | other | None) and `source_class` are
    carried on the RawSource; the adapter only shapes text into blocks + a structure
    map — IntakePolicy owns the treatment decision (§4).
    """

    raw: RawSource
    text: str


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


class MarkdownDocumentAdapter:
    """Markdown / plain text → paragraph blocks + a heading-based structure map.

    The structure map is a first-class product (§4): sections are cut by markdown
    headings — each heading opens a section whose path is the heading hierarchy
    (`["Contract", "Clause 5 Penalties"]` for a level-2 heading under a level-1). A block is one
    paragraph (a run of non-blank, non-heading lines separated by blank lines). Text
    with no headings falls back to paragraph blocks under a single implicit `[]`
    (preamble) section, so L0/L1 stay whole (I3). Plain text (no `#`) parses as one
    section of paragraphs.
    """

    def default_intake_hints(self) -> IntakeHints:
        # Documents default to reference/None; the request's declared_type +
        # source_class override these (IntakePolicy owns the decision).
        return {"kind": "document", "source_class": "reference", "declared_type": None}

    def normalize(
        self, raw_input: PlainDocumentInput, *, time: TimeContext | None = None
    ) -> NormalizedSource:
        # `time` is part of the SourceAdapter contract but unused here: a document's
        # sections are cut by HEADINGS, so no instant ever becomes a calendar day on this
        # path and there is nothing to align.
        lines = raw_input.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

        blocks: list[NormalizedBlock] = []
        # section_path per block, then collapse contiguous same-path runs into spans.
        block_paths: list[list[str]] = []
        heading_stack: list[tuple[int, str]] = []  # (level, title)
        para: list[str] = []

        def cur_path() -> list[str]:
            return [title for _, title in heading_stack]

        def flush_para() -> None:
            if not para:
                return
            text = "\n".join(para).strip()
            para.clear()
            if not text:
                return
            idx = len(blocks)
            blocks.append(
                NormalizedBlock(index=idx, text=text, section_path=cur_path())
            )
            block_paths.append(cur_path())

        for line in lines:
            m = _MD_HEADING_RE.match(line)
            if m is not None:
                flush_para()
                level = len(m.group(1))
                title = m.group(2).strip()
                # pop deeper-or-equal headings, then push this one.
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))
                continue
            if not line.strip():
                flush_para()
                continue
            para.append(line)
        flush_para()

        spans: list[SectionSpan] = []
        run_path: list[str] | None = None
        run_start = 0
        for i, path in enumerate(block_paths):
            if run_path is None:
                run_path, run_start = path, i
            elif path != run_path:
                spans.append(
                    SectionSpan(path=run_path, start_block=run_start, end_block=i - 1)
                )
                run_path, run_start = path, i
        if run_path is not None:
            spans.append(
                SectionSpan(
                    path=run_path, start_block=run_start, end_block=len(blocks) - 1
                )
            )

        return strip_nul(
            NormalizedSource(
                raw=raw_input.raw,
                blocks=blocks,
                structure=StructureMap(sections=spans),
            )
        )
