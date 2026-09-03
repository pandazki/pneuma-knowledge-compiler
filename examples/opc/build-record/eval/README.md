# The reference line — OPC regression eval

This folder is the lineage index. The numbers live in the rendered reports beside it; what
this page holds is what each line IS, and what any two of them may be compared on.

## What a line is

A line is one scoring pass, identified by four things:

- the **truth set** it was scored against (`opc-my-data-vN`, the version stamped in
  `eval/opc-truth.json`);
- the **answering path** the library was asked through — `evidence_strategy`, and the
  `answer_format` that went with it;
- the **judge prompt** the facets and the negative auditor were graded under, by sha256;
- the **library** that answered, and the run date.

The current line lives at the top of this folder and keeps its raw artifacts. Every
superseded line keeps its dated subfolder with the two rendered summaries only
(`opc-eval.md`, `report.md`); its `opc-eval.json` / `scorecard.json` are dropped, because the
scorecard is the compile trajectory — identical across re-scores of one library — and the
per-case JSON of a line nobody compares against any more is weight without a reader.

## The lines

| line | truth set | answering | judge prompt | run | what distinguishes it |
|---|---|---|---|---|---|
| current — this folder | `opc-my-data-v6` | `select` | `4e61c27b9e93` | 2026-09-03 | every question audited against the inputs one at a time, then pinned in time where the corpus had moved on; the judge's approximation rule corrected against its own calibration suite, which agrees with all 112 items |
| [`2026-09-02-truth-v5-select/`](2026-09-02-truth-v5-select/) | `opc-my-data-v5` | `select` | `1d189759c379` | 2026-09-02 | a facet's illustrations sit beside its proposition; the negative auditor is told the absence it is handed is true |
| [`2026-09-02-truth-v4-select/`](2026-09-02-truth-v4-select/) | `opc-my-data-v4` | `select` | `f1d54900d364` | 2026-09-02 | the first line answered under `select` |
| [`2026-09-02-truth-v3-ranked/`](2026-09-02-truth-v3-ranked/) | `opc-my-data-v3` | `ranked` | `f1d54900d364` | 2026-09-02 | the last line answered under `ranked` |
| [`2026-09-02-truth-v3-second-pass/`](2026-09-02-truth-v3-second-pass/) | `opc-my-data-v3` | `ranked` | `f1d54900d364` | 2026-09-02 | scored before the auditor was told what answering inside an invented subject is |
| [`2026-09-02-truth-v3-first-pass/`](2026-09-02-truth-v3-first-pass/) | `opc-my-data-v3` | `ranked` | earlier | 2026-09-02 | the first v3 run, under the judge prompt that read the cited spans as the whole material |
| [`2026-09-02-truth-v2/`](2026-09-02-truth-v2/) | `opc-my-data-v2` | `ranked` | earlier | 2026-09-02 | kept whole |
| [`2026-09-01-truth-v1/`](2026-09-01-truth-v1/) | `opc-my-data-v1` | `ranked` | earlier | 2026-09-01 | the first line; 59 fast-lane cases rather than 61 |

Every pass is committed whole, including the ones whose numbers were higher than the line
that replaced them. Nothing here is selected.

## Comparison boundaries

**A number is only a library result when the library is the only thing that moved.** Two
lines whose truth set, answering path and judge prompt all match differ in the library alone,
and their difference is a library comparison. Any other pair crosses a ruler change, and its
difference is not attributable to the library at all — the run itself renders the per-case
reconciliation into [`opc-eval.md`](opc-eval.md) and [`report.md`](report.md), filing every
question whose status changed under the revision that lies between the two lines. A revision
the compared line was already scored under cannot be blamed for a move since: its facets were
byte-identical on both lines.

**A single-digit move on the fast lane is not a result.** Two independent measurements put
this suite's run-to-run width at 5 to 8 of the 61 fast-lane cases. A movement is attributable
only when the cases that moved are the cases a stated change was made for.

**The answering column is the process's own report, not the engine file.** The runner records
what answered each question (`answering_evidence_strategy`), because an edited file proves
nothing about a container that was not restarted, and `tests/test_opc_eval_set.py` holds the
committed line to the committed engine. The three earliest lines predate that field; their
`ranked` is stated from this repository's history.

**Quality and cost are separate axes.** Throughput and per-question cost are recorded in each
line's own report, apart from every quality number, and a claim about one says nothing about
the other.

## The grader, for the next comparison

| | |
|---|---|
| judge model | `openai/gpt-5.6-luna` |
| provider pinned | yes (this project's own OpenRouter route) |
| judge prompt sha256 | `4e61c27b9e934f7cac95ad486f22ffd6d3a4119d65deb00fb65f09f10fa5edf4` |
| previous line's prompt | `1d189759c37912b742df85d1e79e73404fee2f219ccee62aeb2604457d84b7bd` |
| judge calibration | 112 items, 112 agreed, no blocking variant short of 100% (`eval/judge-calibration.json`, run first by `--mode full`) |
| answering | `/v1/users/u-opc-lin/recall`, visitor class `silent`, fast lane `answer_format: structured`, `evidence_strategy: select` |

A later run that reports a different number has to say which of these moved before it can call
the difference a library change.

## The files

| file | what it is |
|---|---|
| `opc-eval.md` | the suite report this run rendered: the reconciliation, then lanes, axes, tiers, `expected_via`, negatives, probes |
| `opc-eval.json` | every case, every facet, every verdict and rationale, every answer, the L0 spans the negative judge was shown, the answering path each answer reported, and the resolved evidence locators |
| `report.md` / `scorecard.json` | the eval package's own scorecard over the compile trajectory (groups A–F), with the same reconciliation at its head |
| the dated subfolders | one superseded line each, as the table above names them |
| [`2026-09-03-truth-audit/`](2026-09-03-truth-audit/) | not a line: the per-case rigor audit that preceded truth v6 — one read-only process per case over the example's inputs, its 84 verdicts and their aggregate, kept as the provenance of the ruler this line was scored with |
