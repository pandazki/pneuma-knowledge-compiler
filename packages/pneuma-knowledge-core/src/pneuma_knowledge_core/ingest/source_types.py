"""Typed source plugins: the vertical seam for structured context streams.

WHY THIS EXISTS (design intent)
-------------------------------
Developer tools, meeting bots, agents, and local recorders emit structured, high-context
streams. The generic upload path is universal precisely because it discards structure;
typed context data is the opposite — its structure IS the signal. Each stream is therefore
a vertical plugin that preserves and
exploits structure end-to-end, instead of being flattened into the generic document path.

A `FirstPartySourceType` bundles the FOUR places one stream differs from another:

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

UNCERTAINTY IS FIRST-CLASS. Real capture is noisy ASR with environmental sound; no type
targets byte-perfect extraction. Every concern degrades gracefully — never fabricate
structure the capture didn't provide; mark or drop noise rather than assert it. Success is
"the owner's high-value memory is captured and correctly attributed more often, with
uncertainty preserved", not zero error.

The generic `upload` path is the degenerate type (no loader beyond the posted body, plain
formatter, no per-type compile guidance, settings-driven indexing); first-party types are
an ADDITIVE plugin layer over it, so adding a source integration never touches the core
compile/recall engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..domain.source import ConversationTurn, NormalizedSource, RawSource, SourceOrigin
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
        return (
            "【第一方数据说明】\n"
            f"· 数据结构：{self.data_context}\n"
            f"· 功能意图：{self.app_context}"
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

    def format(self, raw: RawSource, turns: list[ConversationTurn]) -> NormalizedSource:
        """Concern 2: typed turns → addressable, owner-anchored NormalizedSource."""
        ...

    def compile_guidance(self) -> CompileGuidance | None:
        """Concern 3: per-type compile context, or None for the generic path."""
        ...

    def indexing(self) -> IndexingSpec:
        """Concern 4: L2 chunking strategy for this stream."""
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


_CONTEXT_STREAM_GUIDANCE = CompileGuidance(
    data_context=(
        "这是结构化工作上下文流，已按声道把说话人分成「本人」与「参与者N」"
        "（同一 N 全文指同一人）。转录可能来自 ASR，夹着环境音、串音和识别错误——"
        "人名、数字、日期、否定词、责任人这些改变含义的词经常不可靠。"
    ),
    app_context=(
        "context stream 要把本人参与的工作过程沉淀为日后可行动、可解释、可审计的知识："
        "产品假设、技术决定、实验、承诺、风险与悬而未决的问题。本人是这段知识的主体——"
        "从大量上下文里凸显未来有用的内容，不做逐字纪要。"
        "谁说的都如实记为出处：归属是**溯源、不是裁定**——拿不准某件事是不是本人的，就留成不确定，"
        "不下正反结论。承诺按现场实际的确定程度记：提议不等于已定的决定，关键值听不清就留待确认，"
        "不拔高成事实。"
    ),
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

    def format(self, raw: RawSource, turns: list[ConversationTurn]) -> NormalizedSource:
        return self._adapter.normalize(PlainConversationInput(raw=raw, turns=turns))

    def compile_guidance(self) -> CompileGuidance | None:
        return _CONTEXT_STREAM_GUIDANCE

    def indexing(self) -> IndexingSpec:
        return IndexingSpec(chunk_strategy="semantic")


# origin → first-party type. `upload` is absent (the generic default path handles it).
_FIRST_PARTY_TYPES: dict[str, FirstPartySourceType] = {
    "context_stream": ContextStreamSourceType(),
}


def first_party_type(origin: str) -> FirstPartySourceType | None:
    """Resolve the first-party plugin for an origin, or None for the generic upload path."""
    return _FIRST_PARTY_TYPES.get(origin)
