"""Phase 2: whole-KB reorganization runner (schema-evolve §2.3).

Shaped like `compile.runner.run_compile` — a hand-rolled tool loop over an in-memory
`PatchDraft` — with the differences a whole-KB reorganization demands:

- **A wider tool face.** The claim-level compile tools plus the evolve-only merge channel
  (`move_claim` / `delete_claim`) and two READ ports (`search_knowledge` / `fetch_source`)
  for re-finding evidence and fetching verbatim source blocks. move is the main verb:
  a claim moves to its new family VERBATIM, anchor unchanged, so L3 / events / git blame
  stay continuous.
- **Mixed sync/async dispatch.** The write tools mutate only the in-memory draft (sync);
  the two read ports are async port calls. The loop picks the branch with
  `inspect.iscoroutinefunction`, so an async tool is awaited and its result rides a
  ToolMessage like any other.
- **One System, two contracts concatenated.** `render_system_contract(new_skill)` (the
  write mechanics + the new skill's families) then the phase-2 task contract — a single
  byte-stable SystemMessage per (new_skill, contract).
- **Bigger budget:** MAX_TOOL_CALLS=120 (a whole-KB pass dwarfs one compile),
  MAX_REPAIR_ROUNDS=1 (one gate-violation feedback round).

The core does NOT commit — the branch commit is the service's (Stage C). Still-failing
after the repair round → status="aborted" (nothing lands). Passing → an EvolveResult with
the produced files, the dropped-anchor list, and a mechanical summary.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from ..compile.anchor_ops import AnchorToolError
from ..compile.documents import render_document
from ..compile.gate import Violation
from ..compile.patch import PatchDraft
from ..domain.canonical import CanonicalDocument
from ..domain.ids import UserId, extract_anchors
from ..skill.contract import render_system_contract
from ..skill.version import SkillVersion
from .contracts import phase2_contract
from .gate import DroppedAnchor, SourceBounds, run_evolve_gate
from .propose import EvolveProposal

# A whole-KB reorganization is much larger than a single compile.
MAX_TOOL_CALLS = 120
MAX_REPAIR_ROUNDS = 1

SearchKnowledge = Callable[[str], Awaitable[str]]
FetchSource = Callable[[str, int, int], Awaitable[str]]


@dataclass
class EvolveResult:
    status: Literal["completed", "aborted", "noop"]
    files: dict[str, str]
    dropped: list[DroppedAnchor]
    summary: dict
    tool_calls: int
    token_usage: dict[str, int]


async def _search_unavailable(query: str) -> str:
    return "（本次未接检索端口，search_knowledge 不可用）"


async def _fetch_unavailable(source_id: str, block_start: int, block_end: int) -> str:
    return "（本次未接原文端口，fetch_source 不可用）"


def _render_evolve_task(base_docs: list[CanonicalDocument], proposal: EvolveProposal) -> str:
    parts: list[str] = ["# 现有 canonical 文档（全量）"]
    if not base_docs:
        parts.append("(暂无文档)")
    else:
        for d in base_docs:
            parts.append(f"\n## {d.path}")
            parts.append(render_document(d.frontmatter, d.body).rstrip())
    parts.append("\n# 本次 schema evolve 依据\n" + proposal.rationale)
    families: list[str] = []
    for pack in proposal.packs:
        for template in pack.extra_path_templates:
            families.append(f"- {template}")
        if pack.extra_instructions.strip():
            families.append(f"  ↳ {pack.extra_instructions.strip()}")
    parts.append(
        "\n# 新增的模板家族（把 topics 里本应属于这些家族的语义搬移归位）\n"
        + ("\n".join(families) or "（无）")
    )
    return "\n".join(parts)


def _render_violations(violations: list[Violation]) -> str:
    lines = [
        "# evolve gate 拒绝：以下机械校验未通过，请用工具修正后重新 finish_evolve。",
    ]
    lines.extend(v.render() for v in violations)
    return "\n".join(lines)


async def run_evolve(
    *,
    user_id: UserId,
    model: BaseChatModel,
    base_docs: list[CanonicalDocument],
    new_skill: SkillVersion,
    proposal: EvolveProposal,
    source_bounds: SourceBounds,
    search_knowledge: SearchKnowledge | None = None,
    fetch_source: FetchSource | None = None,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> EvolveResult:
    """Drive the phase-2 reorganization tool loop, then the evolve gate. See module docstring."""
    _search = search_knowledge or _search_unavailable
    _fetch = fetch_source or _fetch_unavailable

    draft = PatchDraft.from_canonical(base_docs, new_skill.path_templates)

    # Mechanical summary counters (closure state for the tool wrappers).
    stats = {"new_documents": 0, "moved_claims": 0, "merged_claims": 0}
    adopted: dict[str, int] = {}

    # --- sync write tools -----------------------------------------------------

    def list_documents() -> str:
        return "\n".join(draft.list_paths()) or "(no documents yet)"

    def read_document(path: str) -> str:
        doc = draft.read(path)
        return render_document(doc.frontmatter, doc.body)

    def create_document(path: str, frontmatter: dict, body: str) -> str:
        doc = draft.create_document(path, frontmatter, body)
        stats["new_documents"] += 1
        anchors = ", ".join(extract_anchors(doc.body)) or "(none)"
        return f"created {path} (pneuma_id={doc.pneuma_id}); system-assigned anchors: {anchors}"

    def move_claim(from_path: str, anchor_id: str, to_path: str, heading: str) -> str:
        draft.move_claim(from_path, anchor_id, to_path, heading)
        stats["moved_claims"] += 1
        adopted[to_path] = adopted.get(to_path, 0) + 1
        return (
            f"moved c:{anchor_id} from {from_path} to {to_path} under '{heading}' "
            "(anchor preserved verbatim)"
        )

    def edit_claim(path: str, anchor_id: str, new_text: str) -> str:
        draft.edit_claim(path, anchor_id, new_text)
        return f"edited claim c:{anchor_id} in {path} (anchor preserved)"

    def append_block(path: str, heading: str, text: str) -> str:
        before = set(extract_anchors(draft.read(path).body))
        doc = draft.append_block(path, heading, text)
        new = [a for a in extract_anchors(doc.body) if a not in before]
        return f"appended claim to {path} under '{heading}'; assigned anchor: {new}"

    def delete_claim(path: str, anchor_id: str) -> str:
        draft.delete_claim(path, anchor_id)
        stats["merged_claims"] += 1
        return f"deleted c:{anchor_id} from {path} (合并/丢弃；锚将进入 dropped 清单)"

    def finish_evolve() -> str:
        return "evolve finished"

    # --- async read ports -----------------------------------------------------

    async def search_knowledge_tool(query: str) -> str:
        return await _search(query)

    async def fetch_source_tool(
        source_id: str, block_start: int, block_end: int
    ) -> str:
        return await _fetch(source_id, block_start, block_end)

    tools = [
        StructuredTool.from_function(list_documents, description="列出现有 canonical 文档路径。"),
        StructuredTool.from_function(read_document, description="读取一份文档完整内容（含锚）。"),
        StructuredTool.from_function(create_document, description="新建文档；系统分配 pneuma_id 与全部锚。"),
        StructuredTool.from_function(
            move_claim,
            name="move_claim",
            description="把带锚 claim 块原文照录搬到目标文档指定小节末尾，锚不变；目标须先 create_document。",
        ),
        StructuredTool.from_function(edit_claim, description="原位改写指定锚的 claim，锚自动保持。"),
        StructuredTool.from_function(append_block, description="在小节末尾新增一条 claim，锚由系统分配。"),
        StructuredTool.from_function(
            delete_claim,
            name="delete_claim",
            description="整块移除一条 claim（仅用于合并等价冗余；锚会进入 dropped 清单）。",
        ),
        StructuredTool.from_function(
            coroutine=search_knowledge_tool,
            name="search_knowledge",
            description="按 query 再检索知识库（L1/L2/L3），换角度找证据。",
        ),
        StructuredTool.from_function(
            coroutine=fetch_source_tool,
            name="fetch_source",
            description="逐字直取某来源指定 block 区间的原文，用于核对 citation。",
        ),
        StructuredTool.from_function(finish_evolve, description="无更多操作时调用，结束本次重组。"),
    ]
    by_name = {t.name: t for t in tools}
    bound = model.bind_tools(tools)

    invoke_config = {
        "callbacks": callbacks or [],
        "metadata": trace_metadata or {},
        "run_name": "evolve",
    }

    system_text = (
        render_system_contract(new_skill)
        + "\n\n# 本次任务：schema evolve\n"
        + phase2_contract()
    )
    messages: list[BaseMessage] = [
        SystemMessage(content=system_text),
        HumanMessage(content=_render_evolve_task(base_docs, proposal)),
    ]

    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    tool_calls = 0

    def accumulate(response: BaseMessage) -> None:
        meta = getattr(response, "usage_metadata", None) or {}
        for key in usage:
            usage[key] += int(meta.get(key, 0) or 0)

    async def dispatch(name: str, args: dict) -> str:
        tool = by_name.get(name)
        if tool is None:
            return f"unknown tool: {name}"
        fn = tool.coroutine or tool.func
        try:
            if inspect.iscoroutinefunction(fn):
                return await fn(**args)
            return fn(**args)
        except AnchorToolError as exc:
            return str(exc)
        except (TypeError, ValueError) as exc:
            return f"tool {name} 调用失败：{exc}"

    async def tool_loop() -> None:
        nonlocal tool_calls
        while tool_calls < MAX_TOOL_CALLS:
            response = await bound.ainvoke(messages, config=invoke_config)
            messages.append(response)
            accumulate(response)
            calls = getattr(response, "tool_calls", None) or []
            if not calls:
                return
            for call in calls:
                tool_calls += 1
                name, args, cid = call["name"], call.get("args", {}), call.get("id")
                if name == "finish_evolve":
                    messages.append(ToolMessage(content="ok", tool_call_id=cid))
                    return
                content = await dispatch(name, args)
                messages.append(ToolMessage(content=content, tool_call_id=cid))
                if tool_calls >= MAX_TOOL_CALLS:
                    return

    await tool_loop()
    violations, dropped = await run_evolve_gate(
        draft, source_bounds=source_bounds, path_templates=new_skill.path_templates
    )

    if violations and MAX_REPAIR_ROUNDS >= 1:
        messages.append(HumanMessage(content=_render_violations(violations)))
        await tool_loop()
        violations, dropped = await run_evolve_gate(
            draft, source_bounds=source_bounds, path_templates=new_skill.path_templates
        )

    summary = {
        "new_documents": stats["new_documents"],
        "moved_claims": stats["moved_claims"],
        "merged_claims": stats["merged_claims"],
        "adopted_by_document": dict(adopted),
    }
    files = draft.to_files()

    if violations:
        # Abort: the core commits nothing; the service must not land this branch.
        return EvolveResult(
            status="aborted",
            files=files,
            dropped=dropped,
            summary=summary,
            tool_calls=tool_calls,
            token_usage=usage,
        )

    status: Literal["completed", "aborted", "noop"] = (
        "completed" if draft.is_dirty() else "noop"
    )
    return EvolveResult(
        status=status,
        files=files,
        dropped=dropped,
        summary=summary,
        tool_calls=tool_calls,
        token_usage=usage,
    )
