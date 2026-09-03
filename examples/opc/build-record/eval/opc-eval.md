# OPC regression eval — question suite

- generated: `2026-09-03T04:12:08.706330+00:00`
- mode: `full`
- truth set: `opc-truth.json` (opc-my-data-v6)
- library: `/Users/pandazki/orca/workspaces/pneuma-knowledge-compiler/lynx/examples/opc/data/canonical/u-opc-lin`
- answered by: `http://127.0.0.1:28000` / `u-opc-lin` (visitor class `silent`)
- judge: `openai/gpt-5.6-luna` (provider pinned: true; prompt sha256 `4e61c27b9e93`)
- judge calibration: 112/112 items agreed (100.0%); blocking variants all agreed — see `judge-calibration.md`

## Reconciliation — an EVAL-SET change — truth v6 and a calibrated judge; library and engine untouched

Same canonical library, byte-for-byte, and no compile in between; same stack, same corpus, same harness, and the same engine configuration the previous line was answered under (`evidence_strategy: select`). What changed is the ruler, on both of its halves. Every one of the 84 questions was re-read against the inputs alone by an independent read-only process and the maintainer's accepted findings applied — questions pinned in time, compound facets split, negative `absent` statements narrowed. And the judge's own approximation rule was corrected against the calibration suite, which now agrees with all 112 of its items and gates on every variant but one. Every difference below is a difference in the measurement.

Seven lines have now been scored against the same shipped canonical library, the same stack and the same corpus. `ruler_changes` on a case says which revision of the truth set touched it and which change inside that revision, so a case that moved can be attributed rather than guessed at — and a revision the compared line was already scored under cannot be blamed for a move since. What is left for a case with no revision in between is the fallback this map names for that key: for a v5 comparison it is the judge-rule-or-noise group, because the one corrected judging rule reaches every case in its suite and cannot be separated, case by case, from the answering lane's own width — measured twice at 5–8 of 61 fast-lane cases.

| line | truth set | run | judge prompt | answering | fast-lane positive | negative |
|---|---|---|---|---|---:|---:|
| truth-v5-select | `opc-my-data-v5` | 2026-09-02 | `1d189759c379` | `select` | 43 / 61 | 20 / 22 |
| this line | `opc-my-data-v6` | 2026-09-03 | `4e61c27b9e93` | `select` | 48 / 61 | 21 / 22 |

### Against `truth-v5-select` (2026-09-02)

14 of 83 questions changed status, grouped by the ruler revision that touched them.

#### the question re-pinned in time, or re-targeted — 10 question(s)

An accepted finding of the per-case rigor audit, and its largest class: a question with no date, scored against a state the corpus later changed, loses a library that answers with the current value. These questions now name the date they ask about and their `as_of` says the same; chain-08 went the other way and asks 「目前」, with the April state kept as a detail. A case whose facets moved as well is filed here rather than under the split, because the pin is what forced them.

| case | truth-v5-select | this line |
|---|---|---|
| `calendar-05` | miss | pass |
| `chain-01` | miss | pass |
| `chain-03` | miss | pass |
| `chain-05` | pass | miss |
| `chain-06` | pass | miss |
| `join-04` | miss | pass |
| `join-06` | miss | pass |
| `set-02` | pass | miss |
| `set-03` | pass | miss |
| `set-07` | miss | pass |

#### facets split, or a core and a detail retagged — 1 question(s)

An accepted finding of the audit. 24 facets that bundled two claims became separate facets, and core against detail was brought back to exactly what the question asks — a count the question did ask for became a core, a room number and a witness's name became details. The judge returns one verdict per facet, so a split moves a case in either direction.

| case | truth-v5-select | this line |
|---|---|---|
| `join-05` | miss | pass |

#### the judge's approximation rule, or the answering lane's own noise — 3 question(s)

These cases' questions, `as_of`, facets and `absent` statements are byte-identical to the previous line's: the truth set did not touch them, so nothing in it can have moved them. Two things between the lines can. (1) The facet judge's rule 9. An approximation is now read as an assertion of a value carrying the tolerance its rounding word implies — `stated` when the fact falls inside it, `contradicted` when the range excludes it — where before a non-rounding approximation was `omitted`; the suite's own item for it was expecting the wrong verdict, which is how the correction was found. (2) The lane's own run-to-run width, measured on this suite at 5–8 of 61 fast-lane cases. The two cannot be told apart case by case, and this list does not try: it names the questions and stops.

