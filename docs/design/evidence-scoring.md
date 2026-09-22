# Evidence scoring: uncertainty and source clocks

**English** | [简体中文](evidence-scoring.zh-CN.md)

The scored selector judges which retrieved material is useful to read. Its score is not
truth probability, permission to speak an early fact, or permission to write canonical.
The existing four-level rubric, 0.5 normalized keep floor, named candidate keys, shard
budgets and ranked safety anchors remain the selection policy.

## Decisions

1. **Interpret source-time intent separately from relevance.** The optional
   `SourceClockPolicy` sends only the question to one TypeSafe request containing a Noul
   and a Choice. Noul probability 0.8 enables source-clock reasoning; Choice confidence
   0.7 admits a supported calendar period. Core computes UTC boundaries from `as_of`, the
   owner's timezone and timezone history. The model selects a period name; it does not
   calculate dates. Supported periods cover today/yesterday, fixed recent day counts,
   calendar weeks/months/years, and literal fully specified ISO or Chinese dates. Event
   dates are not source-date filters. Vague recency, sub-day windows, exclusions and
   disjoint comparisons remain unresolved; no arbitrary interval is invented.

   The request has a two-second ceiling and overlaps retrieval. Voice's early and broad
   phases share one task, which the librarian cancels and joins on termination. A negative
   intent preserves the original candidate strings. No configured policy preserves the
   existing lane. An unavailable configured policy is distinct from a negative intent:
   the lane withholds facts and reports validation unavailable, even for a question whose
   temporal intent could not be classified. This conservative failure mode reduces
   availability; it is not a request for the user to supply dates again.

   For admitted temporal questions, compact local-day relations stay beside each cited
   source clock, explicitly distinguished from event time. Source-wide dates, partial
   block clocks and unknown clocks remain distinct. Ingestion time fills none of them.
2. **Retain uncertainty without imposing another filter.** `EvidenceScores.details`
   retains each candidate's optional ordered probability distribution, confidence and
   reported model version. The requested model and a hash of the instructions/rubric are
   separate fields. A missing reported version stays missing. Confidence is distribution
   concentration, not correctness; equal expected scores can have different distributions.
   Selection still uses the original score floor. `SelectedEvidence.score_report` retains
   the report for its caller, and the existing bounded stage preview exposes aggregates
   and at most eight numeric candidate samples. Preview truncation still applies: this
   is diagnostic telemetry, not a complete persisted transcript of all provider answers.
3. **Reject invalid scores.** Nonfinite, boolean and out-of-range scores are unscored,
   rather than clamped to apparently valid evidence. Invalid optional diagnostics are
   omitted without discarding a valid score. Missing distributions remain empty.
4. **Share the concurrency budget.** The cached adapter's semaphore bounds concurrent
   scoring passes together, rather than giving each recall sixteen independent slots.
   This is per adapter/process, not a distributed account-wide rate limiter. Cancellation
   releases its slots. Connection reuse and per-call timeouts remain.
5. **Respect provider cooldowns within the recall budget.** Retries honor `Retry-After`
   seconds or HTTP dates, with 250ms exponential backoff as the minimum. A hint at least
   as long as the configured request timeout ends that shard unscored; it does not sleep
   indefinitely or retry early. The default remains one retry. Voice's outer five-second
   selection timeout can cancel earlier than the adapter's six-second request timeout.

6. **Enforce an admitted source period outside the score.** Before selection and again
   after assembly/provenance expansion, core retains only claims and derived summaries
   whose complete cited block clocks fall within the interval. Mixed verbatim windows
   are reread from tenant-isolated L0 and split into exact in-period block runs. Unknown
   clocks and source-wide dates alone cannot prove that every cited block is in range.
   Bounded origins prevent later expansion across the interval; original media receives
   the same window check. Ranked anchors and scorer-failure fallback cannot restore
   excluded records. Whole-page, glance and timeline expansion are withheld on this path.
   The early voice lookup uses the same scope before its existing first-fact gate. With
   no admitted evidence, both voice refinement and ordinary fast answering return a
   mechanical result without an answer-model call. Scope/policy and final counts are
   visible in the bounded stage previews, including when selection has no candidates.

The caller isolates each tenant's candidates; time checks reread L0 through that same
boundary. No canonical data, source records or kept records are rewritten. A below-floor
item can still enter through a ranked anchor if it passes time admission. Relevance,
source-time admission, citation validity and semantic faithfulness remain separate:
mechanical interval enforcement cannot establish that the model understood the question
correctly or that an event occurred when its source was written.

