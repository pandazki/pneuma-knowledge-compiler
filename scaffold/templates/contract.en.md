---
skill_id: {{SKILL_ID}}
version: app-v1
path_templates:
  - subjects/{slug}.md
---

# Compile contract: a source-grounded working library

## Purpose and subject boundaries

Build a library that helps its readers recover what happened, understand current state,
explain decisions, and act on commitments. The library can concern people, a team, a
research topic or an organization; do not assume its tenant identifier names a person in
its sources. An unstated owner profile is not missing evidence to invent.

Start with `subjects/{slug}.md`: one page per independently evolving subject, such as a
person, project, organization, artifact or recurring topic. Open a page when the material
provides useful knowledge about that subject. Reuse it across sources and names; preserve
source-supported aliases and the evidence for identity. Similar names alone do not establish
identity. Do not create one page per import, generic baskets of unrelated facts, or empty
pages for names that only pass through the conversation. Record a relationship with its
participants on the relevant subject page and link an existing related page when useful.

## Admission follows future use

Retain information whose loss would obstruct an action, judgment, explanation, collaboration
or review. A project implies a progress record; an event implies a timeline; a decision
implies its rationale and constraints. Preserve the details those uses need: who did or said
what, to whom, when, where, why, the result, and any unresolved obligation — where supplied.
Specific names, quantities, exceptions and negative facts can be more useful than a broad
summary. Keep distinct events distinct, even when they share a topic.

Do not compress away a useful fact merely because it seems too small for the overview.
The ledger retains the history; the overview gives a concise current picture, drawing on
that ledger. Greetings, repetition and unsupported speculation usually need no canonical
claim; their raw source remains available. Read the actual source before deciding that a
passage adds nothing. An empty patch can be correct, but its reason must fit the material.

## Evidence, change and uncertainty

Separate observations, reported claims, intentions, decisions, attempts and outcomes.
Attribute statements to their speaker or author. A recommendation is not acceptance, an
attempt is not completion, and a caption or OCR result is derived evidence, not proof that
the original image was inspected. Preserve disagreement and qualifiers rather than silently
choosing a confident version. An inference must name its basis and remain an inference.

If an earlier claim misread its evidence, edit it with the supported correction. If the
world changed after a correct claim, supersede it and retain the predecessor as history. For an `owner-dialogue/v1` correction, use what the owner actually
said, with its citation; do not give the steward's wording the owner's authority. Distinguish
a changed state from a correction of a mistaken record. Refresh affected overviews and
relationships after either. An overview must not strengthen the claims it summarizes.

## Time

Distinguish the time of the event, the time of the statement, and the time of import.
Resolve relative expressions against the source's own occurrence context, keeping the
original expression. Convert to an exact date or interval only when that context and the
calendar convention determine it; otherwise preserve the anchored expression and uncertainty.
A date without a clock time or timezone does not authorize inventing either. Preserve
planned dates as plans, and past events as past events.

## Non-admission and customization

Do not copy credentials or authentication secrets into canonical claims. Exclude unrelated
private details that serve none of the library's stated uses. This admission policy is not
an ingestion filter: material that must never be stored or sent to a model must be removed
before import.

This is a usable starting contract. After reading representative sources, specialize the
purpose, subject families, useful detail and exclusions for this library. Keep the body and
`path_templates` consistent. Change the contract because source inspection and intended uses
justify it; do not encode benchmark questions or expected answers into it.
