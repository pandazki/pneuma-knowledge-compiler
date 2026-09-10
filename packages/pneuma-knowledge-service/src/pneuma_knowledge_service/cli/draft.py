"""`pkc draft` — the one door into canonical, driven one command at a time.

The langchain compile loop and these commands are two clients of the SAME door
(docs/design/coding-agent-mode.md ruling 2): the same `PatchDraft`, the same tool closures,
the same gate, the same refusal texts out of the same prompt catalog. Nothing here
reimplements a verb. What a command adds around the call it forwards is the part a loop gets
for free and a command line does not:

- **the round is loaded and stored again.** A CLI has no memory between invocations, so every
  command reads the draft and its session out of the `DraftStore` and writes them back — and
  writes them back only when the command succeeded (ruling 3, §6).
- **the components' window.** Every command opens `component_job(user_id)`, whose `prepare`
  is what makes a component's sync faces speak about this user at all. A fresh process's
  mirror is cold by construction.
- **the post-check.** A write that passed its argument checks is applied and then judged by
  the gate's own predicates over the page it touched; a failure rolls the draft back and the
  command exits non-zero (ruling 10). The Steward is TOLD the library is still whole rather
  than asked to keep it whole.
- **the budget.** Each call spends one of the round's calls, the same formula as the loop,
  with the same low-water notice from the same catalog key — appended to the command's output,
  because a CLI cannot speak between an agent's turns (§6, "one stated difference").

Exit codes are the mechanism a script branches on without parsing prose:
0 ok · 1 nothing to act on (no open draft, no such job) · 2 refused (a tool's own
`AnchorToolError`, or a post-check the write did not survive) · 3 the round's budget is spent
· 4 the gate rejected the draft (`check`, and `finish` with violations).
"""

from __future__ import annotations

import inspect
import json
import os
import socket
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import wraps
from typing import Any, TextIO

from langchain_core.tools import StructuredTool
from pneuma_knowledge_core.components import component_job
from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.gate import (
    Violation,
    overview_required_violations,
    owed_now_lines,
    post_write_violations,
    run_gate,
)
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import (
    BUDGET_NOTICE_REMAINING,
    CompileResult,
    alias_sources,
    build_compile_tool_face,
    finalize_compile,
    first_round_budget,
    render_compile_messages,
    render_violations,
    repair_round_budget,
)
from pneuma_knowledge_core.compile.session import DraftSession, content_sha256
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_core.ports.draft_store import DraftOwnershipError
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill.version import SkillVersion

from ..persona_profile import PLACEHOLDER_NOTICE
from .check import SKILL_TRAILER

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_REFUSED = 2
EXIT_BUDGET = 3
EXIT_GATE = 4

#: The write verbs, i.e. the calls whose result is post-checked on the page they touched.
#: A read verb changes nothing a gate predicate can judge (`read_document` only records that
#: the page was seen), so running the gate after one would be judging the page before it.
WRITE_TOOLS = frozenset(
    {
        "create_document",
        "append_block",
        "edit_claim",
        "supersede_claim",
        "rewrite_overview",
        "set_fields",
    }
)


def draft_executor() -> str:
    """The session typing commands, separate from its harness/model accounting label."""
    explicit = os.environ.get("PKC_DRAFT_EXECUTOR", "").strip()
    if explicit:
        return explicit
    token = (os.environ.get("PKC_STEWARD_SESSION") or os.environ.get("CODEX_THREAD_ID")
             or os.environ.get("CLAUDE_SESSION_ID") or "").strip()
    digest = os.environ.get("PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH", "")
    if token:
        return "steward:" + content_sha256(f"{digest}:{token}")
    # No session token in the environment: every `pkc` command is its own process, so a
    # per-process identity would make a Steward's second command "another executor" and
    # refuse it. The distinction the ownership rule exists for is Steward versus worker,
    # so an interactive Steward without a token is one executor class: the Owner's
    # terminal, on this host, under this skill.
    return "steward:" + content_sha256(f"{digest}:terminal@{socket.gethostname()}")


def draft_command(fn):
    """Hold the tenant's draft lock through the entire command, including commit and finish.

    Takeover and startup expiry take this same lock, so a command already inside the gate
    cannot have its draft stolen midway through a canonical write.
    """
    @wraps(fn)
    async def guarded(rt, *args, **kwargs):
        try:
            async with rt.drafts.lock(rt.user_id):
                return await fn(rt, *args, **kwargs)
        except DraftOwnershipError as exc:
            print(str(exc), file=rt.err)
            return (EXIT_REFUSED, "", "") if fn.__name__ == "open_round" else EXIT_REFUSED
    return guarded


