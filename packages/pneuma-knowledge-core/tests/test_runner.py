"""run_compile driven by a scripted fake chat model over three scenarios:
1. clean compile of two documents → commit + correct events;
2. first-round illegal citation → gate reject → repair fixes → commit;
3. still illegal after repair → abort with the canonical layer untouched.
"""

import asyncio
from datetime import datetime, timezone
from itertools import count

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from pneuma_knowledge_core.compile.anchor_ops import (
    AnchorToolError,
    anchored_blocks,
    assign_document_anchors,
)
from pneuma_knowledge_core.canonical_glance import render_outline
from pneuma_knowledge_core.compile.documents import (
    Overview,
    overview_region,
    parse_document,
    parse_overview,
    render_document,
)
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.gate import Violation
from pneuma_knowledge_core.compile.runner import (
    CompileCallTimeout,
    _build_tools,
    first_round_budget,
    repair_round_budget,
    run_compile,
)
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.components import (
    BaseComponent,
    register_component,
    reset_components,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId, SourceId, extract_anchors
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource, StructureMap
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_core.skill import load_skill_base

_ids = count()


def tc(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call-{next(_ids)}", "type": "tool_call"}


def bad_tc(name: str, *, args: str = "{\"path\": ", error: str = "unterminated object") -> dict:
    """A call whose arguments never parsed as JSON.

    langchain files these under `AIMessage.invalid_tool_calls` instead of `tool_calls`, but
    the assistant message still carries the function call on the wire — which is why the
    runner owes it a result all the same. Scripted turns mix these freely with `tc(...)`;
    the fake splits them onto the two fields the way a provider adapter does.
    """
    return {
        "name": name,
        "args": args,
        "id": f"call-{next(_ids)}",
        "error": error,
        "type": "invalid_tool_call",
    }


def _assert_tool_calls_are_all_answered(messages) -> None:
    """Every tool call an AIMessage declared has a ToolMessage answering it.

    A provider REJECTS a history that carries fewer results than the AIMessage before it
    declared, so a round that returns mid-batch without answering the rest poisons the NEXT
    `ainvoke` — and the repair round is exactly that next call. Scripted models are happy to
    ignore the pairing, which is why this fake refuses to: the invariant is checked here so a
    regression fails in the suite rather than in production.
    """
    answered = {
        m.tool_call_id for m in messages if isinstance(m, ToolMessage)
    }
    for message in messages:
        # `invalid_tool_calls` counts: the provider adapter puts an unparseable call back on
        # the wire as a function call like any other, so an unanswered one is the same 400.
        declared = list(getattr(message, "tool_calls", None) or []) + list(
            getattr(message, "invalid_tool_calls", None) or []
        )
        for call in declared:
            assert call["id"] in answered, (
                f"tool call {call['name']} ({call['id']}) reached the model with no "
                "ToolMessage answering it"
            )


class ScriptedChatModel(BaseChatModel):
    turns: list = []
    _cursor: int = PrivateAttr(default=0)
    # Every message list this model was ever handed, so a test can assert on what the
    # runner actually put in front of it (the budget notice, the gate feedback).
    _seen: list = PrivateAttr(default_factory=list)

    @property
    def seen(self) -> list:
        return self._seen

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        _assert_tool_calls_are_all_answered(messages)
        self._seen.append(list(messages))
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if self._cursor < len(self.turns):
            calls = self.turns[self._cursor]
            self._cursor += 1
            msg = AIMessage(
                content="",
                tool_calls=[c for c in calls if c["type"] == "tool_call"],
                invalid_tool_calls=[c for c in calls if c["type"] == "invalid_tool_call"],
                usage_metadata=usage,
            )
        else:
            msg = AIMessage(content="done", usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # Explicit async face — do not lean on BaseChatModel's thread-pool _agenerate default.
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class FakeCanonicalStore:
    """In-memory CanonicalStore recording commits (asserts on git-commit presence)."""

    def __init__(self, docs: list[CanonicalDocument] | None = None) -> None:
        self._docs = list(docs or [])
        self.commits: list[dict[str, str]] = []

    async def list(self, user_id, *, at: SnapshotRef | None = None):
        return list(self._docs)

    async def read(self, user_id, document_id, *, at: SnapshotRef | None = None):
        return next((d for d in self._docs if d.doc_id == document_id), None)

    async def commit_patch(self, user_id, files: dict[str, str], *, message: str):
        self.commits.append(dict(files))
        new_docs: list[CanonicalDocument] = []
        for path, text in files.items():
            fm, body = parse_document(text)
            new_docs.append(
                CanonicalDocument(
                    doc_id=DocumentId(str(fm.get("doc_id", ""))),
                    path=path,
                    frontmatter=fm,
                    body=body,
                )
            )
        self._docs = new_docs
        return SnapshotRef(ref=f"commit-{len(self.commits)}")

    def snapshots(self, user_id):
        return [SnapshotRef(ref=f"commit-{i + 1}") for i in range(len(self.commits))]

    def tag(self, user_id, ref, label):
        return SnapshotRef(ref=label, label=label)


def _source(source_id: str, n_blocks: int) -> NormalizedSource:
    return NormalizedSource(
        raw=RawSource(
            source_id=SourceId(source_id),
            user_id=UserId("u-1"),
            kind="conversation",
            title="会议",
            mime="text/plain",
            checksum=source_id,
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=i, text=f"b{i}") for i in range(n_blocks)],
        structure=StructureMap(),
    )


USER = UserId("u-compile-1")
SKILL = load_skill_base("v1")


async def test_scenario_1_clean_compile_two_documents():
    store = FakeCanonicalStore()
    sources = [_source("src-01", 5)]
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path="memory/people/cheng-ye.md",
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶3]\n- 别名「欧文」。[cite: src-01 ¶0]",
                ),
                tc(
                    "create_document",
                    path="memory/topics/q3-launch.md",
                    frontmatter={"type": "topic", "slug": "q3-launch"},
                    body="## 承诺\n\n- 下周交付演示稿。[cite: src-01 ¶4]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=sources, skill=SKILL
    )
    assert result.status == "committed"
    assert len(store.commits) == 1
    assert result.snapshot is not None
    assert set(result.files) == {"memory/people/cheng-ye.md", "memory/topics/q3-launch.md"}
    # Three claims created → three claim_added events.
    assert len(result.events) == 3
    assert all(e.type == "claim_added" for e in result.events)
    assert result.token_usage["total_tokens"] > 0
    assert result.rounds == 1


