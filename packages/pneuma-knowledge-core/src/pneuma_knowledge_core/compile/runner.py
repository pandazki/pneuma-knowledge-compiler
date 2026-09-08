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

The loop itself lives in `compile/round.py` behind a one-method protocol, because it is the
only part of a compile that changes when a different body drives the round — a coding agent
under the Owner's subscription rather than a provider model (docs/design/coding-agent-mode.md
ruling 2). Everything this module does around it is the same either way.

Nothing here persuades the model; the anchor/citation/path mechanisms are enforced by
the tools and the gate (architecture.md §0 discipline 1).
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
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
from ..ingest.evidence_context import block_evidence_context
from ..ports.canonical_store import CanonicalStore
from ..prompts import prompt, prompt_overlay_hash
from ..skill.contract import render_system_contract
from ..skill.version import SkillVersion
from .documents import Connection, Overview, render_document
from .overview import OVERVIEW_BUDGET_CHARS, OVERVIEW_REQUIRED_AFTER_CLAIMS
from .gate import (
    Violation,
    archive_refusals,
    overview_required_violations,
    owed_now_lines,
    run_gate,
)
from ..components import component_job, registered_components
from .patch import PatchDraft, history_volume_owner
# The round itself — the ONE part of a compile that changes with the executor, and therefore
# the one part behind a protocol (compile/round.py). Three of these names were defined here
# before the seam existed and are re-exported so their import sites keep working (notably
# `compile/brief.py`'s `_call_model` and the tests' `CompileCallTimeout`).
from .round import (  # noqa: F401 — re-exported: see above
    BUDGET_NOTICE_REMAINING,
    CompileCallTimeout,
    LangchainRoundRunner,
    RoundOutcome,
    RoundRunner,
    RoundToolFace,
    _call_model,
)
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
# `BUDGET_NOTICE_REMAINING` — how much budget must be LEFT for the low-water notice to still
# be worth sending — now lives with the loop that sends it (compile/round.py), and is
# re-exported above.
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

    Source occurrence days and normalized section dates describe the material's coverage;
    the earliest day alone cannot anchor every statement in a multi-day source. Individual
    sections and message envelopes remain beside their blocks below. created_at is an
    ingestion clock and is never used as evidence of when a statement occurred.

    The current clock and timezone history are supplied, not read here. Previously compiled
    dates are not rewritten when that timezone changes.
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
        # Coverage is not a per-statement timestamp, even when one source supplies it all.
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
        context = block_evidence_context(s)
        if context.misaligned:
            parts.append(prompt("compile.task.context_unavailable"))
        previous_section: list[str] = []
        for b in s.blocks:
            if b.section_path != previous_section:
                parts.append(prompt(
                    "compile.task.section_context",
                    path=json.dumps(b.section_path, ensure_ascii=False),
                ))
                previous_section = b.section_path
            if context.blocks.get(b.index):
                parts.append(prompt(
                    "compile.task.block_context", index=b.index,
                    context=json.dumps(context.blocks[b.index], ensure_ascii=False),
                ))
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


#: The environment variable a coding-agent Steward's session carries: the sha256 of the skill
#: package it was installed with. Set by the generated shim, read here and nowhere else.
STEWARD_SKILL_HASH_ENV = "PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH"


def executor_skill_hash() -> str:
    """The executor's own skill hash for this process, or "" when there is none.

    Process state, exactly like `prompt_overlay_hash()`: an executor is a property of the
    running body, not an argument every call site would have to thread. Reading it here keeps
    the two executors on ONE trailer format — the CLI's `finish` and the langchain loop call
    the same function, and what differs between them is only whether the variable is set.
    """
    return os.environ.get(STEWARD_SKILL_HASH_ENV, "").strip()


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
    # Fourth axis, and only when a coding agent is the body: WHICH WORDS the executor itself
    # was taught. The skill package a `pkc` Steward reads is generated from this same catalog
    # and this same contract, and its sha256 is exported by the shim that starts the session
    # (docs/design/coding-agent-mode.md §7). Absent for the langchain executor, whose process
    # nothing exports it into — so a model-compiled commit's trailer is byte-for-byte what it
    # has always been.
    executor_skill = executor_skill_hash()
    if executor_skill:
        trailers.append(f"Executor-Skill: {executor_skill}")
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


#: Public spelling of the gate's own feedback rendering. Both executors show the same text:
#: the langchain loop puts it in the repair round's HumanMessage, `pkc draft finish` prints it
#: on stderr. A second rendering would be a second thing the two could disagree about.
render_violations = _render_violations


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


# ─────────────────────────────────────── the round's pieces, reusable by either executor
#
# Everything below is called by `run_compile` and by the `pkc draft` commands, and that is
# the point: the claim-level draft with its tool face and its gate is ONE door, and the
# langchain loop and the CLI are two clients of it (ruling 2 of
# docs/design/coding-agent-mode.md). A second rendering of the task, a second tool face or a
# second commit tail would be a second door, and "whatever one refuses the other refuses with
# the same text" would then be an aspiration rather than a fact about the code.


