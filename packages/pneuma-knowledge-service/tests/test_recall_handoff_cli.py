"""`pkc recall --evidence` and `pkc consult answer` — the hand-over, and what closes it.

The claim under test is one claim, made twice: what `--evidence` prints is what the answering
model would have received, byte for byte. Once against the lane's own model-free half
(`fast_recall(evidence_only=True)`), and once against a RECORDING model driven through the
whole lane — the second is the one that would catch a rendering the CLI invented, because it
compares against a message an answering call actually carried.

Then the other half: a hand-over becomes a consultation only when someone answers it, through
the fast lane's own builder, under the fast lane's own citation rule, out the same emission
`/recall` uses.
"""

from __future__ import annotations

import io
from unittest.mock import Mock

import pytest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from pneuma_knowledge_core.domain.ids import SourceId
from pneuma_knowledge_core.recall.fast import fast_recall, message_text
from pneuma_knowledge_service.cli import consult as consult_cmd
from pneuma_knowledge_service.cli import read as read_cmd

from _cli_library import USER, LexHit, VecHit, document, library, source

PAGE = "memory/topics/pricing.md"
QUESTION = "what do seats cost?"


@dataclass
class ClaimStub:
    anchor: str
    document_path: str
    text: str
    section_path: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    score: float = 1.0


class ClaimIndex:
    """Satisfies both claim faces (`search_claims`), like the core fast-lane tests' own."""

    def __init__(self, claims: list[ClaimStub]) -> None:
        self._claims = claims

    async def search_claims(  # noqa: ANN001
        self, user_id, query_or_embedding, *, limit=40, include_archived=False
    ):
        # The port's own keyword (docs/design/archive.md §3): the lane passes it only on an
        # `include_archived` call, and a double that could not take it would refuse the one
        # scope this file's last two tests are about.
        return list(self._claims[:limit])


class RecordingModel(GenericFakeChatModel):
    """The answering model, plus the message lists it was handed. The comparison this file
    makes is against what the lane actually SENT, so the sent messages have to be readable."""

    seen: list = []

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        RecordingModel.seen.append(list(messages))
        return await super()._agenerate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )


def _lib(model=None):
    lib = library(
        docs=[
            document(
                PAGE,
                "## Pricing\n\n- Seats cost 20. [cite: s-01 ¶1] <!-- c:aaa1 -->\n",
            )
        ],
        lexical_hits=[LexHit(source_id=SourceId("s-01"), block_index=1, text="20 a seat")],
        vector_hits=[
            VecHit(source_id=SourceId("s-01"), block_start=1, block_end=1, text="20 a seat")
        ],
    )
    claims = ClaimIndex(
        [
            ClaimStub(
                anchor="aaa1",
                document_path=PAGE,
                text="Seats cost 20. [cite: s-01 ¶1]",
                citations=[],
            )
        ]
    )
    lib.ctx.lexical = _Both(lib.lexical, claims)
    lib.ctx.vectors = _Both(lib.vectors, claims)
    lib.ctx.get_chat_model = (lambda role="default": model) if model else lib.ctx.get_chat_model
    return lib


class _Both:
    """One object wearing both faces the lane asks of an index: the body search and the
    claim search. The real adapters do exactly this."""

    def __init__(self, body, claims) -> None:  # noqa: ANN001
        self._body, self._claims = body, claims

    async def search(self, *a, **kw):  # noqa: ANN001
        return await self._body.search(*a, **kw)

    async def search_claims(self, *a, **kw):  # noqa: ANN001
        return await self._claims.search_claims(*a, **kw)


def _rt(lib, *, as_json=False):
    return read_cmd.ReadRuntime(
        user_id=USER,
        ctx=lib.ctx,
        as_json=as_json,
        out=io.StringIO(),
        err=io.StringIO(),
    )


async def _seed(lib):
    await lib.store.add(
        USER, source("s-01", blocks=["intro", "20 a seat", "renewal terms"])
    )


# ─────────────────────────────────────────────────── the evidence face is the lane's


