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

The framework itself parses none of this. Registration is explicit — `SkillVersion.from_parts(skill_id, version, instructions, path_templates, contract_rules)` — and `instructions` is the markdown body verbatim. The frontmatter is the scaffold's own convention (its driver reads the fields and strips the guidance comments before registering); an application registering programmatically declares the fields in code. The `content_hash` is a sha256 over those five parts — computed by `from_parts`, never hand-written — and it is stamped into every canonical version the contract produces, so a library state is always attributable to the exact contract that made it. Changing the contract means registering a new `version`; it shapes future compiles and never rewrites what is already recorded. An executable starter contract lives at [`scaffold/templates/contract.en.md`](../../scaffold/templates/contract.en.md) (Chinese variant beside it), reference contracts at [`packages/pneuma-knowledge-strategies/`](../../packages/pneuma-knowledge-strategies/), and a complete worked deployment at [`examples/opc/`](../../examples/opc/).

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
- **Time.** Anchor relative time ("next Monday") to the material's own occurrence date while keeping the original phrase. Resolve exact dates or spans only when the material or the owner's calendar supplies an unambiguous convention; otherwise retain the anchored expression rather than guessing endpoints.
- **Privacy.** Non-admission is judgement, and it is yours: the gate reads provenance, structure and paths, never what a claim is about, so nothing at the write layer stops a credential or an identity number from being recorded. Name what your domain must never record — credentials and identity numbers are where most libraries start — and keep what must not reach the compiler at all out at ingest, in the deployment's own source pipeline.

**Modality enters through the evidence chain, not by flattening everything to text.** Choose the context assembly only after the compile model and its actual provider route are known. If that path accepts native media, preserve message order, keep the original media retrievable at a stable L0 address, and bind each image/audio/file content block to the text turn that introduced it. If it does not, use an explicitly derived caption, transcript or OCR representation that names its producer and still links to the original media. A URL rendered as text is not equivalent to an image input. As a concrete example, OpenAI's [GPT-5.6 image-input family](https://developers.openai.com/api/docs/guides/images-vision) — Sol, Terra and Luna — can receive native images; use detail appropriate to the evidence needed and measure the resulting tokens and latency. Provider gateways still need an end-to-end capability check.

Treat each representation as an independent optional observation. The absence of an image URL must not discard a present caption; the absence of a caption must not discard OCR, a transcript or the original media. Context conversion is accepted by comparing every admitted input field, its order and its digest before and after normalization — comparing rendered text with the same renderer's expected string only proves self-consistency and can hide dropped fields. A labelled derived representation is still usable evidence when native media is unavailable: preserve its provenance, but do not suppress the substantive observation or add a generic hedge to every claim solely because the representation is derived.

The contract's job is the judgement at the end of that path: say whether a family may treat direct inspection of original media as evidence, how derived captions/OCR are attributed, and when their uncertainty is material. The contract cannot repair a context builder that never delivered the media.

**Under-compilation shows itself in use, not in a count.** The diagnosis runs through the owner's own questions going quiet and through families whose obligations never land: a timeline with no dates on it, a multi-hop question whose middle step was never recorded, a family that collects nothing across a whole batch of material that plainly concerns it. A batch that produced strikingly few claims is a symptom worth following to one of those; it is not itself the finding, because restraint and a family that never fired produce the same number.

## 4. Mechanism stays out

The framework already enforces a set of rules mechanically: grounded provenance chains on all authored ledger claims (ending at a source or admitted mechanical record), system-assigned immutable anchors, read-only closed volumes, path ownership, L0/L1 reachability ([architecture §5, §9](../architecture.md)). Repeating any of them in the contract spends tokens and changes nothing — the gate does not read prose.

A document's frontmatter `title` is mechanism too, and derived rather than stored: the system reads it off the document's first `# ` heading — the heading's TEXT, with anchor marks and any trailing system comment removed, which is the same reading every outline and glance displays, so the stored name and the shown name cannot disagree — on every path that serializes a document it changed: the compile draft, both files a rollover writes, the adopt merge that lands a reviewed reorganization, and the volume-link repair pass (which is otherwise byte-preserving outside link hrefs, and takes the derived title as its one stated exception rather than carrying a wrong one forward). A page nobody wrote this round is left byte-identical, stale title and all, and converges on its next write. It also replaces one written into `create_document` and refuses `set_fields` on it — so what a contract has to decide is not the field but the heading, and a person's JOB title is not the name of their page (it belongs in the overview `definition` or in a field of that family).

