"""The published `owner-dialogue/v1` JSON Schema and the runtime validator, held together.

The schema under `docs/reference/source-contracts/` is what an application integrates
against: it is the face that says what a payload may be before anyone writes the code that
sends one. The pydantic model in core is what actually decides. Two faces of one contract,
maintained by hand, are two chances to state the rule — and the whitespace-only turn is what
drift looks like when it happens. `minLength: 1` admitted `"   \\n "`; the runtime refused it
with `.strip()`. An integrator reading the schema built a payload the schema called valid and
the API rejected, and nothing in either face could have told them which one was wrong.

So the cases below drive both faces over the same payloads and assert they answer alike.

What is deliberately NOT mirrored is pinned too, at the bottom: uniqueness, spoken order and
an explicit timezone offset are relational rules JSON Schema has no vocabulary for. The
schema is therefore a strict weakening — it never refuses what the runtime accepts — and a
payload that passes it may still be refused at the boundary. Pinning that keeps the gap a
known one rather than the next thing somebody discovers in a review.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "reference"
    / "source-contracts"
    / "owner-dialogue-v1.schema.json"
)


def _payload(**overrides) -> dict:
    payload = {
        "schema": "pneuma.source.owner-dialogue/v1",
        "provider": "console",
        "dialogue_id": "dlg-0902",
        "owner_id": "app-owner-7",
        "steward_id": "app-steward-1",
        "turns": [
            {
                "turn_id": "t1",
                "role": "owner",
                "said_at": "2026-09-02T09:00:00+08:00",
                "text": "The Aurora deadline moved to 2026-09-30.",
            },
            {
                "turn_id": "t2",
                "role": "steward",
                "said_at": "2026-09-02T09:00:20+08:00",
                "text": "Understood. Which page holds it today?",
            },
        ],
        "metadata": {"channel": "console"},
    }
    payload.update(overrides)
    return payload


def _schema_accepts(payload: dict) -> bool:
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text("utf-8")))
    return not list(validator.iter_errors(payload))


def _runtime_accepts(payload: dict) -> bool:
    try:
        parse_source_contract(payload)
    except ValidationError:
        return False
    return True


def _blank(text: str) -> dict:
    payload = _payload()
    payload["turns"][0]["text"] = text
    return payload


#: One payload per rule both faces are supposed to state, and the rule it breaks.
REFUSED: list[tuple[str, dict]] = [
    ("a whitespace-only owner turn", _blank("   \n ")),
    ("an owner turn of one space", _blank(" ")),
    ("an empty owner turn", _blank("")),
    (
        "a dialogue of steward turns alone",
        _payload(
            turns=[
                {**turn, "role": "steward"} for turn in _payload()["turns"]
            ]
        ),
    ),
    ("a turn with no text field at all", _payload(turns=[
        {
            "turn_id": "t1",
            "role": "owner",
            "said_at": "2026-09-02T09:00:00+08:00",
        }
    ])),
    ("a role nobody in this contract has", _payload(turns=[
        {**_payload()["turns"][0], "role": "visitor"}
    ])),
    ("a field the contract does not declare", _payload(escalate=True)),
    ("no turns at all", _payload(turns=[])),
    ("a provider outside the enum", _payload(provider="whatsapp")),
    ("the wrong schema discriminator", _payload(schema="pneuma.source.im/v1")),
    ("a dialogue with no id", _payload(dialogue_id="")),
]


@pytest.mark.parametrize("why,payload", REFUSED, ids=[why for why, _ in REFUSED])
def test_the_two_faces_refuse_the_same_payloads(why: str, payload: dict):
    assert not _schema_accepts(payload), f"the schema admitted {why}"
    assert not _runtime_accepts(payload), f"the runtime admitted {why}"


def test_the_two_faces_accept_the_same_payload():
    """The control: without it, a schema that refuses everything would pass the row above."""
    assert _schema_accepts(_payload())
    assert _runtime_accepts(_payload())

    # A `steward_id` is optional and may be explicitly null — the console has one, a mock
    # provider replaying a monologue need not.
    assert _schema_accepts(_payload(steward_id=None))
    assert _runtime_accepts(_payload(steward_id=None))


#: Rules the runtime states and JSON Schema cannot: they are relations BETWEEN turns, or a
#: property of a timestamp's text that `format: date-time` does not constrain.
BEYOND_THE_SCHEMA: list[tuple[str, dict]] = [
    (
        "duplicate turn ids",
        _payload(
            turns=[
                _payload()["turns"][0],
                {**_payload()["turns"][1], "turn_id": "t1"},
            ]
        ),
    ),
    (
        "turns that go backwards",
        _payload(
            turns=[
                _payload()["turns"][0],
                {**_payload()["turns"][1], "said_at": "2026-09-02T08:59:00+08:00"},
            ]
        ),
    ),
    (
        "a naive timestamp",
        _payload(
            turns=[
                {**_payload()["turns"][0], "said_at": "2026-09-02T09:00:00"},
                _payload()["turns"][1],
            ]
        ),
    ),
]


@pytest.mark.parametrize(
    "why,payload", BEYOND_THE_SCHEMA, ids=[why for why, _ in BEYOND_THE_SCHEMA]
)
def test_the_schema_is_a_weakening_and_says_so_only_here(why: str, payload: dict):
    """Not drift — the boundary of the vocabulary. Recorded so the gap is known, and so a
    schema that one day CAN say these things fails here rather than passing silently."""
    assert _schema_accepts(payload), f"the schema unexpectedly refused {why}"
    assert not _runtime_accepts(payload), f"the runtime admitted {why}"
