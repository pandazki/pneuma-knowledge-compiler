"""Phase 2 reorganization runner (schema-evolve §B4): a scripted model walks
create → move×2 → delete×1 → search/fetch (async) → finish; assert the EvolveResult
summary, files, dropped list, and that async tools are awaited with results in ToolMessages.

Plus the compile-regression guard: the daily _build_tools face never exposes the
evolve-only move_claim / delete_claim."""

from itertools import count

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import _build_tools
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.evolve.propose import EvolveProposal
from pneuma_knowledge_core.evolve.runner import run_evolve
from pneuma_knowledge_core.skill import compose_skill, load_skill_base
from pneuma_knowledge_core.skill.pack import SchemaPack

_ids = count()


def tc(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call-{next(_ids)}", "type": "tool_call"}


class ScriptedChatModel(BaseChatModel):
    turns: list = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if self._cursor < len(self.turns):
            calls = self.turns[self._cursor]
            self._cursor += 1
            msg = AIMessage(content="", tool_calls=calls, usage_metadata=usage)
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
        "finish_compile",
        "search_knowledge",
        "search_source",
    }
