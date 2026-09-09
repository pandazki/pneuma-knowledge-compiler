"""`pkc owner say` and `pkc ingest` — the two ways material enters (§5.3, §5.4).

Owner speech has exactly one shape and it is a source: the statement lands in L0 verbatim as
`¶0`, one compile job is enqueued, and `--about` reaches that job's source guidance. There is
no command that changes a claim without a job, and these tests are what makes that a fact
about the code rather than a sentence in a skill.

`pkc ingest` is the same import the HTTP route performs, so the test that matters is that it
IS the same import: the same validation, the same content-stable source ids, the same
refusals — and one refusal of its own, for a contract name that is not one of the five.
"""

from __future__ import annotations

import io
import json
from pneuma_knowledge_service.cli import ingest as ingest_cmd
from pneuma_knowledge_service.cli import owner as owner_cmd
from pneuma_knowledge_service.ingest_sources import ingest_source_contract
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract

from _cli_library import USER, library

PAGE = "memory/topics/pricing.md"

STATEMENT = "Seats are 25 now, not 20.\nThe change took effect on 2026-08-01."


def _payload(kind: str) -> dict:
    """One minimal payload per contract family, in the shape the route's own tests use."""
    if kind == "agent-session/v1":
        return {
            "schema": "pneuma.source.agent-session/v1",
            "provider": "codex", "session_id": "session-001", "owner_id": "momo",
            "agent": {"name": "codex"}, "started_at": "2026-09-07T09:00:00+08:00",
            "turns": [{"turn_id": "t1", "role": "owner", "kind": "say",
                       "at": "2026-09-07T09:00:00+08:00", "text": "Keep the rationale."}],
        }
    if kind == "meeting/v1":
        return {
            "schema": "pneuma.source.meeting/v1",
            "provider": "mock",
            "meeting_id": "m-1",
            "title": "pricing review",
            "started_at": "2026-08-01T09:00:00+00:00",
            "participants": [{"participant_id": "p1", "display_name": "Cheng Ye"}],
            "segments": [
                {
                    "segment_id": "sg1",
                    "speaker_id": "p1",
                    "started_at": "2026-08-01T09:00:05+00:00",
                    "text": "Seats are 25 now.",
                }
            ],
        }
    if kind == "document-library/v1":
        return {
            "schema": "pneuma.source.document-library/v1",
            "provider": "mock",
            "library_id": "lib-1",
            "title": "vault",
            "documents": [
                {
                    "document_id": "n1",
                    "path": "notes/pricing.md",
                    "title": "pricing",
                    "content": "Seats are 25 now.",
                    "frontmatter": {},
                    "tags": [],
                    "links": [],
                }
            ],
        }
    if kind == "im/v1":
        return {
            "schema": "pneuma.source.im/v1",
            "provider": "mock",
            "archive_id": "w-1",
            "owner_user_ids": ["p1"],
            "users": [{"user_id": "p1", "display_name": "Cheng Ye"}],
            "conversations": [
                {
                    "conversation_id": "c1",
                    "conversation_type": "channel",
                    "title": "pricing",
                    "member_ids": ["p1"],
                    "messages": [
                        {
                            "message_id": "msg1",
                            "sender_id": "p1",
                            "sent_at": "2026-08-01T09:00:00+00:00",
                            "text": "Seats are 25 now.",
                        }
                    ],
                }
            ],
        }
    if kind == "email/v1":
        return {
            "schema": "pneuma.source.email/v1",
            "provider": "mock",
            "archive_id": "mb-1",
            "owner_addresses": ["a@example.test"],
            "threads": [
                {
                    "thread_id": "t1",
                    "subject": "pricing",
                    "messages": [
                        {
                            "message_id": "e1",
                            "from": {"address": "a@example.test"},
                            "to": [{"address": "b@example.test"}],
                            "cc": [],
                            "sent_at": "2026-08-01T09:00:00+00:00",
                            "subject": "pricing",
                            "text": "Seats are 25 now.",
                        }
                    ],
                }
            ],
        }
    return {
        "schema": "pneuma.source.owner-dialogue/v1",
        "provider": "mock",
        "dialogue_id": "d-1",
        "owner_id": str(USER),
        "turns": [
            {
                "turn_id": "t1",
                "role": "owner",
                "said_at": "2026-08-01T09:00:00+00:00",
                "text": "Seats are 25 now.",
            }
        ],
    }


async def _say(lib, text, *, about=None, as_json=True):
    out, err = io.StringIO(), io.StringIO()
    code = await owner_cmd.cmd_owner_say(
        lib.ctx,
        USER,
        text=text,
        about=about,
        said_at="2026-08-01T09:00:00+00:00",
        as_json=as_json,
        out=out,
        err=err,
    )
    return code, out.getvalue(), err.getvalue()


