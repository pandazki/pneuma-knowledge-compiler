"""The draft's state form: a round trip that changes nothing about what the draft refuses.

A CLI has no memory between invocations, so `PatchDraft` and the round around it gain a JSON
form (docs/design/coding-agent-mode.md ruling 3). What has to hold is not "the fields survive"
but "the OBJECT survives": the same files, the same dirtiness, the same read marks — and above
all the same refusals, because every refusal in the draft is the mechanism the write
discipline rests on, and a draft that refuses differently after a reload is a door with two
different locks.
"""

import json

import pytest
from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.documents import Overview
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.session import DraftSession, handles_for
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId

TEMPLATES = ["memory/people/{slug}.md", "memory/topics/{slug}.md"]


def _base() -> list[CanonicalDocument]:
    return [
        CanonicalDocument(
            doc_id=DocumentId("abc123"),
            path="memory/people/cheng-ye.md",
            frontmatter={"doc_id": "abc123", "type": "person", "slug": "cheng-ye"},
            body="## 程野\n\n- 程野 是后端负责人。[cite: s01 ¶0] <!-- c:aa11 -->",
        )
    ]


def _draft() -> PatchDraft:
    return PatchDraft.from_canonical(_base(), TEMPLATES, overview_budget_chars=1234)


def test_a_round_trip_reproduces_the_draft_exactly():
    draft = _draft()
    draft.read("memory/people/cheng-ye.md")
    draft.mark_read("memory/people/cheng-ye.md")
    draft.append_block(
        "memory/people/cheng-ye.md", "承诺", "- 下周交付。[cite: s01 ¶1]"
    )
    draft.create_document(
        "memory/topics/q3.md",
        {"type": "topic", "slug": "q3"},
        "## Q3\n\n- 目标已定。[cite: s01 ¶1]",
    )

    state = draft.to_state()
    json.dumps(state)  # the form is a JSON document, not a pickle by another name
    back = PatchDraft.from_state(state)

    assert back.to_files() == draft.to_files()
    assert back.base_bodies() == draft.base_bodies()
    assert back.new_bodies() == draft.new_bodies()
    assert back.is_dirty() == draft.is_dirty()
    assert back.read_paths() == draft.read_paths()
    assert back.path_templates == draft.path_templates
    assert back.overview_budget_chars == draft.overview_budget_chars


def test_the_read_marks_survive_so_a_whole_region_write_is_still_refused():
    """The read mark is not bookkeeping: it is what refuses a rewrite of a page this round
    never looked at. Losing it in the round trip would silently unlock the door."""
    draft = _draft()
    reloaded = PatchDraft.from_state(draft.to_state())
    with pytest.raises(AnchorToolError):
        reloaded.rewrite_overview(
            "memory/people/cheng-ye.md", Overview(definition="他是后端负责人。 c:aa11")
        )
    # …and once the page has been read, the reload keeps that too.
    draft.mark_read("memory/people/cheng-ye.md")
    reopened = PatchDraft.from_state(draft.to_state())
    reopened.rewrite_overview(
        "memory/people/cheng-ye.md", Overview(definition="他是后端负责人。 c:aa11")
    )


def test_path_ownership_and_anchor_refusals_are_the_same_after_a_reload():
    draft = PatchDraft.from_state(_draft().to_state())
    with pytest.raises(AnchorToolError):
        draft.create_document("notes/loose.md", {"type": "note", "slug": "loose"}, "- x")
    with pytest.raises(AnchorToolError):
        draft.edit_claim("memory/people/cheng-ye.md", "zzzz", "- 改写。[cite: s01 ¶0]")


def test_the_session_round_trips_and_derives_both_handle_directions():
    session = DraftSession(
        user_id="u-1",
        job_id="job-7",
        handle_by_real=handles_for(["src-b", "src-a"]),
        round="repair",
        budget=12,
        spent=3,
        noticed=True,
        cut_off=True,
        task_sha256="deadbeef",
        skill_id="personal-knowledge",
        skill_version="v1",
        skill_content_hash="cafe",
        overview_budget_chars=2000,
        overview_required_after_claims=8,
        max_tool_calls=0,
        violations=(("citation", "memory/people/x.md", "unknown source"),),
        commit_message="compile job-7",
    )
    state = session.to_state()
    json.dumps(state)
    back = DraftSession.from_state(state)
    assert back == session
    # Supply order is the handle order, numerically — not the lexical order of `sNN`.
    assert back.source_ids == ("src-b", "src-a")
    assert back.real_by_handle == {"s01": "src-b", "s02": "src-a"}
    assert back.remaining == 9


def test_a_hundred_sources_still_order_by_supply_position():
    session = DraftSession(
        user_id="u-1", job_id="j", handle_by_real=handles_for([f"src-{i}" for i in range(101)])
    )
    assert session.source_ids[99] == "src-99"
    assert session.source_ids[100] == "src-100"
