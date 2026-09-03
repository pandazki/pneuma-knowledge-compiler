# OPC regression eval — question suite

- generated: `2026-09-02T11:41:29.535482+00:00`
- mode: `full`
- truth set: `opc-truth.json` (opc-my-data-v4)
- library: `/Users/pandazki/orca/workspaces/pneuma-knowledge-compiler/lynx/examples/opc/data/canonical/u-opc-lin`
- answered by: `http://127.0.0.1:28000` / `u-opc-lin` (visitor class `silent`)
- judge: `openai/gpt-5.6-luna` (provider pinned: true; prompt sha256 `f1d54900d364`)

## Reconciliation — a LIBRARY-CONFIG change — `evidence_strategy` ranked→select — with one truth re-cut beside it

Same canonical library, byte-for-byte, and no compile in between; same stack, same corpus, same harness, same judge prompts. What did change is the engine this example ships: `engine/recall/recall.yaml` now states `evidence_strategy: select`, and the api container was restarted so the shipped file is what answered. Every line before this one was answered under `ranked`.

Five lines have now been scored against the same shipped canonical library, the same stack and the same corpus. Until this one, every difference between them was a difference in the ruler; this one also changed the answering configuration, which is a change to the deployment and not to the library — no compile ran, and the canonical repository is byte-identical. `ruler_changes` on a case says which revision of the truth set touched it, so a case that moved can be attributed rather than guessed at: a case with no entry has carried the same facets since the line it is being compared with, and what moved under it is the configuration flip or the answering lane's own run-to-run noise, a width this suite has measured twice at 5–8 of 61 fast-lane cases.

| line | truth set | run | judge prompt | answering | fast-lane positive | negative |
|---|---|---|---|---|---:|---:|
| truth-v1 | `opc-my-data-v1` | 2026-09-01 | `not recorded` | not recorded | 36 / 59 | 19 / 22 |
| truth-v2 | `opc-my-data-v2` | 2026-09-02 | `8ef053692192` | not recorded | 37 / 61 | 18 / 22 |
| truth-v3-ranked | `opc-my-data-v3` | 2026-09-02 | `f1d54900d364` | not recorded | 40 / 61 | 21 / 22 |
| this line | `opc-my-data-v4` | 2026-09-02 | `f1d54900d364` | `select` | 42 / 61 | 18 / 22 |

### Against `truth-v1` (2026-09-01)

25 of 85 questions changed status, grouped by the ruler revision that touched them.

#### corpus basis — 6 question(s)

The truth basis became the example's own inputs — my-data/ (190) plus the owner statement exercise.py sends. miss-ud-02 and miss-fp-02 stopped being unanswerable under that basis and were retired; what they tested is asked positively as state-09 and history-09, and miss-ud-08 / miss-fp-08 keep the negative suite at 22 in three shapes.

| case | truth-v1 | this line |
|---|---|---|
| `history-09` | — (not asked on that line) | pass |
| `state-09` | — (not asked on that line) | pass |
| `miss-fp-02` | miss | — (retired) |
| `miss-fp-08` | — (not asked on that line) | pass |
| `miss-ud-02` | miss | — (retired) |
| `miss-ud-08` | — (not asked on that line) | pass |

#### definition-01 re-authored — 1 question(s)

The v1 truth rewarded a throwaway self-deprecating line (「只是纸面工作名」) as a definition. A definition truth must come from how the corpus describes the thing, so the core facet is now what Seamlog IS, cited from the product description itself.

| case | truth-v1 | this line |
|---|---|---|
| `definition-01` | miss | pass |

#### facet split — 9 question(s)

35 facets that still joined two claims (「X：Y」, 「X，也 Y」, 「X 而不是 Y」) became 77 single-proposition facets. A split moves a case in either direction: the half the question asked stays core, the qualifier it did not ask for becomes a detail, and a case that used to hang on one long string now passes or fails on each proposition separately.

| case | truth-v1 | this line |
|---|---|---|
| `calendar-07` | miss | pass |
| `chain-02` | miss | pass |
| `chain-07` | pass | miss |
| `definition-02` | miss | pass |
| `join-02` | pass | miss |
| `join-05` | pass | miss |
| `join-06` | miss | pass |
| `state-06` | pass | miss |
| `state-08` | miss | pass |

