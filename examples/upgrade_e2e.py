#!/usr/bin/env python
"""End-to-end upgrade drill with a scripted (keyless) model.

Proves 需求 6: a strategy upgrade rebuilds only the derived layer and NEVER rewrites the
git-canonical authority. Two paths, one repo, real git + real middleware:

  Path A — derived-only upgrade: compile with skill v1, record canonical HEAD sha, then
  swap the projection strategy and rebuild_projection. The canonical HEAD sha stays
  byte-identical; the derived projection + L3 retrieval face change per the new strategy.

  Path B — forward-only skill upgrade: with v1 canonical in place, compile a NEW source
  with skill v2. The new commit carries `Skill-Version: v2`, the old commit still says
  v1, both coexist, and no old anchor is dropped.

Exit code is non-zero on any failed assertion. Run after
`docker compose -f infra/docker-compose.yml up -d --wait`.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from datetime import datetime, timezone

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.projection import PROJECTION_V2
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.projection import rebuild_projection
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_user

RUN = uuid.uuid4().hex[:8]


def _turn(text: str) -> ConversationTurn:
    return ConversationTurn(
        speaker="A", text=text, at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    )


async def _compile(ctx, user, text: str, *, path: str, slug: str, version: str) -> str:
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
    n = await drain_user(ctx, model, load_builtin_skill(version), user)
    # index (L1/L2) + compile (L3) — see compile_e2e for the same note.
    assert n == 2, f"expected 2 jobs processed (index + compile), got {n}"
    return sid


async def main() -> int:
    tmp = tempfile.mkdtemp(prefix="pneuma_knowledge-upgrade-e2e-")
    ctx = await build_context(Settings(canonical_root=tmp))
    failures: list[str] = []
    try:
        user = UserId(f"u-e2e-upgrade-{RUN}")

        # v1/v2 skill identity: independent, stable content hashes.
        v1_skill, v2_skill = load_builtin_skill("v1"), load_builtin_skill("v2")
        print("== skill versions ==")
        print(f"  v1 {v1_skill.content_hash[:12]}…   v2 {v2_skill.content_hash[:12]}…")
        if v1_skill.content_hash == v2_skill.content_hash:
            failures.append("v1/v2 content_hash collided")

        # --- setup: v1 canonical -------------------------------------------------
        print(f"\n== compile source-1 with skill v1 (user={user}) ==")
        await _compile(ctx, user, "程野 是后端负责人", path="memory/people/cheng-ye.md", slug="cheng-ye", version="v1")
        head_v1 = (await ctx.canonical.snapshots(user))[0].ref
        v1_claim_texts = sorted(c["text"] for c in await ctx.store.list_canonical_claims(user))
        print(f"  canonical HEAD = {head_v1[:12]}…")
        print(f"  v1 projection: {v1_claim_texts}")

        # --- Path A: derived-only upgrade ---------------------------------------
        print("\n== Path A: projection strategy upgrade + rebuild_projection ==")
        n = await rebuild_projection(ctx, user, strategy=PROJECTION_V2)
        head_after = (await ctx.canonical.snapshots(user))[0].ref
        v2_claim_texts = sorted(c["text"] for c in await ctx.store.list_canonical_claims(user))
        lex = await ctx.lexical.search_claims(user, "后端负责人", limit=5)
        print(f"  canonical HEAD before = {head_v1[:12]}…")
        print(f"  canonical HEAD after  = {head_after[:12]}…   (unchanged: {head_after == head_v1})")
        print(f"  projection rows: {len(v1_claim_texts)} → {n} (same rows, re-rendered)")
        print(f"  v2 projection: {v2_claim_texts}")
        print(f"  L3 lexical face now returns: {[h.text for h in lex]}")
        if head_after != head_v1:
            failures.append("Path A: canonical HEAD changed on a derived-only upgrade")
        if not (v2_claim_texts != v1_claim_texts and all(t.startswith("[") for t in v2_claim_texts)):
            failures.append("Path A: projection did not reflect the new strategy")
        if not (lex and all(h.text.startswith("[") for h in lex)):
            failures.append("Path A: L3 retrieval face did not reflect the new projection")

        # --- Path B: forward-only skill upgrade ---------------------------------
        print("\n== Path B: compile source-2 with skill v2 (forward-only) ==")
        anchors_before = {c["anchor"] for c in await ctx.store.list_canonical_claims(user)}
        await _compile(ctx, user, "Carol 是产品经理", path="memory/people/carol.md", slug="carol", version="v2")
        head_v2 = (await ctx.canonical.snapshots(user))[0].ref
        tr_new = await ctx.canonical.commit_trailer(user, SnapshotRef(ref=head_v2), "Skill-Version")
        tr_old = await ctx.canonical.commit_trailer(user, SnapshotRef(ref=head_v1), "Skill-Version")
        anchors_after = {c["anchor"] for c in await ctx.store.list_canonical_claims(user)}
        paths_head = sorted(d.path for d in await ctx.canonical.list(user))
        print(f"  new commit {head_v2[:12]}…  Skill-Version = {tr_new}")
        print(f"  old commit {head_v1[:12]}…  Skill-Version = {tr_old}")
        print(f"  both versions coexist in one repo: {{{tr_old}, {tr_new}}}")
        print(f"  anchors preserved (old ⊆ head): {anchors_before <= anchors_after}")
        print(f"  canonical docs at HEAD: {paths_head}")
        if tr_new != "v2":
            failures.append(f"Path B: new commit trailer = {tr_new!r}, expected 'v2'")
        if tr_old != "v1":
            failures.append(f"Path B: old commit trailer = {tr_old!r}, expected 'v1' (forward-only broken)")
        if not (anchors_before <= anchors_after):
            failures.append("Path B: anchor continuity broke (an old anchor was dropped)")

        await ctx.store.delete_user(user)
        await ctx.lexical.delete_user(user)
        await ctx.vectors.delete_user(user)
    finally:
        await ctx.aclose()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: upgrade e2e passed — canonical frozen through Path A, forward-only through Path B")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