# ─────────────────────────────────────────────────────────────────── owner say


async def test_owner_say_lands_the_statement_in_L0_verbatim_as_one_block():
    lib = library()
    code, out, _err = await _say(lib, STATEMENT + "\n")
    assert code == 0
    payload = json.loads(out)
    source_id = payload["sources"][0]["source_id"]
    stored = await lib.store.get(USER, source_id)
    # Verbatim: the trailing newline a heredoc adds is the only thing removed. The block
    # carries the framework's own role label in front of it — a role, never an id — and the
    # Owner's words are byte-for-byte what was typed.
    assert len(stored.blocks) == 1
    assert stored.blocks[0].index == 0
    assert stored.blocks[0].text.endswith(STATEMENT)
    assert len(payload["compile_jobs"]) == 1


async def test_owner_say_enqueues_one_compile_and_about_reaches_its_source_guidance():
    lib = library()
    code, out, _err = await _say(lib, STATEMENT, about=[PAGE])
    assert code == 0
    job_id = json.loads(out)["compile_jobs"][0]
    job = await lib.store.get_job(USER, job_id)
    assert job.payload["about_paths"] == [PAGE]

    # …and the job's payload is what the compile round's source guidance is built from.
    from pneuma_knowledge_service.workers.compile_worker import compile_inputs

    lib.ctx.settings.context_stream_compile_guidance = True
    inputs = await compile_inputs(lib.ctx, USER, job)
    guidance = "\n".join(inputs.source_guidance.values())
    assert PAGE in guidance


async def test_a_blank_statement_is_refused_in_the_contracts_own_words_and_writes_nothing():
    lib = library()
    code, _out, err = await _say(lib, "   \n\n")
    assert code == 2
    assert "a turn nobody spoke" in err
    assert await lib.store.list(USER) == []
    assert lib.store.jobs == []


async def test_saying_the_same_thing_twice_records_it_once():
    lib = library()
    _code, first, _err = await _say(lib, STATEMENT)
    _code, again, _err = await _say(lib, STATEMENT)
    first_id = json.loads(first)["sources"][0]["source_id"]
    # A repeated statement is the same content, so it is the same source, and the second
    # import enqueues nothing.
    assert json.loads(again)["sources"][0]["source_id"] == first_id
    assert json.loads(again)["compile_jobs"] == []


# ────────────────────────────────────────────────────────────────────── ingest


async def _ingest(lib, contract, payload, **kw):
    out, err = io.StringIO(), io.StringIO()
    code = await ingest_cmd.cmd_ingest(
        lib.ctx,
        USER,
        contract_name=contract,
        payload_text=json.dumps(payload),
        as_json=True,
        out=out,
        err=err,
        **kw,
    )
    return code, out.getvalue(), err.getvalue()


async def test_every_contract_family_goes_through_and_produces_the_routes_own_source_ids():
    for name in ingest_cmd.CONTRACTS:
        payload = _payload(name)

        through_cli = library()
        code, out, err = await _ingest(through_cli, name, payload)
        assert code == 0, (name, err)

        # The same payload through the service function the route calls — the ids must be
        # the same ids, because a source's identity is its content and not its door.
        through_route = library()
        expected = await ingest_source_contract(
            through_route.ctx, USER, parse_source_contract(payload)
        )
        assert [s["source_id"] for s in json.loads(out)["sources"]] == [
            str(i.source_id) for i in expected.sources
        ], name


async def test_an_unknown_contract_is_refused_by_name_before_the_payload_is_read():
    lib = library()
    out, err = io.StringIO(), io.StringIO()
    code = await ingest_cmd.cmd_ingest(
        lib.ctx,
        USER,
        contract_name="slack/v1",
        payload_text="{ this is not even JSON",
        as_json=True,
        out=out,
        err=err,
    )
    assert code == 2
    assert "unknown contract 'slack/v1'" in err.getvalue()
    assert "meeting/v1" in err.getvalue()


async def test_a_payload_that_declares_another_contract_is_refused():
    lib = library()
    code, _out, err = await _ingest(lib, "im/v1", _payload("email/v1"))
    assert code == 2
    assert "the two must agree" in err


async def test_the_intake_override_replaces_the_proposal():
    lib = library()
    code, out, _err = await _ingest(lib, "meeting/v1", _payload("meeting/v1"), intake="archive")
    assert code == 0
    plan = json.loads(out)["sources"][0]["intake_plan"]
    from pneuma_knowledge_core.domain.intake import plan_for_archetype

    assert plan["canonical_treatment"] == plan_for_archetype("archive").canonical_treatment

    lib = library()
    code, _out, err = await _ingest(lib, "meeting/v1", _payload("meeting/v1"), intake="nope")
    assert code == 2
    assert "unknown intake archetype" in err
