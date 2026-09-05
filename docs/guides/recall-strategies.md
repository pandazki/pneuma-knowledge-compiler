# Choosing a recall strategy

**English** | [简体中文](recall-strategies.zh-CN.md)

Every question takes the same two steps: retrieval pulls candidates out of the index, and one
model call writes the answer. `evidence_strategy` decides the one thing in between — whether
anything chooses which of those candidates the answer gets to see, and who does the choosing.
There are three answers to that, and none of them is better than the others in the abstract:
they trade latency, input cost and precision against each other, and which trade is right
depends on what your users are waiting for.

This guide is for the person making that call for a business. It states what each strategy
does, where the trade-off actually falls, and ends in a summary of what you are choosing
between — the choosing itself is yours, on your own material. All three are choices
inside the *fast* lane; the deep lane sits beside them and has its own section below. The
per-setting reference is [reference/configuration.md](../reference/configuration.md);
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
a selection. Provenance is the one thing it does not soften: when a chosen claim is followed
back to a source L0 cannot produce, the request fails rather than answering on evidence it
could not resolve.

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
  provider's own default applies. The override is merged with existing request options,
  including provider routing, and is carried through both text and structured calls.
  Changing it needs a restart.
- **`selection_reasoning_effort`** is the same hint bound to the `select` call only, and is
  read by no other strategy. Applies hot.
- **`all_context_chars`** is `all`'s only bound and is read by nothing else. `0` turns the
  ceiling off; it does not mean "drop everything".
- **Candidate caps vs final caps.** `claim_candidate_cap` / `window_candidate_cap` are index
  depth — cheap, and the thing to raise when the needed evidence is not in the pool at all.
  `claim_cap` / `episode_summary_cap` / `window_cap` bound the final prompt — raise those when
  the pool is right and the context is dropping what the answer needed. Raising a final cap
  because a candidate cap was too small just makes the prompt bigger without adding the fact.

## Where the trade-off actually falls

Latency is not ordered the way the call count suggests. The serial selection call `select`
spends can cost more wall clock than `all`'s longer prompt does, so `all` is not reliably the
slow one — and by not choosing, it leaves the answer standing on evidence from several
documents instead of one. What `select` buys in exchange is a narrower, deliberately chosen
evidence set: what you want when the answer will be audited claim by claim, and what you do
not want when the reader needed the second and third document too. `deliberation` costs
output tokens and a little time and returns a readable evidence review with them.
`answer_reasoning_effort` is not reliably monotone — treat it as something to test, not
something to turn up.

No figure belongs in that paragraph, because latency and cost are properties of your
provider, your prompt sizes and your library, and a number measured elsewhere does not
transfer. The one measured artifact in this repository is
[`examples/opc/build-record/eval/`](../../examples/opc/build-record/eval/), where every line
records its harness, its date and what may be compared with what; measure your own the same
way before you commit to a strategy.

## Beside them: the deep lane

All three strategies are choices *inside* the fast lane, and the fast lane is one of the two
this framework ships. The two are the canonical retrieval shapes, implemented once so a project
starts from a working reference instead of a blank file — `evidence_strategy` reaches only the
first of them, and sending it to the second is refused rather than ignored (the API answers 400,
a generated project's CLI exits).

**fast** is multi-path retrieval answered in a single call: lexical and vector retrieval over
the compiled claim face and the raw source face, fused by RRF, plus whatever routed paths the
enabled index components contribute, with `evidence_strategy` deciding what of that pool the
answer sees. **deep** is an agentic loop over the same faces: it opens on the evidence fast
would have answered over, plus the library's glance, then re-searches either face from new
angles, lists and reads canonical documents in full, follows the markdown links inside them,
and fetches verbatim spans. The loop is bounded — a tool budget and a trail record per call,
both mechanical — and it ends by answering.

Both lanes use the addressing scheme shared by the gate and projection, preserve no-trace
caller semantics, and report token usage. Citation coverage of every conclusion is a model
contract, not a semantic proof. Structured fast answers validate the explicit citation list
against the exact spans shown to the model. If any entry is rejected, it is removed and
`answer_format_degraded` is `invalid_citations`; the answer and its kind remain available,
and no second model call is made. An empty citation list alone does not trigger this marker,
including for `inference` and `no_record` answers.

They differ mechanically in two ways. **Cost:** fast is one model call (two under `select`) over
a prompt whose size follows from the caps; deep is a number of calls nobody knows in advance,
because the loop decides how many it needs, so its latency and token spend vary per question
instead of sitting near a constant. **Reach:** one shot answers over what one retrieval
returned, while a loop can walk, because a canonical document read in full carries its links and
following one is another read. Which is why a fact no retrieved passage states — a join across
documents, a count over many sources — is not a retrieval-depth problem: raising a candidate cap
widens what one shot sees, it does not move an answer to a neighbouring document.

Routing between them belongs to the application. Per-question routing, one lane always, both
offered to the reader, a lane of your own in place of either — the framework carries all of them
and holds none as doctrine. What these two are is the baseline your own arrangement is measured
against, and the cost line every answer returns is what makes that measurement yours rather than
borrowed from someone else's corpus.

## What you are choosing between

The three strategies and the two settings that ride beside them, as mechanism, cost, reach
and what each one lets you see afterwards. No row says which workload it belongs to: that
depends on your library, your provider and what your readers are waiting for, and it is
settled by measuring these against each other on your own questions.

| | mechanism | cost | reach | what it makes observable |
|---|---|---|---|---|
| `ranked` | the ranked head of each face, nothing judging the cut but the retrieval score | one model call, the smallest prompt of the three | what the final caps hold | the candidate counts beside the final ones — evidence retrieved below the cut is evidence the answer never saw |
| `select` | one structured call returns coordinates; the framework validates them, unions a ranked safety head, enforces the final caps and follows chosen claims back to source | two model calls, serial — the selection latency adds rather than overlaps; on timeout it falls back to the exact `ranked` context and marks the answer degraded | the broad pools, narrowed deliberately | how many items the model itself chose before the safety anchors: near zero against a large final ledger says the serial call is not doing the work |
| `all` | no selection at all — the pool `select` would have judged goes to the answer whole, trimmed only by `all_context_chars` | one model call, a much longer prompt, paid in input tokens and in the answer model's attention | the broad pools entire, `claim_candidate_cap` and every retrieved window | what the ceiling dropped, stated in the answer's telemetry |
| `answer_format: structured` | answer text, answer kind and citations travel as separate schema fields, and the cited spans are validated | no extra call | independent of the strategy | a citation ledger that can be checked apart from the prose; `answer_text` for automation, `answer` for a reader |
| `all` + `answer_format: structured` | the pair turns on `deliberation` by itself | a bounded field written before the answer, in the same call | — | which handed-over items bore on the question and which were dismissed, in the model's own words |

And for the caps, one rule: **raise a candidate cap when the fact is missing from the pool,
raise a final cap when the pool has it and the context drops it.** Under `all`, the number
that widens the claim pool is `claim_candidate_cap`, not `claim_cap`, and the window face is
already unbounded — so the knob that matters there is `all_context_chars`, which is what
decides how much of it survives.

Nothing here changes a default. The framework ships `evidence_strategy: ranked` and
`answer_format: text`, a generated engine writes the same, and the OPC example keeps
`select` as its default — `all` with `deliberation` is a deliberate
choice for a workload, not a new baseline. Both settings can also be overridden for a single
question (`evidence_strategy` / `answer_format` in the recall request body, or
`--evidence-strategy` / `--answer-format` on a generated project's CLI), which is the cheapest
way to compare them on your own material before changing anything.