## Validation before implementation

New tests reproduced four existing problems: invalid numeric answers, dropped uncertainty,
concurrency exceeding the configured budget across recalls, and premature retries despite
`Retry-After`. The existing scorer/selector checks passed (27 tests). Five additional tests
specified the new clock behavior before its implementation: local-day conversion, partial
coverage, future/source-wide dates, unknown dates and unusable zones. Further regression
tests cover optional fields, shard alignment, cancellation, low-confidence retention and
stage telemetry. These keyless checks validate mechanics, not semantic model quality.

## Initial paired experiment, 2026-09-21

This first experiment used the earlier unconditional JSON clock bundle. It is historical
evidence for computing dates, not the final input policy; the follow-up below supersedes
the global rollout decision.

Synthetic Chinese/English material only; no private library data or LLM-generated labels.
The pinned model was `typesafe/jev-1.13-20260917` through OpenRouter. Requests used the same
four-level rubric, 0.5 normalized floor and candidate groups. The only experimental input
change was the computed source-clock metadata. Expected labels were never sent to JEV.

| Cohort | Before | After |
|---|---:|---:|
| Initial: true positives / false negatives | 24 / 0 | 24 / 0 |
| Initial: false positives / true negatives | 14 / 46 | 0 / 60 |
| Initial: input tokens | 26,319 | 36,360 |
| Initial: call median | 323ms | 344.5ms |
| Holdout: true positives / false negatives | 8 / 4 | 12 / 0 |
| Holdout: false positives / true negatives | 8 / 16 | 0 / 24 |
| Holdout: input tokens | 11,658 | 15,996 |
| Holdout: call median | 331ms | 348ms |

The initial cohort has eight questions and 28 unique candidate judgments, repeated three
times (24 calls per variant). It includes today/yesterday questions, older relevant
definitions, and event dates that differ from source dates. The holdout has twelve new
questions and 36 candidate judgments, run once per variant with alternating call order;
it covers month/year boundaries and New York's daylight-saving transition. Overall this
is 20 questions, 64 unique judgments and 72 calls, not 120 independent test cases.

This measures score-floor eligibility **before** ranked anchors and answer generation.
It supports the clock-input change on these examples, not a claim of general retrieval
accuracy, injection resistance or voice-answer correctness. Input tokens increased by
about 37–38%; measured medians also rose slightly. This is not a latency optimization.
Keep batch-size, rubric and confidence-threshold changes behind separate comparisons.

## Follow-up: realistic pools and conditional context (before interval admission)

A fixed, seed-selected 24-question replay used 4,105 frozen candidates: five actual Owner
questions, ten questions generated from real claims, five generated broad questions and
four invented-subject negatives. Candidate text/order remained frozen; source clocks were
hydrated read-only from L0 and then frozen. The new reference instant was explicitly
2026-09-21 01:00 UTC, Asia/Shanghai. This is a replay of historical pools, not a claim that
the current live retrieval or the original question's historical clock was reproduced.
Private material remains under ignored `local/`; only aggregate results belong here.

Against existing model-judge labels on the nineteen non-Owner-question controls, the raw
floor precision/recall were 72.0%/82.1% for the original input, 69.1%/79.7% with the verbose
clock bundle, and 69.8%/81.6% with compact clocks applied globally. After anchors and caps,
precision was 56.2%, 54.0%, 53.5%, respectively. These are partial, model-generated labels,
not human ground truth. The nine target claims present in the pool survived all versions;
the tenth target was absent from the pool. Neither global variant demonstrated a general
quality gain, so computed clocks are no longer added to every question.

The earlier Noul-only policy matched 44 exploration cases and 24 separate synthetic holdout
cases, including historical facts, event dates and subjects literally named Yesterday.
At the fixed 0.8 threshold it enabled two of the 24 realistic questions: recent projects
and recent work. The other 22 retain the original candidate strings byte for byte. This
protects input compatibility; it does not guarantee identical stochastic model answers.
The holdout policy median was 340.5ms, and its 24 calls consumed 9,744 input tokens.

The final compact input was also compared directly on all twenty frozen synthetic
questions (64 unique judgments, alternating variants): original input TP/FP/FN/TN was
17/13/3/31, compact input 20/0/0/44. Tokens rose from 20,431 to 23,543 (+15.2%), rather
than the earlier 37–38%. This checks the representation; the separate policy evaluation
checks whether to use it. Those two measurements are not a single end-to-end benchmark.

