"""Evolve gate profile (schema-evolve §B3): repo-level anchor continuity + dropped
anchors, store-real citation validation with repo-level grandfathering, path ownership
against the new skill's templates."""

from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_core.evolve.gate import run_evolve_gate

TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "memory/topics/{slug}.md",
    "memory/products/{slug}.md",
    "materials/{slug}.md",
]


def _topic(slug: str, body: str) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=f"memory/topics/{slug}.md",
        frontmatter={"doc_id": f"d-{slug}", "type": "topic", "slug": slug},
        body=body,
    )


def _kinds(violations) -> set[str]:
    return {v.kind for v in violations}


class _CountingBounds:
    """source_bounds stub that records every source id it is asked about."""

    def __init__(self, bounds: dict[str, int]) -> None:
        self._bounds = bounds
        self.calls: list[str] = []

    async def __call__(self, source_id: str) -> int | None:
        self.calls.append(source_id)
        return self._bounds.get(source_id)


async def test_move_keeps_anchor_no_violation_no_dropped():
    src = _topic("atlas", "## 计划\n\n- Atlas Q3 发布。[cite: src-01 ¶2] <!-- c:aa11 -->")
    draft = PatchDraft.from_canonical([src], TEMPLATES)
    draft.create_document(
        "memory/products/atlas.md", {"type": "product", "slug": "atlas"}, "## 产品\n"
    )
    draft.move_claim("memory/topics/atlas.md", "aa11", "memory/products/atlas.md", "产品")

    bounds = _CountingBounds({"src-01": 5})
    violations, dropped = await run_evolve_gate(
        draft, source_bounds=bounds, path_templates=TEMPLATES
    )
    assert violations == []
    assert dropped == []
    # The moved citation is a verbatim base carry-over → repo-level grandfathered, never
    # hits the store (the whole point of the exemption).
    assert bounds.calls == []


async def test_delete_produces_dropped_anchor_not_violation():
    src = _topic(
        "atlas",
        "- 计划发布。[cite: src-01 ¶0] <!-- c:aa11 -->\n"
        "- 冗余重复。[cite: src-01 ¶1] <!-- c:bb22 -->",
    )
    draft = PatchDraft.from_canonical([src], TEMPLATES)
    draft.delete_claim("memory/topics/atlas.md", "bb22")

    bounds = _CountingBounds({"src-01": 5})
    violations, dropped = await run_evolve_gate(
        draft, source_bounds=bounds, path_templates=TEMPLATES
    )
    assert "anchor_continuity" not in _kinds(violations)
    assert [d.anchor for d in dropped] == ["bb22"]
    assert dropped[0].old_path == "memory/topics/atlas.md"
    assert "冗余重复" in dropped[0].text  # original text carried for the review page


async def test_new_citation_out_of_range_is_violation():
    src = _topic("atlas", "## 计划\n")
    draft = PatchDraft.from_canonical([src], TEMPLATES)
    draft.create_document(
        "memory/products/atlas.md",
        {"type": "product", "slug": "atlas"},
        "- 新写事实。[cite: src-09 ¶9]",  # src-09 has only 3 blocks → ¶9 out of range
    )
    bounds = _CountingBounds({"src-09": 3})
    violations, dropped = await run_evolve_gate(
        draft, source_bounds=bounds, path_templates=TEMPLATES
    )
    assert "citation" in _kinds(violations)
    assert bounds.calls == ["src-09"]  # a NEW citation is validated against the store


async def test_grouped_new_citation_validates_each_span():
    src = _topic("atlas", "## 计划\n")
    draft = PatchDraft.from_canonical([src], TEMPLATES)
    draft.create_document(
        "memory/products/atlas.md",
        {"type": "product", "slug": "atlas"},
        "- 新写事实。[cite: src-09 ¶1-2,6]",
    )
    bounds = _CountingBounds({"src-09": 3})
    violations, _ = await run_evolve_gate(
        draft, source_bounds=bounds, path_templates=TEMPLATES
    )
    citation_violations = [item for item in violations if item.kind == "citation"]
    assert len(citation_violations) == 1
    assert "¶6-6" in citation_violations[0].detail
    assert bounds.calls == ["src-09", "src-09"]


async def test_new_citation_missing_source_is_violation():
    src = _topic("atlas", "## 计划\n")
    draft = PatchDraft.from_canonical([src], TEMPLATES)
    draft.create_document(
        "memory/products/atlas.md",
        {"type": "product", "slug": "atlas"},
        "- 新写事实。[cite: ghost ¶0]",
    )
    bounds = _CountingBounds({})  # ghost not in store → None
    violations, _ = await run_evolve_gate(
        draft, source_bounds=bounds, path_templates=TEMPLATES
    )
    assert "citation" in _kinds(violations)
    assert bounds.calls == ["ghost"]


async def test_path_outside_new_templates_is_violation():
    src = _topic("atlas", "## 计划\n\n- 事实。[cite: src-01 ¶0] <!-- c:aa11 -->")
    draft = PatchDraft.from_canonical([src], TEMPLATES)
    # A path allowed by the draft (seeded with a wider template set) but NOT in the
    # narrower set we validate against → path ownership is against the NEW skill's templates.
    draft.create_document(
        "memory/products/atlas.md", {"type": "product", "slug": "atlas"}, "## 产品\n"
    )
    draft.move_claim("memory/topics/atlas.md", "aa11", "memory/products/atlas.md", "产品")

    narrow = [t for t in TEMPLATES if "products" not in t]
    bounds = _CountingBounds({"src-01": 5})
    violations, _ = await run_evolve_gate(
        draft, source_bounds=bounds, path_templates=narrow
    )
    assert "path" in _kinds(violations)
