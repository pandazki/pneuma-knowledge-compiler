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

from ..canonical_glance import render_outline
from ..domain.canonical import CanonicalDocument
from ..domain.ids import UserId, SourceId, extract_anchors
from ..recall.citation_alias import resolve_handles
from ..domain.snapshot import SnapshotRef
from ..domain.source import NormalizedSource
from ..domain.time_context import TimeContext
from ..ports.canonical_store import CanonicalStore
from ..prompts import prompt, prompt_overlay_hash
from ..skill.contract import render_system_contract
from ..skill.version import SkillVersion
from .anchor_ops import AnchorToolError
from .documents import render_document
from .gate import Violation, run_gate
from .patch import PatchDraft, history_volume_owner
from .transitions import CompileEvent, derive_events

# Injected read ports, mirroring evolve/runner.py's shape. compile was the only agentic
# stage in the system with NO retrieval at all — it could list paths and read a document by
# exact path, but never ask "what do I already know about X". That is why context had to be
# supplied by dumping the whole knowledge base. Both are optional: absent → a tool that
# says so, never a crash.
SearchKnowledge = Callable[[str], Awaitable[str]]
SearchSource = Callable[[str], Awaitable[str]]


async def _search_knowledge_unavailable(query: str) -> str:
    return prompt("compile.tool.search_knowledge_unavailable")


async def _search_source_unavailable(query: str) -> str:
    return prompt("compile.tool.search_source_unavailable")


# Centralized loop bounds.
MAX_TOOL_CALLS = 40
MAX_REPAIR_ROUNDS = 1

# Per-source treatment instruction segments (architecture.md §4, execution paths). These are
# fixed strings mechanically mapped from IntakePlan.canonical_treatment — a mechanism,
# not persuasion (§0 discipline 1). They ride the HumanMessage (task content), never
# the byte-stable SystemMessage (I5). skill instructions are unchanged.
Treatment = Literal["full", "distill", "card"]

_TREATMENT_KEYS: dict[str, str] = {
    "full": "compile.treatment.full",
    "distill": "compile.treatment.distill",
    "card": "compile.treatment.card",
}

# The closed set of treatment tiers — the thing a caller validating an intake plan needs.
TREATMENTS: frozenset[str] = frozenset(_TREATMENT_KEYS)


