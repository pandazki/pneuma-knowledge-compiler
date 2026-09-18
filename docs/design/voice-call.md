# Talking with the knowledge library

**English** | [简体中文](voice-call.zh-CN.md)

## 1. Intended experience

The Owner should be able to talk to a colleague who can consult the library: ask a question,
add a detail, correct a name, interrupt an answer, and follow up on what was actually said.
Success means a relevant, supported answer delivered at a useful conversational pace. A
microphone attached to a succession of independent text queries does not achieve that.

Evidence is backend support, not the center of the spoken experience: the Owner need not
listen to citations or inspect a card to continue. The voice can summarize or explain a
still-current result without another lookup; it delegates when facts are missing or changed.
Preserving uncertainty, negation and scope matters more than reciting provenance. A backend
synthesis is useful for multi-record questions; an additional call merely rewriting a concise
result for speech is not. We keep synthesis in recall and let Live choose natural phrasing.

Measure three separate outcomes: understanding the request, answering it from the right
evidence, and communicating the answer in conversation. A fast acknowledgment is not a fast
answer. A completed backend answer is not proof the Owner heard it.

Calls are read-only. No compile, draft, owner statement, or source ingestion happens here.

## 2. Responsibility and official guidance

GPT-Live handles full-duplex conversation. The application owns task state and runs the
knowledge backend. The standing voice prompt carries personality, backchannels, interruption
policy, actual backend capabilities, and concrete delegation conditions. Retrieval instructions
and business rules belong to the backend. Volatile date/time context is separate from the
byte-stable standing instructions.