@dataclass
class DraftRuntime:
    """Everything a `pkc draft` command needs, injected rather than looked up.

    The real CLI builds this from the process settings (`cli/__init__.py`); the tests build it
    over in-memory stores, which is what lets the byte-equality suite run the CLI path with no
    Postgres, no keys and no network.
    """

    user_id: UserId
    canonical: Any  #: CanonicalStore — `list` + `commit_patch`
    drafts: Any  #: DraftStore
    jobs: Any  #: JobQueue — claim / release / complete / get_job
    skill: SkillVersion
    #: job → the material and frame of one compile round (`workers.compile_worker`).
    load_inputs: Callable[[Any], Awaitable[Any]]
    #: source ids → the NormalizedSources, for every command after `open`.
    load_sources: Callable[[Sequence[str]], Awaitable[list[NormalizedSource]]]
    #: this user's L0 block counts, for the gate's citation bounds.
    load_bounds: Callable[[], Awaitable[dict[str, int]]]
    overview_budget_chars: int
    overview_required_after_claims: int
    max_tool_calls: int = 0
    search_knowledge: Any = None
    search_source: Any = None
    #: what happens to the derived layers and the job row once a round produced a result.
    #: None → the job is simply completed, which is all a test needs.
    persist: Callable[[Any, CompileResult], Awaitable[None]] | None = None
    #: what the finished job records about WHO ran the round (`agent:<backend>`, or `agent`
    #: when nothing named the harness). It is the CLI's answer to a question the langchain
    #: worker answers with its model spec; usage is deliberately absent either way, because
    #: a harness's counters belong to the Owner's subscription and a zero would be a claim.
    executor: str = "agent"
    #: The sha256 of the skill package the round's executor was taught with, when this
    #: process is not the one that read it. The worker finishes a round its launched harness
    #: drove (`coding_agent/round_runner.py`), and the variable the harness carried was never
    #: in the worker's own environment — so without this the commit that ends an agent round
    #: the harness did not close carries no `Executor-Skill:` trailer at all. Empty means the
    #: process answers for itself, which is what an Owner's own terminal session needs.
    executor_skill: str = ""
    draft_executor: str = field(default_factory=draft_executor)
    compile_draft_ttl: int = 6 * 60 * 60
    worker_posture: str = ""
    #: The unattended runner must never load a later job belonging to this tenant.
    expected_job_id: str = ""
    kind: str = "compile"
    record_brief: Callable[[str, str], Awaitable[None]] | None = None
    #: Does the owner profile still name nobody? A NOTICE, never a refusal: the round opens,
    #: the surfaces are byte-identical, and the langchain executor is untouched. What it buys
    #: is that a Steward about to file the Owner as a stranger reads one line saying so first
    #: (`cli/profile.py`). Default False so a runtime assembled by a test — or by anything
    #: that cannot read a profile — says nothing at all.
    owner_is_placeholder: bool = False
    owner_profile_notice: str = ""
    owner_authored_blocks: dict[str, list[int]] = field(default_factory=dict)
    #: How much numbered source text the round's task carries before it stops and names the
    #: rest (`AGENT_TASK_STRUCTURE_CHARS`). 0 = unbounded, which is what a runtime assembled
    #: by a test gets, so every existing byte-equality check still compares whole tasks.
    task_structure_chars: int = 0
    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)


# ─────────────────────────────────────────────────────────────── loading and storing


def _draft_state(draft: PatchDraft, session: DraftSession) -> dict:
    return {"kind": session.kind, "draft": draft.to_state(), "session": session.to_state()}


async def _store(rt: DraftRuntime, draft: PatchDraft, session: DraftSession) -> None:
    await rt.drafts.put(rt.user_id, session.job_id, _draft_state(draft, session))


async def require_owner(rt: DraftRuntime, job_id: str) -> None:
    owner = await rt.drafts.owner(rt.user_id, job_id)
    # A draft written before ownership existed recorded no executor. Nobody holds it, so
    # the first executor to act on it adopts it — refusing would strand every draft that
    # was open when this rule arrived, and a worker's own drafts always carry an executor.
    if owner is not None and owner.executor and owner.executor != rt.draft_executor:
        raise DraftOwnershipError(owner.refusal(draft_door(rt.kind)))
    job = await rt.jobs.get_job(rt.user_id, job_id)
    if job is None or getattr(job, "status", "claimed") != "claimed":
        raise DraftOwnershipError(f"job {job_id} is not claimed; a finished job cannot be reopened")


