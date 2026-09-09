"""`pkc draft` against `run_compile`: one door, two clients (coding-agent-mode ruling 2).

The acceptance test of the whole CLI executor is byte equality — the same sequence of tool
calls, run once through the langchain loop with a scripted model and once through the draft
commands, produces the same committed files, the same events and the same violations. It is
written before the CLI has a user, and everything else here is the same claim from a different
side: the refusals are the tools' own texts, the budget is the same formula, the lifecycle is
the queue's own single-writer rule.

Keyless and middleware-free: an in-memory canonical store, the in-memory `DraftStore` and job
queue (`adapters/draft_mock.py`), and the scripted chat model the rest of the suite uses.
"""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from langchain_core.messages import ToolMessage
from pneuma_knowledge_core.compile.documents import parse_document
from pneuma_knowledge_core.compile.runner import (
    BUDGET_NOTICE_REMAINING,
    first_round_budget,
    render_violations,
    run_compile,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.ports.canonical_store import CanonicalDirtyError
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from langchain_core.tools import StructuredTool
from pneuma_knowledge_core.components import (
    BaseComponent,
    register_component,
    reset_components,
)
from pneuma_knowledge_core.compile.gate import Violation
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service.adapters.draft_mock import InMemoryDraftStore, InMemoryJobQueue
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.cli import (
    DEFAULT_TENANT,
    _tool_call,
    build_parser,
    draft as draft_cmd,
    resolve_tenant,
)
from pydantic import PrivateAttr

USER = UserId("u-draft-1")
SKILL = load_skill_base("v1")
PERSON = "memory/people/cheng-ye.md"
TOPIC = "memory/topics/q3-launch.md"


class RecordingScriptedChatModel(ScriptedChatModel):
    """The suite's scripted model, plus the message lists it was handed.

    The comparison this file makes is against what the LOOP actually saw and was told, so the
    loop's own messages have to be readable: the system and task bytes for the byte-equality
    test, and the ToolMessages for refusal parity.
    """

    _seen: list = PrivateAttr(default_factory=list)

    @property
    def seen(self) -> list:
        return self._seen

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self._seen.append(list(messages))
        return await super()._agenerate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )


class FakeCanonicalStore:
    """In-memory CanonicalStore: `list` + `commit_patch`, recording what was committed."""

    def __init__(self, docs: list[CanonicalDocument] | None = None) -> None:
        self._docs = list(docs or [])
        self.commits: list[dict[str, str]] = []
        self.messages: list[str] = []

    async def list(self, user_id, *, at: SnapshotRef | None = None):  # noqa: ANN001
        return list(self._docs)

    async def commit_patch(self, user_id, files: dict[str, str], *, message: str):  # noqa: ANN001
        self.commits.append(dict(files))
        self.messages.append(message)
        self._docs = [
            CanonicalDocument(
                doc_id=DocumentId(str(parse_document(text)[0].get("doc_id", ""))),
                path=path,
                frontmatter=parse_document(text)[0],
                body=parse_document(text)[1],
            )
            for path, text in files.items()
        ]
        return SnapshotRef(ref=f"commit-{len(self.commits)}")


def source(source_id: str = "src-01", n_blocks: int = 5) -> NormalizedSource:
    return NormalizedSource(
        raw=RawSource(
            source_id=SourceId(source_id),
            user_id=USER,
            kind="conversation",
            title="会议",
            mime="text/plain",
            checksum=source_id,
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=i, text=f"b{i}") for i in range(n_blocks)],
        structure=StructureMap(),
    )


@dataclass
class FakeInputs:
    """The shape `workers.compile_worker.compile_inputs` returns, as a round needs it here."""

    sources: list[NormalizedSource]
    source_ids: list[str] = field(default_factory=list)
    treatments: dict = field(default_factory=dict)
    source_guidance: dict = field(default_factory=dict)
    source_preamble: dict = field(default_factory=dict)
    owner: Any = None
    owner_name: str = ""
    retrieved: str = ""
    time: Any = None
    known_source_bounds: dict = field(default_factory=dict)
    image_mode: str = "caption"
    image_payloads: dict = field(default_factory=dict)
    commit_message: str = "compile"
    image_count: int = 0


@dataclass
class Harness:
    rt: draft_cmd.DraftRuntime
    store: FakeCanonicalStore
    jobs: InMemoryJobQueue
    drafts: InMemoryDraftStore
    job_id: str
    #: every `CompileResult` the round produced, caught at the persistence seam.
    results: list = field(default_factory=list)

    def out(self) -> str:
        return self.rt.out.getvalue()

    def err(self) -> str:
        return self.rt.err.getvalue()

    def clear(self) -> None:
        self.rt.out.truncate(0)
        self.rt.out.seek(0)
        self.rt.err.truncate(0)
        self.rt.err.seek(0)


