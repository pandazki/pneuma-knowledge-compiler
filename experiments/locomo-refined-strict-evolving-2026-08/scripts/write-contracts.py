#!/usr/bin/env python3
"""Preparation phase: write the ten compile contracts, one per conversation.

Each contract is authored from that conversation's first session plus its structural
fields (session count, speaker names, date span) — nothing else was read. The shared
skeleton reflects judgements that hold for all ten (a two-person long-horizon chat log
arriving session by session); the per-conversation blocks are the ten bets.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path("/data/qiwei/lcr-final")

# (project, speaker_a, speaker_b, span, sessions, a_lines, b_lines, named_objects, worth, not_worth)
CONVS = [
    dict(
        n="01", a="Caroline", b="Melanie",
        span="8 May 2023 – 22 October 2023", sessions=19,
        a_lines="an LGBTQ support group and what it changed for her, self-acceptance, "
                "continuing her education, and a move toward counselling / mental-health work",
        b_lines="raising kids alongside a demanding job, painting as her outlet "
                "(a lake-sunrise canvas she painted the year before), swimming with the kids",
        objects="Melanie's lake-sunrise painting; the support group itself",
        worth="Caroline saying which career direction she is now pursuing and why; "
              "Melanie naming when she painted a particular canvas; a support-group session "
              "attended on a stated day and what came out of it; either woman's stated feeling "
              "about a concrete event (it is the substance of this friendship, not small talk)",
        not_worth="greetings and sign-offs; \"good to see you\"; generic encouragement "
                  "that carries no fact",
    ),
    dict(
        n="02", a="Jon", b="Gina",
        span="20 January 2023 – 23 July 2023", sessions=19,
        a_lines="losing his job as a banker and starting a dance studio, contemporary dance, "
                "a crew that took first place in a local competition, rehearsals after work, "
                "an upcoming festival performance",
        b_lines="losing her Door Dash job, dance as stress relief, competing as a teenager "
                "(first place at a regional at fifteen), a contemporary piece called "
                "\"Finding Freedom\"",
        objects="the \"Finding Freedom\" piece; the waterfront studio Jon wants; the festival",
        worth="a job ending or starting, with the date it happened; a competition placing with "
              "the year and the age; the name of a piece or a venue; a date the two of them "
              "agreed to meet; a business step actually taken (a lease looked at, a name chosen)",
        not_worth="mutual excitement with no fact attached; repeated \"let's do it soon\" "
                  "where no date is set",
    ),
    dict(
        n="03", a="John", b="Maria",
        span="17 December 2022 – 16 August 2023", sessions=32,
        a_lines="a run at local politics built on education and infrastructure, kickboxing, "
                "family road trips, and the neighbourhood history behind his platform",
        b_lines="volunteering at a homeless shelter, aerial yoga and staying fit",
        objects="the school that was renovated after funding; the shelter; the campaign itself",
        worth="a campaign step and when it happened (who he spoke to, what he committed to); "
              "a stated policy focus and the reason he gives for it; a volunteering shift or "
              "a fitness milestone with its date; a trip with where and when",
        not_worth="agreement noises; general praise; aspirations restated without a new fact",
    ),
    dict(
        n="04", a="Joanna", b="Nate",
        span="21 January 2022 – 11 November 2022", sessions=29,
        a_lines="writing and a project she is working on, reading, film (drama and romantic "
                "comedy), nature; a favourite film she first watched about three years ago and "
                "owns on disc",
        b_lines="competitive video gaming (a first tournament win in Counter-Strike: Global "
                "Offensive), action and sci-fi film",
        objects="the films and games named on either side; the tournament; Joanna's writing project",
        worth="a title named, plus how it entered their life (recommended by whom, watched when, "
              "owned in what form); a tournament result with the game and the date; a milestone "
              "in Joanna's writing project; a recommendation one made to the other and whether "
              "it was taken up",
        not_worth="taste declared with no title attached; \"sounds cool, I'll check it out\" "
                  "with no follow-through",
    ),
    dict(
        n="05", a="Tim", b="John",
        span="21 May 2023 – 12 January 2024", sessions=29,
        a_lines="a Harry Potter fan project and the collaborations around it, a London trip to "
                "a Potter site some years back",
        b_lines="signing with the Minnesota Wolves as a shooting guard, a season opener, working "
                "on his shooting percentage, fitting into a new team, a sneaker collection",
        objects="the fan project; the Minnesota Wolves; named games and venues; the sneaker collection",
        worth="a signing, a game, or a season milestone with its date and the opponent or result; "
              "a stated training goal and any later measurement of it; a step in the fan project "
              "(who joined, what was decided, what shipped); a place visited with roughly when",
        not_worth="pre-game excitement carrying no fact; compliments; repeated statements of "
                  "enthusiasm for the same thing",
    ),
    dict(
        n="06", a="Audrey", b="Andrew",
        span="27 March 2023 – 22 November 2023", sessions=28,
        a_lines="three dogs — Pepper, Precious and Panda, hers for three years — and the city "
                "parks and trails she explores with them",
        b_lines="a new job as a Financial Analyst started shortly before the first session, "
                "birds (eagles above all), and hiking (Fox Hollow at weekends)",
        objects="Pepper, Precious and Panda; Fox Hollow and the other named trails and parks",
        worth="which dog is which and what is true of each one specifically; a job start, change "
              "or milestone with its date; a named trail, park or outing and when it happened; "
              "a purchase for the dogs and roughly when",
        not_worth="\"cute!\"; generic animal appreciation; the same fondness restated",
    ),
    dict(
        n="07", a="James", b="John",
        span="17 March 2022 – 7 November 2022", sessions=31,
        a_lines="programming (Python and C++, a website, game mods), two dogs named Max and "
                "Daisy, a dog-walking and pet-care app idea, and a childhood comic he wants to "
                "turn into a computer game; bowling; a wallet stolen at a slot machine",
        b_lines="a programming class he signed up for, older HTML/CSS experience, VR, and an "
                "intention to start running",
        objects="Max and Daisy; the dog-walking app; the indie game from the childhood comic; "
                "the named games (The Witcher 3 and others)",
        worth="a project step with its date (a mod released, a feature decided, a collaborator "
               "invited); which language or tool was used for what; a named pet and what is true "
               "of it; an incident with a date and a consequence; a plan the two of them fixed "
               "to a specific day",
        not_worth="mutual enthusiasm about games with no fact; \"maybe someday\" ideas nobody "
                  "acted on",
    ),
    dict(
        n="08", a="Deborah", b="Jolene",
        span="23 January 2023 – 20 September 2023", sessions=30,
        a_lines="her mother, who died some years ago, the mother's old house and the bench by "
                "its window, a pendant she keeps, and teaching yoga in her community",
        b_lines="electrical engineering work, her mother who died the previous year, and a "
                "pendant her mother gave her in Paris in 2010 whose symbol stands for freedom",
        objects="each woman's pendant (they are two different pendants); the mother's house and "
                "its bench; the yoga classes; Jolene's engineering projects",
        worth="which keepsake belongs to whom, who gave it, where and in what year; a death, a "
              "visit or an anniversary with its date; a class taught or a project finished with "
              "its date; the reason someone gives for a practice they keep",
        not_worth="condolences; shared sentiment with no fact; comfort offered without new "
                  "information",
    ),
    dict(
        n="09", a="Evan", b="Sam",
        span="18 May 2023 – 11 January 2024", sessions=25,
        a_lines="a new Prius after the old one broke down (repaired, then sold), family trips "
                "including the Rockies, and watercolour painting he took up a few years ago "
                "after a friend introduced him to it",
        b_lines="hiking, including one with his father when he was ten, and an intention to "
                "take up painting",
        objects="the old and the new Prius (two distinct vehicles); the named trips and trails; "
                "the paintings",
        worth="a vehicle acquired, repaired or sold, with the date and which vehicle it was; a "
              "trip with where, when and who came; when a hobby started and who introduced it; "
              "a first attempt at something new and how it went",
        not_worth="\"looks amazing\"; encouragement with no fact; restated fondness for a hobby",
    ),
    dict(
        n="10", a="Calvin", b="Dave",
        span="23 March 2023 – 17 November 2023", sessions=30,
        a_lines="a new mansion, a stay in Japan arranged by his agent (leaving the month after "
                "the first session, staying some months, then on to Boston), Japanese culture, "
                "and collaborations with local musicians",
        b_lines="classic cars and car shows, and a park with a lake he spends time at",
        objects="the mansion and the Japanese lodging (two distinct places); the named parks and "
                "car shows; the musical collaborations",
        worth="a move, a trip or a stay with its dates and its destination; who arranged what; "
              "a collaboration with the musician named and what came of it; a show attended with "
              "its date; a purchase of consequence",
        not_worth="travel excitement with no itinerary fact; generic admiration of a photo",
    ),
]

TEMPLATE = """---
# The machine-readable half of the contract: skill identity plus the path templates of the
# subject families. These correspond one-to-one with the families in section 1 below.
skill_id: lcr-{n}-knowledge
version: lcr-{n}-v1
path_templates:
  - people/{{slug}}.md
  - threads/{{slug}}.md
  - timeline/{{slug}}.md
  - things/{{slug}}.md
