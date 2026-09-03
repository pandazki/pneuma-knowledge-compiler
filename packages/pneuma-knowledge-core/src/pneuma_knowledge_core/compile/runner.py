"""Compile main loop (pure core; middleware injected via ports).

Assembles a byte-stable SystemMessage (render_system_contract) + a HumanMessage carrying
this compile's supplied sources and the existing canonical documents, then drives a
langchain tool loop over the claim-level write tools. When the model finishes (or the
round's tool-call budget is spent) the mechanical gate runs; on violations one repair round
feeds the violation text back and re-runs the loop. Still-failing → abort with the
canonical layer untouched (no commit). Passing + dirty → commit_patch + derive_events.

Each round is bounded by its OWN tool-call budget, never a counter shared with the round
before it (see the budget block below): the first round's scales with the supplied material
unless the deployment states an absolute `max_tool_calls`, and the repair round is given a
fresh allowance sized by the violations it was handed. Inside a round the budget is made
visible rather than merely enforced — a notice at the low-water mark names the calls left
and what the gate's own predicates already find owed, and a round that ran out says so at
the top of the feedback the next round reads.

Nothing here persuades the model; the anchor/citation/path mechanisms are enforced by
the tools and the gate (architecture.md §0 discipline 1).
"""

from __future__ import annotations

import asyncio
import base64
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.content import create_image_block
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..canonical_glance import render_outline
from ..domain.archive import ARCHIVE_OF_KEY, archived_path, is_archive_record, is_archived_path
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
from .documents import Connection, Overview, render_document
from .overview import OVERVIEW_BUDGET_CHARS, OVERVIEW_REQUIRED_AFTER_CLAIMS
from .gate import (
    Violation,
    archive_refusals,
    overview_required_violations,
    run_gate,
)
from ..components import component_job, registered_components
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


class _ConnectionArg(BaseModel):
    """One overview connection as the model supplies it: a repo-relative document path plus
    the relation in one line. Declared rather than inferred, so the tool schema names the two
    fields instead of asking for "an object"."""

    path: str = ""
    relation: str = ""


class _RewriteOverviewArgs(BaseModel):
    """The `rewrite_overview` payload: the whole picture, every call — the four prose slots
    and the structured fields beside them."""

    path: str
    definition: str = ""
    summary: str = ""
    introduction: str = ""
    connections: list[_ConnectionArg] = Field(default_factory=list)
    fields: dict = Field(default_factory=dict)


# ─────────────────────────────────────────────────────── the round's tool-call budget
#
# A compile is bounded by a count of tool calls, and for a long time that count was one
# constant shared by BOTH rounds. Two mechanical failures came out of that shape on a real
# 88-day rebuild:
#
# 1. A fixed 40 does not describe a day group of 36 sources. Reading each source once and
#    writing twice is 108 calls of ordinary, correct work — the first round was cut at 40
#    mid-append, every time. So the default now SCALES with the material: a floor of
#    `MIN_TOOL_CALLS`, or `TOOL_CALLS_PER_SOURCE` per supplied source, whichever is larger.
#    A deployment that states `max_tool_calls` states the absolute number instead; the
#    scaling rule is the default, not a minimum applied over the knob.
# 2. One counter across both rounds means a first round that spends everything leaves the
#    repair round with `spent < budget` already false — its `tool_loop` never entered its
#    loop at all, so the gate's feedback was written to a model that was never asked again
#    and every such compile aborted. The repair round therefore gets its OWN allowance,
#    sized by the work it was actually given (`REPAIR_TOOL_CALLS_PER_VIOLATION` per
#    violation, floor `MIN_REPAIR_TOOL_CALLS`) and bounded by the round budget above — one
#    knob governs the ceiling of both rounds, so a deployment tuning cost has one number to
#    turn, not two that can disagree.
MIN_TOOL_CALLS = 40
TOOL_CALLS_PER_SOURCE = 3
MIN_REPAIR_TOOL_CALLS = 12
REPAIR_TOOL_CALLS_PER_VIOLATION = 3
# How much budget must be LEFT for the low-water notice to still be worth sending. Below a
# handful of calls the notice would name work the model can no longer do; above it the
# notice is noise in the middle of a round that has room. Rendered once per round.
BUDGET_NOTICE_REMAINING = 6
MAX_REPAIR_ROUNDS = 1