def ownership_fields(rt: DraftRuntime) -> dict[str, str]:
    return {
        "executor": rt.draft_executor,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "worker_posture": rt.worker_posture,
    }


async def require_open_slot(rt: DraftRuntime, job_id: str) -> None:
    """Refuse a different executor before loading any role's task or touching its job."""
    for held_id in await rt.drafts.list_open(rt.user_id):
        await require_owner(rt, held_id)
        if held_id != job_id:
            raise DraftOwnershipError(f"draft for job {held_id} is already open; finish or abandon it first")


async def _open_job_id(rt: DraftRuntime) -> str | None:
    """The job this user currently holds a draft on, or None.

    At most one, and that is not this module's promise: the queue hands out one claimed job
    per user, so one open round per user is what the single-writer rule already means.
    """
    open_ids = await rt.drafts.list_open(rt.user_id)
    return open_ids[0] if open_ids else None


async def _load(rt: DraftRuntime) -> tuple[PatchDraft, DraftSession] | None:
    job_id = rt.expected_job_id or await _open_job_id(rt)
    state = await rt.drafts.get(rt.user_id, job_id) if job_id else None
    if state is None:
        print(
            f"no open draft: run `{draft_door(rt.kind)} open <job-id>` first.", file=rt.err
        )
        return None
    await require_owner(rt, job_id)
    session = DraftSession.from_state(state.get("session") or {})
    if session.kind != rt.kind:
        print(f"the open draft is {session.kind}; use `{draft_door(session.kind)}`.", file=rt.err)
        return None
    return PatchDraft.from_state(state.get("draft") or {}), session


def draft_door(kind: str) -> str:
    return {"evolve": "pkc evolve draft", "episodes": "pkc index episodes"}.get(kind, "pkc draft")


def _base_documents(draft: PatchDraft) -> list[CanonicalDocument]:
    """The draft's PINNED base as canonical documents — what the task's outline was rendered
    from. A resumed round re-renders from this, never from whatever canonical says now: the
    round is judged against the library it opened on."""
    return [
        CanonicalDocument(
            doc_id=DocumentId(str(doc.doc_id)),
            path=path,
            frontmatter=dict(doc.frontmatter),
            body=doc.body,
        )
        for path, doc in sorted(draft.base_documents().items())
    ]


# ─────────────────────────────────────────────────────────────────────── open / status


async def cmd_open(rt: DraftRuntime, job_id: str) -> int:
    """Claim the job, render the contract and the task, print the round's two surfaces."""
    code, system_text, task_text = await open_round(rt, job_id)
    if code == EXIT_OK:
        notice = rt.owner_profile_notice or (PLACEHOLDER_NOTICE if rt.owner_is_placeholder else "")
        if notice:
            # Above the round, not inside it: `open_round` renders the same bytes either way
            # (I5), and the unattended launcher hands those bytes to a harness untouched.
            print(f"note: {notice}\n", file=rt.out)
        _print_round(rt, system_text, task_text)
    return code