On the 24 realistic pools, the original, verbose-global and compact-global scoring passes
consumed 2,665,499 / 3,476,945 / 2,972,128 tokens in 161 / 250 / 195 HTTP requests.
Composing the recorded policy decisions with those measured branches gives 2,700,447
tokens including the policy and 187 requests (+1.3% tokens versus the original input).
This last figure is an offline composition, not a newly timed full pipeline run. The
additional policy round has a latency cost; no overall speedup is claimed.

Five actual questions were also replayed through answer generation using frozen selected
evidence, without new retrieval or provenance expansion. The recent-work pool's latest
source instant was September 17, while the question clock was September 21. Both original
and compact variants still described older work as recent. Thus better source-clock input
does not solve missing candidates or answer honesty. Ranked anchors also reintroduced
useful evidence alongside noise, so they were not removed on the strength of this probe.
There is no end-to-end correctness claim from these five answer replays.

## Resumed validation: interval admission, 2026-09-22

With the final Noul+Choice policy and the same pinned JEV model, 19 of the 20 original
interval cases and all 12 separately authored holdout cases matched the expected result.
All 32 requests returned decisions. One original English “today's meeting notes” question
selected `today` correctly but had Choice confidence 0.65, below the unchanged 0.7 admission
threshold, so it returned unresolved. The threshold was not retuned to this result.
Medians were 306.5ms and 391ms; policy input totals were 17,980 and 10,781 tokens.
This checks interpretation and date resolution, not retrieval completeness or answer quality.

A fresh paired replay of the same twenty compact-clock scoring cases (64 unique candidate
judgments, twenty calls per variant) yielded:

| Score-floor outcome | Original input | Compact source clocks |
|---|---:|---:|
| True positives / false negatives | 16 / 4 | 20 / 0 |
| False positives / true negatives | 13 / 31 | 0 / 44 |
| Unscored | 0 | 0 |
| Input tokens | 20,431 | 23,543 |
| Call median | 333ms | 364ms |

The comparison fixes the rubric, floor, candidate order and model, and alternates variants.
It measures the clock representation separately from the intent policy and interval gate.
It is a small synthetic comparison, with no general accuracy or latency improvement claim.
The baseline differs slightly from the earlier run because model decisions are stochastic.
Keyless lane tests separately cover old-record exclusion through ranked fallback, mixed
block splitting, tenant rejection, unavailable validation, shared voice policy cancellation,
and both early/final refusal when no source-time-admitted evidence remains.

## Reproduction

The frozen paired inputs and expected labels are in
`packages/pneuma-knowledge-eval/tests/fixtures/jev-source-clocks.json`.
The compact representation is frozen in `jev-source-clocks-compact.json`; the independent
policy holdout is `jev-source-clock-policy.json` in the same directory.
`pneuma_knowledge_eval.evidence_scoring.compare(scorer, cases, repeats=1)` replays them with
an injected `EvidenceScorer`, alternating before/after order and reporting unscored items
separately. It does not configure a provider or read credentials. Pass the same pinned
adapter to both variants; the model, floor and rubric must remain fixed. The initial
record above used three repeats and sequential variant runs; the holdout used alternating
order. A future replay is a new measurement, not a reproduction of identical wall time.
`evaluate_source_clock_policy(policy, cases)` tests intent separately.
`evaluate_source_time_scope(policy, cases, as_of=..., zone=...)` additionally checks the
resolved calendar window using `source-time-window-cases.json` and the independent
`source-time-window-holdout.json`. Expected dates and labels remain in the eval leaf;
only questions reach the policy. Unavailable decisions are unscored, not correct negatives.

Keyless checks:

```bash
uv run pytest packages/pneuma-knowledge-service/tests/test_typesafe_scorer.py \
  packages/pneuma-knowledge-core/tests/test_scorer_time_context.py \
  packages/pneuma-knowledge-core/tests/test_fast_scored_selector.py \
  packages/pneuma-knowledge-eval/tests/test_evidence_scoring.py -q
```

## Official references

- [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13): arithmetic/date comparison in code; reduce irrelevant state and indirection.
- [Score](https://docs.typesafe.ai/primitives/score) and [Confidence](https://docs.typesafe.ai/confidence): keep the distribution distinct from its expected score and from factual correctness.
- [API](https://docs.typesafe.ai/api): retryable failures and backoff. Native TypeSafe limits and model aliases do not automatically describe the OpenRouter route used here.
