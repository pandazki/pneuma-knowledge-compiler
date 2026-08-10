"""Compile context can carry labelled captions and real native image blocks."""

from datetime import datetime, timezone

import pytest

from pneuma_knowledge_core.compile.runner import _render_task, _render_task_content
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    BlockImage,
    DerivedMediaText,
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)


def _image_source() -> NormalizedSource:
    return NormalizedSource(
        raw=RawSource(
            source_id=SourceId("source-image"),
            user_id=UserId("tenant-a"),
            kind="im",
            origin="mock",
            title="Design thread",
            mime="application/vnd.pneuma.im+json",
            checksum="checksum",
            created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        blocks=[
            NormalizedBlock(
                index=0,
                text="Alex: This is the latest layout.",
                images=[
                    BlockImage(
                        image_id="img-layout",
                        mime_type="image/png",
                        sha256="2c8648d103e3dd7ad87660da0f126a1443b6d21ac1bd3ec000c5e24e2373a90c",
                        size_bytes=11,
                        storage_key="tenant/image",
                        derived=[
                            DerivedMediaText(
                                kind="caption",
                                text="A dashboard with three project columns.",
                                producer="fixture-captioner",
                            )
                        ],
                    )
                ],
            )
        ],
        structure=StructureMap(),
    )


def test_caption_mode_labels_derived_image_evidence_in_the_cited_block():
    source = _image_source()
    task = _render_task([source], [])

    assert "¶0 Alex: This is the latest layout." in task
    assert "img-layout" in task
    assert "caption" in task
    assert "fixture-captioner" in task
    assert "A dashboard with three project columns." in task
    assert "A dashboard with three project columns." in source.blocks[0].index_text()


def test_native_mode_emits_a_standard_image_content_block_with_citation_locator():
    source = _image_source()
    content = _render_task_content(
        [source],
        [],
        image_mode="native",
        image_payloads={"tenant/image": b"image-bytes"},
    )

    assert isinstance(content, list)
    assert content[-2]["type"] == "text"
    assert all("id" not in block for block in content if block["type"] == "text")
    assert "source-image" in content[-2]["text"]
    assert "¶0" in content[-2]["text"]
    assert "Alex: This is the latest layout." in content[-2]["text"]
    assert content[-1]["type"] == "image"
    assert content[-1]["base64"] == "aW1hZ2UtYnl0ZXM="
    assert content[-1]["mime_type"] == "image/png"


def test_caption_mode_refuses_an_image_with_no_textual_representation():
    source = _image_source()
    source.blocks[0].images[0].derived = []

    with pytest.raises(ValueError, match="caption mode requires"):
        _render_task_content([source], [], image_mode="caption")
