"""run_compile driven by a scripted fake chat model over three scenarios:
1. clean compile of two documents → commit + correct events;
2. first-round illegal citation → gate reject → repair fixes → commit;
3. still illegal after repair → abort with the canonical layer untouched.
"""

from datetime import datetime, timezone
from itertools import count

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError, assign_document_anchors
from pneuma_knowledge_core.compile.documents import parse_document, render_document
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import _build_tools, run_compile
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId, SourceId, extract_anchors
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import NormalizedBlock, NormalizedSource, RawSource, StructureMap
from pneuma_knowledge_core.skill import load_skill_base

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
