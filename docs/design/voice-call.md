# The voice call — a voice in front, the library behind it

**English** | [简体中文](voice-call.zh-CN.md)

## 1. Why, and what a call is not

Every other way into this library is a turn: you type, it answers, you read. A call is not
that. The Owner is walking, or driving, or holding a cup of coffee, and wants to ask the
library something the way they would ask a colleague sitting across the room — interrupting
it, correcting themselves halfway through a name, saying "no, the second one" and being
understood.

That is a different engineering problem from the one the console solves, and the difference
is not the microphone. It is that **nobody is reading**. A written answer may take eleven
seconds; the person watches the stages tick by and knows the machine is working. Eleven
seconds of silence on a phone line is a dropped call. Everything in this design that looks
unusual is that constraint working its way down through the stack.

Three things follow from it, and they are the whole design:

- The conversation and the knowledge are **different jobs for different models**. Conducting
  a full-duplex conversation — listening while speaking, deciding many times a second whether
  to talk, back off or wait — is what the voice model is for. It knows nothing about this
  library and must never pretend to (§2).
- What the library says is **the ordinary fast lane**, under the same contract, the same
  citation gate and the same archive scope as every other answer — but asked in a posture
  built for someone waiting in silence (§6).
- Everything the voice says that did not come from the library is **visible as such** on the
  screen beside it (§7). A voice is a persuasive medium and the library's whole argument is
  that it does not fabricate; a call that blurred the two would spend that argument.

**A call is not a new retrieval lane.** It answers from fast recall and writes nothing. The
library is not modified by talking to it.

## 2. The split: a voice that conducts, a library that answers

The voice model runs at OpenAI, reached with the deployment's own `OPENAI_API_KEY`. It
carries a short standing prompt — its manner, its backchannel and interruption policy, and
one paragraph naming what the backend can help with — and nothing about the library's
contents. Its provider's own guidance is emphatic that this prompt stays small, and
measurement agreed: a first draft that spelled out every formatting case delayed the model's
first spoken token by seconds.

When the voice decides it needs the library, it **delegates**. Two modes exist; this design
uses **client delegation**, where our own process answers, rather than the hosted mode where
the provider calls a model of its own. The reason is the citation gate. A hosted backend
would assemble its own context from the conversation and answer out of it; the library's
claim that nothing is fabricated rests on evidence being retrieved, cited and gated HERE. A
call that answered from somewhere else would be a second, ungated mouth speaking in the
library's name.

The consequence is a peculiarity worth stating plainly, because every later section is
shaped by it:

> **The delegation event carries no question.** It says *that* the voice wants help, and
> *when* on the session timeline. Not what about.

The question is in the transcript, and reconstructing it is the first thing the delegate
does (§6.1).

## 3. The shape of one call

Audio never touches this engine. The browser and the provider hold a WebRTC connection
directly, and the engine is on the path exactly once, at the start, to exchange the browser's
SDP offer for an answer using the project key. This is the documented browser path for this
API, and it has a property worth having: **the browser never holds a credential**. It is
handed an SDP answer and two ids.

The engine then attaches a **sideband** — a second connection to the same session that
carries events and commands while the audio stays on WebRTC — and from there it owns
everything the library has a stake in.

```
     ┌──────────┐      audio (WebRTC)      ┌────────────┐
     │ browser  │◄────────────────────────►│  voice     │
     │          │   captions (data chan)   │  model     │
     └────┬─────┘                          └─────┬──────┘
          │ SDP offer                            │ sideband: transcript, delegations,
          │ ─────────────►┌────────┐◄────────────┘ hand-overs, usage, close
          │ ◄──── answer  │ engine │
          │   call frames │        │──► ask formation ──► fast recall ──► spoken chunks
          └──────────────►└────────┘
```

**One owner per action.** The browser draws captions and may close or mute. Everything else —
reading the transcript, answering a delegation, handing words to the voice — is the engine's,
done once. This is not a convention the page is asked to respect: the session is created with
the data channel narrowed to three commands (close, mute, unmute), so a page that tried to
append an instruction to the voice is refused by the provider (`event_not_allowed`, verified
against the live API).

## 4. The doors

