# OPC 84-day v2: group QA rubric and fail-closed gate

This rubric governs authored 2- or 3-day groups before any source-contract JSON is produced. A group is an original body of source material, not a parameter set. Code may validate, calculate reports, and assemble accepted authored content; it must not generate, expand, paraphrase, cycle, or copy body text.

## Non-negotiable safety and provenance

All corpus content, names, addresses, file names, companies, projects, identifiers, timestamps, and attachments are synthetic. Do not put user credentials, API keys, access tokens, passwords, cookies, real private messages, real personal data, or brand-sensitive/confidential material into the corpus. Synthetic email addresses must use a reserved test domain (for example `example.test`), never a real organization or person.

The Schema records final, complete source text. It deliberately has no expansion controls. Do not add an alternate spelling of an expansion control to a group document or an assembly input.

Every source, and every visible content unit inside it, has a stable authored ID, occurred-at timestamp, role, `signal`/`noise`/`ambiguous` class, and links to story beats, facts, and continuity IDs. IDs are immutable once a group enters review. A shared `authored_id` is a hard error unless it is the same serialized unit being referenced rather than re-authored.

Each group also includes at least two `research_context` records from topic-led web research. Each records the topic query, URL, title, access date, source credibility/tier and rationale, applicability scope, author-written fact summaries, fictionalization boundary, and affected authored IDs. They supply facts and structural patterns, not prose to transplant. Never move a real company, product brand, organization, person, private event, or sensitive claim directly into the synthetic story; abstract the input into synthetic setting and detail.

## Required inputs and outputs

For group `G`, QA consumes one document conforming to `group-content.schema.json`, the approved story ledger through `G`, and all previously accepted group documents and QA reports. Each group has at least two actual source families and at least one source classified `signal`; its four source-array keys remain present so absence is explicit. It emits:

- `qa/group-G.json`: machine-readable evidence for every gate, measurements by source type, detector version/configuration, matched IDs and spans, reviewer decisions, and a final status.
- `qa/global.json`: the same evidence over all accepted groups, including the cross-group index, timeline, fact ledger, unresolved-continuity ledger, and per-source-type summaries.
- `qa/returns/G-<revision>.md`: a precise return memo: failed gate, authored IDs/spans, why the material fails, required revision, and whether a new review is needed. It must never propose mechanical text substitution.

Missing, unreadable, stale (input hash differs), or internally inconsistent evidence is a failure. Reports must preserve raw detector matches; a pass/fail summary alone is insufficient.

## State machine and write boundary

`draft → structural_pass → content_review → accepted → assembled → ingested`

- `draft`: authored group only; nothing may be assembled.
- `structural_pass`: schema and deterministic checks pass; it is still not eligible for assembly.
- `content_review`: all automated content gates pass and named human/subagent review is underway.
- `accepted`: automated gates and independent human/subagent sign-off both pass. Only this state is an assembly input.
- `assembled`: source-contract payloads have been derived without altering authored prose; mapping evidence identifies every output item and authored ID.
- `ingested`: the ordinary ingestion result is retained with the assembled hash.

Any failed check, revision, source-text change, ledger change that affects the group, or mapping change returns the group to `draft`. A group cannot skip a state. Assembly and ingestion reject non-`accepted` inputs; an unreviewed exception is not available.

## Gate 0 — structural and contract-mapping checks

Validate Draft 2020-12 Schema first. Then fail if any of the following is true:

- `day_count` is not two or three, `starts_on`/`ends_on` disagree with it, or any occurred-at timestamp falls outside the group window/timezone.
- Fewer than two source families have a source, no actual source is classified `signal`, an actual source's required complete body is empty, a referenced actor/thread/parent/message is absent, or a stable ID is duplicated.
- Every document `visible_blocks` item must occur verbatim in the corresponding `full_markdown`, in declared block order. A missing/out-of-order block or repeated `block_id` fails Gate 0. Such a block is excluded from all substance and noise statistics even though the mapping failure already returns the group.
- An official-contract mapping drops a required official field, invents a body string, changes authored prose, or fails to map each output content unit back to an authored ID. Required mappings are meeting `utterances → segments`; document `full_markdown → content`, path/frontmatter/tags/links unchanged; IM conversations/members/full messages/thread/reactions unchanged; email threads/full messages/from-to-cc/subject/RFC822 headers/attachments unchanged.
- The group needs an ID outside its declared allowed beats, known facts, or open/new continuity scope. New facts and newly opened continuity must be recorded in the approved ledger before acceptance.

