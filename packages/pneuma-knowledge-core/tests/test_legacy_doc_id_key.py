"""Backward compatibility for the pre-rename document id key.

The canonical id frontmatter key used to be spelled `pneuma_id`. Canonical is the one
non-rebuildable layer (invariant I2), so documents already committed in a deployed git
authority repo keep that spelling and are never rewritten by a history migration. The
contract these tests pin: READS accept the legacy spelling and fold it onto `doc_id`, the
gate never reports a legacy-only document as missing its id, and WRITES only ever emit
`doc_id` — so a legacy document migrates for free the next time it is serialized.
"""

from datetime import datetime, timezone

from pneuma_knowledge_core.compile.documents import (
    normalize_frontmatter,
    parse_document,
    render_document,
)
from pneuma_knowledge_core.compile.gate import run_gate
from pneuma_knowledge_core.compile.patch import DraftDoc, PatchDraft
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)

TEMPLATES = ["memory/profile.md", "memory/people/{slug}.md", "memory/topics/{slug}.md"]

# A document as it sits in a repo compiled before the rename: legacy id key, and a claim
# whose citation was validated at its own commit.
LEGACY_FILE = (
    "---\n"
    "pneuma_id: d-song-yao\n"
    "slug: song-yao\n"
    "type: person\n"
    "---\n"
    "\n"
    "## 宋遥\n"
    "\n"
    "- 宋遥 负责 Atlas 的检索评测。[cite: src-01 ¶0] <!-- c:aa11 -->\n"
)


def _source() -> NormalizedSource:
    return NormalizedSource(
        raw=RawSource(
            source_id=SourceId("src-01"),
            user_id=UserId("u-1"),
            kind="conversation",
            title="t",
            mime="text/plain",
            checksum="src-01",
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=i, text=f"b{i}") for i in range(3)],
        structure=StructureMap(),
    )


# --- read side ----------------------------------------------------------------


def test_parsing_a_legacy_document_yields_doc_id_and_drops_the_legacy_key():
    frontmatter, body = parse_document(LEGACY_FILE)
    assert frontmatter["doc_id"] == "d-song-yao"
    assert "pneuma_id" not in frontmatter  # one spelling reaches every caller
    assert "c:aa11" in body


def test_an_explicit_doc_id_wins_over_the_legacy_key():
    normalized = normalize_frontmatter(
        {"pneuma_id": "d-old", "doc_id": "d-new", "type": "person", "slug": "song-yao"}
    )
    assert normalized["doc_id"] == "d-new"
    assert "pneuma_id" not in normalized


def test_normalizing_a_current_document_changes_nothing():
    current = {"doc_id": "d-song-yao", "type": "person", "slug": "song-yao"}
    assert normalize_frontmatter(current) == current


# --- gate ---------------------------------------------------------------------


def test_gate_accepts_a_document_carrying_only_the_legacy_id_key():
    """A legacy document that reached the gate un-normalized is not hard-rejected: the
    frontmatter check treats `pneuma_id` as a read-side alias of `doc_id`."""
    path = "memory/people/song-yao.md"
    draft = PatchDraft.from_canonical([], TEMPLATES)
    draft._working[path] = DraftDoc(
        path,
        DocumentId("d-song-yao"),
        {"pneuma_id": "d-song-yao", "type": "person", "slug": "song-yao"},
        "- 宋遥 负责 Atlas 的检索评测。[cite: src-01 ¶0] <!-- c:aa11 -->",
    )
    assert run_gate(draft, [_source()]) == []


def test_gate_still_rejects_a_document_with_neither_id_spelling():
    path = "memory/people/song-yao.md"
    draft = PatchDraft.from_canonical([], TEMPLATES)
    draft._working[path] = DraftDoc(
        path,
        DocumentId("d-song-yao"),
        {"type": "person", "slug": "song-yao"},
        "- 宋遥 负责 Atlas 的检索评测。[cite: src-01 ¶0] <!-- c:aa11 -->",
    )
    v = [x for x in run_gate(draft, [_source()]) if x.kind == "frontmatter"]
    assert len(v) == 1 and "doc_id" in v[0].detail


# --- write side ---------------------------------------------------------------


def test_reserializing_a_legacy_document_emits_only_the_new_key():
    """Load → serialize is the lazy migration path: the next commit that re-renders this
    file writes `doc_id`, and the legacy spelling never round-trips back to disk."""
    frontmatter, body = parse_document(LEGACY_FILE)
    rendered = render_document(frontmatter, body)
    assert "doc_id: d-song-yao" in rendered
    assert "pneuma_id" not in rendered
    assert parse_document(rendered)[0] == frontmatter