@pytest.mark.parametrize("strategy", ["ranked", "select", "all"])
async def test_reading_never_builds_a_chat_model_or_materializes_schema(strategy, monkeypatch):
    """Even a keyed deployment with fresh packs and model-assisted selection reads directly."""
    from pneuma_knowledge_service import skills

    lib = _lib()
    await _seed(lib)
    lib.ctx.settings.user_schema_packs = True
    lib.ctx.settings.recall_evidence_strategy = strategy
    lib.ctx.settings.recall_plan_queries = 3
    lib.ctx.settings.semantic_retrieval = "off"
    lib.ctx.embeddings = lib.ctx.vectors = None
    build_model = Mock(side_effect=AssertionError("reading constructed a chat model"))
    resolve_writable = Mock(side_effect=AssertionError("reading resolved a writable schema"))
    lib.ctx.get_chat_model = build_model
    monkeypatch.setattr(skills, "skill_for_user", resolve_writable)

    assert await read_cmd.cmd_glance(_rt(lib)) == 0
    rt = _rt(lib, as_json=True)
    assert await read_cmd.cmd_recall_evidence(rt, QUESTION, handoffs=lib.handoffs) == 0
    import json

    evidence = json.loads(rt.out.getvalue())
    assert evidence["evidence_manifest"]
    handle = next(h for h, sid in evidence["handles"].items() if sid == "s-01")
    code, _out, _err = await _answer(
        lib, evidence["handoff_id"], f"20 a seat. [cite: {handle} ¶1]"
    )
    assert code == 0 and lib.store.consultations
    # The read path absorbs optional failures; assert calls as well as raising so a
    # swallowed AssertionError cannot masquerade as model-free execution.
    build_model.assert_not_called()
    resolve_writable.assert_not_called()


async def test_evidence_prints_exactly_what_the_lane_would_hand_its_model():
    lib = _lib()
    await _seed(lib)
    rt = _rt(lib)
    when = datetime(2026, 9, 1, tzinfo=timezone.utc)

    code = await read_cmd.cmd_recall_evidence(
        rt, QUESTION, handoffs=lib.handoffs, as_of=when.isoformat()
    )
    assert code == 0
    printed = rt.out.getvalue()

    # The lane's own model-free half, called directly with the same inputs.
    evidence = await fast_recall(
        USER,
        QUESTION,
        evidence_only=True,
        **await read_cmd._fast_kwargs(rt, as_of=when, style=None),
    )
    assert message_text(evidence.content) in printed
    assert evidence.manifest  # the lane put something in front of a model


async def test_the_evidence_is_byte_for_byte_the_human_message_the_answer_call_carries():
    """The claim that matters, checked against a real answering call rather than against
    another call to the same function."""
    RecordingModel.seen = []
    model = RecordingModel(messages=iter([AIMessage(content="20 a seat. [cite: s01 ¶1]")]))
    lib = _lib(model)
    await _seed(lib)
    rt = _rt(lib)
    when = datetime(2026, 9, 1, tzinfo=timezone.utc)
    kwargs = await read_cmd._fast_kwargs(rt, as_of=when, style=None)

    evidence = await fast_recall(USER, QUESTION, evidence_only=True, **dict(kwargs))
    await fast_recall(USER, QUESTION, **dict(kwargs))

    human = RecordingModel.seen[-1][-1]
    assert message_text(human.content) == message_text(evidence.content)
    assert RecordingModel.seen[-1][0].content == evidence.system


async def test_evidence_records_a_pending_handoff_and_no_consultation():
    lib = _lib()
    await _seed(lib)
    rt = _rt(lib, as_json=True)
    code = await read_cmd.cmd_recall_evidence(
        rt, QUESTION, handoffs=lib.handoffs, visitor_class="business"
    )
    assert code == 0
    import json

    handoff_id = json.loads(rt.out.getvalue())["handoff_id"]
    state = await lib.handoffs.get(USER, handoff_id)
    assert state["question"] == QUESTION
    assert state["visitor_class"] == "business"
    assert state["manifest"]
    # Nothing is a consultation yet — that is the whole point of the pending row.
    assert lib.store.consultations == []