async def harness(
    sources: list[NormalizedSource],
    *,
    base: list[CanonicalDocument] | None = None,
    max_tool_calls: int = 0,
    commit_message: str = "compile",
) -> Harness:
    store = FakeCanonicalStore(base)
    jobs = InMemoryJobQueue()
    drafts = InMemoryDraftStore(jobs)
    job_id = await jobs.enqueue(
        USER, "compile", {"source_ids": [str(s.raw.source_id) for s in sources]}
    )
    by_id = {str(s.raw.source_id): s for s in sources}

    async def load_inputs(job):  # noqa: ANN001
        return FakeInputs(
            sources=list(sources),
            source_ids=[str(s.raw.source_id) for s in sources],
            commit_message=commit_message,
        )

    async def load_sources(ids):  # noqa: ANN001
        return [by_id[str(i)] for i in ids if str(i) in by_id]

    async def load_bounds():
        # None, not {}: "this deployment states no historical bounds" is what `run_compile`
        # is called with here, and the gate's single-span grandfather rule reads that
        # difference. An empty dict would be a claim that every past source has zero blocks.
        return None

    results: list = []

    async def persist(job, result):  # noqa: ANN001
        # The seam the real runtime hands to `persist_compile_result`; here it records the
        # result and then ends the job exactly as the runtime-less path would.
        results.append(result)
        await draft_cmd.complete_job(rt, getattr(job, "job_id"), result)

    rt = draft_cmd.DraftRuntime(
        user_id=USER,
        canonical=store,
        drafts=drafts,
        jobs=jobs,
        skill=SKILL,
        load_inputs=load_inputs,
        load_sources=load_sources,
        load_bounds=load_bounds,
        overview_budget_chars=2000,
        overview_required_after_claims=8,
        max_tool_calls=max_tool_calls,
        out=io.StringIO(),
        err=io.StringIO(),
    )
    rt.persist = persist
    return Harness(
        rt=rt, store=store, jobs=jobs, drafts=drafts, job_id=job_id, results=results
    )


# The one scripted sequence both executors run: two documents, three cited claims, finish.
CALLS = [
    (
        "create_document",
        {
            "path": PERSON,
            "frontmatter": {"type": "person", "slug": "cheng-ye"},
            "body": (
                "## 程野\n\n- 程野 是后端负责人。[cite: s01 ¶3]\n"
                "- 别名「欧文」。[cite: s01 ¶0]"
            ),
        },
    ),
    (
        "create_document",
        {
            "path": TOPIC,
            "frontmatter": {"type": "topic", "slug": "q3-launch"},
            "body": "## 承诺\n\n- 下周交付演示稿。[cite: s01 ¶4]",
        },
    ),
]


def turns(calls) -> list:
    return [[{"name": name, "args": args} for name, args in calls] + [{"name": "finish_compile"}]]


async def run_through_the_loop(sources, calls, *, base=None, raw_turns=None):
    store = FakeCanonicalStore(base)
    model = RecordingScriptedChatModel(turns=raw_turns or turns(calls))
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=sources, skill=SKILL
    )
    return store, model, result


async def run_through_the_cli(h: Harness, calls) -> int:
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK
    for name, args in calls:
        code = await draft_cmd.run_tool(h.rt, name, args)
        assert code == draft_cmd.EXIT_OK, h.err()
    return await draft_cmd.cmd_finish(h.rt)


# ───────────────────────────────────────────────────────────────────── byte equality


async def test_the_same_calls_through_both_executors_commit_the_same_files_and_events():
    sources = [source()]
    loop_store, _, loop_result = await run_through_the_loop(sources, CALLS)

    h = await harness(sources)
    assert await run_through_the_cli(h, CALLS) == draft_cmd.EXIT_OK, h.err()

    assert loop_result.status == "committed"
    assert h.store.commits == loop_store.commits
    assert h.store.messages == loop_store.messages  # the skill trailer included
    cli_result_line = h.out().strip().splitlines()[-1]
    assert cli_result_line.startswith("committed:")


async def test_a_finished_round_records_who_ran_it_and_no_usage_it_did_not_measure():
    """The job row's `executor`, from the CLI side.

    Two statements, and the second is the one that costs discipline: an agent-executed job
    names the body that typed the calls, and reports NOTHING about tokens. The harness's
    counters belong to the Owner's subscription and this process never saw them; a zero there
    would read as "this compile was free" (story 2.15, "absent rather than zero").
    """
    h = await harness([source()])
    h.rt.executor = "agent:codex"
    assert await run_through_the_cli(h, CALLS) == draft_cmd.EXIT_OK, h.err()

    record = h.jobs.completed[-1]
    assert record["ok"] is True
    assert record["executor"] == "agent:codex"
    assert record["token_usage"] in (None, {})
    assert not record["token_usage"]


