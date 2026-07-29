"""Schema-evolve service flow end-to-end over real middleware (schema-evolve §2, Stage C).

Drives the evolve queue jobs directly (no HTTP): the four phase-1 outcomes each land the
right task status; a proposed run lands a branch with the evolved manifest in its tree and a
correct summary; an adopt merges onto main (HEAD advances), rebuilds the L3 projection (spy),
flips the composed skill (manifest闭环), decides the task adopted and deletes the branch.
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlparse

import pytest
import pneuma_knowledge_service.evolve_service as evolve_service
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.evolve.propose import _EvolveDraft, _ProposedFamily
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.evolve_service import run_evolve_job
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.skills import MANIFEST_PATH, skill_for_user
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_user


def _open(url: str, default: int) -> bool:
    p = urlparse(url if "://" in url else f"//{url}")
    try:
        with socket.create_connection((p.hostname, p.port or default), timeout=1.5):
            return True
    except OSError:
        return False


@pytest.fixture
async def ctx(tmp_path):
    s = Settings(canonical_root=str(tmp_path / "canonical"), evolve_auto_trigger=False)
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    c = await build_context(s)
    yield c
    await c.aclose()


_ATLAS_BODY = (
    "## 产品计划\n\n"
    "- Atlas Q3 发布。[cite: s-evolve ¶0] <!-- c:aa11 -->\n"
    "- Atlas 的技术决策由林知远负责。[cite: s-evolve ¶1] <!-- c:bb22 -->"
)


async def _seed_base(ctx, user) -> None:
    """Commit a base topic doc so the evolve run has canonical to reorganize."""
    from pneuma_knowledge_core.compile.documents import render_document

    files = {
        "memory/topics/atlas.md": render_document(
            {"doc_id": "d-atlas", "type": "topic", "slug": "atlas"}, _ATLAS_BODY
        )
    }
    await ctx.canonical.commit_patch(user, files, message="seed base")


class _FakeStructured:
    def __init__(self, payload):
        self._payload = payload

    async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
        return {"parsed": self._payload, "raw": None}


class _FakeModel:
    """A propose-only fake (used for the non-proposed outcomes, which never reach phase 2)."""

    def __init__(self, payload):
        self._payload = payload

    def with_structured_output(self, schema, include_raw=False):  # noqa: ANN001, ARG002
        return _FakeStructured(self._payload)


def _override_model(ctx, model) -> None:
    ctx.get_chat_model = lambda role="default": model


async def _run_one_evolve(ctx, user) -> None:
    """Enqueue + drain a single evolve job (the compile model arg is unused for evolve)."""
    await ctx.store.enqueue(user, "evolve", {})
    await drain_user(ctx, ScriptedChatModel(turns=[]), None, user)


# ---------------------------------------------------------- phase-1 four outcomes


async def test_evolve_no_change_lands_no_change_task(ctx):
    user = UserId(f"u-it-ev-nc-{uuid.uuid4().hex[:8]}")
    await _seed_base(ctx, user)
    _override_model(ctx, _FakeModel(_EvolveDraft(needs_change=False, rationale="证据不足")))
    await _run_one_evolve(ctx, user)
    tasks = await ctx.store.list_evolve_tasks(user)
    assert len(tasks) == 1 and tasks[0]["status"] == "no_change"
    assert tasks[0]["branch"] is None
    await ctx.store.delete_user(user)


async def test_evolve_parse_error_lands_aborted(ctx):
    user = UserId(f"u-it-ev-pe-{uuid.uuid4().hex[:8]}")
    await _seed_base(ctx, user)
    _override_model(ctx, _FakeModel({"unexpected": "shape"}))
    await _run_one_evolve(ctx, user)
    tasks = await ctx.store.list_evolve_tasks(user)
    assert tasks[0]["status"] == "aborted"
    assert "parse_error" in (tasks[0]["detail"] or "")
    await ctx.store.delete_user(user)


async def test_evolve_invalid_templates_lands_aborted(ctx):
    user = UserId(f"u-it-ev-it-{uuid.uuid4().hex[:8]}")
    await _seed_base(ctx, user)
    bad = _EvolveDraft(
        needs_change=True,
        rationale="r",
        families=[
            _ProposedFamily(
                family="products",
                path_template="memory/{bad}/{slug}.md",  # illegal placeholder
                instructions="x",
                evidence="e",
            )
        ],
    )
    _override_model(ctx, _FakeModel(bad))
    await _run_one_evolve(ctx, user)
    tasks = await ctx.store.list_evolve_tasks(user)
    assert tasks[0]["status"] == "aborted"
    assert "invalid_templates" in (tasks[0]["detail"] or "")
    await ctx.store.delete_user(user)


def _proposed_scripted_model() -> ScriptedChatModel:
    """turn0 = phase-1 structured proposal; turn1 = phase-2 reorganization tool calls."""
    return ScriptedChatModel(
        turns=[
            [
                {
                    "name": "_EvolveDraft",
                    "args": {
                        "needs_change": True,
                        "rationale": "topics 下已积累多个个人产品主题。",
                        "families": [
                            {
                                "family": "products",
                                "path_template": "memory/products/{slug}.md",
                                "instructions": "收编个人产品台账。",
                                "evidence": "Atlas 产品规划主题。",
                            }
                        ],
                    },
                }
            ],
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": "memory/products/atlas.md",
                        "frontmatter": {"type": "product", "slug": "atlas"},
                        "body": "## 产品\n",
                    },
                },
                {
                    "name": "move_claim",
                    "args": {
                        "from_path": "memory/topics/atlas.md",
                        "anchor_id": "aa11",
                        "to_path": "memory/products/atlas.md",
                        "heading": "产品",
                    },
                },
                {
                    "name": "move_claim",
                    "args": {
                        "from_path": "memory/topics/atlas.md",
                        "anchor_id": "bb22",
                        "to_path": "memory/products/atlas.md",
                        "heading": "产品",
                    },
                },
                {"name": "finish_evolve"},
            ],
        ]
    )


async def test_evolve_proposed_lands_draft_branch_with_manifest(ctx):
    user = UserId(f"u-it-ev-ok-{uuid.uuid4().hex[:8]}")
    await _seed_base(ctx, user)
    _override_model(ctx, _proposed_scripted_model())
    await _run_one_evolve(ctx, user)

    tasks = await ctx.store.list_evolve_tasks(user)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["status"] == "draft"
    branch = task["branch"]
    assert branch and (await ctx.canonical.branch_head(user, branch)) is not None

    # summary numbers are mechanical: two claims moved into one new product doc.
    assert task["summary"]["moved_claims"] == 2
    assert task["summary"]["new_documents"] == 1
    assert task["summary"]["adopted_by_document"] == {"memory/products/atlas.md": 2}

    # the evolved manifest rides the branch tree, carrying the new products pack.
    manifest = await ctx.canonical.read_meta_at(user, MANIFEST_PATH, branch)
    assert manifest is not None and "memory/products/{slug}.md" in manifest

    # the reorganized product doc lives on the branch, not on main.
    branch_docs = {
        d.path: d for d in await ctx.canonical.list(user, at=SnapshotRef(ref=branch))
    }
    assert "c:aa11" in branch_docs["memory/products/atlas.md"].body
    main_docs = {d.path for d in await ctx.canonical.list(user)}
    assert "memory/products/atlas.md" not in main_docs

    await ctx.store.delete_user(user)


# ------------------------------------------------------------------- adopt闭环


async def test_adopt_merges_flips_skill_and_deletes_branch(ctx, monkeypatch):
    user = UserId(f"u-it-ev-adopt-{uuid.uuid4().hex[:8]}")
    await _seed_base(ctx, user)
    _override_model(ctx, _proposed_scripted_model())
    await _run_one_evolve(ctx, user)
    task = (await ctx.store.list_evolve_tasks(user))[0]
    task_id = task["task_id"]
    branch = task["branch"]

    # skill before adopt: no products template yet.
    before_skill = await skill_for_user(ctx, user)
    assert "memory/products/{slug}.md" not in before_skill.path_templates
    head_before = (await ctx.canonical.snapshots(user))[0].ref

    # spy on the L3 projection rebuild.
    calls: list[str] = []
    real = evolve_service.rebuild_projection

    async def spy(c, u, ref=None, **kw):  # noqa: ANN001
        calls.append(str(ref))
        return await real(c, u, ref, **kw)

    monkeypatch.setattr(evolve_service, "rebuild_projection", spy)

    await ctx.store.enqueue(user, "evolve_adopt", {"task_id": task_id})
    await drain_user(ctx, ScriptedChatModel(turns=[]), None, user)

    # HEAD advanced; projection rebuilt against the adopted ref.
    head_after = (await ctx.canonical.snapshots(user))[0].ref
    assert head_after != head_before
    assert calls == [head_after]

    # task decided adopted, branch gone.
    decided = await ctx.store.get_evolve_task(user, task_id)
    assert decided["status"] == "adopted"
    assert "adopted_ref" in (decided["detail"] or "")
    assert await ctx.canonical.branch_head(user, branch) is None

    # the product doc is now on main, its claims moved verbatim.
    main_docs = {d.path: d for d in await ctx.canonical.list(user)}
    assert "c:aa11" in main_docs["memory/products/atlas.md"].body

    # skill_for_user now composes the evolved pack (manifest闭环).
    after_skill = await skill_for_user(ctx, user)
    assert "memory/products/{slug}.md" in after_skill.path_templates

    await ctx.store.delete_user(user)