async def test_scenario_2_illegal_citation_then_repair_passes():
    store = FakeCanonicalStore()
    sources = [_source("src-01", 5)]
    path = "memory/people/cheng-ye.md"
    bad_body = "- 程野 是后端负责人。[cite: src-99 ¶3]"
    # The anchor is system-assigned deterministically on create; the repair edit must
    # target that exact anchor (a real model would read_document to learn it).
    anchor = extract_anchors(assign_document_anchors(bad_body, path))[0]
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body=bad_body,
                ),
                tc("finish_compile"),
            ],
            [
                tc(
                    "edit_claim",
                    path=path,
                    anchor_id=anchor,
                    new_text="- 程野 是后端负责人。[cite: src-01 ¶3]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=sources, skill=SKILL
    )
    assert result.status == "committed"
    assert result.rounds == 2
    assert len(store.commits) == 1
    assert result.violations == []
    assert "src-99" not in result.files[path]
    assert len(result.events) == 1 and result.events[0].type == "claim_added"


async def test_scenario_3_still_illegal_after_repair_aborts_with_zero_canonical_change():
    store = FakeCanonicalStore()
    sources = [_source("src-01", 5)]
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path="memory/people/cheng-ye.md",
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="- 程野 是后端负责人。[cite: src-99 ¶3]",
                ),
                tc("finish_compile"),
            ],
            [
                tc(
                    "create_document",
                    path="memory/people/mei.md",
                    frontmatter={"type": "person", "slug": "mei"},
                    body="- Mei 仍引用未供给来源。[cite: src-77 ¶1]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=sources, skill=SKILL
    )
    assert result.status == "aborted"
    assert result.violations  # citation violations remain
    assert result.events == []
    assert result.snapshot is None
    # Canonical layer untouched: no commit was made (git log would show no new commit).
    assert store.commits == []
    assert await store.list(USER) == []


async def test_scenario_1_editing_existing_base_document_preserves_anchor():
    base = CanonicalDocument(
        doc_id=DocumentId("abc123"),
        path="memory/people/cheng-ye.md",
        frontmatter={"doc_id": "abc123", "type": "person", "slug": "cheng-ye"},
        body="## 程野\n\n- 程野 是后端负责人。[cite: src-00 ¶0] <!-- c:aa11 -->",
    )
    store = FakeCanonicalStore([base])
    sources = [_source("src-05", 5)]
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "edit_claim",
                    path="memory/people/cheng-ye.md",
                    anchor_id="aa11",
                    new_text="- 程野 转任架构师。[cite: src-05 ¶2]",
                ),
                tc(
                    "append_block",
                    path="memory/people/cheng-ye.md",
                    heading="程野",
                    text="- 程野 下周休假。[cite: src-05 ¶3]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=sources, skill=SKILL
    )
    assert result.status == "committed"
    types = sorted(e.type for e in result.events)
    assert types == ["claim_added", "claim_revised"]
    # aa11 preserved through the edit.
    assert "c:aa11" in result.files["memory/people/cheng-ye.md"]


# ------------------------------------------------- compiling a rolled-over subject


def _rolled_over_base() -> list[CanonicalDocument]:
    """An active page plus one frozen history volume, as a compile after a groom sees them."""
    active_path = "work/products/aurora-planner.md"
    active = CanonicalDocument(
        doc_id=DocumentId("d-aurora"),
        path=active_path,
        frontmatter={"doc_id": "d-aurora", "type": "product", "slug": "aurora-planner"},
        body=(
            "# Aurora planner\n\n## Delivery\n\n"
            "- Sprint 9: checklist advanced. [cite: src-00 ¶0] <!-- c:aaaa1111 -->\n"
        ),
    )
    volume = CanonicalDocument(
        doc_id=DocumentId("d-aurora-a01"),
        path="work/products/aurora-planner/a01.md",
        frontmatter={
            "doc_id": "d-aurora-a01",
            "type": "product",
            "slug": "a01",
            "archived_from": active_path,
            "rollover_volume": "01",
        },
        body=(
            "# Aurora planner\n\n## Delivery\n\n"
            "- Sprint 1: checklist started. [cite: src-00 ¶0] <!-- c:bbbb2222 -->\n"
        ),
    )
    return [active, volume]


