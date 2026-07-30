# Evaluation scorecard — u-opc-lin

- mode: `mechanical`
- generated: 2026-07-30T00:56:27.976101+00:00
- checkpoints: 11
- documents at head: 9
- claims at head: 76
- L0 sources: 11 (145 blocks)

## Trajectory

| round | ref | committed | docs | claims | canonical chars |
| --- | --- | --- | --- | --- | --- |
| r01 | 3ac804493f63 | 2026-07-28T19:27:31 | 6 | 39 | 5453 |
| r02 | 4945f01281b6 | 2026-07-28T19:27:55 | 6 | 42 | 5937 |
| r03 | 9b39a80fde11 | 2026-07-28T19:28:06 | 6 | 46 | 6496 |
| r04 | 0a1fae94f60b | 2026-07-28T19:28:17 | 6 | 48 | 6746 |
| r05 | 2d1b8fd24ca7 | 2026-07-28T19:28:31 | 7 | 51 | 7165 |
| r06 | 53b492ef8b37 | 2026-07-28T19:28:46 | 8 | 56 | 7800 |
| r07 | ae274bbfca70 | 2026-07-28T19:29:18 | 8 | 60 | 8435 |
| r08 | 9b098ce08d08 | 2026-07-28T19:29:31 | 8 | 62 | 8654 |
| r09 | caafc408f79b | 2026-07-28T19:29:43 | 9 | 67 | 9244 |
| r10 | 7f1c56c11acd | 2026-07-28T19:30:03 | 9 | 72 | 9904 |
| r11 | 2272163a534d | 2026-07-28T19:30:22 | 9 | 76 | 10407 |

## A · grounded

| round | claims | cited | coverage | citations | resolvable | residue |
| --- | --- | --- | --- | --- | --- | --- |
| r01 | 39 | 38 | 0.9744 | 44 | 44 | 0 |
| r02 | 42 | 41 | 0.9762 | 47 | 47 | 0 |
| r03 | 46 | 45 | 0.9783 | 52 | 52 | 0 |
| r04 | 48 | 47 | 0.9792 | 54 | 54 | 0 |
| r05 | 51 | 50 | 0.9804 | 57 | 57 | 0 |
| r06 | 56 | 55 | 0.9821 | 62 | 62 | 0 |
| r07 | 60 | 59 | 0.9833 | 68 | 68 | 0 |
| r08 | 62 | 61 | 0.9839 | 69 | 69 | 0 |
| r09 | 67 | 66 | 0.9851 | 74 | 74 | 0 |
| r10 | 72 | 71 | 0.9861 | 79 | 79 | 0 |
| r11 | 76 | 75 | 0.9868 | 82 | 82 | 0 |

| transition | anchors before | anchors after | added | vanished (repo-wide) |
| --- | --- | --- | --- | --- |
| r01→r02 | 39 | 42 | 3 | 0 |
| r02→r03 | 42 | 46 | 4 | 0 |
| r03→r04 | 46 | 48 | 2 | 0 |
| r04→r05 | 48 | 51 | 3 | 0 |
| r05→r06 | 51 | 56 | 5 | 0 |
| r06→r07 | 56 | 60 | 4 | 0 |
| r07→r08 | 60 | 62 | 2 | 0 |
| r08→r09 | 62 | 67 | 5 | 0 |
| r09→r10 | 67 | 72 | 5 | 0 |
| r10→r11 | 72 | 76 | 4 | 0 |

## C · layering

| round | prose chars | markup chars | L0 chars | ratio | chars/claim |
| --- | --- | --- | --- | --- | --- |
| r01 | 2640 | 2813 | 4343 | 0.6079 | 67.6923 |
| r02 | 2934 | 3003 | 4463 | 0.6574 | 69.8571 |
| r03 | 3198 | 3298 | 4668 | 0.6851 | 69.5217 |
| r04 | 3324 | 3422 | 4873 | 0.6821 | 69.2500 |
| r05 | 3556 | 3609 | 5049 | 0.7043 | 69.7255 |
| r06 | 3878 | 3922 | 5238 | 0.7404 | 69.2500 |
| r07 | 4179 | 4256 | 5459 | 0.7655 | 69.6500 |
| r08 | 4319 | 4335 | 5551 | 0.7781 | 69.6613 |
| r09 | 4598 | 4646 | 5705 | 0.8060 | 68.6269 |
| r10 | 4942 | 4962 | 5982 | 0.8261 | 68.6389 |
| r11 | 5240 | 5167 | 6318 | 0.8294 | 68.9474 |

| round | claims | near-dup groups | cross-doc groups | dup row rate |
| --- | --- | --- | --- | --- |
| r01 | 39 | 2 | 1 | 0.0513 |
| r02 | 42 | 2 | 1 | 0.0476 |
| r03 | 46 | 2 | 1 | 0.0435 |
| r04 | 48 | 2 | 1 | 0.0417 |
| r05 | 51 | 2 | 1 | 0.0392 |
| r06 | 56 | 2 | 1 | 0.0357 |
| r07 | 60 | 2 | 1 | 0.0333 |
| r08 | 62 | 2 | 1 | 0.0323 |
| r09 | 67 | 2 | 1 | 0.0299 |
| r10 | 72 | 2 | 1 | 0.0278 |
| r11 | 76 | 2 | 1 | 0.0263 |

