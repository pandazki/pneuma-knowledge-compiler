# Driving and reviewing evolution

**English** | [简体中文](evolution.zh-CN.md)

No model of a domain stays right. Data accumulates, its distribution shifts, the business pivots — and the contract that filed everything correctly six months ago starts filing things wrong. Evolution is the framework's answer: infrastructure that watches how compilation actually goes, drafts a better model when the evidence warrants one, and puts the change in front of you as a reviewable diff. You drive the pace; nothing is adopted without a decision.

What evolves is the **model** — document families, path templates, how pages are cut. What does not evolve is the **facts**: recorded claims are reorganized, never rewritten, and anything that would disappear in the reorganization is surfaced to you by name before it can happen.

## 1. The loop at a glance

```
compile events accumulate ──▶ trigger fires ──▶ proposal drafted
                                                     │
                              no_change ◀────────────┤ proposed
                                 │                   ▼
                          recorded, done    library rebuilt on branch  evolve/<task-id>
                                                     │
                                                     ▼
                                       you review: rationale · diff · dropped anchors
                                                     │
                                     adopt ◀─────────┴─────────▶ drop / TTL expiry
                                       │                              │
                        mechanical reconcile into main          branch deleted
```

## 2. Evidence and triggers

The compiler records an event for every claim it adds or revises. These events — not the raw material — are evolution's evidence: they show where facts have actually been landing, which families absorb everything, which declared families stay empty.

A proposal round starts in one of two ways:

- **Automatically**, after a compile, once both thresholds are crossed since the last look: enough new documents *and* enough new claims (`PNEUMA_KNOWLEDGE_EVOLVE_TRIGGER_TOPIC_DOCS`, `…_NEW_CLAIMS`). The whole behavior sits behind `PNEUMA_KNOWLEDGE_EVOLVE_AUTO_TRIGGER`.
- **Manually**, via `POST /v1/users/{uid}/evolve` — when you already suspect the model is behind the data.

One round at a time: a pending draft or an in-flight job makes further requests return `409`. Review the draft on the table before asking for another.

## 3. The proposal

Given the current contract, the recent events, and the shape of the existing library, the evolve model produces one of:

- **`no_change`** — the current model still fits, with the reasoning recorded. This is a first-class outcome, not a failure: a well-argued "leave it alone" is exactly what you want from a reviewer, mechanical or human.
- **`proposed`** — a concrete revision: families to add or refine, path templates to adjust, pages to restructure — with its rationale.
- Two abort states (`parse_error`, `invalid_templates`) — recorded with their reasons; nothing was touched.

## 4. Rebuilding on a branch

A `proposed` round does not stop at prose. The framework rebuilds the library under the proposed model on its own branch (`evolve/<task-id>`), using a wider toolset than compile — it may move claims between pages and retire pages — while the canonical mainline stays untouched.

The evolve gate then checks the result. One check behaves differently from compile: anchor continuity is verified **library-wide, and a missing anchor does not hard-reject the build**. Instead, every anchor that would disappear becomes an entry in a `dropped` list attached to the task. Reorganization sometimes legitimately retires content — but that judgement belongs to you, not to the machine, so the machine's job is to make the loss impossible to miss.

## 5. Reviewing a draft

A draft task carries everything the decision needs: the proposal and its rationale, the full file diff (old body vs. new body, per changed document), and the dropped-anchor list. The web UI's evolve view presents the same, with adopt/drop actions and the draft's remaining TTL.

What to actually judge — the same standard as [writing the contract](compile-contract.md#5-the-acceptance-loop):

- **Is this a better model for future use, or just a different one?** Change is not the goal. If the rationale reads as taste rather than as evidence ("these twelve claims kept landing in the wrong family"), lean toward drop.
- **Read the dropped list before anything else.** Every entry is recorded knowledge that will not survive adoption. An empty list makes the rest of the review easy; a non-empty one is the review.
- **Check the seams.** Reorganizations fail at boundaries — the two families that used to attract each other's facts should come out of the diff *more* separable, not less.

Drafts expire on a TTL (`PNEUMA_KNOWLEDGE_EVOLVE_DRAFT_TTL_HOURS`, default 24h): an unreviewed draft lapses rather than lingering as a stale fork of a library that has moved on.

## 6. Adopt, drop

**Drop** deletes the branch immediately. Nothing else happened; nothing needs undoing.

**Adopt** enqueues a merge job that reconciles three states mechanically — the point where the draft forked, the draft branch, and the current mainline, which may have received new compiles while you were reviewing. The reconciliation involves no LLM: it is deterministic, auditable bookkeeping that carries the new model and the reorganized pages onto the mainline, rebuilds the derived layers, and records both the pre-adoption and post-adoption versions on the task. If reconciliation cannot proceed safely, the task stays a draft and the job records why — an adoption either lands cleanly or does not land.

After adoption, future compiles file under the new model. Nothing already recorded was rewritten; the history up to the adoption point reads exactly as it always did.

## 7. Policy, not hard constraint

Everything in this lifecycle above the safety floor is **policy, soft by design**. What the framework hard-guarantees is only the floor itself: one round in flight, losses surfaced by name, adoption through mechanical reconciliation, recorded facts never rewritten. How the lifecycle breathes is a business decision. Some deployments pause mainline writes while a draft is under review — with the base frozen, the three-way reconcile degenerates to the trivial case and migration cost drops to its minimum; others let compiles keep flowing and accept that reconciliation does more work. Sparse-data deployments stretch the draft TTL — a quiet week is normal there; dense ones tighten the TTL and raise the trigger thresholds so evolution speaks only when it has something to say.

| Setting | Default | Meaning |
|---|---|---|
| `PNEUMA_KNOWLEDGE_EVOLVE_AUTO_TRIGGER` | `true` | master switch for compile-driven triggering |
| `PNEUMA_KNOWLEDGE_EVOLVE_TRIGGER_TOPIC_DOCS` | `5` | new documents since last round (AND-ed with the next) |
| `PNEUMA_KNOWLEDGE_EVOLVE_TRIGGER_NEW_CLAIMS` | `30` | new claims since last round |
| `PNEUMA_KNOWLEDGE_EVOLVE_DRAFT_TTL_HOURS` | `24` | draft lifetime before lazy expiry |
| `PNEUMA_KNOWLEDGE_LLM_MODEL_EVOLVE` | — | model role for proposing and rebuilding; falls back to the compile role |