def test_the_compile_tool_face_marks_a_volume_read_only_and_refuses_writes_early():
    """The two working-set surfaces a compile model actually sees: read_document says the
    volume is frozen (while staying fully readable), and the write tools refuse a volume
    path with the active-page redirect instead of letting the attempt run to the gate."""
    base = _rolled_over_base()
    active_path, volume_path = base[0].path, base[1].path
    draft = PatchDraft.from_canonical(base, SKILL.path_templates)
    tools = {t.name: t for t in _build_tools(draft)}

    read = tools["read_document"].func(path=volume_path)
    assert read.startswith("(this document is a frozen archive volume of")
    assert f"`{active_path}`" in read
    assert "Sprint 1: checklist started." in read  # deep-reading history stays allowed
    # an ordinary document reads without any banner
    assert tools["read_document"].func(path=active_path).startswith("---")

    with pytest.raises(AnchorToolError) as err:
        tools["edit_claim"].func(path=volume_path, anchor_id="bbbb2222", new_text="- x")
    assert "frozen history volume" in str(err.value)
    assert f"active page: use edit_claim / append_block on `{active_path}`" in str(err.value)
    with pytest.raises(AnchorToolError):
        tools["append_block"].func(path=volume_path, heading="Delivery", text="- x")
    assert not draft.is_dirty()


async def test_a_compile_on_a_rolled_over_subject_lands_on_the_active_page_not_the_volume():
    """The live trap, end to end: this round's material updates a subject whose history was
    rolled over. The first attempt path-addresses the frozen volume and is refused by the
    TOOL inside the same round; the compile then lands the claim on the active page and
    commits, with the volume byte-identical."""
    base = _rolled_over_base()
    store = FakeCanonicalStore(base)
    sources = [_source("src-01", 5)]
    active_path, volume_path = base[0].path, base[1].path
    volume_file_before = render_document(base[1].frontmatter, base[1].body)
    model = ScriptedChatModel(
        turns=[
            # the trap: the model tries to update the archived claim inside the volume
            [
                tc(
                    "edit_claim",
                    path=volume_path,
                    anchor_id="bbbb2222",
                    new_text="- Sprint 1: shipped after all. [cite: src-01 ¶1]",
                ),
            ],
            # the refusal named the active page; the model redirects there and finishes
            [
                tc(
                    "append_block",
                    path=active_path,
                    heading="Delivery",
                    text="- Sprint 10: kickoff confirmed. [cite: src-01 ¶1]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=sources, skill=SKILL
    )
    assert result.status == "committed"
    assert result.rounds == 1  # caught at the tool face, not spent on a gate repair round
    assert result.violations == []
    # the volume is byte-identical to what the groom froze...
    assert result.files[volume_path] == volume_file_before
    # ...and the new claim landed on the active page
    assert "Sprint 10: kickoff confirmed." in result.files[active_path]
    assert len(result.events) == 1 and result.events[0].type == "claim_added"


async def test_a_compile_supersedes_a_paragraph_claim_and_commits():
    """Paragraph-style claims (no bullet) supersede exactly like list items: the successor
    is its own block, the gate passes in one round and the commit carries a claim_superseded
    event. Before the blank-line separation this run aborted with
    `supersession_target_missing` — predecessor and successor were one paragraph."""
    path = "memory/people/caroline.md"
    body = "## 生活\n\nCaroline 单身。[cite: src-01 ¶1]"
    doc_body = assign_document_anchors(body, path)
    store = FakeCanonicalStore(
        [
            CanonicalDocument(
                doc_id=DocumentId("d-caroline"),
                path=path,
                frontmatter={"doc_id": "d-caroline", "type": "person", "slug": "caroline"},
                body=doc_body,
            )
        ]
    )
    anchor = extract_anchors(doc_body)[0]
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "supersede_claim",
                    path=path,
                    anchor_id=anchor,
                    new_text="Caroline 正在与 Jon 交往。[cite: src-01 ¶3]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[_source("src-01", 5)], skill=SKILL
    )
    assert result.violations == []
    assert result.status == "committed" and result.rounds == 1
    assert len(result.events) == 1
    assert result.events[0].type == "claim_superseded"
    assert result.events[0].supersedes == anchor
    committed = result.files[path]
    assert f"Caroline 单身。[cite: src-01 ¶1] <!-- c:{anchor} -->\n\n" in committed
    assert anchored_blocks(committed) == [
        f"Caroline 单身。[cite: src-01 ¶1] <!-- c:{anchor} -->",
        f"Caroline 正在与 Jon 交往。[cite: src-01 ¶3] <!-- c:{result.events[0].anchor} --> "
        f"<!-- supersedes: c:{anchor} -->",
    ]


async def test_a_claim_citing_an_owner_dialogue_turn_passes_the_gate():
    """The ruling, mechanically: the owner corrects the library by SPEAKING, and the
    correction reaches canonical the ordinary way — a `supersede_claim` whose successor
    cites a turn of the statement, through the same gate as any other citation. Nothing
    here is special-cased: `[cite: <dialogue-sid> ¶2]` is just a source id and a block.
    """
    dialogue = normalize_source_contract(
        parse_source_contract(
            {
                "schema": "pneuma.source.owner-dialogue/v1",
                "provider": "console",
                "dialogue_id": "dlg-1",
                "owner_id": "app-owner-7",
                "turns": [
                    {
                        "turn_id": "t1",
                        "role": "owner",
                        "said_at": "2026-08-31T09:00:00+08:00",
                        "text": "关于 Aurora 的交付日期。",
                    },
                    {
                        "turn_id": "t2",
                        "role": "steward",
                        "said_at": "2026-08-31T09:00:20+08:00",
                        "text": "库里记的是 2026-09-15。",
                    },
                    {
                        "turn_id": "t3",
                        "role": "owner",
                        "said_at": "2026-08-31T09:00:40+08:00",
                        "text": "改到 2026-09-30 了，评审那天定的日子已经不作数。",
                    },
                ],
            }
        ),
        USER,
        imported_at=datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc),
    )[0]
    sid = str(dialogue.raw.source_id)
    path = "work/products/aurora.md"
    body = "## 交付\n\n- Aurora 交付日期为 2026-09-15。[cite: src-01 ¶1]"
    doc_body = assign_document_anchors(body, path)
    anchor = extract_anchors(doc_body)[0]
    store = FakeCanonicalStore(
        [
            CanonicalDocument(
                doc_id=DocumentId("d-aurora"),
                path=path,
                frontmatter={"doc_id": "d-aurora", "type": "product", "slug": "aurora"},
                body=doc_body,
            )
        ]
    )
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "supersede_claim",
                    path=path,
                    anchor_id=anchor,
                    new_text=f"Aurora 交付日期改为 2026-09-30。[cite: {sid} ¶2]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 5), dialogue],
        skill=SKILL,
    )
    assert result.violations == []
    assert result.status == "committed" and result.rounds == 1
    assert [e.type for e in result.events] == ["claim_superseded"]
    assert result.events[0].supersedes == anchor
    committed = result.files[path]
    # The old claim stays byte-for-byte; the successor names it and cites the statement.
    assert f"- Aurora 交付日期为 2026-09-15。[cite: src-01 ¶1] <!-- c:{anchor} -->" in committed
    assert f"[cite: {sid} ¶2] <!-- c:{result.events[0].anchor} -->" in committed


