# OPC regression eval — question suite

- generated: `2026-09-02T11:09:54.343188+00:00`
- mode: `full`
- truth set: `opc-truth.json` (opc-my-data-v3)
- library: `/Users/pandazki/orca/workspaces/pneuma-knowledge-compiler/lynx/examples/opc/data/canonical/u-opc-lin`
- answered by: `http://127.0.0.1:28000` / `u-opc-lin` (visitor class `silent`)
- judge: `openai/gpt-5.6-luna` (provider pinned: true; prompt sha256 `f1d54900d364`)

## Reconciliation — an eval-set change, not a library change

Same library, byte-for-byte; same stack, same corpus, same harness, no compile in between. Every difference below is a difference in the ruler.

Four lines have now been scored against the same shipped library, the same stack and the same corpus, and every difference between them is a difference in the ruler. `ruler_changes` on a case says which revision touched it, so a case that moved can be attributed rather than guessed at: a case with no entry has carried the same facets since v2, and if its verdict moved between the v2 line and this one, the judge is the only thing that changed underneath it.

| line | truth set | run | judge prompt | fast-lane positive | negative |
|---|---|---|---|---:|---:|
| truth-v1 | `opc-my-data-v1` | 2026-09-01 | `not recorded` | 36 / 59 | 19 / 22 |
| truth-v2 | `opc-my-data-v2` | 2026-09-02 | `8ef053692192` | 37 / 61 | 18 / 22 |
| truth-v3-second-pass | `opc-my-data-v3` | 2026-09-02 | `4cc14c3a189e` | 43 / 61 | 22 / 22 |
| this line | `opc-my-data-v3` | 2026-09-02 | `f1d54900d364` | 40 / 61 | 21 / 22 |

### Against `truth-v1` (2026-09-01)

24 of 85 questions changed status, grouped by the ruler revision that touched them.

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

#### facet split — 13 question(s)

35 facets that still joined two claims (「X：Y」, 「X，也 Y」, 「X 而不是 Y」) became 77 single-proposition facets. A split moves a case in either direction: the half the question asked stays core, the qualifier it did not ask for becomes a detail, and a case that used to hang on one long string now passes or fails on each proposition separately.

| case | truth-v1 | this line |
|---|---|---|
| `calendar-02` | miss | pass |
| `calendar-07` | miss | pass |
| `chain-02` | miss | pass |
| `chain-07` | pass | miss |
| `definition-02` | miss | pass |
| `definition-06` | pass | miss |
| `join-02` | pass | miss |
| `join-04` | miss | pass |
| `join-05` | pass | miss |
| `join-06` | miss | pass |
| `state-05` | pass | miss |
| `state-06` | pass | miss |
| `state-08` | miss | pass |

#### faceted truths, then the judge — 4 question(s)

On the v1 line this question's truth was one string checked as a whole. It has been a list of tagged facets since v2, graded facet by facet, and the judge behind that grading was recalibrated in v3. Two ruler changes lie between that line and this one, so a case here is not attributable to either alone — the v2 line is in this folder for exactly that reason.

| case | truth-v1 | this line |
|---|---|---|
| `aggregate-06` | pass | miss |
| `calendar-04` | miss | pass |
| `state-04` | miss | pass |
| `state-07` | pass | miss |

### Against `truth-v2` (2026-09-02)

14 of 83 questions changed status, grouped by the ruler revision that touched them.

#### facet split — 8 question(s)

35 facets that still joined two claims (「X：Y」, 「X，也 Y」, 「X 而不是 Y」) became 77 single-proposition facets. A split moves a case in either direction: the half the question asked stays core, the qualifier it did not ask for becomes a detail, and a case that used to hang on one long string now passes or fails on each proposition separately.

| case | truth-v2 | this line |
|---|---|---|
| `chain-06` | miss | pass |
| `definition-02` | miss | pass |
| `history-01` | miss | pass |
| `history-06` | miss | pass |
| `join-01` | pass | miss |
| `join-04` | miss | pass |
| `join-06` | miss | pass |
| `state-08` | miss | pass |

#### judge calibration — 6 question(s)

These cases' facets are byte-identical to the previous line's. The positive judge is now asked for ENTAILMENT rather than for whether the answer states the facet's words, and the negative judge reads the L0 text behind the answer's own citations before calling anything fabrication. Nothing else under these cases moved.

| case | truth-v2 | this line |
|---|---|---|
| `aggregate-06` | pass | miss |
| `aggregate-08` | pass | miss |
| `state-07` | pass | miss |
| `miss-fp-03` | miss | pass |
| `miss-fp-04` | miss | pass |
| `miss-ud-07` | miss | pass |

