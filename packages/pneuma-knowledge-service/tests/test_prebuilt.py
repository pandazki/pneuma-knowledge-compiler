"""What a restore refuses, and what it is allowed to touch (no middleware needed).

`restore_refusal` and `settleable_jobs` are the two decisions in a restore, and both are pure
so they can be pinned here rather than only inside an integration round trip.
"""

from __future__ import annotations

import gzip
import hashlib

import pytest
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_service.prebuilt import (
    BUNDLE_NAME,
    L0_DUMP_NAME,
    L0_MEDIA_DIR_NAME,
    PrebuiltUnavailable,
    prebuilt_authorities,
    read_prebuilt_media,
    restore_refusal,
    settleable_jobs,
)

HEAD_A = "a" * 40
HEAD_B = "b" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-png-payload"


def _image_row() -> NormalizedSource:
    digest = hashlib.sha256(PNG).hexdigest()
    return NormalizedSource.model_validate(
        {
            "raw": {
                "source_id": "src-image",
                "user_id": "builder",
                "kind": "im",
                "origin": "mock",
                "title": "image",
                "mime": "application/json",
                "checksum": "checksum",
                "created_at": "2026-08-10T00:00:00Z",
            },
            "blocks": [
                {
                    "index": 0,
                    "text": "look",
                    "images": [
                        {
                            "image_id": "image-1",
                            "mime_type": "image/png",
                            "sha256": digest,
                            "size_bytes": len(PNG),
                            "storage_key": "tenants/build/images/old-key",
                        }
                    ],
                }
            ],
            "structure": {"sections": []},
        }
    )


def test_both_authorities_are_required(tmp_path):
    with pytest.raises(PrebuiltUnavailable) as missing_both:
        prebuilt_authorities(tmp_path)
    assert BUNDLE_NAME in str(missing_both.value)
    assert L0_DUMP_NAME in str(missing_both.value)

    # Half a prebuilt library is refused too: a canonical without its L0 restores claims
    # whose citations address sources that do not exist.
    (tmp_path / BUNDLE_NAME).write_bytes(b"not really a bundle, but present")
    with pytest.raises(PrebuiltUnavailable) as missing_dump:
        prebuilt_authorities(tmp_path)
    assert L0_DUMP_NAME in str(missing_dump.value)
    assert BUNDLE_NAME not in str(missing_dump.value)

    with gzip.open(tmp_path / L0_DUMP_NAME, "wt", encoding="utf-8") as handle:
        handle.write("")
    bundle, dump = prebuilt_authorities(tmp_path)
    assert bundle.name == BUNDLE_NAME and dump.name == L0_DUMP_NAME


def test_image_prebuilt_requires_and_verifies_the_original_media_payload(tmp_path):
    row = _image_row()
    digest = row.blocks[0].images[0].sha256
    with pytest.raises(PrebuiltUnavailable) as missing:
        read_prebuilt_media(tmp_path, [row])
    assert L0_MEDIA_DIR_NAME in str(missing.value)

    payload = tmp_path / L0_MEDIA_DIR_NAME / "sha256" / digest[:2] / digest
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"not the declared image")
    with pytest.raises(PrebuiltUnavailable) as corrupt:
        read_prebuilt_media(tmp_path, [row])
    assert "sha256" in str(corrupt.value)

    payload.write_bytes(PNG)
    assert read_prebuilt_media(tmp_path, [row]) == {
        digest: (PNG, "image/png")
    }


# ------------------------------------------------------------------ what a restore refuses
#
# codex review #6 (prebuilt): a restore used to keep an existing canonical, import its own L0
# under it, settle EVERY queued job for that user as success, and mark EVERY source digested.
# On a tenant with its own uncompiled material that reports a compile that never happened.


def test_an_empty_tenant_is_restorable():
    assert (
        restore_refusal(
            canonical_head=None,
            bundle_head=HEAD_A,
            existing_source_ids=set(),
            dump_source_ids={"s1", "s2"},
        )
        is None
    )


def test_the_same_bundle_restored_twice_is_an_idempotent_re_run():
    assert (
        restore_refusal(
            canonical_head=HEAD_A,
            bundle_head=HEAD_A,
            existing_source_ids={"s1", "s2"},
            dump_source_ids={"s1", "s2"},
        )
        is None
    )


def test_material_the_bundle_does_not_ship_refuses_the_restore():
    """The audit's scenario: the user's own source, not in the dump."""
    refusal = restore_refusal(
        canonical_head=None,
        bundle_head=HEAD_A,
        existing_source_ids={"s1", "mine"},
        dump_source_ids={"s1"},
    )
    assert refusal is not None
    assert "mine" in refusal
    assert "never compiled" in refusal


def test_a_different_canonical_library_refuses_the_restore():
    """Two authorities from two different builds must never coexist for one user."""
    refusal = restore_refusal(
        canonical_head=HEAD_B,
        bundle_head=HEAD_A,
        existing_source_ids={"s1"},
        dump_source_ids={"s1"},
    )
    assert refusal is not None
    assert "different canonical library" in refusal


def test_an_unreadable_bundle_head_cannot_prove_a_re_run():
    refusal = restore_refusal(
        canonical_head=HEAD_A,
        bundle_head=None,
        existing_source_ids=set(),
        dump_source_ids=set(),
    )
    assert refusal is not None and "cannot be read" in refusal


# ------------------------------------------------------------------ what a restore settles


def test_only_pending_jobs_over_this_bundles_sources_are_settled():
    jobs = [
        {"job_id": "covered", "status": "queued", "payload": {"source_ids": ["s1"]}},
        {"job_id": "covered-claimed", "status": "claimed", "payload": {"source_id": "s2"}},
        {"job_id": "foreign", "status": "queued", "payload": {"source_ids": ["mine"]}},
        {"job_id": "mixed", "status": "queued", "payload": {"source_ids": ["s1", "mine"]}},
        {"job_id": "sourceless", "status": "queued", "payload": {}},
        {"job_id": "finished", "status": "done", "payload": {"source_ids": ["s1"]}},
    ]
    assert settleable_jobs(jobs, {"s1", "s2"}) == ["covered", "covered-claimed"]