async def test_the_events_the_two_executors_derive_are_identical():
    sources = [source()]
    _, _, loop_result = await run_through_the_loop(sources, CALLS)
    h = await harness(sources)
    await run_through_the_cli(h, CALLS)

    cli_result = h.results[-1]
    assert cli_result.status == loop_result.status == "committed"
    assert [asdict(e) for e in cli_result.events] == [
        asdict(e) for e in loop_result.events
    ]
    assert cli_result.files == loop_result.files
    assert cli_result.violations == loop_result.violations == []


async def test_open_prints_the_very_bytes_the_loop_puts_in_its_two_messages():
    sources = [source()]
    _, model, _ = await run_through_the_loop(sources, CALLS)
    system_message, human_message = model.seen[0][0], model.seen[0][1]

    h = await harness(sources)
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK
    printed = h.out()
    assert printed == f"{system_message.content}\n\n{human_message.content}\n"


# ───────────────────────────────────────────────────────────────────── refusal parity


def _tool_replies(model: RecordingScriptedChatModel) -> list[str]:
    """Every ToolMessage the loop was handed back, in order."""
    return [
        str(m.content)
        for messages in model.seen
        for m in messages
        if isinstance(m, ToolMessage)
    ]


#: A page that already stands in the library, whole and gate-clean — the round has not read
#: it, which is what the whole-region writes refuse a path for.
LEGACY = "memory/people/legacy.md"


def legacy_base() -> list[CanonicalDocument]:
    return [
        CanonicalDocument(
            doc_id=DocumentId("legacy01"),
            path=LEGACY,
            frontmatter={"doc_id": "legacy01", "type": "person", "slug": "legacy"},
            body="## 旧页\n\n- 旧的一条。[cite: src-old ¶0] <!-- c:bb22 -->",
        )
    ]


@pytest.mark.parametrize(
    "call",
    [
        # a path outside the contract's templates
        (
            "create_document",
            {
                "path": "notes/loose.md",
                "frontmatter": {"type": "note", "slug": "loose"},
                "body": "- 一条。[cite: s01 ¶0]",
            },
        ),
        # an anchor that does not exist
        ("edit_claim", {"path": PERSON, "anchor_id": "zzzz", "new_text": "- 改。[cite: s01 ¶0]"}),
        # machinery inside a claim's text
        (
            "append_block",
            {
                "path": PERSON,
                "heading": "承诺",
                "text": "- 一条。<!-- c:__NEW__ --> [cite: s01 ¶0]",
            },
        ),
        # the overview of a page this round has NOT read
        ("rewrite_overview", {"path": LEGACY, "definition": "他是后端负责人。 c:bb22"}),
        # an overview slot the ledger does not carry
        ("rewrite_overview", {"path": PERSON, "definition": "后端负责人。"}),
        # structured fields on a page this round has not read
        ("set_fields", {"path": LEGACY, "fields": {"status": "archived"}}),
        # a system-owned frontmatter field
        ("set_fields", {"path": PERSON, "fields": {"doc_id": "mine"}}),
        # a document that already exists
        (
            "create_document",
            {
                "path": PERSON,
                "frontmatter": {"type": "person", "slug": "cheng-ye"},
                "body": "- 又一次。[cite: s01 ¶0]",
            },
        ),
    ],
)
async def test_every_tool_refusal_reaches_the_cli_with_the_same_text(call):
    """Whatever the CLI refuses, the langchain tool refuses with the same text (ruling 2).

    The comparison is not against a string this file spells out — it is against the very
    `ToolMessage` the loop was handed back for the same call. A catalog key that changed under
    one executor and not the other would fail here.
    """
    sources = [source()]
    bad = {"name": call[0], "args": call[1]}
    first = {"name": CALLS[0][0], "args": CALLS[0][1]}
    # Two turns, so the loop is called again WITH the refusal in its history — that second
    # call is where the ToolMessage becomes readable.
    _, model, _ = await run_through_the_loop(
        sources,
        [],
        base=legacy_base(),
        raw_turns=[[first, bad], [{"name": "finish_compile"}]],
    )
    refusal = _tool_replies(model)[1]

    h = await harness(sources, base=legacy_base())
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK
    assert await draft_cmd.run_tool(h.rt, *CALLS[0]) == draft_cmd.EXIT_OK, h.err()
    h.clear()
    assert await draft_cmd.run_tool(h.rt, call[0], call[1]) == draft_cmd.EXIT_REFUSED
    assert h.err().rstrip("\n") == refusal.rstrip("\n")