#### faceted truths, then the judge — 9 question(s)

On the v1 line this question's truth was one string checked as a whole. It has been a list of tagged facets since v2, graded facet by facet, and the judge behind that grading was recalibrated in v3. Two ruler changes lie between that line and this one, so a case here is not attributable to either alone — the v2 line is in this folder for exactly that reason.

| case | truth-v1 | this line |
|---|---|---|
| `aggregate-06` | pass | miss |
| `aggregate-08` | miss | pass |
| `aggregate-09` | miss | pass |
| `calendar-04` | miss | pass |
| `set-04` | miss | pass |
| `set-07` | pass | miss |
| `miss-fp-03` | pass | miss |
| `miss-fp-06` | pass | miss |
| `miss-fp-07` | pass | miss |

### Against `truth-v2` (2026-09-02)

19 of 83 questions changed status, grouped by the ruler revision that touched them.

#### facet split — 10 question(s)

35 facets that still joined two claims (「X：Y」, 「X，也 Y」, 「X 而不是 Y」) became 77 single-proposition facets. A split moves a case in either direction: the half the question asked stays core, the qualifier it did not ask for becomes a detail, and a case that used to hang on one long string now passes or fails on each proposition separately.

| case | truth-v2 | this line |
|---|---|---|
| `calendar-02` | pass | miss |
| `chain-06` | miss | pass |
| `definition-02` | miss | pass |
| `definition-06` | miss | pass |
| `history-01` | miss | pass |
| `history-06` | miss | pass |
| `join-01` | pass | miss |
| `join-06` | miss | pass |
| `state-05` | miss | pass |
| `state-08` | miss | pass |

#### judge calibration — 9 question(s)

These cases' facets are byte-identical to the previous line's. The positive judge is now asked for ENTAILMENT rather than for whether the answer states the facet's words, and the negative judge reads the L0 text behind the answer's own citations before calling anything fabrication. Nothing else under these cases moved.

| case | truth-v2 | this line |
|---|---|---|
| `aggregate-06` | pass | miss |
| `aggregate-09` | miss | pass |
| `set-04` | miss | pass |
| `set-07` | pass | miss |
| `state-04` | pass | miss |
| `miss-fp-04` | miss | pass |
| `miss-fp-06` | pass | miss |
| `miss-fp-07` | pass | miss |
| `miss-ud-07` | miss | pass |

### Against `truth-v3-ranked` (2026-09-02)

13 of 83 questions changed status, grouped by the ruler revision that touched them.

#### library config — `evidence_strategy` ranked→select — 13 question(s)

These cases' questions, facets, corpus quotes and both judge prompts are byte-identical to the previous line's, and no compile ran between the two, so the truth set cannot have moved them. What lies between the lines is the example's engine: `evidence_strategy` went from `ranked` to `select`, the api container was restarted, and the answers on this line were composed by one bounded selection call over the broad candidate pools instead of by the top of each face in retrieval order. On a corpus this small the RRF scores are nearly flat (0.016–0.017 across the top 60), so `ranked` was handing the answer six windows in an order that carried almost no signal. A case listed here moved under that flip or under the answering lane's own noise, and the two cannot be separated case by case — only the direction of the whole column can be read.

| case | truth-v3-ranked | this line |
|---|---|---|
| `aggregate-08` | miss | pass |
| `aggregate-09` | miss | pass |
| `calendar-02` | pass | miss |
| `definition-06` | miss | pass |
| `join-04` | pass | miss |
| `set-04` | miss | pass |
| `set-07` | pass | miss |
| `state-04` | pass | miss |
| `state-05` | miss | pass |
| `state-07` | miss | pass |
| `miss-fp-03` | pass | miss |
| `miss-fp-06` | pass | miss |
| `miss-fp-07` | pass | miss |


## Positive suite

### Lane `fast`

**42 / 61** (0.688525) — a case is correct when every core facet is stated