async def test_a_claim_citing_a_turn_the_dialogue_does_not_have_is_rejected():
    """The gate is not relaxed for an owner statement: a span past the last turn is an
    illegal citation like any other, and the compile aborts with canonical untouched."""
    dialogue = normalize_source_contract(
        parse_source_contract(
            {
                "schema": "pneuma.source.owner-dialogue/v1",
                "provider": "console",
                "dialogue_id": "dlg-2",
                "owner_id": "app-owner-7",
                "turns": [
                    {
                        "turn_id": "t1",
                        "role": "owner",
                        "said_at": "2026-08-31T09:00:00+08:00",
                        "text": "交付日期改到 2026-09-30。",
                    }
                ],
            }
        ),
        USER,
        imported_at=datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc),
    )[0]
    sid = str(dialogue.raw.source_id)
    store = FakeCanonicalStore()
    call = tc(
        "create_document",
        path="work/products/aurora.md",
        frontmatter={"type": "product", "slug": "aurora"},
        body=f"## 交付\n\n- Aurora 交付日期为 2026-09-30。[cite: {sid} ¶4]",
    )
    model = ScriptedChatModel(turns=[[call, tc("finish_compile")], [tc("finish_compile")]])
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[dialogue], skill=SKILL
    )
    assert result.status == "aborted"
    assert store.commits == []
    assert [v.kind for v in result.violations] == ["citation"]
    assert "¶4" in result.violations[0].detail


class HangingChatModel(ScriptedChatModel):
    """A provider connection that never answers (the 23-minute hang, in miniature)."""

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        await asyncio.sleep(30)
        raise AssertionError("unreachable: the call must be abandoned first")


async def test_a_hung_model_call_times_out_and_leaves_canonical_untouched():
    store = FakeCanonicalStore()
    with pytest.raises(CompileCallTimeout) as err:
        await run_compile(
            user_id=USER,
            model=HangingChatModel(),
            store=store,
            sources=[_source("src-01", 5)],
            skill=SKILL,
            call_timeout=0.05,
        )
    # The message is what the worker records as the job's failure reason.
    assert str(err.value) == "compile model call timed out after 0.05s"
    assert store.commits == []


async def test_call_timeout_zero_means_unbounded():
    """0 is the documented "no timeout" value — it must not be handed to wait_for as a
    zero-second budget."""
    store = FakeCanonicalStore()
    model = ScriptedChatModel(turns=[[tc("finish_compile")]])
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 5)],
        skill=SKILL,
        call_timeout=0,
    )
    assert result.status == "noop"


# ------------------------------------------------------------------ the component prepare hook
# A component's compile faces (tools, outline tails, source preambles) are all SYNC, and a
# compile runs in a process that indexed nothing: whatever a component mirrors in memory is
# cold. `run_compile` awaits `prepare` before rendering any of them — that is the only reason
# a library-wide seam says anything at all in the shipped deployment shape.


class _RecordingComponent(BaseComponent):
    name = "recorder"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.prepared: list[str] = []

    async def prepare(self, user_id: str) -> None:
        self.prepared.append(user_id)
        self.events.append("prepare")

    def compile_tools(self, draft, *, sources=()):
        self.events.append("tools")
        return []

    def source_preamble(self, source):
        self.events.append("preamble")
        return None


class _RaisingPrepare(BaseComponent):
    name = "raiser"

    def __init__(self) -> None:
        self.called = 0

    async def prepare(self, user_id: str) -> None:
        self.called += 1
        raise RuntimeError("projection unreachable")


@pytest.fixture
def _registry():
    reset_components()
    yield
    reset_components()


