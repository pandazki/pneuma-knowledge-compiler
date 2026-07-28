"""run_compile driven by a scripted fake chat model over three scenarios:
1. clean compile of two documents → commit + correct events;
2. first-round illegal citation → gate reject → repair fixes → commit;
3. still illegal after repair → abort with the canonical layer untouched.
"""

from datetime import datetime, timezone
from itertools import count

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from pneuma_knowledge_core.compile.anchor_ops import assign_document_anchors
from pneuma_knowledge_core.compile.documents import parse_document
from pneuma_knowledge_core.compile.runner import run_compile
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId, SourceId, extract_anchors
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource, StructureMap
from pneuma_knowledge_core.skill import load_builtin_skill

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
        return next((d for d in self._docs if d.pneuma_id == document_id), None)

    async def commit_patch(self, user_id, files: dict[str, str], *, message: str):
        self.commits.append(dict(files))
        new_docs: list[CanonicalDocument] = []
        for path, text in files.items():
            fm, body = parse_document(text)
            new_docs.append(
                CanonicalDocument(
                    pneuma_id=DocumentId(str(fm.get("pneuma_id", ""))),
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
SKILL = load_builtin_skill()


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
        pneuma_id=DocumentId("abc123"),
        path="memory/people/cheng-ye.md",
        frontmatter={"pneuma_id": "abc123", "type": "person", "slug": "cheng-ye"},
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