This follows OpenAI's [Live guide](https://developers.openai.com/api/docs/guides/live),
[prompting guide](https://developers.openai.com/api/docs/guides/live-prompting), and
[delegation guide](https://developers.openai.com/api/docs/guides/live-delegation). The Chinese
URLs requested during review did not expose Markdown through the documentation tool; the
corresponding official English pages were fetched instead.

| Option | Assessment |
|---|---|
| Client delegation with our recall backend | Retained. We control context, evidence handling and which results reach Live. Reuses tenant isolation and archive scope. |
| Managed Responses delegation with a knowledge lookup function | A valid alternative, **not inherently ungated or unsafe**. It manages conversation context and backend connections, but adds an orchestrating model around an existing answering backend and requires a different function-result lifecycle. Compare end-to-end before adopting. |
| Retrieved facts sent directly to Live | Useful for an unambiguous single fact. A large time-range result is not a useful voice payload: relevance and synthesis still need an owner. Not the general answering path. |
| Separate selection for every question | Appropriate for wide/noisy pools, unnecessary latency for a small complete pool. |
| A smaller fixed candidate count | Not adopted as a latency shortcut: it can remove the only relevant record before any model sees it. |

Client delegation is a control choice, not a truth guarantee. Canonical admission checks
provenance; the selected-evidence path follows bounded source spans. The current **text**
answer stream is model-generated text, not a per-sentence semantic validator. The structured
answer path's citation admission does not apply merely because a text answer carries markers.
Live paraphrases commentary and may also speak independently. Neither citation presence nor
an injection acknowledgment proves semantic fidelity or playback.

## 3. Connections and scope

The browser exchanges microphone/speaker audio directly with the provider over WebRTC. The
engine exchanges the SDP with its project key, then attaches a sideband for transcript,
delegation, result and usage events. The browser receives an SDP answer and identifiers, never
a credential. Its data channel permits only close, mute and unmute; the provider rejects
instruction appends from it.

- `GET /v1/users/{uid}/call`: configuration availability and reason if unavailable.
- `POST /v1/users/{uid}/call`: create a call from a browser SDP offer.
- `WS /v1/users/{uid}/call/{call_id}`: backend cards, timings, usage and close events;
  `{"type":"end"}` requests hangup.

There is one call per owner. A replacement closes the old call. Idle, maximum-duration and
orphan limits bound open sessions. The tray opens the browser console, where microphone
permissions and a sustained conversation can be handled.

## 4. Conversation state

The delegation event contains an ID and timestamp, **no question**. The engine retains both
speakers' transcript fragments and keeps earlier delegated questions/results. Fragments are
not turn boundaries. The ledger groups each speaker independently so a backchannel cannot
split the other person's utterance.

After a bounded settling interval, the engine freezes the transcript input before vocabulary
I/O or model work. Ask formation reads that snapshot, a bounded vocabulary of canonical page
titles, and earlier questions/results. It resolves references and corrections, repairs a name
only when supported, and can return a clarification instead of a guessed query. A helper
failure currently degrades to the Owner's last words; ambiguous follow-ups remain a limitation
of that fallback.

The two-phase workflow starts only after question formation. Raw-ASR speculation is removed:
starting two competing progressive workflows would duplicate both lookups and their model
work. A clarification starts neither lookup.

Each provider delegation is claimed once. A new delegation supersedes older in-flight speech;
older work may finish its on-screen card but cannot send further results. While an answer is pending, new owner speech pauses outgoing updates until a bounded
semantic review distinguishes a backchannel from cancellation or a changed request. A cancel
or replacement suppresses old speech even without another provider delegation. A three-second
review timeout suppresses the stale answer conservatively and records that decision. Context injection already accepted by the provider cannot
be retracted by this local revision check.

## 4.5 Speech spelling reference

[Live prompting](https://developers.openai.com/api/docs/guides/live-prompting) recommends
language/pronunciation instructions and clarifying unclear names; it does not promise exact
capture. The separate [transcription API](https://developers.openai.com/api/docs/guides/realtime-transcription#add-transcription-context)
supports `keywords`, but `gpt-live-1` WebRTC session configuration does not expose that field.
We use initial developer context for a bounded reference, not an invented ASR API option.
Raw transcript spelling can still differ; ask formation receives the same reference.

Preprocessing is explicit, outside dialing:

```sh
uv run python scripts/ops/build_speech_lexicon.py USER --dry-run
uv run python scripts/ops/build_speech_lexicon.py USER --model openrouter:openai/gpt-5.6-luna
```

Use the deployment's environment. The tool reads live canonical titles and complete bodies
in overlapping bounded chunks. Luna selects uncommon names, coined terms, mixed-language
terms and confusing acronyms; frequency alone never admits a common word. Each accepted
spelling must occur in that supplied page text, with Latin token boundaries checked. This
proves source occurrence, not that the model assessed recognition difficulty correctly.
A second, bounded cross-page model pass removes code identifiers and generic concepts and
orders the shortlist by usefulness in spoken conversation. Page coverage can prioritize
already-eligible uncommon names, but cannot admit ordinary words. It can only select source-checked
candidates; this selection is still a model judgment, not a recognition benchmark.
Model-generated aliases/pronunciations are not accepted. Explicit `--confusion 'Lyrra=leera'`
entries are used only while their canonical spelling still occurs in a live page.

A tenant-hashed JSON under `ENGINE_DIR/derived/speech-lexicons/` stores page fingerprints,
model/prompt recipe, selected spellings, risk and page origins. Without an engine directory,
it lives under `canonical_root.parent/derived/speech-lexicons/`, outside canonical git.
Unchanged pages are reused; changed pages are rescanned; failures retain prior work and remain
eligible for retry. The file is atomically replaced. Rerun after a compile batch; no periodic
background extraction or canonical write is introduced. At call time, deleted/archived pages
and spellings absent from current text are excluded. Missing cache means metadata only, not
an unfiltered title dump. The cache is derived and can be deleted and rebuilt.

Page metadata is maintained during ordinary compilation, using `create_document`,
`set_fields`, or `rewrite_overview(fields)` in the same draft and commit. The shared compile
contract and tool descriptions instruct both model and coding-agent executors to select
uncommon spoken terms, preserve relevant entries, add new names, and explicitly clear a
page with no useful terms. This is model judgment; the gate does not prove completeness or
recognition difficulty. No separate background extraction job is needed for these pages.

```yaml
speech_terms: [{"term": "Lyrra", "confusions": ["leera"]}, "洛芮"]
```

This reserved structured field is serialized as single-line JSON (valid YAML), unlike
legacy scalar metadata. The write face and final gate enforce a list of at most 40 entries,
bounded spellings, normalized uniqueness, and exact term occurrence in the page body
(including headings). Confusions contain at most six spellings and are supplied only for
explicit owner corrections. Body changes that invalidate stored terms require a metadata
repair before commit. Claims and citations retain their existing gates.

At call startup, live page fields are collected and globally deduplicated. A present field,
even `[]`, overrides that page's transitional preprocessing cache. Old pages without the
field retain the existing cache until their metadata is maintained; this is a compatibility
bridge, not a second authoritative vocabulary. No model runs during collection. Archived
pages are excluded. The reference retains original spelling, removes ambiguous confusion
mappings, and stays within 80 terms and 3,000 JSON characters. New calls see committed
metadata; an ongoing call keeps its opening reference.
Test recognition, raw transcription and downstream interpretation separately on identical
audio. A lexical occurrence check or a unit-test pass is not an ASR accuracy measurement.

## 5. One delegation, two overlapping lookups

Every formed question starts both lookups. This is not a choice between a small and a large
pool, and the earlier size-based shortcut is removed. Both phases share the resolved tenant,
`as_of`, canonical document set and archive policy. This is a shared read context, not a
transactional snapshot of all indexes.

```text
formed question ──┬─ bounded lexical lookup → pick one complete short record → Live speaks
                 └─ broader fast recall ───────────────────┐
                     exact first finding ──────────────────┴→ refine → Live continues
```

**First look.** The ordinary fast lane runs in evidence-only mode with no embedding, routing,
selection or answer model call: 8 claim candidates / 6 retained claims, 3 raw-window candidates
/ 2 retained windows, no semantic summaries, and bounded source expansion. It uses the same
archive filtering and source-span checks as selected recall. A small structured model call
then chooses one short record index, or abstains. When candidates include records beyond the 300-byte quote
budget, it sees complete records (at most 6,000 bytes each and 4,000 characters
combined) and returns one selected index plus a partial answer of at most 200 characters.
The index must address a supplied record; summarization is model interpretation, not a
mechanical guarantee of semantic entailment. Superseded and archived claims remain excluded.

The result is wrapped as a partial finding. The first-result deadline is six seconds;
empty or uncertain results are labelled `no_supported_finding`, and timeouts are recorded
separately. Neither cancels the broader lookup. Complete records are never cut mid-qualification.
Source traceability does not prove that a record is current or that a paraphrase is faithful.

**Broader lookup.** This starts concurrently, using the deployment's ordinary lexical,
semantic and enabled component faces. Cross-face selection retains its five-second timeout
and explicit ranked fallback. There is no name-containment filter inside a time component.
Once both the broader evidence and the first finding are available, a structured refinement
call receives the first finding as conversation context, never as new evidence. It returns:

- ordered factual units, each marked retained, new or correction relative to the exact first finding;
- its relationship to the first finding: answer, extension, correction, confirmation or
  unresolved result;
- citation addresses supporting the answer from the broader evidence actually supplied.

Citation fields are admitted only if every address exactly matches that evidence. Nonempty
factual answers require admitted references. An invalid result is refused before speech. This
is address validation, not a semantic entailment proof. Unresolved output uses fixed honest
wording, rather than forwarding a speculative model paragraph.

Each factual unit is authored once. The card displays all units, including still-supported
retained facts; after a first finding, speech contains only new/correction units. This makes
selection mechanical, but the model's semantic classification can still be wrong. Mixed
retained/new sentences must be split. Extensions and corrections receive application-owned
transition prefixes. A confirmation with no new facts sends quiet completion, not another
spoken summary. Without a first finding, all answer units are spoken. Both phases' token
receipts are retained.
`FastEvidence` now carries retrieval/selection usage so stopping before the answering call
cannot lose the broader lookup's cost.

This remains a fixed workflow over fast recall, not a new autonomous agent or write lane.
The synthesis call is needed to compare records and resolve the earlier partial picture;
there is no extra model call merely to rewrite its result for speech.

## 6. Streaming a task's results into Live

OpenAI explicitly supports repeated `session.commentary.append` events for the same client
`delegation_id`. One delegated task can therefore return a first finding and later updates
without opening a second delegation. Each append is at most 500 tokens. An acknowledgment
means estimated context injection, not playback.

The application streams **completed results across phases**. The refinement schema is parsed
and its addresses checked before its spoken update is released; unvalidated JSON/token
fragments are not read aloud. Complete sentences are handed over progressively within a
result. Citation markers and display markup stay off the spoken channel. Every outgoing
append, including clarification text, is bounded to 480 UTF-8 bytes and 420 characters;
oversized sentences prefer word boundaries when split. A failed text stream's unfinished tail
is discarded. Previously injected material cannot be retracted, so a revision must say what
changed.

A 1,200-character safety ceiling limits runaway speech payloads. It is not the old
130-character summary cap: requests to explain or compare can receive substantive detail.

Progress, clarification and failure do not enter `said`, consume its budget, create result
links or set first-result latency. A one-time holding line does not suppress an invoke-only
answer. Failure after a first finding explicitly says the broader check did not complete and
the first result remains partial. Both lookup tasks are canceled and joined on cancellation;
a newer delegation suppresses every late spoken result of the older one, while its card may
finish.

Progress and no-change completion use `session.thinking.append`; useful findings and
corrections use `session.commentary.append`. Trusted control instructions remain separate
from retrieved content. The voice prompt asks Live to preserve scope, incorporate additions naturally
and acknowledge corrections, without restarting the whole answer.

## 7. Screen and measurement

The screen shows both speakers' captions and one evidence card per delegation. `said` means
text handed to Live, not text heard by the Owner. Only result-injection acknowledgments enter
`deliveries`; they share timestamps with transcript events. The UI's temporal card association
is a navigation hint, **not sentence-level provenance verification**. In particular, matching
the latest earlier injection cannot establish that every later utterance is supported by it.

Measure delegation-to-first-useful-result separately from first acknowledgment, total backend
time and audible response latency. `elapsed_ms` measures the first result handover; actual
speech needs the output transcript/audio. Assess answer quality separately from cost/latency.

The expandable per-delegation trace retains the preliminary result, exact append bodies,
phase, event ID, send/acknowledgment/error states, owner-change decisions and contemporaneous
Live output transcript. It can be exported as JSON. `first_sent` and `sent_ms` use backend
elapsed time from delegation creation; acknowledgment `start_ms`/`end_ms` are the provider's
estimated injection interval on its session clock. Neither establishes what the user heard.
Output transcript association is temporal, not a causal attribution to a particular update.

Real-library evaluation uses fixed-evidence replay separately from paced PCM WebSocket calls.
Cancellation, correction, confirmation and added-detail scenarios are inspected separately.
A synthetic voice and received output audio do not test browser microphone permissions or
physical playback. Live can still paraphrase/repeat facts; small runs do not establish a
universal quality or latency improvement. Private transcripts stay under ignored `local/`.

### September 18, 2026 backend experiment

`pneuma_knowledge_eval.progressive_call.compare` exercises three synthetic scenarios twice:
a partial regional count expanded by a wider list, a launch date superseded by a later record,
and additional details. It uses the production evidence renderer, including `as_of`, and the
Chinese prompt overlay. The deployment model was `openrouter:openai/gpt-5.6-luna`, reasoning
off. All six first findings copied the complete supplied record; all six refinements selected
an expected relation and contained the checked new information. These checks are diagnostics,
not a general semantic quality score. One first-selector call took 3.773 s: this uncapped
backend diagnostic retains it for inspection, but the application would skip it at its
2.5-second first-look deadline. Five of the six first-selector calls alone met that deadline;
real retrieval consumes part of it too.

Median first-finding generation was **1.429 s**, and final refinement **3.332 s** from the
start. A single complete answer on the same already-available broader evidence had a median
of **1.786 s**. This shows the cost of an extra stage, not an end-to-end speed win: the experiment
excludes retrieval, ASR, question formation and audio. Its purpose is to inspect the handover
and correction behavior. Deterministic tests separately prove that a first result can be
sent while the broader retrieval is still blocked.

An initial simplified fixture omitted the actual time context and one run invented calendar
dates. Using the production renderer and explicit time context removed that observed failure
in this small rerun; it does not establish that the model cannot invent a date. The exact-copy
first stage has a stronger mechanical boundary than the synthesized refinement. Live itself
was not exercised by these text-backend calls.

## 8. Verification and remaining work

Deterministic tests cover result/progress separation, invoke-only delivery, failed-stream
cleanup, stable ask snapshots, substantive follow-ups, multibyte append bounds, concurrent lookups, explicit correction, cancellation cleanup, late-result suppression,
source-address admission and retained tenant/archive/provenance checks. Existing route/session tests cover
ownership, duplicate delegation, supersession and shutdown. They do not grade natural speech.

Before claiming production conversational quality, repeat real calls covering name repair,
“the second one,” corrections during retrieval and speech, repeat versus expand, empty evidence,
conflicting dates, and broad time-range questions. Record both backend cards and actual audio;
compare the same scenarios with the previous implementation. The Owner's reported failures
should become cases in that set. Browser autoplay, cross-browser WebRTC and tray handoff remain
separate end-to-end checks.

### Local runtime fixes after deployment

Spoken recall permits source-only markers such as `[cite: s01]`. Refinement now binds them
to the exact shown spans for that handle, intersected with the typed evidence manifest;
the structured-output schema offers only those admitted choices, and unknown handles and invented explicit spans remain rejected. Disjoint spans stay disjoint.
The earlier exact-span-only gate incorrectly rejected the ordinary spoken answer format.

Voice recall retains four raw windows, three episode summaries, up to four claim provenance
passages and one episode provenance passage. Expanded passages over 6,000 characters are
omitted whole after address validation, with an assembly degradation reason; their cited
claims remain available. This prevents a complete agent-session expansion from adding
100,000 characters to an otherwise small spoken-answer context. These bounds trade context
coverage for latency and do not constitute a measured quality improvement. The synthetic
selector measurements above describe the earlier verbatim-only implementation.
