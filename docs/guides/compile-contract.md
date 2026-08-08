# Writing a compile contract

**English** | [简体中文](compile-contract.zh-CN.md)

The compile contract is the constitution of a library. It teaches the compile model how to judge inside your domain: what deserves to be remembered long-term, on which page, in what wording. It is judgement, not a rulebook — and this guide is about how to arrive at that judgement.

A contract is a markdown body plus four declared fields — `skill_id`, `version`, `path_templates`, `contract_rules`. The scaffold's template spells the fields as frontmatter above the body the compile model reads on every job:

```markdown
---
skill_id: my-knowledge
version: app-v1
path_templates:
  - people/{slug}.md
  - projects/{slug}.md
  - topics/{slug}.md
---
(what to record, at what granularity, under what wording — the subject of this guide)
```

The framework itself parses none of this. Registration is explicit — `SkillVersion.from_parts(skill_id, version, instructions, path_templates, contract_rules)` — and `instructions` is the markdown body verbatim. The frontmatter is the scaffold's own convention (its driver reads the fields and strips the guidance comments before registering); an application registering programmatically declares the fields in code. The `content_hash` is a sha256 over those five parts — computed by `from_parts`, never hand-written — and it is stamped into every canonical version the contract produces, so a library state is always attributable to the exact contract that made it. Changing the contract means registering a new `version`; it shapes future compiles and never rewrites what is already recorded. A fill-in skeleton lives at [`scaffold/templates/contract.en.md`](../../scaffold/templates/contract.en.md) (Chinese variant beside it), reference contracts at [`packages/pneuma-knowledge-strategies/`](../../packages/pneuma-knowledge-strategies/), and a complete worked deployment at [`examples/opc/`](../../examples/opc/).

## 1. The core reasoning: type → implied use → obligations

Everything else in a contract is an application of one inference: **each type of knowledge in the real world naturally implies how it will be used, and the implied use decides what must be recorded.**

- Recurring **events** imply a **timeline**.
- An **ongoing project** implies a **running record** — goals, decisions, milestones, status changes.
- A **recurring collaborator** implies an **accumulating dossier**.
- A thing that goes by **several names** (nickname, title, abbreviation, codename) implies a subject page that **records its aliases** — otherwise one subject's story splits across names and never reassembles at retrieval time.

Two disciplines pin this inference down:

1. **Derive from the material, never from a preset list.** The four cases above are demonstrations, not a checklist. Your domain implies uses of its own; a list will miss them, the inference will not. Uses also evolve with the material — when the data shifts, re-derive.
2. **Facts a use depends on must be first-class.** Retrieval can only resurface what was recorded; it cannot conjure a fact nobody wrote down. So the answer to "which facts does this use need" *is* the recording-obligation list.

Two traps worth knowing before you write:

- **Compile models favor outcomes and drop beginnings.** "When it started", "who first took it on" — these evaporate when material is compressed into conclusions. If any use computes durations or orders events, make start points an explicit obligation, as first-class as endings.
- **Obligations chain.** A handover owes three facts at once: who gave it up, who took it over, on what date. After deriving one obligation, ask what other fact it needs to be answerable.

Write the *results* of this reasoning into the contract — obligations concrete to the family level ("for this family, always record X") — not the reasoning itself.

## 2. Subject granularity: one independently evolving thing, one document

This is the first principle of filing. A single catch-all page collapses a library: it grows without boundary, triggers constant rollover, dominates every retrieval, and makes "how did this thing change over time" unreadable — twenty stories interleaved in one scroll.

Whether something earns its own page is one question: **will it evolve independently?** A person who will appear again, a project with a next step, a topic that keeps returning — yes, a page. A one-off document, a name passing through once — no; it stays in L0 and retrieval will find it when needed.

For each family in your `path_templates`, answer two things: **what it collects** (which facts belong to it), and **when a new subject earns a page** (on first appearance, or only when it returns with substance?).

**Misattribution is the most expensive error class: the fact is true, the subject is wrong.** It is harder to catch than omission — the library looks complete, things just hang in the wrong place — and no retrieval-time cleverness can undo a compile-time misfile. So spell out, per family, what it collects *and what it must not* — especially for adjacent families that naturally attract each other's facts (people vs. projects, projects vs. topics, events vs. participants). Alias recording (§1) is the same failure in the dimension of names: an unrecorded alias silently turns one subject into several.

## 3. What enters canon