def _treatment_instruction(treatment: str) -> str:
    """The fixed paragraph for one treatment tier; an unknown tier degrades to `full`."""
    return prompt(_TREATMENT_KEYS.get(treatment, _TREATMENT_KEYS["full"]))


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
    sources: Sequence[NormalizedSource], time: TimeContext | None
) -> list[str]:
    """The task's time frame: when this compile runs, and what period the material covers.

    The skill requires relative time ("tomorrow", "last week") to be normalized to absolute
    dates, but
    the prompt carried no reference point to normalize AGAINST: the only dates present were
    whatever happened to appear inside the text. `RawSource.created_at` is no help either —
    it is the INGEST wall-clock, so material captured weeks ago is stamped with today.

    Every date here is a calendar day in the SUBJECT's timezone, and the anchor says which
    zone that is: the section dates were cut in that zone at ingest, so a "today" stated in
    UTC would silently disagree with them for a third of the day. `time` is passed in rather
    than read from the clock so the render stays deterministic and testable.

    A recorded timezone change is stated too. Dates compiled before the move were normalized
    under the OLD zone and are never rewritten (canonical is the non-rebuildable layer), so
    the only honest option is to tell the model which zone an older date belongs to.
    """
    lines: list[str] = []
    if time is not None:
        lines.append(
            prompt(
                "compile.task.time_now",
                date=time.today.isoformat(),
                zone=time.zone_name,
            )
        )
        for change in time.history:
            lines.append(
                prompt(
                    "compile.task.time_zone_changed",
                    at=time.local_date(change.changed_at).isoformat(),
                    from_zone=change.from_zone,
                    to_zone=change.to_zone,
                )
            )
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
        lines.append(
            prompt("compile.task.time_window", span=span_text, days=len(dates))
        )
        # A round of ONE day needs nothing more: the span above IS every source's date. A
        # round of several (a deployment batching sources into one job) must say so, because
        # the span alone cannot place a source inside it and the relative-time rule below is
        # then mechanically unexecutable. The per-source preambles carry the actual dates;
        # this line is what tells the model to go read them.
        if len(dates) > 1:
            lines.append(
                prompt(
                    "compile.task.time_multi_day",
                    sources=len(sources),
                    days=len(dates),
                )
            )
        lines.append(prompt("compile.task.time_relative_rule"))
    else:
        lines.append(prompt("compile.task.time_unknown"))
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

    The render itself now lives in `canonical_glance`, shared with the recall side's glance,
    so the compiler and the answerer derive "what a document is" from one place instead of
    two drifting copies. This function stays as the compile task's name for it; the bytes are
    unchanged.
    """
    return render_outline(base_docs)


def _render_task(
    sources: Sequence[NormalizedSource],
    base_docs: list[CanonicalDocument],
    treatments: Mapping[str, str] | None = None,
    source_guidance: Mapping[str, str] | None = None,
    source_preamble: Mapping[str, str] | None = None,
    retrieved: str | None = None,
    time: TimeContext | None = None,
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
        parts.append(prompt("compile.task.guidance_header"))
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
        parts.append(prompt("compile.task.treatment_header"))
        for t in used:
            parts.append(_treatment_instruction(t))
        parts.append("")

    parts.append(prompt("compile.task.time_header"))
    parts.extend(_render_time_anchor(sources, time))
    parts.append("")

    parts.append(prompt("compile.task.sources_header"))
    for s in sources:
        parts.append(
            prompt(
                "compile.task.source_heading",
                source_id=s.raw.source_id,
                title=s.raw.title,
            )
        )
        # Per-source provenance sentence with the OWNER as subject: whose material, when it
        # happened, what his role in it was. The transcript cannot convey any of that, and
        # authorship + time are exactly what the compiler must not guess.
        preamble = source_preamble.get(str(s.raw.source_id))
        if preamble:
            parts.append(preamble)
        treatment = treatments.get(str(s.raw.source_id), "full")
        parts.append(prompt("compile.task.treatment_tag", treatment=treatment))
        for b in s.blocks:
            parts.append(prompt("compile.task.block_line", index=b.index, text=b.text))
        parts.append("")
    parts.append(prompt("compile.task.outline_header"))
    parts.append(prompt("compile.task.outline_note"))
    parts.append("")
    parts.extend(_render_outline(base_docs))

    if retrieved:
        parts.append(prompt("compile.task.retrieved_header"))
        parts.append(prompt("compile.task.retrieved_note"))
        parts.append("")
        parts.append(retrieved.rstrip())
    return "\n".join(parts)


def _with_skill_trailer(message: str, skill: SkillVersion) -> str:
    """Append a git trailer block recording which skill version compiled this snapshot.

    A free git audit trace (architecture.md §9 M5): a blank line then `Key: value`
    trailers. `git log --format=%(trailers:key=Skill-Version,valueonly)` reads it back.
    Forward-only — old commits keep whatever version compiled them; this never rewrites
    history."""
    trailers = [
        f"Skill-Version: {skill.version}",
        f"Skill-Id: {skill.skill_id}",
        f"Skill-Content-Hash: {skill.content_hash}",
    ]
    # Second identity axis: WHICH prose the model saw. The skill hash pins the skill body;
    # the overlay hash pins every prompt surface a deployment rewrote. Absent when nothing is
    # overridden, so a stock deployment's trailer is byte-for-byte what it always was.
    overlay = prompt_overlay_hash()
    if overlay is not None:
        trailers.append(f"Prompt-Overlay-Hash: {overlay}")
    return f"{message}\n\n" + "\n".join(trailers)


#: Public spelling for the other canonical write channels (rollover/groom): every commit that
#: touches canonical should be attributable to the same two identity axes, and a second copy
#: of the trailer format would be a second thing to keep in step.
with_skill_trailer = _with_skill_trailer


def _render_violations(violations: Sequence[Violation]) -> str:
    lines = [prompt("gate.feedback_header")]
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
        return "\n".join(draft.list_paths()) or prompt("compile.tool.list_documents_empty")

    def read_document(path: str) -> str:
        doc = draft.read(path)
        rendered = render_document(doc.frontmatter, doc.body)
        # A frozen rollover volume stays fully READABLE (deep reads of history are the
        # point of keeping it), but the read result itself must say the content is not a
        # write target — otherwise the one surface that shows the model a volume's claims
        # presents them exactly like editable ones.
        owner = history_volume_owner(path, draft.path_templates)
        if owner is not None:
            notice = prompt("compile.tool.read_document_frozen_notice", owner=owner)
            return f"{notice}\n{rendered}"
        return rendered

    def create_document(path: str, frontmatter: dict, body: str) -> str:
        doc = draft.create_document(path, frontmatter, body)
        anchors = ", ".join(extract_anchors(doc.body)) or prompt("compile.anchor.none")
        return prompt(
            "compile.tool.create_document_result",
            path=path,
            doc_id=doc.doc_id,
            anchors=anchors,
        )

    def edit_claim(path: str, anchor_id: str, new_text: str) -> str:
        draft.edit_claim(path, anchor_id, new_text)
        return prompt("compile.tool.edit_claim_result", anchor_id=anchor_id, path=path)

    def append_block(path: str, heading: str, text: str) -> str:
        before = set(extract_anchors(draft.read(path).body))
        doc = draft.append_block(path, heading, text)
        new = [a for a in extract_anchors(doc.body) if a not in before]
        return prompt(
            "compile.tool.append_block_result", path=path, heading=heading, anchors=new
        )

    def finish_compile() -> str:
        return prompt("compile.tool.finish_compile_result")

    _search_knowledge = search_knowledge or _search_knowledge_unavailable
    _search_source = search_source or _search_source_unavailable

    async def search_knowledge_tool(query: str) -> str:
        return await _search_knowledge(query)

    async def search_source_tool(query: str) -> str:
        return await _search_source(query)

    return [
        StructuredTool.from_function(
            list_documents, description=prompt("compile.tool.list_documents")
        ),
        StructuredTool.from_function(
            read_document, description=prompt("compile.tool.read_document")
        ),
        StructuredTool.from_function(
            create_document, description=prompt("compile.tool.create_document")
        ),
        StructuredTool.from_function(
            edit_claim, description=prompt("compile.tool.edit_claim")
        ),
        StructuredTool.from_function(
            append_block, description=prompt("compile.tool.append_block")
        ),
        StructuredTool.from_function(
            finish_compile, description=prompt("compile.tool.finish_compile")
        ),
        StructuredTool.from_function(
            coroutine=search_knowledge_tool,
            name="search_knowledge",
            description=prompt("compile.tool.search_knowledge"),
        ),
        StructuredTool.from_function(
            coroutine=search_source_tool,
            name="search_source",
            description=prompt("compile.tool.search_source"),
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
    # The subject's clock for this job (domain/time_context.py): the instant the compile
    # runs PLUS the timezone its calendar days are counted in. Timezone is a compile input,
    # not a rendering option — the ingest side already cut sections in this zone, and the
    # time frame has to agree with them. Absent → no time frame is rendered at all.
    time: TimeContext | None = None,
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
        # `time` reaches the system side too, but only for its zone and that zone's
        # provenance (the subject-environment declaration in §2) — never its instant, so the
        # SystemMessage stays byte-stable per (skill, owner, zone, overlay).
        SystemMessage(content=render_system_contract(skill, owner=owner, time=time)),
        HumanMessage(
            content=_render_task(
                a_sources,
                base_docs,
                treatments,
                source_guidance,
                source_preamble,
                retrieved,
                time,
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
                    content = prompt("compile.tool.unknown_tool", name=name)
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
                        content = prompt(
                            "compile.tool.call_failed", name=name, error=exc
                        )
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