async def test_a_refused_write_leaves_the_stored_draft_exactly_as_it_stood():
    sources = [source()]
    h = await harness(sources)
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    before = await h.drafts.get(USER, h.job_id)
    await draft_cmd.run_tool(
        h.rt,
        "create_document",
        {"path": "notes/loose.md", "frontmatter": {"type": "n", "slug": "l"}, "body": "- x"},
    )
    after = await h.drafts.get(USER, h.job_id)
    # The draft did not move; the round did — a refusal spends a call, as it does in the loop.
    assert after["draft"] == before["draft"]
    assert after["session"]["spent"] == before["session"]["spent"] + 1


# ─────────────────────────────────────────────────────────────────────── post-check


async def test_a_write_that_leaves_the_page_uncited_is_applied_judged_and_rolled_back():
    """The tool's argument checks pass — nothing about the text is malformed — and the gate's
    own predicate over the touched page is what refuses it (ruling 10)."""
    sources = [source()]
    h = await harness(sources)
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    before = await h.drafts.get(USER, h.job_id)
    h.clear()

    code = await draft_cmd.run_tool(
        h.rt,
        "append_block",
        {"path": PERSON, "heading": "承诺", "text": "- 他会负责发布。"},
    )
    assert code == draft_cmd.EXIT_REFUSED
    assert "[citation]" in h.err() and PERSON in h.err()
    after = await h.drafts.get(USER, h.job_id)
    assert after["draft"] == before["draft"]
    assert after["session"]["spent"] == before["session"]["spent"] + 1
    assert h.store.commits == []


async def test_a_page_that_arrived_broken_does_not_refuse_an_unrelated_write():
    """The write answers for itself and nothing else: a legacy page's standing violation is
    not the next command's fault, and a round is never wedged by a finding no command can
    repair."""
    legacy = CanonicalDocument(
        doc_id=DocumentId("legacy01"),
        path="memory/people/legacy.md",
        frontmatter={"doc_id": "legacy01", "type": "person"},  # no slug: gate 4 rejects it
        body="## 旧页\n\n- 旧的一条。[cite: src-old ¶0] <!-- c:bb22 -->",
    )
    sources = [source()]
    h = await harness(sources, base=[legacy])
    await draft_cmd.cmd_open(h.rt, h.job_id)
    assert await draft_cmd.run_tool(h.rt, *CALLS[0]) == draft_cmd.EXIT_OK, h.err()


# ───────────────────────────────────────────────────────────────────────── budget


async def test_the_round_refuses_a_call_once_its_budget_is_spent():
    sources = [source()]
    h = await harness(sources, max_tool_calls=2)
    await draft_cmd.cmd_open(h.rt, h.job_id)
    assert await draft_cmd.run_tool(h.rt, *CALLS[0]) == draft_cmd.EXIT_OK
    assert await draft_cmd.run_tool(h.rt, *CALLS[1]) == draft_cmd.EXIT_OK
    h.clear()
    code = await draft_cmd.run_tool(h.rt, "list_documents", {})
    assert code == draft_cmd.EXIT_BUDGET
    assert h.err().rstrip("\n") == prompt("compile.budget.call_refused", budget=2)


async def test_the_low_water_notice_is_appended_once_and_only_once():
    sources = [source()]
    h = await harness(sources, max_tool_calls=BUDGET_NOTICE_REMAINING + 1)
    await draft_cmd.cmd_open(h.rt, h.job_id)
    h.clear()
    await draft_cmd.run_tool(h.rt, "list_documents", {})
    first = h.out()
    assert "tool-call budget" in first
    h.clear()
    await draft_cmd.run_tool(h.rt, "list_documents", {})
    assert "tool-call budget" not in h.out()


async def test_status_reports_the_budget_the_pages_read_and_what_is_owed():
    sources = [source()]
    h = await harness(sources)
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    h.clear()
    assert await draft_cmd.cmd_status(h.rt) == draft_cmd.EXIT_OK
    text = h.out()
    assert f"budget: {first_round_budget(1) - 1} of {first_round_budget(1)} calls remain" in text
    assert PERSON in text  # created this round, therefore read
    assert prompt("compile.budget.owed_none") in text


# ────────────────────────────────────────────────────────────────────── lifecycle


def _broken_base() -> list[CanonicalDocument]:
    """A page that fails the gate and that this round never touches — the only way a CLI round
    reaches `finish` with violations at all, now that every write is post-checked."""
    return [
        CanonicalDocument(
            doc_id=DocumentId("legacy01"),
            path="memory/people/legacy.md",
            frontmatter={"doc_id": "legacy01", "type": "person"},
            body="## 旧页\n\n- 旧的一条。[cite: src-old ¶0] <!-- c:bb22 -->",
        )
    ]


async def test_open_claims_the_job_and_the_worker_no_longer_sees_it():
    h = await harness([source()])
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK
    assert await h.jobs.claim_next(USER) is None
    held = await h.jobs.get_job(USER, h.job_id)
    assert held.status == "claimed" and held.claimed_by == h.rt.draft_executor


