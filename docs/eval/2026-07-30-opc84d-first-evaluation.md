# First evaluation — the shipped preset, and a live run of current `main`

Date: 2026-07-30 · Evaluator: `packages/pneuma-knowledge-eval` · Groups: A–F

## What this report contains

| | track (a) | track (b) |
| --- | --- | --- |
| artifact | the preset bundle shipped in this repository, `examples/data/preset/u-opc-lin` | a live compile of the accepted 84-day v2 corpus on current `main` |
| compiled | 2026-07-28 19:27–19:30, on tree `344e226` | 2026-07-30 06:36–08:16, on the working tree described below |
| compile contract | skill base **v1**, zero contract rules | per-user composed base **v3** + schema packs — the current default |
| corpus | `examples/data/opc-demo` (Orion client pilot, 11 sources) | `docs/experiments/opc-84d-v2/accepted` (Seamlog, 84 days, 28 groups, 190 sources) |
| mode | `mechanical` | `mechanical` **and** `full` (embedding matcher + LLM judge + live recall QA) |
| groups with numbers | A, C, D, E | A, B, C, D, E, F |

Track (a) is the earlier draft. It is kept, in full, as the appendix: it is the only evidence
about the shipped artifact, and the gate it was produced under no longer exists. Track (b) is
new and answers the three questions track (a) left open.

**The headline is not in any single group.** On every structural metric the current contract is
better than the shipped artifact — links exist, growth is sublinear, duplication and verbatim
leakage are down threefold. And the two groups that were supposed to measure *judgement*
(B admission, F usability) turned out to be measuring their own matcher: group B reports
**0/7 recall** while group F answers **5–6 of 6** questions about those same seven facts, and every
one of F's 9 checks was decided by the judge rather than the mechanical arm. Sections
[*B*](#b--admission-judgement) and [*The measurement problem*](#the-measurement-problem) are the
part of this report worth reading first.

---

## Corpus identity: there are three "84-day corpora", and only one can be compiled

The evaluation plan named `examples/data/opc-84d` as the dataset. Track (a) corrected one
assumption (the shipped preset is not that corpus). Track (b) turned up a second, larger one,
and it changes what group B is able to measure.

| | v1 generated (`examples/data/opc-84d`) | v2 accepted (`docs/experiments/opc-84d-v2`) |
| --- | --- | --- |
| story | RelayForge, key `opc-84d-relayforge` | Seamlog / 竹影工作室, key `opc-84d-v2` |
| how it was made | `examples/generate_opc_84d.py`, seeded generator | authored per group, then QA-gated and byte-accepted |
| intake axis | 12 weekly batches (`index.json`) | 28 three-day groups G01–G28 |
| size | 98 normalized units, 2,280 atoms, 213,726 chars | 104 contracts → 190 normalized units, 1,292 blocks, 140,185 chars |
| labels | 120 truth entries, 36 negative controls, 12 supersessions, 36 retrieval cases | **7** truth entries, **5** negative controls, **0** supersessions, **6** retrieval cases |
| importer on current `main` | **none** | `examples/run_opc_84d_experiment.py` |

`examples/run_opc_84d_experiment.py` — the only batch-wise importer in the repository, and the
one the task names — builds its dataset from `build_accepted_opc_84d_v2_dataset`, i.e. the **v2
accepted** corpus. Its docstring says so, and its scripted branch notes that "accepted v2
sources carry evidence links rather than the old synthetic truth manifest". The v1 corpus is
still on disk with its 120-entry manifest, but nothing on current `main` imports it as batches;
`examples/import_source.py` would take its 98 contracts one at a time, with no batch axis and no
per-batch drain.

Consequences, stated up front because they bound every group-B number below:

- **Group B runs against 7 labelled statements and 5 negative controls, not 120 and 36.** That
  can say whether a labelled fact is expressible in canonical. It cannot carry a recall *rate*
  anyone should quote as a system property.
- **Admission latency is `unavailable`** — the v2 truth asset is a frozen label file with no
  intake windows, so there is no round axis to measure a lag against. A per-fact first-match
  round is reported instead: the same evidence without an invented denominator.
- **Supersession correctness is `unavailable`** — v2 declares no supersessions while v1 declares
  12. This is the largest labelling gap in the repository: supersession handling is a headline
  claim of the design and track (b) cannot test it at all.

### Control: what a wrong corpus actually looks like

To calibrate the above, the v1 RelayForge labels were also scored against the v2 Seamlog
canonical (`docs/eval/artifacts/track-b-control-mismatched-corpus/`). Result: **head recall
0.0 over 120 entries, 0 unguarded leaks over 36 negative controls, 0/12 supersessions correct,
108 of 108 current facts never admitted.** The cross-corpus false-positive floor is exactly
zero — there are no accidental matches. That both validates the `--require-corpus` guard and
sharpens the question in group B, where the *right* corpus also scored 0.0.

---

## Track (b): how the run was produced

```
uv run python examples/run_opc_84d_experiment.py --mode real \
    --user u-opc-seamlog-v2-trackb-20260730 --until-batch 28
```

- **Stack**: the framework's own development stack (`pneuma-knowledge-compiler-{postgres,qdrant,meilisearch}`,
  ports 15432 / 16333 / 17700), a fresh tenant, canonical at
  `data/canonical/u-opc-seamlog-v2-trackb-20260730`. L2 went to its own 1536-dim collection
  (`pneuma_knowledge_chunks_84dv2_real_1536`), because a collection has one fixed vector dim.
- **Models**: all roles on real OpenRouter models, recorded as `openrouter:configured` for the
  same reason the runner's own `_public_model_label` does it — public run evidence should be
  useful without publishing private model routing. Compile / recall / live-context share one
  model; deep recall and schema evolve get a stronger one; embeddings are
  `openrouter:openai/text-embedding-3-small` (1536-dim). `--mode real` fails closed unless every
  role resolves to a real provider. All calls traced to the local Langfuse project.
- **Contract**: one deliberate deviation from the shipped runner, made in the run wrapper rather
  than by editing the repository. `run_opc_84d_experiment.py` passes `load_builtin_skill()` into
  `drain_user`, and that loader defaults to skill base **v1**, which carries zero contract rules.
  The current default is `user_schema_base_version = "v3"` composed with per-user schema packs,
  and that is what the production worker resolves — the compile worker passes `skill=None`
  precisely so that "each job loads its user's own composed skill"
  (`workers/compile_worker.py:457`). Track (b) is a statement about current `main`, so it took
  the production path. All 170 commits carry `Skill-Version: v3` and one `Skill-Content-Hash`,
  so there is no version confound inside the trajectory.
- **`evolve_auto_trigger` is off**, as in the shipped runner. Group E therefore has a pressure
  series and no evolve response to score. That is a scope limit, not a result, and it matters for
  reading E's verdict below.

### The run record, including the two attempts that failed

Track (b) took three attempts. Both failures were infrastructure, not the compiler, and each
exposed a different missing guard. The second is the more interesting finding.

**Attempt 1 — aborted at batch 10.** Kept in `docs/eval/artifacts/aborted-run-2026-07-30T0559/`.
G01–G09 clean; G10 finished with **6 of 16 jobs failed** and the runner failed closed:
`RuntimeError: G10 has 6 failed or unfinished jobs`. Cause: this machine's TUN proxy publishes a
synthetic `198.18.0.0/15` DNS answer for `openrouter.ai` and its route for that host went down
mid-run, so every embedding call failed (`OpenRouter embeddings failed after 3 tries`) and a
compile job whose L2 step cannot embed is a failed job. At the same moment a direct connection to
the real Cloudflare address answered 200 while the TUN path and both local HTTP proxies returned
nothing. Fixed by taking `openrouter.ai` out of the proxy path — `NO_PROXY` plus the
`PNEUMA_KNOWLEDGE_OPENROUTER_RESOLVE_IP` escape hatch `examples/_bootstrap.py` already documents
for exactly this failure (hostname and TLS SNI unchanged, `getaddrinfo` redirected in-process,
no system DNS or `/etc/hosts` edit).

**Attempt 2 — hung indefinitely inside batch 8.** G01–G07 completed cleanly (47 sources, 94 jobs,
0 failed, 83 claims). Then one compile job sat idle for **25+ minutes** with two open HTTPS
connections and the main thread parked in `kevent`: no error, no progress, no timeout. Two gaps
combine to make that unrecoverable rather than merely slow.

1. **There is no request timeout on the chat path, and no way to configure one.**
   `wiring._build_from_name` builds the OpenRouter model with `init_chat_model(...)` passing
   neither `timeout` nor `max_retries`, and `Settings` has no field for either. The embeddings
   adapter, by contrast, pins `_TIMEOUT = 60.0` / `_RETRIES = 3` and even documents provider
   latency variance. So the layer already known to stall is guarded and the layer running the
   expensive multi-round tool loop is not.
2. **The experiment runner never performs the worker's own startup self-heal.** It calls
   `drain_user` directly, so `store.requeue_claimed_jobs()` never runs — the method the compile
   worker invokes on startup because "a 'claimed' row means a worker died mid-job (e.g. killed
   during a long LLM call), which otherwise blocks that user's queue forever". After the hung
   process was killed the tenant held exactly one orphaned `claimed` job, and since
   `_batch_failures` counts any unresolved job intersecting the current batch, batch 8 became
   permanently unrunnable in that tenant. The only shipped recovery is `--reset-user`: discard
   seven good batches to recover one job.

