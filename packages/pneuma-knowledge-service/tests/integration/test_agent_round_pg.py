"""One unattended round for real: a launched process typing `pkc draft` against Postgres.

Everything above this file mocks something — the keyless round tests replace the launcher,
the keyless launcher tests replace the harness's judgement. Here nothing between the worker
and the git commit is replaced except the model's judgement itself: a real subprocess (the
fake `codex`) is launched by the real launcher, runs the real `pkc` against real Postgres and
a real per-user git repository, and the round ends because `pkc draft finish` inside that
subprocess ended it.

What it is therefore able to prove, and the keyless tier cannot:

* the draft one process wrote is the draft another process reads — the whole reason
  `DraftStore` exists (ruling 3);
* `pkc` works as a bare framework entry point standing in a project, which is how the shim
  runs it: the contract and the wording come from the process the test starts, exactly as the
  scaffold's driver supplies them;
* the commit is real, and it carries the trailer that makes the next round's audit pass.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_service.cli.runtime import build_runtime
from pneuma_knowledge_service.coding_agent.backends import CODEX
from pneuma_knowledge_service.coding_agent.round_runner import (
    COMMITTED_BY_HARNESS,
    AgentRoundRunner,
)
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs

FAKE_DIR = Path(__file__).parent.parent / "fake_harness"

PAGE = "memory/people/cheng-ye.md"

#: The driver a real project would supply. `pkc` is the FRAMEWORK's entry point — the shim
#: hands off to it — so in a deployment the contract arrives from the engine directory
#: (`bootstrap_engine`). This suite's contract is the reference strategy package instead, so
#: the wrapper registers it the way `scaffold/templates/app.py` registers a project's own.
DRIVER = '''#!/usr/bin/env python
import sys

from pneuma_knowledge_core.skill import SkillVersion, register_skill_base
from pneuma_knowledge_strategies import list_strategies

for strategy in list_strategies("personal-knowledge"):
    register_skill_base(
        strategy.version,
        SkillVersion.from_parts(
            skill_id=strategy.skill_id,
            version=strategy.version,
            instructions=strategy.read_text(),
            path_templates=strategy.path_templates,
            contract_rules=strategy.contract_rules,
        ),
    )

from pneuma_knowledge_service.cli import main

sys.exit(main())
'''


def _open(url: str, default: int) -> bool:
    parsed = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((parsed.hostname, parsed.port or default), timeout=1.5):
            return True
    except OSError:
        return False


@pytest.fixture
async def ctx(tmp_path):
    settings = Settings(canonical_root=str(tmp_path / "canonical"))
    if not (
        _open(settings.pg_dsn, 5432)
        and _open(settings.meili_url, 7700)
        and _open(settings.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    built = await build_context(settings, probe_agent=False)
    yield built
    await built.aclose()


def _driver(tmp_path: Path) -> Path:
    path = tmp_path / "pkc-driver"
    path.write_text(DRIVER, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


async def test_one_unattended_round_commits_through_a_launched_process(
    ctx, tmp_path, monkeypatch
):
    user = UserId(f"u-it-agent-{uuid.uuid4().hex[:8]}")
    imported = await ingest_conversation(
        ctx,
        user,
        [
            ConversationTurn(
                speaker="Alice",
                text="程野 是后端负责人，下周交付演示稿。",
                at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
            )
        ],
        title="项目同步",
    )
    sid = str(imported.source_id)
    await drain_index_jobs(ctx, user)
    job_id = [j for j in await ctx.store.list_jobs(user) if j["kind"] == "compile"][0]["job_id"]
    claimed = await ctx.store.claim(user, job_id, claimed_by="worker")
    assert claimed is not None

    # What the harness will type. Two commands, absolute paths: its working directory is a
    # fresh mkdtemp holding nothing but the round's own files.
    driver = _driver(tmp_path)
    body = tmp_path / "body.md"
    body.write_text(f"## 程野\n\n- 程野 是后端负责人。[cite: {sid} ¶0]\n", encoding="utf-8")
    script = tmp_path / "script.json"
    script.write_text(
        json.dumps(
            [
                [
                    str(driver),
                    "draft",
                    "create-document",
                    PAGE,
                    "--frontmatter",
                    json.dumps({"type": "person", "slug": "cheng-ye"}),
                    "--body-file",
                    str(body),
                ],
                [str(driver), "draft", "finish"],
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", f"{FAKE_DIR}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PKC_FAKE_SCRIPT", str(script))

    rt = await build_runtime(ctx, user, executor="agent:codex")
    runner = AgentRoundRunner(
        manifest=CODEX,
        project_dir=str(tmp_path),
        timeout_s=120.0,
        retries=0,
        env={
            "PNEUMA_KNOWLEDGE_TENANT": str(user),
            "PNEUMA_KNOWLEDGE_CANONICAL_ROOT": str(tmp_path / "canonical"),
            # The driver is a script, not the installed console entry point.
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
        },
    )
    result = await runner.run_job(rt, job_id)

    # The subprocess finished its own round: the draft is gone and the job is done.
    assert result.outcome == COMMITTED_BY_HARNESS, result
    assert result.usage == {"input_tokens": 900, "output_tokens": 250, "total_tokens": 1150}
    from pneuma_knowledge_service.adapters.postgres import PostgresDraftStore

    assert await PostgresDraftStore(ctx.store).get(user, job_id) is None

    job = [j for j in await ctx.store.list_jobs(user) if j["job_id"] == job_id][0]
    assert job["status"] == "done" and job["ok"] is True
    assert job["executor"] == "agent:codex"

    # A real commit in a real per-user repository, carrying the trailer the next round's
    # `open` audit reads back.
    snapshots = await ctx.canonical.snapshots(user)
    assert snapshots
    assert await ctx.canonical.commit_trailer(user, snapshots[0], "Skill-Version")
    documents = {doc.path for doc in await ctx.canonical.list(user)}
    assert PAGE in documents
    events = await ctx.store.list_compile_events(user)
    assert events and all(e["type"] == "claim_added" for e in events)

    await ctx.store.delete_user(user)


async def test_the_worker_finishes_a_round_a_launched_process_walked_away_from(
    ctx, tmp_path, monkeypatch
):
    """The harness wrote and then died. The worker runs the same `pkc draft finish`, so the
    gate judges what was written instead of the round being lost with the process."""
    user = UserId(f"u-it-agent-{uuid.uuid4().hex[:8]}")
    imported = await ingest_conversation(
        ctx,
        user,
        [
            ConversationTurn(
                speaker="Alice",
                text="程野 是后端负责人。",
                at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
            )
        ],
        title="项目同步",
    )
    sid = str(imported.source_id)
    await drain_index_jobs(ctx, user)
    job_id = [j for j in await ctx.store.list_jobs(user) if j["kind"] == "compile"][0]["job_id"]
    assert await ctx.store.claim(user, job_id, claimed_by="worker") is not None

    driver = _driver(tmp_path)
    body = tmp_path / "body.md"
    body.write_text(f"## 程野\n\n- 程野 是后端负责人。[cite: {sid} ¶0]\n", encoding="utf-8")
    script = tmp_path / "script.json"
    script.write_text(
        json.dumps(
            [
                [
                    str(driver),
                    "draft",
                    "create-document",
                    PAGE,
                    "--frontmatter",
                    json.dumps({"type": "person", "slug": "cheng-ye"}),
                    "--body-file",
                    str(body),
                ]
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", f"{FAKE_DIR}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PKC_FAKE_SCRIPT", str(script))

    rt = await build_runtime(ctx, user, executor="agent:codex")
    result = await AgentRoundRunner(
        manifest=CODEX,
        project_dir=str(tmp_path),
        timeout_s=120.0,
        retries=0,
        env={
            "PNEUMA_KNOWLEDGE_TENANT": str(user),
            "PNEUMA_KNOWLEDGE_CANONICAL_ROOT": str(tmp_path / "canonical"),
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
        },
    ).run_job(rt, job_id)

    assert result.launches == 1
    assert (await ctx.canonical.list(user)), "the worker did not finish what was written"
    job = [j for j in await ctx.store.list_jobs(user) if j["job_id"] == job_id][0]
    assert job["status"] == "done" and job["ok"] is True

    await ctx.store.delete_user(user)
