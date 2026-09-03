"""`owner-dialogue/v1`: the owner's own statement, as an ordinary source.

The whole point of the contract is that nothing about it is special — L0 verbatim, one
block per turn, `[cite: <sid> ¶n]`, the same gate. What IS different is legibility: the
blocks read like a transcript and are not one, so the framework's own per-source line
states the kind. These tests pin both halves: the ordinariness, and the one difference.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pneuma_knowledge_core.compile.runner import _render_task
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.intake import archetype_of, propose_intake
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import (
    OwnerDialogueSource,
    parse_source_contract,
)
from pneuma_knowledge_core.ingest.source_types import describe_source

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)


def _payload(**overrides) -> dict:
    payload = {
        "schema": "pneuma.source.owner-dialogue/v1",
        "provider": "console",
        "dialogue_id": "dlg-0831",
        "owner_id": "app-owner-7",
        "steward_id": "app-steward-1",
        "turns": [
            {
                "turn_id": "t1",
                "role": "owner",
                "said_at": "2026-08-31T09:00:00+08:00",
                "text": "The Aurora deadline moved to 2026-09-30.",
            },
            {
                "turn_id": "t2",
                "role": "steward",
                "said_at": "2026-08-31T09:00:20+08:00",
                "text": "Understood. Which page holds it today?",
            },
            {
                "turn_id": "t3",
                "role": "owner",
                "said_at": "2026-08-31T09:00:40+08:00",
                "text": "The Aurora product page. The old date came from the review.",
            },
        ],
        "metadata": {"channel": "console"},
    }
    payload.update(overrides)
    return payload


def _normalize(payload: dict):
    return normalize_source_contract(
        parse_source_contract(payload), UserId("u-owner-test"), imported_at=NOW
    )


# ────────────────────────────────────────────────────────────────────── the contract


def test_a_good_dialogue_parses_as_the_fifth_official_contract():
    contract = parse_source_contract(_payload())
    assert isinstance(contract, OwnerDialogueSource)
    assert contract.contract_schema == "pneuma.source.owner-dialogue/v1"
    assert [turn.role for turn in contract.turns] == ["owner", "steward", "owner"]


def test_duplicate_turn_ids_are_rejected():
    payload = _payload()
    payload["turns"][1]["turn_id"] = "t1"
    with pytest.raises(ValidationError, match="duplicate turn ids"):
        parse_source_contract(payload)


def test_a_naive_timestamp_is_rejected():
    payload = _payload()
    payload["turns"][0]["said_at"] = "2026-08-31T09:00:00"
    with pytest.raises(ValidationError, match="explicit timezone offset"):
        parse_source_contract(payload)


def test_turns_that_go_backwards_are_rejected_rather_than_sorted():
    """Where this contract parts from `im/v1`, deliberately.

    A provider archive's order is an artefact of the export, so IM sorts. A dialogue's
    order IS its meaning — "the old date came from the review" qualifies the sentence
    before it and stops qualifying it once the two are swapped — so a payload that
    disagrees with itself is refused instead of silently rearranged.
    """
    payload = _payload()
    payload["turns"][2]["said_at"] = "2026-08-31T08:59:00+08:00"
    with pytest.raises(ValidationError, match="timestamped before"):
        parse_source_contract(payload)


def test_equal_timestamps_are_allowed_because_only_a_decrease_is_a_contradiction():
    payload = _payload()
    for turn in payload["turns"]:
        turn["said_at"] = "2026-08-31T09:00:00+08:00"
    assert parse_source_contract(payload).turns[2].turn_id == "t3"


def test_a_dialogue_of_steward_turns_alone_is_not_the_owners_statement():
    """The one thing this contract asserts about its own material.

    Everything downstream reads a payload here as the subject speaking for themselves:
    the normalizer labels the turns by role, the compile task's per-source line names
    the kind, and the intake proposal gives it full canonical treatment on that basis.
    A dialogue of `steward` turns alone is a document the steward wrote ABOUT the owner
    — compiled under this contract it would make steward-written text the owner's
    canonical knowledge, which no gate downstream can catch because every citation
    resolves. So it is refused at the contract.
    """
    payload = _payload()
    for turn in payload["turns"]:
        turn["role"] = "steward"
    with pytest.raises(ValidationError, match="at least one turn spoken by the owner"):
        parse_source_contract(payload)

    # One owner turn anywhere in it is enough — the contract asks who spoke, not how much.
    payload["turns"][1]["role"] = "owner"
    assert parse_source_contract(payload).turns[1].role == "owner"


def test_a_blank_owner_turn_satisfies_the_rule_only_as_a_formality_and_is_refused():
    """The gap the role check alone left open.

    A payload of steward turns plus one EMPTY owner turn passed: something was labelled
    `owner`, so the rule was formally met — while the dialogue was still, materially, the
    steward writing about the owner, and the blank turn could not become a block of L0
    anyone could cite. A turn nobody spoke is not a turn, so it is refused by the turn it
    is, naming it and its role, rather than filtered away as though the payload had never
    claimed it.
    """
    payload = _payload()
    for turn in payload["turns"]:
        turn["role"] = "steward"
    payload["turns"][0]["role"] = "owner"
    payload["turns"][0]["text"] = "   \n "
    with pytest.raises(ValidationError, match="'t1' \\(owner\\) has no text"):
        parse_source_contract(payload)

    # A blank STEWARD turn is refused on the same terms — the reason is the empty turn,
    # not who was supposed to have spoken it.
    payload["turns"][0]["text"] = "供应商把交期从两周缩短到五天。"
    payload["turns"][1]["text"] = ""
    with pytest.raises(ValidationError, match="'t2' \\(steward\\) has no text"):
        parse_source_contract(payload)


def test_an_unknown_role_or_an_unknown_field_is_rejected():
    payload = _payload()
    payload["turns"][0]["role"] = "visitor"
    with pytest.raises(ValidationError):
        parse_source_contract(payload)
    payload = _payload(escalate=True)
    with pytest.raises(ValidationError):
        parse_source_contract(payload)


# ─────────────────────────────────────────────────────────────────── normalization


def test_one_block_per_turn_labelled_by_role_with_the_ids_kept_out_of_the_text():
    [normalized] = _normalize(_payload())
    raw = normalized.raw
    assert raw.kind == "owner_dialogue"
    assert raw.origin == "console"
    assert [block.text for block in normalized.blocks] == [
        "Owner: The Aurora deadline moved to 2026-09-30.",
        "Steward: Understood. Which page holds it today?",
        "Owner: The Aurora product page. The old date came from the review.",
    ]
    # The application's own ids are envelope, never text: the compiler is shown a role.
    body = "\n".join(block.text for block in normalized.blocks)
    assert "app-owner-7" not in body and "app-steward-1" not in body
    assert raw.meta["owner_id"] == "app-owner-7"
    assert raw.meta["steward_id"] == "app-steward-1"
    assert raw.meta["turns"] == [
        {"turn_id": "t1", "role": "owner", "said_at": "2026-08-31T09:00:00+08:00"},
        {"turn_id": "t2", "role": "steward", "said_at": "2026-08-31T09:00:20+08:00"},
        {"turn_id": "t3", "role": "owner", "said_at": "2026-08-31T09:00:40+08:00"},
    ]


def test_one_dialogue_stays_one_source_dated_by_its_own_turns():
    """No expansion boundary: a statement is one statement. And `occurred_on` is the day
    it was SAID, never the ingest wall clock (`imported_at` here is a different day)."""
    normalized = _normalize(_payload())
    assert len(normalized) == 1
    assert normalized[0].raw.occurred_on() == "2026-08-31"
    assert [block.section_path for block in normalized[0].blocks] == [["2026-08-31"]] * 3


def test_the_source_id_is_content_addressed_like_every_other_contract():
    first = _normalize(_payload())[0].raw
    same = _normalize(_payload())[0].raw
    changed = _payload()
    changed["turns"][0]["text"] = "The Aurora deadline moved to 2026-10-31."
    other = _normalize(changed)[0].raw
    assert first.source_id == same.source_id
    assert first.source_id != other.source_id


# ────────────────────────────────────────────────────────────────────────── intake


def test_an_owner_statement_is_compiled_in_full_and_indexed_in_full():
    raw = _normalize(_payload())[0].raw
    plan = propose_intake(raw.kind, raw.source_class, 200, None)
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("full", "full")
    assert archetype_of(plan) == "digest"
    assert "owner dialogue" in plan.rationale


# ──────────────────────────────────────────────── the framework's per-source line


def test_the_compile_task_states_the_kind_above_the_blocks():
    [normalized] = _normalize(_payload())
    sentence = describe_source(normalized.raw, len(normalized.blocks), "Mei LIN")
    # The kind, in the framework's own line — not a component's preamble, and not a
    # sentence in a contract body asking the model to remember something.
    assert "speaking to this library directly" in sentence
    assert "not a record of an event" in sentence
    assert "2026-08-31" in sentence  # the statement's own day
    task = _render_task(
        [normalized], [], source_preamble={str(normalized.raw.source_id): sentence}
    )
    assert task.index(sentence) < task.index("¶0 Owner:")


def test_a_dialogue_the_framework_could_not_date_still_states_the_kind():
    [normalized] = _normalize(_payload())
    normalized.raw.meta = {
        key: value
        for key, value in normalized.raw.meta.items()
        if key != "occurred_on"
    }
    sentence = describe_source(normalized.raw, len(normalized.blocks), "Mei LIN")
    assert "speaking to this library directly" in sentence
    assert "resolves against" not in sentence
