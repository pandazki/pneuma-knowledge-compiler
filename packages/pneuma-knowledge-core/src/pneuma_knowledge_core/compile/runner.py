"""Compile main loop (pure core; middleware injected via ports).

Assembles a byte-stable SystemMessage (render_system_contract) + a HumanMessage carrying
this compile's supplied sources and the existing canonical documents, then drives a
langchain tool loop over the claim-level write tools. When the model finishes (or the
tool-call budget is spent) the mechanical gate runs; on violations one repair round
feeds the violation text back and re-runs the loop. Still-failing → abort with the
canonical layer untouched (no commit). Passing + dirty → commit_patch + derive_events.

Nothing here persuades the model; the anchor/citation/path mechanisms are enforced by
the tools and the gate (architecture.md §0 discipline 1).
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from dataclasses import dataclass
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool

from ..domain.canonical import CanonicalDocument
from ..domain.ids import UserId, SourceId, extract_anchors
from ..recall.citation_alias import resolve_handles
from ..domain.snapshot import SnapshotRef
from ..domain.source import NormalizedSource
from ..ports.canonical_store import CanonicalStore
from ..skill.contract import render_system_contract
from ..skill.version import SkillVersion
from .anchor_ops import AnchorToolError
from .documents import render_document
from .gate import Violation, run_gate
from .patch import PatchDraft
from .transitions import CompileEvent, derive_events

# Injected read ports, mirroring evolve/runner.py's shape. compile was the only agentic
# stage in the system with NO retrieval at all — it could list paths and read a document by
# exact path, but never ask "what do I already know about X". That is why context had to be
# supplied by dumping the whole knowledge base. Both are optional: absent → a tool that
# says so, never a crash.
SearchKnowledge = Callable[[str], Awaitable[str]]
SearchSource = Callable[[str], Awaitable[str]]


async def _search_knowledge_unavailable(query: str) -> str:
    return "（本次未接 L3 检索端口，search_knowledge 不可用；可用 read_document 按路径读取）"


async def _search_source_unavailable(query: str) -> str:
    return "（本次未接 L1/L2 检索端口，search_source 不可用；只能使用本轮供给的素材）"


# Centralized loop bounds.
MAX_TOOL_CALLS = 40
MAX_REPAIR_ROUNDS = 1

# Per-source treatment instruction segments (architecture.md §4 执行路径). These are
# fixed strings mechanically mapped from IntakePlan.canonical_treatment — a mechanism,
# not persuasion (§0 discipline 1). They ride the HumanMessage (task content), never
# the byte-stable SystemMessage (I5). skill instructions are unchanged.
Treatment = Literal["full", "distill", "card"]

_TREATMENT_INSTRUCTIONS: dict[str, str] = {
    "full": (
        "【treatment=full · 常规全量消化】按 skill 判断把该素材中值得长期记忆的语义编译进 "
        "canonical，各按主体归档到 skill 允许的归档位。"
        "若该素材通不过准入标准（寒暄、通知播报、无后续效用的过程细节），"
        "就**不为它写任何 claim**——它仍留在 L0 原文与检索层，不算漏。"
    ),
    "distill": (
        "【treatment=distill · 定向蒸馏】该素材的正文不进 canonical，靠 L0/L1 可达即可。"
        "**注意：让这份素材「能被搜到」不是你的任务——L1/L2 已经做到了。**"
        "你要做的只有一件事：判断它有没有**改变或推进某条脉络**，"
        "有就把那一点写进**相应主体已有的文档**（`edit_claim` / `append_block`）。"
        "没有就什么都不写——为一份素材建一张只是概括它的卡，功能上与 L1/L2 重复，"
        "只是给不可重建层增加副本。"
        "只有当这份资料**本身**就是一个需要长期指向的主体（外部报告、合同、规范、评测集）时，"
        "才建 `materials/{slug}.md`，并写清它属于哪条脉络、支撑了哪个决定。"
    ),
    "card": (
        "【treatment=card · 仅登记】只登记这份资料**存在过、属于哪条脉络**，不抄内容细节。"
        "**若它不挂在任何脉络上，就不要登记**——单纯「存着能搜到」由 L1/L2 负责。slug 按主体取。"
    ),
}


@dataclass
class CompileResult:
    status: Literal["committed", "aborted", "noop"]
    files: dict[str, str]
    events: list[CompileEvent]
    violations: list[Violation]
    rounds: int
    tool_calls: int
    token_usage: dict[str, int]
    snapshot: SnapshotRef | None = None


def _render_time_anchor(
    sources: Sequence[NormalizedSource], now: "datetime | None"
) -> list[str]:
    """The task's time frame: when this compile runs, and what period the material covers.

    The skill requires relative time ("明天", "上周") to be normalized to absolute dates, but
    the prompt carried no reference point to normalize AGAINST: the only dates present were
    whatever happened to appear inside the text. `RawSource.created_at` is no help either —
    it is the INGEST wall-clock, so material captured weeks ago is stamped with today.

    The window is derived from each source's own occurrence metadata (`occurred_on`, else the
    date section paths the conversation adapters cut). `now` is passed in rather than read
    from the clock so the render stays deterministic and testable.
    """
    lines: list[str] = []
    if now is not None:
        lines.append(f"- **本次编译时间**：{now.date().isoformat()}")
    dates: set[str] = set()
    for s in sources:
        occurred_on = str((s.raw.meta or {}).get("occurred_on") or "").strip()
        if occurred_on:
            dates.add(occurred_on)
            continue
        for span in s.structure.sections:
            for part in span.path:
                if len(part) == 10 and part[4] == "-" and part[7] == "-":
                    dates.add(part)
    if dates:
        lo, hi = min(dates), max(dates)
        span_text = lo if lo == hi else f"{lo} — {hi}"
        lines.append(f"- **本轮素材发生于**：{span_text}（共 {len(dates)} 天）")
        lines.append(
            "- 素材里的相对时间（「昨天」「上周」「下周一」）以**素材发生日**为基准归一为绝对日期，"
            "不要以本次编译时间为基准；基准不可靠时保留原话并标为待确认。"
        )
    else:
        lines.append(
            "- **本轮素材未提供发生时间**：不要推断绝对日期，相对时间一律保留原话并标为待确认。"
        )
    return lines


def _render_outline(base_docs: list[CanonicalDocument]) -> list[str]:
    """Existing canonical as an OUTLINE: one line per document — path, type, claim count,
    section headings. Not the bodies.

    The task used to inline every existing document in full, so the prompt grew with the
    size of the knowledge base rather than with the material being compiled: a job with a
    handful of new sources spent the overwhelming majority of its window re-reading knowledge
    it already had, and that share only rises as the base grows. An outline gives the shape
    (what subjects exist, where they live, how developed each is) at a fraction of the cost;
    the CONTENT of whatever is actually relevant arrives two ways instead — the retrieved
    claim subset below, and `search_knowledge` / `read_document` on demand.

    Note the draft still holds every document (PatchDraft.from_canonical): anchor continuity
    and the gate need the full set. Only what the MODEL is shown changes here.
    """
    if not base_docs:
        return ["(暂无既有 canonical；用 create_document 新建)"]
    lines: list[str] = []
    for d in sorted(base_docs, key=lambda x: x.path):
        heads = [
            ln[3:].strip()
            for ln in d.body.splitlines()
            if ln.startswith("## ") and ln[3:].strip()
        ]
        claims = len(extract_anchors(d.body))
        doc_type = str((d.frontmatter or {}).get("type") or "?")
        tail = f"：{' / '.join(heads)}" if heads else ""
        lines.append(f"- `{d.path}`（type={doc_type}，{claims} 条 claim）{tail}")
    return lines


def _render_task(
    sources: Sequence[NormalizedSource],
    base_docs: list[CanonicalDocument],
    treatments: Mapping[str, str] | None = None,
    source_guidance: Mapping[str, str] | None = None,
    source_preamble: Mapping[str, str] | None = None,
    retrieved: str | None = None,
    now: "datetime | None" = None,
) -> str:
    treatments = treatments or {}
    source_guidance = source_guidance or {}
    source_preamble = source_preamble or {}
    parts: list[str] = []

    # First-party per-type guidance is a per-ORIGIN constant, so it is stated ONCE per job
    # rather than re-pasted under every source. It used to repeat verbatim per source, so a
    # job carrying many same-origin sources spent a large share of its window restating one
    # identical paragraph — which both wastes the window and dilutes the instruction.
    distinct_guidance: list[str] = []
    for s in sources:
        g = source_guidance.get(str(s.raw.source_id))
        if g and g not in distinct_guidance:
            distinct_guidance.append(g)
    if distinct_guidance:
        parts.append("# 本轮素材的类型说明（适用于下列全部素材）\n")
        parts.extend(distinct_guidance)
        parts.append("")

    # Treatment explanations are one of three FIXED strings, so they are stated once per job
    # (only the ones actually used) and each source then carries a short tag. Pasting the
    # full paragraph under every source was the same waste as the per-type guidance: on a
    # day of mostly-distill sources it spent thousands of characters repeating one string.
    used: list[str] = []
    for s_ in sources:
        t = treatments.get(str(s_.raw.source_id), "full")
        if t not in used:
            used.append(t)
    if used:
        parts.append("# 本轮用到的处理档位\n")
        for t in used:
            parts.append(_TREATMENT_INSTRUCTIONS.get(t, _TREATMENT_INSTRUCTIONS["full"]))
        parts.append("")

    parts.append("# 本轮的时间坐标\n")
    parts.extend(_render_time_anchor(sources, now))
    parts.append("")

    parts.append("# 本次编译供给的素材\n")
    for s in sources:
        parts.append(f"## source {s.raw.source_id} — {s.raw.title}")
        # Per-source provenance sentence with the OWNER as subject: whose material, when it
        # happened, what his role in it was. The transcript cannot convey any of that, and
        # authorship + time are exactly what the compiler must not guess.
        preamble = source_preamble.get(str(s.raw.source_id))
        if preamble:
            parts.append(preamble)
        treatment = treatments.get(str(s.raw.source_id), "full")
        parts.append(f"→ 处理档位：**treatment={treatment}**（说明见开头）")
        for b in s.blocks:
            parts.append(f"¶{b.index} {b.text}")
        parts.append("")
    parts.append("# 既有 canonical 全貌（大纲）\n")
    parts.append(
        "这是本人知识库当前的全部文档，只列结构不列正文。"
        "先在这里找主体是否已经存在：**已存在就用 `edit_claim` / `append_block` 就地更新，"
        "不要另建一篇新文档**；需要正文时用 `read_document(path)` 或 `search_knowledge(query)` 取。"
    )
    parts.append("")
    parts.extend(_render_outline(base_docs))

    if retrieved:
        parts.append("\n# 与本轮素材相关的既有 claim（自动召回，供对齐与更新）\n")
        parts.append(
            "以下 claim 是按本轮素材检索出来的既有知识，**不是本轮的证据**——"
            "它们的作用是让你发现该更新哪一条、避免重复建立同义 claim。"
            "要引用证据仍须回到本轮素材的 ¶ 区间。"
        )
        parts.append("")
        parts.append(retrieved.rstrip())
    return "\n".join(parts)


def _with_skill_trailer(message: str, skill: SkillVersion) -> str:
    """Append a git trailer block recording which skill version compiled this snapshot.

    A free git audit trace (architecture.md §9 M5): a blank line then `Key: value`
    trailers. `git log --format=%(trailers:key=Skill-Version,valueonly)` reads it back.
    Forward-only — old commits keep whatever version compiled them; this never rewrites
    history."""
    trailers = (
        f"Skill-Version: {skill.version}",
        f"Skill-Id: {skill.skill_id}",
        f"Skill-Content-Hash: {skill.content_hash}",
    )
    return f"{message}\n\n" + "\n".join(trailers)


def _render_violations(violations: Sequence[Violation]) -> str:
    lines = [
        "# gate 拒绝：以下机械校验未通过，请用 claim 级工具修正后重新 finish_compile。",
    ]
    lines.extend(v.render() for v in violations)
    return "\n".join(lines)


def _build_tools(
    draft: PatchDraft,
    search_knowledge: SearchKnowledge | None = None,
    search_source: SearchSource | None = None,
) -> list[StructuredTool]:
    """The claim-level write tools. Deliberately SYNC: every one of them mutates only the
    in-memory PatchDraft (no port, no network), and the runner's hand-rolled loop calls
    `tool.func(**args)` directly rather than handing the tools to an agent — so there is
    nothing to await and async would only color the loop for free."""

    def list_documents() -> str:
        return "\n".join(draft.list_paths()) or "(no documents yet)"

    def read_document(path: str) -> str:
        doc = draft.read(path)
        return render_document(doc.frontmatter, doc.body)

    def create_document(path: str, frontmatter: dict, body: str) -> str:
        doc = draft.create_document(path, frontmatter, body)
        anchors = ", ".join(extract_anchors(doc.body)) or "(none)"
        return f"created {path} (pneuma_id={doc.pneuma_id}); system-assigned anchors: {anchors}"

    def edit_claim(path: str, anchor_id: str, new_text: str) -> str:
        draft.edit_claim(path, anchor_id, new_text)
        return f"edited claim c:{anchor_id} in {path} (anchor preserved)"

    def append_block(path: str, heading: str, text: str) -> str:
        before = set(extract_anchors(draft.read(path).body))
        doc = draft.append_block(path, heading, text)
        new = [a for a in extract_anchors(doc.body) if a not in before]
        return f"appended claim to {path} under '{heading}'; assigned anchor: {new}"

    def finish_compile() -> str:
        return "compile finished"

    _search_knowledge = search_knowledge or _search_knowledge_unavailable
    _search_source = search_source or _search_source_unavailable

    async def search_knowledge_tool(query: str) -> str:
        return await _search_knowledge(query)

    async def search_source_tool(query: str) -> str:
        return await _search_source(query)

    return [
        StructuredTool.from_function(list_documents, description="列出现有 canonical 文档路径。"),
        StructuredTool.from_function(read_document, description="读取一份文档完整内容（含锚）。"),
        StructuredTool.from_function(create_document, description="新建文档；系统分配 pneuma_id 与全部锚。"),
        StructuredTool.from_function(edit_claim, description="原位改写指定锚的 claim，锚自动保持。"),
        StructuredTool.from_function(append_block, description="在小节末尾新增一条 claim，锚由系统分配。"),
        StructuredTool.from_function(finish_compile, description="无更多写操作时调用，结束本次编译。"),
        StructuredTool.from_function(
            coroutine=search_knowledge_tool,
            name="search_knowledge",
            description=(
                "按 query 检索**既有 canonical claim**（L3），返回命中 claim 的锚与所在文档路径。"
                "用它判断某个主体是否已经记过、该更新哪一条锚，而不是另建新文档。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=search_source_tool,
            name="search_source",
            description=(
                "按 query 检索**原始素材**（L1/L2），跨源找旁证或补上下文。"
                "注意：只有本轮供给的素材才能作为 citation 的 source_id。"
            ),
        ),
    ]


async def run_compile(
    *,
    user_id: UserId,
    model: BaseChatModel,
    store: CanonicalStore,
    sources: Sequence[NormalizedSource],
    skill: SkillVersion,
    commit_message: str = "compile",
    treatments: Mapping[str, str] | None = None,
    source_guidance: Mapping[str, str] | None = None,
    known_source_bounds: Mapping[str, int] | None = None,
    source_preamble: Mapping[str, str] | None = None,
    owner: object | None = None,
    retrieved: str | None = None,
    search_knowledge: SearchKnowledge | None = None,
    search_source: SearchSource | None = None,
    now: "datetime | None" = None,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> CompileResult:
    # Compile-boundary citation aliasing: the model mis-copies 32-char UUID source ids into
    # `[cite:]` markers (blind audit: a whole source was lost when the compiler mis-typed
    # its id 4× → gate rejected). Show it short per-job handles `sNN` instead; the gate
    # validates handles; on commit we resolve them back so canonical stores the real ids.
    handle_by_real = {str(s.raw.source_id): f"s{i + 1:02d}" for i, s in enumerate(sources)}
    real_by_handle = {h: r for r, h in handle_by_real.items()}
    a_sources = [
        s.model_copy(
            update={
                "raw": s.raw.model_copy(
                    update={"source_id": SourceId(handle_by_real[str(s.raw.source_id)])}
                )
            }
        )
        for s in sources
    ]
    treatments = {handle_by_real[k]: v for k, v in (treatments or {}).items() if k in handle_by_real}
    source_guidance = {
        handle_by_real[k]: v for k, v in (source_guidance or {}).items() if k in handle_by_real
    }
    source_preamble = {
        handle_by_real[k]: v for k, v in (source_preamble or {}).items() if k in handle_by_real
    }

    base_docs = await store.list(user_id)
    draft = PatchDraft.from_canonical(base_docs, skill.path_templates)
    tools = _build_tools(draft, search_knowledge, search_source)
    by_name = {t.name: t for t in tools}
    bound = model.bind_tools(tools)

    # core depends only on langchain's callback abstraction (architecture.md §2): the
    # service injects a langfuse handler via `callbacks`; every invoke in the tool loop
    # carries it so Langfuse sees each multi-turn tool round. Keyless → config is a no-op.
    invoke_config = {
        "callbacks": callbacks or [],
        "metadata": trace_metadata or {},
        "run_name": "compile",
    }

    messages: list[BaseMessage] = [
        SystemMessage(content=render_system_contract(skill, owner=owner)),
        HumanMessage(
            content=_render_task(
                a_sources,
                base_docs,
                treatments,
                source_guidance,
                source_preamble,
                retrieved,
                now,
            )
        ),
    ]

    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    tool_calls = 0

    def accumulate(response: BaseMessage) -> None:
        meta = getattr(response, "usage_metadata", None) or {}
        for key in usage:
            usage[key] += int(meta.get(key, 0) or 0)

    async def tool_loop() -> None:
        nonlocal tool_calls
        while tool_calls < MAX_TOOL_CALLS:
            response = await bound.ainvoke(messages, config=invoke_config)
            messages.append(response)
            accumulate(response)
            calls = getattr(response, "tool_calls", None) or []
            if not calls:
                return  # model ended its turn without more tool calls
            for call in calls:
                tool_calls += 1
                name, args, cid = call["name"], call.get("args", {}), call.get("id")
                if name == "finish_compile":
                    messages.append(ToolMessage(content="ok", tool_call_id=cid))
                    return
                tool = by_name.get(name)
                if tool is None:
                    content = f"unknown tool: {name}"
                else:
                    fn = tool.coroutine or tool.func
                    try:
                        # Read ports are async; the write tools stay sync (pure in-memory
                        # PatchDraft mutation). Dispatch on the function, as evolve does.
                        content = (
                            await fn(**args)
                            if inspect.iscoroutinefunction(fn)
                            else fn(**args)
                        )
                    except AnchorToolError as exc:
                        content = str(exc)
                    except (TypeError, ValueError) as exc:
                        content = f"tool {name} 调用失败：{exc}"
                messages.append(ToolMessage(content=content, tool_call_id=cid))
                if tool_calls >= MAX_TOOL_CALLS:
                    return

    await tool_loop()
    rounds = 1
    violations = run_gate(
        draft,
        sources,
        alias_map=real_by_handle,
        known_source_bounds=known_source_bounds,
    )

    if violations and MAX_REPAIR_ROUNDS >= 1:
        messages.append(HumanMessage(content=_render_violations(violations)))
        await tool_loop()
        rounds = 2
        violations = run_gate(
            draft,
            sources,
            alias_map=real_by_handle,
            known_source_bounds=known_source_bounds,
        )

    files = draft.to_files()
    if violations:
        # Abort: canonical layer untouched (no commit).
        return CompileResult(
            status="aborted",
            files=files,
            events=[],
            violations=violations,
            rounds=rounds,
            tool_calls=tool_calls,
            token_usage=usage,
            snapshot=None,
        )

    if not draft.is_dirty():
        return CompileResult(
            status="noop",
            files=files,
            events=[],
            violations=[],
            rounds=rounds,
            tool_calls=tool_calls,
            token_usage=usage,
            snapshot=None,
        )

    # Resolve the per-job `sNN` handles back to real source ids, so canonical stores real
    # provenance (base docs already carry real ids; only the model's new citations use
    # handles). Both the committed files and the event diff run over the resolved bodies.
    files = {p: resolve_handles(b, real_by_handle) for p, b in files.items()}
    new_bodies = {p: resolve_handles(b, real_by_handle) for p, b in draft.new_bodies().items()}
    snapshot = await store.commit_patch(
        user_id, files, message=_with_skill_trailer(commit_message, skill)
    )
    events = derive_events(draft.base_bodies(), new_bodies)
    return CompileResult(
        status="committed",
        files=files,
        events=events,
        violations=[],
        rounds=rounds,
        tool_calls=tool_calls,
        token_usage=usage,
        snapshot=snapshot,
    )