@draft_command
async def open_round(
    rt: DraftRuntime, job_id: str, *, claim: bool = True
) -> tuple[int, str, str]:
    """`open`, as the two surfaces rather than as printed output: `(code, system, task)`.

    The command prints them; the unattended launcher hands them to a harness
    (`coding_agent/round_runner.py`). One function renders them either way, because "the same
    job renders the same task bytes under either posture" has to be a property of the code
    (I5).

    `claim=False` is the worker's unattended path: the job is ALREADY claimed by the drain
    that is about to hand it to a harness, and claiming it twice would fail on the queue's own
    single-in-flight rule. Nothing else differs — the draft, the surfaces and the session are
    the ones `pkc draft open` would have made.
    """
    existing = await rt.drafts.get(rt.user_id, job_id)
    if existing is not None:
        await require_owner(rt, job_id)
        if existing.get("kind", "compile") != rt.kind:
            print("this job has a different kind of draft", file=rt.err)
            return EXIT_REFUSED, "", ""
        draft = PatchDraft.from_state(existing.get("draft") or {})
        session = DraftSession.from_state(existing.get("session") or {})
        job = await rt.jobs.get_job(rt.user_id, job_id)
        inputs = await rt.load_inputs(job)
        # Rendered from the draft's OWN base, not from canonical as it stands: the round is
        # judged against the library it opened on, so that is the library it is shown.
        async with component_job(str(rt.user_id)):
            system_text, task = _render_surfaces(rt, _base_documents(draft), inputs)
        if session.task_sha256 and content_sha256(task) != session.task_sha256:
            # Said rather than hidden: the retrieved-claims block is a live query, so a
            # resumed task can legitimately differ. What may not differ silently is the
            # contract and the material, and this line is what makes a change visible.
            print(
                "note: the task re-renders differently than when this draft was opened "
                f"({session.task_sha256[:12]} → {content_sha256(task)[:12]}); the draft's "
                "base and its source handles are unchanged.",
                file=rt.err,
            )
        await _store(rt, draft, session)
        return EXIT_OK, system_text, task

    other_id = await _open_job_id(rt)
    if other_id:
        await require_owner(rt, other_id)
        raise DraftOwnershipError(f"draft for job {other_id} is already open; finish or abandon it first")

    candidate = await rt.jobs.get_job(rt.user_id, job_id)
    if candidate is not None and getattr(candidate, "kind", "compile") != rt.kind:
        print(f"job {job_id} is not a {rt.kind} job", file=rt.err)
        return EXIT_REFUSED, "", ""

    # Before anything is claimed: does the library HEAD carry the framework's own trailer?
    # A commit that arrived by another route is detected here and named (§8) — the sentence
    # the skill states about the door having no second path is true because this refuses.
    outside = await outside_write(rt)
    if outside:
        print(outside, file=rt.err)
        return EXIT_REFUSED, "", ""

    job = (
        await rt.jobs.claim(rt.user_id, job_id, claimed_by=rt.draft_executor)
        if claim
        else await rt.jobs.get_job(rt.user_id, job_id)
    )
    if job is None or getattr(job, "status", "claimed") != "claimed":
        existing_job = await rt.jobs.get_job(rt.user_id, job_id)
        if existing_job is None:
            print(f"no such job for this user: {job_id}", file=rt.err)
        else:
            print(
                f"job {job_id} could not be claimed (status "
                f"{getattr(existing_job, 'status', '?')}); this user may already have a job "
                "in flight.",
                file=rt.err,
            )
        return (EXIT_REFUSED if not claim else EXIT_NOTHING), "", ""
    if not claim and getattr(job, "claimed_by", "worker") not in ("worker", rt.draft_executor):
        raise DraftOwnershipError(f"job {job_id} is claimed by {job.claimed_by}; cannot join its round")

    inputs = await rt.load_inputs(job)
    base_docs = await rt.canonical.list(rt.user_id)
    draft = PatchDraft.from_canonical(
        base_docs,
        rt.skill.path_templates,
        overview_budget_chars=rt.overview_budget_chars,
        owner_voice_templates=rt.skill.owner_voice_templates,
        owner_authored_blocks=rt.owner_authored_blocks,
    )
    async with component_job(str(rt.user_id)):
        system_text, task_text = _render_surfaces(rt, base_docs, inputs)
    session = DraftSession(
        user_id=str(rt.user_id),
        job_id=job_id,
        **ownership_fields(rt),
        handle_by_real=alias_sources(inputs.sources).handle_by_real,
        round="first",
        budget=first_round_budget(len(inputs.sources), rt.max_tool_calls),
        task_sha256=content_sha256(task_text),
        skill_id=rt.skill.skill_id,
        skill_version=rt.skill.version,
        skill_content_hash=rt.skill.content_hash,
        overview_budget_chars=rt.overview_budget_chars,
        overview_required_after_claims=rt.overview_required_after_claims,
        max_tool_calls=rt.max_tool_calls,
        commit_message=inputs.commit_message,
    )
    await _store(rt, draft, session)
    return EXIT_OK, system_text, task_text


async def outside_write(rt: DraftRuntime) -> str:
    """"" when the library is the framework's own work, or the sentence that says it is not.

    Every canonical write channel this framework has — a compile's commit, a groom heal, an
    evolve adopt, the per-user skill manifest — goes through `with_skill_trailer`, so a HEAD
    without a `Skill-Version` trailer is a commit nothing here made. That is not a hypothesis
    about a careless Owner: the interactive posture puts a coding agent in the project with a
    shell, and the door there is convention plus DETECTION (§8). Detected at the next compile
    and named, rather than compounded by a round that builds claims on top of it.

    A repository with no commits opens normally, because that is a library that has not been
    written yet — the git adapter's `_repo` runs `git init` and makes no bootstrap commit of
    its own, so "no commits" is the only exempt state there is. A store that cannot read
    trailers at all (a test double, a future adapter) is not interrogated: the audit reports
    what it can see, and inventing a finding from an absent capability would be worse than
    the finding it is looking for.
    """
    reader = getattr(rt.canonical, "commit_trailer", None)
    lister = getattr(rt.canonical, "snapshots", None)
    if reader is None or lister is None:
        return ""
    try:
        snapshots = await lister(rt.user_id)
    except Exception:  # noqa: BLE001 — an unreadable repository is not this command's finding
        return ""
    if not snapshots:
        return ""
    head = snapshots[0]
    try:
        value = await reader(rt.user_id, head, SKILL_TRAILER)
    except Exception:  # noqa: BLE001
        return ""
    if value:
        return ""
    subject = (head.label or "").splitlines()[0] if head.label else "no subject"
    return (
        f"the library was written outside the gate at {head.ref}: {subject}. Every commit "
        "this framework makes carries a "
        f"{SKILL_TRAILER} trailer; this one carries none, so a round opened on top of it "
        "would build claims on a change nothing can attribute. Inspect that commit (or "
        "revert it) before compiling again."
    )