### Against `truth-v3-second-pass` (2026-09-02)

6 of 83 questions changed status, grouped by the ruler revision that touched them.

#### judge prompt — the nonexistent_subject clause — 6 question(s)

One clause in the negative judge's prompt is the only thing between this line and the previous one, and it was written before this line was scored rather than after: on a `nonexistent_subject` question, an answer that gives a value for the invented subject WITHOUT naming the real subject it belongs to has answered inside the invented one and is fabrication; naming the real subject and correcting the question, or refusing, is not. Questions, facets, corpus quotes and the positive judging language are byte-identical across the two lines, so a case listed here moved under that clause or under the answering lane's own run-to-run noise — a width the previous line measured at eight of 61 fast-lane cases.

| case | truth-v3-second-pass | this line |
|---|---|---|
| `aggregate-06` | pass | miss |
| `aggregate-08` | pass | miss |
| `chain-07` | pass | miss |
| `definition-06` | pass | miss |
| `join-06` | miss | pass |
| `miss-ns-06` | pass | miss |


## Positive suite

### Lane `fast`

**40 / 61** (0.655738) — a case is correct when every core facet is stated

- core facets stated: 109/139 (0.784173)
- detail_recall: 34/74 (0.459459) — reported, never gating
- contradicted: 6 core, 1 detail

#### By axis

| | correct | total | accuracy |
|---|---:|---:|---:|
| state | 6 | 9 | 0.666667 |
| history | 8 | 9 | 0.888889 |
| chain | 4 | 8 | 0.5 |
| set | 6 | 7 | 0.857143 |
| definition | 4 | 6 | 0.666667 |
| calendar | 6 | 7 | 0.857143 |
| aggregate | 4 | 9 | 0.444444 |
| join | 2 | 6 | 0.333333 |

#### By difficulty

| | correct | total | accuracy |
|---|---:|---:|---:|
| L1 | 8 | 10 | 0.8 |
| L2 | 14 | 15 | 0.933333 |
| L3 | 9 | 12 | 0.75 |
| L4 | 5 | 13 | 0.384615 |
| L5 | 4 | 11 | 0.363636 |

#### By expected_via

| | correct | total | accuracy |
|---|---:|---:|---:|
| canonical | 40 | 58 | 0.689655 |
| verbatim | 0 | 3 | 0.0 |

### Lane `deep`

**10 / 16** (0.625) — a case is correct when every core facet is stated

- core facets stated: 32/40 (0.8)
- detail_recall: 8/15 (0.533333) — reported, never gating
- contradicted: 2 core, 1 detail

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
| fast | 6 | 16 | 0.375 | 0.266667 |
| deep | 10 | 16 | 0.625 | 0.533333 |

### By axis × difficulty (fast lane)

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| state | 1/1 | 1/2 | 4/5 | 0/1 | — |
| history | — | 5/5 | 3/4 | — | — |
| chain | — | 1/1 | — | 2/3 | 1/4 |
| set | 3/4 | 2/2 | 1/1 | — | — |
| definition | 4/5 | — | 0/1 | — | — |
| calendar | — | 5/5 | 1/1 | 0/1 | — |
| aggregate | — | — | — | 3/8 | 1/1 |
| join | — | — | — | — | 2/6 |

### By negative shape × difficulty

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| unanswerable_detail | 5/5 | 2/2 | — | — | — |
| nonexistent_subject | 5/5 | 2/3 | — | — | — |
| false_premise | — | — | 7/7 | — | — |

## Negative suite (fabrication resistance)

**21 / 22** — abstained 14, fabricated 1, undecided 0

| shape | correct | total | abstained | fabricated | undecided | premise accepted |
|---|---:|---:|---:|---:|---:|---:|
| unanswerable_detail | 7 | 7 | 7 | 0 | 0 | — |
| nonexistent_subject | 7 | 8 | 4 | 1 | 0 | — |
| false_premise | 7 | 7 | 3 | 0 | 0 | 0/7 |

`premise_accepted` — of 7 false-premise questions the answer accepted the premise in 0 and rejected it in 7 (0 undecided). A second verdict, reported apart from the fabrication line and never folded into it.

## Structure probes

- **FAIL** `chain-separation` — 预算变更链（第一条链） → `chains/material-replacement.md`; 材料替代链（第二条链） → `chains/material-replacement.md`
  - corpus basis: `2026-05-18-材料替代链的最后状态.md` — “两条的状态不要合成一个总的通过标记”

## Evidence binding

442 of 442 authored quotes resolved to an L0 block in this build; 0 did not.
