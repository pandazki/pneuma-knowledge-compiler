---
skill_id: personal-projects
version: app-v1
path_templates:
  - projects/{slug}/overview.md
  - projects/{slug}/evolution.md
  - projects/{slug}/features/{slug}.md
  - projects/{slug}/decisions/{slug}.md
  - path: owner/views/{slug}.md
    owner_voice: true
  - memory/people/{slug}.md
  - memory/topics/{slug}.md
contract_rules:
  - contract.rule.citation_granularity
  - contract.rule.citation_shape
  - contract.rule.strength_labels
---

# Personal projects

The subject comes first: what the Owner's projects are, whom they serve, their top-level
design and principles, their key features, and how they evolved. Second comes how the
Owner thinks about them. The detailed making process comes last, as searchable evidence.
A session is material for these subjects; it is never itself a subject deserving a page.

## Project families

Use one stable project slug across its pages. A recorded working directory identifies the
project the session belongs to; a similar name or shared remote alone does not establish
that two projects are one. A project earns an overview once the material establishes a
purpose and continuing work. Empty family pages and pages for passing mentions add nothing.

- `projects/{slug}/overview.md` collects the project's purpose, audience, top-level design,
  scope, principles and current state. Its expected `definition` says what it is and for
  whom; its expected `summary` says how it is designed, what is decided and what remains
  open. `introduction` gives its origin; `connections` leads to the feature, decision and
  evolution pages that explain it. Rewrite the picture when purpose, design or state
  changes, not whenever another implementation session adds claims. Implementation steps
  and every feature's details do not belong in this head.
- `projects/{slug}/evolution.md` begins when a dated beginning, milestone, version or turn
  in direction is supported. Collect those events in chronological order, each with its
  date, what changed, why it matters and the resulting state. Record beginnings as well
  as completions. Link the feature or decision that explains a turning point; do not
  repeat its whole account. The date of a session is evidence of when something was
  reported, not automatically the date of an earlier release. With an unknown event date,
  keep the report date and label the event date unknown rather than inventing it.
- `projects/{slug}/features/{slug}.md` is one key feature that can evolve independently.
  Open it when a capability's user problem, purpose and a consequential design choice
  become clear. Collect what it does, for whom, why it exists, the decision that shaped
  it, acceptance conditions and substantive changes. A file, helper function or isolated
  bug fix does not earn a feature page. Put a small capability in the overview until its
  independent lifecycle warrants a page.
- `projects/{slug}/decisions/{slug}.md` begins with an explicit consequential choice.
  Collect the question, chosen alternative, alternatives actually considered, reason,
  constraints, decision date and who accepted it. Unknown alternatives or reasons remain
  unknown. A proposed option is not an accepted decision. A reason affecting one small
  feature can stay with that feature; a choice whose rationale will be revisited earns
  its own page and links back to the affected subjects.

The making process gets **no page**: which file was edited when, which command ran, which
test failed, incremental status chatter and per-session summaries stay in L0/L1, retrievable
and citable as evidence under the subjects above. A lasting finding from a failed test may
explain a design decision; the sequence of retries itself is not that decision.

For example, Mei LIN chooses local storage for momo because offline use is essential:
record the design and its reason on momo's pages. An agent edits a file and runs three
commands: no new subject and no process log in canonical.

## The Owner's views

`owner/views/{slug}.md` holds one principle, taste, insistence or recurring judgement that
will inform future choices. An explicit durable statement can earn a page immediately;
otherwise wait for repeated substantive judgements. Collect the Owner's position, its
scope, their stated reason and exceptions, and changes in that position. Project-specific
acceptance criteria belong to that project; a judgement used across choices belongs here.

The creation template for `owner/views/{slug}.md` carries this frontmatter:

```yaml
owner_voice: true
```

Claims on these pages may cite **only the Owner's own turns**. An agent's description of
the Owner's taste, a quoted third party, and the Owner relaying a proposal are not the
Owner stating that view. The Owner saying “I want momo to work offline because I use it
without a connection” supports their preference; an agent saying “Mei prefers offline
software” does not. The library's owner-voice gate checks the speaker of cited evidence;
the judgement here is whether those words actually express the Owner's own position.

## Evidence and change

A source whose metadata carries `continues` is the next part of an ongoing session.
Read the project and Owner-view pages built from the earlier part first, then work from
that previous result plus this part's turns. The earlier transcript text is not re-read.
`from_turn` identifies this part's first retained turn and `part` numbers the parts. Each
new claim cites the source part containing its evidence; a continuation link alone is not
evidence, and earlier claims keep their original citations.

Owner turns establish what the Owner asked, accepted or thought. Agent narrative is
attributed evidence of what was done and of the project's reported state, never evidence
of what the Owner thinks. An agent saying a feature shipped remains a reported completion;
it does not establish Owner acceptance. A tool action stub records that an action was
requested, not that it succeeded. Do not infer an outcome from a missing tool result.

Distinguish observations, explanations, hypotheses, proposals, decisions and acceptance.
Metrics carry their definition, sample, conditions and scope. Negative findings deserve
space when they change future action; retries and transient failures do not. Commitments
and decisions use `【firm】` for confirmed choices with responsibility and conditions,
`【forming】` for a direction still missing a key condition, and `【loose】` for unaccepted
proposals or hypotheses.

Project scope, status, release targets, feature behavior and the Owner's current position
are states: a later change calls for `supersede_claim`, retaining the earlier state and
change date. A misattributed speaker or a number that was already wrong calls for
`edit_claim`. A decision's original reason stays historical even when a later decision
reverses it. Anchor relative dates to the source's occurrence date, retain the original
phrase, and resolve exact endpoints only when unambiguous.

## Other personal material

- `memory/people/{slug}.md` accumulates a recurring collaborator's relationship to the
  Owner, roles, responsibilities, commitments and confirmed aliases. Open it when the
  relationship has substance and a future, not for every mentioned name. Record who handed
  a responsibility to whom and when; project-wide facts stay on the project. Similar names
  do not merge identities; a repeated form of address or an explicit equivalence may.
- `memory/topics/{slug}.md` collects a recurring non-project subject with lasting use for
  the person. Open it when substantive material establishes that use. It holds supported
  knowledge and unresolved questions about that subject, never a catch-all for transcripts,
  discarded implementation detail or an alternative home for Owner views.

Research and chat sessions are index-only: nothing to compile unless the Owner states a
view worth keeping. A pile of search results or the agent's research narrative earns no
page merely because it is long. An Owner view from that material follows the same
owner-only evidence rule; all other conversation remains searchable. Meeting notes,
documents and other personal sources can still build the people and topics families.

Keep secrets, credentials and identity numbers out of canonical. Preserve attribution
and material uncertainty; scattered remarks do not establish a diagnosis, asset position
or legal conclusion. The useful result is a readable project and the Owner's actual
judgement, with evidence available beneath each, rather than a transcript retold.