When unsure whether something belongs in the contract, apply one test: **if breaking it gets the write mechanically rejected, it is mechanism and stays out; if only a person reading the library can tell right from wrong, it is judgement and belongs in.**

## 5. The overview: what a document says about itself

Every document may carry an **overview** — a bounded head above the claim ledger, in four slots: `definition` (one sentence: what or who this is), `summary` (the state now), `introduction` (background, origin, why it matters) and `connections` (links to other subject pages, each with the relation in one line), plus the structured `fields` that belong to the same picture. The compile model writes it with `rewrite_overview`, which replaces the whole region in one call and leaves the ledger untouched.

The overview is a **snapshot**, never a changelog, and every call is a judgement over the one that already stands there — four outcomes: keep it (do not call), merge or rewrite it (call with the whole new region), drop it (call with every slot empty and no fields, which removes the region and leaves the document its claims). That the previous overview was actually observed is mechanical, not asked for: `rewrite_overview` and `set_fields` refuse a document this compile has not read.

The mechanism is not yours to restate: `rewrite_overview` refuses the call outright — before a byte is written, naming every failing block at once — and the gate stands behind it as the final arbiter. Between them they bound the region's size, require every block (a `connections` item included) to reference a ledger claim or cite a source span, refuse a definition that runs past one short block, and refuse a connection to a document that does not exist. They also REQUIRE one: past `OVERVIEW_REQUIRED_AFTER_CLAIMS` ledger claims (default 8), a document this round touched must carry at least a `definition`, refused at `finish_compile` and again at the gate — a subject may well start with no picture, but a page holding that much knowledge and showing none is a gap the mechanism closes, not a judgement your contract makes. What IS yours is the **wording** — what "the current picture" means for the subjects your library files. A contract for a person page may say the definition names the relationship to the owner rather than a job title; a contract for a product page may say the summary leads with what is decided and what is still open. Say what a reader of that family should learn from four lines, and leave everything the gate enforces out of it.

One judgement is worth stating explicitly, because it is judgement and not mechanism: **when to rewrite**. The overview is a reading of the ledger, so it moves when the reading changes, not when the ledger grows. A contract that tells the compiler what counts as a changed picture for its subjects — a role that ended, a decision that closed, a relationship that began — gets an overview that is worth reading; one that says "keep it up to date" gets it rewritten every round for nothing.

## 6. `supersede_claim` vs `edit_claim`: the world changed vs I was wrong

Two write verbs look interchangeable and are not. `edit_claim` rewrites a claim in place — it is for a claim that was **wrong when it was written**: a misheard number, a name attached to the wrong person, a sentence that overstated what the source said. `supersede_claim` records that a claim was **right, and the world has since moved** — a role, an employer, a deadline, a price. The predecessor stays on the page and the new claim is filed behind it as the current state of the same fact:

```markdown
- X is Hengyin Printing's contact [cite: s01 ¶8-9] <!-- c:a1f3 -->
- X has been procurement director at Xinhua Printing since 2026-05 [cite: s02 ¶3] <!-- c:c07e --> <!-- supersedes: c:a1f3 -->
```

Correcting a state with `edit_claim` erases the previous state from the readable page — it survives only in git — and "when did this change, and on whose word" stops being answerable. **This is judgement, and it is the one judgement nobody downstream can make on the compiler's behalf: a contract that never says which of its facts are STATES gets corrections where it wanted history.**

The mechanism is not yours to restate: the predecessor stays byte-for-byte and becomes frozen — its text may never change again, and the tool face refuses an `edit_claim` on it, naming the successor instead; the successor gets a system-assigned anchor plus a `<!-- supersedes: c:xxxx -->` marker, keeps the predecessor's block form, and must carry a `[cite:]` of its own — a state change without new evidence is rejected at the write, not asked for in prose. Chains stay linear and acyclic: one claim supersedes one claim, and one claim has at most one successor.

