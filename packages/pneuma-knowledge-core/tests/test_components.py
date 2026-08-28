"""The index-component seam: with nothing registered every surface is byte-identical; a
registered component's four faces reach the gate, the outline and the compile tool list."""

from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool

from pneuma_knowledge_core.canonical_glance import render_outline
from pneuma_knowledge_core.compile.gate import Violation, run_gate
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import _build_tools
from pneuma_knowledge_core.components import (
    BaseComponent,
    CanonicalReadOnly,
    IndexComponent,
    notify_source_indexed,
    rebuild_components,
    register_component,
    registered_components,
    reset_components,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId

from test_gate import SOURCES, TEMPLATES  # noqa: E402


class _Tagger(BaseComponent):
    """A toy component: documents of type `person` must declare `tag`; the outline shows it."""

    name = "tagger"

    def gate_checks(self, docs, base_docs):
        return [
            Violation("component:tagger", path, "person without tag")
            for path, doc in docs.items()
            if doc.frontmatter.get("type") == "person" and not doc.frontmatter.get("tag")
        ]

    def outline_tail(self, doc):
        tag = (doc.frontmatter or {}).get("tag")
        return f"tag: {tag}" if tag else None

    def compile_tools(self, draft, *, sources=()):
        def find_tag(tag: str) -> str:
            hits = [p for p, d in draft.documents().items() if d.frontmatter.get("tag") == tag]
            return ", ".join(hits) or "(none)"

        return [StructuredTool.from_function(find_tag, description="find a tag")]


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_components()
    yield
    reset_components()


def _doc(tag: str | None) -> CanonicalDocument:
    fm = {"doc_id": "d1", "type": "person", "slug": "x"}
    if tag:
        fm["tag"] = tag
    return CanonicalDocument(
        doc_id=DocumentId("d1"),
        path="memory/people/x.md",
        frontmatter=fm,
        body="- 事实。[cite: src-01 ¶0] <!-- c:aa11 -->",
    )


def test_nothing_registered_means_every_surface_is_unchanged():
    assert registered_components() == ()
    draft = PatchDraft.from_canonical([_doc(None)], TEMPLATES)
    assert run_gate(draft, SOURCES) == []
    # path line + the page's own ledger under it (no overview); no component line
    assert len(render_outline([_doc("x")])) == 2
    assert not any(t.name == "find_tag" for t in _build_tools(draft))


def test_a_registered_component_reaches_gate_outline_and_tools():
    component = _Tagger()
    assert isinstance(component, IndexComponent)
    register_component(component)

    draft = PatchDraft.from_canonical([_doc(None)], TEMPLATES)
    kinds = [v.kind for v in run_gate(draft, SOURCES)]
    assert kinds == ["component:tagger"]

    lines = render_outline([_doc("supplier")])
    assert len(lines) == 3 and lines[2].strip() == "tag: supplier"

    tools = _build_tools(draft, extra_tools=[t for t in component.compile_tools(draft)])
    find_tag = next(t for t in tools if t.name == "find_tag")
    assert find_tag.func(tag="supplier") == "(none)"


async def test_a_registered_component_is_stamped_into_the_commit_trailer_and_may_add_a_source_preamble():
    from pneuma_knowledge_core.compile.runner import _with_skill_trailer, _render_task
    from pneuma_knowledge_core.skill import load_skill_base
    from test_gate import _source

    class _Preambler(BaseComponent):
        name = "preambler"
        def source_preamble(self, source):
            return f"Identities present: im:{source.raw.source_id}"

    skill = load_skill_base("v1")
    assert "Components:" not in _with_skill_trailer("compile", skill)
    register_component(_Preambler())
    assert _with_skill_trailer("compile", skill).endswith("Components: preambler")
    task = _render_task([_source("src-01", 2)], [], {}, {}, {}, None, None)
    assert "Identities present: im:src-01" in task


# --------------------------------------------------------------- the projection channel


class _Projector(BaseComponent):
    """A component that keeps an index of its own: it records what it was told."""

    def __init__(self, name: str, *, explode: bool = False) -> None:
        self.name = name
        self.explode = explode
        self.indexed: list[str] = []
        self.rebuilt: list[str] = []

    async def on_source_indexed(self, user_id, source):
        if self.explode:
            raise RuntimeError("boom")
        self.indexed.append(f"{user_id}:{source.raw.source_id}")

    async def rebuild(self, user_id):
        if self.explode:
            raise RuntimeError("boom")
        self.rebuilt.append(str(user_id))


async def test_nothing_registered_means_the_projection_channel_is_a_no_op():
    from test_gate import _source

    assert registered_components() == ()
    await notify_source_indexed("u-1", _source("src-01", 2))
    assert await rebuild_components("u-1") == []


async def test_a_component_with_no_projection_of_its_own_rides_the_channel_harmlessly():
    """`BaseComponent`'s no-op defaults mean the channel reaches a component that keeps
    nothing persisted and simply does nothing — no branch at the call site, no error."""
    from test_gate import _source

    register_component(_Tagger())  # gate/outline/tools only, no projection of its own
    await notify_source_indexed("u-1", _source("src-01", 2))
    assert await rebuild_components("u-1") == ["tagger"]


async def test_every_registered_component_is_told_a_source_was_indexed():
    from test_gate import _source

    first, second = _Projector("first"), _Projector("second")
    register_component(first)
    register_component(second)

    await notify_source_indexed("u-1", _source("src-01", 2))

    assert first.indexed == ["u-1:src-01"] and second.indexed == ["u-1:src-01"]
    assert await rebuild_components("u-1") == ["first", "second"]
    assert first.rebuilt == ["u-1"] and second.rebuilt == ["u-1"]


async def test_a_component_that_raises_never_takes_the_job_or_the_rebuild_with_it():
    """A component projection is DERIVED: the worst a broken one may cost is a stale index
    until the next rebuild — never the L1/L2 indexing that already succeeded."""
    from test_gate import _source

    broken, healthy = _Projector("broken", explode=True), _Projector("healthy")
    register_component(broken)
    register_component(healthy)

    await notify_source_indexed("u-1", _source("src-01", 2))
    assert healthy.indexed == ["u-1:src-01"]  # the failure did not stop the fan-out

    assert await rebuild_components("u-1") == ["healthy"]  # and it is reported as not run


async def test_a_component_tool_is_built_with_this_compiles_sources_under_their_handles():
    """A component tool whose answer depends on the MATERIAL — which identity this job's
    turns address by a given name — is handed the job's sources. They arrive aliased, so a
    tool that names one names it by the same `sNN` handle the task text uses."""
    from pneuma_knowledge_core.compile.runner import run_compile
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_core.skill import load_skill_base
    from test_gate import _source
    from test_runner import FakeCanonicalStore, ScriptedChatModel

    seen: list[str] = []

    class _Reader(BaseComponent):
        name = "reader"

        def compile_tools(self, draft, *, sources=()):
            seen.extend(str(s.raw.source_id) for s in sources)
            return []

    register_component(_Reader())
    await run_compile(
        user_id=UserId("u-1"),
        model=ScriptedChatModel(turns=[]),
        store=FakeCanonicalStore(),
        sources=[_source("src-01", 2), _source("src-02", 1)],
        skill=load_skill_base("v1"),
    )
    assert seen == ["s01", "s02"]


async def test_a_component_receives_a_canonical_face_with_no_way_to_write():
    """Invariant I7, as a mechanism rather than a promise.

    A component indexes canonical; it never authors it. `CanonicalReadOnly` is what makes
    that structural — the object a component holds simply has no write method, so "the
    shipped components happen not to call `commit_patch`" never has to be the guarantee.
    """
    from test_runner import FakeCanonicalStore

    store = FakeCanonicalStore()
    face = CanonicalReadOnly(store)

    assert not hasattr(face, "commit_patch")
    assert not any(
        hasattr(face, name) for name in ("tag", "revert", "write", "delete_user")
    )
    # …and the one read it does expose still reaches the real store.
    assert await face.list(UserId("u-1")) == await store.list(UserId("u-1"))