| Door | What it is |
|---|---|
| `GET /v1/users/{uid}/call` | whether a call can be placed here, and if not, the one thing missing (`no_openai_key`, `no_recall_model`). The console draws its button from this; an older engine answers 404 and the console shows nothing |
| `POST /v1/users/{uid}/call` | the browser's SDP offer in, the provider's SDP answer out, plus the ids. The project key is used here and nowhere else. Creating a session is billed, so this is only ever reached from a click |
| `WS /v1/users/{uid}/call/{call_id}` | what the engine knows that the browser's own data channel does not: each delegation's card as it develops, usage, the close. `{"type":"end"}` hangs up |

One call per owner. A second `POST` ends the first, because the usual reason a first one is
still open is a tab that died mid-call — and that session is still billing.

## 5. The rules a call is held to

These four are the ones that took measurement to get right, and they live in
`call/session.py`.

**The latest ask wins; the screen keeps every answer.** A spoken interruption cancels nothing
at the provider — what happens to work already running is this application's decision. The
decision is mechanical: when a new delegation arrives, every older one still in flight is
marked *superseded*. It finishes its lookup and completes its card on screen, and it hands
the voice nothing. The Owner hears the answer to what they just asked, and the answer to what
they asked a moment ago is still there to read.

**An acknowledgement is not speech.** The provider acks a hand-over when it estimates the
text reached the model's context — not when anybody heard it. So an ack is never rendered as
"said". What is taken from it is its interval on the session timeline, which is what lets the
console line up which spoken sentences stand on which answer, and mark the ones that stand on
none (§7).

**A delegation is claimed before any work starts**, so a redelivered event cannot run the
same lookup twice.

**Silence is billed.** A session costs by the minute for as long as it is open, whether or
not anyone is speaking, and muting the microphone does not stop the meter. So a call that has
heard nothing from the Owner for `CALL_IDLE_SECONDS` is closed by the engine, no call outlives
`CALL_MAX_SECONDS`, and a call whose browser never opened its socket — or whose socket went
away — is closed as an orphan.

## 6. The delegate: what the library does when asked

### 6.1 Ask formation

The delegation event carries no text (§2), so the question has to be written from what the
call has heard. A small structured call does it, reading the transcript's tail, the earlier
asks of this same call, and a list of the library's own page titles. It produces one
standalone question — resolving "the second one" against what was said, applying the Owner's
latest correction, repairing a misheard project name — or says the transcript does not
establish one yet and gives the voice a clarifying question to ask instead.

It fails toward the Owner's own words. A timeout, a provider error, a model without
structured output, or no model at all degrade to what the Owner said since the voice last
spoke. That is a worse question than a formed one, and it is the Owner's; a delegate that
went silent because a helper call failed would leave a voice that was told not to guess with
nothing to say.

Two details each came from a call that went wrong:

- **The title list is ordered by what was heard.** A library outgrows any fixed budget of
  titles, and a cut in path order drops exactly the page being asked about as often as not. A
  misheard name usually keeps most of its words, so those words choose what is shown.
- **Speculation.** Writing the question costs a model call — the largest single wait in a
  lookup — and for a first question asked in a whole sentence it returns the Owner's own words
  with a question mark on the end. So those words go to the library *at once*, beside the call
  that may replace them, and whatever comes back is **held**: nothing reaches the voice until
  the formed question turns out to be the same one. When it differs — a follow-up, a
  correction, a repaired name — the speculative attempt is dropped unheard and the real
  lookup starts. The wasted attempt is a real cost, and it is this design's to own.

### 6.2 The fast lane, in a posture for speech

The answer is `fast_recall` — the same function the console's Recall view and `pkc recall`
call, assembled by the same code, so a call answers from exactly the evidence faces, archive
scope and citation discipline every other answer does. What differs is a posture, and every
line of it was bought with a measurement on a real library:

| Posture | Why |
|---|---|
| the `call` model role, reasoning pinned off | ask formation, the routing turn and the answer all happen while a person waits in silence |
| a small evidence head (10 claims, 3 windows, 2 episode summaries) | the answering call's prompt is the second-largest wait, and a spoken answer is three sentences long |
| no glance rendered into the prompt | it was two thirds of that prompt, and its pick was the long pole of retrieval |
| the `spoken` answer style | written to be said: conclusion first, two or three plain sentences, no headings, lists or code formatting |

Together these took the first answer token from about ten seconds to about two.

The `spoken` style is short on purpose and that, too, is measured: a first draft three times
its length — every formatting case spelled out, numbers "the way they are said" — delayed the
answering model's first token by two to six seconds on the same evidence. What it no longer
says is done mechanically instead: citation markers and markdown are stripped before the
voice is handed anything, because the screen carries them and a voice reads `[cite: s3 ¶4-9]`
out loud.

