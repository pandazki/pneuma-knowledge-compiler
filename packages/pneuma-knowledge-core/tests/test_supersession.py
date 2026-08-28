"""supersede_claim: the mechanical form of "the world changed".

Locked here: the old claim stays byte-for-byte and becomes frozen; the new claim gets a
system anchor and one supersedes marker; the current view and the history chain are
derived from the marker alone; the gate rejects every illegal link shape; the event stream
narrates a state change rather than an addition.
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_core.compile.anchor_ops import (
    AnchorToolError,
    anchored_blocks,
    supersede_claim_text,
)
from pneuma_knowledge_core.compile.brief import render_brief_record
from pneuma_knowledge_core.compile.gate import check_supersession, run_gate
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.supersession import (
    SUPERSEDES_MARK_RE,
    block_by_anchor,
    chains,
    current_blocks,
    superseded_index,
    supersessions,
)
from pneuma_knowledge_core.compile.transitions import derive_events
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import ANCHOR_MARK_RE, DocumentId, extract_anchors

from test_gate import SOURCES, TEMPLATES  # noqa: E402 — shared fixtures

PATH = "memory/people/jia-ning.md"
OLD = "- 贾宁是恒印印刷的对接人，能定打样排期。[cite: src-01 ¶0] <!-- c:a1f3 -->"
NEW_TEXT = "- 贾宁自 2026-05 起任新华印务采购总监。[cite: src-01 ¶2]"


def _doc(body: str = OLD) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId("d1"),
        path=PATH,
        frontmatter={"doc_id": "d1", "type": "person", "slug": "jia-ning"},
        body=body,
    )


def _draft(body: str = OLD) -> PatchDraft:
    return PatchDraft.from_canonical([_doc(body)], TEMPLATES)


# --- the text primitive -------------------------------------------------------


def test_supersede_keeps_the_old_claim_and_places_the_successor_right_after_it():
    body = "## 位置\n\n" + OLD + "\n- 其他事实。[cite: src-01 ¶1] <!-- c:b2d0 -->"
    text, new_anchor = supersede_claim_text(body, "a1f3", NEW_TEXT, document_path=PATH)
    lines = text.split("\n")
    assert OLD in lines  # byte-for-byte
    successor = lines[lines.index(OLD) + 1]
    assert successor.startswith("- 贾宁自 2026-05 起任新华印务采购总监")
    assert f"<!-- c:{new_anchor} -->" in successor
    assert "<!-- supersedes: c:a1f3 -->" in successor
    # The anchor grammar is untouched: the marker is NOT an anchor.
    assert extract_anchors(successor) == [new_anchor]
    assert ANCHOR_MARK_RE.search("<!-- supersedes: c:a1f3 -->") is None
    assert SUPERSEDES_MARK_RE.findall(successor) == ["a1f3"]
    # the unrelated neighbour is untouched and still last
    assert lines[-1].endswith("<!-- c:b2d0 -->")


def test_supersede_refuses_a_successor_without_new_evidence():
    with pytest.raises(AnchorToolError, match="cite"):
        supersede_claim_text(OLD, "a1f3", "- 贾宁升任总监。", document_path=PATH)


def test_supersede_refuses_a_caller_minted_anchor_or_marker_and_multi_block_text():
    with pytest.raises(AnchorToolError):
        supersede_claim_text(OLD, "a1f3", NEW_TEXT + " <!-- c:ffff -->", document_path=PATH)
    with pytest.raises(AnchorToolError):
        supersede_claim_text(
            OLD, "a1f3", NEW_TEXT + " <!-- supersedes: c:a1f3 -->", document_path=PATH
        )
    with pytest.raises(AnchorToolError, match="one claim"):
        supersede_claim_text(OLD, "a1f3", NEW_TEXT + "\n- 第二条。[cite: src-01 ¶3]", document_path=PATH)


def test_supersede_refuses_an_unknown_anchor_listing_the_existing_ones():
    with pytest.raises(AnchorToolError, match="a1f3"):
        supersede_claim_text(OLD, "zzzz", NEW_TEXT, document_path=PATH)


# --- the draft: frozen history at the tool face ----------------------------------


def test_a_superseded_claim_is_frozen_for_edit_and_for_a_second_supersession():
    draft = _draft()
    _, new_anchor = draft.supersede_claim(PATH, "a1f3", NEW_TEXT)
    with pytest.raises(AnchorToolError, match=new_anchor):
        draft.edit_claim(PATH, "a1f3", "- 改写旧状态。[cite: src-01 ¶0]")
    with pytest.raises(AnchorToolError, match=new_anchor):
        draft.supersede_claim(PATH, "a1f3", "- 又一次取代。[cite: src-01 ¶4]")
    # the successor itself stays editable (correction) and supersedable (further change)
    draft.edit_claim(PATH, new_anchor, "- 措辞修正。[cite: src-01 ¶2]")
    _, third = draft.supersede_claim(PATH, new_anchor, "- 再次变化。[cite: src-01 ¶4]")
    assert chains(draft.new_bodies()) == [["a1f3", new_anchor, third]]


# --- derived views ----------------------------------------------------------------


def test_current_view_and_history_chain_are_derived_from_the_marker_alone():
    draft = _draft()
    _, new_anchor = draft.supersede_claim(PATH, "a1f3", NEW_TEXT)
    bodies = draft.new_bodies()
    assert supersessions(bodies[PATH]) == {new_anchor: "a1f3"}
    assert superseded_index(bodies) == {"a1f3": (PATH, new_anchor)}
    current = current_blocks(bodies[PATH], superseded_index(bodies))
    assert len(current) == 1 and new_anchor in current[0]
    assert chains(bodies) == [["a1f3", new_anchor]]


# --- the gate ---------------------------------------------------------------------


def _docs(body: str):
    draft = _draft(body)
    return draft.documents(), draft.base_bodies()


def test_gate_accepts_a_legal_supersession_end_to_end():
    draft = _draft()
    draft.supersede_claim(PATH, "a1f3", NEW_TEXT)
    assert run_gate(draft, SOURCES) == []


def test_gate_rejects_missing_target_self_reference_and_multiple_targets():
    missing = OLD + "\n- 新。[cite: src-01 ¶1] <!-- c:c07e --> <!-- supersedes: c:dead -->"
    assert {v.detail for v in check_supersession(*_docs(missing))} and any(
        "dead" in v.detail for v in check_supersession(*_docs(missing))
    )
    selfref = "- 自指。[cite: src-01 ¶1] <!-- c:c07e --> <!-- supersedes: c:c07e -->"
    assert any("itself" in v.detail for v in check_supersession(*_docs(selfref)))
    multi = (
        OLD
        + "\n- 另一条。[cite: src-01 ¶1] <!-- c:b2d0 -->"
        + "\n- 新。[cite: src-01 ¶2] <!-- c:c07e --> <!-- supersedes: c:a1f3 --> <!-- supersedes: c:b2d0 -->"
    )
    assert any("several" in v.detail for v in check_supersession(*_docs(multi)))


def test_gate_rejects_two_successors_a_cycle_and_a_missing_citation():
    fork = (
        OLD
        + "\n- 甲。[cite: src-01 ¶1] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->"
        + "\n- 乙。[cite: src-01 ¶2] <!-- c:d18f --> <!-- supersedes: c:a1f3 -->"
    )
    assert any("more than one" in v.detail for v in check_supersession(*_docs(fork)))
    cycle = (
        "- 甲。[cite: src-01 ¶1] <!-- c:c07e --> <!-- supersedes: c:d18f -->"
        "\n- 乙。[cite: src-01 ¶2] <!-- c:d18f --> <!-- supersedes: c:c07e -->"
    )
    assert any("loops" in v.detail for v in check_supersession(*_docs(cycle)))
    uncited = OLD + "\n- 无证据。 <!-- c:c07e --> <!-- supersedes: c:a1f3 -->"
    assert any("evidence" in v.detail for v in check_supersession(*_docs(uncited)))


def test_gate_freezes_a_claim_that_was_already_superseded_in_the_base():
    base_body = OLD + "\n- 新。[cite: src-01 ¶2] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->"
    draft = _draft(base_body)
    # Poke the working body directly (no tool can do this): rewrite the frozen claim.
    draft.documents()[PATH].body = base_body.replace("能定打样排期", "改了历史")
    violations = check_supersession(draft.documents(), draft.base_bodies())
    assert [v.kind for v in violations] == ["supersession"]
    assert "frozen" in violations[0].detail


# --- events and the brief ----------------------------------------------------------


def test_events_narrate_a_state_change_not_an_addition():
    draft = _draft()
    _, new_anchor = draft.supersede_claim(PATH, "a1f3", NEW_TEXT)
    events = derive_events(draft.base_bodies(), draft.new_bodies())
    assert [(e.type, e.anchor, e.supersedes) for e in events] == [
        ("claim_superseded", new_anchor, "a1f3")
    ]
    assert "恒印印刷" in events[0].before and "新华印务" in events[0].after
    record = render_brief_record(events, [])
    assert "superseded (state changed)" in record and "(supersedes: " in record


def test_editing_a_successor_keeps_its_supersedes_marker_and_refuses_moving_it():
    draft = _draft()
    _, new_anchor = draft.supersede_claim(PATH, "a1f3", NEW_TEXT)
    draft.edit_claim(PATH, new_anchor, "- 措辞修正。[cite: src-01 ¶2]")
    assert supersessions(draft.new_bodies()[PATH]) == {new_anchor: "a1f3"}
    with pytest.raises(AnchorToolError, match="supersedes"):
        draft.edit_claim(PATH, new_anchor, "- 改链。[cite: src-01 ¶2] <!-- supersedes: c:b2d0 -->")


def test_evolve_cannot_merge_away_a_superseded_predecessor():
    # The evolve-only delete channel refuses, so a reorganization can never leave a
    # successor's `supersedes` link dangling (which would brick every later compile).
    draft = _draft()
    _, new_anchor = draft.supersede_claim(PATH, "a1f3", NEW_TEXT)
    with pytest.raises(AnchorToolError, match="predecessor"):
        draft.delete_claim(PATH, "a1f3")
    # deleting the successor (the head) is allowed — nothing points at it
    draft.delete_claim(PATH, new_anchor)
    assert chains(draft.new_bodies()) == []


def test_a_successor_of_a_list_item_is_written_as_a_list_item():
    text, new_anchor = supersede_claim_text(OLD, "a1f3", "贾宁升任总监。[cite: src-01 ¶2]", document_path=PATH)
    successor = text.split("\n")[1]
    assert successor.startswith("- 贾宁升任总监。") and f"c:{new_anchor}" in successor


def test_projection_strips_the_supersedes_marker_from_claim_text():
    from pneuma_knowledge_core.recall.projection import project_document_claims

    body = OLD + "\n- 新状态。[cite: src-01 ¶2] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->"
    claims = project_document_claims(_doc(body))
    assert [c.text for c in claims] == ["贾宁是恒印印刷的对接人，能定打样排期。", "新状态。"]


# --- paragraph claims: the successor is its OWN block -------------------------------

PARA_OLD = "贾宁是恒印印刷的对接人，能定打样排期。[cite: src-01 ¶0] <!-- c:a1f3 -->"
PARA_NEW = "贾宁自 2026-05 起任新华印务采购总监。[cite: src-01 ¶2]"


def test_a_paragraph_successor_is_separated_from_its_predecessor_by_a_blank_line():
    """Without the blank line the two claims are ONE paragraph — and therefore one block
    to every reader of blocks, so the predecessor's anchor disappears from the anchor→block
    lookup and the gate reports a live target as missing."""
    body = "## 位置\n\n" + PARA_OLD + "\n\n其他事实。[cite: src-01 ¶1] <!-- c:b2d0 -->"
    text, new_anchor = supersede_claim_text(body, "a1f3", PARA_NEW, document_path=PATH)
    lines = text.split("\n")
    assert PARA_OLD in lines  # byte-for-byte
    at = lines.index(PARA_OLD)
    assert lines[at + 1] == ""  # exactly one blank line between the two claims
    assert f"<!-- c:{new_anchor} --> <!-- supersedes: c:a1f3 -->" in lines[at + 2]
    assert lines[at + 3] == "" and lines[at + 4].endswith("<!-- c:b2d0 -->")
    assert "\n\n\n" not in text  # no doubled blank line introduced
    # Each claim is its own block, so the predecessor is still findable by its anchor.
    blocks = anchored_blocks(text)
    assert blocks == [PARA_OLD, lines[at + 2], lines[at + 4]]
    assert set(block_by_anchor({PATH: text})) == {"a1f3", new_anchor, "b2d0"}


def test_a_paragraph_supersession_passes_the_gate_and_chains_linearly():
    draft = _draft(PARA_OLD)
    _, second = draft.supersede_claim(PATH, "a1f3", PARA_NEW)
    assert run_gate(draft, SOURCES) == []
    _, third = draft.supersede_claim(PATH, second, "贾宁 2026-08 离职。[cite: src-01 ¶3]")
    assert run_gate(draft, SOURCES) == []
    assert chains(draft.new_bodies()) == [["a1f3", second, third]]
    events = derive_events(draft.base_bodies(), draft.new_bodies())
    assert [(e.type, e.supersedes) for e in events] == [
        ("claim_superseded", "a1f3"),
        ("claim_superseded", second),
    ]


def test_a_paragraph_successor_at_end_of_document_adds_no_trailing_blank():
    text, _ = supersede_claim_text(PARA_OLD, "a1f3", PARA_NEW, document_path=PATH)
    assert len(text.split("\n")) == 3 and not text.endswith("\n")
