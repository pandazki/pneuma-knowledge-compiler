# Post-protocol measured line: capability-guidance

This is the specification for the maintainer-ordered 2026-09-04 answer-and-score line. It is
not part of the frozen 2026-09-03 run and must not change that run's recorded 78.147612% score.

## Attribution boundary

- Framework base: `0646268bea1ed51f546112461d01519892975326`.
- Follow-up head: `212a8fe46da3a8e6f29d36ed82dd7cb38b39736a`.
- The follow-up head is exactly four commits after the base. The measured treatment is those
  four commits plus the requested concurrency change. Within this one line, the canonical-
  document glance and concise-coherence changes cannot be separated from one another.
- The ten compiled libraries, frozen allowlisted question projection, answer flags, judge,
  metrics, and official dataset are unchanged. No compile/evolve/challenge work is rerun.
- Every `app-NN/app.py` must be byte-identical to the follow-up head's
  `scaffold/templates/app.py`, SHA-256
  `67f43f2ef0d71dba9d6499071b134b5b44ad60449a4ad6d2c938cb27fd5e1f92`.

## Immutable baseline

The following original-run artifacts are guarded before answering, before scoring, and after
scoring:

```text
6c9598fb597417dda3e6e02a588e7233e8765842482f6b4104001651bd5fcef4  RUN-REPORT.md
693b4944ea60583a839caff68ceffa9359b2b94211b47074b6919af5a05a7a86  results/score-summary.json
0074f150ab3073e5e4974c0f29b1b3bd279d87c3586b7d0b1e9cb0a763ad1d82  results/official-summary.json
c1134ae29ba81a0f22af92ecb83e4cd319079e26a06e1ced62e1b34d57737140  results/predictions.jsonl
2c299829ba2c9934a28f97b5556c90a7e8feb84fbd84b58c1c9acaa6654259f3  results/predictions-scored-sanitized.jsonl
```

The follow-up may append `RUN-LOG.md`, add `REPORT-ADDENDUM.md`, add scripts/tests/build records,
and add `results/2026-09-04-capability-guidance/`. It must not overwrite any root-level result.

## Input and output contracts

- Question input is only `outputs/questions-projected.jsonl`, SHA-256
  `42bcc322da30d8ca9cf9862c9b9be8471c023f74ab6fb902b55a1d995c0b6410`. Each record must contain
  exactly `qa_id`, `conversation_idx`, and `question`. The follow-up code never opens the official
  questions file.
- Fresh answers live only under `outputs/answers-2026-09-04/`. The first launch refuses a
  non-empty unowned directory; a line-owned marker then makes interruption recovery explicit.
  It never reads or writes `outputs/answers/`.
- Each completed ask is one atomically replaced JSON record under
  `records/app-NN/`. A resumed process validates and skips only records in this new line. A
  complete app is deterministically assembled into `app-NN.jsonl` in projection order.
- Safe scored artifacts live only in `results/2026-09-04-capability-guidance/`. Gold-bearing raw
  scorer artifacts live only in the ignored `data/outputs/2026-09-04-capability-guidance/`.
- Scored output uses the existing frozen `assemble_predictions.py`, `run_official_score.py`, and
  `sanitize_results.py`. The official command remains `./scripts/run_eval.sh --metrics llm f1
  bleu --llm-judge refined --concurrency 64` with `qwen/qwen3-14b`.

## Concurrency, retries, and budget

- All ten stacks are started before asking. All ten conversation runners start together.
- Per-project worker allocation is `4,4,3,3,3,3,3,3,3,3`, for an exact global maximum of 32
  in-flight asks. Each ask is read-only and the CLI's unchanged default is a silent visitor.
- Every ask uses the original question unchanged and the same flags:
  `--style concise --evidence-strategy select --answer-format structured`; it never uses `--deep`
  or original-image retrieval.
- A failed or timed-out ask is never recorded as success. Up to five attempts back off for
  15/30/60/120 seconds. 429/rate-limit failures are classified in control logs without printing
  response bodies. Exhaustion leaves the qa_id absent and makes the runner fail.
- The answer-side soft ceiling is USD 50 under the original conservative Luna pricing
  ($0.20/M input, $1.20/M output, no cache discount). A controller snapshot scans only this
  line's atomic records, reports observed/projected cost, and discloses a soft-ceiling crossing;
  a soft ceiling is not silently converted into a hard stop.

## Lifecycle and completion

Docker mutations are allowed only through an `app-NN/app.py` whose `.env` has the exact
`pneuma-lcr2609-NN-` compose prefix. Stacks are brought down after scoring without deleting
volumes. Completion requires 1,382 unique non-empty predictions, successful official scoring,
recursive absence of prohibited gold fields in the sanitized copy, unchanged baseline hashes,
zero remaining owned containers, a committed addendum, and a clean site worktree.
