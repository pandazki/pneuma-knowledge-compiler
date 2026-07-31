"""The glance on the answering side: fast's parallel selection pass, deep's document tools.

What is worth locking here is the SHAPE of the addition rather than any wording:

- the glance is in the prompt for every question, whether or not anything is selected;
- fast's two branches genuinely overlap (the selection pass is not awaited before retrieval
  starts) and the whole lane's wall clock is the slower branch, not their sum;
- every way the selection pass can fail — timeout, provider error, non-schema reply, a path
  that does not exist — degrades to the retrieval-only answer, never to an exception;
- deep's new tools are the compile face's tools by name and shape, and a link walk
  (read → follow the link → read) actually works over them;
- with no canonical documents supplied, every lane is byte-for-byte what it was before.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.briefing import BriefingScope, build_briefing
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.recall.fast import (
    DocumentSelection,
    fast_recall,
    select_glance_documents,
)
from pneuma_knowledge_core.skill import SkillVersion
from pneuma_knowledge_core.domain.snapshot import SnapshotRef

from test_deep_recall import FakeContent, ScriptedToolModel
from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings

_AS_OF = datetime(2026, 7, 20, 12, 0, 0)
_USER = UserId("u-glance")

TEMPLATES = ["memory/profile.md", "memory/people/{slug}.md", "memory/topics/{slug}.md"]

SKILL = SkillVersion(
    skill_id="test-skill",
    version="t1",
    instructions="body",
    path_templates=list(TEMPLATES),
    content_hash="0" * 64,
)


def _anchor(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:8]


def _doc(path: str, title: str, body_rows: str) -> CanonicalDocument:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=path,
        frontmatter={"doc_id": f"d-{slug}", "type": "person", "slug": slug},
        body=f"# {title}\n\n## Role\n{body_rows}\n",
    )


#: Two people documents, the first linking to the second — the follow-the-thread fixture.
#: Synthetic people, no real names anywhere.
ADA = _doc(
    "memory/people/ada-quill.md",
    "Ada Quill",
    "- Ada Quill runs the Delta pilot with [Bo Marsh](bo-marsh.md). "
    f"[cite: src-01 ¶0] <!-- c:{_anchor('ada')} -->",
)
BO = _doc(
    "memory/people/bo-marsh.md",
    "Bo Marsh",
    f"- Bo Marsh owns the pilot's data export. [cite: src-01 ¶4] <!-- c:{_anchor('bo')} -->",
)
DOCS = [ADA, BO]


# --------------------------------------------------------------- the selection pass alone


class _SelectionModel(BaseChatModel):
    """A model whose structured-output face returns one scripted `DocumentSelection`.

    `with_structured_output` is overridden rather than scripted through tool calls so the test
    controls exactly what the pass receives back — including the failure modes, which is the
    behaviour under test."""

    paths: list[str] = []
    raise_with: Any = None
    delay: float = 0.0
    parsed_override: Any = "__unset__"
    seen: list[list] = []

    @property
    def _llm_type(self) -> str:
        return "selection-fake"

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ARG002
        outer = self

        class _Structured:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                outer.seen.append(list(messages))
                if outer.delay:
                    await asyncio.sleep(outer.delay)
                if outer.raise_with is not None:
                    raise outer.raise_with
                parsed = (
                    DocumentSelection(paths=list(outer.paths))
                    if outer.parsed_override == "__unset__"
                    else outer.parsed_override
                )
                return {
                    "raw": AIMessage(
                        content="",
                        usage_metadata={
                            "input_tokens": 7,
                            "output_tokens": 3,
                            "total_tokens": 10,
                        },
                    ),
                    "parsed": parsed,
                    "parsing_error": None,
                }

        return _Structured()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="answer"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return self._generate(messages)


async def test_the_pass_sees_the_glance_and_the_question_and_returns_existing_paths():
    model = _SelectionModel(paths=["memory/people/ada-quill.md"], seen=[])
    picked, usage, degraded = await select_glance_documents(
        model, "who runs the pilot?", "GLANCE-TEXT", known_paths=[d.path for d in DOCS]
    )
    assert picked == ("memory/people/ada-quill.md",)
    assert degraded is None
    assert usage["input_tokens"] == 7  # the pass's own tokens are accounted for
    human = model.seen[0][1].content
    assert "GLANCE-TEXT" in human and "who runs the pilot?" in human


async def test_selecting_nothing_is_a_normal_result_not_a_degradation():
    model = _SelectionModel(paths=[], seen=[])
    picked, _usage, degraded = await select_glance_documents(
        model, "q", "glance", known_paths=[d.path for d in DOCS]
    )
    assert picked == ()
    assert degraded is None  # ran and chose nothing — the common case, not a failure


async def test_a_path_outside_the_glance_is_discarded_rather_than_reported():
    """The glance is the model's whole view of the library, so anything else is invented; an
    invented path must not come back as a document that was read."""
    model = _SelectionModel(paths=["memory/people/nobody.md", "memory/people/bo-marsh.md"], seen=[])
    picked, _usage, degraded = await select_glance_documents(
        model, "q", "glance", known_paths=[d.path for d in DOCS]
    )
    assert picked == ("memory/people/bo-marsh.md",)
    assert degraded is None


async def test_the_cap_is_enforced_on_the_models_output():
    model = _SelectionModel(paths=[d.path for d in DOCS], seen=[])
    picked, _usage, _degraded = await select_glance_documents(
        model, "q", "glance", known_paths=[d.path for d in DOCS], cap=1
    )
    assert len(picked) == 1


async def test_a_timeout_degrades_to_no_selection_with_telemetry():
    model = _SelectionModel(paths=[ADA.path], delay=0.5, seen=[])
    picked, usage, degraded = await select_glance_documents(
        model, "q", "glance", known_paths=[d.path for d in DOCS], timeout=0.01
    )
    assert picked == () and degraded == "timeout"
    assert usage["total_tokens"] == 0


async def test_a_provider_error_degrades_to_no_selection_with_telemetry():
    model = _SelectionModel(raise_with=RuntimeError("provider exploded"), seen=[])
    picked, _usage, degraded = await select_glance_documents(
        model, "q", "glance", known_paths=[d.path for d in DOCS]
    )
    assert picked == () and degraded == "error"


async def test_a_non_schema_reply_degrades_rather_than_being_parsed_optimistically():
    model = _SelectionModel(parsed_override=None, seen=[])
    picked, _usage, degraded = await select_glance_documents(
        model, "q", "glance", known_paths=[d.path for d in DOCS]
    )
    assert picked == () and degraded == "error"


async def test_a_model_without_structured_output_degrades_instead_of_raising():
    """A keyless or minimal chat model may not implement structured output at all. That is a
    missing capability, not a reason for the whole answer to fail."""
    model = GenericFakeChatModel(messages=iter([AIMessage(content="not structured")]))
    picked, _usage, degraded = await select_glance_documents(
        model, "q", "glance", known_paths=[d.path for d in DOCS]
    )
    assert picked == () and degraded == "error"


# ------------------------------------------------------------------- fast, end to end


class _CapturingAnswerModel(_SelectionModel):
    """The selection face plus a recorded answer call, so one object drives both branches."""

    answer: str = "answered"
    answers_seen: list[list] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self.answers_seen.append(list(messages))
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.answer))]
        )


def _fast_kwargs(**overrides) -> dict:
    kwargs = dict(
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([ClaimStub("aaaa", "memory/people/ada-quill.md", "a claim")]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
    )
    kwargs.update(overrides)
    return kwargs


async def test_the_glance_is_in_the_answer_prompt_even_when_nothing_is_selected():
    model = _CapturingAnswerModel(paths=[], seen=[], answers_seen=[])
    result = await fast_recall(
        _USER, "who runs the pilot?", model=model, documents=DOCS, skill=SKILL,
        **_fast_kwargs(),
    )
    human = model.answers_seen[0][1].content
    assert prompt("recall.glance.header") in human
    assert "memory/people/ada-quill.md" in human
    assert result.glance_chars > 0
    assert result.expanded_documents == ()
    assert result.glance_degraded is None
    # nothing was expanded, so the full-document section is absent
    assert prompt("recall.fast.select.documents_header", count=1) not in human


async def test_a_selected_document_arrives_in_full_with_its_anchors_and_links():
    model = _CapturingAnswerModel(paths=[ADA.path], seen=[], answers_seen=[])
    result = await fast_recall(
        _USER, "who runs the pilot?", model=model, documents=DOCS, skill=SKILL,
        **_fast_kwargs(),
    )
    human = model.answers_seen[0][1].content
    assert result.expanded_documents == (ADA.path,)
    assert prompt("recall.fast.select.document_heading", path=ADA.path) in human
    assert "<!-- c:" in human  # anchors survive, so the answer can cite what it read
    assert "[Bo Marsh](bo-marsh.md)" in human  # and the link it could follow
    assert result.answer == "answered"


async def test_the_selection_pass_tokens_are_added_to_the_lanes_usage():
    model = _CapturingAnswerModel(paths=[], seen=[], answers_seen=[])
    result = await fast_recall(
        _USER, "q", model=model, documents=DOCS, skill=SKILL, **_fast_kwargs()
    )
    assert result.token_usage["input_tokens"] >= 7  # the pass's own call is not free, and is counted


async def test_the_two_branches_run_concurrently_not_in_sequence():
    """The design's latency claim, asserted on the intervals rather than on a total.

    A wall-clock threshold would be a flake and would also pass for the wrong reason (whichever
    branch happens to be fast). So each branch stamps when it entered and when it left, and
    what is asserted is that the intervals OVERLAP: the selection pass began before retrieval
    finished, which is exactly what makes the lane cost max(A, B) instead of A + B.
    """
    marks: dict[str, float] = {}

    def now() -> float:
        return asyncio.get_running_loop().time()

    class _SlowClaims:
        async def search_claims(self, user_id, query_or_embedding, *, limit=40):  # noqa: ANN001
            marks.setdefault("retrieval_in", now())
            await asyncio.sleep(0.10)
            marks["retrieval_out"] = now()
            return []

    class _MarkingModel(_CapturingAnswerModel):
        def with_structured_output(self, schema, **kwargs):  # noqa: ANN001
            inner = super().with_structured_output(schema, **kwargs)

            class _Marked:
                async def ainvoke(self, messages, config=None):  # noqa: ANN001
                    marks["select_in"] = now()
                    result = await inner.ainvoke(messages, config=config)
                    marks["select_out"] = now()
                    return result

            return _Marked()

    model = _MarkingModel(paths=[], delay=0.10, seen=[], answers_seen=[])
    await fast_recall(
        _USER,
        "q",
        as_of=_AS_OF,
        claim_lexical=_SlowClaims(),
        claim_vectors=_SlowClaims(),
        embeddings=FakeEmbeddings(),
        model=model,
        documents=DOCS,
        skill=SKILL,
    )
    assert marks["select_in"] < marks["retrieval_out"], "the selection pass waited for retrieval"
    assert marks["retrieval_in"] < marks["select_out"], "retrieval waited for the selection pass"
    # and the answer call is strictly after both: it needs the evidence from each.
    assert model.answers_seen, "the answer call never happened"


async def test_a_failing_pass_still_answers_over_retrieval_with_the_glance_present():
    model = _CapturingAnswerModel(raise_with=RuntimeError("boom"), seen=[], answers_seen=[])
    result = await fast_recall(
        _USER, "q", model=model, documents=DOCS, skill=SKILL, **_fast_kwargs()
    )
    assert result.answer == "answered"
    assert result.glance_degraded == "error"
    assert result.expanded_documents == ()
    assert result.glance_chars > 0  # the map is context, not a reward for a working pass


async def test_without_documents_the_lane_is_the_retrieval_only_one_it_always_was():
    model = GenericFakeChatModel(messages=iter([AIMessage(content="plain")]))
    result = await fast_recall(_USER, "q", model=model, **_fast_kwargs())
    assert result.answer == "plain"
    assert result.glance_chars == 0
    assert result.expanded_documents == ()
    assert result.glance_degraded is None


# --------------------------------------------------------------------------- deep lane


def _deep_kwargs(**overrides) -> dict:
    kwargs = dict(
        as_of=_AS_OF,
        claim_lexical=FakeClaimIndex([]),
        claim_vectors=FakeClaimIndex([]),
        embeddings=FakeEmbeddings(),
        content=FakeContent(),
    )
    kwargs.update(overrides)
    return kwargs


def _call(name: str, args: dict, cid: str) -> dict:
    return {"name": name, "args": args, "id": cid}


async def test_deep_opens_with_the_glance_in_its_first_human_turn():
    model = ScriptedToolModel(turns=[AIMessage(content="done")], seen=[])
    result = await deep_recall(
        _USER, "who runs the pilot?", model=model, documents=DOCS, skill=SKILL,
        **_deep_kwargs(),
    )
    human = model.seen[0][1].content
    assert prompt("recall.glance.header") in human
    assert result.glance_chars > 0
    assert result.read_documents == ()


async def test_deep_walks_a_link_list_then_read_then_read_the_linked_document():
    """The follow-the-thread acceptance: the loop lists documents, opens one, sees a markdown
    link in it, and opens the link's target — reaching a subject the seed retrieval (empty
    here) never surfaced."""
    model = ScriptedToolModel(
        turns=[
            AIMessage(content="", tool_calls=[_call("list_documents", {}, "c1")]),
            AIMessage(
                content="",
                tool_calls=[_call("read_document", {"path": ADA.path}, "c2")],
            ),
            AIMessage(
                content="",
                tool_calls=[_call("read_document", {"path": BO.path}, "c3")],
            ),
            AIMessage(content="Bo Marsh owns the export."),
        ],
        seen=[],
    )
    result = await deep_recall(
        _USER, "who owns the export?", model=model, documents=DOCS, skill=SKILL,
        **_deep_kwargs(),
    )
    assert result.answer == "Bo Marsh owns the export."
    assert result.read_documents == (ADA.path, BO.path)
    steps = [(s["tool"], s.get("path")) for s in result.trail]
    assert steps == [
        ("list_documents", None),
        ("read_document", ADA.path),
        ("read_document", BO.path),
    ]
    # the link that made the second read possible was in the first read's result
    first_read = next(s for s in result.trail if s["tool"] == "read_document")
    assert "bo-marsh.md" in first_read["result"]


async def test_read_document_states_a_missing_path_instead_of_raising():
    model = ScriptedToolModel(
        turns=[
            AIMessage(
                content="",
                tool_calls=[_call("read_document", {"path": "memory/people/nobody.md"}, "c1")],
            ),
            AIMessage(content="no record"),
        ],
        seen=[],
    )
    result = await deep_recall(
        _USER, "q", model=model, documents=DOCS, skill=SKILL, **_deep_kwargs()
    )
    assert result.answer == "no record"
    assert result.read_documents == ()
    assert result.trail[0]["found"] is False
    assert "nobody.md" in result.trail[0]["result"]


async def test_the_document_tools_exist_with_no_documents_and_say_the_base_is_empty():
    """The tool FACE is constant: a deployment that forgets to pass documents gets a stated
    absence, not a model reaching for a tool that is not there."""
    model = ScriptedToolModel(
        turns=[
            AIMessage(content="", tool_calls=[_call("list_documents", {}, "c1")]),
            AIMessage(content="nothing compiled yet"),
        ],
        seen=[],
    )
    result = await deep_recall(_USER, "q", model=model, **_deep_kwargs())
    assert result.glance_chars == 0
    assert result.trail[0]["result"] == prompt("recall.deep.tool.list_documents_empty")


async def test_deep_tool_face_is_the_exact_expected_set():
    """Newly exposed tools on the answering side are a deliberate decision, like the compile
    face's. The two document tools are named EXACTLY as compile names them."""
    captured: list[list[str]] = []

    class _NameCapturingModel(ScriptedToolModel):
        def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
            captured.append(sorted(getattr(t, "name", "") for t in tools))
            return self

    model = _NameCapturingModel(turns=[AIMessage(content="done")], seen=[])
    await deep_recall(_USER, "q", model=model, documents=DOCS, skill=SKILL, **_deep_kwargs())
    assert captured and captured[0] == [
        "fetch_verbatim",
        "list_documents",
        "read_document",
        "search_claims",
        "search_content",
    ]


# ----------------------------------------------------------------------------- briefing


async def test_briefing_carries_the_static_glance_and_stays_byte_stable():
    async def _build():
        return await build_briefing(
            _USER,
            BriefingScope(),
            snapshot=SnapshotRef(ref="deadbeef"),
            snapshot_docs=DOCS,
            skill=SKILL,
        )

    first, second = await _build(), await _build()
    assert prompt("recall.glance.header") in first.system_prefix
    assert "memory/people/bo-marsh.md" in first.system_prefix
    # no selection pass here: a briefing is built once and reused, so there is no
    # per-question moment to select in — the shape is all it carries.
    assert first.system_prefix == second.system_prefix
