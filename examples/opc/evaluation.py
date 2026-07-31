"""Evidence-based evaluation for the deterministic 84-day OPC experiment.

No LLM judge is used. The evaluator combines normalized character matching with the
configured embedding model, replays every citation locator, exercises the live dual
claim indexes, and compares all four derived/canonical counts.

NOTE ON LANGUAGE. `_GUARD_MARKERS` below is the scoring vocabulary for the Chinese
synthetic corpus in ``examples/opc/data/84-day`` — it matches compiled canonical
text produced from that corpus, so it is data paired with this example rather than
framework prose.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.recall.fast import retrieve_claims
from pneuma_knowledge_core.recall.projection import project_snapshot_claims
from pneuma_knowledge_eval.matching import (
    NEGATIVE_THRESHOLD,
    TRUTH_CATEGORIES as _TRUTH_CATEGORIES,
    TRUTH_THRESHOLD,
    canonical_quality,
    char_similarity,
    cosine as _cosine,
    guarded_statement,
    truth_entries,
)

CITATION_SUPPORT_THRESHOLD = 0.55
RETRIEVAL_THRESHOLD = 0.68

def _best_match(
    target: str,
    candidates: Iterable[str],
    vectors: dict[str, list[float]],
) -> dict[str, Any]:
    best = {
        "score": 0.0,
        "char_score": 0.0,
        "embedding_score": 0.0,
        "text": None,
    }
    for candidate in candidates:
        char_score = char_similarity(target, candidate)
        embedding_score = _cosine(vectors.get(target), vectors.get(candidate))
        score = max(char_score, embedding_score)
        if score > best["score"]:
            best = {
                "score": round(score, 6),
                "char_score": round(char_score, 6),
                "embedding_score": round(embedding_score, 6),
                "text": candidate,
            }
    return best


async def _embed_texts(
    embeddings: Any, texts: Iterable[str], *, batch_size: int = 64
) -> dict[str, list[float]]:
    unique = list(dict.fromkeys(text for text in texts if text.strip()))
    out: dict[str, list[float]] = {}
    for start in range(0, len(unique), batch_size):
        batch = unique[start : start + batch_size]
        vectors = await embeddings.aembed_documents(batch)
        out.update(zip(batch, vectors))
    return out


def _by_category(matches: list[dict[str, Any]]) -> dict[str, Any]:
    totals = Counter(row["category"] for row in matches)
    passed = Counter(
        row["category"] for row in matches if row["matched"]
    )
    return {
        category: {
            "matched": passed[category],
            "total": totals[category],
            "recall": round(passed[category] / totals[category], 6)
            if totals[category]
            else None,
        }
        for category in _TRUTH_CATEGORIES
    }


async def evaluate_opc_84d(
    ctx: Any,
    user_id: UserId,
    manifest: dict[str, Any],
    *,
    retrieval_limit: int = 15,
) -> dict[str, Any]:
    """Evaluate the live experiment state and return a JSON-serializable report."""
    docs = await ctx.canonical.list(user_id)
    claims = await ctx.store.list_canonical_claims(user_id)
    claim_texts = [str(row["text"]) for row in claims]
    projected = project_snapshot_claims(docs)

    meili_count = await ctx.lexical.count_claims(user_id)
    qdrant_count = await ctx.vectors.count_claims(user_id)

    # Citation locator replay is mechanical and user-scoped.
    source_cache: dict[str, Any] = {}
    citation_records: list[dict[str, Any]] = []
    support_text_by_claim: dict[tuple[str, str], str] = {}
    for claim in claims:
        key = (str(claim["document_path"]), str(claim["anchor"]))
        support_parts: list[str] = []
        for citation in claim.get("citations") or []:
            source_id = str(citation.get("source_id") or "")
            start = int(citation.get("block_start", -1))
            end = int(citation.get("block_end", -1))
            valid = False
            error = None
            try:
                if source_id not in source_cache:
                    source_cache[source_id] = await ctx.store.get(
                        user_id, SourceId(source_id)
                    )
                source = source_cache[source_id]
                if start < 0 or end < start or end >= len(source.blocks):
                    error = "out_of_range"
                else:
                    support_parts.extend(
                        source.blocks[index].text for index in range(start, end + 1)
                    )
                    valid = True
            except (KeyError, ValueError) as exc:
                error = type(exc).__name__
            citation_records.append(
                {
                    "document_path": key[0],
                    "anchor": key[1],
                    "source_id": source_id,
                    "block_start": start,
                    "block_end": end,
                    "valid": valid,
                    "error": error,
                }
            )
        if support_parts:
            support_text_by_claim[key] = "\n".join(support_parts)

    # Exercise the real dual lexical/vector claim indexes. Retrieval itself embeds each
    # query; semantic truth scoring below batches expected/candidate text separately.
    retrieval_runs: list[dict[str, Any]] = []
    retrieval_candidate_texts: list[str] = []
    for case in manifest["truth"].get("retrieval_cases", []):
        hits = await retrieve_claims(
            user_id,
            case["question"],
            claim_lexical=ctx.lexical,
            claim_vectors=ctx.vectors,
            embeddings=ctx.embeddings,
            limit=retrieval_limit,
        )
        hit_rows = [
            {
                "document_path": hit.document_path,
                "anchor": str(hit.anchor),
                "text": hit.text,
                "paths": list(hit.paths),
                "score": round(float(hit.score), 8),
            }
            for hit in hits
        ]
        retrieval_candidate_texts.extend(row["text"] for row in hit_rows)
        retrieval_runs.append({"case": case, "hits": hit_rows})

    all_truth = truth_entries(manifest)
    current_truth = truth_entries(manifest, current_only=True)
    truth_by_id = {row["truth_id"]: row for row in all_truth}
    negatives = list(manifest["truth"].get("negative_controls", []))

    embedding_texts: list[str] = [
        *claim_texts,
        *(row["value"] for row in all_truth),
        *(row["value"] for row in negatives),
        *support_text_by_claim.values(),
        *retrieval_candidate_texts,
    ]
    vectors = await _embed_texts(ctx.embeddings, embedding_texts)

    truth_matches: list[dict[str, Any]] = []
    for truth in current_truth:
        best = _best_match(truth["value"], claim_texts, vectors)
        truth_matches.append(
            {
                "truth_id": truth["truth_id"],
                "category": truth["category"],
                "value": truth["value"],
                "matched": best["score"] >= TRUTH_THRESHOLD,
                "best": best,
            }
        )
    matched_truth = sum(row["matched"] for row in truth_matches)

    precision_rows: list[dict[str, Any]] = []
    truth_values = [row["value"] for row in all_truth]
    for claim in claims:
        best = _best_match(str(claim["text"]), truth_values, vectors)
        precision_rows.append(
            {
                "document_path": claim["document_path"],
                "anchor": claim["anchor"],
                "text": claim["text"],
                "matched": best["score"] >= TRUTH_THRESHOLD,
                "best": best,
            }
        )
    matched_claims = sum(row["matched"] for row in precision_rows)

    negative_rows: list[dict[str, Any]] = []
    for negative in negatives:
        best = _best_match(negative["value"], claim_texts, vectors)
        found = best["score"] >= NEGATIVE_THRESHOLD
        guarded = found and guarded_statement(str(best["text"] or ""))
        negative_rows.append(
            {
                "truth_id": negative["truth_id"],
                "value": negative["value"],
                "found": found,
                "guarded": guarded,
                "unguarded_leak": found and not guarded,
                "best": best,
            }
        )

    supersession_rows: list[dict[str, Any]] = []
    for supersession in manifest["truth"].get("supersessions", []):
        before = truth_by_id[supersession["before_truth_id"]]
        after = truth_by_id[supersession["after_truth_id"]]
        before_best = _best_match(before["value"], claim_texts, vectors)
        after_best = _best_match(after["value"], claim_texts, vectors)
        before_found = before_best["score"] >= TRUTH_THRESHOLD
        before_guarded = before_found and guarded_statement(
            str(before_best["text"] or "")
        )
        after_found = after_best["score"] >= TRUTH_THRESHOLD
        supersession_rows.append(
            {
                "supersession_id": supersession["supersession_id"],
                "before_truth_id": before["truth_id"],
                "after_truth_id": after["truth_id"],
                "before_found": before_found,
                "before_guarded": before_guarded,
                "after_found": after_found,
                "correct": after_found and (not before_found or before_guarded),
                "before_best": before_best,
                "after_best": after_best,
            }
        )

    citation_support_rows: list[dict[str, Any]] = []
    claim_by_key = {
        (str(row["document_path"]), str(row["anchor"])): row for row in claims
    }
    for key, support in support_text_by_claim.items():
        claim_text = str(claim_by_key[key]["text"])
        char_score = char_similarity(claim_text, support)
        embedding_score = _cosine(vectors.get(claim_text), vectors.get(support))
        score = max(char_score, embedding_score)
        citation_support_rows.append(
            {
                "document_path": key[0],
                "anchor": key[1],
                "score": round(score, 6),
                "char_score": round(char_score, 6),
                "embedding_score": round(embedding_score, 6),
                "supported": score >= CITATION_SUPPORT_THRESHOLD,
            }
        )

    retrieval_results: list[dict[str, Any]] = []
    path_counts = Counter()
    expected_total = 0
    expected_matched = 0
    for run in retrieval_runs:
        case = run["case"]
        candidates = [row["text"] for row in run["hits"]]
        for hit in run["hits"]:
            path_counts.update(hit["paths"])
        expected: list[dict[str, Any]] = []
        for truth_id in case["expected_truth_ids"]:
            expected_total += 1
            truth = truth_by_id[truth_id]
            best = _best_match(truth["value"], candidates, vectors)
            matched = best["score"] >= RETRIEVAL_THRESHOLD
            expected_matched += int(matched)
            expected.append(
                {
                    "truth_id": truth_id,
                    "matched": matched,
                    "best": best,
                }
            )
        retrieval_results.append(
            {
                "case_id": case["case_id"],
                "question": case["question"],
                "as_of": case.get("as_of"),
                "historical": case.get("as_of") is not None,
                "success": all(row["matched"] for row in expected),
                "expected": expected,
                "hit_count": len(run["hits"]),
                "hits": run["hits"],
            }
        )

    citation_total = len(citation_records)
    citation_valid = sum(row["valid"] for row in citation_records)
    support_total = len(citation_support_rows)
    support_valid = sum(row["supported"] for row in citation_support_rows)
    supersession_correct = sum(row["correct"] for row in supersession_rows)
    unguarded_leaks = sum(row["unguarded_leak"] for row in negative_rows)
    historical_cases = [row for row in retrieval_results if row["historical"]]
    current_cases = [row for row in retrieval_results if not row["historical"]]

    return {
        "schema": "pneuma.experiment.evaluation/v1",
        "experiment_id": manifest["experiment_id"],
        "user_id": str(user_id),
        "thresholds": {
            "truth": TRUTH_THRESHOLD,
            "negative": NEGATIVE_THRESHOLD,
            "citation_support": CITATION_SUPPORT_THRESHOLD,
            "retrieval": RETRIEVAL_THRESHOLD,
        },
        "counts": {
            "canonical_documents": len(docs),
            "canonical_projected_claims": len(projected),
            "postgres_claims": len(claims),
            "meilisearch_claims": meili_count,
            "qdrant_claims": qdrant_count,
        },
        "projection_consistency": {
            "consistent": len(projected) == len(claims) == meili_count == qdrant_count,
            "canonical_equals_postgres": len(projected) == len(claims),
            "postgres_equals_meilisearch": len(claims) == meili_count,
            "postgres_equals_qdrant": len(claims) == qdrant_count,
        },
        "canonical_quality": canonical_quality(claims),
        "truth_recall": {
            "matched": matched_truth,
            "total": len(truth_matches),
            "recall": round(matched_truth / len(truth_matches), 6)
            if truth_matches
            else None,
            "by_category": _by_category(truth_matches),
            "misses": [row for row in truth_matches if not row["matched"]],
            "matches": truth_matches,
        },
        "truth_set_precision_proxy": {
            "matched": matched_claims,
            "total": len(precision_rows),
            "precision": round(matched_claims / len(precision_rows), 6)
            if precision_rows
            else None,
            "unmatched_samples": [
                row for row in precision_rows if not row["matched"]
            ][:30],
        },
        "negative_controls": {
            "unguarded_leaks": unguarded_leaks,
            "total": len(negative_rows),
            "leak_rate": round(unguarded_leaks / len(negative_rows), 6)
            if negative_rows
            else None,
            "guarded_mentions": sum(row["guarded"] for row in negative_rows),
            "details": negative_rows,
        },
        "supersessions": {
            "correct": supersession_correct,
            "total": len(supersession_rows),
            "accuracy": round(
                supersession_correct / len(supersession_rows), 6
            )
            if supersession_rows
            else None,
            "details": supersession_rows,
        },
        "citations": {
            "claims_with_citations": sum(
                bool(row.get("citations")) for row in claims
            ),
            "claims_total": len(claims),
            "claim_coverage": round(
                sum(bool(row.get("citations")) for row in claims) / len(claims), 6
            )
            if claims
            else None,
            "locators_valid": citation_valid,
            "locators_total": citation_total,
            "locator_replay_rate": round(citation_valid / citation_total, 6)
            if citation_total
            else None,
            "semantic_support_valid": support_valid,
            "semantic_support_total": support_total,
            "semantic_support_rate": round(support_valid / support_total, 6)
            if support_total
            else None,
            "invalid_locators": [
                row for row in citation_records if not row["valid"]
            ],
            "weak_support_samples": [
                row for row in citation_support_rows if not row["supported"]
            ][:30],
        },
        "retrieval": {
            "cases_successful": sum(row["success"] for row in retrieval_results),
            "cases_total": len(retrieval_results),
            "case_success_rate": round(
                sum(row["success"] for row in retrieval_results)
                / len(retrieval_results),
                6,
            )
            if retrieval_results
            else None,
            "expected_truths_matched": expected_matched,
            "expected_truths_total": expected_total,
            "expected_truth_recall": round(
                expected_matched / expected_total, 6
            )
            if expected_total
            else None,
            "current_cases_successful": sum(row["success"] for row in current_cases),
            "current_cases_total": len(current_cases),
            "historical_cases_successful": sum(
                row["success"] for row in historical_cases
            ),
            "historical_cases_total": len(historical_cases),
            "path_hits": dict(sorted(path_counts.items())),
            "cases": retrieval_results,
        },
        "limitations": [
            "Truth-set precision is a finite-manifest proxy; useful unlabeled facts can score as unmatched.",
            "Historical as_of retrieval is evaluated against the current HEAD claim indexes because the live retrieval API has no snapshot selector.",
            "Semantic thresholds are serialized and misses retain best-match evidence; no LLM judge silently changes labels.",
        ],
    }
