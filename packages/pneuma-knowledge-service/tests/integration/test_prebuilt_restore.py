"""Ship a compiled library, restore it elsewhere: the round trip, keyless.

Build a real library (ingest → scripted compile), export exactly the two authorities a
project ships — the canonical git bundle and the verbatim L0 rows — then restore them for a
DIFFERENT user and assert the whole library is back: same source ids (so every citation
still binds), canonical documents, projected claims, L1/L2 rebuilt, nothing left queued.
"""

from __future__ import annotations

import gzip
import base64
import hashlib
import json
import socket
import subprocess
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.ingest_sources import ingest_source_contract
from pneuma_knowledge_service.prebuilt import (
    BUNDLE_NAME,
    L0_DUMP_NAME,
    L0_MEDIA_DIR_NAME,
    SETTLED_DETAIL,
    PrebuiltUnavailable,
    restore_prebuilt,
)
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_user


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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


async def _build_library(ctx, user: UserId) -> str:
    """One ingested source compiled into one canonical document. Returns the source id."""
    turn = ConversationTurn(
        speaker="A",
        text="The pilot stays read-only until the appendix is signed.",
        at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )
    result = await ingest_conversation(ctx, user, [turn], title="pilot scope")
    sid = str(result.source_id)
    model = ScriptedChatModel(
        turns=[
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": "memory/topics/pilot.md",
                        "frontmatter": {"type": "topic", "slug": "pilot"},
                        "body": (
                            "## Pilot\n\n- Read-only until the appendix is signed"
                            f"[cite: {sid} ¶0]"
                        ),
                    },
                },
                {"name": "finish_compile"},
            ]
        ]
    )
    assert await drain_user(ctx, model, load_skill_base("v1"), user) == 2
    return sid


async def _export_authorities(ctx, user: UserId, directory) -> None:
    """Write canonical, L0 manifests, and any immutable L0 media originals."""
    directory.mkdir(parents=True, exist_ok=True)
    repo = ctx.canonical.repo_path(user)
    subprocess.run(
        ["git", "-C", str(repo), "bundle", "create", str(directory / BUNDLE_NAME), "--all"],
        capture_output=True,
        text=True,
        check=True,
    )
    with gzip.open(directory / L0_DUMP_NAME, "wt", encoding="utf-8") as handle:
        for raw in await ctx.store.list(user):
            normalized = await ctx.store.get(user, raw.source_id)
            handle.write(json.dumps(normalized.model_dump(mode="json")) + "\n")
            for block in normalized.blocks:
                for image in block.images:
                    payload = (
                        directory
                        / L0_MEDIA_DIR_NAME
                        / "sha256"
                        / image.sha256[:2]
                        / image.sha256
                    )
                    payload.parent.mkdir(parents=True, exist_ok=True)
                    payload.write_bytes(await ctx.media.get(user, image.storage_key))