# ─────────────────────────────────────────────────────────── closing the hand-over


async def _handoff(lib, *, visitor_class="business"):
    rt = _rt(lib, as_json=True)
    await read_cmd.cmd_recall_evidence(
        rt, QUESTION, handoffs=lib.handoffs, visitor_class=visitor_class
    )
    import json

    payload = json.loads(rt.out.getvalue())
    return payload["handoff_id"], payload["handles"], payload["evidence_manifest"]


async def _answer(lib, handoff_id, text, *, kind="answer"):
    out, err = io.StringIO(), io.StringIO()
    code = await consult_cmd.cmd_consult_answer(
        lib.ctx,
        USER,
        handoff_id,
        handoffs=lib.handoffs,
        text=text,
        kind=kind,
        as_json=True,
        out=out,
        err=err,
    )
    return code, out.getvalue(), err.getvalue()


async def test_an_invented_span_refuses_the_answer_and_preserves_the_handoff():
    lib = _lib()
    await _seed(lib)
    handoff_id, handles, manifest = await _handoff(lib)
    # The handle the lane minted for the one source it surfaced.
    handle = next(h for h, real in handles.items() if real == "s-01")
    spans = [row["ref"] for row in manifest if row["ref"].startswith("s-01 ")]
    assert spans, "the lane handed at least one span of s-01"

    code, out, err = await _answer(
        lib, handoff_id, f"20 a seat. [cite: {handle} ¶1] [cite: {handle} ¶999]",
    )
    assert code == 4 and not out
    assert "s-01 ¶999" in err
    assert not lib.store.consultations and not lib.store.projection_jobs
    assert await lib.handoffs.get(USER, handoff_id) is not None
    # Correct the answer against the same hand-over: exactly one question, one record.
    code, _out, _err = await _answer(lib, handoff_id, f"20 a seat. [cite: {handle} ¶1]")
    assert code == 0
    assert len(lib.store.consultations) == len(lib.store.projection_jobs) == 1


async def test_answering_writes_the_record_the_lane_would_have_and_closes_the_handoff():
    lib = _lib()
    await _seed(lib)
    handoff_id, handles, _manifest = await _handoff(lib)
    handle = next(h for h, real in handles.items() if real == "s-01")

    code, _out, _err = await _answer(lib, handoff_id, f"20 a seat. [cite: {handle} ¶1]")
    assert code == 0
    row = lib.store.consultations[-1]
    assert row["question"] == QUESTION
    assert row["answer_kind"] == "answer"
    assert row["miss"] is False
    # The handle never reaches the record: it is valid for exactly one call.
    assert handle not in row["answer"]
    assert "s-01" in row["answer"]
    assert await lib.handoffs.get(USER, handoff_id) is None


async def test_a_no_record_answer_is_recorded_as_a_miss_the_way_the_lane_would():
    lib = _lib()
    await _seed(lib)
    handoff_id, _handles, _manifest = await _handoff(lib)
    code, _out, _err = await _answer(
        lib, handoff_id, "the library holds nothing about this", kind="no_record"
    )
    assert code == 0
    assert lib.store.consultations[-1]["miss"] is True


async def test_business_enqueues_one_projection_job_and_silent_enqueues_none():
    lib = _lib()
    await _seed(lib)
    handoff_id, handles, _m = await _handoff(lib, visitor_class="business")
    handle = next(h for h, real in handles.items() if real == "s-01")
    await _answer(lib, handoff_id, f"20. [cite: {handle} ¶1]")
    assert len(lib.store.projection_jobs) == 1

    quiet = _lib()
    await _seed(quiet)
    handoff_id, handles, _m = await _handoff(quiet, visitor_class="silent")
    handle = next(h for h, real in handles.items() if real == "s-01")
    await _answer(quiet, handoff_id, f"20. [cite: {handle} ¶1]")
    assert quiet.store.projection_jobs == []
    # Silent leaves nothing at all — not a row, not a job.
    assert quiet.store.consultations == []


