"""One keyless library the `pkc` command tests share: L0, canonical, the indexes, a context.

The read commands take an AppContext, and building a real one needs Postgres, Qdrant and
Meilisearch. What they actually TOUCH is a handful of ports, so this assembles a stand-in
carrying those and nothing else — the same shape `SimpleNamespace(...)` the route tests use,
kept in one module because five command families ask the same questions of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.user import UserProfile
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    SectionSpan,
    StructureMap,
)
from pneuma_knowledge_service.adapters.draft_mock import InMemoryRecallHandoffStore
from pneuma_knowledge_service.adapters.read_mock import InMemoryLibraryStore
from pneuma_knowledge_service.settings import Settings

USER = UserId("u-cli-read")


class FakeCanonicalStore:
    """`list` + `snapshots` + `commit_trailer` — the three faces the read commands and
    `pkc library check` reach for. `trailers` maps a ref to the value `Skill-Version` reads
    back on it; a ref that is absent from it has no trailer, which is the finding
    `library check` reports."""

    def __init__(
        self,
        docs: list[CanonicalDocument] | None = None,
        *,
        snapshots: list[SnapshotRef] | None = None,
        trailers: dict[str, str] | None = None,
    ) -> None:
        self._docs = list(docs or [])
        self._snapshots = list(
            snapshots if snapshots is not None else [SnapshotRef(ref="c0", label="compile 1")]
        )
        self._trailers = dict(
            trailers if trailers is not None else {s.ref: "v1" for s in self._snapshots}
        )

    async def list(self, user_id, *, at: SnapshotRef | None = None):  # noqa: ANN001
        return list(self._docs)

    async def read(self, user_id, document_id, *, at=None):  # noqa: ANN001
        return next((d for d in self._docs if str(d.doc_id) == str(document_id)), None)

    async def snapshots(self, user_id):  # noqa: ANN001
        return list(self._snapshots)

    async def commit_trailer(self, user_id, ref, key: str):  # noqa: ANN001
        return self._trailers.get(ref.ref if hasattr(ref, "ref") else str(ref))

    async def read_meta(self, user_id, rel_path: str):  # noqa: ANN001
        return None

    async def last_commit(self, user_id, path, *, at=None):  # noqa: ANN001
        return None


class FakeLexical:
    def __init__(self, hits: list[Any] | None = None) -> None:
        self.hits = list(hits or [])

    async def search(self, user_id, query, *, limit=20, include_archived=False):  # noqa: ANN001
        return self.hits[:limit]

    async def search_with_total(self, user_id, query, *, limit=20, include_archived=False):  # noqa: ANN001
        hits = await self.search(user_id, query, limit=limit, include_archived=include_archived)
        return hits, len(self.hits)

    async def count(self, user_id, query, *, all_terms=False, include_archived=False):  # noqa: ANN001
        return len(self.hits)

    async def search_claims(  # noqa: ANN001
        self, user_id, query, *, limit=40, include_archived=False
    ):
        return []


class FakeVector:
    def __init__(self, hits: list[Any] | None = None) -> None:
        self.hits = list(hits or [])

    async def search(  # noqa: ANN001
        self, user_id, embedding, *, limit=20, representation="raw", include_archived=False
    ):
        return self.hits[:limit] if representation == "raw" else []

    async def search_claims(  # noqa: ANN001
        self, user_id, embedding, *, limit=40, include_archived=False
    ):
        return []


class FakeEmbeddings:
    async def aembed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    async def aembed_documents(self, texts):  # noqa: ANN001
        return [[0.1, 0.2, 0.3] for _ in texts]


@dataclass
class LexHit:
    source_id: SourceId
    block_index: int
    text: str
    score: float = 1.0


@dataclass
class VecHit:
    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    score: float = 1.0
    char_start: int = 0
    char_end: int = 0
    representation: str = "raw"
    episode_summary_text: str = ""


def document(path: str, body: str, **frontmatter: Any) -> CanonicalDocument:
    fm = {"doc_id": frontmatter.pop("doc_id", path.replace("/", "-")), "type": "topic",
          "slug": path.rsplit("/", 1)[-1].removesuffix(".md"), **frontmatter}
    return CanonicalDocument(
        doc_id=DocumentId(str(fm["doc_id"])), path=path, frontmatter=fm, body=body
    )


def source(
    source_id: str = "s-01",
    *,
    blocks: list[str] | None = None,
    title: str = "kickoff meeting",
    kind: str = "conversation",
    archived_at: datetime | None = None,
) -> NormalizedSource:
    texts = blocks or ["first block", "second block", "third block"]
    return NormalizedSource(
        raw=RawSource(
            source_id=SourceId(source_id),
            user_id=USER,
            kind=kind,
            title=title,
            mime="text/plain",
            checksum=source_id,
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            # The L0 mark itself (docs/design/archive.md §2.2): null is live, and a day is
            # the day the owner retired it. Every archive-aware face reads this one field.
            archived_at=archived_at,
        ),
        blocks=[NormalizedBlock(index=i, text=t) for i, t in enumerate(texts)],
        structure=StructureMap(
            sections=[SectionSpan(path=["body"], start_block=0, end_block=len(texts) - 1)]
        ),
    )


@dataclass
class Library:
    ctx: Any
    store: InMemoryLibraryStore
    canonical: FakeCanonicalStore
    handoffs: InMemoryRecallHandoffStore
    lexical: FakeLexical
    vectors: FakeVector


def library(
    *,
    docs: list[CanonicalDocument] | None = None,
    snapshots: list[SnapshotRef] | None = None,
    trailers: dict[str, str] | None = None,
    lexical_hits: list[Any] | None = None,
    vector_hits: list[Any] | None = None,
    **settings_over: Any,
) -> Library:
    store = InMemoryLibraryStore()
    canonical = FakeCanonicalStore(docs, snapshots=snapshots, trailers=trailers)
    lexical = FakeLexical(lexical_hits)
    vectors = FakeVector(vector_hits)
    ctx = SimpleNamespace(
        settings=Settings(**settings_over),
        store=store,
        canonical=canonical,
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        media=None,
        user_info=FakeUserInfo(store),
        get_chat_model=_no_model,
    )
    return Library(
        ctx=ctx,
        store=store,
        canonical=canonical,
        handoffs=InMemoryRecallHandoffStore(),
        lexical=lexical,
        vectors=vectors,
    )


class FakeUserInfo:
    """The composite provider's shape over the in-memory store: the persisted owner picture
    when one was written, and `None` when none was.

    `None` rather than the mock synthesis on purpose — "this library has no owner profile" is
    a state the CLI has to say something honest about (`pkc profile show`), and a double that
    invented a picture would hide it.
    """

    def __init__(self, store: InMemoryLibraryStore) -> None:
        self._store = store

    async def get_profile(self, user_id):  # noqa: ANN001
        stored = await self._store.get_user_profile(user_id)
        return UserProfile.model_validate(stored) if stored is not None else None


def _no_model(role: str = "default"):
    raise RuntimeError(f"this deployment is keyless: no {role} model")