Schema validation does not establish cross-reference membership, calendar arithmetic, ID uniqueness across nested arrays, Markdown block coverage, or semantic quality. The deterministic checks above do.

When `daily-beats.json` is supplied, deterministic QA also requires the group window to match that ledger group's exact three dates, source counts to equal the three daily `source_plan.type` counts (with `IM` normalized to `im`), and scope/links to remain within the permitted D/F/C truth at the final day. Its QA JSON preserves all three ledger rows, expected/actual source counts, permitted IDs, and every violation; no future fact or continuity may be admitted by a broad group-level allowance.

## Gate 0.5 — research grounding

Each group must have at least two reachable research records, with the topic query, URL, title, access date, credibility rationale, applicability scope, concise author-written fact/structure summaries, fictionalization boundary, and one or more existing `applied_authored_ids`. Prefer official and first-party material (standards bodies, public agency publications, primary research, official product documentation, or source-owner records); technical claims must use primary sources only. Record the source type and why it is appropriate in `qa/group-G.json`.

For every research record, a reviewer traces each applied authored ID to a material change in the source's shape or detail: for example, a plausible meeting constraint, document convention, communication cadence, terminology boundary, or operational friction. A link that does not change a concrete authored unit is decoration and fails. `author_fact_summaries` must be independent short summaries of facts or structure, never webpage quotations; the 280-character schema ceiling is not a quotation allowance. The fictionalization boundary must say what cannot be carried from the source into the invented setting.

The deterministic gate compares every research summary with every authored prose unit. It fails long continuous overlap (80 normalized characters or more) and high 5-gram Jaccard overlap (0.55 or more), emitting the research record, authored ID, and matched spans. It checks only text retained in the research ledger, so it cannot prove a summary was independently written or detect copying from an unrecorded page. An independent reviewer must therefore open each cited source, inspect the page, and record the manual comparison before acceptance.

Return the group immediately for copied or closely paraphrased webpage sentences, inaccessible/unstable evidence without a recorded replacement, non-primary technical material, unsupported factual claims, research that only validates a finished story after the fact, real personal/private data, or direct use of real companies, brands, organizations, or people. Research grounding is about realism and constraint, not importing a real-world narrative.

## Gate 1 — minimum source substance

The deterministic character-count policy is `mapped-visible-body/v2`:

- Meeting counts only utterance `text`; IM counts only message `full_text`.
- Email counts only newly authored `full_text`, excluding RFC822 headers, quote prefixes, and quoted/forwarded reply sections.
- Document library counts only non-heading `visible_blocks` that can be located verbatim and in order in that document's `full_markdown`. It renders those mapped blocks to text before counting: Markdown headings, frontmatter, fences, list/task/quote/callout markers, table separators/pipes, link destinations, and formatting glyphs do not count.
- The count is the Python/Unicode string length of the resulting visible body, including ordinary punctuation and the single spaces retained when structural whitespace is collapsed. Source titles, paths, IDs, JSON syntax, frontmatter, headers, reactions, attachments, and unmapped blocks never count.

QA reports both raw evidence (`raw_full_markdown_chars`, `mapped_raw_chars`, `unmapped_visible_block_chars`) and the gate value (`body_chars`). Count body separately for every source family; do not offset a weak family with a long source elsewhere. For example, G01's former 2,801 figure counted 914 characters from orphan document blocks. The only eight mapped document body blocks total 886 raw characters before Markdown structure is removed; with 1,001 IM characters, the group is at most 1,887 and therefore cannot satisfy either the 1,800 document floor or the 2,400 whole-group floor.

Apply a source-family floor only when that family actually appears in the group (one or more sources). An absent array is not a zero-valued pass and cannot be used to dilute any measurement. Each present family fails below either its source total or its count:

| Source family | Minimum authored body | Minimum units | Specific floor |
| --- | ---: | ---: | --- |
| Meeting | 1,200 characters | 1 meeting / 12 utterances | 2 actual speaking participants |
| Document library | 1,800 characters | 2 documents / 8 visible blocks | 2 distinct paths |
| IM | 1,000 characters | 2 conversations / 18 messages | 3 human senders across the archive |
| Email | 1,200 characters | 2 threads / 4 messages | 3 distinct senders or recipients |
| Whole group | `max(2,400 characters, ceil(0.85 × sum of the floors for present families))` | at least 2 source families | every present family passes its own floor; no empty family is counted |

