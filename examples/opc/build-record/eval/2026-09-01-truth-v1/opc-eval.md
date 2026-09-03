# OPC regression eval — question suite

- generated: `2026-09-01T16:19:14.578744+00:00`
- mode: `full`
- truth set: `opc-truth.json` (opc-my-data-v1)
- library: `/Users/pandazki/orca/workspaces/pneuma-knowledge-compiler/lynx/examples/opc/data/canonical/u-opc-lin`
- answered by: `http://127.0.0.1:28000` / `u-opc-lin` (visitor class `silent`)

## Positive suite

**36 / 59** (0.610169)

### By axis

| | correct | total | accuracy |
|---|---:|---:|---:|
| state | 6 | 8 | 0.75 |
| history | 7 | 8 | 0.875 |
| chain | 4 | 8 | 0.5 |
| set | 6 | 7 | 0.857143 |
| definition | 3 | 6 | 0.5 |
| calendar | 3 | 7 | 0.428571 |
| aggregate | 5 | 9 | 0.555556 |
| join | 2 | 6 | 0.333333 |

### By difficulty

| | correct | total | accuracy |
|---|---:|---:|---:|
| L1 | 7 | 10 | 0.7 |
| L2 | 12 | 15 | 0.8 |
| L3 | 5 | 10 | 0.5 |
| L4 | 7 | 13 | 0.538462 |
| L5 | 5 | 11 | 0.454545 |

### By axis × difficulty

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| state | 1/1 | 2/2 | 2/4 | 1/1 | — |
| history | — | 5/5 | 2/3 | — | — |
| chain | — | 0/1 | — | 2/3 | 2/4 |
| set | 3/4 | 2/2 | 1/1 | — | — |
| definition | 3/5 | — | 0/1 | — | — |
| calendar | — | 3/5 | 0/1 | 0/1 | — |
| aggregate | — | — | — | 4/8 | 1/1 |
| join | — | — | — | — | 2/6 |

### By negative shape × difficulty

| | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| unanswerable_detail | 5/6 | 1/1 | — | — | — |
| nonexistent_subject | 5/5 | 2/3 | — | — | — |
| false_premise | — | — | 6/7 | — | — |

## Negative suite (fabrication resistance)

**19 / 22** — abstained 12, fabricated 3, undecided 0

| shape | correct | total | abstained | fabricated | undecided |
|---|---:|---:|---:|---:|---:|
| unanswerable_detail | 6 | 7 | 6 | 1 | 0 |
| nonexistent_subject | 7 | 8 | 3 | 1 | 0 |
| false_premise | 6 | 7 | 3 | 1 | 0 |

## Structure probes

- **FAIL** `chain-separation` — 预算变更链（第一条链） → `chains/material-replacement.md`; 材料替代链（第二条链） → `chains/material-replacement.md`
  - corpus basis: `2026-05-18-材料替代链的最后状态.md` — “两条的状态不要合成一个总的通过标记”

## Evidence binding

210 of 210 authored quotes resolved to an L0 block in this build; 0 did not.