async def _build_image_library(ctx, user: UserId) -> str:
    digest = hashlib.sha256(PNG).hexdigest()
    contract = parse_source_contract(
        {
            "schema": "pneuma.source.im/v1",
            "provider": "mock",
            "archive_id": "prebuilt-image",
            "owner_user_ids": ["owner"],
            "users": [{"user_id": "owner", "display_name": "Owner"}],
            "conversations": [
                {
                    "conversation_id": "visual",
                    "conversation_type": "dm",
                    "title": "Visual",
                    "member_ids": ["owner"],
                    "messages": [
                        {
                            "message_id": "m1",
                            "sender_id": "owner",
                            "sent_at": "2026-08-10T00:00:00Z",
                            "text": "The diagram is the launch marker.",
                            "images": [
                                {
                                    "image_id": "marker",
                                    "mime_type": "image/png",
                                    "source": {
                                        "type": "base64",
                                        "data": base64.b64encode(PNG).decode("ascii"),
                                        "sha256": digest,
                                    },
                                    "derived": [
                                        {
                                            "kind": "caption",
                                            "text": "A launch marker.",
                                            "producer": "test-fixture",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    ingested = await ingest_source_contract(ctx, user, contract)
    source_id = str(ingested.sources[0].source_id)
    model = ScriptedChatModel(
        turns=[
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": "memory/topics/visual.md",
                        "frontmatter": {"type": "topic", "slug": "visual"},
                        "body": (
                            "## Visual\n\n- The diagram is the launch marker"
                            f"[cite: {source_id} ¶0]"
                        ),
                    },
                },
                {"name": "finish_compile"},
            ]
        ]
    )
    assert await drain_user(ctx, model, load_skill_base("v1"), user) == 2
    return source_id


async def test_a_shipped_library_restores_for_another_user_without_a_model(ctx, tmp_path):
    builder = UserId(f"u-it-prebuilt-src-{uuid.uuid4().hex[:8]}")
    owner = UserId(f"u-it-prebuilt-dst-{uuid.uuid4().hex[:8]}")
    prebuilt = tmp_path / "prebuilt"
    try:
        sid = await _build_library(ctx, builder)
        await _export_authorities(ctx, builder, prebuilt)

        # The restore itself: no chat model is constructed anywhere in this call.
        report = await restore_prebuilt(ctx, owner, prebuilt)
        assert report.canonical_cloned is True
        assert (report.sources, report.indexed, report.documents) == (1, 1, 1)
        assert report.claims >= 1

        # Source ids survive verbatim — the restored canonical's citations bind to them.
        restored = await ctx.store.list(owner)
        assert [str(s.source_id) for s in restored] == [sid]
        cited = await ctx.canonical.list(owner)
        assert len(cited) == 1 and sid in cited[0].body

        # Nothing is left for a later compile to redo: queue empty, sources digested.
        assert await ctx.store.claim_next(owner) is None
        digested = await ctx.store.digested_map(owner, [sid])
        assert digested.get(sid)

        # Derived state is really there (L2 points, L3 claims in PG).
        assert await ctx.vectors.count_chunks(owner) > 0

        # A second restore is idempotent and never overwrites the canonical authority.
        again = await restore_prebuilt(ctx, owner, prebuilt)
        assert again.canonical_cloned is False
        assert (again.sources, again.documents) == (1, 1)
        assert again.claims == report.claims

        # The builder's library is untouched by either restore (I1).
        assert [str(s.source_id) for s in await ctx.store.list(builder)] == [sid]
        assert len(await ctx.canonical.list(builder)) == 1
    finally:
        for user in (builder, owner):
            await ctx.store.delete_user(user)
            await ctx.lexical.delete_user(user)
            await ctx.vectors.delete_user(user)


async def test_an_image_prebuilt_restores_original_bytes_under_the_new_tenant(ctx, tmp_path):
    if not _open(ctx.settings.media_s3_endpoint_url, 9000):
        pytest.skip("RustFS unreachable")
    builder = UserId(f"u-it-prebuilt-img-src-{uuid.uuid4().hex[:8]}")
    owner = UserId(f"u-it-prebuilt-img-dst-{uuid.uuid4().hex[:8]}")
    prebuilt = tmp_path / "prebuilt-image"
    try:
        source_id = await _build_image_library(ctx, builder)
        await _export_authorities(ctx, builder, prebuilt)

        report = await restore_prebuilt(ctx, owner, prebuilt)
        assert report.images == 1
        built = await ctx.store.get(builder, SourceId(source_id))
        restored = await ctx.store.get(owner, SourceId(source_id))
        assert built is not None and restored is not None
        built_image = built.blocks[0].images[0]
        restored_image = restored.blocks[0].images[0]
        assert restored_image.storage_key != built_image.storage_key
        assert await ctx.media.get(owner, restored_image.storage_key) == PNG
    finally:
        for user in (builder, owner):
            await ctx.media.delete_user(user)
            await ctx.store.delete_user(user)
            await ctx.lexical.delete_user(user)
            await ctx.vectors.delete_user(user)


async def test_pending_work_for_this_bundle_is_settled_with_a_reason_not_deleted(ctx, tmp_path):
    """Work over THIS bundle's sources is settled and says why; nothing else is touched.

    A shipped canonical already covers every restored source, so compiling that queue would redo
    a finished build. Those jobs are completed with a recorded reason rather than dropped, so the
    Process view still shows what happened to them. A pending job that names no source of this
    bundle is not this restore's business — settling it would report a compile that never ran
    (codex review #6, prebuilt)."""
    builder = UserId(f"u-it-prebuilt-log-{uuid.uuid4().hex[:8]}")
    owner = UserId(f"u-it-prebuilt-own-{uuid.uuid4().hex[:8]}")
    prebuilt = tmp_path / "prebuilt"
    try:
        sid = await _build_library(ctx, builder)
        await _export_authorities(ctx, builder, prebuilt)
        covered = await ctx.store.enqueue(owner, "compile", {"source_ids": [sid]})
        unrelated = await ctx.store.enqueue(owner, "evolve", {})
        report = await restore_prebuilt(ctx, owner, prebuilt)
        assert report.jobs_settled == 1
        jobs = {job["job_id"]: job for job in await ctx.store.list_jobs(owner)}
        assert jobs[covered]["status"] == "done"
        assert SETTLED_DETAIL in (jobs[covered].get("detail") or "")
        assert jobs[unrelated]["status"] == "queued", "not this bundle's work to finish"
    finally:
        for user in (builder, owner):
            await ctx.store.delete_user(user)
            await ctx.lexical.delete_user(user)
            await ctx.vectors.delete_user(user)


async def test_a_tenant_holding_uncompiled_material_of_its_own_is_refused(ctx, tmp_path):
    """codex review #6 (prebuilt): the audit's scenario, refused instead of misreported.

    Someone imports their own material, its compile job has not run yet, and they run
    `./app.py restore`. The old restore settled that job as "prebuilt library" and stamped the
    source digested — a compile that never happened, reported as done, with the material now
    invisible to the next compile. Nothing about the tenant is touched now: it is refused first.
    """
    builder = UserId(f"u-it-prebuilt-src-{uuid.uuid4().hex[:8]}")
    owner = UserId(f"u-it-prebuilt-own-{uuid.uuid4().hex[:8]}")
    prebuilt = tmp_path / "prebuilt"
    try:
        await _build_library(ctx, builder)
        await _export_authorities(ctx, builder, prebuilt)
        # The owner's own material, ingested and queued but never compiled.
        own = await ingest_conversation(
            ctx,
            owner,
            [
                ConversationTurn(
                    speaker="A",
                    text="A decision I made myself, not yet compiled.",
                    at=datetime(2026, 3, 3, tzinfo=timezone.utc),
                )
            ],
            title="my own notes",
        )
        own_id = str(own.source_id)
        with pytest.raises(PrebuiltUnavailable) as refused:
            await restore_prebuilt(ctx, owner, prebuilt)
        assert own_id in str(refused.value)
        assert "never compiled" in str(refused.value)
        # Nothing moved: no job was finished, and the source is still undigested.
        assert all(j["status"] == "queued" for j in await ctx.store.list_jobs(owner))
        # (`undigested_source_ids` excludes sources with an in-flight job, so the stamp itself
        # is what to check: nothing claimed this material was compiled.)
        assert (await ctx.store.digested_map(owner, [own_id])).get(own_id) is None
        assert await ctx.canonical.list(owner) == []
    finally:
        for user in (builder, owner):
            await ctx.store.delete_user(user)
            await ctx.lexical.delete_user(user)
            await ctx.vectors.delete_user(user)
