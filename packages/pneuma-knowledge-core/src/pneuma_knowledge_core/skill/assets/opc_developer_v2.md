# opc-developer-knowledge v2 domain guidance

This strategy serves an AI-native solo developer working as a one-person company. The compile goal is a **long-term, traceable personal memory** with the owner as its subject, covering product, engineering, research and operations. It is not a transcript summary, and it is not permanent storage of every input.

Ask one question each time: **will this information later be used for action, judgment, explanation, collaboration or audit?** If yes it enters canonical; otherwise it stays in the original source and the retrieval layers.

## 1. High-value meaning

Prefer to keep product hypotheses and positioning, architecture decisions and constraints, experiment design and results, explicit commitments and acceptance conditions, user feedback together with its exact wording, operational facts affecting releases / cash flow / compliance, and stable working preferences. Greetings, repeated broadcasts, unaccepted suggestions, background noise and short-lived detail do not enter long-term knowledge.

## 2. An observation is not a fact

Transcripts, model summaries, search results and agent output are all merely observations. When a high-impact slot — a person, a number, a date, a negation, an owner, an experiment metric — cannot be supported directly by the source, keep the uncertainty; do not fill in a plausible-looking answer.

Keep the exact words apart from the interpretation; a metric carries its definition, sample and range; a model suggestion is not the owner's decision; an agent log is not a completion; a single piece of feedback does not extrapolate into a market conclusion.

## 3. Identity and attribution

People, organizations, products, repositories and projects are not merged by default. Similar names only form a candidate association; an explicit correction, a stable role, or consistent evidence across sources is what confirms one entity. Aliases are only added, never removed.

The owner relaying someone else's opinion is not the owner agreeing with it; a collaborator proposing a plan is not an accepted decision; an agent generating a candidate is not a fulfilled commitment.

## 4. State and time

Only new evidence about the same entity, in the same semantic scope, explicitly describing the current state, may supersede an old state. When updating, keep the old state, the time of change and the source; do not rewrite history.

**Relative time must be normalized to an absolute date before it is stored.** Expressions like "tomorrow", "next Monday" or "after the last release" are resolved against the source's occurrence time, while the original wording is kept. When the reference point is missing or ambiguous, do not write a definite date — mark it as pending.

Proposal, decision, execution and acceptance stay separate; closing an issue is not solving the problem; merging code is not completing a release; finishing an experiment run is not the hypothesis holding; verbal interest is not a contract or revenue.

## 5. Commitment and relationship strength tiering

Use a controlled **strength prefix label** for commitments, decisions and stable relationships:

- `【firm】`: an owner, a condition/time, or confirmation by both sides is already in place;
- `【forming】`: the direction is clear but one key slot is missing, such as an undecided time or a pending written confirmation;
- `【loose】`: an idea, a hypothesis, a second-hand account, or a proposal not yet accepted.

Strength is re-tiered forward as evidence changes, keeping the old tier and the basis for the change. Use only these three tiers; when unsure, drop a tier.

## 6. Privacy and secrets

Keep only the minimum information needed to complete future action. Passwords, verification codes, tokens, private keys, payment credentials, full identity numbers and authentication secrets never enter canonical; express business state without the secret value.

Information touching third parties, health, finances or legal matters must keep its source and its uncertainty; do not derive a diagnosis, an asset position or a legal conclusion from scattered remarks.

## 7. Document organization

- owner profile, long-term preferences and way of working → `memory/profile.md`
- stable collaborators / contacts → `memory/people/{slug}.md`
- ongoing product state → `work/products/{slug}.md`
- experiments, evaluations and hypothesis evolution → `work/experiments/{slug}.md`
- releases, sales, cash flow and operational matters → `work/operations/{slug}.md`
- cross-domain topics not yet stably classified → `memory/topics/{slug}.md`
- important material whose body must live outside → `materials/{slug}.md`

Organize by shared lifecycle, not one document per session. Move forward, one way only, when the classification is accurate; when unsure leave it in topics.

## 8. The profile is not material

The registration profile, the schema packs and this strategy are only used to judge relevance and filing location; they cannot be the source of a claim. Every claim must link back to this round's source or to existing canonical.

## 9. Closing self-check

Check citations, attribution, absolute time, strength tier, experiment conditions, failure causes, entity boundaries, secret exclusion and preserved uncertainty.
