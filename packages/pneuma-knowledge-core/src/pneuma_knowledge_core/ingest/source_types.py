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

import re
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

    def describe(self, raw: RawSource, blocks_count: int, owner_name: str) -> str:
        """Medium-neutral: a diarized stream with turn counts and the owner's involvement.
        A deployment whose capture has a名字 (a chat room, a call) subclasses and overrides
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
# All examples below use the repository's synthetic persona (林知远 / Atlas, see
# examples/seed_demo.py). Never illustrate with real captured material.
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
    accidental double spaces. The preamble is assembled from a mix of Chinese templates and
    Latin names/dates, so doing this once at the end beats hand-tuning every seam that
    would otherwise read as 「林知远在场」/「一篇Atlas 周报」.

    Spans inside 「」 are left byte-for-byte alone: those are DATA (a document title, a chat
    room's name), not prose. Re-spacing them would silently rewrite a proper noun whose exact
    form callers may rely on — 「Atlas MVP发布组」 must not become 「Atlas MVP 发布组」.
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


def _context_stream_preamble(raw: RawSource, blocks_count: int, owner_name: str) -> str:
    """A diarized stream → one sentence with the owner as subject.

    Core stays domain-neutral: it renders the metadata the ingest side supplies and knows
    nothing about what KIND of stream this is. `meta["scene"]` is the business-supplied
    phrase for where this happened (a chat room, a call, a recorded session); absent, the
    sentence degrades to an unqualified one rather than guessing a medium.
    """
    meta = raw.meta or {}
    scene = str(meta.get("scene") or "").strip() or "一段对话"
    when = str(meta.get("occurred_on") or "").strip()
    part = ""
    if int(meta.get("part_count") or 1) > 1:
        part = f"，当日第 {meta.get('part')}/{meta.get('part_count')} 段"
    owner_turns = int(meta.get("owner_turns") or 0)
    role = (
        f"{owner_name}发言 {owner_turns} 次"
        if owner_turns
        else f"{owner_name}在场，但本段没有发言"
    )
    mentions = int(meta.get("owner_mentions") or 0)
    if mentions:
        role += f"，被 @ 提及 {mentions} 次"
    replied = int(meta.get("owner_replied_to") or 0)
    if replied:
        role += f"，有 {replied} 条消息在回复他"
    when_part = f"{when} " if when else ""
    # Owner-as-subject: "这是 <owner> 于 <when> 在 <场景>…", not "这是 <场景>…".
    return f"这是 {owner_name} {when_part}{scene}，共 {blocks_count} 条消息{part}。{role}。"


def _document_preamble(raw: RawSource, owner_name: str) -> str:
    meta = raw.meta or {}
    kind = meta.get("doc_kind") or meta.get("declared_type") or "文档"
    author = str(meta.get("author") or "").strip()
    by_owner = bool(meta.get("authored_by_owner")) or author == owner_name
    created, updated = _fmt_when(meta.get("created_at")), _fmt_when(meta.get("updated_at"))
    who = owner_name if by_owner else (author or "他人")
    title_part = f"，标题为「{raw.title}」" if raw.title else ""
    when = f"于 {created} 创建" if created else ""
    if updated and updated[:10] != created[:10]:
        when = f"{when}、{updated[:10]} 最后更新" if when else f"{updated[:10]} 最后更新"
    parent = f"，隶属于上层文档「{meta.get('parent_title')}」" if meta.get("parent_title") else ""
    stance = (
        f"{owner_name}是作者，文中的判断默认属于他。"
        if by_owner
        else f"{owner_name}是读者而不是作者，文中的判断属于{who}，不得记成他自己的决定。"
    )
    lead = f"这是{who}{when}的一篇{kind}{title_part}{parent}。"
    return f"{lead}{stance}"


def _reference_preamble(raw: RawSource, owner_name: str) -> str:
    """`source_class == "reference"` with no authorship metadata:外部资料。The stance
    clause matters more than the provenance detail — it must not be read as the owner's
    own words."""
    title_part = f"「{raw.title}」" if raw.title else ""
    return (
        f"这是一份供{owner_name}参考的外部资料{title_part}，不是他本人的表述。"
        f"其中的说法属于资料作者；只有当它确实构成对他将来有用的事实时才编译，并如实标注来源。"
    )


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


def describe_source(raw: RawSource, blocks_count: int, owner_name: str = "本人") -> str:
    """One sentence naming whose material this is, when it happened, and the owner's role.

    Dispatches on the source's own shape (origin / kind / source_class) and degrades to a
    minimal but still owner-subject sentence when metadata is thin — a source with no
    metadata should read as "provenance unknown", never as if it were the owner's own.

    Shape of the output (synthetic persona; see examples/seed_demo.py):

      context_stream (scene supplied by the ingest side)
        这是 林知远 2026-07-18 在 Atlas 评审会上的一段对话，共 12 条消息。
        林知远发言 4 次，被 @ 提及 1 次。
      document authored by the owner
        这是 林知远 于 2026-07-18 09:30 创建的一篇工作笔记，标题为「Atlas 发布检查」。
        林知远是作者，文中的判断默认属于他。
      document authored by someone else
        这是 宋遥 于 2026-07-10 14:05 创建的一篇工作笔记，标题为「…」。
        林知远是读者而不是作者，文中的判断属于宋遥，不得记成他自己的决定。
    """
    return _spaced(_describe(raw, blocks_count, owner_name))


def _describe(raw: RawSource, blocks_count: int, owner_name: str) -> str:
    # Concern 5 belongs to the registered type when there is one, so a deployment's own
    # phrasing wins without core knowing anything about its medium.
    plugin = _FIRST_PARTY_TYPES.get(str(raw.origin))
    describe = getattr(plugin, "describe", None)
    if callable(describe):
        return describe(raw, blocks_count, owner_name)
    meta = raw.meta or {}
    if raw.kind == "document":
        if meta.get("author") or meta.get("created_at") or meta.get("authored_by_owner"):
            return _document_preamble(raw, owner_name)
        if raw.source_class == "reference":
            return _reference_preamble(raw, owner_name)
        title_part = f"「{raw.title}」" if raw.title else ""
        return (
            f"这是{owner_name}导入的一篇文档{title_part}；素材未提供作者与成文时间，"
            f"因此不得默认其中的判断出自他本人。"
        )
    title_part = f"「{raw.title}」" if raw.title else ""
    return (
        f"这是{owner_name}知识库中的一份素材{title_part}；素材未提供出处与时间，"
        f"归属与时间一律留待确认。"
    )


# origin → first-party type. `upload` is absent (the generic default path handles it).
_FIRST_PARTY_TYPES: dict[str, FirstPartySourceType] = {
    "context_stream": ContextStreamSourceType(),
}


def first_party_type(origin: str) -> FirstPartySourceType | None:
    """Resolve the first-party plugin for an origin, or None for the generic upload path."""
    return _FIRST_PARTY_TYPES.get(origin)
