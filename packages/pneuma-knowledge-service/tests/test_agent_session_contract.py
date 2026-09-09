"""Agent-session admission, published schema, CLI structure and compile enforcement."""

import io
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_core.skill.version import SkillVersion
from pneuma_knowledge_service.api.routes.v1 import router
from pneuma_knowledge_service.cli import build_parser
from pneuma_knowledge_service.cli import draft as draft_cmd
from pneuma_knowledge_service.cli.read import ReadRuntime, cmd_source_show
from pneuma_knowledge_service.engine.contract import load_engine_contract
from pneuma_knowledge_service.ingest_sources import ingest_source_contract
from pneuma_knowledge_service.source_authorship import load_owner_authored_blocks

from _cli_library import USER, library
from test_owner_ingest_cli import _payload
from test_draft_cli import harness

SCHEMA = (
    Path(__file__).resolve().parents[3]
    / "docs/reference/source-contracts/agent-session-v1.schema.json"
)


def payload(owner_turns=2):
    value = _payload("agent-session/v1")
    turn = value["turns"][0]
    value["turns"] = [{**turn, "turn_id": f"o{i}"} for i in range(owner_turns)] + [
        {
            **turn,
            "turn_id": "a1",
            "role": "agent",
            "kind": "narrative",
            "text": "I wrote the rationale.",
        },
        {
            **turn,
            "turn_id": "a2",
            "role": "agent",
            "kind": "action",
            "text": "edited docs/rationale.md",
        },
    ]
    return value


def skill():
    return SkillVersion.from_parts(
        skill_id="synthetic",
        version="v1",
        instructions="Record preferences.",
        path_templates=[{"path": "voice/{slug}.md", "owner_voice": True}],
    )


@pytest.mark.parametrize("count,treatment", [(2, "none"), (3, "full")])
@pytest.mark.parametrize("semantic", ["on", "off"])
async def test_http_import_intake_dedup_and_l0_isolation(count, treatment, semantic):
    lib = library(semantic_retrieval=semantic)
    app = FastAPI()
    app.state.ctx = lib.ctx
    app.include_router(router)
    value = payload(count)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/v1/users/{USER}/sources/import", json=value)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["contract_schema"] == value["schema"]
        item = result["sources"][0]
        assert item["intake_plan"]["canonical_treatment"] == treatment
        assert item["intake_plan"]["semantic_indexing"] == (
            "full" if semantic == "on" else "none"
        )
        sid = item["source_id"]
        ns = await lib.store.get(USER, sid)
        assert len(ns.blocks) == count + 2
        jobs = await lib.store.list_jobs(USER)
        assert [j["kind"] for j in jobs].count("index") == 1
        assert [j["kind"] for j in jobs].count("compile") == (count == 3)
        with pytest.raises(KeyError):
            await lib.store.get(UserId("other"), sid)
        assert "Keep the rationale." in await lib.store.fetch(
            USER, sid, {"blocks": [0, 0]}
        )
        response = await client.post(f"/v1/users/{USER}/sources/import", json=value)
        assert response.json()["sources"][0]["deduplicated"]
        assert len(await lib.store.list_jobs(USER)) == len(jobs)
        bad = deepcopy(value)
        bad["turns"][-1]["output"] = "file bytes"
        response = await client.post(f"/v1/users/{USER}/sources/import", json=bad)
        assert response.status_code == 422
        assert "agent_session_tool_payload" in response.text


async def test_structure_exposes_roles_kinds_without_reading_activity_text():
    lib = library()
    result = await ingest_source_contract(
        lib.ctx, USER, parse_source_contract(payload())
    )
    sid = str(result.sources[0].source_id)
    out = io.StringIO()
    rt = ReadRuntime(
        user_id=USER, ctx=lib.ctx, as_json=True, out=out, err=io.StringIO()
    )
    assert await cmd_source_show(rt, sid) == 0
    value = json.loads(out.getvalue())
    assert value["block_authorship"] == [
        {"index": 0, "role": "owner", "kind": "say"},
        {"index": 1, "role": "owner", "kind": "say"},
        {"index": 2, "role": "agent", "kind": "narrative"},
        {"index": 3, "role": "agent", "kind": "action"},
    ]
    assert "edited docs" not in out.getvalue()
    rt.as_json = False
    out.seek(0)
    out.truncate()
    assert await cmd_source_show(rt, sid) == 0
    assert "¶2  agent / narrative" in out.getvalue()
    assert (
        build_parser().parse_args(["source", "structure", sid]).command == "structure"
    )


async def test_owner_lookup_is_tenant_scoped_and_includes_archived_evidence():
    lib = library()
    result = await ingest_source_contract(
        lib.ctx, USER, parse_source_contract(payload())
    )
    sid = str(result.sources[0].source_id)
    ns = await lib.store.get(USER, sid)
    ns.raw.archived_at = datetime.now(timezone.utc)
    # The in-memory adapter copies on read; use its add face to seed an archived source.
    other = UserId("other")
    foreign = normalize_source_contract(
        parse_source_contract(payload(3)), other, imported_at=datetime.now(timezone.utc)
    )[0]
    await lib.store.add(other, foreign)
    owners = await load_owner_authored_blocks(lib.store, USER, skill())
    assert owners == {sid: [0, 1]}
    assert str(foreign.raw.source_id) not in owners
    calls = []

    async def page(user_id, **kw):
        calls.append((user_id, kw))
        return ([ns.raw], 1, False)

    assert await load_owner_authored_blocks(
        SimpleNamespace(list_sources_page=page), USER, skill()
    ) == {sid: [0, 1]}
    assert calls[0][0] == USER and calls[0][1]["include_archived"] is True
    plain = SkillVersion.from_parts(
        skill_id="x", version="v1", instructions="x", path_templates=["voice/{slug}.md"]
    )
    assert await load_owner_authored_blocks(object(), USER, plain) == {}