async def test_open_on_an_unknown_job_says_so_and_claims_nothing():
    h = await harness([source()])
    assert await draft_cmd.cmd_open(h.rt, "no-such-job") == draft_cmd.EXIT_NOTHING
    assert await h.drafts.list_open(USER) == []


async def test_finish_with_violations_keeps_the_job_and_stores_a_repair_budget():
    h = await harness([source()], base=_broken_base())
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    h.clear()

    assert await draft_cmd.cmd_finish(h.rt) == draft_cmd.EXIT_GATE
    assert prompt("gate.feedback_header") in h.err()
    state = await h.drafts.get(USER, h.job_id)
    assert state is not None
    session = state["session"]
    assert session["round"] == "repair"
    assert session["budget"] > 0 and session["spent"] == 0
    assert session["violations"]
    assert (await h.jobs.get_job(USER, h.job_id)).status == "claimed"
    assert h.store.commits == []


async def test_a_second_failed_finish_aborts_the_job_and_deletes_the_draft():
    h = await harness([source()], base=_broken_base())
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    assert await draft_cmd.cmd_finish(h.rt) == draft_cmd.EXIT_GATE
    h.clear()
    assert await draft_cmd.cmd_finish(h.rt) == draft_cmd.EXIT_GATE

    assert await h.drafts.get(USER, h.job_id) is None
    assert h.store.commits == []  # canonical untouched, exactly as run_compile aborts
    assert h.jobs.completed[-1]["ok"] is False
    assert (await h.jobs.get_job(USER, h.job_id)).status == "done"


async def test_the_same_broken_library_aborts_the_langchain_loop_too():
    """Parity on the ending, not only on the writes: the gate that stops the CLI stops the
    loop, with the same violations."""
    sources = [source()]
    loop_store, _, loop_result = await run_through_the_loop(
        sources, [CALLS[0]], base=_broken_base()
    )
    assert loop_result.status == "aborted"
    assert loop_store.commits == []

    h = await harness(sources, base=_broken_base())
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    await draft_cmd.cmd_finish(h.rt)
    h.clear()
    assert await draft_cmd.cmd_finish(h.rt) == draft_cmd.EXIT_GATE
    assert h.err().rstrip("\n") == render_violations(loop_result.violations).rstrip("\n")


async def test_check_runs_the_whole_gate_without_deciding_anything():
    h = await harness([source()], base=_broken_base())
    await draft_cmd.cmd_open(h.rt, h.job_id)
    h.clear()
    assert await draft_cmd.cmd_check(h.rt) == draft_cmd.EXIT_GATE
    assert prompt("gate.feedback_header") in h.out()
    # nothing decided: the draft is still open, the job still claimed, the round unspent
    state = await h.drafts.get(USER, h.job_id)
    assert state["session"]["spent"] == 0
    assert (await h.jobs.get_job(USER, h.job_id)).status == "claimed"


async def test_abandon_releases_the_job_and_deletes_the_draft():
    h = await harness([source()])
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    h.clear()
    assert await draft_cmd.cmd_abandon(h.rt) == draft_cmd.EXIT_OK
    assert await h.drafts.get(USER, h.job_id) is None
    assert (await h.jobs.get_job(USER, h.job_id)).status == "queued"
    # …and the worker can take it: nothing was written, so nothing was lost.
    assert (await h.jobs.claim_next(USER)).job_id == h.job_id
    assert h.store.commits == []


async def test_a_command_without_an_open_draft_says_so_and_writes_nothing():
    h = await harness([source()])
    assert await draft_cmd.run_tool(h.rt, "list_documents", {}) == draft_cmd.EXIT_NOTHING
    assert "no open draft" in h.err()


async def test_a_second_open_resumes_the_round_it_does_not_start_another():
    h = await harness([source()])
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    first = h.out()
    h.clear()
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK
    # the same two surfaces again, and the round's own work still in the draft
    assert h.out().startswith(first.split("\n")[0])
    state = await h.drafts.get(USER, h.job_id)
    assert PERSON in state["draft"]["working"]
    assert state["session"]["spent"] == 1


# ────────────────────────────────────────────────────────── the component seam, by CLI


class ObjectingComponent(BaseComponent):
    """One compile tool and one gate check, so both seams can be watched through the CLI."""

    name = "fake"

    def compile_tools(self, draft, *, sources=()):  # noqa: ANN001
        def note_person(path: str, note: str) -> str:
            """What this component knows about a page (fake)."""
            return f"noted {note} on {path}"

        return [
            StructuredTool.from_function(note_person, description="Note a page (fake).")
        ]

    def gate_checks(self, docs, base_docs):  # noqa: ANN001
        return [
            Violation("fake", path, "the fake component objects to this page")
            for path, doc in docs.items()
            if "objection" in doc.body
        ]


