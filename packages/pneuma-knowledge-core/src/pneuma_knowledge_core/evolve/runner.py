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
- **Bigger budget:** MAX_TOOL_CALLS=120 per ROUND (a whole-KB pass dwarfs one compile),
  MAX_REPAIR_ROUNDS=1 (one gate-violation feedback round) — and the repair round has its own
  fresh allowance, so a first round that spends everything is still repairable.

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
from ..components import component_job
from ..domain.canonical import CanonicalDocument
from ..domain.ids import UserId, extract_anchors
from ..prompts import prompt
from ..skill.contract import render_system_contract
from ..skill.version import SkillVersion
from .contracts import phase2_contract
from .gate import DroppedAnchor, SourceBounds, run_evolve_gate
from .propose import EvolveProposal

# A whole-KB reorganization is much larger than a single compile.
MAX_TOOL_CALLS = 120
# … and, exactly as in `compile/runner.py`, the repair round gets its OWN allowance rather
# than what the first round left behind. One counter across both rounds means a first round
# that spends its budget leaves the repair round unable to enter its loop at all: the gate's
# feedback is appended to a conversation nobody is asked to continue, and the reorganization
# aborts with the model never having read the violations. Sized by the work it was handed,
# bounded by the round budget above.
MIN_REPAIR_TOOL_CALLS = 12
REPAIR_TOOL_CALLS_PER_VIOLATION = 3
MAX_REPAIR_ROUNDS = 1


def repair_round_budget(violation_count: int, round_budget: int) -> int:
    """The repair round's fresh allowance — never borrowed from what round one spent."""
    sized = max(MIN_REPAIR_TOOL_CALLS, REPAIR_TOOL_CALLS_PER_VIOLATION * violation_count)
    return min(round_budget, sized)

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
    return prompt("evolve.tool.search_unavailable")


async def _fetch_unavailable(source_id: str, block_start: int, block_end: int) -> str:
    return prompt("evolve.tool.fetch_unavailable")


def _render_evolve_task(base_docs: list[CanonicalDocument], proposal: EvolveProposal) -> str:
    parts: list[str] = [prompt("evolve.task.docs_header")]
    if not base_docs:
        parts.append(prompt("evolve.task.docs_empty"))
    else:
        for d in base_docs:
            parts.append(f"\n## {d.path}")
            parts.append(render_document(d.frontmatter, d.body).rstrip())
    parts.append(
        "\n" + prompt("evolve.task.rationale_header") + "\n" + proposal.rationale
    )
    families: list[str] = []
    for pack in proposal.packs:
        for template in pack.extra_path_templates:
            families.append(f"- {template}")
        if pack.extra_instructions.strip():
            families.append(f"  ↳ {pack.extra_instructions.strip()}")
    parts.append(
        "\n"
        + prompt("evolve.task.families_header")
        + "\n"
        + ("\n".join(families) or prompt("evolve.task.families_empty"))
    )
    return "\n".join(parts)