async def test_components_are_prepared_once_before_any_sync_face(_registry):
    events: list[str] = []
    recorder = _RecordingComponent(events)
    register_component(recorder)
    store = FakeCanonicalStore()
    model = ScriptedChatModel(turns=[[tc("finish_compile")]])

    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[_source("src-01", 3)], skill=SKILL
    )

    assert result.status == "noop"
    assert recorder.prepared == [str(USER)]
    # Prepared first, and only then are the sync faces rendered.
    assert events[0] == "prepare"
    assert "prepare" not in events[1:]
    assert set(events[1:]) == {"tools", "preamble"}


async def test_a_component_whose_prepare_raises_does_not_fail_the_compile(_registry):
    raiser = _RaisingPrepare()
    events: list[str] = []
    recorder = _RecordingComponent(events)
    register_component(raiser)
    register_component(recorder)
    store = FakeCanonicalStore()
    model = ScriptedChatModel(turns=[[tc("finish_compile")]])

    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[_source("src-01", 3)], skill=SKILL
    )

    assert result.status == "noop"
    assert raiser.called == 1
    # One component's failure never costs the next one its preparation.
    assert recorder.prepared == [str(USER)]


async def test_a_compile_rewrites_an_overview_and_commits_one_overview_event():
    """The overview end to end: the model writes the region, the gate accepts it, the commit
    carries ONE `overview_rewritten` event (not four claims added), and the ledger below is
    byte-for-byte what it was."""
    path = "memory/people/lena.md"
    body = "## Role\n\nLena runs procurement. [cite: src-01 ¶1]"
    doc_body = assign_document_anchors(body, path)
    anchor = extract_anchors(doc_body)[0]
    store = FakeCanonicalStore(
        [
            CanonicalDocument(
                doc_id=DocumentId("d-lena"),
                path=path,
                frontmatter={"doc_id": "d-lena", "type": "person", "slug": "lena"},
                body=doc_body,
            )
        ]
    )
    model = ScriptedChatModel(
        turns=[
            [
                # The rewrite is a judgement over the picture that already stands there, so
                # the loop has to look at it first — the write refuses until it has.
                tc("read_document", path=path),
                tc(
                    "rewrite_overview",
                    path=path,
                    definition=f"Lena is the owner's procurement lead. c:{anchor}",
                    summary=f"She has run procurement throughout the record. c:{anchor}",
                    fields={"employer": "Northwind"},
                ),
                tc("finish_compile"),
            ]
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[_source("src-01", 5)], skill=SKILL
    )
    assert result.status == "committed", result.violations
    assert [e.type for e in result.events] == ["overview_rewritten"]
    assert result.events[0].path == path
    _, new_body = parse_document(result.files[path])
    overview, ledger = parse_overview(new_body)
    assert overview is not None
    assert overview.definition.startswith("Lena is the owner's procurement lead.")
    assert ledger == doc_body
    # the structured fields ride the same call — one picture, one authority
    assert parse_document(result.files[path])[0]["employer"] == "Northwind"


async def test_the_loop_hears_the_unread_refusal_and_recovers_in_the_same_compile():
    """The refusal is a TOOL RESULT, not an abort: the model that rewrote a picture it had
    not looked at reads the document and writes it in the same round."""
    path = "memory/people/lena.md"
    doc_body = assign_document_anchors(
        "## Role\n\nLena runs procurement. [cite: src-01 ¶1]", path
    )
    anchor = extract_anchors(doc_body)[0]
    store = FakeCanonicalStore(
        [
            CanonicalDocument(
                doc_id=DocumentId("d-lena"),
                path=path,
                frontmatter={"doc_id": "d-lena", "type": "person", "slug": "lena"},
                body=doc_body,
            )
        ]
    )
    seen: list[str] = []

    class Recording(ScriptedChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
            seen.extend(str(getattr(m, "content", "")) for m in messages)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = Recording(
        turns=[
            [tc("rewrite_overview", path=path, definition=f"Lena leads procurement. c:{anchor}")],
            [
                tc("read_document", path=path),
                tc("rewrite_overview", path=path, definition=f"Lena leads procurement. c:{anchor}"),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[_source("src-01", 5)], skill=SKILL
    )
    assert any("was not read in this compile" in text for text in seen)
    assert result.status == "committed", result.violations
    assert [e.type for e in result.events] == ["overview_rewritten"]


async def test_the_loop_hears_the_missing_overview_refusal_before_the_gate_round():
    """A page that reached the threshold this round cannot be finished without a head.

    The refusal is a TOOL RESULT at `finish_compile`, not a gate violation: the model still
    holds the material, one `rewrite_overview` settles it, and the round's single repair
    round is still unspent (`rounds == 1`). The gate re-states the same line for a draft
    that never calls finish at all.
    """
    path = "memory/people/lena.md"
    body = "## Record\n\n" + "\n".join(
        f"- Lena signed off supplier lot {i}. [cite: src-01 ¶{i % 5}]" for i in range(8)
    )
    anchor = extract_anchors(assign_document_anchors(body, path))[0]
    store = FakeCanonicalStore()
    seen: list[str] = []

    class Recording(ScriptedChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
            seen.extend(str(getattr(m, "content", "")) for m in messages)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = Recording(
        turns=[
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "lena"},
                    body=body,
                ),
                tc("finish_compile"),
            ],
            [
                tc(
                    "rewrite_overview",
                    path=path,
                    definition=f"Lena signs off supplier lots. c:{anchor}",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[_source("src-01", 5)], skill=SKILL
    )
    assert any("8 ledger claims and no overview" in text for text in seen)
    assert result.status == "committed", result.violations
    assert result.rounds == 1
    assert len(store.commits) == 1
    overview, _ = parse_overview(parse_document(result.files[path])[1])
    assert overview is not None and overview.definition.startswith("Lena signs off")


async def test_the_threshold_switched_off_lets_the_same_round_finish_headless():
    """The knob is mechanical all the way down: at 0 the finish face says nothing and the
    gate judges nothing — a deployment that does not want the floor does not have one."""
    path = "memory/people/lena.md"
    body = "## Record\n\n" + "\n".join(
        f"- Lena signed off supplier lot {i}. [cite: src-01 ¶{i % 5}]" for i in range(8)
    )
    store = FakeCanonicalStore()
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "lena"},
                    body=body,
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 5)],
        skill=SKILL,
        overview_required_after_claims=0,
    )
    assert result.status == "committed", result.violations
    assert parse_overview(parse_document(result.files[path])[1])[0] is None


async def test_a_compile_that_does_not_touch_the_overview_leaves_the_region_byte_identical():
    """The other half of "rewrite it only when the picture changed": a round that appends a
    claim and never calls the tool leaves the head exactly as it stood."""
    path = "memory/people/lena.md"
    base_body = assign_document_anchors(
        "## Role\n\nLena runs procurement. [cite: src-01 ¶1]", path
    )
    anchor = extract_anchors(base_body)[0]
    with_region = PatchDraft.from_canonical(
        [
            CanonicalDocument(
                doc_id=DocumentId("d-lena"),
                path=path,
                frontmatter={"doc_id": "d-lena", "type": "person", "slug": "lena"},
                body=base_body,
            )
        ],
        SKILL.path_templates,
    )
    with_region.mark_read(path)
    with_region.rewrite_overview(
        path, Overview(definition=f"Lena is the procurement lead. c:{anchor}")
    )
    seeded = with_region.read(path).body
    region_before = overview_region(seeded)

    store = FakeCanonicalStore(
        [
            CanonicalDocument(
                doc_id=DocumentId("d-lena"),
                path=path,
                frontmatter={"doc_id": "d-lena", "type": "person", "slug": "lena"},
                body=seeded,
            )
        ]
    )
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "append_block",
                    path=path,
                    heading="Role",
                    text="- She signed off the Q3 supplier list. [cite: src-01 ¶2]",
                ),
                tc("finish_compile"),
            ]
        ]
    )
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[_source("src-01", 5)], skill=SKILL
    )
    assert result.status == "committed", result.violations
    _, new_body = parse_document(result.files[path])
    assert overview_region(new_body) == region_before
    assert [e.type for e in result.events] == ["claim_added"]