@dataclass(frozen=True)
class AliasedSources:
    """This compile's sources under their per-job `sNN` handles, plus the two maps.

    Compile-boundary citation aliasing (see `run_compile`): the model mis-copies 32-char UUID
    source ids into `[cite:]` markers, so it is shown short per-job handles instead, the gate
    validates handles, and the commit resolves them back to real ids. Minted here rather than
    inline so both executors alias one way.
    """

    sources: list[NormalizedSource]
    handle_by_real: dict[str, str]
    real_by_handle: dict[str, str]
    treatments: dict[str, str]
    source_guidance: dict[str, str]
    source_preamble: dict[str, str]


def alias_sources(
    sources: Sequence[NormalizedSource],
    *,
    treatments: Mapping[str, str] | None = None,
    source_guidance: Mapping[str, str] | None = None,
    source_preamble: Mapping[str, str] | None = None,
) -> AliasedSources:
    """The supplied sources re-keyed onto `sNN` handles, with the per-source maps re-keyed too."""
    handle_by_real = {str(s.raw.source_id): f"s{i + 1:02d}" for i, s in enumerate(sources)}
    real_by_handle = {h: r for r, h in handle_by_real.items()}
    aliased = [
        s.model_copy(
            update={
                "raw": s.raw.model_copy(
                    update={"source_id": SourceId(handle_by_real[str(s.raw.source_id)])}
                )
            }
        )
        for s in sources
    ]
    return AliasedSources(
        sources=aliased,
        handle_by_real=handle_by_real,
        real_by_handle=real_by_handle,
        treatments={
            handle_by_real[k]: v
            for k, v in (treatments or {}).items()
            if k in handle_by_real
        },
        source_guidance={
            handle_by_real[k]: v
            for k, v in (source_guidance or {}).items()
            if k in handle_by_real
        },
        source_preamble={
            handle_by_real[k]: v
            for k, v in (source_preamble or {}).items()
            if k in handle_by_real
        },
    )


def render_compile_messages(
    *,
    sources: Sequence[NormalizedSource],
    base_docs: list[CanonicalDocument],
    skill: SkillVersion,
    treatments: Mapping[str, str] | None = None,
    source_guidance: Mapping[str, str] | None = None,
    source_preamble: Mapping[str, str] | None = None,
    retrieved: str | None = None,
    owner: object | None = None,
    time: TimeContext | None = None,
    image_mode: Literal["caption", "native"] = "caption",
    image_payloads: Mapping[str, bytes] | None = None,
) -> tuple[str, str | list[dict]]:
    """The two surfaces one compile round is given: `(system text, task content)`.

    `sources` are the ALIASED sources — the handles the model will cite. Called inside the
    component window, because the task carries every enabled component's `source_preamble`
    line. The langchain executor puts the pair into a SystemMessage and a HumanMessage; the
    CLI prints it from `pkc draft open`. Same call, same bytes: invariant I5 holds for an
    agent reading a terminal exactly as it holds for a provider reading a request.
    """
    return (
        render_system_contract(skill, owner=owner, time=time),
        _render_task_content(
            sources,
            base_docs,
            treatments,
            source_guidance,
            source_preamble,
            retrieved,
            time,
            image_mode=image_mode,
            image_payloads=image_payloads,
        ),
    )


def build_compile_tool_face(
    draft: PatchDraft,
    *,
    sources: Sequence[NormalizedSource] = (),
    search_knowledge: SearchKnowledge | None = None,
    search_source: SearchSource | None = None,
) -> list[StructuredTool]:
    """The write tools plus every enabled component's compile tools, in registration order.

    `sources` are the ALIASED sources: a component tool that names a source must name it by
    the same `sNN` handle the task text under the model's eyes uses. Call inside the component
    window (`component_job`), whose `prepare` is what makes a component's sync faces speak
    about this user at all.
    """
    component_tools = [
        tool
        for component in registered_components()
        for tool in component.compile_tools(draft, sources=sources)
    ]
    return _build_tools(draft, search_knowledge, search_source, component_tools)