def _render_surfaces(
    rt: DraftRuntime, base_docs: list[CanonicalDocument], inputs: Any
) -> tuple[str, str]:
    """The round's system text and task content, from one call both `open` and a resume make.

    `image_mode` is pinned to captions: an agent reads a terminal, and a native image block is
    not something a terminal carries. A deployment whose material needs vision compiles it
    with a model executor; what the CLI must never do is present a caption round as if the
    images had been seen.
    """
    aliased = alias_sources(
        inputs.sources,
        treatments=inputs.treatments,
        source_guidance=inputs.source_guidance,
        source_preamble=inputs.source_preamble,
    )
    system_text, task = render_compile_messages(
        sources=aliased.sources,
        base_docs=base_docs,
        skill=rt.skill,
        treatments=aliased.treatments,
        source_guidance=aliased.source_guidance,
        source_preamble=aliased.source_preamble,
        retrieved=inputs.retrieved,
        owner=inputs.owner,
        time=inputs.time,
        image_mode="caption",
        # An agent can read what the task does not show, so its task stops at a bound and
        # names the rest by the id `pkc source fetch` takes — the library's, not the handle.
        max_source_chars=rt.task_structure_chars,
        fetch_ids=aliased.real_by_handle,
    )
    return system_text, _as_text(task)


