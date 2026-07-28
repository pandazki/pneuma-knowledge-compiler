"""Incremental canonical-claim projection: only the content delta reaches indexes."""

from __future__ import annotations

from types import SimpleNamespace

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_service.projection import sync_projection

USER = UserId("u-projection-sync")


def _doc(path: str, document_id: str, body: str) -> CanonicalDocument:
    return CanonicalDocument(
        pneuma_id=DocumentId(document_id),
        path=path,
        frontmatter={"pneuma_id": document_id, "type": "note", "slug": document_id},
        body=body,
    )


class _Canonical:
    async def list(self, user_id, *, at=None):
        return [
            _doc(
                "memory/a.md",
                "doc-a",
                "# Facts\n\n- kept [cite: src-a ¶0] <!-- c:aa11 -->",
            ),
            _doc(
                "memory/b.md",
                "doc-b",
                "# Facts\n\n- changed now [cite: src-b ¶1] <!-- c:bb22 -->",
            ),
            _doc(
                "memory/c.md",
                "doc-c",
                "# Facts\n\n- newly added [cite: src-c ¶2] <!-- c:cc33 -->",
            ),
        ]


class _Store:
    def __init__(self):
        self.synced = None

    async def list_canonical_claims(self, user_id):
        return [
            {
                "document_path": "memory/a.md",
                "anchor": "aa11",
                "section_path": ["Facts"],
                "text": "kept",
                "citations": [
                    {"source_id": "src-a", "block_start": 0, "block_end": 0}
                ],
                "snapshot_ref": "sha-old",
            },
            {
                "document_path": "memory/b.md",
                "anchor": "bb22",
                "section_path": ["Facts"],
                "text": "changed before",
                "citations": [
                    {"source_id": "src-b", "block_start": 1, "block_end": 1}
                ],
                "snapshot_ref": "sha-old",
            },
            {
                "document_path": "memory/deleted.md",
                "anchor": "dd44",
                "section_path": ["Facts"],
                "text": "remove me",
                "citations": [],
                "snapshot_ref": "sha-old",
            },
        ]

    async def sync_canonical_claims(
        self, user_id, snapshot_ref, upserts, deleted_keys
    ):
        self.synced = (user_id, snapshot_ref, upserts, deleted_keys)


class _Lexical:
    def __init__(self):
        self.synced = None

    async def sync_claims(self, user_id, upserts, deleted_keys):
        self.synced = (user_id, upserts, deleted_keys)


class _Vectors:
    def __init__(self):
        self.synced = None

    async def sync_claims(self, user_id, upserts, vectors, deleted_keys):
        self.synced = (user_id, upserts, vectors, deleted_keys)


class _Embeddings:
    def __init__(self):
        self.calls = []

    async def aembed_documents(self, texts):
        self.calls.append(list(texts))
        return [[float(i), 1.0] for i, _ in enumerate(texts)]


def _ctx():
    return SimpleNamespace(
        canonical=_Canonical(),
        store=_Store(),
        lexical=_Lexical(),
        vectors=_Vectors(),
        embeddings=_Embeddings(),
    )


async def test_sync_embeds_and_upserts_only_added_or_changed_claims():
    ctx = _ctx()

    result = await sync_projection(ctx, USER, "sha-current")

    assert result.total == 3
    assert result.upserted == 2
    assert result.deleted == 1
    assert result.unchanged == 1
    assert ctx.embeddings.calls == [["changed now", "newly added"]]

    upserts = ctx.store.synced[2]
    deleted = ctx.store.synced[3]
    assert [(c.document_path, str(c.anchor)) for c in upserts] == [
        ("memory/b.md", "bb22"),
        ("memory/c.md", "cc33"),
    ]
    assert deleted == [("memory/deleted.md", "dd44")]
    assert ctx.lexical.synced[1:] == (upserts, deleted)
    assert ctx.vectors.synced[1] == upserts
    assert len(ctx.vectors.synced[2]) == 2
    assert ctx.vectors.synced[3] == deleted


async def test_zero_delta_does_not_call_embeddings():
    ctx = _ctx()
    current = await ctx.canonical.list(USER)
    from pneuma_knowledge_core.recall.projection import project_snapshot_claims

    claims = project_snapshot_claims(current)
    ctx.store.list_canonical_claims = lambda user_id: _rows(claims)

    result = await sync_projection(ctx, USER, "sha-current")

    assert result.upserted == result.deleted == 0
    assert result.unchanged == result.total == 3
    assert ctx.embeddings.calls == []


async def _rows(claims):
    return [
        {
            "document_path": claim.document_path,
            "anchor": str(claim.anchor),
            "section_path": list(claim.section_path),
            "text": claim.text,
            "citations": [
                {
                    "source_id": str(citation.source_id),
                    "block_start": citation.block_start,
                    "block_end": citation.block_end,
                }
                for citation in claim.citations
            ],
            "snapshot_ref": "sha-old",
        }
        for claim in claims
    ]