async def test_an_unknown_or_expired_handoff_exits_one():
    lib = _lib()
    code, _out, err = await _answer(lib, "nope", "anything")
    assert code == 1
    assert "no pending handoff" in err


async def test_an_empty_answer_is_refused_rather_than_recorded_as_a_miss():
    lib = _lib()
    await _seed(lib)
    handoff_id, _handles, _m = await _handoff(lib)
    code, _out, err = await _answer(lib, handoff_id, "   \n")
    assert code == 2
    assert "no_record" in err
    # Refused BEFORE anything was written, and the hand-over is still open.
    assert lib.store.consultations == []
    assert await lib.handoffs.get(USER, handoff_id) is not None


# ───────────────────────────────────── what the call leaves behind, and who is told (B7)


def _recall_args(**fields):
    import argparse

    return argparse.Namespace(**{"visitor_class": None, "evidence": False, **fields})


def test_the_two_recall_faces_default_to_different_visitor_classes():
    """A Steward followed exactly what the CLI printed, answered the handoff, and found
    `pkc consultations` empty — the use-side ledger silently not filling. `--evidence` hands
    the context to someone about to answer the Owner with it, which IS the library being
    used; `pkc recall` prints its own answer to whoever typed it, which is the lane being
    evaluated."""
    from pneuma_knowledge_service.cli import recall_visitor_class

    assert recall_visitor_class(_recall_args(evidence=True)) == "business"
    assert recall_visitor_class(_recall_args(evidence=False)) == "silent"
    # Stated always wins, in both directions.
    assert recall_visitor_class(_recall_args(evidence=True, visitor_class="silent")) == "silent"
    assert recall_visitor_class(_recall_args(evidence=False, visitor_class="audit")) == "audit"


def test_the_help_text_says_that_silent_records_nothing():
    from pneuma_knowledge_service.cli import build_parser

    parser = build_parser(())
    action = next(
        a
        for a in parser._subparsers._group_actions[0].choices["recall"]._actions  # noqa: SLF001
        if "--visitor-class" in a.option_strings
    )
    assert action.default is None
    help_text = " ".join((action.help or "").split())
    assert "NOTHING AT ALL" in help_text
    assert "`--evidence` defaults to `business`" in help_text
    assert "defaults to `silent`" in help_text


async def test_the_handoff_line_says_what_answering_it_will_record():
    lib = _lib()
    await _seed(lib)
    rt = _rt(lib)
    code = await read_cmd.cmd_recall_evidence(
        rt, QUESTION, handoffs=lib.handoffs, visitor_class="silent"
    )
    assert code == 0
    printed = rt.out.getvalue()
    assert "visitor class: silent" in printed
    assert "NO consultation record" in printed
    assert "--visitor-class business" in printed
    # And `-` for stdin, which the skill's own examples use.
    assert "--text-file <f>" in printed and "`-` for stdin" in printed


async def test_a_recording_class_says_so_instead():
    lib = _lib()
    await _seed(lib)
    rt = _rt(lib)
    await read_cmd.cmd_recall_evidence(
        rt, QUESTION, handoffs=lib.handoffs, visitor_class="business"
    )
    printed = rt.out.getvalue()
    assert "visitor class: business" in printed
    assert "records one consultation" in printed
    assert "NO consultation record" not in printed


# ────────────────────────────────────────────────── the scope the hand-over was read under