- corpus language: `cjk` (L0 block scripts {'mixed': 25, 'cjk': 120})

| round | claims | consistent | diverged | mixed | consistency rate |
| --- | --- | --- | --- | --- | --- |
| r01 | 39 | 29 | 0 | 10 | 0.7436 |
| r02 | 42 | 31 | 0 | 11 | 0.7381 |
| r03 | 46 | 33 | 0 | 13 | 0.7174 |
| r04 | 48 | 35 | 0 | 13 | 0.7292 |
| r05 | 51 | 38 | 0 | 13 | 0.7451 |
| r06 | 56 | 42 | 0 | 14 | 0.7500 |
| r07 | 60 | 44 | 0 | 16 | 0.7333 |
| r08 | 62 | 45 | 0 | 17 | 0.7258 |
| r09 | 67 | 49 | 0 | 18 | 0.7313 |
| r10 | 72 | 52 | 0 | 20 | 0.7222 |
| r11 | 76 | 56 | 0 | 20 | 0.7368 |

## D · navigability

| round | docs | edges | reachable | reach rate | isolated | orphan claims |
| --- | --- | --- | --- | --- | --- | --- |
| r01 | 6 | 0 | 1 | 0.1667 | 6 | 35 |
| r02 | 6 | 0 | 1 | 0.1667 | 6 | 38 |
| r03 | 6 | 0 | 1 | 0.1667 | 6 | 41 |
| r04 | 6 | 0 | 1 | 0.1667 | 6 | 43 |
| r05 | 7 | 0 | 1 | 0.1429 | 7 | 46 |
| r06 | 8 | 0 | 1 | 0.1250 | 8 | 51 |
| r07 | 8 | 0 | 1 | 0.1250 | 8 | 55 |
| r08 | 8 | 0 | 1 | 0.1250 | 8 | 57 |
| r09 | 9 | 0 | 1 | 0.1111 | 9 | 62 |
| r10 | 9 | 0 | 1 | 0.1111 | 9 | 66 |
| r11 | 9 | 0 | 1 | 0.1111 | 9 | 70 |

## E · evolution

| round | new claims | catch-all | share | under pressure |
| --- | --- | --- | --- | --- |
| r01 | 39 | 0 | 0.0000 | no |
| r02 | 3 | 0 | 0.0000 | no |
| r03 | 4 | 0 | 0.0000 | no |
| r04 | 2 | 0 | 0.0000 | no |
| r05 | 3 | 3 | 1.0000 | yes |
| r06 | 5 | 0 | 0.0000 | no |
| r07 | 4 | 0 | 0.0000 | no |
| r08 | 2 | 0 | 0.0000 | no |
| r09 | 5 | 0 | 0.0000 | no |
| r10 | 5 | 0 | 0.0000 | no |
| r11 | 4 | 0 | 0.0000 | no |

- response status: `no_evolution_events`
- response verdict: `aligned_restraint`

## B · admission

- B status: `unavailable` — no truth set is bound to this trajectory: admission judgement is only measurable against a corpus whose facts, exhaust and supersessions were labelled before compilation


## F · usability QA

- F status: `skipped` — outcome question answering needs a live recall path (and, for the judge arm, a model); mechanical mode is defined as zero-LLM and zero-network


## Findings

| severity | metric | observed | why it matters |
| --- | --- | --- | --- |
| high | `A.citations.claim_coverage` | 75/76 | an uncited claim is an assertion in the only non-rebuildable layer |
| medium | `C.duplication.cross_document_groups` | 1 | two documents claiming the same fact means neither owns the subject |
| medium | `C.verbatim_reproduction.transcription_rate` | 0.0267 | canonical is the thread layer; a transcript duplicates L0 without adding a thread |
| low | `C.compression.trend` | 0.2215 | a rising ratio means the compiler transcribes at a fixed rate instead of threading |
| high | `D.reachability.edges` | 0 | with no inter-document links the follow-the-thread job does not exist at all |
| medium | `D.reachability.isolated_documents` | 9 | an isolated document is retrievable but not browsable |
| medium | `D.growth.canonical_growth_exponent` | 1.7477 | canonical growing at or above the material's own rate means the bird's-eye view stops improving as material accumulates |
| coverage | `B.admission` | unavailable | no truth set is bound to this trajectory: admission judgement is only measurable against a corpus whose facts, exhaust and supersessions were labelled before compilation |
| coverage | `F.usability_qa` | skipped | outcome question answering needs a live recall path (and, for the judge arm, a model); mechanical mode is defined as zero-LLM and zero-network |
