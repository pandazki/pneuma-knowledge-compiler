"""No write to Qdrant is unbounded, and no request waits five seconds for a large one.

The night this was written a source's whole L2 went out as ONE `upsert(..., wait=True)`
against a client built with the library's default 5-second timeout. The read died
mid-response (`httpcore.ReadError` → `httpx.ReadError` →
`qdrant_client.ResponseHandlingException`), the drain waited the outage out and put the job
back, the same write failed the same way twice more, and the strike guard failed the episodes
job. Nothing about the size of the request was visible anywhere.

Pinned here, keyless, against a recording client: every write path goes out in batches of at
most `UPSERT_BATCH`, and the timeout a deployment states reaches the client's constructor.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from pneuma_knowledge_core.domain.ids import AnchorId, SourceId, UserId
from pneuma_knowledge_core.ingest.chunking import EmbeddedChunk
from pneuma_knowledge_core.recall.projection import ProjectedClaim
from pneuma_knowledge_service.adapters import qdrant as qdrant_adapter
from pneuma_knowledge_service.adapters.qdrant import (
    CLIENT_TIMEOUT_S,
    UPSERT_BATCH,
    QdrantVectorIndex,
)
from pneuma_knowledge_service.settings import Settings

USER = UserId("u-batch")


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list, bool]] = []
        self.deletes: list[list] = []

    async def upsert(self, collection: str, *, points: list, wait: bool) -> None:
        self.calls.append((collection, points, wait))

    async def delete(self, collection: str, *, points_selector, wait: bool) -> None:  # noqa: ANN001
        self.deletes.append(list(points_selector.points))


def _index(batch: int = UPSERT_BATCH) -> tuple[QdrantVectorIndex, _RecordingClient]:
    """The adapter over a client that records instead of speaking (no I/O, no container)."""
    index = object.__new__(QdrantVectorIndex)
    client = _RecordingClient()
    index._client = client
    index._collection = "bounds-test"
    index._dim = 2
    index._upsert_batch = batch
    return index, client


def _sizes(client: _RecordingClient) -> list[int]:
    return [len(points) for _collection, points, _wait in client.calls]


async def test_a_source_s_chunks_go_out_in_bounded_batches() -> None:
    """The write that failed live: one source's L2, all of it, in one request."""
    index, client = _index()
    chunks = [
        EmbeddedChunk(
            source_id=SourceId("s-1"),
            block_start=n,
            block_end=n,
            char_start=n * 10,
            char_end=n * 10 + 9,
            text=f"chunk {n}",
            embedding=[float(n), 1.0],
        )
        for n in range(1000)
    ]

    await index.upsert_chunks(USER, chunks)

    assert _sizes(client) == [256, 256, 256, 232]
    assert max(_sizes(client)) <= UPSERT_BATCH
    assert sum(_sizes(client)) == len(chunks)
    assert all(collection == "bounds-test" for collection, _, _ in client.calls)
    assert all(wait for _, _, wait in client.calls)
    # Every id is a uuid5 over the tenant and the chunk's own span, which is what makes a
    # half-written source safe to write again: a landed batch overwrites itself.
    ids = [point.id for _, points, _ in client.calls for point in points]
    assert len(set(ids)) == len(chunks)


async def test_an_empty_write_asks_qdrant_nothing() -> None:
    index, client = _index()
    await index.upsert_chunks(USER, [])
    await index.upsert_claims(USER, [], [])
    assert client.calls == []


def _claims(count: int) -> tuple[list[ProjectedClaim], list[list[float]]]:
    claims = [
        ProjectedClaim(
            anchor=AnchorId(f"a{n}"),
            document_path="memory/test.md",
            section_path=("Test",),
            text=f"claim {n}",
        )
        for n in range(count)
    ]
    return claims, [[float(n), 1.0] for n in range(count)]


async def test_the_claim_projection_uses_the_same_bound_and_stays_idempotent() -> None:
    index, client = _index()
    claims, vectors = _claims(257)

    await index.upsert_claims(USER, claims, vectors)

    assert _sizes(client) == [256, 1]
    assert sum(_sizes(client)) == len(claims)


async def test_a_delta_s_deletions_are_batched_too() -> None:
    """A rebuild's delta can name thousands of ids, and one request carrying all of them is
    one read that can die on the way back — the same failure as the upsert."""
    index, client = _index(batch=100)
    claims, vectors = _claims(1)
    deleted = [("memory/test.md", f"a{n}") for n in range(250)]

    await index.sync_claims(USER, claims, vectors, deleted)

    assert [len(batch) for batch in client.deletes] == [100, 100, 50]
    assert len({point for batch in client.deletes for point in batch}) == len(deleted)


async def test_a_deployment_states_the_timeout_and_the_batch_and_they_reach_the_client(
    monkeypatch,
) -> None:
    """The client's own default is 5 s. It is a read timeout on a search and an ambush on a
    write of a few hundred vectors, so it is stated here and never inherited."""
    built: list[dict] = []

    def client(**kwargs):  # noqa: ANN003, ANN202
        built.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(qdrant_adapter, "AsyncQdrantClient", client)

    default = QdrantVectorIndex("http://q:6333", 2)
    assert built[-1] == {"url": "http://q:6333", "timeout": int(CLIENT_TIMEOUT_S)}
    assert default._upsert_batch == UPSERT_BATCH

    stated = QdrantVectorIndex("http://q:6333", 2, timeout=90.0, upsert_batch=64)
    assert built[-1]["timeout"] == 90
    assert stated._upsert_batch == 64

    # …and the read-only dimension probe builds its own client the same way.
    probe = SimpleNamespace(
        collection_exists=AsyncMock(return_value=False), close=AsyncMock()
    )
    monkeypatch.setattr(qdrant_adapter, "AsyncQdrantClient", lambda **kw: built.append(kw) or probe)
    await qdrant_adapter.existing_dimension("http://q:6333", "c", timeout=30.0)
    assert built[-1]["timeout"] == 30


def test_the_settings_carry_the_same_numbers_the_adapter_defaults_to() -> None:
    """A deployment that states neither knob gets exactly what the adapter states, so the
    two are never two answers (`wiring.build_context` passes both)."""
    settings = Settings(_env_file=None)
    assert settings.qdrant_upsert_batch == UPSERT_BATCH
    assert settings.qdrant_timeout_s == CLIENT_TIMEOUT_S
