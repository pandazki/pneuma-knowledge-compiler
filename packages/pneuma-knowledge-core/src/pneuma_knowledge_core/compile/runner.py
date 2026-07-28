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

from collections.abc import Mapping, Sequence
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
        "【treatment=full · 常规全量消化】按 skill 判断把该素材中值得长期记忆的语义"
        "编译进 canonical（people/topics/profile 各按主体归档）。"
    ),
    "distill": (
        "【treatment=distill · 定向蒸馏】只为该素材建一张 materials/{slug}.md 资料卡："
        "是什么 / 覆盖什么 / 关键信息 claims（每条 claim 用 citation 指向原文 ¶）；"
        "不要把正文逐条搬进 people/topics，正文靠 L0/L1 可达。"
    ),
    "card": (
        "【treatment=card · 仅卡片元信息】只为该素材建 materials/{slug}.md 卡片元信息"
        "（标题 / 类型 / 覆盖范围一两条），不蒸馏内容细节；正文靠 L0/L1 可达。"
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


def _render_task(
    sources: Sequence[NormalizedSource],
    base_docs: list[CanonicalDocument],
    treatments: Mapping[str, str] | None = None,
    source_guidance: Mapping[str, str] | None = None,
) -> str:
    treatments = treatments or {}
    source_guidance = source_guidance or {}
    parts: list[str] = ["# 本次编译供给的素材\n"]
    for s in sources:
        parts.append(f"## source {s.raw.source_id} — {s.raw.title}")
        # First-party per-type compile guidance (data-context + app-intent) rides here,
        # before the treatment instruction — it tells the compiler what this stream is and
        # what is worth remembering, which the transcript alone cannot convey.
        guidance = source_guidance.get(str(s.raw.source_id))
        if guidance:
            parts.append(guidance)
        treatment = treatments.get(str(s.raw.source_id), "full")
        instruction = _TREATMENT_INSTRUCTIONS.get(
            treatment, _TREATMENT_INSTRUCTIONS["full"]
        )
        parts.append(instruction)
        for b in s.blocks:
            parts.append(f"¶{b.index} {b.text}")
        parts.append("")
    parts.append("# 现有 canonical 文档")
    if not base_docs:
        parts.append("(暂无，可用 create_document 新建)")
    else:
        for d in base_docs:
            parts.append(f"\n## {d.path}")
            parts.append(render_document(d.frontmatter, d.body).rstrip())
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


def _build_tools(draft: PatchDraft) -> list[StructuredTool]:
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

    return [
        StructuredTool.from_function(list_documents, description="列出现有 canonical 文档路径。"),
        StructuredTool.from_function(read_document, description="读取一份文档完整内容（含锚）。"),
        StructuredTool.from_function(create_document, description="新建文档；系统分配 pneuma_id 与全部锚。"),
        StructuredTool.from_function(edit_claim, description="原位改写指定锚的 claim，锚自动保持。"),
        StructuredTool.from_function(append_block, description="在小节末尾新增一条 claim，锚由系统分配。"),
        StructuredTool.from_function(finish_compile, description="无更多写操作时调用，结束本次编译。"),
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

    base_docs = await store.list(user_id)
    draft = PatchDraft.from_canonical(base_docs, skill.path_templates)
    tools = _build_tools(draft)
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
        SystemMessage(content=render_system_contract(skill)),
        HumanMessage(
            content=_render_task(a_sources, base_docs, treatments, source_guidance)
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
                    try:
                        content = tool.func(**args)
                    except AnchorToolError as exc:
                        content = str(exc)
                    except (TypeError, ValueError) as exc:
                        content = f"tool {name} 调用失败：{exc}"
                messages.append(ToolMessage(content=content, tool_call_id=cid))
                if tool_calls >= MAX_TOOL_CALLS:
                    return

    await tool_loop()
    rounds = 1
    violations = run_gate(draft, sources, alias_map=real_by_handle)

    if violations and MAX_REPAIR_ROUNDS >= 1:
        messages.append(HumanMessage(content=_render_violations(violations)))
        await tool_loop()
        rounds = 2
        violations = run_gate(draft, sources, alias_map=real_by_handle)

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
