"""Phase 2 reorganization runner (schema-evolve §B4): a scripted model walks
create → move×2 → delete×1 → search/fetch (async) → finish; assert the EvolveResult
summary, files, dropped list, and that async tools are awaited with results in ToolMessages.

Plus the compile-regression guard: the daily _build_tools face never exposes the
evolve-only move_claim / delete_claim."""

from itertools import count

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from pneuma_knowledge_core.compile.gate import Violation
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import _build_tools
from pneuma_knowledge_core.components import (
    BaseComponent,
    register_component,
    reset_components,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.evolve.propose import EvolveProposal
from pneuma_knowledge_core.evolve.runner import (
    repair_round_budget as evolve_repair_budget,
    run_evolve,
)
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill import compose_skill, load_skill_base
from pneuma_knowledge_core.skill.pack import SchemaPack

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
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


USER = UserId("u-evolve-1")

ATLAS_BODY = (
    "## 产品计划\n\n"
    "- Atlas Q3 发布。[cite: src-01 ¶2] <!-- c:aa11 -->\n"
    "- Atlas 的技术决策由测试用户负责。[cite: src-01 ¶3] <!-- c:bb22 -->\n"
    "- 冗余：Atlas Q3 发布（重复）。[cite: src-01 ¶2] <!-- c:cc33 -->"
)


def _base_docs() -> list[CanonicalDocument]:
    return [
        CanonicalDocument(
            doc_id=DocumentId("d-atlas"),
            path="memory/topics/atlas.md",
            frontmatter={"doc_id": "d-atlas", "type": "topic", "slug": "atlas"},
            body=ATLAS_BODY,
        )
    ]


def _proposal() -> EvolveProposal:
    pack = SchemaPack(
        pack_id="evolved-products",
        origin="evolved",
        extra_instructions="收编个人产品台账。",
        extra_path_templates=["memory/products/{slug}.md"],
    )
    return EvolveProposal(packs=[pack], rationale="topics 下已积累 3 个个人产品主题。")


class _RecordingSearch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, query: str) -> str:
        self.calls.append(query)
        return f"（检索 {query} 命中 0 条新证据）"


class _RecordingFetch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    async def __call__(self, source_id: str, block_start: int, block_end: int) -> str:
        self.calls.append((source_id, block_start, block_end))
        return f"{source_id} ¶{block_start}-{block_end} 原文……"


async def _bounds(source_id: str) -> int | None:
    return {"src-01": 5}.get(source_id)


async def test_reorganization_walk_create_move_delete_finish():
    new_skill = compose_skill(load_skill_base("v1"), _proposal().packs)
    search = _RecordingSearch()
    fetch = _RecordingFetch()
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path="memory/products/atlas.md",
                    frontmatter={"type": "product", "slug": "atlas"},
                    body="## 产品\n",
                ),
                tc("search_knowledge", query="Atlas 产品"),
                tc(
                    "move_claim",
                    from_path="memory/topics/atlas.md",
                    anchor_id="aa11",
                    to_path="memory/products/atlas.md",
                    heading="产品",
                ),
                tc(
                    "move_claim",
                    from_path="memory/topics/atlas.md",
                    anchor_id="bb22",
                    to_path="memory/products/atlas.md",
                    heading="产品",
                ),
                tc("fetch_source", source_id="src-01", block_start=2, block_end=2),
                tc("delete_claim", path="memory/topics/atlas.md", anchor_id="cc33"),
                tc("finish_evolve"),
            ],
        ]
    )

    result = await run_evolve(
        user_id=USER,
        model=model,
        base_docs=_base_docs(),
        new_skill=new_skill,
        proposal=_proposal(),
        source_bounds=_bounds,
        search_knowledge=search,
        fetch_source=fetch,
    )

    assert result.status == "completed"
    # summary is mechanical statistics.
    assert result.summary["new_documents"] == 1
    assert result.summary["moved_claims"] == 2
    assert result.summary["merged_claims"] == 1
    assert result.summary["adopted_by_document"] == {"memory/products/atlas.md": 2}

    # files: moved claims live verbatim in the new product doc, gone from the topic.
    product = result.files["memory/products/atlas.md"]
    topic = result.files["memory/topics/atlas.md"]
    assert "- Atlas Q3 发布。[cite: src-01 ¶2] <!-- c:aa11 -->" in product
    assert "c:bb22" in product
    assert "c:aa11" not in topic and "c:bb22" not in topic
    assert "c:cc33" not in topic  # deleted

    # dropped: the merged claim's anchor, with its original text.
    assert [d.anchor for d in result.dropped] == ["cc33"]
    assert "冗余" in result.dropped[0].text

    # async tools were awaited in-loop and their results consumed.
    assert search.calls == ["Atlas 产品"]
    assert fetch.calls == [("src-01", 2, 2)]
    assert result.token_usage["total_tokens"] > 0


