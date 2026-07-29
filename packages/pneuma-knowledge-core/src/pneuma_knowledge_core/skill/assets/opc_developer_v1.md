# opc-developer-knowledge v1 domain guidance

This strategy serves an AI-native solo developer working as a one-person company. The compile goal is a **long-term, traceable personal memory** with the owner as its subject, covering product, engineering, research and operations. It is not a transcript summary, and it is not permanent storage of every input.

Ask one question each time: **will this information later be used for action, judgment, explanation, collaboration or audit?** If yes it enters canonical; otherwise it stays in the original source and the retrieval layers.

## 1. High-value meaning

Prefer to keep:

- product hypotheses, target users, problem definitions, changes of scope and positioning;
- architecture decisions, interface contracts, technical constraints, failure causes and retrospective conclusions;
- an experiment's hypothesis, method, observations, conclusions and next step;
- commitments, deadlines and acceptance conditions explicitly accepted by the owner or a collaborator;
- customer / prospective-user feedback, keeping the exact words, the observation and the owner's interpretation apart;
- operational facts affecting cash flow, releases, compliance, privacy or long-term maintenance;
- stable personal working preferences, tool choices and collaboration boundaries.

Do not promote greetings, repeated status broadcasts, unaccepted suggestions, background noise or short-lived detail into long-term knowledge.

## 2. An observation is not a fact

Transcripts, model summaries, search results and agent output are all merely observations. When a high-impact slot — a person, a number, a date, a negation, an owner, an experiment metric — cannot be supported directly by the source, keep the uncertainty; do not fill in a plausible-looking answer.

- record the exact words separately from the interpretation;
- a metric must keep its definition, sample and time range;
- a model suggestion is not the owner's decision;
- an agent execution log is not a completed task;
- one piece of user feedback does not automatically extrapolate into a market conclusion.

## 3. Identity and attribution

People, organizations, products, repositories and projects are not merged by default. Similar names only form a candidate association; an explicit correction, a stable role, or consistent evidence across sources is what confirms one entity. Aliases are only added, never removed, so a subject can later be recalled by any name it ever appeared under.

Speaker attribution decides ownership of a fact: the owner relaying someone else's opinion is not the owner agreeing with it; a collaborator proposing a plan is not an accepted decision; an agent generating a candidate is not a fulfilled commitment.

## 4. State evolves forward

Only new evidence about the same entity, in the same semantic scope, explicitly describing the current state, may supersede an old state. When updating, keep the old state, the time of change and the source; do not rewrite history.

- proposal, decision, execution and acceptance are different states;
- closing an issue is not the problem being solved;
- merging code is not a completed release;
- finishing an experiment run is not the hypothesis holding;
- a customer's verbal interest is not a contract or revenue.

## 5. Privacy and secrets

Keep only the minimum information needed to complete future action. Passwords, verification codes, tokens, private keys, payment credentials, full identity numbers and authentication secrets never enter canonical; rewrite them as business state without the secret value, for example "deployment access still pending".

Information touching third parties, health, finances or legal matters must keep its source and its uncertainty; do not derive a diagnosis, an asset position or a legal conclusion from scattered remarks.

## 6. Document organization

- owner profile, long-term preferences and way of working → `memory/profile.md`
- each stable collaborator / contact → `memory/people/{slug}.md`
- a product and its ongoing state → `work/products/{slug}.md`
- experiments, evaluations and hypothesis evolution → `work/experiments/{slug}.md`
- releases, sales, cash flow and operational matters → `work/operations/{slug}.md`
- cross-domain topics not yet stably classified → `memory/topics/{slug}.md`
- important material whose body must live outside → `materials/{slug}.md`

Organize documents by shared lifecycle, not one per meeting or per session. Move a topic forward when it clearly belongs to a product, experiment or operations family; when unsure leave it in topics rather than forcing a classification for tidiness.

## 7. The profile is not material

The registration profile, the schema packs and this strategy are only used to judge relevance and filing location; they cannot be the source of a claim. Every claim must link back to this round's source or to existing canonical; if no source can be found, it should not be created.

## 8. Closing self-check

Check whether new content carries citations; whether a suggestion was written as a decision, an execution as a completion, a correlation as a cause; whether entities were silently merged; whether a key commitment, experiment condition or failure cause was omitted; whether a secret was written; whether the necessary uncertainty was preserved.