def first_round_budget(source_count: int, max_tool_calls: int = 0) -> int:
    """How many tool calls this compile's first round may spend.

    `max_tool_calls` > 0 is the deployment's absolute answer. Otherwise the number is
    derived from the material: a first round must be able to read every supplied source and
    append at least twice per source, and no round is smaller than the historical floor.
    """
    if max_tool_calls > 0:
        return max_tool_calls
    return max(MIN_TOOL_CALLS, TOOL_CALLS_PER_SOURCE * max(source_count, 0))


def repair_round_budget(violation_count: int, round_budget: int) -> int:
    """The repair round's own fresh allowance — never borrowed from what round one spent."""
    sized = max(MIN_REPAIR_TOOL_CALLS, REPAIR_TOOL_CALLS_PER_VIOLATION * violation_count)
    return min(round_budget, sized)


class CompileCallTimeout(TimeoutError):
    """A single model call in the compile loop exceeded its wall-clock budget.

    A provider connection that hangs is invisible to every other guardrail: the request is
    open, no error arrives, and the job stays `claimed` — one hung call held a worker for
    23 minutes, and orphan reclaim only runs on worker restart. The bound is per CALL, not
    per compile: a slow-but-alive model must not be killed, so the budget is generous and
    the guard is against hangs. Raising propagates out of `run_compile` before any commit,
    so the worker's "any exception completes the job as failed" path records the reason and
    the canonical layer is untouched."""


async def _call_model(coro, timeout: float | None):
    """Await one model call under `timeout` seconds; `None` / `0` = no bound."""
    if not timeout:
        return await coro
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError as exc:
        raise CompileCallTimeout(
            f"compile model call timed out after {timeout:g}s"
        ) from exc


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
    #: Every archive refusal this compile hit — a write aimed under `archive/`, a create on a
    #: path an archived document shadows, a create under an archived document's title — from
    #: the tool face and the gate alike (`gate.archive_refusals`). Empty for every compile in
    #: a library with no archive, which is every compile until the owner makes one.
    #:
    #: NOT a compile event: events are derived from the file diff and a refusal wrote no
    #: file. It rides the result so the worker can put it in the job's completion detail,
    #: where the owner sees that new material came in about a subject they retired
    #: (docs/design/archive.md §2.1).
    archive_refusals: list[dict] = field(default_factory=list)


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
        # What the source boundary knows and the transcript cannot show — an enabled
        # component states it here (e.g. the identities present in this source), so the
        # compiler binds a source identity as a fact it was given, never as a guess.
        for component in registered_components():
            extra = getattr(component, "source_preamble", None)
            line = extra(s) if extra is not None else None
            if line:
                parts.append(line)
        treatment = treatments.get(str(s.raw.source_id), "full")
        parts.append(prompt("compile.task.treatment_tag", treatment=treatment))
        for b in s.blocks:
            parts.append(prompt("compile.task.block_line", index=b.index, text=b.text))
            for image in b.images:
                if image.derived:
                    for derived in image.derived:
                        parts.append(
                            prompt(
                                "compile.task.image_derived",
                                image_id=image.image_id,
                                kind=derived.kind,
                                producer=derived.producer,
                                text=derived.text,
                            )
                        )
                else:
                    parts.append(
                        prompt(
                            "compile.task.image_without_derived",
                            image_id=image.image_id,
                        )
                    )
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