@pytest.fixture
def objecting_component():
    register_component(ObjectingComponent())
    try:
        yield
    finally:
        reset_components()


async def test_a_component_tool_is_reachable_as_a_command_and_spends_one_call(
    objecting_component,
):
    h = await harness([source()])
    await draft_cmd.cmd_open(h.rt, h.job_id)
    h.clear()
    code = await draft_cmd.run_tool(
        h.rt, "note_person", {"path": PERSON, "note": "hello"}
    )
    assert code == draft_cmd.EXIT_OK, h.err()
    assert h.out().strip() == f"noted hello on {PERSON}"
    assert (await h.drafts.get(USER, h.job_id))["session"]["spent"] == 1


async def test_a_components_gate_check_refuses_the_write_that_broke_it(
    objecting_component,
):
    """The post-check runs every enabled component's checks over the touched page, so a
    component's rule is heard at the write and not only at `finish` (ruling 10, I7)."""
    h = await harness([source()])
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, *CALLS[0])
    before = await h.drafts.get(USER, h.job_id)
    h.clear()

    code = await draft_cmd.run_tool(
        h.rt,
        "append_block",
        {"path": PERSON, "heading": "承诺", "text": "- objection 在此。[cite: s01 ¶1]"},
    )
    assert code == draft_cmd.EXIT_REFUSED
    assert "the fake component objects" in h.err()
    after = await h.drafts.get(USER, h.job_id)
    assert after["draft"] == before["draft"]
    assert after["session"]["spent"] == before["session"]["spent"] + 1


def test_the_parser_renders_every_component_tool_as_a_subcommand(objecting_component):
    parser = build_parser(draft_cmd.component_tool_specs())
    args = parser.parse_args(
        ["draft", "note-person", "--path", PERSON, "--note", "hello"]
    )
    assert _tool_call(args, draft_cmd.component_tool_specs()) == (
        "note_person",
        {"path": PERSON, "note": "hello"},
    )


# ────────────────────────────────────────────────────────── text never rides on argv