For every candidate fact, one question: **will this be used later — for action, judgement, explanation, collaboration, or review?** Yes: record it. No: the original text and the indexes keep it reachable — L0 fetch and lexical search are unconditional and never depend on what the contract says — so nothing is lost by leaving it out. Canon can therefore afford a high bar: it is the small set of facts that passed judgement, not a copy of the source.

What a contract should contain here is your domain's **two or three most typical "worth it" and "not worth it" cases**, not a universal list. A neutral personal-knowledge baseline reads: worth recording — explicit decisions with their reasons, commitments and acceptance criteria, milestones with dates, verbatim feedback, substantive status changes; not worth recording — pleasantries, suggestions that were not taken up, one-off moods. Your domain almost certainly reads differently; rewrite it wholesale.

Three calibers extend the same judgement, and the pattern is always *ask the use first, then set the caliber*:

- **Evidence.** Reported is not agreed; a proposal is not a decision; "it ran" is not "it was accepted"; "first mentioned" is not "started". Say whose word counts in your domain, what model or tool output counts as, and what qualifiers a number must carry.
- **Time.** Normalize relative time ("next Monday") to absolute dates while keeping the original phrase; the material's own occurrence date governs, and uncertainty is marked rather than guessed.
- **Privacy.** Credentials and identity numbers are framework red lines; add what your domain must never record on top.

**Modality enters through the evidence chain, not by flattening everything to text.** Choose the context assembly only after the compile model and its actual provider route are known. If that path accepts native media, preserve message order, keep the original media retrievable at a stable L0 address, and bind each image/audio/file content block to the text turn that introduced it. If it does not, use an explicitly derived caption, transcript or OCR representation that names its producer and still links to the original media. A URL rendered as text is not equivalent to an image input. As a concrete example, OpenAI's [GPT-5.6 image-input family](https://developers.openai.com/api/docs/guides/images-vision) — Sol, Terra and Luna — can receive native images; use detail appropriate to the evidence needed and measure the resulting tokens and latency. Provider gateways still need an end-to-end capability check.

The contract's job is the judgement at the end of that path: say whether a family may treat direct inspection of original media as evidence, how derived captions/OCR are attributed, and what uncertainty they retain. The contract cannot repair a context builder that never delivered the media.

**Density is the health check for this section.** When a batch of material compiles into far fewer claims than common sense expects, that is rarely restraint — usually some family's obligations are not landing, and timelines and multi-hop questions will go quiet with them.

## 4. Mechanism stays out

The framework already enforces a set of rules mechanically: citations on every claim, system-assigned immutable anchors, frozen archive volumes, path ownership, L0/L1 reachability ([architecture §5, §9](../architecture.md)). Repeating any of them in the contract spends tokens and changes nothing — the gate does not read prose.

When unsure whether something belongs in the contract, apply one test: **if breaking it gets the write mechanically rejected, it is mechanism and stays out; if only a person reading the library can tell right from wrong, it is judgement and belongs in.**

## 5. The acceptance loop

A contract is not thought correct; it is **accepted** through rounds of use. One round:

```
build on an empty library → read the glance → ask real questions → judge →
revise the contract (new version) → rebuild → look again
```

- **Rebuild on empty.** A contract change shapes future compiles only and never rewrites existing canon, so the cleanest read of a revision is a fresh build.
- **Read the glance first.** Did the subjects that should exist get pages? Is there a page that collects everything? A crowd of single-appearance names each holding a page?
- **Ask real questions, with citations on.** What you are checking is not eloquence but whether **the facts the answer depends on are on the page** — and when an answer fails, whether the cause is *not recorded* or *not retrieved*. The two have entirely different fixes.
- **Verify placement, not string presence.** "The date appears somewhere in the library" is false comfort — after a year, almost every date appears somewhere. A fact counts as recorded when it hangs on the right subject, bound to the right object.
- **Judge structurally, and write the judgement down.** Change is not the goal; a better model for future use is. A well-reasoned "no change" is a good outcome and worth recording too. And never revise on the back of one or two questions — re-asking the same set flips a handful of verdicts either way; act on structural shifts (a whole question class improving, a subject's timeline connecting for the first time), not single-point noise.

Two or three rounds in, the library starts looking right. That is delivery.

The ask-real-questions step also exists in mechanized form: the optional **coverage challenge** (see [configuration](../reference/configuration.md)) runs it after every compile — questions generated blind from the material and your contract, judged against the recorded claims, confirmed gaps fed back through one gated compensation compile. It does not replace this loop: the challenge audits recording coverage; only you can judge whether the model itself is right.