These are floors, not a request to inflate. A short source that is inherently authentic must be marked `ambiguous` and receive a documented human waiver; absent a waiver it fails. The default 84-day plan is 28 three-day groups. A mixed 2/3-day plan is allowed only when the sum of all group day counts is exactly 84, and every accepted group must meet the floors for its actual sources.

The meeting participant floor is a generic authenticity check, not a global three-person quota. When a beat requires a deeper or multi-party exchange, `daily-beats.json` and the independent reviewer enforce that requirement; do not add an irrelevant third speaker merely to satisfy deterministic QA.

## Gate 2 — repetition and near-copy detection

Run all detectors over normalized body text, preserving a mapping to raw spans. Run separately within each source family, within each artifact, against prior groups, and across the full accepted corpus. A global average never clears a family or artifact failure.

Normalize only for detection: Unicode NFKC, case folding, collapsed whitespace, standardized punctuation/quote characters, and replacement of synthetic address/date/ID tokens with typed placeholders. Retain exact raw text for the verdict. Exclude only declared structural repeat zones described below.

| Detector | Group threshold | Global threshold | Fail condition |
| --- | ---: | ---: | --- |
| Exact body duplicate | 0 allowed | 0 allowed | identical non-structural body, whole unit or span ≥80 characters |
| Normalized body duplicate | 0 allowed | 0 allowed | equal after the stated normalization, span ≥80 characters |
| Word n-gram overlap | ≤0.18 pairwise Jaccard | ≤0.14 against any prior group | 5-gram overlap above limit for any pair in the same source family |
| Local self-repetition | ≤0.12 per artifact | n/a | non-structural 5-gram overlap across two distinct utterances/messages/blocks/bodies exceeds limit |
| Near semantic duplicate | ≤0.86 cosine | ≤0.82 against prior groups | embedding similarity above limit after candidate lexical match, confirmed by reviewer |
| Reused beat expression | 0 for `signal` | 0 for `signal` | same fact/beat is expressed with materially matching wording in two artifacts without a required explicit quote |

For short units, compare concatenated chronological windows of up to three adjacent units as well as individual units. This prevents a copied paragraph from being split among chat messages. Similarity is a candidate detector, not an averaging metric: all hits at or above a threshold fail unless the reviewer classifies the exact span as an allowed structural repeat and records it in the report.

Allowed structural repeats are limited to: fixed Markdown headings from an approved heading registry, RFC822 header *names* (not values), a correctly attributed quoted-email block, legally necessary footer text, and literal thread references required by the source format. The registry must be small and versioned. Repeated heading/body text, a copied email body disguised as a quote, repeated subject wording used as content, generic "status/update/next steps" prose, and recurring system-notification wording are substantive repetition and fail.

## Gate 3 — chronology, facts, and continuity

Build a total timeline from every `occurred_at`, then review it in source order and story order.

- Source timestamps must be plausible for the source type, ordered within a meeting/thread/conversation, and compatible with edits, replies, document modifications, and cited earlier events.
- A fact is allowed only if it is in `known_fact_ids`, is introduced by this group's approved beat, or is explicitly uncertain/rumored and linked as such. Later outcomes, hidden causes, final decisions, and unearned certainty are hard failures.
- Each open continuity must either remain open with a credible reason, gain a bounded complication, or close only when the story ledger permits it. It cannot disappear silently. New continuity must be observable in a source artifact and have a ledger ID.
- No group may resolve more than one major continuity or introduce more than two major facts unless the approved ledger explicitly identifies a milestone exception and a reviewer signs it. A major decision that immediately succeeds without evidence of constraint, disagreement, delay, cost, or uncertainty fails the pacing review.

## Gate 4 — story movement, voices, and noise

Review each group as a slice of lived work rather than a report of plot.