**Attempt 3 — the run this report evaluates.** Recovery, in order: a 300s timeout with 2 retries
on the chat model, supplied by the run wrapper; the orphaned `claimed` row returned to `queued`
(the identical statement `requeue_claimed_jobs()` runs, narrowed to this tenant — the global form
would also rewrite ~70 abandoned `u-it-*` test tenants' rows on the shared stack); resume with
`--from-batch 8`, which re-ingested G08's contracts (all deduplicated by checksum, `+0 sources`)
and drained the requeued job. G08 closed in 24 seconds.

**A third failure, inside attempt 3.** Batch 21 lost one compile job to the same route flap:
`worker error: OpenRouter embeddings failed after 3 tries`. The adapter's whole retry budget is
`sleep(0.5 * (attempt + 1))` over 3 attempts — **~1.5 seconds of backoff** — which no transient
route failure respects. Recovery used the framework's own surface rather than a workaround:
`store.undigested_source_ids()` returned exactly the one casualty, which is precisely what
`POST /v1/users/{id}/compile` acts on and is documented as idempotent. A **new** job was enqueued
for it and drained; the failed job stays failed in the ledger, because canonical history is
append-only and nothing was rewritten. The retry budget was then widened to ~14 seconds for the
remainder of the run. Batches 22–28 completed with no new failures.

So the evaluated trajectory is continuous — batches 1–7 from attempt 2, 8–28 from attempt 3, one
tenant, one canonical repository, one skill version, no gap, no re-compiled source. Audit trail:
`opc84dv2-trackb-run.json`, `opc84dv2-trackb-run-resume.json`, `opc84dv2-trackb-run-resume2.json`.

Three things are worth keeping. **Fail-closed worked**: attempt 1 stopped at the first batch it
could not complete instead of emitting 18 more batches whose L2 layer was silently missing.
**Fail-closed is not enough**: attempt 2 did not fail, it stopped existing, and no between-batch
check can catch that. And **both failures were invisible from the compile output** — the model
kept answering while the embedding provider was gone; the socket stayed open while nothing
arrived.

### Run statistics

| | |
| --- | --- |
| batches executed | **28 / 28** (G01–G28) |
| batch wall time | 3,875.6 s (64.6 min), excluding the two failed attempts |
| source contracts ingested | 104 → **190** normalized source units (9 deduplicated) |
| L0 | 1,292 blocks, 132,290 chars reachable from canonical citations |
| jobs | **381** (190 compile + 190 index + 1 retry); 380 ok, **1** historical failure (G21, transient embeddings) |
| projection syncs | 189 (471 claim upserts, 0 deletes) |
| canonical at head | **170 commits**, 8 documents, 328 claims, 170 snapshots |
| indexes at head | Qdrant 319 chunks + 328 claim vectors (1536-dim); Meili 1,292 blocks + 328 claims |

---

## Track (b): the batch axis

Per-group, and aggregated to the 12 calendar weeks the evaluation plan asked for. Counts are
cumulative at the end of each batch; `claims` is the canonical-claim projection.

| week | groups | new sources | new claims | sources | docs | claims | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| W01 | G01–G03 | 21 | 34 | 21 | 3 | 34 | 470 |
| W02 | G04–G05 | 12 | 24 | 33 | 5 | 58 | 255 |
| W03 | G06–G07 | 14 | 25 | 47 | 6 | 83 | 332 |
| W04 | G08–G10 | 16 | 27 | 72 | 6 | 122 | 359 |
| W05 | G11–G12 | 15 | 21 | 87 | 6 | 143 | 305 |
| W06 | G13–G14 | 13 | 29 | 100 | 6 | 172 | 279 |
| W07 | G15–G17 | 26 | 39 | 126 | 8 | 211 | 504 |
| W08 | G18–G19 | 12 | 21 | 138 | 8 | 232 | 295 |
| W09 | G20–G21 | 11 | 27 | 149 | 8 | 259 | 246 |
| W10 | G22–G24 | 22 | 46 | 171 | 8 | 306 | 454 |
| W11 | G25–G26 | 11 | 14 | 182 | 8 | 320 | 203 |
| W12 | G27–G28 | 8 | 8 | 190 | 8 | 328 | 172 |

The full 28-group table is in the run reports. Two things are visible from the week view alone:
**the document count stops moving at G16** (8 documents; weeks 7 through 12 add 117 claims and
zero documents), and **claim intake decays in the last three weeks** (46 → 14 → 8) while source
intake decays more slowly (22 → 11 → 8).

Because one compile job is one commit, the checkpoint axis has 170 rounds. Sampled every 17th:

| round | claims | cited | citations | resolvable | residue | prose | L0 | ratio | chars/claim | docs | edges | isolated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| r18 | 34 | 34 | 51 | 51 | 0 | 10,931 | 13,376 | 0.8172 | 321.5 | 3 | 1 | 1 |
| r35 | 73 | 73 | 115 | 115 | 0 | 17,512 | 25,746 | 0.6802 | 239.9 | 6 | 3 | 3 |
| r52 | 99 | 99 | 164 | 164 | 0 | 21,469 | 36,774 | 0.5838 | 216.9 | 6 | 3 | 3 |
| r69 | 123 | 123 | 206 | 206 | 0 | 25,254 | 48,760 | 0.5179 | 205.3 | 6 | 3 | 3 |
| r86 | 163 | 162 | 262 | 262 | **3** | 30,752 | 64,329 | 0.4780 | 188.7 | 6 | 4 | 3 |
| r103 | 205 | 204 | 308 | 308 | 3 | 37,382 | 75,145 | 0.4975 | 182.4 | 8 | 5 | 3 |
| r120 | 229 | 228 | 344 | 344 | 3 | 40,986 | 87,761 | 0.4670 | 179.0 | 8 | 6 | 3 |
| r137 | 269 | 268 | 402 | 402 | 3 | 46,600 | 103,931 | 0.4484 | 173.2 | 8 | 7 | 3 |
| r154 | 309 | 308 | 458 | 458 | 3 | 52,470 | 117,635 | 0.4460 | 169.8 | 8 | 7 | 3 |
| r170 | 328 | 327 | 484 | 484 | **4** | 55,705 | 132,290 | 0.4211 | 169.8 | 8 | 8 | 3 |

---

## A · grounded — provenance honesty

- **Claim citation coverage at head: 327 / 328 (0.9970).** One claim carries no provenance.
- **Citation replay: 484 / 484 locators resolve** to a real source with an in-bounds ¶ interval.
  0 unknown sources, 0 out-of-range intervals, at every one of the 170 checkpoints.
- **Anchor continuity: 0 anchors vanished** repo-wide across all 169 transitions; anchor floor
  monotone (0 → 328); 0 documents dropped.
- **Links: 56 markdown links at head, 0 dead, 0 self-referential.** Compare track (a): zero
  links of any kind.
- **Unparsable citation-like markers: 4 — a new failure mode, and the one genuinely new defect
  this group found.**

**Reading.** The provenance backbone holds at ten times the shipped bundle's scale: 484
locators, every one replayable, across 170 commits. That is the strongest single result in the
report, and it is a mechanism result — the gate rejects an illegal locator, so the interesting
question was only ever whether the model would find a way to write something the gate does not
inspect. It did.

**The 4 unparsable markers are anchor references written in citation syntax:**

```
work/operations/demo-material-intake.md → [cite: c:519ccb24]
work/operations/demo-material-intake.md → [cite: c:9715400e]
work/products/seamlog.md               → [cite: c:9715400e]
work/products/seamlog.md               → [cite: c:270160f1]
```

`c:519ccb24` is an *anchor* — another canonical claim — not a source locator. The contract asks
for exactly this relation: v3 §8 says "every claim must link back to this round's source **or to
existing canonical**", and gate rule 3c accepts "a reference to a base anchor". But the only
syntax the gate parses inside `[cite: …]` is `<32 hex> ¶N`, so an anchor written there matches
neither the citation grammar nor the anchor-comment grammar. The gate does not reject it, group A
cannot resolve it, and a reader sees provenance that leads nowhere. It is the same class of defect
as the fullwidth `【cite: …】` variant seen on an earlier real-model run, where the gate's
`CITATION_RE` did not match and the claims were recorded with zero citations: **text that looks
like a citation but resolves to nothing is worse than no citation**, because it suppresses the
question. It appeared at r86 and survived to head; it is not a transient.

**The single uncited claim** is in `work/operations/demo-material-intake.md`. Unlike track (a)'s
uncited claim, this one was written *under* rule 3c — so either it reached the gate by a path 3c
does not cover, or 3c's base-anchor escape accepted it, and the four markers above suggest which.
Worth one focused investigation; it is 1 of 328, and it is the kind of 1 that indicates a rule
with a seam in it.

---

## B · admission judgement

Truth set: `opc-84d-v2` — **7** entries (all current), **5** negative controls, 0 supersessions,
0 declared intake batches. Matcher: `max(char_similarity, cosine)` over
`openai/text-embedding-3-small`, threshold **0.72**.

| metric | value |
| --- | --- |
| head recall | **0.0** (0 / 7) |
| peak recall over 170 checkpoints | **0.0** |
| first-match round, per entry | `null` for all 7 |
| negative controls: unguarded leaks at head | **0** of 5 |
| negative controls: guarded mentions | 0 |
| labelled detail leakage | 0 of 5 present |
| admission latency | `unavailable` — corpus declares no intake windows |
| supersession correctness | `unavailable` — corpus declares no supersessions |

Zero of seven, at every checkpoint. Before reading that as an admission catastrophe, here are the
best matches the matcher actually found, with their scores against the 0.72 threshold:

| truth id | score | the labelled statement | the best-matching canonical claim (truncated) |
| --- | --- | --- | --- |
| `v2-f-d78-second-chain` | 0.694 | 第二条材料替代链已有自己的来源和确认；两条链不合成总通过标记。 | 【firm】2026-04-22，陈放继续核对材料替代链；林舟明确该链只能说明材料之间的关联，不能替代缺失的一次现场确认，也不能作为试点已验收的证据。采购材料与使用核对必须保持分开… |
| `v2-x-d84-open` | 0.638 | 附录仍待签，删除确认未完成，尾款仍没有付款结果。 | 【forming】截至2026-05-24，删除演练的业务确认仍未完成：吴岚尚未签附录、完成删除确认或提供尾款日期… |
| `v2-f-d84-focus` | 0.620 | 下一周期只聚焦小型设计团队的变更证据链。 | 【forming】下一周期的新工作卡只问一条记录如何回到来源、确认和状态，并以此检查小型设计团队的变更证据链… |
| `v2-d-d82-stop-platform` | 0.618 | 停止全项目平台方向，供应商审批模块延后。 | 【firm】云麓当前试点不把供应商审批纳入默认组成…供应商审批继续延后；重新提出前须独立写清范围、使用者和成本理由… |
| `v2-d-d84-no-contract` | 0.609 | 六周延长仍是带条件的口头意向，尚未生效，并非长期合同。 | 【forming】截至2026-05-24，云麓相关事项仍不能写成成交、签字或付款完成…吴岚明确表示该回复不构成同意延长，因此六周口头意向尚未生效。 |
| `v2-f-d29-start` | 0.604 | 3月30日，四个分别标名的只读副本进入观察；这不等于资料已验证。 | 【firm】2026-03-30，本轮批次已将会议、项目沟通、邮件和每日笔记四类副本分别放入只读观察队列…不把该状态写成内容正确、验收或“首日顺利”。 |
| `v2-c-d80-conditions` | 0.503 | 删除处理证明草案只保留请求到达、范围核对和处理结果三个阶段… | 【firm】删除处理证明草案只保留请求到达、范围核对和处理结果三个阶段；最小字段包括请求标识、项目代号… |

**Reading — and this is a judgement stated explicitly, not a metric.** Read the pairs. Every one
of the seven best matches expresses the labelled fact, several of them *better* than the label
does: the relative date normalized to an absolute one, the enumeration spelled out, and the "this
does not mean it was verified / agreed / paid" hedge stated more precisely than the label states
it. `v2-c-d80-conditions` at 0.503 opens with the label's own first clause almost verbatim and
then continues for another 90 characters. Nothing here looks like a fact the compiler failed to
admit. Every one looks like a fact the compiler admitted and then elaborated.

The scores cluster at 0.50–0.69 against a 0.72 threshold, and the mechanism is structural: the
labels average ~30 characters, the v3-contract claims average **170** (group C), so a claim that
correctly restates a short label as a longer, hedged, date-normalized sentence loses on character
containment *and* dilutes the cosine. `char_similarity` returns 1.0 on containment, which is why
this worked for track (a)'s terser claims — but the current contract paraphrases rather than
contains, by design.

So group B's honest output is **not** "recall is 0". It is: *the matcher and threshold inherited
from the existing live evaluator cannot recognize admission under the current compile contract,
and 0/7 is what that failure looks like.* The cross-corpus control scored 0.0 too — but with best
matches nowhere near threshold, whereas these seven sit just under it. A metric that reports the
same number for "wrong corpus entirely" and "right corpus, admitted and elaborated" is not
discriminating, and the fix is calibration, not a better compiler. Group F is the independent
check that settles it.

**What is trustworthy in this group:** the negative-control result. **0 unguarded leaks of 5
labelled exhaust statements at head, and 0 at every checkpoint**, plus 0 of 5 labelled details
present. The negatives are things that must *not* appear ("试点尾款已经到账" — the pilot's final
payment has arrived), and absence is exactly what character matching *can* establish reliably: a
false negative would require the compiler to have written the forbidden statement in words sharing
no long substring with it. That result is real, on a 5-item set.

### `noise_support` — admission over-inclusion, against the corpus's own labels

Because the 7-entry truth asset is too small to say much, group B gained a second noise metric
that consumes a far larger label set. The v2 accepted corpus labels **every authored unit** with
`authorship.content_class ∈ {signal, noise, ambiguous}` *before* compilation, and the loader
recovers **1,513 labelled texts** from it. `noise_support` resolves each claim's citations to ¶
blocks, each ¶ block to its label, and asks what the claim's evidence was called before anything
was compiled. Bound with `--content-classes docs/experiments/opc-84d-v2/accepted`.

| | at head (r170) |
| --- | --- |
| claims judged (citations resolve) | 327 of 328 |
| claims citing **any** noise-labelled block | 27 |
| claims resting **only** on noise-labelled blocks | **14 — rate 0.0428** |
| claims with at least one unmatched block | 17 |
| cited block class totals | 825 signal, 156 ambiguous, 35 noise, 33 unmatched |

Two deliberate conservatisms, because this metric is easy to inflate. A ¶ block whose text matches
no authored label counts as `unmatched` and is never treated as signal — and it also
**disqualifies** its claim from `noise_only`, since "we could not find this block's label" is not
evidence that the block was exhaust. And a claim that threads a noise block *together with* real
evidence is doing its job, so only claims whose entire basis is exhaust are counted. (The first
version of this measurement, written as an ad-hoc script before promotion, got the second rule
right and the first one wrong; the unit test that caught it is why the number below can be
trusted. The headline 14 happens to be unchanged, because none of the 14 also cites an unmatched
block.)

Where those 14 claims live is the finding: `work/operations/vehicle-maintenance.md` (10),
`work/operations/household-rice-subscription.md` (2), `memory/topics/camera-purchase.md` (1),
`work/operations/demo-material-intake.md` (1). **Four of the eight documents at head are
household admin** — a car service, a rice-delivery subscription, a camera purchase, a
subscription cleanup — and the compiler filed three of them under `work/operations`, a family the
v3 skill defines as "releases, sales, cash flow and operational matters". The skill's §1 is
explicit that "short-lived detail" does not enter long-term knowledge, and its counter-example is
a one-off personal state. A rice delivery with a Wednesday-noon reschedule deadline is that
counter-example.

This matters beyond tidiness, and there is direct evidence. During an interim check, a group-F
question about whether the six-week extension could take effect came back:

> There is no relevant record confirming that a **verbal six-week extension** can take effect.
> **If this refers to the rice subscription**, the available record only says that a late check
> does not automatically defer…

Admitted household noise does not sit inertly in a corner of canonical; it competes for retrieval
against the questions the system exists to answer. The 5-item negative-control set reports 0 leaks
and is right to — none of these documents restates a labelled negative. The corpus's own
pre-compilation labels catch what the negative controls structurally cannot: material that is
genuinely low-value and that nobody thought to write down as a forbidden statement.

---

## C · layering — thread layer or second copy

| | track (b) at head |
| --- | --- |
| compression ratio (prose / L0), first → head | **1.0914 → 0.4211** |
| trend | **−0.6703** |
| prose chars / markup chars | 55,705 / 27,676 (markup = 33.2% of the artifact) |
| prose chars per claim | **169.8** |
| near-duplicate clusters | 3 (2 of them cross-document) |
| duplicate row rate | 0.0091 |
| verbatim transcription rate | 0.0061 (2 of 327 supported claims) |
| longest verbatim run | 58 chars |
| labelled detail leakage | 0 of 5 present |
| language consistency with L0 | **0.6646** — 218 consistent, **38 diverged**, 72 mixed |

**Reading.** The compression curve is the mirror image of track (a)'s. It **starts above 1.0** —
in the first rounds canonical was *larger* than the material it compiled — and then falls
monotonically to 0.42, i.e. by head the thread layer is 42% of the size of the evidence it
threads. Track (a) rose 0.61 → 0.83 over 11 rounds; track (b) falls 1.09 → 0.42 over 170.
Direction is the comparable part (the corpora differ), and the direction reverses.

Both ends of that curve are informative. The falling trend means the compiler is **threading, not
transcribing**: as canonical accumulates, new material is increasingly absorbed into existing
claims rather than added as new prose. The >1.0 start means it has **no economy at small scale** —
the first few sources produce a document longer than themselves, because the v3 contract's
apparatus (strength labels, absolute-date normalization, explicit hedges, evidence tiering) has a
fixed cost per claim that only pays off once there is something to thread against. For a new user
whose knowledge base is three sources old, canonical is a longer read than the raw material.

**Claim size is the other big contract change: 170 prose chars per claim, against track (a)'s
flat ~69.** Claims are 2.5× longer, and the series shows them *shrinking* toward that value from
321 at r18 — so the compiler starts verbose and converges. Longer claims are not obviously worse:
reading the samples in group B, the extra length carries the hedge and the normalized date, which
is exactly what the contract asks for. But it is the direct cause of group B's measurement
failure, and it is a real cost at retrieval time — 170-character claims fill a recall context
window 2.5× faster.

Duplication and verbatim leakage are both down roughly threefold as rates (0.026 → 0.009;
0.027 → 0.006) on a corpus four times the size. The 2 cross-document duplicate clusters are the
same structural pattern track (a) found — a fact asserted by two families with no link between
them — and are discussed under E.

### `language_consistency` — canonical drifted off the language of its evidence

The corpus is Chinese: of 1,292 L0 blocks, 1,172 read as CJK and 120 as mixed, none as Latin. The
compile contract and skill body became English in `6e9fcd8`. Canonical came out in between.

| | track (a) | track (b) |
| --- | --- | --- |
| corpus language (from L0) | `cjk` | `cjk` |
| claims consistent with it | 56 of 76 | 218 of 328 |
| claims **diverged** (wholly the other script) | **0** | **38** |
| claims mixed (real weight in both) | 20 | 72 |
| consistency rate | 0.7368 | **0.6646** |

**This is a regression introduced with the current contract, and the comparison is what makes it
legible.** Track (a), compiled under skill base v1 when the contract prose was Chinese, wrote
**zero** claims wholly in the wrong language — its 20 "mixed" claims are Chinese sentences carrying
English identifiers, which is unavoidable in any corpus. Track (b) wrote 38 claims wholly in
English about Chinese evidence, and 72 genuinely bilingual ones.

The distribution is not random, and the series makes the mechanism plain: **rounds r02 through r11
are 100% diverged — consistency rate 0.0, twenty-three consecutive claims, every one of them in
English.** The first claim in the corpus language appears at r12, after which the rate climbs
steadily as accumulated Chinese canonical starts supplying the context the contract prose does not.
Divergence peaks at 39 claims (r102) and ends at 38, so exactly one English claim was ever brought
back into the corpus language. `work/products/seamlog.md` holds 24 of the final 38; the rest are
spread one to three per document across six others.

In other words the compiler takes its output language from whatever is in front of it, and at the
start of a knowledge base the only thing in front of it is an English contract. This is the same
cold-start shape as the compression ratio starting above 1.0: both are defects of the empty
knowledge base, not of the compiler at scale — and both land permanently in an append-only
artifact.

Why this is a layering defect and not a cosmetic one. Canonical is the thread layer over evidence
that is never rewritten, and the contract requires exact wording to be kept apart from
interpretation — so a claim in another language is a translation presented as a thread, and the
reader can no longer tell which words were the speaker's. It also silently breaks every
character-level measurement downstream: a Chinese truth label cannot contain-match an English
claim, so **the 38 diverged claims are invisible to group B by construction**, and paraphrase-level
duplicates spanning the two scripts are invisible to group C's own duplicate check.

---

## D · navigability — the two jobs canonical exists to do

| | track (a) | track (b) |
| --- | --- | --- |
| documents at head | 9 | 8 |
| link edges at head | **0** | **8** (56 markdown links) |
| hub documents present (`memory/profile.md`) | 1 | **0** |
| reachable-document rate from hub | 0.1111 | **0.0** |
| isolated documents | 9 | 3 (of 8) |
| orphan claims | 70 / 76 (0.921) | **328 / 328 (1.0)** |
| canonical growth exponent | 1.7477 | **0.7801** |
| claim growth exponent | 1.8210 | **0.9582** |
| sublinear | **no** | **yes** |
| aggregation rate | 0.5556 | **0.75** |
| dated-slug documents | 0 | 0 |
| families in use / available | 6 / 7 | **3 / 7** |
| normalized family entropy | 0.7846 | **0.4546** |
| claims in unowned paths | 0 | 0 |

**Reading. The single highest-value thing track (a) asked track (b) to measure has a clear
answer: the compiler now links.** Track (a) found 0 inter-document edges across 11 checkpoints
and called the follow-the-thread job absent. Track (b) has 56 markdown links resolving to 8
distinct inter-document edges, **0 dead and 0 self-referential**, appearing from r18 and growing
monotonically. The rebuilt compile prompt instructs it explicitly ("a relation must be written as
a markdown link `[subject name](relative/path)`" plus the dead-link prohibition), and the
instruction took. That is a genuine mechanism win.

**And the bird's-eye job improved even more.** The growth exponent falls from 1.75 to **0.78** —
superlinear to genuinely sublinear, over a trajectory with a real lever arm this time (L0 grows
from 13k to 132k chars, a 10× span, against track (a)'s 45%). Claim count grows at 0.96,
essentially linear in material. With an aggregation rate of 0.75 and zero dated slugs, subject
aggregation is working better than in the shipped bundle.

**But `memory/profile.md` was never created, so the hub does not exist, and the reachable-document
rate is 0.0 — worse than track (a)'s 0.111.** All 328 claims are orphans by this metric, not
because nothing is linked but because there is no declared entry point to walk from. The graph has
edges; it has no front door. Track (a) had a hub with 6 claims and nothing leaving it; track (b)
has a connected component with no hub in it. Both fail the same job for opposite reasons, and the
metric's asymmetry is worth stating plainly: **an artifact can improve on every edge-level measure
and still score 0 on reachability, because reachability is measured from a fixed family the
compiler is never obliged to populate.** The v3 skill lists `memory/profile.md` for "owner
profile, long-term preferences and way of working", and §8 warns that the registration profile
"cannot be the source of a claim" — a compiler reading those two rules together may reasonably
conclude it has nothing to put there. That is a contract gap, not a model failure.

**Family concentration is the other regression.** 3 of 7 families in use against track (a)'s 6,
normalized entropy 0.45 against 0.78, and the distribution is severe: `work/operations` 203
claims, `work/products` 92, `memory/topics` 33, and **zero** in `memory/people`,
`work/experiments`, `memory/profile`, `materials`. One document,
`work/operations/demo-material-intake.md`, holds 176 anchors and 40,539 characters — **49% of the
entire artifact**. The 84-day story has five recurring people and a run of explicit experiments;
neither got a home. Track (a), on a corpus one quarter the size, populated `memory/people` with 18
claims and `work/experiments` with 5.

An interim observation worth recording, because it bears on how much any filing number should be
trusted: **attempt 1 of this run, on the same corpus prefix under the same contract, did create
`memory/people/{jia-ning,wu-lan,chen-fang,sun-qiu}.md`.** Attempt 3 created none. Same contract,
same model, same material, materially different filing decisions. Structural metrics like family
entropy and aggregation rate therefore carry run-to-run sampling variance that a single run cannot
separate from a systematic property, and this report has exactly one run of each track. Directions
supported by a mechanism change (links, growth exponent) are safe to read; family-distribution
numbers are one sample.

---

## E · evolution — misfit pressure and response

| | track (a) | track (b) |
| --- | --- | --- |
| rounds under catch-all pressure | 1 / 11 | **19 / 170** |
| longest consecutive run | 1 | **5** (r112–r116, plus r110, r118) |
| mean catch-all share | 0.0909 | 0.1266 |
| sustained pressure (≥3 consecutive) | no | **yes** |
| evolve events | none | none |
| verdict | `aligned_restraint` | **`missed_pressure`** |
| cross-family duplicate clusters at head | 1 | 2 |
| move fidelity | `no_moves_observed` | `no_moves_observed` |
| family floor / anchor floor monotone | yes / yes | yes / yes |

**Reading, with the scope limit first because it determines how much the verdict is worth.**
`evolve_auto_trigger` was **off** for this run, as it is in the shipped experiment runner. The
passive trigger that would have fired schema evolve could not fire. So `missed_pressure` is
*arithmetically* correct — sustained catch-all pressure with no schema response — but it is not
evidence that the compiler ignored pressure. It is evidence that **nobody was listening, because
the listener was disabled.** Reporting it as a compiler failure would be dishonest; reporting it
as nothing would waste the one real signal here.

The real signal is the pressure series itself, and it is stronger than track (a)'s. 19 rounds
under pressure with a 5-round consecutive run around r110–r118 is a different regime from one
isolated round. `memory/topics/` accumulated 33 claims — 10% of the artifact — in a family the
skill defines as "cross-domain topics not yet stably classified", and the two documents there are
`yunlu.md` (32 claims, the client) and `camera-purchase.md` (1). A client with 32 claims parked in
the not-yet-classified family, while `memory/people` sits empty, is exactly the shape misfit
pressure is supposed to have. **Whether schema evolve would have responded correctly to it is the
most valuable thing a follow-up run can measure, and it needs one flag flipped.**

Both monotone floors hold: no family ever removed, no anchor floor regression, 0 churn events
across 170 rounds. The 2 cross-family duplicate clusters straddle `work/operations` and
`work/products` — the same boundary track (a) found with 1 cluster, which makes this the second
independent observation that a product's delivery/intake state has two plausible owners under this
schema.

---

## F · usability QA — can the structure answer the question

Asked over the **live recall path** of a running service against the same tenant, using the
corpus's own 6 human-reviewed retrieval cases (`--answer-url`, judge on the same stronger
configured model as deep recall). Scoring: normalized character containment at threshold 0.62
first, judge consulted only for checks the mechanical arm has already failed.

The suite was run three times in total (the fast arm twice, once before and once after the two new
metrics landed, and the deep arm once), which turned out to matter.

| | fast, run 1 | fast, run 2 | deep |
| --- | --- | --- | --- |
| cases correct | 5 / 6 (0.8333) | **6 / 6 (1.0)** | 5 / 6 (0.8333) |
| durable_facts | 2 / 2 | 2 / 2 | 2 / 2 |
| commitments | 1 / 1 | 1 / 1 | 1 / 1 |
| constraints | 1 / 1 | 1 / 1 | 1 / 1 |
| mixed | 1 / 2 | **2 / 2** | 1 / 2 |
| checks passed by the mechanical arm | **0 / 9** | **0 / 9** | **0 / 9** |
| checks decided by the judge | 9 | 9 | 9 |

**Reading. Three findings, and the last two undercut the first.**

First: **the structure answers the questions.** 5 or 6 of 6, including all four single-category
cases in every run, against a corpus of 190 sources and 132k characters, with the answers carrying
the labelled facts. This directly refutes group B's 0/7 — the same seven facts group B could not
match in claim text are recoverable through the system, in the right form, in answer to
human-written questions. Judgement quality is better than the admission metric was able to see.

Second: **the mechanical arm scored zero — 0 of 9 checks, in all three runs — so every passing
verdict came from the LLM judge.** Group F's accuracy is 100% judge-dependent. That is the design's
stated worry in reverse: the module consults the judge only after character containment fails,
precisely so a judge cannot approve answers the corpus never supported, and it turns out
containment never succeeds at all. An answer is prose that wraps the fact; a v3 claim is prose that
elaborates the fact; normalized containment recognizes neither.

Third, and this is why the first finding must be stated as a range: **the verdicts are not
reproducible.** One case, `v2-r-extension-status` (three expected statements, the hardest in the
suite), was judged incorrect in run 1, correct in run 2, and incorrect on the deep arm. Its middle
check is what flips. So the honest figure is **5–6 of 6 across three runs, all judge-decided**, and
the accuracy number should be read as *a judge's opinion on 6 questions, restated*, not as a
measurement. The rationales are recorded per check and they are specific and checkable
("答案未包含‘附录签字’和‘尾款处理’两项条件") — evidence of the same kind as a careful human review, with
the same reproducibility caveat, on a suite far too small to average the noise out.

**The rag-only vs fused ablation did not separate.** The one case that differs between the fast and
deep arms is the same case that differs between two runs of the fast arm, so the arm difference is
inside the judge's own variance. On 6 cases this is a null result, not a finding.

---

## The measurement problem

Groups B and F, run on real artifacts for the first time, failed in the same way, and it is worth
naming once as a single defect rather than twice as two.

**The evaluator's notion of "the same statement" is normalized character containment, and the
current compile contract does not produce containment.** `char_similarity` returns 1.0 when the
shorter normalized string appears inside the longer one. That is a good rule for terse claims that
quote their material — which is what the shipped v1-contract bundle produced, at 69 characters per
claim. The v3 contract produces 170-character claims that normalize dates, add strength labels and
state hedges explicitly. Those are *paraphrases with additions*. Containment fails, cosine over a
30-character label against a 170-character claim lands at 0.50–0.69, and the 0.72 threshold —
inherited unchanged from `opc_84d_evaluation.py` so that both evaluators would agree — rejects all
of them.

Consequences visible in this report:

- group B reports 0/7 recall on facts that are demonstrably present and usable;
- group B reports **the same 0.0** for a deliberately mismatched corpus, so the metric cannot
  distinguish "wrong corpus" from "right corpus, well compiled";
- group F's mechanical arm contributes nothing, leaving a judge as the sole scorer;
- group C's duplicate detection uses the same matcher, so its 3 clusters at head are a *lower
  bound* — paraphrase-level duplication is invisible to it by construction.

None of this is fixed by a better compiler, and none of it should be fixed by lowering the
threshold until the numbers look right. What it needs, in order: **calibrate the threshold against
labelled pairs** (the seven pairs in group B are a starting set, and they place the boundary for
this contract above 0.70); **report best-match score distributions, not just pass/fail**, so a
near-miss cluster is visible instead of collapsing into a zero; and **make the per-truth-entry
table standard output**, because reading the pairs is what turned a catastrophic-looking result
into a measurement finding. Until then, group B's trustworthy output on this corpus is the
negative-control result and nothing else.

---

## Track (a) vs track (b) — full comparison

Comparability is stated per row. **Structural** rows describe artifact shape and differ partly
because the corpora differ in size; **comparable** rows are rates or invariants that normalize;
**direction only** rows may be compared for sign, not magnitude; **content** rows are not
comparable at all. The two corpora are different stories of different sizes, so no row here is a
controlled experiment — the only controlled difference is the compile contract, and it is
confounded with corpus everywhere.

| metric | track (a) `u-opc-lin` | track (b) `u-opc-seamlog-v2-trackb-20260730` | comparability |
| --- | --- | --- | --- |
| checkpoints (compile commits) | 11 | 170 | structural |
| documents at head | 9 | 8 | structural |
| claims at head | 76 | 328 | structural |
| L0 sources / blocks | 11 / 145 | 190 / 1292 | input |
| A claim citation coverage | 0.9868 | **0.9970** | comparable |
| A citations at head | 82 | 484 | content |
| A citations resolvable | 82/82 (1.0) | 484/484 (1.0) | comparable |
| A unparsable marker residue | 0 | **4** | comparable |
| A anchors: no repo-wide loss | yes | yes | comparable |
| A link edges at head | **0** | **8** (56 links) | comparable |
| A dead / self links | 0 / 0 | 0 / 0 | comparable |
| C compression ratio, first → head | 0.6079 → 0.8294 | 1.0914 → **0.4211** | direction only |
| C compression trend | +0.2215 | **−0.6703** | direction only |
| C prose chars per claim | 68.9 | **169.8** | comparable |
| C markup share of head bytes | 49.7% | **33.2%** | comparable |
| C near-duplicate clusters | 2 | 3 | comparable |
| C cross-document duplicate clusters | 1 | 2 | comparable |
| C duplicate row rate | 0.0263 | **0.0091** | comparable |
| C verbatim transcription rate | 0.0267 | **0.0061** | comparable |
| C longest verbatim run | 58 | 58 | comparable |
| C language consistency with L0 | 0.7368 | **0.6646** | comparable |
| C claims diverged from corpus language | **0** | **38** | comparable |
| D reachable-document rate | 0.1111 | **0.0** | comparable |
| D hub documents present | 1 | **0** | comparable |
| D isolated documents | 9 of 9 | **3 of 8** | comparable |
| D orphan claim rate | 0.9211 | **1.0** | comparable |
| D canonical growth exponent | 1.7477 | **0.7801** | comparable |
| D claim growth exponent | 1.8210 | **0.9582** | comparable |
| D sublinear | no | **yes** | comparable |
| D aggregation rate | 0.5556 | **0.75** | comparable |
| D dated-slug documents | 0 | 0 | comparable |
| D families in use / available | 6 / 7 | **3 / 7** | comparable |
| D normalized family entropy | 0.7846 | **0.4546** | comparable |
| D claims in unowned paths | 0 | 0 | comparable |
| E rounds under catch-all pressure | 1 / 11 | 19 / 170 | comparable |
| E sustained pressure | no | **yes** | comparable |
| E evolve events | none | none | comparable |
| E verdict | `aligned_restraint` | `missed_pressure` (trigger disabled) | comparable |
| E schema floors monotone | yes / yes | yes / yes | comparable |
| B admission | `unavailable` | `ok` — 0/7 recall, 0/5 leaks | n/a |
| B claims resting only on labelled noise | `unavailable` (no labels) | **14 / 327 (0.0428)** | n/a |
| F usability QA | `skipped` | `ok` — 5–6/6, judge-decided | n/a |

### Core conclusions

1. **The connective tissue arrived. 0 → 8 inter-document edges, 0 dead, 0 self-referential.**
   Track (a)'s highest-severity finding was that canonical had no links at all and that the gate
   punished a bad link while nothing noticed a document with none. The rebuilt compile prompt
   states the rule explicitly and the model follows it. This is the clearest
   contract-attributable improvement in the report, and it is a mechanism result rather than a
   corpus artifact.

2. **The bird's-eye job went from failing to working: growth exponent 1.75 → 0.78, superlinear to
   sublinear, on a 10× L0 span instead of a 45% one.** Compression reverses from rising (+0.22) to
   falling (−0.67), duplication drops 0.026 → 0.009, verbatim leakage 0.027 → 0.006. Track (a)
   could not separate "threads a transcript hard" from "transcribes summaries" because its corpus
   arrived in one lump; track (b)'s does not, and the answer is that the current compiler threads.

3. **Reachability got worse while the graph got better, because the hub was never created.**
   Track (a): a hub with nothing leaving it (rate 0.111). Track (b): a linked component with no
   hub in it (rate 0.0, all 328 claims orphaned). `memory/profile.md` has zero claims, and the
   contract gives a compiler two reasons not to write it — the family is for owner-profile
   material, and §8 forbids the registration profile from being a claim source. **The
   follow-the-thread job is still not done, and the reason is now a contract gap rather than a
   missing instruction.**

4. **Concentration replaced distribution: 6 → 3 families in use, entropy 0.78 → 0.45, one document
   holding 49% of the artifact.** `memory/people` and `work/experiments` are empty over a corpus
   with five recurring people and a run of explicit experiments. Aggregation is up (0.75) but it
   has become aggregation into too few places — and the interim evidence that attempt 1 of the
   same run *did* create `memory/people/*` means this number carries real sampling variance.

5. **The two judgement groups could not judge, and that is the most actionable result here.**
   Group B: 0/7 on facts group F then answered 5–6/6 from the same canonical, with all seven best
   matches at 0.50–0.69 against a 0.72 threshold calibrated for claims 2.5× shorter. Group F:
   mechanical arm 0/9 in every run, so all verdicts are the judge's, and one of six cases flips
   between runs. Before the next evaluation is worth running, the matcher needs calibrating
   against labelled pairs — otherwise every future run will report a contract that writes longer,
   more careful claims as a contract that admits nothing.

6. **Canonical drifted off the language of its evidence, and only the comparison shows it is new.**
   38 of 328 claims are written wholly in English over a wholly-Chinese corpus, against **zero** in
   track (a). It arrived with the English contract prose, it concentrates in the earliest rounds,
   and it makes those 38 claims unmatchable by any character-level metric — including the one
   reporting 0/7 above.

---

## Weaknesses of the current version, ranked

1. **No entry point into the knowledge graph (D, high).** `memory/profile.md` is never created;
   reachable-document rate 0.0; all 328 claims orphaned. Links exist and resolve, so this is one
   missing document away from working — but as measured, browsing from a known starting point is
   impossible.
2. **Citation-shaped markers that resolve to nothing (A, high).** 4 occurrences of
   `[cite: c:<anchor>]` — anchor references written in source-locator syntax. The gate does not
   reject them, the evaluator cannot resolve them, and a reader sees provenance that leads
   nowhere. The contract asks for claim→claim references and provides no syntax for them. Appeared
   at r86, survived to head.
3. **The evaluation cannot measure judgement (B/F, high).** Threshold and matcher calibrated for
   69-char claims, applied to 170-char claims: group B 0/7 on present facts, group F mechanically
   0/9 so every verdict is the judge's and one case in six flips between runs, group C's duplicate
   count a lower bound. This blocks the next evaluation more than it blocks this one.
4. **Household noise admitted as operations knowledge (B, medium-high).** `B.noise_support`: 14 of
   327 judged claims (rate 0.0428) rest only on evidence the corpus labelled exhaust, against 1,513
   pre-compilation labels. 4 of 8 head documents are personal admin, 3 filed under
   `work/operations`. Demonstrated to compete with real questions at retrieval time. The 5-item
   negative-control set reports 0 leaks and cannot see any of it.
5. **Extreme family concentration (D, medium).** 3 of 7 families; entropy 0.45; one document at
   49% of the artifact; `memory/people` and `work/experiments` empty. Carries run-to-run variance
   — attempt 1 filed people differently — so it needs repeat runs before being called systematic.
6. **Sustained catch-all pressure with no listener (E, medium).** 19 rounds under pressure, a
   5-round run, 33 claims parked in `memory/topics` including a 32-claim client. Verdict
   `missed_pressure` is arithmetically right and evidentially weak: `evolve_auto_trigger` was off.
   One flag flip turns this into the most valuable measurement available.
7. **No economy at small scale (C, medium).** Compression starts at 1.09 — canonical larger than
   its material — because the v3 apparatus has a fixed per-claim cost. A three-source-old
   knowledge base is a longer read than the raw sources.
8. **Claims are 2.5× longer (C, observation with consequences).** 170 chars vs 69. The length
   carries hedges and normalized dates the contract asks for, so it is not a defect on its own —
   but it breaks the admission matcher and fills a recall context 2.5× faster.
9. **Canonical drifted off its corpus language (C, medium).** `C.language_consistency`: 0.665, with
   **38 claims wholly in English** over a wholly-Chinese corpus and 72 bilingual. Rounds r02–r11 are
   100% diverged — the first ten compile rounds produced twenty-three claims, all English — and
   track (a) had zero diverged, so this is new with the English contract prose and worst when the
   knowledge base is empty. Beyond the provenance problem — a translation presented as a thread —
   those 38 claims cannot be matched by any character-level metric, so they are invisible to
   group B by construction.
10. **One uncited claim under a rule that should forbid it (A, low-medium).** 1 of 328, written
    *after* rule 3c existed, in the same document as the malformed markers. Likely the same seam.
11. **Subject ownership still leaks across families (C/E, low-medium).** 2 cross-document
    duplicate clusters straddling `work/operations` and `work/products` — the second independent
    sighting of this boundary problem, and a lower bound given the matcher.

### Framework robustness gaps found while running

Not compiler quality, but they cost this evaluation two runs and would cost a production
deployment more.

1. **No request timeout on the chat path, and no setting for one.** `wiring._build_from_name`
   passes neither `timeout` nor `max_retries`; `Settings` has no field. A stalled socket hangs a
   compile job forever — observed at 25+ minutes with no error. The embeddings adapter guards
   itself; the more expensive path does not.
2. **The embeddings retry budget is ~1.5 seconds.** `_RETRIES = 3` with
   `sleep(0.5 * (attempt + 1))`. Any route flap longer than that fails the job, and the job
   failure fails the batch closed. This is what killed batch 21.
3. **The experiment runner never runs the worker's stale-claim self-heal.** `drain_user` is called
   directly, so `requeue_claimed_jobs()` never runs. A killed run strands a `claimed` job, and
   `_batch_failures` then makes that batch permanently unrunnable in that tenant; the only shipped
   recovery is `--reset-user`. Note that a correct recovery *does* exist for the failed-job case —
   `undigested_source_ids()` + enqueue, i.e. what `POST /compile` does — it simply is not reachable
   from the experiment runner.
4. **`requeue_claimed_jobs()` is global, not per-tenant.** On a shared stack it rewrites every
   tenant's claimed rows, including ~70 abandoned integration-test tenants. A `user_id`-scoped
   variant would make it safe to call from an operator script.

---

## Evaluator defects this run exposed, and the fixes

Track (b) was the first time the package ran against a live trajectory rather than the shipped
bundle. Two of six groups turned out to be unreachable from the command line.

**1. `full` mode could not complete at all when a truth set was bound.** `qa_metrics` is
synchronous and asking a live recall path a question is not, so the one configuration that could
produce a number — full mode, truth bound, answerer supplied — could only ever return
`status: "pending"`. There was also no CLI flag to supply an answerer, so `--mode full --truth …`
raised `EvalDependencyError` and exited 2, every time. The documented six-group mode had no
working path.

- added `qa.qa_metrics_async`, which applies the identical refusals (same statuses, same reasons,
  same raise) and then actually runs `run_qa_suite`;
- `build_scorecard` accepts a precomputed `qa=` group, so an async caller can supply group F
  without the metric modules losing their purity;
- the CLI gained `--answer-url` / `--answer-user` / `--answer-mode` / `--judge-model` /
  `--no-judge`, and prints `qa_status` + `qa_accuracy` in its summary; `--answer-user` defaults to
  the evaluated bundle id;
- the refusal is preserved deliberately: `--mode full` with a truth set and no `--answer-url`
  still exits 2. Adding a way to supply the arm must not add a way to skip it silently.

**2. Groups B and F were invisible in the rendered report.** `report.md` printed one status line
each, so a bound truth set and a completed QA suite could only be read from `scorecard.json`.
`render_report` now renders the recall series, the negative-control result, latency and
supersession statuses, and the QA accuracy tables.

Six tests were added: the async face, the preserved refusals, the `as_of` label reaching the
answerer verbatim, the precomputed-group-F path, and both CLI behaviours (works with an answerer,
still refuses without one).

**One gap deliberately not closed.** `load_git_trajectory` accepts an L0 `sources` mapping and a
`consumed_by_job` mapping, but the CLI's `--git-repo` path has no flag for either, so a canonical
repo evaluated straight off disk reports `l0_blocks: 0` and drops citation resolvability, the
compression series and verbatim reproduction to `unavailable`. Those statuses are honest — each
names its missing denominator — but three of the most valuable metrics are unreachable that way.
Track (b) worked around it by exporting the tenant with the shipped `examples/export_presets.py`
and evaluating the bundle with `--preset`, which has the side benefit that both tracks go through
the identical loader at identical fidelity. That is a workaround, not a fix, and it is the next
change the package needs.

**3. Two measurements this run needed did not exist, and are now metrics.** Both began as ad-hoc
scripts and were promoted into the package rather than left beside it — a number quoted in a report
from a script nobody tested is a number nobody can check.

- **`admission.noise_support`** (group B): claims resting only on evidence the corpus labelled
  exhaust, against `authorship.content_class` labels read by `truth.load_content_classes` and bound
  with `--content-classes`. `unavailable` — never zero — when the corpus ships no such labels. Six
  tests, including the one that caught the original script treating an *unmatched* block as absence
  of signal and so over-reporting.
- **`layering.language_consistency`** (group C): the share of claims written in the language of the
  L0 they compile, with the corpus language read from L0 rather than assumed, and `mixed` kept as
  its own bucket so a bilingual claim is not confused with a wholly-translated one. Six tests,
  including a floor that keeps Latin dates and identifiers inside a Chinese claim from reading as a
  language switch.

Both are rendered in `report.md` and both raise findings. The scripts are deleted.

---

## Reproduce

```bash
# track (a) — offline, deterministic, no key
uv run python -m pneuma_knowledge_eval.cli evaluate \
    --preset examples/data/preset/u-opc-lin --mode mechanical \
    --out docs/eval/artifacts/track-a-mechanical-u-opc-lin

# track (b) — the run (needs the dev stack + a real provider key)
uv run python examples/run_opc_84d_experiment.py --mode real \
    --user <fresh u-opc-seamlog-v2-* tenant> --until-batch 28
uv run python examples/export_presets.py <tenant>=<tenant>

# track (b) — mechanical and full
uv run python -m pneuma_knowledge_eval.cli evaluate \
    --preset docs/eval/artifacts/track-b-bundle-<tenant> \
    --truth docs/experiments/opc-84d-v2/qa/evaluation-v2-truth.json \
    --require-corpus opc-84d-v2 \
    --content-classes docs/experiments/opc-84d-v2/accepted \
    --mode mechanical --out docs/eval/artifacts/track-b-mechanical

uv run python -m pneuma_knowledge_eval.cli evaluate \
    --preset docs/eval/artifacts/track-b-bundle-<tenant> \
    --truth docs/experiments/opc-84d-v2/qa/evaluation-v2-truth.json \
    --require-corpus opc-84d-v2 \
    --content-classes docs/experiments/opc-84d-v2/accepted --mode full \
    --answer-url http://127.0.0.1:8399 --answer-user <tenant> --answer-mode fast \
    --out docs/eval/artifacts/track-b-full
```

Full mode needs `OPENROUTER_API_KEY` (embedding matcher + judge) and a running service for the
answer arm. The run wrapper additionally set a 300s chat timeout and widened the embeddings retry
budget; see *The run record*.

### Artifacts

| path | what |
| --- | --- |
| `docs/eval/artifacts/track-a-mechanical-u-opc-lin/` | track (a) scorecard + rendered report |
| `docs/eval/artifacts/track-b-mechanical/` | track (b) mechanical scorecard + report |
| `docs/eval/artifacts/track-b-full/` | track (b) full mode, fast recall (the numbers above) |
| `docs/eval/artifacts/track-b-full-deep/` | track (b) full mode, deep recall (the ablation) |
| `docs/eval/artifacts/track-b-control-mismatched-corpus/` | v1 RelayForge labels vs v2 Seamlog canonical |
| `docs/eval/artifacts/track-b-bundle-u-opc-seamlog-v2-trackb-20260730/` | the exported tenant the evaluations read: `manifest.json`, `canonical.tar.gz`, `pg/*.json.gz`. The L1/L2 dumps from the original export were removed (5.2 MB of regenerable vectors the evaluator never reads); `manifest.json` records the trim, and its counts describe the original export |
| `docs/eval/artifacts/opc84dv2-trackb-run.json` | run report, batches 1–7 |
| `docs/eval/artifacts/opc84dv2-trackb-run-resume.json` | run report, batches 8–21 |
| `docs/eval/artifacts/opc84dv2-trackb-run-resume2.json` | run report, batches 22–28 |
| `docs/eval/artifacts/aborted-run-2026-07-30T0559/` | attempt 1, aborted at batch 10, with its log |
| `docs/experiments/opc-84d-v2/accepted/` | the corpus's own `content_class` labels, bound via `--content-classes` |

---

## What the next evaluation should do

1. **Calibrate the admission matcher before anything else.** The seven pairs in group B are a
   labelled starting set and they place the boundary for v3-contract claims above 0.70. Report
   best-match distributions, not pass/fail, and make the per-entry table standard output.
2. **Flip `evolve_auto_trigger` on and re-run.** Group E has real sustained pressure and no
   listener; this is the one measurement where a single flag converts an arithmetic verdict into
   evidence.
3. **Label the v2 corpus for supersessions.** It declares zero; v1 declares 12. Supersession
   handling is a headline design claim and is currently untestable on the only corpus that can be
   compiled.
4. **Run the same corpus twice under one contract.** Attempt 1 and attempt 3 filed people
   differently. Family entropy, aggregation rate and document count all carry variance this report
   cannot quantify from one run each.
5. **Fix `--git-repo` L0 loading** so a live tenant can be evaluated without a preset export.
6. **Run group F more than once, or stop quoting its accuracy to three digits.** One case in six
   flips between identical runs, so a single run cannot distinguish a 5/6 structure from a 6/6 one.
   Either repeat the suite and report a range, or expand it past 6 cases.

---
---

# Appendix — track (a) in full

Everything below is the original track (a) draft, unchanged except for this heading and a few
bracketed cross-references to track (b) results. It describes the shipped preset bundle
`u-opc-lin`, compiled under skill base v1 on tree `344e226`, and the gate rules that existed at
that moment. Its numbers were re-derived from the same scorecard used in the comparison above and
reproduce exactly.

## Scope of this draft — read first

This is **track (a) only**: a zero-LLM, zero-network, deterministic evaluation of the
compiled artifacts that ship in this repository.

- **Track (b) — a live run of current `main`** (recompiling the corpus under today's prompts
  and today's gate, then evaluating that trajectory) is **not in this draft**. It needs the
  shared development stack plus a model key, and it is what turns the numbers below from
  "what the shipped artifact looks like" into "what the current compiler does".
- **Group F (usability / outcome QA)** is **not in this draft**. Answering questions requires
  a live recall path and, for the judge arm, a model. Mechanical mode is defined as
  zero-LLM/zero-network, so the group reports `skipped` with that reason rather than a number.
- **Group B (admission judgement)** is `unavailable` for this bundle, for the corpus-identity
  reason in the next section. It is implemented and unit-tested, and it will produce a series
  the moment it is pointed at artifacts compiled from a labelled corpus.

Reproduce:

```
uv run python -m pneuma_knowledge_eval.cli evaluate \
    --preset examples/data/preset/u-opc-lin --mode mechanical --out <dir>
```

## Corpus identity: a correction to the plan

The evaluation plan assumed the shipped preset was the 84-day synthetic corpus, and that its
12 weekly intake batches would supply both the checkpoint axis and the truth set. **It is
not.** The bundle at `examples/data/preset/u-opc-lin` was compiled from the demo corpus in
`examples/data/opc-demo`:

| | shipped preset `u-opc-lin` | 84-day corpus `examples/data/opc-84d` |
| --- | --- | --- |
| story | Orion client pilot | RelayForge product build |
| sources | 11 normalized sources | 98 normalized source units, 12 weekly batches |
| span | 2026-07-18 … 2026-07-25 (8 days) | 2026-03-02 … 2026-05-24 (84 days) |
| L0 size | 145 blocks / 6,318 chars | 2,280 atoms / 213,726 chars |
| labels | none | 120 truth entries, 36 negative controls, 12 supersessions, 36 retrieval cases |
| compile history | 11 commits, all within 3 minutes | no compiled artifact in this repository |

Consequences, all reported rather than papered over:

1. The checkpoint axis is the **compile-commit sequence** (`r01`…`r11`), not 12 weekly
   batches. There is no 12-batch dimension to recover from this bundle.
2. **Group B is `unavailable`.** The 84d labels describe a different story; scoring them
   against this canonical would yield ~0 recall and read as a catastrophic quality finding
   when it is really a mismatched input. The evaluator therefore refuses the binding
   (`--require-corpus` makes the mismatch a loud error) instead of publishing the zero.
3. The trajectory is short and the material is small, so every trend below is a trend over
   11 rounds and 6.3k characters. Directions are meaningful; magnitudes should not be
   extrapolated.
4. The 11 rounds are **not in corpus-chronological order** (round 5 compiles the 07-18
   document after rounds 1-4 compiled 07-22 material), because the demo seeder enqueues all
   sources at once. Nothing below reads a temporal ordering into the round index.

The filename retains `opc84d` because that is where this report was expected to land;
`u-opc-lin` is the bundle actually evaluated.

*[Track (b) established that the 84-day column above understates the problem: that corpus has no
importer on current `main` at all, and the corpus that does have one is a third, different story.
See "Corpus identity: there are three 84-day corpora".]*

## Trajectory

| round | ref | committed | consumed source | docs | claims | canonical chars |
| --- | --- | --- | --- | --- | --- | --- |
| r01 | 3ac80449 | 2026-07-28 19:27:31 | meeting · 需求发现会 (110 ¶) | 6 | 39 | 5,453 |
| r02 | 4945f012 | 2026-07-28 19:27:55 | doc · 会后待办 (3 ¶) | 6 | 42 | 5,937 |
| r03 | 9b39a80f | 2026-07-28 19:28:06 | doc · 首期试点范围 (5 ¶) | 6 | 46 | 6,496 |
| r04 | 0a1fae94 | 2026-07-28 19:28:17 | doc · 项目总览 (4 ¶) | 6 | 48 | 6,746 |
| r05 | 2d1b8fd2 | 2026-07-28 19:28:31 | doc · 公开发布清单 (3 ¶) | 7 | 51 | 7,165 |
| r06 | 53b492ef | 2026-07-28 19:28:46 | doc · EXP-021 (4 ¶) | 8 | 56 | 7,800 |
| r07 | ae274bbf | 2026-07-28 19:29:18 | im · client-orion (5 ¶) | 8 | 60 | 8,435 |
| r08 | 9b098ce0 | 2026-07-28 19:29:31 | im · 陈澄 (3 ¶) | 8 | 62 | 8,654 |
| r09 | caafc408 | 2026-07-28 19:29:43 | im · 交付协作 (4 ¶) | 9 | 67 | 9,244 |
| r10 | 7f1c56c1 | 2026-07-28 19:30:03 | email · 数据边界 (2 ¶) | 9 | 72 | 9,904 |
| r11 | 2272163a | 2026-07-28 19:30:22 | email · 范围确认 (2 ¶) | 9 | 76 | 10,407 |

All 11 commits carry `Skill-Version: v1` / `Skill-Content-Hash: e253fc2f…`, so the whole
trajectory was produced by one skill body — there is no schema-version confound in the series.

## A · grounded — provenance honesty

| round | claims | cited | coverage | citations | resolvable | unparsable residue |
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

Anchor continuity across all 10 transitions: **0 anchors vanished** (per-document and
repo-wide), **0 documents dropped**, anchor count monotone (39 → 76). Links: **0 dead, 0
self-references** — with the caveat under group D that this is because there are no links at
all. Citation replay: **82/82 locators resolve** to a real source with an in-bounds ¶
interval, and there is no text that looks like a citation but does not parse.

**Reading.** The provenance backbone is clean, and it is clean from the first commit rather
than converging — which is what a mechanism-enforced invariant should look like in a
trajectory. The one exception needs its chronology stated, because it is the exact case this
group was designed for.

**Exactly one claim carries no provenance at all**: `work/operations/orion-pilot.md#6781548b` —
「当前素材记录的是已约定的计划与承诺，不等同于相应文件已发送、数据已导入、走查已完成或验收已通过。」
committed in r01 and unchanged through r11. It is a **byte-identical duplicate of
`#75f53736`, in the same document, which cites `cb29d30c ¶97`** — so the compiler wrote the
same sentence twice, attributed once. The cited copy sits under 「行动项」, the uncited copy under
「交付状态边界」 in the same document. This is not a "caveat claims have nothing to cite" gap: the
citation for that exact sentence already exists, three claims earlier.

The chronology matters. The bundle's commits are dated 2026-07-28 19:27–19:30, immediately
after `344e226`. At that commit the gate checked anchor continuity, anchor uniqueness,
citation legality, frontmatter, anchor coverage and path ownership — and **had no
provenance-on-new-claims rule at all**; rule 3c (`claim_without_provenance`) and rule 3d
(dead/self links) were both added later, in `b164c68` (2026-07-30 00:58). So this claim did
not slip past today's gate: it was committed under a gate that did not yet ask. Today's gate
would hard-reject it — a new anchor, no citation marker, no reference to a base anchor.

That is the honest conclusion, and it is a conclusion about the *audit*, not about the current
compiler: **the mechanism closed this hole after this bundle was produced, and canonical is
forward-only so the artifact keeps the evidence.** It is also precisely why group A never
repairs and always reports per checkpoint. What track (b) must confirm is that the hole stays
closed under the current gate — and, separately, that the duplicate-write behaviour behind it
(the same sentence emitted twice in one round) is gone, because *that* is a judgement failure
no gate rule addresses.

*[Track (b) result: coverage rose to 327/328 and the duplicate-write pattern did not recur, but a
new marker-level defect appeared — 4 anchor references written in citation syntax, which the gate
does not inspect.]*

## C · layering — thread layer or second copy

| round | prose chars | markup chars | L0 chars | ratio | chars/claim |
| --- | --- | --- | --- | --- | --- |
| r01 | 2,640 | 2,813 | 4,343 | 0.6079 | 67.7 |
| r02 | 2,934 | 3,003 | 4,463 | 0.6574 | 69.9 |
| r03 | 3,198 | 3,298 | 4,668 | 0.6851 | 69.5 |
| r04 | 3,324 | 3,422 | 4,873 | 0.6821 | 69.3 |
| r05 | 3,556 | 3,609 | 5,049 | 0.7043 | 69.7 |
| r06 | 3,878 | 3,922 | 5,238 | 0.7404 | 69.3 |
| r07 | 4,179 | 4,256 | 5,459 | 0.7655 | 69.7 |
| r08 | 4,319 | 4,335 | 5,551 | 0.7781 | 69.7 |
| r09 | 4,598 | 4,646 | 5,705 | 0.8060 | 68.6 |
| r10 | 4,942 | 4,962 | 5,982 | 0.8261 | 68.6 |
| r11 | 5,240 | 5,167 | 6,318 | 0.8294 | 68.9 |

Duplication is flat across the trajectory: **2 near-duplicate clusters** at every round (1 of
them a byte-exact pair, 1 of them **cross-document**), duplicate row rate 0.026. Verbatim
reproduction: of 75 claims with resolvable support, **2 share a ≥40-character literal run**
with their cited blocks (rate 0.027; longest run 58 characters, mean 15.8).

**Reading.** Two findings, one of them structural.

First, the compression ratio **rises monotonically from 0.61 to 0.83** (+0.22). The ratio is
measured on prose only — citation markers and anchor comments are excluded, because at this
scale that markup is *half the file* (5,167 of 10,407 characters) and counting it would
report the provenance backbone as verbosity. The rise has a benign explanation and a
worrying one, and this bundle cannot separate them: r01 consumed a 110-¶ meeting transcript
(4,343 of the 6,318 total L0 characters), so later rounds each added a small, dense,
already-summarized document. A compiler that threads a transcript hard and transcribes a
summary document lightly would produce exactly this curve. The claim size is the interesting
invariant here: **~69 prose characters per claim at every single round**, never drifting. The
compiler has a stable notion of claim granularity; what varies is how much of the material it
decides to keep.

Second, the two duplicate clusters are different failures and should not be read as one
number. The within-document pair is **byte-identical** (`orion-pilot.md#6781548b` ≡
`#75f53736`, the uncited/cited guard sentence from group A): one round emitted the same
sentence twice. The cross-document pair is **containment**, not equality:
`work/operations/orion-pilot.md#48d59e60` is 「第二周末进行二十题验收。」 while
`work/products/orion-client-knowledge-assistant.md#19fff13c` is
「第一次联合走查重点看导入和原文回放，不要求二十题完成；第二周末进行二十题验收。」 — the operations
document lifted a sub-clause of the product document's claim into a standalone claim, and the
two cite different blocks of the same source (¶70 vs ¶67). That is a subject-ownership
question: the acceptance milestone is asserted by two families, with no link between them
(group D) for a reader to discover the second from the first.

Caveat on the matcher, which the number depends on: `char_similarity` (shared with the live
evaluator) returns 1.0 when the shorter normalized string is contained in the longer one. That
is the right behaviour for "was this statement admitted" and it means the duplicate count here
includes containment, not just paraphrase-level equality. Reading a cluster always requires
looking at the pair.

*[Track (b) found this caveat is larger than it looked: the same matcher, applied to the current
contract's 170-character claims, fails on paraphrase entirely. See "The measurement problem".]*

## D · navigability — the two jobs canonical exists to do

| round | docs | link edges | reachable from hub | reach rate | isolated docs | orphan claims |
| --- | --- | --- | --- | --- | --- | --- |
| r01 | 6 | 0 | 1 | 0.1667 | 6 | 35 / 39 |
| r05 | 7 | 0 | 1 | 0.1429 | 7 | 46 / 51 |
| r08 | 8 | 0 | 1 | 0.1250 | 8 | 57 / 62 |
| r11 | 9 | 0 | 1 | 0.1111 | 9 | 70 / 76 |

(Every intermediate round is identical in kind; the full series is in `scorecard.json`.)

Growth exponents over the trajectory: canonical prose **1.75**, claim count **1.82** — both
superlinear in L0 size. Structure: 9 documents at head, **5 of them grew across more than one
round** (aggregation rate 0.56), **0 dated slugs**, 6 of 7 families in use (only
`materials/{slug}.md` is empty), normalized family entropy 0.78, and **0 claims outside any
declared family**.

**Reading.** This is the strongest finding in the whole evaluation, and it is a finding about
an absence: **the canonical repository contains zero inter-document markdown links, at every
one of the 11 checkpoints.** The follow-the-thread job — walk from an entry point to a related
subject you did not already know the name of — does not exist in this artifact. Group A
reports "0 dead links" and it is true, in the way that a building with no doors has no broken
doors. Everything except `memory/profile.md` is isolated; 70 of 76 claims sit in documents
unreachable by browsing.

Chronology again, for fairness: the dead-link rule (3d) did not exist when this bundle was
compiled either, so the zero is not the model avoiding a punishment — it simply never linked.
But the asymmetry it creates is a live concern for the CURRENT version: today's gate
hard-rejects a link to a nonexistent path (correctly — that is a dead end in the graph), while
nothing rejects, or even notices, a document with no outbound links at all. Not linking is now
the risk-free choice. Whether current prompts overcome that is the single highest-value thing
track (b) should measure.

The bird's-eye half is better than the exponents make it look, and the exponents should not be
over-read: with L0 growing only 45% across the trajectory (because r01 consumed 69% of it) the
log-log lever arm is very short, so 1.75 mostly restates the group C compression trend. The
genuinely good news is in the structure numbers: no dated slugs at all, over half the
documents growing across rounds instead of being re-created, and every claim inside a declared
family. Subject aggregation — the thing that makes a KB survive a year of material — is
working. What is missing is the connective tissue *between* those aggregated subjects.

*[Track (b) answered both questions: the connective tissue arrived — 8 edges, 0 dead — and the
growth exponent fell to 0.78 on a 10× L0 span. Reachability nonetheless went to 0.0, because the
hub document itself was never created.]*

## E · evolution — misfit pressure and response

| round | new claims | into catch-all | share | under pressure |
| --- | --- | --- | --- | --- |
| r01 | 39 | 0 | 0.0000 | no |
| r02 | 3 | 0 | 0.0000 | no |
| r03 | 4 | 0 | 0.0000 | no |
| r04 | 2 | 0 | 0.0000 | no |
| r05 | 3 | 3 | 1.0000 | **yes** |
| r06 | 5 | 0 | 0.0000 | no |
| r07 | 4 | 0 | 0.0000 | no |
| r08 | 2 | 0 | 0.0000 | no |
| r09 | 5 | 0 | 0.0000 | no |
| r10 | 5 | 0 | 0.0000 | no |
| r11 | 4 | 0 | 0.0000 | no |

- Rounds under pressure: **1 of 11**; longest run **1**; mean catch-all share **0.091**;
  sustained (≥3 consecutive) **no**.
- Evolve events: **none** — no evolve commit, no evolve task row. Status
  `no_evolution_events`, verdict **`aligned_restraint`**.
- Cross-family duplicate clusters: **1** (the acceptance-milestone pair above, straddling
  `work/operations` and `work/products`).
- Move fidelity: `no_moves_observed` (nothing to measure without an evolve boundary).
- Monotone floors: family floor **monotone**, anchor floor **monotone**, 0 churn events.

**Reading.** The design's discipline applies exactly here: *no evolution happened, and that
was the correct output.* One isolated high-pressure round — r05, whose OPC release-checklist
document had no owning family and correctly landed in `memory/topics/` — is not misfit
pressure, it is the catch-all doing its job. A metric that rewarded "having acted" would have
scored this trajectory badly for staying still, and would have been wrong. What the group
reports instead is the pressure series intact, plus an explicit statement that response
quality is unmeasured because there is nothing to measure.

The one real signal is the cross-family duplicate. A single straddling cluster is not
evidence of a missing family; it is evidence that `work/operations` and `work/products`
overlap at the boundary where a product's delivery milestones live. Worth watching on a
longer trajectory, not worth a schema change.

*[Track (b), on 170 rounds, saw that boundary again — 2 clusters — and found sustained pressure
this time, but with `evolve_auto_trigger` off there was still no response to score.]*

## B · admission and F · usability — deferred, with reasons

| group | status | reason |
| --- | --- | --- |
| B admission | `unavailable` | no truth set is bound to this trajectory; the labels that exist describe a different corpus (see *Corpus identity*) |
| C detail leakage (labelled half) | `unavailable` | needs the same labelled negatives |
| E response quality | `no_evolution_events` | pressure series reported; no response to score |
| E move fidelity | `no_moves_observed` | no evolve boundary in the trajectory |
| F usability QA | `skipped` | needs a live recall path and (for the judge arm) a model; mechanical mode is zero-LLM/zero-network by definition |

Nothing in this table is a zero. Each row is a stated gap with the input that would close it.

## Weaknesses of the shipped bundle, ranked

Two of these are properties of the shipped artifact under a gate that has since changed;
they are marked **[historical]** and were a track (b) question, not a current verdict.

1. **No inter-document links anywhere (D, high).** 0 edges across 11 checkpoints; 8 of 9
   documents isolated; 70 of 76 claims unreachable from the hub. The follow-the-thread job is
   not degraded, it is absent. Today's gate punishes a bad link and nothing notices a document
   with none. — *resolved in track (b): 8 edges, 0 dead.*
2. **The same sentence emitted twice, once unattributed (A/C, high).**
   `orion-pilot.md#6781548b` ≡ `#75f53736`, one cited and one not. The *uncited* half is
   **[historical]** — rule 3c did not exist at compile time and would reject it today. The
   *duplicate-write* half is not covered by any gate rule and remains a live judgement
   question. — *not reproduced in track (b); duplicate row rate fell to 0.009.*
3. **Subject ownership leaks across families (C/E, medium).** The acceptance milestone is
   asserted by both `work/operations` and `work/products` (containment, different cited
   blocks), with no link between them and no mechanism that would notice. — *reproduced in
   track (b) with 2 clusters at the same family boundary.*
4. **Compression degrades along the trajectory (C, medium).** Prose/L0 rises 0.61 → 0.83. The
   corpus composition explains part of it; this bundle cannot separate "threading a transcript
   hard" from "transcribing summaries". Needs a longer, more evenly-sized corpus to settle —
   i.e. the 84-day corpus. — *settled in track (b): the trend reverses to −0.67.*
5. **Verbatim spans survive into canonical (C, low-medium).** 2 of 75 supported claims carry a
   ≥40-character literal run from their source (longest 58). Small, but it is the leading
   edge of the transcript failure mode. — *rate fell to 0.006 in track (b); longest run
   unchanged at 58.*
6. **Markup is half the artifact (C, observation).** 5,167 of 10,407 characters at head are
   citation markers and anchor comments. Correct and load-bearing, but it means any
   size-based metric that forgets to exclude it will mis-report a small KB badly. — *33% in
   track (b); the share shrinks as the artifact grows.*
7. **Coverage gap: judgement quality is unmeasured (B/F, coverage).** Groups A/C/D/E all
   measure form. Nothing in this draft measures whether the *right* material was admitted or
   whether the result answers a question. Those are the two groups that need the labelled
   corpus and the live stack. — *addressed in track (b), and the attempt revealed that the
   matcher itself cannot measure it. See "The measurement problem".*

## Continuity with the existing evaluator

`packages/pneuma-knowledge-service/src/pneuma_knowledge_service/experiments/opc_84d_evaluation.py`
already reports admission quality on a **live stack at HEAD**. This package does not replace
it and does not re-implement it:

- `char_similarity` / `normalize_text` / `guarded_statement` / `truth_entries` /
  `TRUTH_THRESHOLD` / `NEGATIVE_THRESHOLD` / `_cosine` are **imported**. One definition of
  "the same statement", one set of thresholds, shared by both evaluators.
- The supersession rule (after present **and** before absent-or-guarded) is the existing
  rule, unchanged.
- What is added is the trajectory axis (recall per checkpoint, `peak` vs `head`, admission
  latency in rounds) and the four groups the live evaluator does not cover (layering,
  navigability, evolution, and the outcome-QA shape).
- Where both can run on the same artifacts they should agree at HEAD; that cross-check is
  part of track (b), because the live evaluator needs the stack this draft deliberately does
  not touch.

*[Track (b) note: sharing one threshold with the live evaluator is exactly why group B failed —
`TRUTH_THRESHOLD = 0.72` was calibrated on v1-contract claim lengths. Shared definitions are still
right; the shared constant now needs re-deriving for both.]*

## Gate chronology, for anyone re-reading these numbers later

The bundle was compiled at 2026-07-28 19:27–19:30, on the tree at `344e226`. Two gate rules
have been added since, both in `b164c68` (2026-07-30 00:58):

| rule | present at compile time | consequence for this report |
| --- | --- | --- |
| 3c provenance on newly introduced claims | **no** | the single uncited claim is a pre-rule artifact, not a gate bypass |
| 3d inter-document link targets must exist | **no** | "0 dead links" is trivially true; the 0-edge finding is unaffected |
| 1/2/3/4/4b/5 (anchors, citations, frontmatter, coverage, ownership) | yes | those A-group results are genuine gate-era results |

This table is the reason group A reports per checkpoint and never repairs: a snapshot is
evidence about the rules that existed when it was written.