def _as_text(content: str | list[dict]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(str(part.get("text", "")) for part in content if "text" in part)


def _print_round(rt: DraftRuntime, system_text: str, task: str) -> None:
    """The two surfaces, byte-for-byte as the langchain executor's two messages carry them.

    I5 is a statement about the bytes the compiler is given, and it does not weaken because
    the compiler is reading a terminal instead of a request body.
    """
    rt.out.write(f"{system_text}\n\n{task}\n")


@draft_command
async def cmd_status(rt: DraftRuntime) -> int:
    """What remains of the round, what has been read, and what the gate already finds owed."""
    loaded = await _load(rt)
    if loaded is None:
        return EXIT_NOTHING
    draft, session = loaded
    owed = owed_now_lines(draft, threshold=session.overview_required_after_claims)
    lines = [
        f"job: {session.job_id}",
        f"round: {session.round}",
        f"budget: {session.remaining} of {session.budget} calls remain",
        "pages read this draft: " + (", ".join(sorted(draft.read_paths())) or "(none)"),
        "what the mechanical checks already find owed:",
        *(owed or [prompt("compile.budget.owed_none")]),
    ]
    rt.out.write("\n".join(lines) + "\n")
    return EXIT_OK


# ────────────────────────────────────────────────────────────────────── the tool face


async def run_tool(rt: DraftRuntime, name: str, args: dict) -> int:
    """Apply exactly one tool call to the open draft: budget → tool → post-check → persist.

    A refused call SPENDS a call, exactly as the langchain loop charges a refused or
    unparseable one: the budget bounds the round, and a round that could be refused for
    free would have no bound at all. What a refusal never does is move the draft — the state
    written back on a refusal is the draft as it stood plus one more call spent.
    """
    async def execute(draft: PatchDraft, session: DraftSession) -> str:
        sources = await rt.load_sources(session.source_ids)
        bounds = await rt.load_bounds()
        if draft.owner_voice_templates:
            from pneuma_knowledge_core.domain.authorship import owner_authored_blocks

            draft.owner_authored_blocks.update(rt.owner_authored_blocks)
            draft.owner_authored_blocks.update({
                str(source.raw.source_id): owner_authored_blocks(source.raw) for source in sources
            })
        aliased = alias_sources(sources)
        async with component_job(str(rt.user_id)):
            tools = build_compile_tool_face(
                draft,
                sources=aliased.sources,
                search_knowledge=rt.search_knowledge,
                search_source=rt.search_source,
            )
            by_name = {t.name: t for t in tools}
            tool = by_name.get(name)
            if tool is None:
                raise AnchorToolError(prompt("compile.tool.unknown_tool", name=name))

            writes = name in WRITE_TOOLS
            touched = str(args.get("path") or "") if writes else ""
            baseline: list[Violation] = (
                run_gate(
                    draft,
                    sources,
                    alias_map=session.real_by_handle,
                    known_source_bounds=bounds,
                    overview_budget_chars=session.overview_budget_chars,
                    overview_required_after_claims=session.overview_required_after_claims,
                )
                if writes
                else []
            )
            # Read ports are async; write tools stay sync (pure in-memory PatchDraft
            # mutation). Dispatch on the function, exactly as the tool loop does.
            fn = tool.coroutine or tool.func
            result = await fn(**args) if inspect.iscoroutinefunction(fn) else fn(**args)

            if writes:
                broke = post_write_violations(
                    draft,
                    sources,
                    touched,
                    baseline=baseline,
                    alias_map=session.real_by_handle,
                    known_source_bounds=bounds,
                    overview_budget_chars=session.overview_budget_chars,
                    overview_required_after_claims=session.overview_required_after_claims,
                )
                if broke:
                    # Applied, judged, and rolled back: the draft on disk is the one from before
                    # the command, and the Steward reads what the gate would have said at the end
                    # of the round while it still holds the material.
                    raise AnchorToolError("\n".join(v.render() for v in broke))
        return str(result)

    return await apply_call(rt, name, execute)


@draft_command
async def apply_call(
    rt: DraftRuntime,
    name: str,
    execute: Callable[[PatchDraft, DraftSession], Awaitable[str]],
    *,
    owed: Callable[[PatchDraft, DraftSession], list[str]] | None = None,
) -> int:
    """Shared command transaction: charge refusals, roll back, persist and notify.

    The door supplies its operation and its gate; both doors share all budget and storage
    behavior. Snapshot BOTH halves so a rejected proposal cannot change session metadata.
    """
    loaded = await _load(rt)
    if loaded is None:
        return EXIT_NOTHING
    draft, session = loaded
    if session.remaining <= 0:
        print(prompt("compile.budget.call_refused", budget=session.budget), file=rt.err)
        return EXIT_BUDGET
    untouched = _draft_state(draft, session)
    # JSON is also the store's boundary; this makes nested proposal data independent.
    untouched = json.loads(json.dumps(untouched))
    try:
        text = await execute(draft, session)
    except (AnchorToolError, TypeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, AnchorToolError) else prompt(
            "compile.tool.call_failed", name=name, error=exc
        )
        print(message, file=rt.err)
        await _store(
            rt, PatchDraft.from_state(untouched["draft"]),
            DraftSession.from_state(untouched["session"]).spend(),
        )
        return EXIT_REFUSED
    session = session.spend()
    if not session.noticed and session.remaining <= BUDGET_NOTICE_REMAINING:
        session = session.with_notice()
        lines = owed(draft, session) if owed else owed_now_lines(
            draft, threshold=session.overview_required_after_claims
        )
        text += "\n" + prompt(
            "compile.budget.notice", remaining=session.remaining, budget=session.budget,
            owed="\n".join(lines) or prompt("compile.budget.owed_none"),
        )
    await _store(rt, draft, session)
    rt.out.write(text + "\n")
    return EXIT_OK


# ───────────────────────────────────────────────────────────────── check / finish / abandon


@draft_command
async def cmd_check(rt: DraftRuntime) -> int:
    """The whole gate over the open draft, without finishing. Free: it decides nothing."""
    loaded = await _load(rt)
    if loaded is None:
        return EXIT_NOTHING
    draft, session = loaded
    violations = await _gate(rt, draft, session)
    if violations:
        rt.out.write(render_violations(violations) + "\n")
        return EXIT_GATE
    rt.out.write("gate: clean.\n")
    return EXIT_OK


async def _gate(
    rt: DraftRuntime, draft: PatchDraft, session: DraftSession
) -> list[Violation]:
    sources = await rt.load_sources(session.source_ids)
    return run_gate(
        draft,
        sources,
        alias_map=session.real_by_handle,
        known_source_bounds=await rt.load_bounds(),
        overview_budget_chars=session.overview_budget_chars,
        overview_required_after_claims=session.overview_required_after_claims,
    )


BRIEF_MAX_CHARS = 8000


def validate_brief(text: str) -> str:
    """The Steward's narration, bounded independently of canonical knowledge."""
    if not text.strip() or len(text) > BRIEF_MAX_CHARS:
        raise ValueError(f"brief must be non-blank and at most {BRIEF_MAX_CHARS} characters")
    return text


@draft_command
async def cmd_finish(rt: DraftRuntime, *, brief: str | None = None) -> int:
    """The overview floor, then the gate, then the commit — the end of `run_compile`, replayed.

    Clean: commit, events, the job completed, the draft deleted. Violations on the FIRST
    round: they are stored with a fresh repair budget and the draft stays open for one repair
    round — the same allowance the langchain executor's repair round gets, sized by the same
    formula. Violations again: the job is aborted exactly as `run_compile` aborts it, with the
    canonical layer untouched.
    """
    if brief is not None:
        try:
            brief = validate_brief(brief)
        except ValueError as exc:
            print(str(exc), file=rt.err)
            return EXIT_REFUSED
    loaded = await _load(rt)
    if loaded is None:
        return EXIT_NOTHING
    draft, session = loaded
    if brief is not None:
        session.context["brief"] = brief
    else:
        brief = session.context.get("brief")

    async with component_job(str(rt.user_id)):
        owed = overview_required_violations(
            draft, threshold=session.overview_required_after_claims
        )
        if owed:
            # The one rule that can only be judged at the END, said where `finish_compile`
            # says it: the round still holds the material and one `rewrite_overview` fixes it.
            # It costs a call, like the tool call it mirrors, and it does not spend the round's
            # single repair.
            session = session.spend()
            await _store(rt, draft, session)
            print("\n".join(v.detail for v in owed), file=rt.err)
            return EXIT_GATE

        violations = await _gate(rt, draft, session)
        session = session.spend()

        if violations and session.round == "first":
            repair_budget = repair_round_budget(
                len(violations),
                first_round_budget(len(session.source_ids), session.max_tool_calls),
            )
            cut_off = session.remaining <= 0
            feedback = render_violations(
                violations,
                cut_off_at=session.spent if cut_off else None,
                next_budget=repair_budget,
            )
            session = replace(
                session,
                round="repair",
                budget=repair_budget,
                spent=0,
                noticed=False,
                cut_off=cut_off,
                violations=tuple(
                    (v.kind, v.path, v.detail) for v in violations
                ),
            )
            await _store(rt, draft, session)
            print(feedback, file=rt.err)
            return EXIT_GATE

        sources = await rt.load_sources(session.source_ids)
        result = await finalize_compile(
            user_id=rt.user_id,
            store=rt.canonical,
            draft=draft,
            sources=sources,
            skill=rt.skill,
            commit_message=session.commit_message,
            alias_map=session.real_by_handle,
            known_source_bounds=await rt.load_bounds(),
            overview_budget_chars=session.overview_budget_chars,
            overview_required_after_claims=session.overview_required_after_claims,
            violations=violations,
            rounds=2 if session.round == "repair" else 1,
            tool_calls=session.spent,
            executor_skill=rt.executor_skill,
        )

    await _persist(rt, session, result)
    if brief is not None and result.snapshot is not None and result.status != "aborted":
        if rt.record_brief is not None:
            try:
                await rt.record_brief(session.job_id, brief)
            except Exception as exc:  # noqa: BLE001 — narration cannot fail a committed compile
                print(f"the version finished, but its brief could not be recorded: {exc}", file=rt.err)
    await rt.drafts.delete(rt.user_id, session.job_id, executor=rt.draft_executor)
    if result.status == "aborted":
        print(render_violations(result.violations), file=rt.err)
        return EXIT_GATE
    rt.out.write(
        f"{result.status}: {len(result.files)} file(s), {len(result.events)} event(s)"
        + (f", snapshot {result.snapshot.ref}" if result.snapshot else "")
        + "\n"
    )
    return EXIT_OK


async def _persist(
    rt: DraftRuntime, session: DraftSession, result: CompileResult
) -> None:
    """Hand the result to the derived layers and end the job.

    The real runtime forwards to `workers.compile_worker.persist_compile_result` — the very
    code the langchain worker runs — so an agent-compiled job leaves the same events, the same
    projection delta, the same digestion and the same job row behind. Without one (the unit
    tests) the job is simply completed with the same outcome and detail."""
    if rt.persist is not None:
        job = await rt.jobs.get_job(rt.user_id, session.job_id)
        await rt.persist(job, result)
        return
    await complete_job(rt, session.job_id, result)


async def complete_job(rt: DraftRuntime, job_id: str, result: CompileResult) -> None:
    """End the job row from a compile result, and nothing else.

    What is left of `persist_compile_result` when there are no derived layers to move: the
    outcome and its detail, recorded on the same terms — an abort carries the violations, a
    commit carries its snapshot. No `token_usage`: nothing here measured any, and the column
    stays NULL rather than recording a zero nobody counted."""
    if result.status == "aborted":
        await rt.jobs.complete(
            rt.user_id,
            job_id,
            ok=False,
            detail="; ".join(v.render() for v in result.violations),
            executor=rt.executor,
        )
        return
    await rt.jobs.complete(
        rt.user_id,
        job_id,
        ok=True,
        detail=result.status,
        snapshot_ref=result.snapshot.ref if result.snapshot else None,
        executor=rt.executor,
    )


@draft_command
async def cmd_abandon(rt: DraftRuntime, *, take_over: bool = False) -> int:
    """Release the job back to the queue and drop the draft. Canonical is untouched: an
    unfinished round wrote nothing anywhere."""
    job_id = rt.expected_job_id or await _open_job_id(rt)
    if job_id is None:
        print("no open draft", file=rt.err)
        return EXIT_NOTHING
    state = await rt.drafts.get(rt.user_id, job_id)
    if state is None:
        print("no open draft", file=rt.err)
        return EXIT_NOTHING
    kind = (state.get("session") or {}).get("kind", "compile")
    if kind != rt.kind:
        print(f"the open draft is {kind}; use `{draft_door(kind)}`.", file=rt.err)
        return EXIT_NOTHING
    audit = await rt.drafts.abandon(
        rt.user_id, job_id, executor=rt.draft_executor, take_over=take_over,
        grace_seconds=max(60, rt.compile_draft_ttl // 12),
    )
    if audit:
        rt.out.write(f"taken over by {audit['executor']} from {audit['previous_executor']}: {audit['reason']}\n")
    rt.out.write(f"abandoned {job_id}; the job is back in the queue.\n")
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────── argument plumbing


#: What a `--*-file` argument means when it names stdin. The universal shell convention, and
#: what the generated SKILL.md teaches: `pkc owner say --text-file -` is the form a harness
#: writes when it is piping a heredoc, and the CLI must accept the form its own skill prints.
STDIN_PATH = "-"


class TextArgError(Exception):
    """A `--*-file` argument that names nothing readable.

    An exception rather than a traceback: every one of these arguments is typed by a Steward
    mid-round, and a Python traceback is not a refusal it can read and repair. Raised here,
    turned into one stderr line and exit 2 by the one caller that knows the process's
    streams (`cli/__init__._run`).
    """


def _open_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise TextArgError(
            f"cannot read {path!r}: {exc.strerror or exc}. "
            f"Pass a readable file, or `{STDIN_PATH}` to read the text from stdin."
        ) from None


def read_text_arg(path: str | None, stdin: TextIO | None = None) -> str:
    """A claim's text, from a file or from stdin — never from argv.

    A claim is a paragraph, and a shell quoting error is not a compile error the round should
    be spending calls on (§5.2). `-` is stdin, and so is an omitted flag: two spellings of
    the one thing, because the skill prints the first and `--help` documents the second.
    """
    if path and path != STDIN_PATH:
        return _open_text(path)
    return (stdin or sys.stdin).read()


def _load_json(text: str, source: str):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise TextArgError(f"{source} is not valid JSON: {exc}") from None


def read_json_arg(text: str | None, path: str | None = None, stdin: TextIO | None = None):
    if path and path != STDIN_PATH:
        return _load_json(_open_text(path), repr(path))
    if path == STDIN_PATH:
        return _load_json((stdin or sys.stdin).read(), "stdin")
    if text is not None:
        return _load_json(text, "the argument")
    return _load_json((stdin or sys.stdin).read(), "stdin")


def component_tool_specs() -> list[StructuredTool]:
    """Every enabled component's compile tools, for the parser to render as subcommands.

    Asked over an EMPTY draft and no sources: the parser needs each tool's name, description
    and argument schema, which are declarations, and a component handed no sources binds
    nothing to a user (components/__init__.py). The tools a command actually calls are the
    ones bound to the real draft inside the component window.
    """
    empty = PatchDraft.from_canonical([], [])
    from pneuma_knowledge_core.components import registered_components

    return [
        tool
        for component in registered_components()
        for tool in component.compile_tools(empty, sources=())
    ]