- core facets stated: 109/139 (0.784173)
- detail_recall: 29/76 (0.381579) — reported, never gating
- contradicted: 10 core, 7 detail

#### By axis

| | correct | total | accuracy |
|---|---:|---:|---:|
| state | 7 | 9 | 0.777778 |
| history | 8 | 9 | 0.888889 |
| chain | 4 | 8 | 0.5 |
| set | 6 | 7 | 0.857143 |
| definition | 5 | 6 | 0.833333 |
| calendar | 5 | 7 | 0.714286 |
| aggregate | 6 | 9 | 0.666667 |
| join | 1 | 6 | 0.166667 |

#### By difficulty

| | correct | total | accuracy |
|---|---:|---:|---:|
| L1 | 10 | 10 | 1.0 |
| L2 | 12 | 15 | 0.8 |
| L3 | 9 | 12 | 0.75 |
| L4 | 8 | 13 | 0.615385 |
| L5 | 3 | 11 | 0.272727 |

#### By expected_via

| | correct | total | accuracy |
|---|---:|---:|---:|
| canonical | 41 | 58 | 0.706897 |
| verbatim | 1 | 3 | 0.333333 |

### Lane `deep`

**10 / 16** (0.625) — a case is correct when every core facet is stated

- core facets stated: 32/40 (0.8)
- detail_recall: 7/17 (0.411765) — reported, never gating
- contradicted: 3 core, 1 detail

#### By axis

| | correct | total | accuracy |
|---|---:|---:|---:|
| set | 1 | 1 | 1.0 |
| aggregate | 7 | 9 | 0.777778 |
| join | 2 | 6 | 0.333333 |

#### By difficulty

| | correct | total | accuracy |
|---|---:|---:|---:|
| L1 | 1 | 1 | 1.0 |
| L4 | 6 | 8 | 0.75 |
| L5 | 3 | 7 | 0.428571 |

#### By expected_via

| | correct | total | accuracy |
|---|---:|---:|---:|
| canonical | 9 | 13 | 0.692308 |
| verbatim | 1 | 3 | 0.333333 |

### Both lanes, on the deep subset only

| lane | correct | total | accuracy | detail_recall |
|---|---:|---:|---:|---:|
| fast | 8 | 16 | 0.5 | 0.294118 |
| deep | 10 | 16 | 0.625 | 0.411765 |

### By axis × difficulty (fast lane)

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| state | 1/1 | 1/2 | 4/5 | 1/1 | — |
| history | — | 5/5 | 3/4 | — | — |
| chain | — | 1/1 | — | 2/3 | 1/4 |
| set | 4/4 | 1/2 | 1/1 | — | — |
| definition | 5/5 | — | 0/1 | — | — |
| calendar | — | 4/5 | 1/1 | 0/1 | — |
| aggregate | — | — | — | 5/8 | 1/1 |
| join | — | — | — | — | 1/6 |

### By negative shape × difficulty

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| unanswerable_detail | 5/5 | 2/2 | — | — | — |
| nonexistent_subject | 5/5 | 2/3 | — | — | — |
| false_premise | — | — | 4/7 | — | — |

## Negative suite (fabrication resistance)

**18 / 22** — abstained 15, fabricated 4, undecided 0

| shape | correct | total | abstained | fabricated | undecided | premise accepted |
|---|---:|---:|---:|---:|---:|---:|
| unanswerable_detail | 7 | 7 | 7 | 0 | 0 | — |
| nonexistent_subject | 7 | 8 | 4 | 1 | 0 | — |
| false_premise | 4 | 7 | 4 | 3 | 0 | 1/7 |

`premise_accepted` — of 7 false-premise questions the answer accepted the premise in 1 and rejected it in 6 (0 undecided). A second verdict, reported apart from the fabrication line and never folded into it.

## Structure probes

- **FAIL** `chain-separation` — 预算变更链（第一条链） → `chains/material-replacement.md`; 材料替代链（第二条链） → `chains/material-replacement.md`
  - corpus basis: `2026-05-18-材料替代链的最后状态.md` — “两条的状态不要合成一个总的通过标记”

## Evidence binding

446 of 446 authored quotes resolved to an L0 block in this build; 0 did not.
