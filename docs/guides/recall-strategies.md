# Choosing a recall strategy

**English** | [简体中文](recall-strategies.zh-CN.md)

Every question takes the same two steps: retrieval pulls candidates out of the index, and one
model call writes the answer. `evidence_strategy` decides the one thing in between — whether
anything chooses which of those candidates the answer gets to see, and who does the choosing.
There are three answers to that, and none of them is better than the others in the abstract:
they trade latency, input cost and precision against each other, and which trade is right
depends on what your users are waiting for.

This guide is for the person making that call for a business. It states what each strategy
does, shows one measurement so the shape of the trade-off is concrete, and ends in a decision
table. The per-setting reference is [reference/configuration.md](../reference/configuration.md);
when an answer is already wrong and you are hunting for the layer that lost the fact, read
[recall-quality.md](recall-quality.md) instead — that is a different question from this one.

## The three strategies

**`ranked` — take the heads.** Retrieval returns candidates in rank order; the lane takes the
top of each face (`claim_cap` claims, `episode_summary_cap` episode summaries, `window_cap`
verbatim windows) and hands them to the answer. One model call per question. Nothing judges
the cut except the retrieval score. The smallest prompt, the lowest latency, and the failure
mode is a fact that was retrieved at rank 41 and never shown.

**`select` — spend a call to choose.** The broad candidate pools go to one extra structured
model call, which returns *coordinates only* — which claims, which episode summaries, which
windows, which canonical documents. The framework validates every index it returns, unions in
a small deterministic ranked safety head so a bad selection cannot produce an empty context,
enforces the final caps, and follows the chosen claims back to bounded verbatim source. Two
model calls per question, and they are serial: the selection call sits between retrieval and
answering, so its latency is added, not overlapped. If it times out or the provider fails, the
lane falls back to the exact `ranked` context and marks the answer degraded — it never invents
a selection.

**`all` — remove the choice.** The same pool `select` would have judged goes to the answer
whole: no selection call, no score truncation. One model call per question, a much longer
prompt. Note two things the caps table does not say out loud — `all` reads
`claim_candidate_cap` (the broad number), not `claim_cap`, it takes *every* retrieved window
rather than `window_cap` of them, and it never reranks. Its only bound is
`all_context_chars`: over that ceiling it drops windows first, then episode summaries, then
the lowest-ranked claims, and states in the answer's telemetry what fell. It buys the failure
mode where the right evidence was retrieved and then not picked; it pays in input tokens and
in the answer model's attention.

## The calls per question

```
                        retrieval (index only, no model call)
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
     ranked                          select                            all
        │                               │                               │
 take the ranked heads          ONE selection call over          take the pool whole
 claim_cap / episode_           the broad pools; it returns      claim_candidate_cap
 summary_cap / window_cap       coordinates only, then the       claims, every window,
        │                       framework validates them         the widened episode set
        │                       and unions safety anchors                │
        │                               │                    all_context_chars trims
        │                               │                    windows → episodes →
        │                               │                    lowest claims, and says so
        └───────────────────────────────┼───────────────────────────────┘
                                        ▼
                                ONE answer call
                    (under answer_format: structured, `all` writes a
                     bounded `deliberation` field FIRST — the evidence
                     review no selector performed, inside the same call)
```

## The knobs that ride along

- **`deliberation` is not a setting.** It turns on by itself when `evidence_strategy: all`
  meets `answer_format: structured`. The structured schema then opens with one bounded field
  the model writes *before* it commits to an answer: it names which of the handed-over items
  bear on the question and dismisses the rest. It costs no extra call — it is a field in front
  of the answer in the same one — and it is returned on the wire as `deliberation`, never
  entering the system prompt. Use it when a reviewer has to see why evidence was accepted or
  ignored.
- **`answer_reasoning_effort`** is a provider hint bound to the final answer call only. Empty
  sends nothing at all, so the request is byte-identical to the no-knob behaviour and the
  provider's own default applies. Changing it needs a restart.
- **`selection_reasoning_effort`** is the same hint bound to the `select` call only, and is
  read by no other strategy. Applies hot.
- **`all_context_chars`** is `all`'s only bound and is read by nothing else. `0` turns the
  ceiling off; it does not mean "drop everything".
- **Candidate caps vs final caps.** `claim_candidate_cap` / `window_candidate_cap` are index
  depth — cheap, and the thing to raise when the needed evidence is not in the pool at all.
  `claim_cap` / `episode_summary_cap` / `window_cap` bound the final prompt — raise those when
  the pool is right and the context is dropping what the answer needed. Raising a final cap
  because a candidate cap was too small just makes the prompt bigger without adding the fact.

## One measurement, so the trade-off is concrete

These numbers come from **one library, one question, one provider** — a real 88-day
collaboration library, a single representative question, run against a single model provider.
They are the shape of the trade, not a benchmark, and your library will not reproduce them.
Measure your own before you commit; latency in particular is a property of your provider on
your prompt sizes.

| | `select` | `all` |
|---|---|---|
| Wall clock | 17.4 s | 10–13 s |
| Input tokens | ~27.7k | ~40k |
| Documents cited in the answer | 1 | 2–5 |

`all` was **faster and broader** here, and that is not a paradox: the serial selection call
`select` spends costs more wall clock than the longer prompt does, and by not choosing, `all`
left the answer standing on evidence from several documents instead of one. What `select`
bought in exchange is a narrower, deliberately chosen evidence set — which is what you want
when the answer will be audited claim by claim, and what you do not want when the reader
needed the second and third document too.

Two more observations from the same run: turning on `deliberation` cost about **+300 output
tokens and +2–3 s**, and returned a readable evidence review with it. And
`answer_reasoning_effort` showed **no monotone effect** on that provider — raising it did not
reliably improve the answer or reliably cost more time, so treat it as something to test, not
something to turn up.

## Decision table

| If the library serves… | Set | Because |
|---|---|---|
| an interactive assistant, where the wait *is* the product | `evidence_strategy: all` | no serial selection call; measured 10–13 s against `select`'s 17.4 s, at roughly 1.5× the input bill |
| audit, compliance, or any reading where a narrow, deliberately chosen evidence set matters more than breadth | `evidence_strategy: select` | the selection call is a second pass over the evidence before the answer sees it, and it fails soft to `ranked` |
| the cheapest question at the highest volume | `evidence_strategy: ranked` | one call, the smallest prompt, no widened pool — the baseline everything else is measured against |
| a reviewer who must see *why* evidence was accepted or ignored | `all` + `answer_format: structured` | that pair turns on `deliberation`, at ~+300 tokens and +2–3 s |
| downstream automation that needs a clean answer string and a separately validated citation ledger | `answer_format: structured` | independent of the strategy; consume `answer_text`, render `answer` |

And for the caps, one rule: **raise a candidate cap when the fact is missing from the pool,
raise a final cap when the pool has it and the context drops it.** Under `all`, the number
that widens the claim pool is `claim_candidate_cap`, not `claim_cap`, and the window face is
already unbounded — so the knob that matters there is `all_context_chars`, which is what
decides how much of it survives.

Nothing here changes a default. The framework ships `evidence_strategy: ranked` and
`answer_format: text`, a generated engine writes the same, and the deployment these numbers
were measured on keeps `select` as its default — `all` with `deliberation` is a deliberate
choice for a workload, not a new baseline. Both settings can also be overridden for a single
question (`evidence_strategy` / `answer_format` in the recall request body, or
`--evidence-strategy` / `--answer-format` on a generated project's CLI), which is the cheapest
way to compare them on your own material before changing anything.