| case | truth-v5-select | this line |
|---|---|---|
| `aggregate-04` | miss | pass |
| `join-01` | miss | pass |
| `miss-fp-03` | miss | pass |


## Positive suite

### Lane `fast`

**48 / 61** (0.786885) — a case is correct when every core facet is stated

- core facets stated: 128/154 (0.831169)
- detail_recall: 37/88 (0.420455) — reported, never gating
- contradicted: 12 core, 4 detail

#### By axis

| | correct | total | accuracy |
|---|---:|---:|---:|
| state | 8 | 9 | 0.888889 |
| history | 8 | 9 | 0.888889 |
| chain | 4 | 8 | 0.5 |
| set | 5 | 7 | 0.714286 |
| definition | 5 | 6 | 0.833333 |
| calendar | 7 | 7 | 1.0 |
| aggregate | 7 | 9 | 0.777778 |
| join | 4 | 6 | 0.666667 |

#### By difficulty

| | correct | total | accuracy |
|---|---:|---:|---:|
| L1 | 8 | 10 | 0.8 |
| L2 | 14 | 15 | 0.933333 |
| L3 | 10 | 12 | 0.833333 |
| L4 | 8 | 13 | 0.615385 |
| L5 | 8 | 11 | 0.727273 |

#### By expected_via

| | correct | total | accuracy |
|---|---:|---:|---:|
| canonical | 47 | 58 | 0.810345 |
| verbatim | 1 | 3 | 0.333333 |

### Lane `deep`

**12 / 16** (0.75) — a case is correct when every core facet is stated

- core facets stated: 38/43 (0.883721)
- detail_recall: 8/22 (0.363636) — reported, never gating
- contradicted: 2 core, 0 detail

#### By axis

| | correct | total | accuracy |
|---|---:|---:|---:|
| set | 1 | 1 | 1.0 |
| aggregate | 6 | 9 | 0.666667 |
| join | 5 | 6 | 0.833333 |

#### By difficulty

| | correct | total | accuracy |
|---|---:|---:|---:|
| L1 | 1 | 1 | 1.0 |
| L4 | 5 | 8 | 0.625 |
| L5 | 6 | 7 | 0.857143 |

#### By expected_via

| | correct | total | accuracy |
|---|---:|---:|---:|
| canonical | 11 | 13 | 0.846154 |
| verbatim | 1 | 3 | 0.333333 |

### Both lanes, on the deep subset only

| lane | correct | total | accuracy | detail_recall |
|---|---:|---:|---:|---:|
| fast | 12 | 16 | 0.75 | 0.181818 |
| deep | 12 | 16 | 0.75 | 0.363636 |

### By axis × difficulty (fast lane)

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| state | 1/1 | 1/2 | 5/5 | 1/1 | — |
| history | — | 5/5 | 3/4 | — | — |
| chain | — | 1/1 | — | 0/3 | 3/4 |
| set | 2/4 | 2/2 | 1/1 | — | — |
| definition | 5/5 | — | 0/1 | — | — |
| calendar | — | 5/5 | 1/1 | 1/1 | — |
| aggregate | — | — | — | 6/8 | 1/1 |
| join | — | — | — | — | 4/6 |

### By negative shape × difficulty

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| unanswerable_detail | 5/5 | 2/2 | 1/1 | — | — |
| nonexistent_subject | 5/5 | 2/3 | — | — | — |
| false_premise | — | — | 6/6 | — | — |

## Negative suite (fabrication resistance)

**21 / 22** — abstained 15, fabricated 1, undecided 0

| shape | correct | total | abstained | fabricated | undecided | premise accepted |
|---|---:|---:|---:|---:|---:|---:|
| unanswerable_detail | 8 | 8 | 8 | 0 | 0 | — |
| nonexistent_subject | 7 | 8 | 5 | 1 | 0 | — |
| false_premise | 6 | 6 | 2 | 0 | 0 | 0/6 |

`premise_accepted` — of 6 false-premise questions the answer accepted the premise in 0 and rejected it in 6 (0 undecided). A second verdict, reported apart from the fabrication line and never folded into it.

## Structure probes

- **FAIL** `chain-separation` — 预算变更链（第一条链） → `chains/material-replacement.md`; 材料替代链（第二条链） → `chains/material-replacement.md`
  - corpus basis: `2026-03-21-云麓来源映射读取说明.md` — “预算变更与材料替代是两个独立入口”

## Evidence binding

501 of 501 authored quotes resolved to an L0 block in this build; 0 did not.
