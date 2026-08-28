"""Incremental canonical-claim projection: only the content delta reaches indexes.

Plus the three refusals that keep the delta from becoming a demolition — see the guardrail
section at the bottom, and the module docstring of `projection.py` for the incident that put
them there.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_service.projection import (
    ProjectionRefused,
    rebuild_projection,
    sync_projection,
)

USER = UserId("u-projection-sync")


def _doc(path: str, document_id: str, body: str) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId(document_id),
        path=path,
        frontmatter={"doc_id": document_id, "type": "note", "slug": document_id},
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


# ============================================================================== guardrails


class _EmptyCanonical:
    """What a wrong, missing or freshly-initialized canonical root reads like: no documents."""

    async def list(self, user_id, *, at=None):  # noqa: ARG002
        return []

    async def snapshots(self, user_id):  # noqa: ARG002
        return []


class _UnreadableCanonical:
    """A store that cannot resolve the ref — the commit lives in some OTHER repository."""

    async def list(self, user_id, *, at=None):  # noqa: ARG002
        if at is None:
            return []
        raise RuntimeError(f"fatal: bad revision {at.ref!r}")


def _empty_ctx(canonical):
    ctx = _ctx()
    ctx.canonical = canonical
    return ctx


async def test_rebuilding_from_an_empty_canonical_refuses_to_wipe_the_projection():
    """The exact shape of the incident: a repair pointed at the wrong root read zero
    documents, and the whole-table replace carried out "delete everything" without objection."""
    ctx = _empty_ctx(_EmptyCanonical())

    with pytest.raises(ProjectionRefused) as excinfo:
        await rebuild_projection(ctx, USER)

    assert excinfo.value.reason == "empty_canonical"
    assert excinfo.value.facts == {"snapshot_ref": "HEAD", "projected": 3}
    # The message states the damage it prevented, in numbers.
    assert "3 projected claims" in str(excinfo.value)
    assert ctx.store.synced is None  # nothing reached the stores


async def test_allow_wipe_is_the_escape_hatch_when_the_repo_really_is_empty():
    ctx = _empty_ctx(_EmptyCanonical())
    ctx.store.replace_canonical_claims = _record(ctx, "replaced")
    ctx.lexical.index_claims = _record(ctx, "indexed")
    ctx.vectors.delete_claims = _record(ctx, "dropped")

    assert await rebuild_projection(ctx, USER, allow_wipe=True) == 0
    assert ctx.calls["replaced"] and ctx.calls["indexed"] and ctx.calls["dropped"]


async def test_an_empty_canonical_over_an_empty_projection_is_not_a_wipe():
    """There is nothing to protect, so the guard must not turn a first-ever rebuild into an
    error the operator has to override."""
    ctx = _empty_ctx(_EmptyCanonical())
    ctx.store.list_canonical_claims = _empty_rows
    ctx.store.replace_canonical_claims = _record(ctx, "replaced")
    ctx.lexical.index_claims = _record(ctx, "indexed")
    ctx.vectors.delete_claims = _record(ctx, "dropped")

    assert await rebuild_projection(ctx, USER) == 0


async def test_a_ref_this_store_cannot_read_fails_loud_instead_of_projecting():
    """A ref that does not resolve HERE means the commit landed in a different repository.
    That is the first observable moment of a root mismatch, and it has no escape hatch — an
    unreadable ref is never a deliberate operation."""
    ctx = _empty_ctx(_UnreadableCanonical())

    with pytest.raises(ProjectionRefused) as excinfo:
        await sync_projection(ctx, USER, "sha-from-another-repo")

    assert excinfo.value.reason == "unresolvable_snapshot_ref"
    assert excinfo.value.facts["snapshot_ref"] == "sha-from-another-repo"
    assert "different repository" in str(excinfo.value)
    assert ctx.store.synced is None


async def test_a_sync_that_would_lose_most_of_the_projection_is_refused_and_counts_it():
    ctx = _ctx()
    # Canonical now holds ONE of the three projected claims: two anchors would vanish.
    ctx.canonical = _OneDocCanonical()

    with pytest.raises(ProjectionRefused) as excinfo:
        await sync_projection(ctx, USER, "sha-current")

    assert excinfo.value.reason == "excessive_claim_loss"
    assert excinfo.value.facts["lost"] == 2
    assert excinfo.value.facts["projected"] == 3
    assert ctx.store.synced is None

    # …and the same sync goes through when the loss is declared intentional.
    ctx2 = _ctx()
    ctx2.canonical = _OneDocCanonical()
    result = await sync_projection(ctx2, USER, "sha-current", allow_wipe=True)
    assert result.total == 1 and result.deleted == 2


async def test_moving_claims_between_documents_is_not_loss_however_large_the_move():
    """A rollover deletes every key it moves and re-inserts it under the volume's path, so a
    key-counting guardrail would refuse a groom of a small base as if it were a wipe. Loss is
    counted in anchors, which survive the move."""
    ctx = _ctx()
    ctx.canonical = _ArchivedCanonical()

    result = await sync_projection(ctx, USER, "sha-groomed")

    assert result.deleted == 3 and result.upserted == 3  # every claim re-keyed
    assert ctx.store.synced is not None


class _OneDocCanonical:
    async def list(self, user_id, *, at=None):  # noqa: ARG002
        return [
            _doc(
                "memory/a.md",
                "doc-a",
                "# Facts\n\n- kept [cite: src-a ¶0] <!-- c:aa11 -->",
            )
        ]


class _ArchivedCanonical:
    """Every claim moved into an archive volume: same anchors, different document paths."""

    async def list(self, user_id, *, at=None):  # noqa: ARG002
        return [
            _doc(
                "memory/a/a01.md",
                "doc-a01",
                "# Facts\n\n"
                "- kept [cite: src-a ¶0] <!-- c:aa11 -->\n"
                "- changed before [cite: src-b ¶1] <!-- c:bb22 -->\n"
                "- remove me <!-- c:dd44 -->",
            )
        ]


async def _empty_rows(user_id):  # noqa: ARG001
    return []


def _record(ctx, name: str):
    ctx.calls = getattr(ctx, "calls", {})

    async def _call(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        ctx.calls[name] = True

    return _call


# ================================================== the head churns, the ledger is the base

# A document's overview region is a rewritable head: `rewrite_overview` replaces every block
# and RETIRES the anchors of the blocks it replaced. In a young library the head is a large
# share of everything projected (live: 8 overview claims out of 14), so a guardrail counting
# retired overview anchors as loss refuses the tenant's first honest rewrite. Loss is counted
# over LEDGER anchors on both sides of the ratio.

_LEDGER = "\n".join(
    [
        "## Facts",
        "",
        "- kept one [cite: src-a ¶0] <!-- c:1ed00001 -->",
        "- kept two [cite: src-b ¶1] <!-- c:1ed00002 -->",
        "- kept three [cite: src-c ¶2] <!-- c:1ed00003 -->",
    ]
)

_REWRITTEN_OVERVIEW = "\n".join(
    [
        "<!-- overview -->",
        "",
        "<!-- overview:definition -->",
        "### Definition",
        "",
        "Aurora is the qualification pipeline. [cite: src-a ¶0] <!-- c:abcd0001 -->",
        "",
        "<!-- overview:summary -->",
        "### Summary",
        "",
        "Rollout reached stage two. [cite: src-b ¶1] <!-- c:abcd0002 -->",
        "",
        "<!-- /overview -->",
    ]
)


def _overview_doc(ledger: str = _LEDGER) -> CanonicalDocument:
    return _doc(
        "memory/aurora.md",
        "doc-aurora",
        f"# Aurora\n\n{_REWRITTEN_OVERVIEW}\n\n{ledger}",
    )


class _RewrittenOverviewCanonical:
    """The snapshot after one `rewrite_overview`: brand-new overview anchors, same ledger."""

    def __init__(self, ledger: str = _LEDGER):
        self._ledger = ledger

    async def list(self, user_id, *, at=None):  # noqa: ARG002
        return [_overview_doc(self._ledger)]


def _previous_rows() -> list[dict]:
    """What that page projected BEFORE the rewrite: 3 ledger claims and 6 head blocks."""
    ledger = [
        {
            "document_path": "memory/aurora.md",
            "anchor": anchor,
            "section_path": ["Aurora", "Facts"],
            "text": text,
            "citations": [
                {"source_id": source, "block_start": block, "block_end": block}
            ],
            "snapshot_ref": "sha-old",
        }
        for anchor, text, source, block in (
            ("1ed00001", "kept one", "src-a", 0),
            ("1ed00002", "kept two", "src-b", 1),
            ("1ed00003", "kept three", "src-c", 2),
        )
    ]
    head = [
        {
            "document_path": "memory/aurora.md",
            "anchor": f"0da0000{i}",
            "section_path": ["overview", slot],
            "text": f"the picture as it was ({i})",
            "citations": [{"source_id": "src-a", "block_start": 0, "block_end": 0}],
            "snapshot_ref": "sha-old",
        }
        for i, slot in enumerate(
            ("definition", "summary", "introduction", "connections", "summary", "definition"),
            start=1,
        )
    ]
    return ledger + head


def _overview_ctx(canonical=None, previous=None):
    ctx = _ctx()
    ctx.canonical = canonical or _RewrittenOverviewCanonical()
    rows = _previous_rows() if previous is None else previous

    async def _list(user_id):  # noqa: ARG001
        return rows

    ctx.store.list_canonical_claims = _list
    return ctx


def _index_after(ctx) -> set[tuple[str, str]]:
    """The projected key set the stores are left holding after the sync they were handed."""
    _user, _ref, upserts, deleted = ctx.store.synced
    before = {(row["document_path"], row["anchor"]) for row in _previous_rows()}
    return (before - set(deleted)) | {
        (claim.document_path, str(claim.anchor)) for claim in upserts
    }


async def test_retiring_every_overview_anchor_is_not_knowledge_loss():
    """6 of 9 projected claims are head blocks; the rewrite retires all six. Counted whole
    that is 67% loss and a refusal — counted over the ledger it is zero, which is the truth:
    not one claim of the knowledge base went anywhere."""
    ctx = _overview_ctx()

    result = await sync_projection(ctx, USER, "sha-rewritten")

    assert result.total == 5  # 3 ledger + 2 rewritten head blocks
    assert result.unchanged == 3  # the ledger, untouched and not re-embedded
    assert result.upserted == 2 and result.deleted == 6
    assert ctx.embeddings.calls == [
        ["Aurora is the qualification pipeline.", "Rollout reached stage two."]
    ]

    # The index ends holding the ledger plus EXACTLY the new head — no stale overview key.
    assert _index_after(ctx) == {
        ("memory/aurora.md", "1ed00001"),
        ("memory/aurora.md", "1ed00002"),
        ("memory/aurora.md", "1ed00003"),
        ("memory/aurora.md", "abcd0001"),
        ("memory/aurora.md", "abcd0002"),
    }
    # …and the same delta reached the two remote faces, retired keys included.
    assert set(ctx.lexical.synced[2]) == set(ctx.vectors.synced[3]) == {
        ("memory/aurora.md", f"0da0000{i}") for i in range(1, 7)
    }


async def test_a_ledger_wipe_still_refuses_behind_the_churning_head():
    """The head no longer counts, so the guardrail must still be counting SOMETHING: dropping
    2 of the 3 ledger claims is 67% of the knowledge base and is refused at the same half."""
    ctx = _overview_ctx(
        _RewrittenOverviewCanonical(
            "## Facts\n\n- kept one [cite: src-a ¶0] <!-- c:1ed00001 -->"
        )
    )

    with pytest.raises(ProjectionRefused) as excinfo:
        await sync_projection(ctx, USER, "sha-rewritten")

    assert excinfo.value.reason == "excessive_claim_loss"
    assert excinfo.value.facts["lost"] == 2
    assert excinfo.value.facts["projected"] == 3  # the ledger is the base, not the 9 rows
    assert excinfo.value.facts["overview_excluded"] == 6
    assert "ledger claims" in str(excinfo.value)
    assert ctx.store.synced is None


async def test_allow_wipe_still_carries_a_ledger_wipe_through():
    """The escape hatch is untouched by the ledger scoping: a declared wipe still executes."""
    ctx = _overview_ctx(
        _RewrittenOverviewCanonical(
            "## Facts\n\n- kept one [cite: src-a ¶0] <!-- c:1ed00001 -->"
        )
    )

    result = await sync_projection(ctx, USER, "sha-rewritten", allow_wipe=True)

    assert result.total == 3 and result.deleted == 8
    assert _index_after(ctx) == {
        ("memory/aurora.md", "1ed00001"),
        ("memory/aurora.md", "abcd0001"),
        ("memory/aurora.md", "abcd0002"),
    }