def _render_task_content(
    sources: Sequence[NormalizedSource],
    base_docs: list[CanonicalDocument],
    treatments: Mapping[str, str] | None = None,
    source_guidance: Mapping[str, str] | None = None,
    source_preamble: Mapping[str, str] | None = None,
    retrieved: str | None = None,
    time: TimeContext | None = None,
    *,
    image_mode: Literal["caption", "native"] = "caption",
    image_payloads: Mapping[str, bytes] | None = None,
) -> str | list[dict]:
    """Render caption-only text or standard LangChain native image content blocks."""

    task = _render_task(
        sources,
        base_docs,
        treatments,
        source_guidance,
        source_preamble,
        retrieved,
        time,
    )
    images = [
        (source, block, image)
        for source in sources
        for block in source.blocks
        for image in block.images
    ]
    if image_mode == "caption":
        missing = [image.image_id for _, _, image in images if not image.derived]
        if missing:
            raise ValueError(
                "caption mode requires a labelled caption or OCR representation for "
                f"every image; missing: {', '.join(missing)}"
            )
        return task
    payloads = image_payloads or {}
    if not images:
        return task
    content: list[dict] = [{"type": "text", "text": task}]
    content.append({"type": "text", "text": prompt("compile.task.native_images_header")})
    for source, block, image in images:
        if image.storage_key not in payloads:
            raise ValueError(
                f"native image payload is missing for {image.image_id!r}"
            )
        content.append(
            {
                "type": "text",
                "text": prompt(
                    "compile.task.native_image_locator",
                    image_id=image.image_id,
                    source_id=source.raw.source_id,
                    index=block.index,
                    text=block.text,
                ),
            }
        )
        content.append(
            create_image_block(
                base64=base64.b64encode(payloads[image.storage_key]).decode("ascii"),
                mime_type=image.mime_type,
                id=image.image_id,
            )
        )
    return content


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
    # Third axis: WHICH components were in the room — their gate checks, outline lines and
    # tools shaped this compile. Absent when none is enabled, so a stock trailer is unchanged.
    names = [c.name for c in registered_components()]
    if names:
        trailers.append(f"Components: {','.join(names)}")
    return f"{message}\n\n" + "\n".join(trailers)


#: Public spelling for the other canonical write channels (rollover/groom): every commit that
#: touches canonical should be attributable to the same two identity axes, and a second copy
#: of the trailer format would be a second thing to keep in step.
with_skill_trailer = _with_skill_trailer


def _render_violations(
    violations: Sequence[Violation],
    *,
    cut_off_at: int | None = None,
    next_budget: int = 0,
) -> str:
    """The gate's feedback for the repair round.

    `cut_off_at` is set when the previous round did not end on its own but ran out of tool
    calls. Saying so is mechanism, not comfort: a round that was cut mid-exploration and is
    handed only a list of violations has no way to tell that its reading was interrupted,
    and the observed behaviour is that it starts the exploration over and spends the repair
    round on it. One line stating the cut and the fresh budget removes that ambiguity.
    """
    lines: list[str] = []
    if cut_off_at is not None:
        lines.append(
            prompt("gate.previous_round_cut_off", spent=cut_off_at, budget=next_budget)
        )
    lines.append(prompt("gate.feedback_header"))
    lines.extend(v.render() for v in violations)
    return "\n".join(lines)