def test_the_outline_shows_a_documents_definition_line():
    path = "memory/people/lena.md"
    base_body = assign_document_anchors(
        "# Lena\n\n## Role\n\nLena runs procurement. [cite: src-01 ¶1]", path
    )
    anchor = extract_anchors(base_body)[0]
    draft = PatchDraft.from_canonical(
        [
            CanonicalDocument(
                doc_id=DocumentId("d-lena"),
                path=path,
                frontmatter={"doc_id": "d-lena", "type": "person", "slug": "lena"},
                body=base_body,
            )
        ],
        SKILL.path_templates,
    )
    draft.mark_read(path)
    draft.rewrite_overview(
        path, Overview(definition=f"Lena is the owner's procurement lead. c:{anchor}")
    )
    doc = draft.read(path)
    outline = render_outline(
        [
            CanonicalDocument(
                doc_id=doc.doc_id, path=path, frontmatter=doc.frontmatter, body=doc.body
            )
        ]
    )
    assert outline[1] == "    definition: Lena is the owner's procurement lead."


# ═══════════════════════════════════════════════ the round's tool-call budget
#
# The defect these pin, from a real 88-day rebuild: ONE counter shared by both rounds, and a
# fixed ceiling of 40 that does not describe a 36-source day group. The first round was cut
# at 40 mid-append, the gate reported `overview_required`, and the repair round's loop —
# `while tool_calls < MAX_TOOL_CALLS` with the counter already at 40 — never entered. 14 day
# groups (156 sources) never reached the library.


def _budget_notices(messages) -> list[str]:
    """The budget notices in one transcript, in order."""
    head = prompt("compile.budget.notice", remaining=0, budget=0, owed="").split("{")[0]
    head = head.split(":")[0]
    return [
        m.content
        for m in messages
        if isinstance(m, HumanMessage) and str(m.content).startswith(head)
    ]


class _AliasComponent(BaseComponent):
    """A component shaped like `people`'s `alias_undecided`: a term the round has neither
    recorded nor declined is a write-time refusal, and the fix is one `set_fields` call."""

    name = "fake-alias"
    term = "欧文"

    def gate_checks(self, docs, base_docs):  # noqa: ARG002
        return [
            Violation(
                "alias_undecided",
                path,
                f'the term "{self.term}" is neither recorded in aliases nor declined',
            )
            for path, doc in docs.items()
            if self.term not in (doc.frontmatter.get("aliases") or [])
        ]


def test_the_default_budget_scales_with_the_supplied_sources():
    # A first round must be able to read every source and append at least twice per source.
    assert first_round_budget(1) == 40  # the floor still holds for a small job
    assert first_round_budget(13) == 40
    assert first_round_budget(14) == 42
    assert first_round_budget(36) == 108  # the day group that used to be cut at 40
    assert first_round_budget(0) == 40


