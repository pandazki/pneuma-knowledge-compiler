# Diagnosing recall quality

**English** | [简体中文](recall-quality.zh-CN.md)

Recall quality is a pipeline property. A fluent wrong answer and a missing fact can look the
same at the chat surface while requiring opposite fixes. Diagnose the first layer that lost
the information; do not widen every budget or add another model call by default.

## Read the evidence ledger first

For one representative question, inspect the response in this order:

1. **L0 source** — does the normalized source contain the exact material, correct occurrence
   time and a resolvable `source_id + block span`?
2. **L2 representations** — do lexical/raw hits or a labelled derived episode summary find
   the event? A summary helps broad semantic reach; it is not verbatim evidence.
3. **L3 canonical** — did the compile contract promote the durable fact under the right
   subject? Missing L3 is not automatically a failure when L0/L2 still answer correctly.
4. **Candidate retrieval** — is the needed claim/window in the broad candidate pool?
5. **Final composition** — did the bounded answer context retain the needed combination?
6. **Answer projection** — did the model answer the exact question without adding scope, and
   did the consumer use citation-free `answer_text` rather than the cited display string?

The first failing layer owns the repair. Recompiling cannot restore a source that was never
normalized. A larger final prompt cannot retrieve a missing candidate. More candidates do not
fix an answer model that already received exact evidence.

## Use each control for one job

- Widen `claim_candidate_cap` or `window_candidate_cap` when the relevant evidence is absent
  from candidates. Candidate breadth is index work, not final prompt size.
- Adjust `claim_cap`, `episode_summary_cap` and `window_cap` when candidates are correct but
  the final context loses needed coverage or becomes noisy. Episodes carry dense meaning;
  verbatim windows carry exact wording.
- Fix semantic chunking when no coherent episode representation exists. Fix the compile
  contract when durable facts repeatedly land under the wrong subjects.
- Keep `evidence_strategy: ranked` as the direct baseline. Use `select` only for demonstrated
  cross-face composition misses. Compare its model-selected counts with candidates and final
  evidence: near-zero model choices plus a large final ledger means safety anchors, not the
  serial selector, are doing the work.
- Use `answer_format: structured` when downstream systems need a clean semantic answer and a
  separately validated citation ledger. Consume `answer_text` for automation and `answer` for
  interactive cited rendering.
- Request original modalities only when the question requires direct inspection. Caption/OCR
  and native media are distinct evidence choices, not implicit consequences of model ability.

## Keep time semantics honest

`as_of` is the question time. Source occurrence time is separate metadata. Live questions may
omit `as_of` and use the current UTC instant; historical replay must pass the original,
timezone-aware timestamp. Otherwise a correct relative-time calculation can become wrong even
when retrieval and source dates are perfect.

```bash
./app.py ask "How long ago did this happen?" \
  --as-of 2025-06-20T21:00:00Z \
  --style concise
```

## Measure changes without mixing axes

Freeze a small set of real, permissioned acceptance questions that cover exact facts,
multi-evidence joins, time, and any supported modality. For each change, keep the data and
question set fixed and record separately:

- answer acceptance and citation validity;
- candidate, model-selected and final evidence counts;
- per-stage latency, including serial selector or planning calls;
- per-stage token and monetary cost;
- degradation and fallback rates.

A quality gain does not erase a latency regression, and a cheaper result does not establish
better answers. Promote a control only when its own axis and trade-off are visible.
