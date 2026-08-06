---
# The machine-readable half of the contract: skill identity plus the path templates of the
# subject families. These correspond one-to-one with the families in section 1 below.
skill_id: lcr-07-knowledge
version: lcr-07-v1
path_templates:
  - people/{slug}.md
  - threads/{slug}.md
  - timeline/{slug}.md
  - things/{slug}.md
---

# What this library remembers

## 0. Whose library this is, and what it is for

This library holds one long-running two-person conversation: **James** and **John**, talking
across 31 sessions between 17 March 2022 – 7 November 2022. The material arrives one session at a time and
never stops being about the same two lives, so the library's job is to be the memory of that
relationship: who did what, when it happened, and how each thread moved between one session
and the next.

Assume the questions asked of this library later will be specific and factual — *when* did
that happen, *who* was it, *which one* of the two, *how long* between the two events, *what
changed since*. Answering them depends on the fact having been recorded, so this contract is
deliberately dense: a concrete fact about either speaker, about someone in their circle, or
about a named object, place or event, is worth recording even when it feels small in the
moment. Compression is not the goal here; retrievable specificity is.

James's side of it runs through programming (Python and C++, a website, game mods), two dogs named Max and Daisy, a dog-walking and pet-care app idea, and a childhood comic he wants to turn into a computer game; bowling; a wallet stolen at a slot machine.
John's side runs through a programming class he signed up for, older HTML/CSS experience, VR, and an intention to start running.
Recurring named things to expect: Max and Daisy; the dog-walking app; the indie game from the childhood comic; the named games (The Witcher 3 and others).
More will arrive that is not listed here — these are the threads visible at the outset, not a
closed list. Open new subjects as the material introduces them.

## 1. Subject families: what gets its own page

Four families, matching the `path_templates` above.

**`people/{slug}.md`** — one page per person. James and John each have one from the start.
Anyone else the two of them talk about — family, friends, colleagues, coaches, agents, a
partner, a child — gets a page the first time a concrete fact is attached to them (a name plus
a relationship, a job, an event they were part of). A person mentioned only as a passing noun
with nothing true attached to them stays in the raw material. What a person's page collects:
who they are, how they relate to James or John, and the facts that belong to *them* — their job,
their family, their health, their possessions, their history. Record every alias, nickname,
diminutive or spelling variant on the page of the person it belongs to; the two speakers
shorten each other's names and other people's names constantly, and a name split across two
pages is a subject silently turned into two.

**`threads/{slug}.md`** — one page per thing that keeps developing: a job or career move, a
project, a business, a course of study, a hobby taken up, a health situation, a house move, a
trip being planned. A thread page is the running record of that one thing: how it started,
each state change with its date, decisions made and the reasons given, and how it stands now.
Open a thread the first time the material shows it moving, not the first time it is wished
for. One thread page is reserved for the two of them together — the plans they fix, the
meet-ups they agree, the recommendations one makes to the other and whether the other took
them up.

**`timeline/{slug}.md`** — the chronological spine, one page per calendar month, slug
`YYYY-MM`. Every dated happening in that month gets a line: what happened, who it happened to,
the absolute date, and a pointer to the person or thread it belongs to. This family exists
because "when" and "how long between" questions are answered from a spine, not by scanning
every page. A fact recorded on a person or thread page and *also* dated belongs in both
places — that is deliberate duplication, not an error.

**`things/{slug}.md`** — one page per named non-person subject with a story of its own: a
pet, a vehicle, a home, a piece of art or writing, a book, a film, a game, a venue, a trail, a
park, a keepsake. Open a page when the thing is named and something is true of it beyond its
existence. Keep the two speakers' possessions rigorously apart — where both own something of
the same kind, they are two subjects with two pages, never one merged page.

**Where the families touch.** A fact about a person goes on that person's page; a fact about
how something progressed goes on its thread page; a fact about the object itself goes on its
things page; anything with a date also gets a line on the month's timeline page. When a fact
would fit two families, record it in both rather than choosing — but never move a fact onto
the wrong subject to keep a page tidy. Misattribution is the expensive failure here: these two
speakers lead parallel lives full of the same kinds of things — both may have pets, both may
have jobs changing, both may travel — and a fact filed against the wrong one of them looks
perfectly healthy in the library and answers every future question wrongly.

## 2. What is worth recording

Worth it, in this material: a project step with its date (a mod released, a feature decided, a collaborator invited); which language or tool was used for what; a named pet and what is true of it; an incident with a date and a consequence; a plan the two of them fixed to a specific day.

Not worth it: mutual enthusiasm about games with no fact; "maybe someday" ideas nobody acted on.

The test for anything else: would someone reading this library a year from now need this fact
to answer a question about James, John, or someone in their circle? In a chat log the answer is
yes far more often than intuition suggests. Numbers, names, counts, ages, durations, places,
titles, prices, model names, breed names, street names — record them as stated. A fact that
arrives as an aside ("I've had them three years", "that was the year I turned fifteen") is
exactly the kind that gets asked about later, and exactly the kind a summarising instinct
drops. Do not drop it.

Two specific obligations that are easy to lose:

- **Beginnings, not just outcomes.** When something started, who started it, who introduced
  whom, which came first. Any question about duration or order is answered from the start
  point, and the start point is what compression eats first.
- **Chained facts.** A handover, a purchase, a move or an introduction owes several facts at
  once — who, from whom, to whom, when, and what happened to the thing before. Having recorded
  one of them, ask what else is needed to answer a question about it, and record that too.

## 3. Evidence and how to state it

Both speakers are first-hand authorities on their own lives and nothing more. Record who said
it when it matters: a fact about James's job stated by James is direct; the same fact relayed by
John is second-hand and should say so. A plan is not an event — "we'll go next Friday" is an
agreement made on the day it was said, and it becomes an event only when a later session says
it happened. Keep the two separate and let the later session update the thread. When a
subsequent session contradicts an earlier one, record the newer fact with its date and keep
the earlier one with its own date rather than overwriting it; the change itself is often what
gets asked about.

Some messages carry an image. In the source these appear as indented `[images]`, `[caption]`
and `[query]` lines attached to the message above them. Treat the caption and query as a
description of what the speaker showed, attributed to the speaker who shared it — "James shared
a photo of X" — and use it the same way as spoken content when it carries a fact. Do not
present a description of an image as if the speaker had said those words.

## 4. Time

Every session carries an absolute date. Normalise every relative expression against the date
of the session it was said in — "yesterday", "last week", "next Friday", "last year", "three
years ago", "when I was fifteen" — and record the absolute date alongside the speaker's own
words. Both parts matter: the absolute date makes the fact retrievable, and the original
phrase preserves what was actually said.

When a relative expression resolves only to a range ("a few years ago", "last summer"), record
the range and its anchor date rather than inventing a precise day, and say which session it
was said in. Where an age is given instead of a date, record the age as stated and the
computed year only if a birth year is known — do not guess one. An event mentioned as
upcoming carries two dates: the day it was said and the day it is meant to happen; keep both.

## 5. Privacy and what never gets recorded

The framework's red lines hold: no credentials, tokens or identity numbers. Beyond that this
is a private conversation between two friends and the library is the memory of it — record
what they tell each other, including personal, medical and family matters, because those are
precisely the threads they will be asked about later. Do not, however, invent connective
tissue: if the material does not say who someone is or when something happened, the absence is
itself the record.
