"""Business-neutral text matching and canonical-quality primitives.

These functions are shared by the generic trajectory evaluator and deployment-owned
example evaluators. Corpus data, story identifiers and provider bindings do not live
here.
"""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

TRUTH_THRESHOLD = 0.72
NEGATIVE_THRESHOLD = 0.78
TRUTH_CATEGORIES = (
    "durable_facts",
    "decisions",
    "commitments",
    "constraints",
)

# Language-level uncertainty markers, not corpus facts. Deployments with another
# language can supply their own guard classifier at the metric boundary.
_DEFAULT_GUARD_MARKERS = (
    "旧设想",
    "旧决定",
    "已失效",
    "已废弃",
    "已否定",
    "不做清单",
    "明确不做",
    "未确认",
    "未经确认",
    "错误说法",
    "错误判断",
    "仅是猜测",
    "只是猜测",
    "草稿",
    "驳回",
    "并非事实",
    "不应采信",
    "被替代",
    "已被替代",
    "待确认",
    "待核验",
    "未核验",
    "不能视为",
    "不能据此",
    "不代表",
    "不能证明",
    "存在未决冲突",
    "不能静默合并",
    "不能静默更新",
    "不证明",
    "尚未有",
    "暂不能",
    "不能替代",
    "不能把",
)


def normalize_text(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return "".join(character for character in folded if character.isalnum())


def char_similarity(left: str, right: str) -> float:
    """Punctuation-insensitive containment/sequence similarity."""
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 6 and shorter in longer:
        return 1.0
    return SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def guarded_statement(
    text: str,
    *,
    markers: tuple[str, ...] = _DEFAULT_GUARD_MARKERS,
) -> bool:
    """Whether prose explicitly frames a statement as rejected or uncertain."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return any(marker.lower() in normalized for marker in markers)


def truth_entries(
    manifest: dict[str, Any],
    *,
    current_only: bool = False,
    categories: tuple[str, ...] = TRUTH_CATEGORIES,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    truth = manifest["truth"]
    for category in categories:
        for raw in truth.get(category, []):
            if current_only and raw.get("status") in {"superseded", "cancelled"}:
                continue
            rows.append({**raw, "category": category})
    return rows


def canonical_quality(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Mechanical structure/provenance debt indicators over projected claims."""
    by_normalized: dict[str, list[dict[str, str]]] = {}
    claims_per_document: Counter[str] = Counter()
    claims_without_citations = 0
    citation_marker_residue = 0
    marked_section_components = 0
    representative: dict[str, str] = {}

    for claim in claims:
        path = str(claim["document_path"])
        anchor = str(claim["anchor"])
        text = str(claim["text"])
        claims_per_document[path] += 1
        claims_without_citations += int(not claim.get("citations"))
        citation_marker_residue += int("[cite:" in text.lower())
        marked_section_components += sum(
            str(component).lstrip().startswith("#")
            for component in (claim.get("section_path") or [])
        )
        normalized = normalize_text(text)
        if normalized:
            representative.setdefault(normalized, text)
            by_normalized.setdefault(normalized, []).append(
                {"document_path": path, "anchor": anchor}
            )

    duplicate_groups = [
        {
            "text": representative[normalized],
            "count": len(locations),
            "locations": locations,
        }
        for normalized, locations in sorted(by_normalized.items())
        if len(locations) > 1
    ]
    duplicate_rows_excess = sum(row["count"] - 1 for row in duplicate_groups)
    total = len(claims)
    return {
        "claims_total": total,
        "claims_without_citations": claims_without_citations,
        "citation_marker_residue": citation_marker_residue,
        "section_components_with_heading_marker": marked_section_components,
        "exact_duplicate_groups": len(duplicate_groups),
        "duplicate_rows_excess": duplicate_rows_excess,
        "duplicate_row_rate": (
            round(duplicate_rows_excess / total, 6) if total else None
        ),
        "claims_per_document": dict(sorted(claims_per_document.items())),
        "duplicate_samples": duplicate_groups[:30],
    }


__all__ = [
    "NEGATIVE_THRESHOLD",
    "TRUTH_CATEGORIES",
    "TRUTH_THRESHOLD",
    "canonical_quality",
    "char_similarity",
    "cosine",
    "guarded_statement",
    "normalize_text",
    "truth_entries",
]