def _render_violations(
    violations: list[Violation],
    *,
    cut_off_at: int | None = None,
    next_budget: int = 0,
) -> str:
    """The evolve gate's feedback. `cut_off_at` is set when the previous round did not end
    on its own but ran out of tool calls — the same statement `compile/runner.py` makes, and
    for the same reason: a round handed only violations cannot tell that its reading was
    interrupted, and starts the exploration over."""
    lines: list[str] = []
    if cut_off_at is not None:
        lines.append(
            prompt("gate.previous_round_cut_off", spent=cut_off_at, budget=next_budget)
        )
    lines.append(prompt("gate.evolve.feedback_header"))
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
    # An absolute ceiling on the tool calls ONE round may spend. 0 = MAX_TOOL_CALLS. Evolve
    # has no per-source scaling to do (its material is the whole library, not a job's
    # sources), so this is a plain override and not a deployment knob of its own.
    max_tool_calls: int = 0,
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
        return "\n".join(draft.list_paths()) or prompt("evolve.tool.list_documents_empty")

    def read_document(path: str) -> str:
        doc = draft.read(path)
        return render_document(doc.frontmatter, doc.body)

    def create_document(path: str, frontmatter: dict, body: str) -> str:
        doc = draft.create_document(path, frontmatter, body)
        stats["new_documents"] += 1
        anchors = ", ".join(extract_anchors(doc.body)) or prompt("evolve.tool.anchors_none")
        return prompt(
            "evolve.tool.create_document_result",
            path=path,
            doc_id=doc.doc_id,
            anchors=anchors,
        )

    def move_claim(from_path: str, anchor_id: str, to_path: str, heading: str) -> str:
        draft.move_claim(from_path, anchor_id, to_path, heading)
        stats["moved_claims"] += 1
        adopted[to_path] = adopted.get(to_path, 0) + 1
        return prompt(
            "evolve.tool.move_claim_result",
            anchor_id=anchor_id,
            from_path=from_path,
            to_path=to_path,
            heading=heading,
        )

    def edit_claim(path: str, anchor_id: str, new_text: str) -> str:
        draft.edit_claim(path, anchor_id, new_text)
        return prompt("evolve.tool.edit_claim_result", anchor_id=anchor_id, path=path)

    def append_block(path: str, heading: str, text: str) -> str:
        before = set(extract_anchors(draft.read(path).body))
        doc = draft.append_block(path, heading, text)
        new = [a for a in extract_anchors(doc.body) if a not in before]
        return prompt(
            "evolve.tool.append_block_result", path=path, heading=heading, anchors=new
        )

    def delete_claim(path: str, anchor_id: str) -> str:
        draft.delete_claim(path, anchor_id)
        stats["merged_claims"] += 1
        return prompt(
            "evolve.tool.delete_claim_result", anchor_id=anchor_id, path=path
        )

    def finish_evolve() -> str:
        return prompt("evolve.tool.finish_evolve_result")

    # --- async read ports -----------------------------------------------------

    async def search_knowledge_tool(query: str) -> str:
        return await _search(query)

    async def fetch_source_tool(
        source_id: str, block_start: int, block_end: int
    ) -> str:
        return await _fetch(source_id, block_start, block_end)

    tools = [
        StructuredTool.from_function(
            list_documents, description=prompt("evolve.tool.list_documents")
        ),
        StructuredTool.from_function(
            read_document, description=prompt("evolve.tool.read_document")
        ),
        StructuredTool.from_function(
            create_document, description=prompt("evolve.tool.create_document")
        ),
        StructuredTool.from_function(
            move_claim,
            name="move_claim",
            description=prompt("evolve.tool.move_claim"),
        ),
        StructuredTool.from_function(
            edit_claim, description=prompt("evolve.tool.edit_claim")
        ),
        StructuredTool.from_function(
            append_block, description=prompt("evolve.tool.append_block")
        ),
        StructuredTool.from_function(
            delete_claim,
            name="delete_claim",
            description=prompt("evolve.tool.delete_claim"),
        ),
        StructuredTool.from_function(
            coroutine=search_knowledge_tool,
            name="search_knowledge",
            description=prompt("evolve.tool.search_knowledge"),
        ),
        StructuredTool.from_function(
            coroutine=fetch_source_tool,
            name="fetch_source",
            description=prompt("evolve.tool.fetch_source"),
        ),
        StructuredTool.from_function(
            finish_evolve, description=prompt("evolve.tool.finish_evolve")
        ),
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
        + "\n\n"
        + prompt("evolve.task_header")
        + "\n"
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
            return prompt("evolve.tool.unknown_tool", name=name)
        fn = tool.coroutine or tool.func
        try:
            if inspect.iscoroutinefunction(fn):
                return await fn(**args)
            return fn(**args)
        except AnchorToolError as exc:
            return str(exc)
        except (TypeError, ValueError) as exc:
            return prompt("evolve.tool.call_failed", name=name, error=exc)

    def answer_unreached(calls: list, start: int, content: str) -> None:
        """Every declared tool call gets a result, including the ones a mid-batch return
        never reached: a provider rejects a history whose AIMessage declares N tool calls
        and carries fewer than N ToolMessages, so an unanswered call would make the NEXT
        round fail on the transcript rather than on the work."""
        for call in calls[start:]:
            messages.append(ToolMessage(content=content, tool_call_id=call.get("id")))

    async def tool_loop(budget: int) -> tuple[int, bool]:
        """One round under its OWN budget; returns (calls spent, was it cut off)."""
        nonlocal tool_calls
        spent = 0
        while spent < budget:
            response = await bound.ainvoke(messages, config=invoke_config)
            messages.append(response)
            accumulate(response)
            calls = getattr(response, "tool_calls", None) or []
            # Same shape as compile's loop, for the same mechanical reason: a call whose
            # arguments were not valid JSON lands in `invalid_tool_calls` rather than
            # `tool_calls`, yet the assistant message still declares it on the wire and the
            # provider requires a result. Answer those first, charge each to the budget like
            # a refused call, and treat a batch of nothing but invalid calls as a turn the
            # model still owes — not as the model ending it.
            invalid = getattr(response, "invalid_tool_calls", None) or []
            if not calls and not invalid:
                return spent, False
            for call in invalid:
                spent += 1
                tool_calls += 1
                messages.append(
                    ToolMessage(
                        content=prompt(
                            "compile.tool.invalid_call",
                            name=call.get("name") or "?",
                            error=call.get("error") or "?",
                        ),
                        tool_call_id=call.get("id"),
                    )
                )
            if invalid and spent >= budget:
                answer_unreached(
                    calls, 0, prompt("compile.budget.call_refused", budget=budget)
                )
                return spent, True
            if not calls:
                continue
            for index, call in enumerate(calls):
                spent += 1
                tool_calls += 1
                name, args, cid = call["name"], call.get("args", {}), call.get("id")
                if name == "finish_evolve":
                    messages.append(ToolMessage(content="ok", tool_call_id=cid))
                    answer_unreached(calls, index + 1, prompt("compile.tool.round_ended"))
                    return spent, False
                content = await dispatch(name, args)
                messages.append(ToolMessage(content=content, tool_call_id=cid))
                if spent >= budget:
                    answer_unreached(
                        calls,
                        index + 1,
                        prompt("compile.budget.call_refused", budget=budget),
                    )
                    return spent, True
        return spent, True

    # The components' window, exactly as a daily compile opens one (`compile/runner.py`):
    # `prepare` at the top so a component whose gate check reads a per-process mirror of its
    # own projection has one at all, and — while any component is registered — one such
    # window per process at a time. Evolve authors canonical, so the mirror being cold here
    # is the same fail-open a compile refuses to accept: a component that could not load
    # what it judges by says `not_ready` and the reorganization aborts rather than landing a
    # page nothing checked. With no component registered nothing is prepared and nothing is
    # locked, and this whole block runs as it did before the concept existed.
    async with component_job(str(user_id)):
        round_budget = max_tool_calls if max_tool_calls > 0 else MAX_TOOL_CALLS
        spent, cut_off = await tool_loop(round_budget)
        violations, dropped = await run_evolve_gate(
            draft, source_bounds=source_bounds, path_templates=new_skill.path_templates
        )

        if violations and MAX_REPAIR_ROUNDS >= 1:
            repair_budget = repair_round_budget(len(violations), round_budget)
            messages.append(
                HumanMessage(
                    content=_render_violations(
                        violations,
                        cut_off_at=spent if cut_off else None,
                        next_budget=repair_budget,
                    )
                )
            )
            await tool_loop(repair_budget)
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
