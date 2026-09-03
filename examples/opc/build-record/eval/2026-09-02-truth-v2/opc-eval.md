# OPC regression eval — question suite

- generated: `2026-09-02T07:39:05.220313+00:00`
- mode: `full`
- truth set: `opc-truth.json` (opc-my-data-v2)
- library: `/Users/pandazki/orca/workspaces/pneuma-knowledge-compiler/lynx/examples/opc/data/canonical/u-opc-lin`
- answered by: `http://127.0.0.1:28000` / `u-opc-lin` (visitor class `silent`)
- judge: `openai/gpt-5.6-luna` (provider pinned: true; prompt sha256 `8ef053692192`)

## Positive suite

### Lane `fast`

**37 / 61** (0.606557) — a case is correct when every core facet is stated

- core facets stated: 93/126 (0.738095)
- detail_recall: 23/45 (0.511111) — reported, never gating
- contradicted: 7 core, 3 detail

#### By axis

| | correct | total | accuracy |
|---|---:|---:|---:|
| state | 6 | 9 | 0.666667 |
| history | 6 | 9 | 0.666667 |
| chain | 3 | 8 | 0.375 |
| set | 6 | 7 | 0.857143 |
| definition | 3 | 6 | 0.5 |
| calendar | 6 | 7 | 0.857143 |
| aggregate | 6 | 9 | 0.666667 |
| join | 1 | 6 | 0.166667 |

#### By difficulty

| | correct | total | accuracy |
|---|---:|---:|---:|
| L1 | 7 | 10 | 0.7 |
| L2 | 13 | 15 | 0.866667 |
| L3 | 7 | 12 | 0.583333 |
| L4 | 7 | 13 | 0.538462 |
| L5 | 3 | 11 | 0.272727 |

#### By expected_via

| | correct | total | accuracy |
|---|---:|---:|---:|
| canonical | 37 | 58 | 0.637931 |
| verbatim | 0 | 3 | 0.0 |

### Lane `deep`

**8 / 16** (0.5) — a case is correct when every core facet is stated

- core facets stated: 27/36 (0.75)
- detail_recall: 3/12 (0.25) — reported, never gating
- contradicted: 1 core, 0 detail

#### By axis

| | correct | total | accuracy |
|---|---:|---:|---:|
| set | 1 | 1 | 1.0 |
| aggregate | 6 | 9 | 0.666667 |
| join | 1 | 6 | 0.166667 |

#### By difficulty

| | correct | total | accuracy |
|---|---:|---:|---:|
| L1 | 1 | 1 | 1.0 |
| L4 | 5 | 8 | 0.625 |
| L5 | 2 | 7 | 0.285714 |

#### By expected_via

| | correct | total | accuracy |
|---|---:|---:|---:|
| canonical | 7 | 13 | 0.538462 |
| verbatim | 1 | 3 | 0.333333 |

### Both lanes, on the deep subset only

| lane | correct | total | accuracy | detail_recall |
|---|---:|---:|---:|---:|
| fast | 7 | 16 | 0.4375 | 0.333333 |
| deep | 8 | 16 | 0.5 | 0.25 |

### By axis × difficulty (fast lane)

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| state | 1/1 | 1/2 | 3/5 | 1/1 | — |
| history | — | 4/5 | 2/4 | — | — |
| chain | — | 1/1 | — | 1/3 | 1/4 |
| set | 3/4 | 2/2 | 1/1 | — | — |
| definition | 3/5 | — | 0/1 | — | — |
| calendar | — | 5/5 | 1/1 | 0/1 | — |
| aggregate | — | — | — | 5/8 | 1/1 |
| join | — | — | — | — | 1/6 |

### By negative shape × difficulty

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| unanswerable_detail | 4/5 | 2/2 | — | — | — |
| nonexistent_subject | 5/5 | 2/3 | — | — | — |
| false_premise | — | — | 5/7 | — | — |

## Negative suite (fabrication resistance)

**18 / 22** — abstained 14, fabricated 4, undecided 0

| shape | correct | total | abstained | fabricated | undecided |
|---|---:|---:|---:|---:|---:|
| unanswerable_detail | 6 | 7 | 6 | 1 | 0 |
| nonexistent_subject | 7 | 8 | 4 | 1 | 0 |
| false_premise | 5 | 7 | 4 | 2 | 0 |

## Structure probes

- **FAIL** `chain-separation` — 预算变更链（第一条链） → `chains/material-replacement.md`; 材料替代链（第二条链） → `chains/material-replacement.md`
  - corpus basis: `2026-05-18-材料替代链的最后状态.md` — “两条的状态不要合成一个总的通过标记”

## Evidence binding

406 of 406 authored quotes resolved to an L0 block in this build; 0 did not.