- **Pacing and setbacks:** at least one `signal` artifact must create or sharpen a question, constraint, disagreement, dependency, delay, trade-off, or partial reversal. Across every rolling three-group window, at least two groups must contain a materially evidenced setback or unresolved decision. Do not manufacture drama; record genuine incompleteness.
- **Character voice:** for every recurring human with at least six units in the corpus, compare lexical habits, directness, detail level, reaction habits, and decision posture with their prior units. A reviewer must flag indistinguishable voices, omniscient exposition, or people who speak only in clean plot summaries. Voice consistency must not become catchphrase reuse; Gate 2 still applies.
- **Noise mix:** per group, at least 15% and at most 40% of counted body characters must be `noise` or `ambiguous`; at least 40% of that subtotal must be lived-work noise (scheduling friction, work-in-progress, mundane coordination, small errors, personal-but-non-private texture, or incomplete handoffs), not system output. System noise may be at most 35% of all noise/ambiguous characters. A noise unit that advances or explains the main beat must be tagged `signal`/`ambiguous`, not used to satisfy the noise quota. At least one noise unit per group must have no direct main-line payoff within that group or the next two groups.
- **No cosmetic noise:** boilerplate deployment notices, repeated reminders, and interchangeable "FYI" exchanges fail even if ratios pass. Noise must vary by source, speaker, setting, and consequence.

## Gate 5 — source-specific reality checks

Every source family that actually appears must pass its own checklist; pass counts are reported separately and no present family may be waived by corpus-level averages.

| Family | Required review evidence | Automatic return triggers |
| --- | --- | --- |
| Meeting | A real conversational shape: at least one clarification, interruption/overlap, correction, or misunderstanding; at least one turn that does not resolve cleanly; participants have different knowledge/authority; agenda is not simply replayed as transcript. | serial monologues, every question answered immediately, one speaker carries ≥75% of body without a documented meeting form, or recurring meeting skeleton/text. |
| Document library | Obsidian-like paths, frontmatter that agrees with the body, document-local links/tags, revision traces or imperfect notes where appropriate, and blocks that reconstruct the supplied full Markdown. | identical note outline across documents, generic polished memo voice everywhere, path/frontmatter/body conflicts, or blocks absent from full Markdown. |
| IM | Conversation type and membership fit the exchange; time cadence has believable gaps; threads actually reply to a root; reactions are sparse and contextual; short turns, edits, acknowledgements, and unresolved handoffs appear naturally. | chat written as email, every message is plot exposition, reaction spam, broken thread IDs, or cloned channel exchanges. |
| Email | RFC822-like headers and address roles agree with typed fields; subject/thread/reply references make sense; recipient lists evolve plausibly; body includes salutations/quoting only when appropriate; attachments are motivated. | email body copied into a thread without an explicit attributable quote, headers contradict message fields, every thread ends with a decision, or attachments exist solely as plot labels. |

## Human/subagent review card

An independent reviewer who did not author the group completes this card after automated gates pass. Reviewers inspect raw full bodies and detector spans, not summaries alone.

| Check | Reviewer result |
| --- | --- |
| Schema/mapping, timestamps, IDs, and four-family source floors pass | pass / return |
| No prohibited data or brand-sensitive material | pass / return |
| Each detector hit is either absent or a registered structural repeat | pass / return |
| Facts, continuity, and pacing obey the ledger | pass / return |
| Voices are differentiated without recycled phrasing | pass / return |
| Noise is lived, varied, and not mechanically instrumental | pass / return |
| Meeting, document, IM, and email each look native to their medium | pass / return |
| Reviewer name/agent, UTC timestamp, input hash, and rationale attached | required |

Any `return`, missing rationale, unresolved detector hit, or disagreement between reviewers is a failure. The group receives the return memo and returns to `draft`; the author revises whole affected units as needed, retains new stable IDs for new content, and repeats every gate. Do not patch a failed group by duplicating an approved artifact, swapping names, or adding filler.

## Global acceptance gate

Before the first assembly and after each accepted group, rebuild `qa/global.json` from scratch. Global acceptance requires every group to be `accepted`, all cross-group detector thresholds to pass per source family, a collision-free authored-ID index, a coherent 84-day timeline, an up-to-date fact/continuity ledger, and no present source family below its group floor in any group. Every consecutive three-group window must contain all four source families at least once; a window that lacks one fails even when its total character count is high. Global source counts and density are set by the approved story beats, not by a fixed quota per group.

Source density may have deliberate low valleys, weekend gaps, or a single-source absence within a group; an eventful period may use more artifacts. Reject a plan that mechanically gives every group the same number, order, or near-equal character share of source families, including a recurring four-source bundle. The global report must chart source-family presence and body characters by group so reviewers can distinguish story-driven rhythm from uniform coverage. A later group that causes a prior-group cross-group failure returns both affected groups to `draft` for review. The global gate is fail-closed: missing evidence, a timeout, an unavailable semantic detector, or a detector configuration change means no assembly or ingestion.