def test_an_explicit_knob_is_the_absolute_number_not_a_minimum():
    # Above the derived value…
    assert first_round_budget(2, 200) == 200
    # …and below it: a deployment that says 25 gets 25, even for 36 sources.
    assert first_round_budget(36, 25) == 25


def test_the_repair_round_gets_a_fresh_allowance_bounded_by_the_round_budget():
    assert repair_round_budget(1, 108) == 12  # floor
    assert repair_round_budget(9, 108) == 27  # 3 per violation
    assert repair_round_budget(9, 20) == 20  # never above the round's own ceiling


async def test_a_first_round_that_spends_its_whole_budget_is_still_repairable():
    """The mutation this pins: with one counter shared across rounds, the repair round's
    loop never entered and this compile aborted with the library untouched."""
    store = FakeCanonicalStore()
    sources = [_source("src-01", 6)]
    path = "memory/people/cheng-ye.md"
    model = ScriptedChatModel(
        turns=[
            # Six calls, no finish_compile: the round is CUT, not ended.
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶0]",
                ),
                *[
                    tc("append_block", path=path, heading="记录", text=f"- 第 {i} 条记录。[cite: src-01 ¶{i}]")
                    for i in range(1, 6)
                ],
            ],
            # The repair round — impossible before this fix.
            [
                tc(
                    "rewrite_overview",
                    path=path,
                    definition="程野 是后端负责人。[cite: src-01 ¶0]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=sources,
        skill=SKILL,
        max_tool_calls=6,
        overview_required_after_claims=2,
    )

    assert result.status == "committed", result.violations
    assert result.rounds == 2
    assert result.tool_calls == 8  # 6 spent in round one, 2 more in the fresh allowance
    assert len(store.commits) == 1


async def test_the_repair_message_states_that_the_previous_round_was_cut_off():
    store = FakeCanonicalStore()
    path = "memory/people/cheng-ye.md"
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶0]",
                ),
                *[
                    tc("append_block", path=path, heading="记录", text=f"- 第 {i} 条记录。[cite: src-01 ¶{i}]")
                    for i in range(1, 6)
                ],
            ],
            [
                tc(
                    "rewrite_overview",
                    path=path,
                    definition="程野 是后端负责人。[cite: src-01 ¶0]",
                ),
                tc("finish_compile"),
            ],
        ]
    )
    await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 6)],
        skill=SKILL,
        max_tool_calls=6,
        overview_required_after_claims=2,
    )

    feedback = [
        str(m.content)
        for m in model.seen[-1]
        if isinstance(m, HumanMessage) and prompt("gate.feedback_header") in str(m.content)
    ]
    assert len(feedback) == 1
    # The cut-off line comes FIRST, above the ordinary rejection header.
    assert feedback[0].startswith(
        prompt("gate.previous_round_cut_off", spent=6, budget=6)
    )


async def test_a_round_that_ends_on_its_own_is_not_reported_as_cut_off():
    """`finish_compile` landing on the last call of the budget still ended the round."""
    store = FakeCanonicalStore()
    path = "memory/people/cheng-ye.md"
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="- 程野 是后端负责人。[cite: src-99 ¶0]",
                ),
                tc("finish_compile"),
            ],
            [tc("finish_compile")],
        ]
    )
    await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 6)],
        skill=SKILL,
        max_tool_calls=2,
    )
    feedback = [
        str(m.content)
        for m in model.seen[-1]
        if isinstance(m, HumanMessage) and prompt("gate.feedback_header") in str(m.content)
    ]
    assert len(feedback) == 1
    assert feedback[0].startswith(prompt("gate.feedback_header"))


async def test_the_budget_notice_appears_once_at_the_low_water_mark_and_names_what_is_owed(
    _registry,
):
    register_component(_AliasComponent())
    store = FakeCanonicalStore()
    path = "memory/people/cheng-ye.md"
    model = ScriptedChatModel(
        turns=[
            # 1 call → 7 left: above the mark, no notice.
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="## 程野\n\n- 程野 是后端负责人。[cite: src-01 ¶0]\n- 欧文 也是他。[cite: src-01 ¶1]",
                )
            ],
            # 1 more → 6 left: the notice fires here, exactly once.
            [tc("list_documents")],
            # 1 more → 5 left: already noticed this round, no second notice.
            [tc("list_documents")],
            # Round one ends on its own; the gate then hands the round its two violations.
            [],
            # The repair round: fix both, finish before the mark is reached.
            [
                tc(
                    "rewrite_overview",
                    path=path,
                    definition="程野 是后端负责人。[cite: src-01 ¶0]",
                ),
                tc("set_fields", path=path, fields={"aliases": ["欧文"]}),
                tc("finish_compile"),
            ],
        ]
    )
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 6)],
        skill=SKILL,
        max_tool_calls=8,
        overview_required_after_claims=1,
    )
    assert result.status == "committed", result.violations

    notices = _budget_notices(model.seen[-1])
    assert len(notices) == 1
    notice = notices[0]
    # It states the arithmetic…
    assert "6" in notice and "8" in notice
    # …and what the gate's own two predicates already find owed: the overview a touched page
    # owes, and the registered component's undecided alias term.
    assert "[overview]" in notice and path in notice
    assert "[alias_undecided]" in notice and _AliasComponent.term in notice


