"""One real compile, through a real coding agent, under a real subscription.

Outside the default testpaths on purpose (§11: "a live suite, gated by an env var"). Nothing
in the keyless or the integration tier calls a model or spends anybody's quota; this does
both, so it runs only when a person asks for it by name:

    PNEUMA_KNOWLEDGE_TEST_LIVE_AGENT=codex uv run pytest tests/live -q -s

Preconditions, each of which SKIPS rather than fails, because none of them is a defect in the
code under test:

* the env var above names an installed, logged-in harness (`pkc skill probe` answers live);
* Postgres, Meilisearch and Qdrant are reachable (`docker compose -f infra/docker-compose.yml
  up -d`);
* an embedding route exists for the index job — set `PNEUMA_KNOWLEDGE_EMBEDDING_MODEL` to
  `fake:384` for a keyless run of everything but the compile itself.

What it exercises that nothing else can: the real harness reading the real generated skill,
running the real shim, and typing `pkc draft` commands whose text it chose. The assertions
are therefore about the MECHANISM, never about the judgement — that a commit exists, that it
carries the trailer, that every claim cites the supplied source, that the job row names the
executor. What the agent decided to record is its own affair, and a test that asserted the
wording would be asserting a model's taste.
"""

from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn

REPO = Path(__file__).resolve().parents[2]

LIVE_ENV = "PNEUMA_KNOWLEDGE_TEST_LIVE_AGENT"

#: The tiny fixture the agent compiles. Three turns, one person, one commitment — enough that
#: a round has something to record and small enough that a real round costs seconds.
TURNS = [
    ("Alice", "程野 是后端负责人，下周三之前交付演示稿。"),
    ("Bob", "验收条件是端到端测试全绿。"),
    ("Alice", "他内部也被叫作「欧文」。"),
]

#: The contract the project states, in the form a real project states it: one
#: `engine/compile/contract.md` with frontmatter. The framework ships none, and this test is
#: not the place to invent a domain — so it uses the reference contract's own instructions.
CONTRACT_FRONTMATTER = """\
---
skill_id: live-agent-test
version: live-v1
path_templates:
  - memory/people/{slug}.md
  - memory/topics/{slug}.md
---

"""


def _open(url: str, default: int) -> bool:
    parsed = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((parsed.hostname, parsed.port or default), timeout=1.5):
            return True
    except OSError:
        return False


def _backend_name() -> str:
    name = os.environ.get(LIVE_ENV, "").strip()
    if not name:
        pytest.skip(f"set {LIVE_ENV}=codex (or claude-code) to run the live agent suite")
    return name


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project directory with an engine contract — what `pkc` resolves a deployment from."""
    contract = tmp_path / "engine" / "compile" / "contract.md"
    contract.parent.mkdir(parents=True)
    reference = (
        REPO
        / "packages/pneuma-knowledge-strategies/src/pneuma_knowledge_strategies"
        / "strategies/personal-knowledge/v1.md"
    )
    contract.write_text(
        CONTRACT_FRONTMATTER + reference.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


async def test_a_real_coding_agent_compiles_one_source_through_the_gate(project, monkeypatch):
    from pneuma_knowledge_service.coding_agent.backends import backend as manifest_for
    from pneuma_knowledge_service.coding_agent.probe import probe

    name = _backend_name()
    manifest = manifest_for(name)
    liveness = await probe(manifest)
    if not liveness.ok:
        pytest.skip(f"{name} is not usable: {liveness.reason}")

    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", str(project / "engine"))
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_CANONICAL_ROOT", str(project / "canonical"))
    monkeypatch.setenv("PNEUMA_APP_FRAMEWORK_REPO", str(REPO))
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE", f"agent:{name}")
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_AGENT_PROBE_ON_START", "false")

    from pneuma_knowledge_service.settings import Settings

    settings = Settings()
    if not (
        _open(settings.pg_dsn, 5432)
        and _open(settings.meili_url, 7700)
        and _open(settings.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")

    from pneuma_knowledge_service.cli.runtime import build_runtime
    from pneuma_knowledge_service.coding_agent.round_runner import AgentRoundRunner
    from pneuma_knowledge_service.engine.contract import bootstrap_engine
    from pneuma_knowledge_service.ingest import ingest_conversation
    from pneuma_knowledge_service.wiring import build_context
    from pneuma_knowledge_service.workers.compile_worker import drain_index_jobs

    # This process plays the application's part, exactly as `scaffold/templates/app.py` does:
    # the engine's contract and its wording, registered before anything is built.
    bootstrap_engine(settings)

    # The skill the agent will actually read, installed into the project by the framework's
    # own command — no second renderer.
    from pneuma_knowledge_service.cli import build_parser, resolve_tenant
    from pneuma_knowledge_service.cli.skill import cmd_skill_install

    user = UserId(f"u-live-agent-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_TENANT", str(user))
    import io

    code = await cmd_skill_install(
        settings,
        user=resolve_tenant(str(user)),
        project=str(project),
        choice=name,
        parser_for=build_parser,
        as_json=False,
        out=io.StringIO(),
        err=io.StringIO(),
    )
    assert code == 0
    shim = project / manifest.skill_dir / "scripts" / "pkc"
    assert shim.is_file(), "the skill install did not put a shim in the project"

    ctx = await build_context(settings, probe_agent=False)
    try:
        imported = await ingest_conversation(
            ctx,
            user,
            [
                ConversationTurn(
                    speaker=speaker,
                    text=text,
                    at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
                )
                for speaker, text in TURNS
            ],
            title="项目同步",
        )
        source_id = str(imported.source_id)
        await drain_index_jobs(ctx, user)
        jobs = [j for j in await ctx.store.list_jobs(user) if j["kind"] == "compile"]
        assert jobs, "ingest enqueued no compile job"
        job_id = jobs[0]["job_id"]
        assert await ctx.store.claim(user, job_id, claimed_by="worker") is not None

        rt = await build_runtime(ctx, user, executor=f"agent:{name}")
        result = await AgentRoundRunner(
            manifest=manifest,
            project_dir=str(project),
            timeout_s=float(settings.compile_call_timeout),
            retries=1,
            env={"PNEUMA_KNOWLEDGE_TENANT": str(user)},
        ).run_job(rt, job_id)
        print(f"\nlive round: {result}")

        job = [j for j in await ctx.store.list_jobs(user) if j["job_id"] == job_id][0]
        assert job["status"] == "done", "the round did not end"
        assert job["executor"] == f"agent:{name}"
        if not job["ok"]:
            pytest.fail(f"the agent's round was aborted by the gate: {job['detail']}")

        snapshots = await ctx.canonical.snapshots(user)
        assert snapshots, "no canonical commit"
        assert await ctx.canonical.commit_trailer(user, snapshots[0], "Skill-Version")
        documents = await ctx.canonical.list(user)
        assert documents, "the round committed no page"
        # The mechanism, not the judgement: every claim it wrote cites this round's material.
        assert any(f"[cite: {source_id}" in doc.body for doc in documents)
    finally:
        await ctx.store.delete_user(user)
        await ctx.aclose()
