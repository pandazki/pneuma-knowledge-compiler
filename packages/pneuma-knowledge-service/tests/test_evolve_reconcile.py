"""adopt catch-up merge (schema-evolve §2.5, C4): the mechanical three-way anchor
reconciliation, driven directly off fabricated base/branch/main doc sets — no git, no docker.

Four review-window cases, one each, plus the terminal-assertion guard: the revive rule is
load-bearing (a window-changed dropped anchor MUST survive), so its removal must turn the
terminal check red (scenario 2 asserts exactly that)."""

from __future__ import annotations

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, extract_anchors
from pneuma_knowledge_service.evolve_service import reconcile_adopt


def _doc(path: str, pneuma: str, body: str) -> CanonicalDocument:
    return CanonicalDocument(
        pneuma_id=DocumentId(pneuma),
        path=path,
        frontmatter={"pneuma_id": pneuma, "type": "topic", "slug": pneuma},
        body=body,
    )


def _claim(text: str, anchor: str, cite: str = "src-01 ¶0") -> str:
    return f"## 记录\n\n- {text}[cite: {cite}] <!-- c:{anchor} -->"


def _final_anchors(final_files: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for body in final_files.values():
        out.update(extract_anchors(body))
    return out


def test_window_edited_moved_anchor_takes_main_text():
    # aa11 lived in topics/atlas (base); evolve moved it to products/atlas; a daily compile
    # edited it in the window → main text wins, at the branch's new location.
    base = [_doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas Q3 发布。", "aa11"))]
    branch = [
        _doc("memory/topics/atlas.md", "d-atlas", "## 记录\n"),
        _doc("memory/products/atlas.md", "d-product", _claim("Atlas Q3 发布。", "aa11")),
    ]
    main = [_doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas Q3 发布并开放源码。", "aa11"))]

    final_files, ok, reason = reconcile_adopt(base, branch, main)
    assert ok, reason
    product = final_files["memory/products/atlas.md"]
    assert "Atlas Q3 发布并开放源码。" in product  # 近者胜: main text
    assert "c:aa11" in product
    assert "c:aa11" not in final_files["memory/topics/atlas.md"]


def test_window_edited_dropped_anchor_is_revived():
    # bb22 lived in topics/globex (base); evolve MERGED it away (dropped). But a daily compile
    # edited it in the window → safety-first revive to its main path. (Terminal-assertion
    # guard: remove the revive rule and this goes red — bb22 required, not window-untouched.)
    base = [_doc("memory/topics/globex.md", "d-gx", _claim("Globex 试点。", "bb22"))]
    branch = [_doc("memory/topics/globex.md", "d-gx", "## 记录\n")]  # merged away
    main = [_doc("memory/topics/globex.md", "d-gx", _claim("Globex 试点已扩容。", "bb22"))]

    final_files, ok, reason = reconcile_adopt(base, branch, main)
    assert ok, reason
    assert "bb22" in _final_anchors(final_files)
    assert "已扩容" in final_files["memory/topics/globex.md"]


def test_window_new_anchor_new_doc_is_carried_over():
    # ce11 is brand-new in the window, in a topics/new-idea.md that never existed on the branch
    # → the whole main doc is carried over.
    base = [_doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas。", "aa11"))]
    branch = [_doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas。", "aa11"))]
    main = [
        _doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas。", "aa11")),
        _doc("memory/topics/new-idea.md", "d-new", _claim("新想法首次记录。", "ce11")),
    ]

    final_files, ok, reason = reconcile_adopt(base, branch, main)
    assert ok, reason
    assert "memory/topics/new-idea.md" in final_files
    assert "ce11" in _final_anchors(final_files)
    assert "新想法首次记录。" in final_files["memory/topics/new-idea.md"]


def test_clean_fast_path_equals_branch():
    # No window change (main == base modulo the reorg): final is the branch tree, drop stays
    # dropped, terminal check passes.
    base = [
        _doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas。", "aa11")),
        _doc("memory/topics/dup.md", "d-dup", _claim("冗余重复。", "dd11")),
    ]
    branch = [
        _doc("memory/topics/atlas.md", "d-atlas", "## 记录\n"),
        _doc("memory/products/atlas.md", "d-product", _claim("Atlas。", "aa11")),
        _doc("memory/topics/dup.md", "d-dup", "## 记录\n"),  # dd11 merged away, untouched
    ]
    # main == base exactly (no daily compile in the window).
    main = [
        _doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas。", "aa11")),
        _doc("memory/topics/dup.md", "d-dup", _claim("冗余重复。", "dd11")),
    ]

    final_files, ok, reason = reconcile_adopt(base, branch, main)
    assert ok, reason
    # aa11 relocated, dd11 stays dropped (window-untouched → allowed to vanish).
    assert "aa11" in _final_anchors(final_files)
    assert "dd11" not in _final_anchors(final_files)
    assert "c:aa11" in final_files["memory/products/atlas.md"]


def test_window_new_doc_with_multiple_anchors_carries_each_anchor_exactly_once():
    """A doc born entirely inside the review window (passive trigger mid-wave: the evolve
    branch never saw it) must be carried whole ONCE — not whole-carried AND then have its
    2nd+ anchors appended again. The live failure mode: duplicated anchors in the adopted
    tree hard-fail every later compile's uniqueness gate (the KB bricks itself)."""
    base = [_doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas Q3 发布。", "aa11"))]
    branch = [_doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas Q3 发布。", "aa11"))]
    main = [
        _doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas Q3 发布。", "aa11")),
        _doc(
            "memory/topics/new-idea.md",
            "d-new",
            _claim("新想法验证为红。", "cc33") + "\n" + _claim("新想法测量为绿。", "dd44"),
        ),
    ]

    final_files, ok, reason = reconcile_adopt(base, branch, main)
    assert ok, reason
    new_idea = final_files["memory/topics/new-idea.md"]
    assert new_idea.count("c:cc33") == 1
    assert new_idea.count("c:dd44") == 1


def test_duplicate_anchor_in_final_tree_fails_the_terminal_check():
    """Uniqueness backstop: adopt commits without a gate run, so the terminal check itself
    must refuse a merge whose final tree carries the same anchor twice."""
    base = [_doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas Q3 发布。", "aa11"))]
    # Degenerate branch state: the same anchor exists in two branch docs (should be
    # impossible via move_claim, but the backstop is exactly for the impossible).
    branch = [
        _doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas Q3 发布。", "aa11")),
        _doc("memory/products/atlas.md", "d-product", _claim("Atlas Q3 发布。", "aa11")),
    ]
    main = [_doc("memory/topics/atlas.md", "d-atlas", _claim("Atlas Q3 发布。", "aa11"))]

    final_files, ok, reason = reconcile_adopt(base, branch, main)
    assert not ok
    assert "重复" in reason
    assert final_files == {}