What IS yours: **which of your families hold state that changes over time, and what counts in your domain as a new state rather than a correction.** A person's role, employer and contact channel are states; where they were born is not. A project's deadline, owner and status are states; the reason a decision was taken is not. Be concrete where the boundary is genuinely thin — "it was always 12, we mistyped 21" is a correction, "it moved from 12 to 21" is a new state — because the material usually says which, but only if the contract has told the compiler to look.

What it buys, with no further word in the contract: the **current view** of a document (its claims with no successor), the **history** of one fact (its chain, root to head), and — with the `time` component enabled — an **as-of** answer, walking the chain by each claim's cited-source date.

## 7. The `people` component: identities, aliases, and the terms that are neither

When the `people` component is enabled over one of your families, that family's documents carry two machine-readable frontmatter fields.

**`identities`** — `scheme:value`, the scheme coming from the source boundary exactly as the source contracts record it (`mailto:`, `im:`, `meeting:`), so the compiler never invents one. An identity is unique across the whole library: the gate rejects a second page claiming one. That uniqueness is what makes it a machine-readable **key** rather than one more name — with it, "everyone who…" is judged over a closed candidate set enumerated from L0, unbound identities included, instead of over whatever a search happened to return.

**`aliases`** — every form of address the material confirms is this person's. One person reaches a library under several: a Chinese name and an English one, a surname alone, a nickname colleagues use, a code name a project gives them. The field is where they all live, because it is what every later lookup resolves against — a question written in one form must reach a page written in another, and an unrecorded form is a page the question misses. The framework narrows that gap mechanically and does not close it: every people lookup also matches contact-book style — pinyin, the surname/given split, either order, initials — so 「可欣」 reaches a page titled `Kexin ZHOU` even though the page never says so. That is retrieval: it is ranked, it is labelled as a match rather than a declaration, and where several people match equally it hands back all of them. What the material confirms still belongs in this field, because a recorded form is exact, unambiguous and permanent. It holds only forms the material CONFIRMS, and confirming is your bar to set (below). The framework supplies the evidence and forces the question: under each source it states the address terms the whole library concentrates on the people present, and the gate requires each of them to end the round either recorded here or declined with `decline_alias(path, term, reason)`. **That question is asked once.** A decline is this round's answer and is stored nowhere — no claim, no alias, no field, nothing on the page — because a name that is not somebody's is not knowledge about them. What closes the question for good is the page being WRITTEN: the framework knows the day a term started being reported and the day the page was last committed, so a page written since has been shown the question and is never asked again, whatever it decided. Write the page in the round you decline in, and you are done with that term; decline in a round that writes nothing and the next one asks again, which is right — nothing was committed, so nothing was answered. Left to itself the round would answer neither, which is what a real library measured: a term reported under 31 sources for 88 days, never on the page, already used by ten other documents' claims.

An **honorific is usually not an alias**, and it is the case worth deciding deliberately. 「周总」 is title plus surname: it is genuinely how people address someone, and it is also how they address every other 周 with that standing — so it identifies a role in a conversation, not a person in a library. The ordinary outcome is `decline_alias(..., reason="honorific")` — the reason is what you tell the round; nothing is stored, the page included. Rule the other way when your material shows the form pinned to one person — the only 周 in the corpus, the form used of them in writing, the person using it of themselves — and say which way you want it decided in your contract text, because both readings are defensible and only one of them is yours.

Both belong to the document's **overview** — its picture of the subject right now — and are written whole by `rewrite_overview(fields=…)` / `set_fields`, exactly like the prose slots beside them. Nothing in the overview only grows: a field is a snapshot, and this round's judgement over what already stands there is what decides whether a value survives. That is the only reason a wrong one is repairable at all. There is no third field for the terms you decline, and deliberately none: the page records what is known about this person, not a memo about what not to ask again.