### 6.3 A period is not a subject

One failure is worth recording in full, because it produced a confident answer about the
wrong thing. Asked how one project had gone over two days, the time component returned
everything those two days held — several thousand characters about other projects — and the
answering model, given a flood and asked for three sentences, summarized the flood. It said
what happened those two days, which was not what was asked, and added that none of it was
about the project in a second paragraph the voice never reached.

The repair is a subject scope on the range lookup: the routing model, which already reads the
question, names the subject; the scoping itself is mechanical — no model, no ranking, a
containment test — and when nothing in the range mentions the subject the lookup returns
nothing, which is the honest answer and one the answering model can stand on. The match is
deliberately strict: a first version that let a long name match on two of its words scoped a
question about one project to the records of its sibling, because projects in a family share
their first words. Missing a loose mention costs an excerpt; admitting a sibling costs the
answer.

### 6.4 What is handed over, and when

The answering model's token stream becomes a few speakable hand-overs rather than one. The
first is released at the first clause boundary, because an answering model asked for three
sentences often writes one long one and the Owner should not wait for its full stop; later
chunks are coalesced, because every hand-over is a point where the voice may re-phrase. A
sentence is never released while a citation bracket is still open.

A hard ceiling bounds what one answer may say — about twenty-five seconds of speech. The
style clause asks for brevity; this enforces it. The card on screen keeps the whole answer,
and the Owner can ask for the rest.

**No quiet context.** The provider offers a channel for context the voice should hold but not
say. Measured against the real model, anything put there beside a result was spoken — label
and all — and a voice holding half-remembered detail answered a follow-up from its own
imagination instead of asking again. The delegate hands over what is to be said and nothing
else, and a follow-up is a new ask.

## 7. What the Owner sees

The call surface has two columns. On the left, captions of both speakers, grouped by the
session timeline and revisable — the provider states no turn boundary, so a row is a display
grouping and never a claim that somebody finished speaking. On the right, one card per ask:
the question as the library understood it, what state it is in, and when it is done, the
answer rendered exactly as the Recall view renders one, with its citations.

Between the two columns runs the feature's honesty mechanism. Each spoken row is matched to
the delegation whose hand-over it stands on — the latest one at or before the row began, by
their intervals on the session timeline — and carries that card's number. **A spoken row that
matches no hand-over is marked "not from the library."** That is the voice talking on its own,
and it is exactly the material that a call, of all surfaces, makes easiest to mistake for
knowledge.

Short unlinked rows are exempt, and the exemption is the point rather than a compromise. "Mm
hm", "let me check", "sure" are the voice doing its actual job, and a mark on every one of
them would appear so often that a reader would learn to skip it — which is the one failure
mode this mechanism cannot afford. The threshold is a length, because length is what
separates an acknowledgement from an assertion.

## 8. Cost

The voice bills per minute of open session, silent or not; the backend is ours and costs what
a fast recall costs. Creating a session bills a fixed opening charge even if nobody speaks,
which is why nothing creates one on page load. The engine's two ceilings (§5) exist for this
reason and no other, and the surface shows the running cost while the call is open.

## 9. Measuring it

Latency is measured **from the delegation event to the first word handed to the voice**, and
each card carries its own breakdown — transcript settled, question written, retrieval
finished, first words out — so a slow call can be read rather than guessed at. The voice
covers the wait with its own "let me look", which is the point of the split, but the number
is not allowed to hide behind that: an earlier acknowledgement is not an earlier answer.

Two things are deliberately measured separately. The **spoken** answer is what the Owner
heard; the **card** is what the library said. They differ — the voice paraphrases — and any
claim about answer quality is about the card.

## 10. Boundaries, and what is not built here

- **The call writes nothing.** No compile, no draft, no owner statement. A transcript is not
  ingested as a source; the shape a call would take as `owner-dialogue/v1` material is
  designed for but not built, and it would have to reckon with a contract that requires
  non-blank turns and non-decreasing times — which barge-in-heavy speech does not supply
  without work.
- **One call per owner**, and it lives only while its surface is open.
- **No telephony.** The provider supports SIP; a library that answered the phone is a
  different product with different authentication.
- **The tray** has no call entry yet; the console's is the only one.
- **Not the Steward.** This is the retrieval lanes with a voice in front. Talking to the
  coding agent that compiles the library stays the Steward view's text session, because its
  unit is a round with commands and results, not a sentence.