---

# What this library remembers

## 0. Whose library this is, and what it is for

This library holds one long-running two-person conversation: **{a}** and **{b}**, talking
across {sessions} sessions between {span}. The material arrives one session at a time and
never stops being about the same two lives, so the library's job is to be the memory of that
relationship: who did what, when it happened, and how each thread moved between one session
and the next.

Assume the questions asked of this library later will be specific and factual — *when* did
that happen, *who* was it, *which one* of the two, *how long* between the two events, *what
changed since*. Answering them depends on the fact having been recorded, so this contract is
deliberately dense: a concrete fact about either speaker, about someone in their circle, or
about a named object, place or event, is worth recording even when it feels small in the
moment. Compression is not the goal here; retrievable specificity is.

{a}'s side of it runs through {a_lines}.
{b}'s side runs through {b_lines}.
Recurring named things to expect: {objects}.
More will arrive that is not listed here — these are the threads visible at the outset, not a
closed list. Open new subjects as the material introduces them.

## 1. Subject families: what gets its own page

Four families, matching the `path_templates` above.

**`people/{{slug}}.md`** — one page per person. {a} and {b} each have one from the start.
Anyone else the two of them talk about — family, friends, colleagues, coaches, agents, a
partner, a child — gets a page the first time a concrete fact is attached to them (a name plus
a relationship, a job, an event they were part of). A person mentioned only as a passing noun
with nothing true attached to them stays in the raw material. What a person's page collects:
who they are, how they relate to {a} or {b}, and the facts that belong to *them* — their job,
their family, their health, their possessions, their history. Record every alias, nickname,
diminutive or spelling variant on the page of the person it belongs to; the two speakers
shorten each other's names and other people's names constantly, and a name split across two
pages is a subject silently turned into two.