async def test_missing_move_target_reported_but_does_not_crash():
    # move to a non-existent doc → the tool returns an AnchorToolError message (no create
    # first); the claim stays put, nothing lands as moved.
    new_skill = compose_skill(load_skill_base("v1"), _proposal().packs)
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "move_claim",
                    from_path="memory/topics/atlas.md",
                    anchor_id="aa11",
                    to_path="memory/products/atlas.md",
                    heading="产品",
                ),
                tc("finish_evolve"),
            ],
        ]
    )
    result = await run_evolve(
        user_id=USER,
        model=model,
        base_docs=_base_docs(),
        new_skill=new_skill,
        proposal=_proposal(),
        source_bounds=_bounds,
    )
    # nothing moved → noop (draft unchanged), aa11 still in the topic.
    assert result.summary["moved_claims"] == 0
    assert result.status == "noop"
    assert "c:aa11" in result.files["memory/topics/atlas.md"]


def test_compile_tool_face_excludes_evolve_only_tools():
    # Regression guard: the daily compile face never exposes the destructive channels that
    # only whole-KB reorganization (evolve, behind its own human gate) is allowed to use.
    draft = PatchDraft.from_canonical([], load_skill_base("v1").path_templates)
    names = {t.name for t in _build_tools(draft)}
    assert "move_claim" not in names
    assert "delete_claim" not in names
    # Exact set, so newly exposed tools are a deliberate decision rather than a drift.
    # compile carries read ports (search_knowledge / search_source) so it can ask what is
    # already known instead of being handed the whole knowledge base in its prompt.
    assert names == {
        "list_documents",
        "read_document",
        "create_document",
        "edit_claim",
        "append_block",
        "supersede_claim",
        "rewrite_overview",
        "set_fields",
        "finish_compile",
        "search_knowledge",
        "search_source",
    }


# --- the components' window is open around the reorganization ------------------------------
#
# A component's sync gate check reads a per-process mirror of its own projection, and an
# evolve job runs where no compile ran — the mirror is cold by construction. `prepare` is
# what fills it, so evolve opens the same window a compile does; without it the check would
# render the empty library and pass every page blind.


class _Watcher(BaseComponent):
    name = "watcher"

    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.log: list[str] = []

    async def prepare(self, user_id: str) -> None:
        self.log.append(f"prepare:{user_id}")

    def gate_checks(self, docs, base_docs):  # noqa: ARG002
        self.log.append("gate")
        if not self.refuse:
            return []
        return [Violation("watcher.refused", "memory/products/atlas.md", "no.")]


async def _one_create(component):
    register_component(component)
    new_skill = compose_skill(load_skill_base("v1"), _proposal().packs)
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path="memory/products/atlas.md",
                    frontmatter={"type": "product", "slug": "atlas"},
                    body="## 产品\n\n- 新事实。[cite: src-01 ¶1]",
                ),
                tc("finish_evolve"),
            ]
        ]
    )
    return await run_evolve(
        user_id=USER,
        model=model,
        base_docs=_base_docs(),
        new_skill=new_skill,
        proposal=_proposal(),
        source_bounds=_bounds,
    )


async def test_prepare_runs_before_the_gate_checks_and_a_component_refusal_aborts():
    component = _Watcher(refuse=True)
    try:
        result = await _one_create(component)
    finally:
        reset_components()
    # prepared once, at the head of the job — then judged (twice: the gate, then the repair
    # round's gate), and the reorganization lands nothing.
    assert component.log[0] == f"prepare:{USER}"
    assert component.log.count("prepare:" + str(USER)) == 1
    assert component.log[1:] == ["gate", "gate"]
    assert result.status == "aborted"


