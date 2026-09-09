"""The sixth source contract: bounded agent activity and mechanical Owner attribution."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.gate import (
    post_write_violations,
    run_gate,
    violation_catalog,
)
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.compile.runner import (
    build_compile_tool_face,
    render_compile_messages,
)
from pneuma_knowledge_core.domain.authorship import (
    block_authorship,
    owner_authored_blocks,
)
from pneuma_knowledge_core.domain.ids import UserId, extract_anchors
from pneuma_knowledge_core.domain.intake import (
    INTAKE_ARCHETYPES,
    propose_intake,
    with_semantic_retrieval,
)
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import (
    AgentSessionSource,
    parse_source_contract,
)
from pneuma_knowledge_core.prompts import override_prompts, reset_prompt_overrides
from pneuma_knowledge_core.prompts.lang_zh import chinese_overlay
from pneuma_knowledge_core.skill.contract import render_system_contract
from pneuma_knowledge_core.skill.pack import compose_skill
from pneuma_knowledge_core.skill.version import SkillVersion

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)
PATH = "voice/preferences.md"
FM = {"type": "preference", "slug": "preferences"}


def payload(owner_turns=1):
    turns = [
        {
            "turn_id": "o1",
            "role": "owner",
            "kind": "say",
            "at": "2026-09-07T09:00:00+08:00",
            "text": "Keep the decision rationale.",
        },
        {
            "turn_id": "a1",
            "role": "agent",
            "kind": "narrative",
            "at": "2026-09-07T09:00:01+08:00",
            "text": "I documented the rationale.\nThe examples are synthetic.",
        },
        {
            "turn_id": "a2",
            "role": "agent",
            "kind": "action",
            "at": "2026-09-07T09:00:02+08:00",
            "text": "edited docs/rationale.md",
        },
    ]
    turns.extend(
        {**turns[0], "turn_id": f"o{n + 2}", "at": "2026-09-07T09:00:03+08:00"}
        for n in range(owner_turns - 1)
    )
    return {
        "schema": "pneuma.source.agent-session/v1",
        "provider": "codex",
        "session_id": "session-001",
        "owner_id": "momo",
        "agent": {"name": "codex", "model": "synthetic-model"},
        "project": {
            "path": "/work/example",
            "name": "Example",
            "git_remote": "https://example.com/example.git",
        },
        "started_at": "2026-09-07T09:00:00+08:00",
        "ended_at": "2026-09-07T09:01:00+08:00",
        "turns": turns,
        "metadata": {"synthetic": True},
    }


def normalize(value=None, user="momo"):
    return normalize_source_contract(
        parse_source_contract(value or payload()), UserId(user), imported_at=NOW
    )[0]


def skill(flag=True):
    return SkillVersion.from_parts(
        skill_id="synthetic",
        version="v1",
        instructions="Record supported preferences.",
        path_templates=[
            {"path": "voice/{slug}.md", "owner_voice": flag},
            "work/{slug}.md",
        ],
    )


def draft(flag=True):
    s = skill(flag)
    return PatchDraft.from_canonical(
        [], s.path_templates, owner_voice_templates=s.owner_voice_templates
    )


def test_minimal_payload_and_free_provider():
    value = payload()
    for key in ["project", "ended_at", "metadata"]:
        del value[key]
    value["agent"] = {"name": "another-harness"}
    value["provider"] = "another-harness"
    value["turns"] = value["turns"][:1]
    parsed = parse_source_contract(value)
    assert isinstance(parsed, AgentSessionSource)
    assert parsed.metadata == {}
    assert normalize(value).raw.meta["provider"] == "another-harness"


@pytest.mark.parametrize(
    "role,kind", [("owner", "narrative"), ("owner", "action"), ("agent", "say")]
)
def test_role_kind_refusal(role, kind):
    value = payload()
    value["turns"][0].update(role=role, kind=kind)
    with pytest.raises(ValidationError, match="agent_session_role_kind"):
        parse_source_contract(value)


@pytest.mark.parametrize("key", ["input", "output", "result"])
@pytest.mark.parametrize(
    "location", ["turn", "metadata", "nested", "envelope", "agent", "project"]
)
def test_no_field_can_carry_tool_payloads(key, location):
    value = payload()
    target = value
    if location == "turn":
        target = value["turns"][2]
    elif location == "nested":
        value["metadata"]["provider_extras"] = [{"tool": {}}]
        target = value["metadata"]["provider_extras"][0]["tool"]
    elif location != "envelope":
        target = value[location]
    target[key] = "file bytes"
    with pytest.raises(ValidationError, match="agent_session_tool_payload"):
        parse_source_contract(value)


@pytest.mark.parametrize(
    "text", ["x" * 201, "read\nfile", "read\rfile", "read\u2028file", "read\u0085file"]
)
def test_actions_are_bounded_single_lines(text):
    value = payload()
    value["turns"][2]["text"] = text
    with pytest.raises(ValidationError, match="agent_session_action_stub"):
        parse_source_contract(value)


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("text", ["", " \n \t"])
def test_blank_turns_are_refused(index, text):
    value = payload()
    value["turns"][index]["text"] = text
    with pytest.raises(ValidationError):
        parse_source_contract(value)


@pytest.mark.parametrize("field", ["started_at", "ended_at", "at"])
def test_naive_timestamps_are_refused(field):
    value = payload()
    target = value["turns"][0] if field == "at" else value
    target[field] = "2026-09-07T09:00:00"
    with pytest.raises(ValidationError, match="explicit timezone offset"):
        parse_source_contract(value)


def test_unique_ids_owner_presence_order_and_session_end():
    for edit, kind in [
        (lambda v: v["turns"][1].update(turn_id="o1"), "duplicate_turn_ids"),
        (lambda v: v.update(turns=v["turns"][1:]), "owner_required"),
        (lambda v: v["turns"][1].update(at="2026-09-07T08:59:00+08:00"), "turn_order"),
        (lambda v: v.update(ended_at="2026-09-07T08:59:00+08:00"), "time_range"),
    ]:
        value = payload()
        edit(value)
        with pytest.raises(ValidationError, match=f"agent_session_{kind}"):
            parse_source_contract(value)
    value = payload()
    value["turns"][2]["text"] = "x" * 200
    for turn in value["turns"]:
        turn["at"] = value["started_at"]
    assert len(parse_source_contract(value).turns) == 3


@pytest.mark.parametrize(
    "edit",
    [
        lambda v: v.update(turns=[]),
        lambda v: v.update(provider=" "),
        lambda v: v.update(session_id=""),
        lambda v: v.update(owner_id=""),
        lambda v: v.update(agent={"name": ""}),
        lambda v: v.update(project={}),
        lambda v: v.update(extra=True),
        lambda v: v["agent"].update(extra=True),
        lambda v: v["turns"][0].update(role="tool"),
        lambda v: v["turns"][0].update(kind="tool"),
    ],
)
def test_invalid_shape(edit):
    value = payload()
    edit(value)
    with pytest.raises(ValidationError):
        parse_source_contract(value)


@pytest.mark.parametrize("chinese", [False, True])
def test_verbatim_normalization_labels_metadata_days_and_identity(chinese):
    if chinese:
        override_prompts(chinese_overlay())
    try:
        value = payload()
        value["turns"][2]["at"] = "2026-09-08T00:00:00+08:00"
        ns = normalize(value)
        labels = (
            ["用户", "codex", "codex 执行"]
            if chinese
            else ["User", "codex", "codex did"]
        )
        separator = "：" if chinese else ": "
        assert [b.text for b in ns.blocks] == [
            f"{label}{separator}{turn['text']}"
            for label, turn in zip(labels, value["turns"])
        ]
        assert [b.index for b in ns.blocks] == [0, 1, 2]
        assert [(s.start_block, s.end_block) for s in ns.structure.sections] == [
            (0, 1),
            (2, 2),
        ]
        assert ns.raw.meta["turns"] == [
            {k: v for k, v in t.items() if k != "text"} for t in value["turns"]
        ]
        assert ns.raw.meta["agent"] == value["agent"]
        assert ns.raw.meta["project"] == value["project"]
        assert block_authorship(ns.raw) == [
            {"index": 0, "role": "owner", "kind": "say"},
            {"index": 1, "role": "agent", "kind": "narrative"},
            {"index": 2, "role": "agent", "kind": "action"},
        ]
        assert owner_authored_blocks(ns.raw) == [0]
        assert ns.blocks[2].index_text() == ns.blocks[2].text
        assert normalize(value).raw.source_id == ns.raw.source_id
        assert normalize(value, user="other").raw.user_id == "other"
        changed = deepcopy(value)
        changed["turns"][0]["text"] += " Please."
        assert normalize(changed).raw.source_id != ns.raw.source_id
    finally:
        reset_prompt_overrides()


@pytest.mark.parametrize("count,treatment", [(2, "none"), (3, "full")])
def test_owner_count_proposal_and_library_semantic_knob(count, treatment):
    ns = normalize(payload(count))
    before = deepcopy(INTAKE_ARCHETYPES)
    plan = propose_intake(
        ns.raw.kind,
        ns.raw.source_class,
        100,
        None,
        owner_turns=len(owner_authored_blocks(ns.raw)),
    )
    assert (plan.canonical_treatment, plan.semantic_indexing) == (treatment, "full")
    assert f"{count} owner turns" in plan.rationale
    assert ("<3" if count == 2 else ">=3") in plan.rationale
    assert with_semantic_retrieval(plan, False).semantic_indexing == "none"
    assert not plan.user_confirmed
    assert INTAKE_ARCHETYPES == before


@pytest.mark.parametrize(
    "span,allowed",
    [("0", True), ("1", False), ("2", False), ("0-1", False), ("0-2", False)],
)
def test_owner_voice_is_refused_at_tool_and_gate(span, allowed):
    ns = normalize()
    body = f"Keep rationale. [cite: {ns.raw.source_id} ¶{span}]"
    d = draft()
    tools = {t.name: t for t in build_compile_tool_face(d, sources=[ns])}
    before = d.to_state()
    if allowed:
        tools["create_document"].func(path=PATH, frontmatter=FM, body=body)
        assert not run_gate(d, [ns])
    else:
        with pytest.raises(AnchorToolError, match="owner_voice"):
            tools["create_document"].func(path=PATH, frontmatter=FM, body=body)
        assert d.to_state() == before
        d.create_document(PATH, FM, body)
        assert any(v.kind == "owner_voice" for v in run_gate(d, [ns]))
        assert any(
            v.kind == "owner_voice" for v in post_write_violations(d, [ns], PATH)
        )
    assert "owner_voice" in dict(violation_catalog())


def test_unflagged_templates_keep_hash_system_bytes_and_gate_behavior():
    s = skill(False)
    legacy = SkillVersion.from_parts(
        skill_id=s.skill_id,
        version=s.version,
        instructions=s.instructions,
        path_templates=s.path_templates,
    )
    assert s.content_hash == legacy.content_hash
    assert render_system_contract(s) == render_system_contract(legacy)
    ns = normalize()
    d = draft(False)
    d.create_document(PATH, FM, f"Agent report. [cite: {ns.raw.source_id} ¶1]")
    assert not run_gate(d, [ns])
    assert skill(True).content_hash != s.content_hash
    assert compose_skill(skill(True), []).owner_voice_templates == ["voice/{slug}.md"]
    with pytest.raises(ValidationError):
        SkillVersion.from_parts(
            skill_id="x",
            version="v1",
            instructions="x",
            path_templates=[{"path": "voice/{slug}.md", "owner_voice": "false"}],
        )


def test_editing_with_a_carried_citation_is_still_checked_and_flags_survive_state():
    ns = normalize()
    d = draft()
    d.create_document(PATH, FM, f"Agent report. [cite: {ns.raw.source_id} ¶1]")
    state = d.to_state()
    state["base"] = deepcopy(state["working"])
    d = PatchDraft.from_state(state)
    assert not run_gate(d, [ns])
    anchor = extract_anchors(d.read(PATH).body)[0]
    d.edit_claim(PATH, anchor, f"The Owner thinks this. [cite: {ns.raw.source_id} ¶1]")
    assert any(v.kind == "owner_voice" for v in run_gate(d, [ns]))


def test_historical_source_authorship_and_aliases():
    ns = normalize()
    sid = str(ns.raw.source_id)
    d = draft()
    d.owner_authored_blocks[sid] = [0]
    d.create_document(PATH, FM, f"Keep rationale. [cite: s01 ¶0]")
    assert not run_gate(d, [], alias_map={"s01": sid}, known_source_bounds={sid: 3})
    d.owner_authored_blocks.clear()
    assert any(
        v.kind == "owner_voice"
        for v in run_gate(d, [], alias_map={"s01": sid}, known_source_bounds={sid: 3})
    )


def test_canonical_references_cannot_launder_agent_authorship():
    ns = normalize()
    for index, allowed in [(0, True), (1, False)]:
        d = draft()
        doc = d.create_document(
            "work/report.md",
            {"type": "report", "slug": "report"},
            f"Report. [cite: {ns.raw.source_id} ¶{index}]",
        )
        anchor = extract_anchors(doc.body)[0]
        d.create_document(PATH, FM, f"Keep rationale. c:{anchor}")
        owner_violations = [v for v in run_gate(d, [ns]) if v.kind == "owner_voice"]
        assert bool(owner_violations) != allowed


@pytest.mark.parametrize("chinese", [False, True])
def test_new_session_preamble_is_human_only_and_system_is_byte_stable(chinese):
    if chinese:
        override_prompts(chinese_overlay())
    try:
        first = normalize()
        value = payload()
        value["session_id"] = "different-session"
        value["turns"][0]["text"] = "Another decision."
        second = normalize(value)
        system1, task1 = render_compile_messages(
            sources=[first], base_docs=[], skill=skill()
        )
        system2, task2 = render_compile_messages(
            sources=[second], base_docs=[], skill=skill()
        )
        assert system1 == system2
        assert task1 != task2
        line = "这是一次编码代理会话" if chinese else "This is a coding-agent session"
        assert line in task1 and line in task2
        assert line not in system1
        assert task1.index(line) < task1.index(first.blocks[0].text)
    finally:
        reset_prompt_overrides()


@pytest.mark.parametrize("kind", ["meeting", "im", "email", "owner-dialogue"])
def test_existing_contracts_resolve_declared_owners_in_normalized_order(kind):
    at = "2026-09-07T09:00:00+08:00"
    if kind == "meeting":
        value = {
            "schema": "pneuma.source.meeting/v1",
            "provider": "mock",
            "meeting_id": "m1",
            "title": "Synthetic review",
            "started_at": at,
            "owner_participant_ids": ["momo"],
            "participants": [
                {"participant_id": "momo", "display_name": "Mei LIN"},
                {"participant_id": "other", "display_name": "Yun WU"},
            ],
            "segments": [
                {
                    "segment_id": f"s{i}",
                    "speaker_id": person,
                    "started_at": at,
                    "text": "Keep rationale.",
                }
                for i, person in [(1, "other"), (0, "momo")]
            ],
        }
    elif kind == "im":
        value = {
            "schema": "pneuma.source.im/v1",
            "provider": "mock",
            "archive_id": "im1",
            "owner_user_ids": ["momo"],
            "users": [
                {"user_id": "momo", "display_name": "Mei LIN"},
                {"user_id": "other", "display_name": "Yun WU"},
            ],
            "conversations": [
                {
                    "conversation_id": "c1",
                    "conversation_type": "dm",
                    "title": "Synthetic review",
                    "member_ids": ["momo", "other"],
                    "messages": [
                        {
                            "message_id": f"s{i}",
                            "sender_id": person,
                            "sent_at": at,
                            "text": "Keep rationale.",
                        }
                        for i, person in [(1, "other"), (0, "momo")]
                    ],
                }
            ],
        }
    elif kind == "email":
        value = {
            "schema": "pneuma.source.email/v1",
            "provider": "mock",
            "archive_id": "email1",
            "owner_addresses": ["momo@example.com"],
            "threads": [
                {
                    "thread_id": "c1",
                    "subject": "Synthetic review",
                    "messages": [
                        {
                            "message_id": f"s{i}",
                            "from": {"address": f"{person}@example.com"},
                            "to": [],
                            "cc": [],
                            "subject": "Review",
                            "sent_at": at,
                            "text": "Keep rationale.",
                        }
                        for i, person in [(1, "other"), (0, "momo")]
                    ],
                }
            ],
        }
    else:
        value = {
            "schema": "pneuma.source.owner-dialogue/v1",
            "provider": "mock",
            "dialogue_id": "d1",
            "owner_id": "momo",
            "turns": [
                {
                    "turn_id": f"s{i}",
                    "role": role,
                    "said_at": at,
                    "text": "Keep rationale.",
                }
                for i, role in [(0, "owner"), (1, "steward")]
            ],
        }
    ns = normalize(value)
    assert owner_authored_blocks(ns.raw) == [0]
    for index in [0, 1]:
        d = draft()
        d.create_document(PATH, FM, f"Preference. [cite: {ns.raw.source_id} ¶{index}]")
        assert bool([v for v in run_gate(d, [ns]) if v.kind == "owner_voice"]) == (
            index == 1
        )
    # Stored envelopes from before role stamping resolve identically, without migration.
    for key in ["segments", "messages"]:
        for item in ns.raw.meta.get(key, []):
            item.pop("role", None)
    assert owner_authored_blocks(ns.raw) == [0]


@pytest.mark.parametrize(
    "verb", ["append_block", "edit_claim", "supersede_claim", "rewrite_overview"]
)
def test_every_claim_write_refuses_agent_evidence_and_rolls_back(verb):
    ns = normalize()
    d = draft()
    doc = d.create_document(PATH, FM, f"Keep rationale. [cite: {ns.raw.source_id} ¶0]")
    anchor = extract_anchors(doc.body)[0]
    bad = f"The Owner prefers this. [cite: {ns.raw.source_id} ¶1]"
    args = {"path": PATH}
    if verb == "append_block":
        args.update(heading="Preferences", text=bad)
    elif verb == "rewrite_overview":
        args.update(definition=bad)
    else:
        args.update(anchor_id=anchor, new_text=bad)
    tools = {t.name: t for t in build_compile_tool_face(d, sources=[ns])}
    before = d.to_state()
    with pytest.raises(AnchorToolError, match="owner_voice"):
        tools[verb].func(**args)
    assert d.to_state() == before


@pytest.mark.parametrize("chinese", [False, True])
def test_owner_turns_carry_the_owner_name_when_the_contract_states_one(chinese):
    """The Owner's turns are labelled with the Owner's own name, never the id; without a
    name the catalog's neutral word stands in. The compile task's per-source line names
    the same label, so the sentence about the text and the text cannot disagree."""
    if chinese:
        override_prompts(chinese_overlay())
    try:
        named = payload()
        named["owner_name"] = "Momo"
        ns = normalize(named)
        separator = "：" if chinese else ": "
        assert ns.blocks[0].text == f"Momo{separator}{named['turns'][0]['text']}"
        assert ns.raw.meta["owner_name"] == "Momo"
        assert "momo" not in ns.blocks[0].text  # the id never reaches the text
        _, task = render_compile_messages(sources=[ns], base_docs=[], skill=skill())
        assert ("标为「Momo」" if chinese else 'labelled "Momo"') in task
        anonymous = normalize(payload())
        assert anonymous.raw.meta["owner_name"] is None
        _, task = render_compile_messages(sources=[anonymous], base_docs=[], skill=skill())
        assert ("标为「用户」" if chinese else 'labelled "User"') in task
    finally:
        reset_prompt_overrides()


@pytest.mark.parametrize("owner_name", ["", "   ", "two\nlines"])
def test_a_blank_or_multiline_owner_name_is_refused(owner_name):
    value = payload()
    value["owner_name"] = owner_name
    with pytest.raises(ValidationError):
        normalize(value)