def test_a_claims_text_arrives_through_a_file_or_stdin_never_as_an_argument(tmp_path):
    """A claim is a paragraph, and a shell quoting error is not a compile error the round
    should be spending its calls on (§5.2)."""
    body = tmp_path / "claim.md"
    body.write_text("- 程野 是后端负责人。[cite: s01 ¶3]\n", encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(
        ["draft", "append-block", PERSON, "--heading", "承诺", "--text-file", str(body)]
    )
    name, call_args = _tool_call(args)
    assert name == "append_block"
    assert call_args["text"] == "- 程野 是后端负责人。[cite: s01 ¶3]\n"

    args = parser.parse_args(["draft", "append-block", PERSON, "--heading", "承诺"])
    name, call_args = _tool_call_with_stdin(args, "- 从标准输入来的。[cite: s01 ¶0]")
    assert call_args["text"] == "- 从标准输入来的。[cite: s01 ¶0]"


def _tool_call_with_stdin(args, text: str):
    import sys as _sys

    original, _sys.stdin = _sys.stdin, io.StringIO(text)
    try:
        return _tool_call(args)
    finally:
        _sys.stdin = original


def test_the_tenant_comes_from_the_project_and_the_user_flag_overrides_it(monkeypatch):
    monkeypatch.delenv("PNEUMA_KNOWLEDGE_TENANT", raising=False)
    monkeypatch.delenv("PNEUMA_APP_USER_ID", raising=False)
    assert resolve_tenant() == DEFAULT_TENANT
    monkeypatch.setenv("PNEUMA_APP_USER_ID", "u-from-app")
    assert resolve_tenant() == "u-from-app"
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_TENANT", "u-from-project")
    assert resolve_tenant() == "u-from-project"
    assert resolve_tenant("u-typed") == "u-typed"


async def test_reading_a_page_is_what_unlocks_its_whole_region_write():
    """The read mark is the mechanism, and it survives the store round trip: the same page
    that was refused before is written after one `read-document` (ruling 6)."""
    h = await harness([source()], base=legacy_base())
    await draft_cmd.cmd_open(h.rt, h.job_id)
    refused = await draft_cmd.run_tool(
        h.rt, "rewrite_overview", {"path": LEGACY, "definition": "他是旧页。 c:bb22"}
    )
    assert refused == draft_cmd.EXIT_REFUSED

    assert await draft_cmd.run_tool(h.rt, "read_document", {"path": LEGACY}) == (
        draft_cmd.EXIT_OK
    )
    assert LEGACY in (await h.drafts.get(USER, h.job_id))["draft"]["read"]
    h.clear()
    assert await draft_cmd.run_tool(
        h.rt, "rewrite_overview", {"path": LEGACY, "definition": "他是旧页。 c:bb22"}
    ) == draft_cmd.EXIT_OK, h.err()


async def test_a_round_that_wrote_nothing_finishes_as_a_noop_and_commits_nothing():
    h = await harness([source()])
    await draft_cmd.cmd_open(h.rt, h.job_id)
    await draft_cmd.run_tool(h.rt, "list_documents", {})
    assert await draft_cmd.cmd_finish(h.rt) == draft_cmd.EXIT_OK
    assert h.results[-1].status == "noop"
    assert h.store.commits == []
    assert await h.drafts.get(USER, h.job_id) is None
    assert h.jobs.completed[-1]["ok"] is True


# ────────────────────────────────── the argument face: `-` is stdin, and a miss is a refusal


def test_a_dash_means_stdin_for_every_file_argument():
    """`pkc owner say --text-file -` is the form the generated SKILL.md prints, and it was
    opened as a literal file called `-`: `FileNotFoundError`, a raw traceback, exit 1. The
    universal convention, in the one function every write verb's text goes through."""
    assert draft_cmd.read_text_arg("-", io.StringIO("piped body")) == "piped body"
    assert draft_cmd.read_text_arg(None, io.StringIO("omitted too")) == "omitted too"
    assert draft_cmd.read_json_arg(None, "-", io.StringIO('{"a": 1}')) == {"a": 1}
    assert draft_cmd.read_json_arg(None, None, io.StringIO('{"b": 2}')) == {"b": 2}


def test_a_file_that_is_not_there_is_a_refusal_and_not_a_traceback(tmp_path):
    """Every one of these arguments is typed by a Steward mid-round. A refusal it can read
    and repair, in the shape §5.2 gives every other one — never a stack trace."""
    missing = str(tmp_path / "nope.txt")
    with pytest.raises(draft_cmd.TextArgError) as caught:
        draft_cmd.read_text_arg(missing)
    assert missing in str(caught.value) and "`-`" in str(caught.value)

    with pytest.raises(draft_cmd.TextArgError):
        draft_cmd.read_json_arg(None, missing)


def test_a_real_file_still_reads_as_a_file(tmp_path):
    path = tmp_path / "claim.txt"
    path.write_text("a paragraph\n", encoding="utf-8")
    assert draft_cmd.read_text_arg(str(path)) == "a paragraph\n"
    payload = tmp_path / "fields.json"
    payload.write_text('{"type": "project"}', encoding="utf-8")
    assert draft_cmd.read_json_arg(None, str(payload)) == {"type": "project"}


def test_malformed_json_is_the_same_kind_of_refusal(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(draft_cmd.TextArgError, match="not valid JSON"):
        draft_cmd.read_json_arg(None, str(path))
    with pytest.raises(draft_cmd.TextArgError, match="not valid JSON"):
        draft_cmd.read_json_arg("{also not json")


# ───────────────────────────────────────────────── the owner the round cannot name yet


async def test_open_says_when_the_owner_profile_is_still_the_placeholder():
    """A notice above the round, never a refusal. The acceptance run compiled the Owner into
    a person page because nothing said the profile named nobody; this is that sentence, and
    it costs the round nothing."""
    from pneuma_knowledge_service.persona_profile import PLACEHOLDER_NOTICE

    h = await harness([source()])
    h.rt.owner_is_placeholder = True
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK
    out = h.out()
    assert PLACEHOLDER_NOTICE in out
    # Above the task: the round itself is unchanged, and everything the contract says still
    # follows the notice.
    assert out.startswith(f"note: {PLACEHOLDER_NOTICE}")


async def test_a_profile_that_names_the_owner_adds_nothing_to_the_round():
    from pneuma_knowledge_service.persona_profile import PLACEHOLDER_NOTICE

    named = await harness([source()])
    assert named.rt.owner_is_placeholder is False
    assert await draft_cmd.cmd_open(named.rt, named.job_id) == draft_cmd.EXIT_OK
    quiet = named.out()
    assert PLACEHOLDER_NOTICE not in quiet

    # And the notice is the ONLY difference: the surfaces a harness is handed are the same
    # bytes either way (I5).
    noisy = await harness([source()])
    noisy.rt.owner_is_placeholder = True
    assert await draft_cmd.cmd_open(noisy.rt, noisy.job_id) == draft_cmd.EXIT_OK
    assert noisy.out().endswith(quiet)


# ──────────────────────────────────────────── the library somebody else is editing


#: What the git adapter refuses with when the working tree holds uncommitted changes this
#: framework did not make: it recovers only its own dead writer's recorded footprint and
#: refuses everything else, having written nothing (`adapters/git_canonical.py`).
DIRTY = ("data/canonical/u-draft-1/work/aurora.md",)


class DirtyCanonicalStore(FakeCanonicalStore):
    """A canonical store standing in a repository somebody is editing by hand.

    Which call raises is the point: `list` is what `pkc draft open` reads the base from, and
    `commit_patch` is what `pkc draft finish` ends on. The adapter refuses at the entry of
    every MUTATING sequence, so a real `open` would get through and a real `finish` would
    not — but a store that refuses both is what proves the door answers the same way wherever
    it comes from.
    """

    def __init__(self, docs=None, *, on: tuple[str, ...] = ("commit_patch",)) -> None:  # noqa: ANN001
        super().__init__(docs)
        self._on = on

    def _refuse(self, call: str) -> None:
        if call in self._on:
            raise CanonicalDirtyError(DIRTY)

    async def list(self, user_id, *, at=None):  # noqa: ANN001
        self._refuse("list")
        return await super().list(user_id, at=at)

    async def commit_patch(self, user_id, files, *, message):  # noqa: ANN001
        self._refuse("commit_patch")
        return await super().commit_patch(user_id, files, message=message)


async def _pkc(monkeypatch, rt, argv: list[str]) -> int:
    """One `pkc …` through the process entry point, over an already-built runtime.

    The refusal under test is the DOOR's, not one command's: `_run` catches
    `CanonicalDirtyError` once for every command that commits, so the test enters at `_run`
    rather than at a command function. Everything below it is the real thing — the parser's
    own arguments, the dispatch, the command function and this runtime. (`main` itself is
    only `asyncio.run` around this, and calling it from an async test is a nested loop.)
    """
    from pneuma_knowledge_service import wiring
    from pneuma_knowledge_service.cli import _run, build_parser, runtime as cli_runtime
    from pneuma_knowledge_service.engine import contract as engine_contract

    class _Ctx:
        async def aclose(self):
            return None

    async def _build_context(_settings, **_kw):
        return _Ctx()

    async def _build_runtime(_ctx, _user, **_kw):
        return rt

    monkeypatch.setattr(wiring, "build_context", _build_context)
    monkeypatch.setattr(cli_runtime, "build_runtime", _build_runtime)
    monkeypatch.setattr(engine_contract, "bootstrap_engine", lambda _settings: None)
    parser = build_parser()
    args = parser.parse_args(["--user", str(USER), *argv])
    return await _run(args, (), lambda: parser)


def _dirty_refusal(err: str) -> None:
    """What the Steward reads: the machine code, the paths, and no traceback."""
    assert "Traceback" not in err
    assert "canonical_dirty" in err
    assert DIRTY[0] in err
    assert "Nothing was written" in err


async def test_open_on_a_library_somebody_is_editing_is_refused_with_the_paths(
    monkeypatch, capsys, tmp_path
):
    """The base a round opens on is read from canonical, so a store that refuses the read
    refuses the round — and the Steward is told which files, not given a stack trace."""
    h = await harness([source()])
    h.rt.canonical = DirtyCanonicalStore(on=("list",))
    monkeypatch.chdir(tmp_path)
    assert await _pkc(monkeypatch, h.rt, ["draft", "open", h.job_id]) == 2
    _dirty_refusal(capsys.readouterr().err)


async def test_finish_on_a_library_somebody_is_editing_commits_nothing(
    monkeypatch, capsys, tmp_path
):
    """The real shape of it: the round opened on a clean library, the Steward wrote, and
    somebody edited the working tree meanwhile. The commit is refused, the draft is still
    there, and the job was not completed on a commit that did not happen."""
    h = await harness([source()])
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK
    for name, args in CALLS[:-1]:
        assert await draft_cmd.run_tool(h.rt, name, args) == draft_cmd.EXIT_OK, h.err()
    h.rt.canonical = DirtyCanonicalStore(h.store._docs)
    monkeypatch.chdir(tmp_path)

    assert await _pkc(monkeypatch, h.rt, ["draft", "finish"]) == 2
    _dirty_refusal(capsys.readouterr().err)
    assert await h.drafts.get(USER, h.job_id) is not None
    assert (await h.jobs.get_job(USER, h.job_id)).status == "claimed"


async def test_the_door_answers_the_same_way_whichever_command_meets_it(
    monkeypatch, capsys, tmp_path
):
    """`pkc draft abandon` writes nothing to canonical today, and the door does not depend on
    that staying true: the refusal is caught once, above the command tree, so every command —
    including ones written later — answers exit 2 with the same detail rather than a
    traceback."""
    h = await harness([source()])
    assert await draft_cmd.cmd_open(h.rt, h.job_id) == draft_cmd.EXIT_OK

    async def _dirty(_rt, **kwargs):  # noqa: ANN001
        raise CanonicalDirtyError(DIRTY)

    monkeypatch.setattr(draft_cmd, "cmd_abandon", _dirty)
    monkeypatch.chdir(tmp_path)
    assert await _pkc(monkeypatch, h.rt, ["draft", "abandon"]) == 2
    _dirty_refusal(capsys.readouterr().err)