async def test_the_notice_says_so_when_the_same_predicates_find_nothing_owed():
    store = FakeCanonicalStore()
    model = ScriptedChatModel(
        turns=[[tc("list_documents"), tc("list_documents")], [tc("finish_compile")]]
    )
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 6)],
        skill=SKILL,
        max_tool_calls=8,
    )
    assert result.status == "noop"
    [notice] = _budget_notices(model.seen[-1])
    assert prompt("compile.budget.owed_none") in notice


async def test_a_batch_the_spent_budget_cannot_reach_still_answers_every_call():
    """Provider validity: an AIMessage declaring N tool calls needs N ToolMessages, or the
    NEXT invoke — the repair round — is rejected on the transcript rather than on the work.
    `ScriptedChatModel` asserts the pairing; this pins the refusal text itself."""
    store = FakeCanonicalStore()
    path = "memory/people/cheng-ye.md"
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="- 程野 是后端负责人。[cite: src-99 ¶0]",
                ),
                tc("list_documents"),
                tc("list_documents"),
            ],
            [tc("finish_compile")],
        ]
    )
    await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 6)],
        skill=SKILL,
        max_tool_calls=1,
    )
    refusals = [
        str(m.content)
        for m in model.seen[-1]
        if isinstance(m, ToolMessage)
        and str(m.content) == prompt("compile.budget.call_refused", budget=1)
    ]
    assert len(refusals) == 2


# ═══════════════════════════════════════ calls whose arguments never parsed as JSON


def _answer_ids(messages) -> list[str]:
    """The tool_call_ids the transcript answered, in the order the answers appear."""
    return [m.tool_call_id for m in messages if isinstance(m, ToolMessage)]


async def test_a_call_with_unparseable_arguments_is_answered_before_the_valid_ones():
    """The production failure: `400 … No tool output found for function call call_XYnXJ…`.

    langchain parses a tool call whose arguments are not valid JSON into
    `invalid_tool_calls`, not `tool_calls` — but the assistant message still declares it on
    the wire, so a loop that only walks `tool_calls` leaves it unanswered and the NEXT
    invoke over that history is rejected. Both ids must be answered, and the unparseable one
    first, because it is answered before the batch's real work runs.
    """
    store = FakeCanonicalStore()
    path = "memory/people/cheng-ye.md"
    invalid = bad_tc("append_block")
    valid = tc(
        "create_document",
        path=path,
        frontmatter={"type": "person", "slug": "cheng-ye"},
        body="- 程野 是后端负责人。[cite: s01 ¶0]",
    )
    model = ScriptedChatModel(turns=[[invalid, valid], [tc("finish_compile")]])
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 6)],
        skill=SKILL,
    )
    assert result.status == "committed"
    # The history the SECOND model call was handed — the one production rejected.
    answers = _answer_ids(model.seen[-1])
    assert invalid["id"] in answers and valid["id"] in answers
    assert answers.index(invalid["id"]) < answers.index(valid["id"])
    [refusal] = [
        m for m in model.seen[-1]
        if isinstance(m, ToolMessage) and m.tool_call_id == invalid["id"]
    ]
    assert str(refusal.content) == prompt(
        "compile.tool.invalid_call", name="append_block", error=invalid["error"]
    )


async def test_a_batch_of_only_unparseable_calls_lets_the_model_try_again():
    """An AIMessage with no PARSED tool calls is not the model ending its turn when the
    calls it did make were unparseable. The round loops, and the retry finishes normally."""
    store = FakeCanonicalStore()
    path = "memory/people/cheng-ye.md"
    model = ScriptedChatModel(
        turns=[
            [bad_tc("create_document")],
            [
                tc(
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="- 程野 是后端负责人。[cite: s01 ¶0]",
                )
            ],
            [tc("finish_compile")],
        ]
    )
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 6)],
        skill=SKILL,
    )
    assert result.status == "committed"
    assert path in store.commits[0]
    assert len(model.seen) == 3  # the invalid batch did NOT end the round


async def test_an_unparseable_call_costs_the_round_a_call_like_a_refused_one():
    """Budget accounting: it spent a turn, so it is charged one.

    Here the invalid call is what exhausts a two-call round, and the valid call beside it in
    the same batch is refused unexecuted — the same answer any call gets once the budget is
    gone. That charge is also what stops a model emitting nothing but bad JSON from looping
    forever: the round runs out instead.
    """
    store = FakeCanonicalStore()
    path = "memory/people/cheng-ye.md"
    invalid = bad_tc("append_block")
    starved = tc("list_documents")
    model = ScriptedChatModel(
        turns=[
            [
                tc(  # cites a source this job never carried → the gate will reject
                    "create_document",
                    path=path,
                    frontmatter={"type": "person", "slug": "cheng-ye"},
                    body="- 程野 是后端负责人。[cite: src-99 ¶0]",
                )
            ],
            [invalid, starved],
            [tc("finish_compile")],
        ]
    )
    result = await run_compile(
        user_id=USER,
        model=model,
        store=store,
        sources=[_source("src-01", 6)],
        skill=SKILL,
        max_tool_calls=2,
    )
    by_id = {
        m.tool_call_id: str(m.content)
        for m in model.seen[-1]
        if isinstance(m, ToolMessage)
    }
    assert by_id[invalid["id"]] == prompt(
        "compile.tool.invalid_call", name="append_block", error=invalid["error"]
    )
    assert by_id[starved["id"]] == prompt("compile.budget.call_refused", budget=2)
    # create_document + the invalid call spent the first round; finish_compile the repair one.
    assert result.tool_calls == 3
    assert store.commits == []  # the gate still rejects the citation: canonical untouched