**`threads/{{slug}}.md`** — one page per thing that keeps developing: a job or career move, a
project, a business, a course of study, a hobby taken up, a health situation, a house move, a
trip being planned. A thread page is the running record of that one thing: how it started,
each state change with its date, decisions made and the reasons given, and how it stands now.
Open a thread the first time the material shows it moving, not the first time it is wished
for. One thread page is reserved for the two of them together — the plans they fix, the
meet-ups they agree, the recommendations one makes to the other and whether the other took
them up.

**`timeline/{{slug}}.md`** — the chronological spine, one page per calendar month, slug
`YYYY-MM`. Every dated happening in that month gets a line: what happened, who it happened to,
the absolute date, and a pointer to the person or thread it belongs to. This family exists
because "when" and "how long between" questions are answered from a spine, not by scanning
every page. A fact recorded on a person or thread page and *also* dated belongs in both
places — that is deliberate duplication, not an error.

**`things/{{slug}}.md`** — one page per named non-person subject with a story of its own: a
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

Worth it, in this material: {worth}.

Not worth it: {not_worth}.

The test for anything else: would someone reading this library a year from now need this fact
to answer a question about {a}, {b}, or someone in their circle? In a chat log the answer is
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
it when it matters: a fact about {a}'s job stated by {a} is direct; the same fact relayed by
{b} is second-hand and should say so. A plan is not an event — "we'll go next Friday" is an
agreement made on the day it was said, and it becomes an event only when a later session says
it happened. Keep the two separate and let the later session update the thread. When a
subsequent session contradicts an earlier one, record the newer fact with its date and keep
the earlier one with its own date rather than overwriting it; the change itself is often what
gets asked about.

Some messages carry an image. In the source these appear as indented `[images]`, `[caption]`
and `[query]` lines attached to the message above them. Treat the caption and query as a
description of what the speaker showed, attributed to the speaker who shared it — "{a} shared
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
"""


def main() -> int:
    written = []
    for c in CONVS:
        body = TEMPLATE.format(**c)
        path = ROOT / f"app-{c['n']}" / "engine" / "compile" / "contract.md"
        path.write_text(body, encoding="utf-8")
        written.append(str(path))
    for p in written:
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
