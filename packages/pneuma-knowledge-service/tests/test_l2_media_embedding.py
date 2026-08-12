"""Every L2 writer keeps raw/media and episode representations as separate vectors."""

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


async def test_shared_l2_writer_separates_raw_media_from_episode_representation():
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
        episode_title="October running-shoe purchase",
        episode_description=(
            "Melanie shared newly purchased running shoes in an October conversation."
        ),
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

    assert len(embedded) == 2
    raw, episode = embedded
    assert raw.representation == "raw"
    assert episode.representation == "episode"

    assert "newly purchased running shoes" in embeddings.documents[0]
    assert "[episode title]" not in embeddings.documents[0]
    assert "[episode description]" not in embeddings.documents[0]
    assert block.text in embeddings.documents[0]

    assert "[episode title] October running-shoe purchase" in embeddings.documents[1]
    assert "[episode description] Melanie shared" in embeddings.documents[1]
    assert block.text not in embeddings.documents[1]
    assert "2023-10-19" in embeddings.documents[1]

    assert raw.text == episode.text == block.text
    assert raw.char_start == episode.char_start == 0
    assert raw.char_end == episode.char_end == len(block.text)


async def test_subchunks_share_one_episode_vector_instead_of_repeating_its_description():
    text = "First detail. Second detail."
    block = NormalizedBlock(index=0, text=text)
    chunks = [
        Chunk(
            source_id=SourceId("source-1"),
            block_start=0,
            block_end=0,
            text=text[:13],
            char_start=0,
            char_end=13,
            episode_title="One complete episode",
            episode_description="A single episode description shared by both raw slices.",
            episode_block_start=0,
            episode_block_end=0,
            episode_char_start=0,
            episode_char_end=len(text),
        ),
        Chunk(
            source_id=SourceId("source-1"),
            block_start=0,
            block_end=0,
            text=text[14:],
            char_start=14,
            char_end=len(text),
            episode_title="One complete episode",
            episode_description="A single episode description shared by both raw slices.",
            episode_block_start=0,
            episode_block_end=0,
            episode_char_start=0,
            episode_char_end=len(text),
        ),
    ]
    embeddings = RecordingEmbeddings()
    normalized = NormalizedSource(
        raw=RawSource(
            source_id=SourceId("source-1"),
            user_id=UserId("user-1"),
            kind="im",
            title="One chat",
            mime="application/json",
            checksum="checksum",
            created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        ),
        blocks=[block],
        structure=StructureMap(),
    )

    embedded = await embed_l2_chunks(SimpleNamespace(embeddings=embeddings), chunks, normalized)

    assert [item.representation for item in embedded] == ["raw", "raw", "episode"]
    assert sum("[episode description]" in text for text in embeddings.documents) == 1
    assert embedded[-1].text == text
    assert (embedded[-1].char_start, embedded[-1].char_end) == (0, len(text))
