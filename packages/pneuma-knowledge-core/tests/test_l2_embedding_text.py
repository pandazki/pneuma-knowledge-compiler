"""L2 embeds source/media context without weakening verbatim chunk provenance."""

from datetime import datetime, timezone

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    BlockImage,
    DerivedMediaText,
    NormalizedBlock,
    RawSource,
)
from pneuma_knowledge_core.ingest.chunking import Chunk, embedding_text_for_chunk


def test_embedding_text_augments_verbatim_chunk_with_block_aligned_media_text():
    blocks = [
        NormalizedBlock(
            index=3,
            text="Sam shared a photo.",
            images=[
                BlockImage(
                    image_id="img-kayak",
                    mime_type="image/jpeg",
                    sha256="a" * 64,
                    size_bytes=42,
                    storage_key="sha256/aa/kayak",
                    derived=[
                        DerivedMediaText(
                            kind="caption",
                            text="A person paddling a yellow kayak on a lake.",
                            producer="luna",
                        )
                    ],
                )
            ],
        )
    ]
    chunk = Chunk(
        source_id=SourceId("source-1"),
        block_start=3,
        block_end=3,
        text="Sam shared a photo.",
        char_start=0,
        char_end=19,
    )

    embedded_text = embedding_text_for_chunk(chunk, blocks)

    assert embedded_text.endswith(chunk.text)
    assert "img-kayak" in embedded_text
    assert "caption" in embedded_text
    assert "producer=luna" in embedded_text
    assert "paddling a yellow kayak" in embedded_text
    assert chunk.text == "Sam shared a photo."


def test_embedding_text_stays_verbatim_when_covered_blocks_have_no_media():
    blocks = [NormalizedBlock(index=0, text="A plain text episode.")]
    chunk = Chunk(
        source_id=SourceId("source-1"),
        block_start=0,
        block_end=0,
        text="A plain text episode.",
        char_start=0,
        char_end=21,
    )

    assert embedding_text_for_chunk(chunk, blocks) == chunk.text


def test_embedding_text_combines_episode_representation_with_verbatim_evidence():
    blocks = [
        NormalizedBlock(
            index=0,
            text="Caroline plans to paddle on the lake this weekend.",
        )
    ]
    chunk = Chunk(
        source_id=SourceId("source-1"),
        block_start=0,
        block_end=0,
        text=blocks[0].text,
        char_start=0,
        char_end=len(blocks[0].text),
        episode_title="Weekend kayaking and safety planning",
        episode_description=(
            "Caroline discussed a kayaking trip and the safety equipment she would bring."
        ),
    )

    embedded_text = embedding_text_for_chunk(chunk, blocks)

    assert "[episode title] Weekend kayaking and safety planning" in embedded_text
    assert "[episode description] Caroline discussed a kayaking trip" in embedded_text
    assert embedded_text.endswith(chunk.text)
    assert chunk.text == blocks[0].text


def test_embedding_text_includes_occurrence_context_without_changing_chunk():
    blocks = [NormalizedBlock(index=0, text="They went hiking last Thursday.")]
    chunk = Chunk(
        source_id=SourceId("source-1"),
        block_start=0,
        block_end=0,
        text=blocks[0].text,
        char_start=0,
        char_end=len(blocks[0].text),
    )
    raw = RawSource(
        source_id=SourceId("source-1"),
        user_id=UserId("user-1"),
        kind="im",
        title="A chat session",
        mime="application/json",
        checksum="checksum",
        created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        meta={"occurred_on": "2023-10-19"},
    )

    embedded_text = embedding_text_for_chunk(chunk, blocks, raw=raw)

    assert "[source title] A chat session" in embedded_text
    assert "[source occurred_on] 2023-10-19" in embedded_text
    assert embedded_text.endswith(chunk.text)
    assert chunk.text == "They went hiking last Thursday."
