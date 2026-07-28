# OPC 84-day evaluation v1

Status: accepted

## Purpose

The experiment report must distinguish “the pipeline completed” from “the resulting
knowledge is useful.” Evaluation runs after the final chronological batch against the
frozen manifest truth set and the live PostgreSQL/Meilisearch/Qdrant/Git state.

## Measures

1. **Truth recall** — current durable facts, decisions, commitments and constraints
   matched to canonical claims by exact/character and embedding similarity.
2. **Truth-set precision proxy** — canonical claims whose best match is one of the
   labelled business truths. It is explicitly a proxy: useful facts outside the finite
   manifest may appear as false negatives.
3. **Noise leakage** — negative-control statements found in canonical. A mention
   explicitly marked old, rejected, unconfirmed, incorrect or out of scope is recorded
   separately and is not counted as an unguarded leak.
4. **Supersession accuracy** — the replacement statement is present and the old
   statement is either absent or explicitly historical/rejected.
5. **Citation integrity** — claims carry citations; every locator resolves to the
   owning user's source and an in-range block interval; cited text is semantically
   supportive.
6. **Retrieval coverage** — every manifest question runs through dual lexical/vector
   claim retrieval. Expected truth statements are matched against the bounded result.
   Historical `as_of` cases are reported separately because the current retrieval index
   is HEAD-only.
7. **Projection consistency** — canonical projection count equals PostgreSQL rows,
   Meilisearch documents and Qdrant claim points.

## Similarity and honesty

- Exact normalized containment scores 1.0.
- Otherwise the evaluator records both character similarity and cosine similarity and
  uses their maximum.
- Thresholds are serialized in the report; misses and unmatched claims include samples.
- No LLM judge rewrites or silently repairs the results.
- The report records evaluator limitations, especially the finite truth-set precision
  proxy and HEAD-only historical retrieval.
