"""LexicalIndex over Meilisearch (ADR-002). L1, unconditional (I3).

Index-per-user: `blocks_<sanitized_uid>` — the physical isolation boundary (I1).
CJK tokenization is Meilisearch's built-in charabia (jieba/lindera), the reason it
was chosen over PG FTS; middle/Japanese query recall is an M1 acceptance item.
Documents are blocks; hits carry source_id + block_index + snippet + score, the
unified addressing that RRF fuses with the vector path (I4).

Client: `meilisearch-python-sdk`'s `AsyncClient` — genuinely async (httpx under the
hood), not a thread-pool shim. The official `meilisearch` package ships a sync-only
client, which would block the single service event loop on every L1 call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import hashlib
from typing import Any

from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import NormalizedBlock
from pneuma_knowledge_core.recall.projection import ProjectedClaim
from meilisearch_python_sdk import AsyncClient, AsyncIndex
from meilisearch_python_sdk.errors import MeilisearchApiError
from meilisearch_python_sdk.models.settings import MeilisearchSettings

_UID_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


@dataclass(frozen=True)
class LexicalHitRow:
    source_id: SourceId
    block_index: int
    text: str
    score: float


@dataclass(frozen=True)
class ClaimHitRow:
    """L3 lexical claim hit — the ClaimHit shape core recall fuses (ports/claim_index)."""

    anchor: str
    document_path: str
    section_path: list[str]
    text: str
    citations: list[dict[str, Any]]
    score: float


def _index_uid(user_id: UserId) -> str:
    return f"blocks_{_UID_SAFE.sub('_', str(user_id))}"


def _claims_index_uid(user_id: UserId) -> str:
    # L3 claim retrieval face — a separate per-user index (invariant I1).
    return f"claims_{_UID_SAFE.sub('_', str(user_id))}"


def _claim_doc_id(claim: ProjectedClaim) -> str:
    # anchor is unique within a document; short path hash disambiguates across docs.
    path_hash = hashlib.sha1(claim.document_path.encode("utf-8")).hexdigest()[:8]
    return f"{claim.anchor}_{path_hash}"


class MeiliLexicalIndex:
    def __init__(self, url: str, api_key: str = "") -> None:
        self._client = AsyncClient(url, api_key or None)
        self._configured: set[str] = set()

    async def _ensure_index(self, uid: str) -> AsyncIndex:
        index = self._client.index(uid)
        if uid not in self._configured:
            task = await index.update_settings(
                MeilisearchSettings(
                    searchable_attributes=["text"],
                    displayed_attributes=["source_id", "block_index", "text"],
                )
            )
            await self._client.wait_for_task(task.task_uid)
            self._configured.add(uid)
        return index

    async def index_blocks(
        self,
        user_id: UserId,
        source_id: SourceId,
        blocks: list[NormalizedBlock],
    ) -> None:
        index = await self._ensure_index(_index_uid(user_id))
        docs = [
            {
                "id": f"{source_id}_{b.index}",
                "source_id": str(source_id),
                "block_index": b.index,
                "text": b.text,
                "section_path": b.section_path,
            }
            for b in blocks
        ]
        if not docs:
            return
        task = await index.add_documents(docs, primary_key="id")
        # Synchronous indexing so recall right after intake is consistent (M1).
        await self._client.wait_for_task(task.task_uid)

    async def delete_user(self, user_id: UserId) -> None:
        """Drop the user's per-user indexes — blocks + claims (test-teardown hygiene)."""
        for uid in (_index_uid(user_id), _claims_index_uid(user_id)):
            try:
                task = await self._client.index(uid).delete()
                await self._client.wait_for_task(task.task_uid)
            except MeilisearchApiError:
                pass  # index absent → nothing to clean
            self._configured.discard(uid)

    async def search(
        self, user_id: UserId, query: str, *, limit: int = 20
    ) -> list[LexicalHitRow]:
        index = self._client.index(_index_uid(user_id))
        try:
            result = await index.search(query, limit=limit, show_ranking_score=True)
        except MeilisearchApiError:
            return []  # index absent (user has no indexed blocks yet) → no L1 hits
        return [
            LexicalHitRow(
                source_id=SourceId(hit["source_id"]),
                block_index=int(hit["block_index"]),
                text=hit["text"],
                score=float(hit.get("_rankingScore", 0.0)),
            )
            for hit in result.hits
        ]

    # --- L3 claim retrieval face (M4) ----------------------------------------

    async def _ensure_claims_index(self, uid: str) -> AsyncIndex:
        index = self._client.index(uid)
        if uid not in self._configured:
            task = await index.update_settings(
                MeilisearchSettings(
                    searchable_attributes=["text", "section_path"],
                    displayed_attributes=[
                        "anchor",
                        "document_path",
                        "section_path",
                        "text",
                        "citations",
                    ],
                )
            )
            await self._client.wait_for_task(task.task_uid)
            self._configured.add(uid)
        return index

    async def index_claims(
        self, user_id: UserId, claims: list[ProjectedClaim]
    ) -> None:
        """Full rebuild (derived, I2): wipe the user's claims index and re-add all
        projected claims. A commit-driven projection always rebuilds in whole."""
        uid = _claims_index_uid(user_id)
        index = await self._ensure_claims_index(uid)
        clear = await index.delete_all_documents()
        await self._client.wait_for_task(clear.task_uid)
        if not claims:
            return
        docs = [
            {
                "id": _claim_doc_id(c),
                "anchor": str(c.anchor),
                "document_path": c.document_path,
                "section_path": list(c.section_path),
                "text": c.text,
                "citations": [
                    {
                        "source_id": str(cit.source_id),
                        "block_start": cit.block_start,
                        "block_end": cit.block_end,
                    }
                    for cit in c.citations
                ],
            }
            for c in claims
        ]
        task = await index.add_documents(docs, primary_key="id")
        await self._client.wait_for_task(task.task_uid)

    async def search_claims(
        self, user_id: UserId, query: str, *, limit: int = 40
    ) -> list[ClaimHitRow]:
        index = self._client.index(_claims_index_uid(user_id))
        try:
            result = await index.search(query, limit=limit, show_ranking_score=True)
        except MeilisearchApiError:
            return []  # claims index absent (user never compiled) → no L3 lexical hits
        return [
            ClaimHitRow(
                anchor=str(hit["anchor"]),
                document_path=hit["document_path"],
                section_path=list(hit.get("section_path") or []),
                text=hit["text"],
                citations=list(hit.get("citations") or []),
                score=float(hit.get("_rankingScore", 0.0)),
            )
            for hit in result.hits
        ]

    async def aclose(self) -> None:
        """Close the underlying httpx client (lifespan/worker shutdown)."""
        await self._client.aclose()