async def test_cli_draft_uses_flag_and_refuses_before_persisting_claim():
    ns = normalize_source_contract(
        parse_source_contract(payload()), USER, imported_at=datetime.now(timezone.utc)
    )[0]
    h = await harness([ns])
    h.rt.skill = skill()
    code = await draft_cmd.cmd_open(h.rt, h.job_id)
    assert code == 0
    args = {
        "path": "voice/preferences.md",
        "frontmatter": {"type": "preference", "slug": "preferences"},
        "body": "Owner preference. [cite: s01 ¶2]",
    }
    assert (
        await draft_cmd.run_tool(h.rt, "create_document", args)
        == draft_cmd.EXIT_REFUSED
    )
    assert "owner_voice" in h.err()
    assert not h.store.commits
    h.clear()
    args["body"] = "Keep rationale. [cite: s01 ¶0]"
    assert await draft_cmd.run_tool(h.rt, "create_document", args) == 0, h.err()
    assert await draft_cmd.cmd_check(h.rt) == 0, h.out()
    assert await draft_cmd.cmd_finish(h.rt) == 0, h.err()
    assert len(h.store.commits) == 1


def test_frontmatter_loads_and_validates_owner_voice(tmp_path):
    path = tmp_path / "compile/contract.md"
    path.parent.mkdir()
    prefix = "---\nskill_id: synthetic\nversion: v1\npath_templates:\n  - path: voice/{slug}.md\n    owner_voice: "
    path.write_text(prefix + "true\n---\nRecord preferences.\n")
    loaded = load_engine_contract(tmp_path)
    assert loaded.path_templates == ["voice/{slug}.md"]
    assert loaded.owner_voice_templates == ["voice/{slug}.md"]
    path.write_text(prefix + "false\n---\nRecord preferences.\n")
    plain = load_engine_contract(tmp_path)
    assert plain.owner_voice_templates == []
    assert plain.content_hash != loaded.content_hash
    path.write_text(prefix + '"false"\n---\nRecord preferences.\n')
    with pytest.raises(ValidationError):
        load_engine_contract(tmp_path)


@pytest.mark.parametrize(
    "edit",
    [
        lambda v: None,
        lambda v: v["turns"][-1].update(text="x" * 200),
        lambda v: v["turns"][-1].update(text="x" * 201),
        lambda v: v["turns"][-1].update(text="ran\npytest"),
        lambda v: v["turns"][-1].update(text="ran\rpytest"),
        lambda v: v["turns"][0].update(kind="narrative"),
        lambda v: v["turns"][-1].update(kind="say"),
        lambda v: v["turns"][0].update(text=" \t"),
        lambda v: v.update(turns=v["turns"][-2:]),
        lambda v: v["turns"][-1].update(input={}),
        lambda v: v.update(metadata={"nested": [{"result": "file bytes"}]}),
        lambda v: v.update(metadata={"nested": [{"output": "file bytes"}]}),
        lambda v: v.update(extra=True),
        lambda v: v.update(provider=""),
    ],
)
def test_published_schema_and_runtime_agree_on_structural_refusals(edit):
    value = payload()
    edit(value)
    validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
    schema_accepts = not list(validator.iter_errors(value))
    try:
        parse_source_contract(value)
        runtime_accepts = True
    except ValidationError:
        runtime_accepts = False
    assert schema_accepts == runtime_accepts


def test_time_component_reads_agent_session_turn_instants():
    from pneuma_knowledge_service.components.time import block_instants

    value = payload()
    value["turns"][-1]["at"] = "2026-09-07T09:00:05+08:00"
    ns = normalize_source_contract(
        parse_source_contract(value), USER, imported_at=datetime.now(timezone.utc)
    )[0]
    instants, _ = block_instants(ns.raw, len(ns.blocks))
    assert instants == [
        datetime.fromisoformat(t["at"]).astimezone(timezone.utc) for t in value["turns"]
    ]


async def test_model_executor_refuses_agent_evidence_then_commits_owner_evidence():
    from pneuma_knowledge_core.compile.runner import run_compile
    from test_draft_cli import FakeCanonicalStore, RecordingScriptedChatModel

    ns = normalize_source_contract(
        parse_source_contract(payload()), USER, imported_at=datetime.now(timezone.utc)
    )[0]
    args = {
        "path": "voice/preferences.md",
        "frontmatter": {"type": "preference", "slug": "preferences"},
    }
    model = RecordingScriptedChatModel(
        turns=[
            [
                {
                    "name": "create_document",
                    "args": {**args, "body": "The Owner prefers this. [cite: s01 ¶2]"},
                }
            ],
            [
                {
                    "name": "create_document",
                    "args": {**args, "body": "Keep the rationale. [cite: s01 ¶0]"},
                }
            ],
            [{"name": "finish_compile"}],
        ]
    )
    store = FakeCanonicalStore()
    result = await run_compile(
        user_id=USER, model=model, store=store, sources=[ns], skill=skill()
    )
    assert result.status == "committed"
    assert result.rounds == 1
    assert any(
        "owner_voice" in str(message.content)
        for messages in model.seen
        for message in messages
        if message.type == "tool"
    )
    assert "The Owner prefers this" not in str(store.commits)
    assert "Keep the rationale" in str(store.commits)