async def test_the_handoff_keeps_the_archive_scope_and_the_answer_carries_it():
    """`--include-archived` is a fact about the READING, and the answer is written from those
    bytes — so it rides on the pending row and comes back out when the record is built. A
    consultation over the archive that read back as one over the present would be the archive
    presented as the present, one hop later (docs/design/archive.md §4)."""
    import json

    lib = _lib()
    await _seed(lib)

    rt = _rt(lib, as_json=True)
    await read_cmd.cmd_recall_evidence(
        rt, QUESTION, handoffs=lib.handoffs, visitor_class="business"
    )
    plain = json.loads(rt.out.getvalue())
    assert plain["include_archived"] is False
    assert (await lib.handoffs.get(USER, plain["handoff_id"]))["include_archived"] is False
    _code, out, _err = await _answer(lib, plain["handoff_id"], "20 a seat.")
    assert json.loads(out)["include_archived"] is False

    rt = _rt(lib, as_json=True)
    await read_cmd.cmd_recall_evidence(
        rt,
        QUESTION,
        handoffs=lib.handoffs,
        visitor_class="business",
        include_archived=True,
    )
    wide = json.loads(rt.out.getvalue())
    assert wide["include_archived"] is True
    state = await lib.handoffs.get(USER, wide["handoff_id"])
    assert state["include_archived"] is True

    _code, out, _err = await _answer(lib, wide["handoff_id"], "20 a seat.")
    assert json.loads(out)["include_archived"] is True


async def test_the_evidence_line_says_when_the_archive_is_in_the_context():
    lib = _lib()
    await _seed(lib)
    rt = _rt(lib)
    await read_cmd.cmd_recall_evidence(
        rt, QUESTION, handoffs=lib.handoffs, include_archived=True
    )
    assert "the archive is INCLUDED" in rt.out.getvalue()


async def test_direct_citations_resolve_beside_handed_handles_and_keep_the_manifest(monkeypatch):
    import json
    from pneuma_knowledge_service.api.routes import v1

    lib = _lib()
    await _seed(lib)
    await lib.store.add(USER, source("s-direct", blocks=["intro", "renewals cost 25"]))
    handoff_id, handles, manifest = await _handoff(lib)
    handle = next(h for h, real in handles.items() if real == "s-01")
    spawn = Mock(wraps=v1._spawn_recording)
    monkeypatch.setattr(v1, "_spawn_recording", spawn)
    code, out, err = await _answer(
        lib, handoff_id,
        f"20. [cite: {handle} ¶1] Renewal: [cite: s-direct ¶1] [cite: s-01 ¶3] c:aaa1",
    )
    assert code == 0, err
    payload = json.loads(out)
    by_ref = {c["ref"]: c for c in payload["citations"]}
    assert by_ref["s-01 ¶1"]["origin"] == "handed"
    assert by_ref["s-direct ¶1"]["origin"] == "direct"
    assert by_ref["s-01 ¶3"]["origin"] == "direct"
    assert by_ref["c:aaa1"]["path"] == PAGE
    assert payload["citations_direct"] == 2
    assert payload["evidence_handed"] == len(manifest)
    assert len(lib.store.projection_jobs) == 1
    spawn.assert_called_once()


@pytest.mark.parametrize("citation", [
    "[cite: s-01 ¶999]", "[cite: s-01 ¶0]", "[cite: s-01 ¶3-2]",
    "[cite: absent ¶1]", "[cite: s99 ¶1]", "c:ffff", "c:invented",
    "[cite: s-01]", "[cite: s-01 ¶1, garbage]", "[cite: s-01 ¶1",
])
async def test_invalid_direct_citations_cannot_leave_partial_records(citation):
    lib = _lib()
    await _seed(lib)
    handoff_id, _handles, _manifest = await _handoff(lib)
    code, out, err = await _answer(lib, handoff_id, f"Read: [cite: s-01 ¶1] {citation}")
    assert code == 4 and not out and "unresolved citation" in err
    assert not lib.store.consultations and not lib.store.projection_jobs
    assert await lib.handoffs.get(USER, handoff_id) is not None


