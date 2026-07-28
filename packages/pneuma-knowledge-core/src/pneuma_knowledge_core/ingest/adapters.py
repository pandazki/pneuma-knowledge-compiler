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

IntakeHints = dict[str, Any]


class SourceAdapter(Protocol):
    def normalize(self, raw_input: Any) -> NormalizedSource: ...

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


def _date_spans(turns: list[ConversationTurn]) -> list[SectionSpan]:
    """Contiguous runs of the same calendar date → one section span each (turns are
    chronological in practice); timestamp-less turns fall in an 'undated' section."""
    spans: list[SectionSpan] = []
    run_date: str | None = None
    run_start = 0
    for i, turn in enumerate(turns):
        date_key = turn.at.date().isoformat() if turn.at is not None else "undated"
        if run_date is None:
            run_date, run_start = date_key, i
        elif date_key != run_date:
            spans.append(SectionSpan(path=[run_date], start_block=run_start, end_block=i - 1))
            run_date, run_start = date_key, i
    if run_date is not None:
        spans.append(SectionSpan(path=[run_date], start_block=run_start, end_block=len(turns) - 1))
    return spans


class PlainConversationAdapter:
    """Turns → one block per turn (`speaker: text`); sections cut by calendar date.

    The generic (non-first-party) path: `speaker` is rendered verbatim, no owner/other
    semantics. Turns without a timestamp land in the "undated" section.
    """

    def default_intake_hints(self) -> IntakeHints:
        return {"kind": "conversation", "source_class": "workstream", "declared_type": None}

    def normalize(self, raw_input: PlainConversationInput) -> NormalizedSource:
        blocks = [
            NormalizedBlock(
                index=i,
                text=f"{turn.speaker}: {turn.text}",
                section_path=[turn.at.date().isoformat() if turn.at else "undated"],
            )
            for i, turn in enumerate(raw_input.turns)
        ]
        return NormalizedSource(
            raw=raw_input.raw,
            blocks=blocks,
            structure=StructureMap(sections=_date_spans(raw_input.turns)),
        )


# Mime that routes conversation intake to the first-party context_stream adapter (registry is
# keyed by (kind, mime); (conversation, None) stays the generic PlainConversationAdapter).
CONTEXT_STREAM_MIME = "application/vnd.pneuma.context-stream+json"

# The owner label the compile skill (§9 说话人与归属) already reasons over. Rendering the
# diarized `owner` role as this exact string binds first-party data to the skill's
# vocabulary, so "以本人为主体" stops being a guess.
_OWNER_LABEL = "本人"


class ContextStreamAdapter:
    """Structured context stream → owner-anchored blocks.

    Same block/section shape as the plain adapter, but turns carry a diarized `role`, so a
    block is rendered in the skill's own vocabulary: the owner's turns as `本人：…` and
    each distinct other speaker as a stable `参与者N（<speaker_id>）：…`. The compiler and
    downstream retrieval now see who owns the knowledge instead of guessing from opaque
    diarization codes. A turn left `unknown` falls back to its raw `speaker` string,
    so a mixed/partial transcript degrades gracefully rather than mislabeling.

    Attribution is never invented here: the role comes from the source boundary, not from
    reading the text. Ambiguous diarization stays whatever role the source assigned.
    """

    def default_intake_hints(self) -> IntakeHints:
        return {"kind": "conversation", "source_class": "workstream", "declared_type": None}

    def normalize(self, raw_input: PlainConversationInput) -> NormalizedSource:
        # Stable "参与者N" numbering per distinct other speaker, in first-appearance order.
        other_labels: dict[str, str] = {}

        def label_for(turn: ConversationTurn) -> str:
            if turn.role == "owner":
                return _OWNER_LABEL
            if turn.role == "other":
                key = turn.speaker_id or turn.speaker
                if key not in other_labels:
                    n = len(other_labels) + 1
                    # Keep the raw diarization id as a parenthetical alias so provenance
                    # back to the capture channel is never lost.
                    suffix = f"（{key}）" if turn.speaker_id else ""
                    other_labels[key] = f"参与者{n}{suffix}"
                return other_labels[key]
            return turn.speaker  # unknown → verbatim, no owner/other claim

        blocks = [
            NormalizedBlock(
                index=i,
                text=f"{label_for(turn)}：{turn.text}",
                section_path=[turn.at.date().isoformat() if turn.at else "undated"],
            )
            for i, turn in enumerate(raw_input.turns)
        ]
        return NormalizedSource(
            raw=raw_input.raw,
            blocks=blocks,
            structure=StructureMap(sections=_date_spans(raw_input.turns)),
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
    (`["合同", "第五条 违约金"]` for a level-2 heading under a level-1). A block is one
    paragraph (a run of non-blank, non-heading lines separated by blank lines). Text
    with no headings falls back to paragraph blocks under a single implicit `[]`
    (preamble) section, so L0/L1 stay whole (I3). Plain text (no `#`) parses as one
    section of paragraphs.
    """

    def default_intake_hints(self) -> IntakeHints:
        # Documents default to reference/None; the request's declared_type +
        # source_class override these (IntakePolicy owns the decision).
        return {"kind": "document", "source_class": "reference", "declared_type": None}

    def normalize(self, raw_input: PlainDocumentInput) -> NormalizedSource:
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

        return NormalizedSource(
            raw=raw_input.raw,
            blocks=blocks,
            structure=StructureMap(sections=spans),
        )