Three things about those fields are FACTS rather than judgement, and the framework refuses them mechanically — at the write face and again at the gate, over the pages a round actually touched. *Touched* means the round changed the page's body **or** its frontmatter, or created it: a compile that appends one claim to a person page and edits no field has written that page, and the page answers for what it declares. A page nobody wrote is left as it stands, so one old wrong page cannot block every later compile — and when a round does touch such a page, the repair costs one `set_fields`. An identity must be `scheme:value` and no two pages may hold the same one. **No page may bind two person ids that both SPEAK in one conversation** — taking a turn of their own is what makes them two people, whether or not either of them has a page you could have collided with. "Person id" is the channel's own handle for one participant: an IM `sender_id` and a meeting `speaker_id` are, an email address is not — one human writing from a work address and a personal one is ordinary, and the correct page binds both, so mail threads contribute nothing to this fact. **An alias may not be somebody else's name**: not another person page's alias, title or slug, and not a display name the sources record for an identity this page does not hold. A group chat titled "Yong BAI, Jie WANG, Fan WANG" is three people, and the page for one of them may not take the other two.

**The address-term line under a source in the compile task is a discovery prompt, not a finding.** It is arithmetic over turn structure — whom a turn addresses, who answers next — reported as a distribution over identities, and the term after an `@` may name a third person (`@X, how's Y doing?` addresses X and asks about Y). The framework's tool descriptions state the distribution and stop there, deliberately: **deciding when a term becomes a canonical alias is the contract's judgement, and this guide is where that judgement belongs.**

Write it as a bar the material has to clear. A term earns an alias when the person **answers to it repeatedly, across turns and across sources**, when they **use it of themselves**, or when **someone states the equivalence outright**. A single co-mention is not enough, and neither is a single adjacency: a nickname and a common phrase that whoever spoke next happened to answer have exactly the same shape inside one conversation. Nothing is lost by leaving a term unbound — it keeps being counted, and comes back under a later source with more support behind it once the library has it. Recording early still costs more than recording late: an alias the library reads as a confirmation is what every later lookup resolves against, and it stands until a round that touches the page decides otherwise.

Two labels appear on that line and they say how much weight a term carries. A **REPORTED** term has library-wide support concentrated on one target — enough occurrences, from more than one source, most of them pointing at the same identity, and used mostly at the vocative position (a term that lives mid-sentence is a topic, not an address, and is not reported however often it is answered). An **EMERGING** term is repeated in this source and not yet backed by the library. The reported one is what a page may act on; the emerging one lets the compiler watch a nickname form. Neither is a binding, and canonical always wins the tie: a confirmed alias is never overruled by a count.

## 8. The acceptance loop

A contract is not thought correct; it is **accepted** through rounds of use. One round:

```
build on an empty library → read the glance → ask real questions → judge →
revise the contract (new version) → rebuild → look again
```

- **Rebuild on empty.** A contract change shapes future compiles only and never rewrites existing canon, so the cleanest read of a revision is a fresh build.
- **Read the glance first.** Did the subjects that should exist get pages? Is there a page that collects everything? A crowd of single-appearance names each holding a page?
- **Ask the owner's own questions, with citations on.** Representative means derived from what this library will actually be asked — the uses the owner stated, the tensions their material keeps returning to — and each one aimed at something the contract decided, which is what makes a bad answer diagnostic rather than merely disappointing. What you are checking is not eloquence but whether **the facts the answer depends on are on the page** — and when an answer fails, whether the cause is *not recorded* or *not retrieved*. The two have entirely different fixes.
- **Verify placement, not string presence.** "The date appears somewhere in the library" is false comfort — after a year, almost every date appears somewhere. A fact counts as recorded when it hangs on the right subject, bound to the right object.
- **Judge structurally, and write the judgement down.** Change is not the goal; a better model for future use is. A well-reasoned "no change" is a good outcome and worth recording too. And never revise on the back of one or two questions — re-asking the same set flips a handful of verdicts either way; act on structural shifts (a whole question class improving, a subject's timeline connecting for the first time), not single-point noise.

It is finished when the modelling holds still under those questions — a round whose revisions no longer change what the library gets right — and the owner recognizes their own domain in the glance. Two or three rounds is what that usually costs; the cost is not the definition, and a library that still misses its owner's questions on the third round is not delivered because it is the third.

The ask-real-questions step also exists in mechanized form: the optional **coverage challenge** (see [configuration](../reference/configuration.md)) runs it after every compile — questions generated blind from the material and your contract, judged against the recorded claims, confirmed gaps fed back through one gated compensation compile. It does not replace this loop: the challenge audits recording coverage; only you can judge whether the model itself is right.