async def test_empty_keyless_handoff_can_close_from_direct_reads_without_a_second_recall():
    import json

    lib = library(docs=[document(PAGE, "## Pricing\n\n- Seats cost 20. <!-- c:aaa1 -->")])
    await _seed(lib)
    lib.ctx.embeddings = lib.ctx.vectors = None
    build_model = Mock(side_effect=AssertionError("reading constructed a model"))
    lib.ctx.get_chat_model = build_model
    rt = _rt(lib, as_json=True)
    assert await read_cmd.cmd_recall_evidence(rt, QUESTION, handoffs=lib.handoffs) == 0
    evidence = json.loads(rt.out.getvalue())
    assert evidence["evidence_manifest"] == []
    arms = {arm["name"]: arm for arm in evidence["arms"]}
    assert arms["retrieve.claims"]["status"] == "ran"
    assert arms["retrieve.windows"]["status"] == "ran"
    assert arms["retrieve.glance"]["status"] == "skipped"
    assert "no model" in arms["retrieve.glance"]["detail"]
    build_model.assert_not_called()
    code, out, err = await _answer(
        lib, evidence["handoff_id"], "20 a seat. [cite: s-01 ¶1] c:aaa1",
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["evidence_handed"] == 0 and payload["citations_direct"] == 2
    assert not payload["miss"]
    assert all(c["origin"] == "direct" for c in payload["citations"])
    assert len(lib.store.consultations) == len(lib.store.projection_jobs) == 1


@pytest.mark.parametrize("visitor_class, recorded, jobs", [
    ("business", True, 1), ("audit", True, 0), ("silent", False, 0),
])
async def test_consult_record_uses_the_same_emission_without_a_handoff(
    visitor_class, recorded, jobs, tmp_path, monkeypatch,
):
    import json
    from pneuma_knowledge_service.api.routes import v1
    from test_read_cli import run

    lib = _lib()
    await _seed(lib)
    answer = tmp_path / "answer.txt"
    answer.write_text("20 a seat. [cite: s-01 ¶1] [cite: c:aaa1]")
    spawn = Mock(wraps=v1._spawn_recording)
    monkeypatch.setattr(v1, "_spawn_recording", spawn)
    code, out, err = await run(
        lib, "consult", "record", "--question", QUESTION, "--text-file", str(answer),
        "--visitor-class", visitor_class, "--json",
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["lane"] == "direct" and payload["recorded"] is recorded
    assert payload["evidence_handed"] == 0 and payload["citations_direct"] == 2
    assert payload["miss"] is False
    assert len(lib.store.consultations) == int(recorded)
    assert len(lib.store.projection_jobs) == jobs
    assert spawn.call_count == int(recorded)
    assert await lib.handoffs.list_pending(USER) == []


async def test_consult_record_accepts_stdin_and_no_record(monkeypatch):
    import json
    from test_read_cli import run

    lib = _lib()
    monkeypatch.setattr("sys.stdin", io.StringIO("The library holds nothing."))
    code, out, err = await run(
        lib, "consult", "record", "--question", QUESTION, "--kind", "no_record", "-", "--json",
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["miss"] and payload["citations_direct"] == 0
    assert lib.store.consultations[-1]["lane"] == "direct"


async def test_direct_anchor_resolution_reads_only_the_callers_canonical_tenant():
    from unittest.mock import AsyncMock
    from pneuma_knowledge_core.domain.ids import UserId

    lib = _lib()
    docs = await lib.canonical.list(USER)
    lib.canonical.list = AsyncMock(side_effect=lambda uid: docs if uid == USER else [])
    other = UserId("u-cli-other")
    err = io.StringIO()
    assert await consult_cmd.cmd_consult_record(
        lib.ctx, other, question=QUESTION, text="c:aaa1", out=io.StringIO(), err=err,
    ) == 4
    assert "c:aaa1" in err.getvalue() and not lib.store.consultations
    lib.canonical.list.assert_awaited_once_with(other)
    assert await consult_cmd.cmd_consult_record(
        lib.ctx, USER, question=QUESTION, text="c:aaa1", out=io.StringIO(),
    ) == 0
    assert lib.store.consultations[-1]["citations"][0]["path"] == PAGE


async def test_evidence_prose_reports_the_model_free_arms():
    lib = _lib()
    await _seed(lib)
    rt = _rt(lib)
    assert await read_cmd.cmd_recall_evidence(rt, QUESTION, handoffs=lib.handoffs) == 0
    printed = rt.out.getvalue()
    assert "retrieve.claims: ran" in printed
    assert "retrieve.windows: ran" in printed
    assert "retrieve.glance: skipped (no model; glance pick skipped" in printed
