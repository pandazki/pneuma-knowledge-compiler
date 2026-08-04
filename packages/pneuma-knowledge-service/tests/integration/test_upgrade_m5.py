"""M5 upgrade drill: prove a strategy upgrade never rewrites canonical (需求 6).

Two paths, both against real git + real middleware with a scripted (keyless) model:

- **Path A — derived-only upgrade.** Compile with v1, record canonical HEAD sha + the
  v1 projection, then swap the projection strategy and `rebuild_projection`. Assert the
  canonical HEAD sha is byte-identical, the derived projection changed per the new
  strategy, and the L3 retrieval face reflects it.
- **Path B — forward-only skill upgrade.** With v1 canonical in place, compile a NEW
  source with skill v2. Assert the new commit's `Skill-Version` trailer is v2, the old
  commit's is still v1, both coexist in one repo, and no old anchor was dropped
  (anchor continuity intact).
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.projection import PROJECTION_V2
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.projection import rebuild_projection
from pneuma_knowledge_service.settings import Settings
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
    s = Settings(canonical_root=str(tmp_path / "canonical"))
    if not (
        _open(s.pg_dsn, 5432) and _open(s.meili_url, 7700) and _open(s.qdrant_url, 6333)
    ):
        pytest.skip("full middleware stack unreachable")
    c = await build_context(s)
    yield c
    await c.aclose()


def _turn(text: str) -> ConversationTurn:
    return ConversationTurn(
        speaker="A", text=text, at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    )


def _register_v2_variant() -> None:
    """The catalog ships one contract; the forward-upgrade path needs a second version,
    so the test registers a local v2 derived from it (exactly what an application does)."""
    from pneuma_knowledge_core.skill import SkillVersion, register_skill_base

    v1 = load_skill_base("v1")
    register_skill_base(
        "v2",
        SkillVersion.from_parts(
            skill_id=v1.skill_id,
            version="v2",
            instructions=v1.instructions + "\n\n## Local v2 addendum\n\nForward-only upgrade probe.",
            path_templates=v1.path_templates,
            contract_rules=v1.contract_rules,
        ),
    )


async def _compile(ctx, user, text: str, *, path: str, slug: str, version: str) -> str:
    """Ingest one conversation and compile it with skill `version` (scripted model)."""
    if version == "v2":
        _register_v2_variant()
    res = await ingest_conversation(ctx, user, [_turn(text)], title="c")
    sid = str(res.source_id)
    model = ScriptedChatModel(
        turns=[
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": path,
                        "frontmatter": {"type": "person", "slug": slug},
                        "body": f"## {slug.upper()}\n\n- {text}[cite: {sid} ¶0]",
                    },
                },
                {"name": "finish_compile"},
            ]
        ]
    )
    # Drains two jobs: the "index" job (L1/L2) then the "compile" job.
    assert await drain_user(ctx, model, load_skill_base(version), user) == 2
    return sid


async def test_path_a_derived_upgrade_leaves_canonical_head_unchanged(ctx):
    user = UserId(f"u-it-m5a-{uuid.uuid4().hex[:8]}")
    try:
        await _compile(ctx, user, "程野 是后端负责人", path="memory/people/cheng-ye.md", slug="cheng-ye", version="v1")

        # Canonical HEAD before the derived upgrade.
        head_before = (await ctx.canonical.snapshots(user))[0].ref
        v1_claims = await ctx.store.list_canonical_claims(user)
        v1_texts = sorted(c["text"] for c in v1_claims)
        assert v1_texts and all(not t.startswith("[") for t in v1_texts)

        # Derived-only upgrade: swap projection strategy + full rebuild. No compile,
        # no commit — canonical is only read.
        n = await rebuild_projection(ctx, user, strategy=PROJECTION_V2)

        # 1. Canonical HEAD sha is byte-identical — the authority layer was untouched.
        head_after = (await ctx.canonical.snapshots(user))[0].ref
        assert head_after == head_before

        # 2. Derived projection changed per the new strategy (same rows, folded text).
        v2_claims = await ctx.store.list_canonical_claims(user)
        v2_texts = sorted(c["text"] for c in v2_claims)
        assert n == len(v1_claims) == len(v2_claims)
        assert v2_texts != v1_texts
        assert all(t.startswith("[") for t in v2_texts)  # section breadcrumb folded in

        # 3. The L3 retrieval face reflects the new projection immediately.
        hits = await ctx.lexical.search_claims(user, "后端负责人", limit=10)
        assert hits and all(h.text.startswith("[") for h in hits)
    finally:
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)


async def test_path_b_v2_forward_compile_coexists_and_preserves_anchors(ctx):
    user = UserId(f"u-it-m5b-{uuid.uuid4().hex[:8]}")
    try:
        # v1 canonical exists.
        await _compile(ctx, user, "程野 是后端负责人", path="memory/people/cheng-ye.md", slug="cheng-ye", version="v1")
        v1_commit = (await ctx.canonical.snapshots(user))[0].ref
        anchors_v1 = {c["anchor"] for c in await ctx.store.list_canonical_claims(user)}
        assert anchors_v1

        # Forward-only: a NEW source compiled with skill v2.
        await _compile(ctx, user, "Carol 是产品经理", path="memory/people/carol.md", slug="carol", version="v2")
        v2_commit = (await ctx.canonical.snapshots(user))[0].ref
        assert v2_commit != v1_commit

        # 1. Skill-Version trailers: new commit = v2, old commit = v1 (forward-only).
        assert await ctx.canonical.commit_trailer(user, SnapshotRef(ref=v2_commit), "Skill-Version") == "v2"
        assert await ctx.canonical.commit_trailer(user, SnapshotRef(ref=v1_commit), "Skill-Version") == "v1"

        # 2. Both versions coexist in one repo — two commits, two skill versions.
        versions = [
            await ctx.canonical.commit_trailer(user, s, "Skill-Version")
            for s in await ctx.canonical.snapshots(user)
        ]
        assert set(versions) == {"v1", "v2"}

        # 3. Anchor continuity: v2's new doc did not drop any v1 anchor.
        anchors_head = {c["anchor"] for c in await ctx.store.list_canonical_claims(user)}
        assert anchors_v1 <= anchors_head
        # v1's document is still present verbatim at HEAD (never rewritten).
        paths_head = {d.path for d in await ctx.canonical.list(user)}
        assert {"memory/people/cheng-ye.md", "memory/people/carol.md"} <= paths_head
    finally:
        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)
