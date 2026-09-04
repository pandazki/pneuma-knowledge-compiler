"""LexicalIndex over Meilisearch (ADR-002). L1, unconditional (I3).

Index-per-user: `blocks_<sanitized_uid>` — the physical isolation boundary (I1).
CJK tokenization is Meilisearch's built-in charabia (jieba/lindera), the reason it
was chosen over PG FTS; middle/Japanese query recall is an M1 acceptance item.
Documents are blocks; hits carry source_id + block_index + snippet + score, the
unified addressing that RRF fuses with the vector path (I4).

Client: `meilisearch-python-sdk`'s `AsyncClient` — genuinely async (httpx under the
hood), not a thread-pool shim. The official `meilisearch` package ships a sync-only
client, which would block the single service event loop on every L1 call.

THE ARCHIVE FILTER (docs/design/archive.md §3). Both indexes carry one derived boolean,
`archived`, and both default searches exclude it with the filter expression

    NOT archived = true

verified empirically against Meilisearch v1.11: a document that carries NO `archived`
attribute at all is RETURNED by that filter, alongside `archived = false`. That is the
property the expression is chosen for — every block and claim document written before this
field existed reads as LIVE, so a deployment that has not yet rebuilt its derived layer
keeps answering exactly as it did. (`archived != true` behaves identically; `archived =
false` alone would silently drop every legacy document, and is the trap this note exists to
name.) The excluding filter is applied at the index and not after it: an archive that
reached the candidate list would eat the caps before the answer ever saw a live item.
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
    return _claim_doc_id_from_key(claim.document_path, str(claim.anchor))


def _claim_doc_id_from_key(document_path: str, anchor: str) -> str:
    # anchor is unique within a document; short path hash disambiguates across docs.
    path_hash = hashlib.sha1(document_path.encode("utf-8")).hexdigest()[:8]
    return f"{anchor}_{path_hash}"


#: The L1 blocks index settings. `filterable_attributes` is what makes the archive filter
#: legal at all — Meilisearch REFUSES a filter on an unconfigured attribute rather than
#: ignoring it, which is why the read path below configures an index it finds unconfigured
#: instead of letting the refusal be swallowed as "no hits". `source_id` is filterable beside
#: it so a flip can be addressed by source.
_BLOCK_SETTINGS = MeilisearchSettings(
    searchable_attributes=["text"],
    displayed_attributes=["source_id", "block_index", "text", "archived"],
    filterable_attributes=["archived", "source_id"],
)

#: The L3 claims index settings. `document_path` is filterable so the archive's unit — a
#: page — is addressable here the way a source is addressable in the blocks index.
_CLAIM_SETTINGS = MeilisearchSettings(
    searchable_attributes=["text", "section_path"],
    displayed_attributes=[
        "anchor",
        "document_path",
        "section_path",
        "text",
        "citations",
        "archived",
    ],
    filterable_attributes=["archived", "document_path"],
)

#: The one excluding filter, stated once. See the module docstring for why `NOT … = true`
#: and not `= false`: a document written before the attribute existed must read as live.
_NOT_ARCHIVED = "NOT archived = true"

#: Meilisearch's code for "that index does not exist". The ONLY api error that means
#: absence.
_INDEX_NOT_FOUND = "index_not_found"


def _is_missing_index(exc: MeilisearchApiError) -> bool:
    """True only for "no such index". Every other api error is a real one.

    `except MeilisearchApiError: return []` reads an auth failure, a connection reset or a
    500 as "this user has nothing indexed" — the lane goes quiet and the answer is built as
    if the library held no lexical material, which is the one failure mode a citation-backed
    system must never have silently. Absence is a specific code; everything else propagates
    to the caller that can log it, retry it, or fail the request.
    """
    return getattr(exc, "code", "") == _INDEX_NOT_FOUND


class MeiliLexicalIndex:
    def __init__(self, url: str, api_key: str = "") -> None:
        self._client = AsyncClient(url, api_key or None)
        self._configured: set[str] = set()

    async def _configure(self, uid: str, settings: MeilisearchSettings) -> None:
        """Apply an index's settings once per PROCESS, memoized in `_configured`.

        Once per process and not once per index life: an index created by an older build —
        or by an older process of this one — carries the settings that build declared, and
        this process has no way to know which. A settings update is idempotent and cheap, so
        the memo's job is only to keep it off the hot path, never to decide that an index
        someone else created is already right.
        """
        if uid in self._configured:
            return
        task = await self._client.index(uid).update_settings(settings)
        await self._client.wait_for_task(task.task_uid)
        self._configured.add(uid)

    async def _configure_for_read(
        self, uid: str, settings: MeilisearchSettings
    ) -> bool:
        """Configure an EXISTING index before filtering on it; False when it does not exist.

        The read path has to do this because a process that only ever SEARCHES (the API,
        while the worker owns indexing) would otherwise filter against whatever settings the
        index happened to be created with, and Meilisearch answers a filter on an
        unconfigured attribute with an error that `search` below turns into an empty result —
        the whole L1/L3 lane going quiet with nothing to read about it.

        Existence is probed rather than assumed so a search never CREATES an index: a
        settings update auto-creates one in Meilisearch, and a user who has indexed nothing
        must stay a user with no index.
        """
        if uid in self._configured:
            return True
        try:
            await self._client.index(uid).fetch_info()
        except MeilisearchApiError as exc:
            if not _is_missing_index(exc):
                raise
            return False
        await self._configure(uid, settings)
        return True

    async def _ensure_index(self, uid: str) -> AsyncIndex:
        await self._configure(uid, _BLOCK_SETTINGS)
        return self._client.index(uid)

    async def index_blocks(
        self,
        user_id: UserId,
        source_id: SourceId,
        blocks: list[NormalizedBlock],
        *,
        archived: bool = False,
    ) -> None:
        """Index one source's blocks. INDEXING is unconditional (invariant I3) — an archived
        source is indexed like any other and simply carries `archived=True`, so it stays
        reachable by an `include_archived` search and needs no re-index to come back."""
        index = await self._ensure_index(_index_uid(user_id))
        docs = [
            {
                "id": f"{source_id}_{b.index}",
                "source_id": str(source_id),
                "block_index": b.index,
                "text": b.index_text(),
                "section_path": b.section_path,
                "archived": archived,
            }
            for b in blocks
        ]
        if not docs:
            return
        task = await index.add_documents(docs, primary_key="id")
        # Synchronous indexing so recall right after intake is consistent (M1).
        await self._client.wait_for_task(task.task_uid)

    async def set_source_archived(
        self,
        user_id: UserId,
        source_id: SourceId,
        block_count: int,
        archived: bool,
    ) -> None:
        """Flip one source's block documents to `archived`, without re-indexing their text.

        A PARTIAL update (`update_documents` merges rather than replaces), addressed by the
        deterministic `{source_id}_{block_index}` ids `index_blocks` writes — so the flip
        costs one request and cannot disturb the verbatim text it does not mention. The
        caller passes the source's block count because L0 is the authority on how many
        blocks a source has; this index is derived and is not asked.
        """
        if block_count <= 0:
            return
        index = await self._ensure_index(_index_uid(user_id))
        task = await index.update_documents(
            [
                {"id": f"{source_id}_{i}", "archived": archived}
                for i in range(block_count)
            ],
            primary_key="id",
        )
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
        self,
        user_id: UserId,
        query: str,
        *,
        limit: int = 20,
        include_archived: bool = False,
    ) -> list[LexicalHitRow]:
        """L1 lexical search. The archive is excluded unless the call says otherwise.

        See the module docstring for the filter expression and why a legacy document with no
        `archived` attribute still reads as live under it."""
        uid = _index_uid(user_id)
        if not await self._configure_for_read(uid, _BLOCK_SETTINGS):
            return []  # index absent (user has no indexed blocks yet) → no L1 hits
        index = self._client.index(uid)
        try:
            result = await index.search(
                query,
                limit=limit,
                show_ranking_score=True,
                filter=None if include_archived else _NOT_ARCHIVED,
            )
        except MeilisearchApiError as exc:
            if not _is_missing_index(exc):
                raise  # auth / connection / server: a real failure, never "no hits"
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
        await self._configure(uid, _CLAIM_SETTINGS)
        return self._client.index(uid)

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
                # Derived from the claim's document path by the projection, never decided
                # here (docs/design/archive.md §2.1).
                "archived": c.archived,
            }
            for c in claims
        ]
        task = await index.add_documents(docs, primary_key="id")
        await self._client.wait_for_task(task.task_uid)

    async def sync_claims(
        self,
        user_id: UserId,
        upserts: list[ProjectedClaim],
        deleted_keys: list[tuple[str, str]],
    ) -> None:
        """Idempotently apply only the changed canonical claim documents."""
        index = await self._ensure_claims_index(_claims_index_uid(user_id))
        if deleted_keys:
            task = await index.delete_documents(
                [
                    _claim_doc_id_from_key(document_path, anchor)
                    for document_path, anchor in deleted_keys
                ]
            )
            await self._client.wait_for_task(task.task_uid)
        if not upserts:
            return
        docs = [
            {
                "id": _claim_doc_id(claim),
                "anchor": str(claim.anchor),
                "document_path": claim.document_path,
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
                "archived": claim.archived,
            }
            for claim in upserts
        ]
        task = await index.add_documents(docs, primary_key="id")
        await self._client.wait_for_task(task.task_uid)

    async def count_claims(self, user_id: UserId) -> int:
        """Exact claim-document count for projection consistency audits."""
        try:
            stats = await self._client.index(
                _claims_index_uid(user_id)
            ).get_stats()
        except MeilisearchApiError:
            return 0
        return int(stats.number_of_documents)

    async def search_claims(
        self,
        user_id: UserId,
        query: str,
        *,
        limit: int = 40,
        include_archived: bool = False,
    ) -> list[ClaimHitRow]:
        """L3 lexical claim search; the archive is excluded unless the call says otherwise."""
        uid = _claims_index_uid(user_id)
        if not await self._configure_for_read(uid, _CLAIM_SETTINGS):
            return []  # claims index absent (user never compiled) → no L3 lexical hits
        index = self._client.index(uid)
        try:
            result = await index.search(
                query,
                limit=limit,
                show_ranking_score=True,
                filter=None if include_archived else _NOT_ARCHIVED,
            )
        except MeilisearchApiError as exc:
            if not _is_missing_index(exc):
                raise  # auth / connection / server: a real failure, never "no hits"
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