async def test_a_component_that_passes_leaves_the_reorganization_alone():
    component = _Watcher()
    try:
        result = await _one_create(component)
    finally:
        reset_components()
    assert result.status == "completed"
    assert "memory/products/atlas.md" in result.files


# ═══════════════════════════════════ the round's tool-call budget (compile's counterpart)
#
# evolve carried the identical shape: ONE `tool_calls` counter and `while tool_calls <
# MAX_TOOL_CALLS` in a `tool_loop` both rounds call. A first round that spent its budget left
# the repair round unable to enter its loop at all — the gate's feedback was appended to a
# conversation nobody was asked to continue, and the reorganization aborted every time.


class _NeedsTheProductPage(BaseComponent):
    """Refuses the round until the product page exists — a violation one call repairs."""

    name = "needs-product-page"

    def gate_checks(self, docs, base_docs):  # noqa: ARG002
        if "memory/products/atlas.md" in docs:
            return []
        return [Violation("needs_product_page", "memory/topics/atlas.md", "not adopted yet")]


def test_the_evolve_repair_round_gets_a_fresh_allowance_bounded_by_the_round_budget():
    assert evolve_repair_budget(1, 120) == 12
    assert evolve_repair_budget(9, 120) == 27
    assert evolve_repair_budget(9, 20) == 20


async def test_an_evolve_first_round_that_spends_its_budget_is_still_repairable():
    register_component(_NeedsTheProductPage())
    try:
        await _evolve_budget_walk()
    finally:
        reset_components()


async def _evolve_budget_walk():
    new_skill = compose_skill(load_skill_base("v1"), _proposal().packs)
    model = ScriptedChatModel(
        turns=[
            # Three calls, no finish_evolve: the round is CUT, not ended.
            [
                tc("list_documents"),
                tc("read_document", path="memory/topics/atlas.md"),
                tc("list_documents"),
            ],
            # The repair round — impossible before this fix.
            [
                tc(
                    "create_document",
                    path="memory/products/atlas.md",
                    frontmatter={"type": "product", "slug": "atlas"},
                    body="## 产品\n",
                ),
                tc("finish_evolve"),
            ],
        ]
    )
    result = await run_evolve(
        user_id=USER,
        model=model,
        base_docs=_base_docs(),
        new_skill=new_skill,
        proposal=_proposal(),
        source_bounds=_bounds,
        max_tool_calls=3,
    )

    assert result.status == "completed"
    assert result.tool_calls == 5  # 3 spent in round one, 2 more in the fresh allowance
    assert "memory/products/atlas.md" in result.files

    feedback = [
        str(m.content)
        for m in model.seen[-1]
        if isinstance(m, HumanMessage)
        and prompt("gate.evolve.feedback_header") in str(m.content)
    ]
    assert len(feedback) == 1
    assert feedback[0].startswith(
        prompt("gate.previous_round_cut_off", spent=3, budget=3)
    )


async def test_evolve_answers_a_call_whose_arguments_never_parsed():
    """The same mechanism as compile's loop: an unparseable call is `invalid_tool_calls`,
    not `tool_calls`, yet the wire still declares it — so it is answered (before the batch's
    valid calls), charged to the round like a refused one, and a batch of nothing but
    unparseable calls loops rather than ending the round."""
    new_skill = compose_skill(load_skill_base("v1"), _proposal().packs)
    invalid = bad_tc("create_document")
    later = tc(
        "create_document",
        path="memory/products/atlas.md",
        frontmatter={"type": "product", "slug": "atlas"},
        body="## 产品\n",
    )
    model = ScriptedChatModel(
        turns=[
            [invalid],  # nothing parsed: the round must continue, not end
            [later, tc("finish_evolve")],
        ]
    )
    result = await run_evolve(
        user_id=USER,
        model=model,
        base_docs=_base_docs(),
        new_skill=new_skill,
        proposal=_proposal(),
        source_bounds=_bounds,
    )

    assert result.status == "completed"
    assert "memory/products/atlas.md" in result.files
    assert result.tool_calls == 3  # the invalid call is charged like any other
    answers = [
        m for m in model.seen[-1] if isinstance(m, ToolMessage)
    ]
    assert answers[0].tool_call_id == invalid["id"]
    assert str(answers[0].content) == prompt(
        "compile.tool.invalid_call", name="create_document", error=invalid["error"]
    )