async def finalize_compile(
    *,
    user_id: UserId,
    store: CanonicalStore,
    draft: PatchDraft,
    sources: Sequence[NormalizedSource],
    skill: SkillVersion,
    commit_message: str = "compile",
    alias_map: dict[str, str] | None = None,
    known_source_bounds: Mapping[str, int] | None = None,
    overview_budget_chars: int = OVERVIEW_BUDGET_CHARS,
    overview_required_after_claims: int = OVERVIEW_REQUIRED_AFTER_CLAIMS,
    violations: Sequence[Violation] | None = None,
    rounds: int = 1,
    tool_calls: int = 0,
    token_usage: Mapping[str, int] | None = None,
) -> CompileResult:
    """The end of a compile round, whichever executor drove it: gate → commit | abort | noop.

    `violations` is an already-computed gate result (the langchain loop runs the gate to
    decide whether a repair round is owed, and hands the answer over rather than paying for
    it twice); `None` means run the gate here. Everything after it is the same either way —
    the handle resolution, the commit with the skill trailer, the derived events — because a
    committed compile is defined by what it wrote, never by who typed the calls.
    """
    if violations is None:
        violations = run_gate(
            draft,
            sources,
            alias_map=alias_map,
            known_source_bounds=known_source_bounds,
            overview_budget_chars=overview_budget_chars,
            overview_required_after_claims=overview_required_after_claims,
        )
    usage = dict(token_usage or {})
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
            violations=list(violations),
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
    resolved = alias_map or {}
    files = {p: resolve_handles(b, resolved) for p, b in files.items()}
    new_bodies = {p: resolve_handles(b, resolved) for p, b in draft.new_bodies().items()}
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
    # WHO drives each round (compile/round.py). None = the langchain loop over `model`,
    # assembled below — which is what every caller in the framework passes today. A second
    # body (an agent under the Owner's subscription) supplies its own runner here and changes
    # nothing else about a compile: same aliasing, same task bytes, same gate, same commit.
    round_runner: RoundRunner | None = None,
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
    # `alias_sources` is the one minting, shared with the CLI executor.
    aliased = alias_sources(
        sources,
        treatments=treatments,
        source_guidance=source_guidance,
        source_preamble=source_preamble,
    )
    real_by_handle = aliased.real_by_handle
    a_sources = aliased.sources
    treatments = aliased.treatments
    source_guidance = aliased.source_guidance
    source_preamble = aliased.source_preamble

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
        tools = build_compile_tool_face(
            draft,
            sources=a_sources,
            search_knowledge=search_knowledge,
            search_source=search_source,
        )
        # core depends only on langchain's callback abstraction (architecture.md §2): the
        # service injects a langfuse handler via `callbacks`; every invoke in the tool loop
        # carries it so Langfuse sees each multi-turn tool round. Keyless → config is a no-op.
        invoke_config = {
            "callbacks": callbacks or [],
            "metadata": trace_metadata or {},
            "run_name": "compile",
        }

        # `time` reaches the system side too, but only for its zone and that zone's
        # provenance (the subject-environment declaration in §2) — never its instant, so the
        # SystemMessage stays byte-stable per (skill, owner, zone, overlay).
        system_text, task_content = render_compile_messages(
            sources=a_sources,
            base_docs=base_docs,
            skill=skill,
            treatments=treatments,
            source_guidance=source_guidance,
            source_preamble=source_preamble,
            retrieved=retrieved,
            owner=owner,
            time=time,
            image_mode=image_mode,
            image_payloads=image_payloads,
        )
        messages: list[BaseMessage] = [
            SystemMessage(content=system_text),
            HumanMessage(content=task_content),
        ]

        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        tool_calls = 0

        def accumulate(spent_usage: Mapping[str, int]) -> None:
            for key in usage:
                usage[key] += int(spent_usage.get(key, 0) or 0)

        # The draft as a round is allowed to see it: the tools, plus the two questions only
        # the whole draft can answer (compile/round.py). Built once and handed to every round.
        face = RoundToolFace(
            tools=tools,
            finish_owed=lambda: [
                v.detail
                for v in overview_required_violations(
                    draft, threshold=overview_required_after_claims
                )
            ],
            owed_now=lambda: owed_now_lines(
                draft, threshold=overview_required_after_claims
            ),
        )
        # Who drives the round. Absent, it is the langchain loop this function has always
        # run — assembled here so the public signature is unchanged and a caller that names
        # no runner gets byte-for-byte the round it got before the seam existed.
        runner = round_runner or LangchainRoundRunner(
            model=model, call_timeout=call_timeout, config=invoke_config
        )

        round_budget = first_round_budget(len(sources), max_tool_calls)
        spent, cut_off, round_usage = await runner.run_round(
            messages=messages, face=face, budget=round_budget
        )
        tool_calls += spent
        accumulate(round_usage)
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
            repair_spent, _, repair_usage = await runner.run_round(
                messages=messages, face=face, budget=repair_budget
            )
            tool_calls += repair_spent
            accumulate(repair_usage)
            rounds = 2
            violations = run_gate(
                draft,
                sources,
                alias_map=real_by_handle,
                known_source_bounds=known_source_bounds,
                overview_budget_chars=overview_budget_chars,
                overview_required_after_claims=overview_required_after_claims,
            )

        return await finalize_compile(
            user_id=user_id,
            store=store,
            draft=draft,
            sources=sources,
            skill=skill,
            commit_message=commit_message,
            alias_map=real_by_handle,
            known_source_bounds=known_source_bounds,
            overview_budget_chars=overview_budget_chars,
            overview_required_after_claims=overview_required_after_claims,
            violations=violations,
            rounds=rounds,
            tool_calls=tool_calls,
            token_usage=usage,
        )
