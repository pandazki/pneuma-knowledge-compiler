from __future__ import annotations

from pneuma_knowledge_core.domain.ids import AnchorId, UserId
from pneuma_knowledge_core.recall.projection import ProjectedClaim
from pneuma_knowledge_service.adapters.qdrant import QdrantVectorIndex


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list, bool]] = []

    async def upsert(self, collection: str, *, points: list, wait: bool) -> None:
        self.calls.append((collection, points, wait))


async def test_claim_upsert_uses_bounded_idempotent_batches() -> None:
    index = object.__new__(QdrantVectorIndex)
    client = _RecordingClient()
    index._client = client
    index._collection = "claims-test"
    index._dim = 2

    claims = [
        ProjectedClaim(
            anchor=AnchorId(f"a{number}"),
            document_path="memory/test.md",
            section_path=("Test",),
            text=f"claim {number}",
        )
        for number in range(129)
    ]
    vectors = [[float(number), 1.0] for number in range(129)]

    await index.upsert_claims(UserId("u-batch"), claims, vectors)

    assert [len(points) for _, points, _ in client.calls] == [128, 1]
    assert all(collection == "claims-test" for collection, _, _ in client.calls)
    assert all(wait for _, _, wait in client.calls)
    assert sum(len(points) for _, points, _ in client.calls) == len(claims)