def _build_tools(
    draft: PatchDraft,
    search_knowledge: SearchKnowledge | None = None,
    search_source: SearchSource | None = None,
    extra_tools: Sequence[StructuredTool] = (),
) -> list[StructuredTool]:
    """The claim-level write tools. Deliberately SYNC: every one of them mutates only the
    in-memory PatchDraft (no port, no network), and the runner's hand-rolled loop calls
    `tool.func(**args)` directly rather than handing the tools to an agent — so there is
    nothing to await and async would only color the loop for free."""

    def list_documents() -> str:
        # LIVE documents only. The archive (`archive/`) is not part of a compile's working
        # set — nothing there may be written and nothing there is offered as a place to
        # write — so listing it would spend the model's attention on pages it cannot use
        # and invite it to re-open a subject the owner retired.
        paths = [p for p in draft.list_paths() if not is_archived_path(p)]
        return "\n".join(paths) or prompt("compile.tool.list_documents_empty")

    def read_document(path: str) -> str:
        # An archived path answers with the fact and nothing else — and is NOT marked read,
        # so the whole-region writes still refuse it for the same reason they refuse an
        # unread page. Unlike a frozen rollover volume (readable, quotable, just not
        # writable), an archived document is outside this compile's working set entirely.
        if is_archived_path(path):
            return prompt("compile.tool.read_document_archived", path=path)
        doc = draft.read(path)
        # The one place a path becomes "seen this round": the whole-region writes below
        # refuse a document this compile has not looked at.
        draft.mark_read(path)
        rendered = render_document(doc.frontmatter, doc.body)
        # A frozen rollover volume stays fully READABLE (deep reads of history are the
        # point of keeping it), but the read result itself must say the content is not a
        # write target — otherwise the one surface that shows the model a volume's claims
        # presents them exactly like editable ones.
        owner = history_volume_owner(path, draft.path_templates)
        if owner is not None:
            notice = prompt("compile.tool.read_document_closed_notice", owner=owner)
            return f"{notice}\n{rendered}"
        # An ARCHIVE RECORD reads in full — that is how the round learns the subject is
        # RETIRED rather than absent, which is the whole reason the record exists — with the
        # same kind of notice a closed volume gets: readable, citable, never a write target.
        if is_archive_record(doc):
            notice = prompt(
                "compile.tool.read_document_record_notice",
                archived=str(
                    (doc.frontmatter or {}).get(ARCHIVE_OF_KEY) or archived_path(path)
                ),
            )
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

    def supersede_claim(path: str, anchor_id: str, new_text: str) -> str:
        _, new_anchor = draft.supersede_claim(path, anchor_id, new_text)
        return prompt(
            "compile.tool.supersede_claim_result",
            anchor_id=anchor_id.removeprefix("c:"),
            new_anchor=new_anchor,
            path=path,
        )

    def rewrite_overview(
        path: str,
        definition: str = "",
        summary: str = "",
        introduction: str = "",
        connections: list | None = None,
        fields: dict | None = None,
    ) -> str:
        before = set(extract_anchors(draft.read(path).body))
        overview = Overview(
            definition=definition or "",
            summary=summary or "",
            introduction=introduction or "",
            connections=tuple(
                Connection(
                    path=str((c or {}).get("path", "") if isinstance(c, dict) else c.path),
                    relation=str(
                        (c or {}).get("relation", "") if isinstance(c, dict) else c.relation
                    ),
                )
                for c in (connections or [])
            ),
        )
        doc = draft.rewrite_overview(path, overview, fields)
        new = [a for a in extract_anchors(doc.body) if a not in before]
        slots = [
            name
            for name, filled in (
                ("definition", overview.definition.strip()),
                ("summary", overview.summary.strip()),
                ("introduction", overview.introduction.strip()),
                ("connections", overview.connections),
            )
            if filled
        ]
        slots.extend(sorted(k for k in (fields or {}) if k in doc.frontmatter))
        return prompt(
            "compile.tool.rewrite_overview_result",
            path=path,
            slots=", ".join(slots) or prompt("compile.tool.overview_removed"),
            anchors=", ".join(new) or prompt("compile.anchor.none"),
        )

    def set_fields(path: str, fields: dict) -> str:
        doc = draft.set_fields(path, fields)
        written = ", ".join(sorted(k for k in (fields or {}) if k in doc.frontmatter))
        return prompt("compile.tool.set_fields_result", path=path, fields=written)

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
            supersede_claim, description=prompt("compile.tool.supersede_claim")
        ),
        StructuredTool.from_function(
            rewrite_overview,
            args_schema=_RewriteOverviewArgs,
            description=prompt("compile.tool.rewrite_overview"),
        ),
        StructuredTool.from_function(
            set_fields, description=prompt("compile.tool.set_fields")
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
        # Read tools contributed by enabled index components (components/__init__.py):
        # appended after the framework's own, in registration order, so the tool list —
        # part of the byte-stable system side — is deterministic per enabled set.
        *extra_tools,
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
    image_mode: Literal["caption", "native"] = "caption",
    image_payloads: Mapping[str, bytes] | None = None,
    # Wall-clock budget for ONE model call in the tool loop (the first round and the repair
    # round share it). None / 0 = unbounded, the pre-guardrail behaviour.
    call_timeout: float | None = None,
    # This deployment's absolute ceiling on the tool calls ONE round of this compile may
    # spend (first round and repair round alike). 0 / unset = derive it from the material —
    # see `first_round_budget`.
    max_tool_calls: int = 0,
    # The overview region's character ceiling for this deployment (compile/overview.py).
    overview_budget_chars: int = OVERVIEW_BUDGET_CHARS,
    # … and its floor: how many ledger claims a document may hold before it must have an
    # overview at all. 0 disables the rule.
    overview_required_after_claims: int = OVERVIEW_REQUIRED_AFTER_CLAIMS,
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
    # The components' one async breath before the sync seams run, and the window that keeps
    # it meaningful. Every face a component contributes to a compile — its tools, its outline
    # tails, its source preambles — is sync, and a compile process is a FRESH process that has
    # indexed nothing: whatever a component keeps in memory about this user is cold until it is
    # told the user. `prepare` is fail-soft per component (it logs); the WINDOW is not an
    # optimisation either — while components are enabled it admits one compile per process at a
    # time, because a second `prepare` would redefine this one's user under its own gate (I1).
    async with component_job(str(user_id)):
        # The tool face refuses an overview by the SAME ceiling the gate uses below: two
        # numbers for one region would let a deployment's knob be honoured at one end only.
        draft = PatchDraft.from_canonical(
            base_docs, skill.path_templates, overview_budget_chars=overview_budget_chars
        )
        # Components see the ALIASED sources: a component tool that names a source must name it
        # by the same `sNN` handle the task text under the model's eyes uses.
        component_tools = [
            tool
            for component in registered_components()
            for tool in component.compile_tools(draft, sources=a_sources)
        ]
        tools = _build_tools(draft, search_knowledge, search_source, component_tools)
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
                content=_render_task_content(
                    a_sources,
                    base_docs,
                    treatments,
                    source_guidance,
                    source_preamble,
                    retrieved,
                    time,
                    image_mode=image_mode,
                    image_payloads=image_payloads,
                )
            ),
        ]

        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        tool_calls = 0

        def accumulate(response: BaseMessage) -> None:
            meta = getattr(response, "usage_metadata", None) or {}
            for key in usage:
                usage[key] += int(meta.get(key, 0) or 0)

        def owed_now() -> list[str]:
            """What the round already OWES, by the very predicates the gate will run.

            Two of them, and no more: the overview a touched page owes
            (`overview_required_violations` — the same call `finish_compile` makes) and every
            enabled component's `gate_checks` over the current draft. Re-deriving this from a
            second set of rules would let the notice name work the gate does not want; asking
            the whole gate would need the sources and the alias map for a message whose only
            job is to point the last few calls at what is outstanding.
            """
            owed = [
                v.render()
                for v in overview_required_violations(
                    draft, threshold=overview_required_after_claims
                )
            ]
            documents, base = draft.documents(), draft.base_documents()
            for component in registered_components():
                owed.extend(v.render() for v in component.gate_checks(documents, base))
            return owed

        def answer_unreached(calls: Sequence[dict], start: int, content: str) -> None:
            """Give every call from `start` on a ToolMessage saying it was not executed.

            A batch's AIMessage declares N tool calls and a provider REQUIRES N results: a
            round that returns mid-batch leaves the transcript with tool calls nothing
            answered, and the next `ainvoke` over that history is rejected outright. Silent
            until now only because the round that returned mid-batch was the last one that
            ever ran — the repair round could not enter its loop. Now that it can, the reply
            has to exist.
            """
            for call in calls[start:]:
                messages.append(ToolMessage(content=content, tool_call_id=call.get("id")))

        async def tool_loop(budget: int) -> tuple[int, bool]:
            """Run one round under its OWN budget; return (calls spent, was it cut off).

            "Cut off" is reported, never re-derived from `spent == budget`: a round whose
            last call is `finish_compile` at exactly the budget ended on its own, and telling
            the repair round otherwise would be a false statement about what happened.
            """
            nonlocal tool_calls
            spent = 0
            noticed = False
            while spent < budget:
                response = await _call_model(
                    bound.ainvoke(messages, config=invoke_config), call_timeout
                )
                messages.append(response)
                accumulate(response)
                calls = getattr(response, "tool_calls", None) or []
                # A call whose arguments the model did not emit as valid JSON never becomes a
                # `tool_calls` entry — langchain files it under `invalid_tool_calls` — but the
                # assistant message still carries it on the wire, so the provider REQUIRES a
                # result for it exactly as for a parsed one ("No tool output found for
                # function call …" on the next invoke otherwise). It is answered here, BEFORE
                # the batch's valid calls, and charged to the round budget like a refused
                # call: an unparseable call spent a turn, and a model that keeps emitting them
                # runs out of round rather than looping forever.
                invalid = getattr(response, "invalid_tool_calls", None) or []
                if not calls and not invalid:
                    return spent, False  # model ended its turn without more tool calls
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
                    # The invalid calls alone spent the round: the rest of the batch still
                    # needs its results, or the repair round is rejected on the transcript.
                    answer_unreached(
                        calls, 0, prompt("compile.budget.call_refused", budget=budget)
                    )
                    return spent, True
                if not calls:
                    # A batch of nothing but unparseable calls is NOT the model ending its
                    # turn — it is the model failing to speak. Loop (budget permitting) so it
                    # can re-send them; the low-water notice below is skipped for this batch
                    # because no tool ran and nothing about the draft changed, and the next
                    # batch that does reach it will state the remaining budget then.
                    continue
                for index, call in enumerate(calls):
                    spent += 1
                    tool_calls += 1
                    name, args, cid = call["name"], call.get("args", {}), call.get("id")
                    if name == "finish_compile":
                        # The one rule that can only be judged at the END: an overview a
                        # document owes is owed by the round as a whole, not by any single
                        # call. Said here, the model still holds the material and one
                        # `rewrite_overview` fixes it; said at the gate, it costs the round's
                        # only repair round — the same reason every other overview rule is
                        # stated at a tool face. The gate re-states it (4d) for a draft that
                        # reaches it without finishing, and the budget bounds the retries.
                        owed = overview_required_violations(
                            draft, threshold=overview_required_after_claims
                        )
                        if owed:
                            messages.append(
                                ToolMessage(
                                    content="\n".join(v.detail for v in owed),
                                    tool_call_id=cid,
                                )
                            )
                            continue
                        messages.append(ToolMessage(content="ok", tool_call_id=cid))
                        answer_unreached(
                            calls, index + 1, prompt("compile.tool.round_ended")
                        )
                        return spent, False
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
                    if spent >= budget:
                        answer_unreached(
                            calls,
                            index + 1,
                            prompt("compile.budget.call_refused", budget=budget),
                        )
                        return spent, True
                # The low-water notice: the budget is a number the model cannot see from
                # inside the loop, and a round that does not know it is nearly over spends
                # its last calls on exploration. It rides a HumanMessage AFTER the whole
                # batch has been answered — every tool call in the batch already has its
                # ToolMessage, so the pairing the provider checks is intact — and once per
                # round, because a line repeated every turn stops being read.
                if not noticed and budget - spent <= BUDGET_NOTICE_REMAINING:
                    noticed = True
                    owed = owed_now()
                    messages.append(
                        HumanMessage(
                            content=prompt(
                                "compile.budget.notice",
                                remaining=budget - spent,
                                budget=budget,
                                owed="\n".join(owed) or prompt("compile.budget.owed_none"),
                            )
                        )
                    )
            return spent, True

        round_budget = first_round_budget(len(sources), max_tool_calls)
        spent, cut_off = await tool_loop(round_budget)
        rounds = 1
        violations = run_gate(
            draft,
            sources,
            alias_map=real_by_handle,
            known_source_bounds=known_source_bounds,
            overview_budget_chars=overview_budget_chars,
            overview_required_after_claims=overview_required_after_claims,
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
            rounds = 2
            violations = run_gate(
                draft,
                sources,
                alias_map=real_by_handle,
                known_source_bounds=known_source_bounds,
                overview_budget_chars=overview_budget_chars,
                overview_required_after_claims=overview_required_after_claims,
            )

        files = draft.to_files()
        # Read AFTER the last gate run, so a refusal the repair round earned is in it, and
        # for every outcome alike: an aborted round hit the archive as truly as a committed
        # one, and a noop is exactly the shape a round spends when the only thing it had to
        # write was refused.
        refusals = archive_refusals(violations, draft)
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
                archive_refusals=refusals,
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
                archive_refusals=refusals,
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
            archive_refusals=refusals,
        )
