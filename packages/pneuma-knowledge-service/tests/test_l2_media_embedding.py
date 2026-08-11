"""Every L2 writer embeds source/media context but stores verbatim chunk text."""

from datetime import datetime, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    BlockImage,
    DerivedMediaText,
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.ingest.chunking import Chunk
from pneuma_knowledge_service.wiring import embed_l2_chunks


class RecordingEmbeddings:
    def __init__(self) -> None:
        self.documents: list[str] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents = texts
        return [[0.1, 0.2] for _ in texts]


async def test_shared_l2_writer_augments_vector_input_and_keeps_payload_verbatim():
    block = NormalizedBlock(
        index=4,
        text="Melanie posted a picture.",
        images=[
            BlockImage(
                image_id="img-shoes",
                mime_type="image/png",
                sha256="b" * 64,
                size_bytes=12,
                storage_key="sha256/bb/shoes",
                derived=[
                    DerivedMediaText(
                        kind="caption",
                        text="A pair of newly purchased running shoes.",
                        producer="luna",
                    )
                ],
            )
        ],
    )
    chunk = Chunk(
        source_id=SourceId("source-1"),
        block_start=4,
        block_end=4,
        text=block.text,
        char_start=0,
        char_end=len(block.text),
    )
    embeddings = RecordingEmbeddings()
    ctx = SimpleNamespace(embeddings=embeddings)
    normalized = NormalizedSource(
        raw=RawSource(
            source_id=SourceId("source-1"),
            user_id=UserId("user-1"),
            kind="im",
            title="Melanie's October chat",
            mime="application/json",
            checksum="checksum",
            created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            meta={"occurred_on": "2023-10-19"},
        ),
        blocks=[block],
        structure=StructureMap(),
    )

    embedded = await embed_l2_chunks(ctx, [chunk], normalized)

    assert "newly purchased running shoes" in embeddings.documents[0]
    assert "2023-10-19" in embeddings.documents[0]
    assert embedded[0].text == block.text
    assert "running shoes" not in embedded[0].text
    assert embedded[0].char_start == 0
    assert embedded[0].char_end == len(block.text)
