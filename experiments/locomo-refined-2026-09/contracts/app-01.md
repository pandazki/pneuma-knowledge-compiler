---
skill_id: locomo-conversation-01
version: locomo-c01-v1
path_templates:
  - people/{slug}.md
  - companions/{slug}.md
  - threads/{slug}.md
  - events/{slug}.md
  - places/{slug}.md
  - objects/{slug}.md
---
# Caroline and Melanie's evolving personal history

Build a detailed, longitudinal record of Caroline, Melanie, and the independently evolving
subjects in their conversations. The permitted first-session sample shows support and identity,
education/career exploration, painting, self-care, and family activities. These are starting
signals, not a closed list: later material decides what else exists.

## Filing model

- `people/`: create Caroline and Melanie immediately. Create another person's page only when
  the material names them and gives a durable relationship, action, role, or repeated history.
  Record relationships, work and education, preferences, skills, health, values, commitments,
  locations, possessions, and dated changes about that person. Do not put another person's fact
  here merely because the page's subject heard it.
- `companions/`: one page per named animal with its person, species/breed when stated, history,
  traits, health, activities, and changes. Do not treat an unnamed pictured animal as owned.
- `threads/`: one page per continuing project, goal, job/career path, study path, hobby practice,
  support/community involvement, travel plan, or other effort that can change independently.
  Keep goals, beginnings, reasons, participants, steps, setbacks, decisions, and outcomes.
- `events/`: a discrete event earns a page only when it has several connected facts, stages,
  participants, or later consequences. Otherwise record it as a dated claim on the relevant
  person or thread. Never create one catch-all timeline page.
- `places/`: create a place page when a visit, move, repeated activity, or plan makes the place
  independently useful. Record who, when, why, what happened, and its significance.
- `objects/`: create a page for a named or repeatedly discussed possession, artwork, collection,
  vehicle, award, or other artifact. Record ownership, origin, appearance only when supported,
  dates, uses, changes, and emotional significance.

## Recording caliber

Record concrete facts likely to support later recall: exact names, titles, counts, ages, ranks,
dates, durations, locations, preferences, reasons, before/after states, quoted wording when it
matters, and explicit negative facts. Preserve who asserted a fact. A suggestion is not a plan,
a plan is not an outcome, praise is not evidence of achievement, and a pictured example is not
automatically the speaker's possession. Keep uncertainty and disagreement rather than resolving
them by guess. Omit greetings, filler, generic encouragement, and repetitions that add no fact.

The `[caption]` line is a derived visual description and may support an observation with that
status. `[query]` and `[image]` URL lines are retrieval/context aids, not proof by themselves.
When dialogue explicitly identifies what an image depicts, combine the statement and caption;
do not replace the speaker's account with the caption or infer details neither supplies.

## Time, state, and correction

Anchor every relative expression to the session date and retain the original wording. Resolve
an exact day only under an unambiguous calendar convention; otherwise record the anchored span
without invented endpoints. Record beginnings as carefully as endings so order and duration
remain answerable.

Jobs, roles, residence, ownership, project status, deadlines, scheduled plans, relationships,
health/education status, and active preferences can change. Use `supersede_claim` when later
evidence changes a previously true state; use `edit_claim` only when the earlier claim was wrong
when written. Never silently turn a future intention into a completed event.

## Overview wording

For a person, define their role in this conversation and summarize current work, commitments,
and life threads. For a thread or event, summarize current status/outcome and what remains open.
For a place, companion, or object, define its connection to the people. Rewrite an overview only
when that current picture changes, and never let it sound more certain than the ledger.

