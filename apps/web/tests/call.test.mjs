/**
 * The call: captions, cards, and the marks that tell one from the other.
 *
 * Three streams land in one reducer — the voice provider's data channel, the engine's socket
 * and the tab's own lifecycle — and what this file pins is the part a reader's trust rests
 * on: that a caption row carries the library's ordinal only when the library really spoke
 * through it, and that a stretch of speech the library did not supply says so.
 *
 * Everything here runs without a browser, a microphone or a peer connection, which is the
 * reason `lib/call.ts` is a pure module with no imports at all.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

async function tsModuleUrl(url) {
  const text = await readFile(url, "utf8");
  const transformed = await transformWithEsbuild(text, url.pathname, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  return `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
}

const {
  CAPTION_GAP_MS,
  UNLINKED_MARK_CHARS,
  captionMarks,
  delegationOrdinal,
  emptyCall,
  formatCost,
  formatElapsed,
  isCallLive,
  ordinalBadge,
  reduce,
} = await import(await tsModuleUrl(new URL("../src/lib/call.ts", import.meta.url)));

function fold(events, state = emptyCall()) {
  return events.reduce((acc, event) => reduce(acc, event), state);
}

/** One assistant transcript fragment. */
const voice = (delta, start, end = start + 200) => ({
  type: "session.output_transcript.delta",
  delta,
  start_ms: start,
  end_ms: end,
});

/** One Owner transcript fragment. */
const owner = (delta, start, end = start + 200) => ({
  type: "session.input_transcript.delta",
  delta,
  start_ms: start,
  end_ms: end,
});

const delegation = (id, patch = {}) => ({
  type: "delegation",
  delegation: {
    id,
    state: "done",
    spoken: true,
    ask: "",
    said: "",
    answer: null,
    detail: "",
    offset_ms: 0,
    deliveries: [],
    elapsed_ms: null,
    ...patch,
  },
});

const LIVE = [{ type: "start" }, { type: "connecting" }, { type: "connected", call_id: "c1", session_id: "s1" }];

/* --------------------------------------------------------------------------- captions */

test("a fragment's text is kept exactly as it arrived — no trimming, no inserted space", () => {
  const state = fold([...LIVE, voice("Let me ", 1000), voice("check", 1300), voice("…", 1500)]);
  assert.equal(state.rows.length, 1);
  assert.equal(state.rows[0].text, "Let me check…");
});

test("the two speakers keep their own rows, and those rows may overlap in time", () => {
  const state = fold([...LIVE, owner("what about the tender", 1000), voice("one moment", 1100)]);
  assert.deepEqual(
    state.rows.map((r) => [r.speaker, r.text]),
    [
      ["owner", "what about the tender"],
      ["voice", "one moment"],
    ],
  );
  // The Owner speaking again joins the OWNER's row, not the one the voice opened after it.
  const more = reduce(state, owner(" and the deadline", 1400));
  assert.equal(more.rows.length, 2);
  assert.equal(more.rows[0].text, "what about the tender and the deadline");
});

test("a gap on the session timeline opens a new row; anything closer joins the current one", () => {
  const close = fold([...LIVE, voice("first", 1000, 1200), voice(" still first", 1200 + CAPTION_GAP_MS)]);
  assert.equal(close.rows.length, 1, "exactly at the gap is still the same row");

  const apart = fold([...LIVE, voice("first", 1000, 1200), voice("second", 1201 + CAPTION_GAP_MS)]);
  assert.equal(apart.rows.length, 2);
  assert.deepEqual(apart.rows.map((r) => r.text), ["first", "second"]);
});

test("rows keep their ids and their order while their text grows", () => {
  let state = fold([...LIVE, owner("q", 1000), voice("a", 1100)]);
  const ids = state.rows.map((r) => r.id);
  state = fold([owner("q2", 1200), voice("a2", 1300)], state);
  assert.deepEqual(state.rows.map((r) => r.id), ids, "no row was reordered or renumbered");
  assert.equal(new Set(ids).size, ids.length, "ids are unique");
});

test("a hand-over to the voice breaks the row, so the filler and the result never share one", () => {
  // The voice starts a filler, the library hands over its result mid-utterance, and the
  // voice carries on. The two must not end up in one row wearing one provenance mark.
  const state = fold([
    ...LIVE,
    voice("let me check…", 1000, 1200),
    delegation("d1", { deliveries: [{ start_ms: 1500, end_ms: 1900 }] }),
    voice("the tender closes on the 14th", 1600),
  ]);
  assert.deepEqual(state.rows.map((r) => r.text), ["let me check…", "the tender closes on the 14th"]);
  // And the fragments after the break stay together: only the FIRST one past a delivery splits.
  const more = reduce(state, voice(" at noon", 1700));
  assert.equal(more.rows.length, 2);
  assert.equal(more.rows[1].text, "the tender closes on the 14th at noon");
});

test("a delivery the row already began after does not split it again", () => {
  const state = fold([
    ...LIVE,
    delegation("d1", { deliveries: [{ start_ms: 1000, end_ms: 1100 }] }),
    voice("the tender", 1200, 1400),
    voice(" closes on the 14th", 1500),
  ]);
  assert.equal(state.rows.length, 1);
});

/* ------------------------------------------------------------------- provenance marks */

test("a row that speaks a delegation carries that card's ordinal", () => {
  const state = fold([
    ...LIVE,
    delegation("d1", { ask: "when does the tender close?", deliveries: [{ start_ms: 1500, end_ms: 1900 }] }),
    voice("the tender closes on the 14th", 1600),
  ]);
  const marks = captionMarks(state);
  const row = state.rows[0];
  assert.equal(marks[row.id].delegationId, "d1");
  assert.equal(marks[row.id].ordinal, 1);
  assert.equal(marks[row.id].unlinked, false);
  assert.equal(ordinalBadge(1), "①");
});

test("the latest hand-over at or before the row wins; an older one is not a better match", () => {
  const state = fold([
    ...LIVE,
    delegation("d1", { deliveries: [{ start_ms: 1000, end_ms: 1200 }] }),
    delegation("d2", { deliveries: [{ start_ms: 3000, end_ms: 3200 }] }),
    voice("the first answer", 1100),
    voice("the second answer", 3100),
  ]);
  const marks = captionMarks(state);
  assert.deepEqual(
    state.rows.map((r) => marks[r.id].delegationId),
    ["d1", "d2"],
  );
  assert.deepEqual(state.rows.map((r) => marks[r.id].ordinal), [1, 2]);
});

test("speech the library did not supply is marked — once it is long enough to be a claim", () => {
  const long = "a".repeat(UNLINKED_MARK_CHARS + 1);
  const state = fold([...LIVE, voice(long, 1000)]);
  assert.equal(captionMarks(state)[state.rows[0].id].unlinked, true);

  // An acknowledgement is not a claim about the library, so it is left alone.
  const short = fold([...LIVE, voice("a".repeat(UNLINKED_MARK_CHARS), 1000)]);
  assert.equal(captionMarks(short)[short.rows[0].id].unlinked, false);

  // The Owner's own words are never marked: the rule is about the voice model, not them.
  const said = fold([...LIVE, owner(long, 1000)]);
  assert.equal(captionMarks(said)[said.rows[0].id].unlinked, false);

  // A row that IS linked is never marked, however long it runs.
  const linked = fold([
    ...LIVE,
    delegation("d1", { deliveries: [{ start_ms: 900, end_ms: 950 }] }),
    voice(long, 1000),
  ]);
  assert.equal(captionMarks(linked)[linked.rows[0].id].unlinked, false);
});

/* ------------------------------------------------------------------------ the cards */

test("a delegation is upserted whole by its id, and never moves from the place it took", () => {
  let state = fold([
    ...LIVE,
    delegation("d1", { state: "hearing", ask: "" }),
    delegation("d2", { state: "searching", ask: "who signed it?" }),
    delegation("d1", { state: "done", ask: "when does the tender close?", elapsed_ms: 1400 }),
  ]);
  assert.deepEqual(state.delegations.map((d) => d.id), ["d1", "d2"]);
  assert.equal(state.delegations[0].state, "done");
  assert.equal(state.delegations[0].ask, "when does the tender close?");
  assert.equal(delegationOrdinal(state, "d2"), 2);
  assert.equal(delegationOrdinal(state, "nope"), 0);

  // The payload is handed through untouched: it is the recall answer, not a copy of it.
  const payload = { answer: "The tender closes on the 14th. [cite: s1 ¶2-3]", used_claims: [] };
  state = reduce(state, delegation("d1", { state: "done", answer: payload }));
  assert.equal(state.delegations[0].answer, payload);
});

test("a superseded ask still completes, and says that nobody heard it", () => {
  const state = fold([...LIVE, delegation("d1", { spoken: false, state: "done", elapsed_ms: 900 })]);
  assert.equal(state.delegations[0].spoken, false);
  // A delegation that says nothing about `spoken` is spoken: silence is not a supersession.
  const plain = reduce(state, { type: "delegation", delegation: { id: "d2", state: "searching" } });
  assert.equal(plain.delegations[1].spoken, true);
  assert.deepEqual(plain.delegations[1].deliveries, []);
});

/* ---------------------------------------------------------- the session's own lifetime */

test("the call walks from a gesture to a live session, and nothing starts it on its own", () => {
  assert.equal(emptyCall().status, "idle");
  assert.equal(isCallLive(emptyCall()), false);
  const state = fold(LIVE);
  assert.equal(state.status, "live");
  assert.equal(state.callId, "c1");
  assert.equal(state.sessionId, "s1");
  assert.equal(isCallLive(state), true);
  // Asking for the microphone is its own state, because it is its own wait.
  assert.equal(fold([{ type: "start" }]).status, "asking-mic");
});

test("usage is the engine's to report, and the context gauge stays absent until it says", () => {
  const state = fold([...LIVE, { type: "usage", seconds: 92, context_ratio: null }]);
  assert.equal(state.seconds, 92);
  assert.equal(state.contextRatio, null);
  assert.equal(reduce(state, { type: "usage", seconds: 130, context_ratio: 0.62 }).contextRatio, 0.62);
});

test("a close ends the call and keeps the final count, from either side", () => {
  const engine = fold([...LIVE, { type: "closed", reason: "owner_ended", seconds: 143 }]);
  assert.equal(engine.status, "ended");
  assert.equal(engine.closedReason, "owner_ended");
  assert.equal(engine.seconds, 143);

  const provider = fold([...LIVE, { type: "session.closed", reason: "hangup", usage: { seconds: 61 } }]);
  assert.equal(provider.status, "ended");
  assert.equal(provider.seconds, 61);

  // A close that carries no number leaves the last one it was told standing.
  const counted = fold([...LIVE, { type: "usage", seconds: 20, context_ratio: null }, { type: "ended" }]);
  assert.equal(counted.seconds, 20);
});

test("a failure keeps its name, and an error on a live call does not end it", () => {
  // The engine's shape and the data channel's shape are the same event to a reader.
  const engine = fold([{ type: "start" }, { type: "error", code: "no_openai_key", detail: "no key" }]);
  assert.equal(engine.status, "failed");
  assert.equal(engine.errorCode, "no_openai_key");
  assert.equal(engine.error, "no key");

  const provider = fold([...LIVE, { type: "error", error: { code: "rate_limited", message: "slow down" } }]);
  assert.equal(provider.status, "live", "a running session is ended by the session, not by a frame");
  assert.equal(provider.errorCode, "rate_limited");
  assert.equal(provider.error, "slow down");

  // A close after a failure does not overwrite the more informative truth.
  const failed = fold([{ type: "failed", code: "mic_denied", detail: "no microphone access" }, { type: "ended" }]);
  assert.equal(failed.status, "failed");
  assert.equal(failed.errorCode, "mic_denied");
});

test("the microphone indicator follows the session's own word, never the click", () => {
  const state = fold([...LIVE, { type: "session.input_audio.muted" }]);
  assert.equal(state.muted, true);
  assert.equal(reduce(state, { type: "session.input_audio.unmuted" }).muted, false);
});

test("a new call starts from nothing, and a ping changes nothing at all", () => {
  const used = fold([...LIVE, voice("hello", 1000), delegation("d1")]);
  const again = reduce(used, { type: "start" });
  assert.deepEqual(again.rows, []);
  assert.deepEqual(again.delegations, []);
  assert.equal(again.status, "asking-mic");
  assert.equal(reduce(used, { type: "ping" }), used, "a keepalive is not a state change");
});

test("the engine says when delegation works, and the console does not guess", () => {
  const state = fold(LIVE);
  assert.equal(state.attached, false);
  assert.equal(reduce(state, { type: "attached" }).attached, true);
});

/* ------------------------------------------------------------------------ the numbers */

test("time and money read in the units a person reads a call in", () => {
  assert.equal(formatElapsed(0), "00:00");
  assert.equal(formatElapsed(9), "00:09");
  assert.equal(formatElapsed(432), "07:12");
  assert.equal(formatCost(0), "$0.00");
  assert.equal(formatCost(60), "$0.05");
  assert.equal(formatCost(120), "$0.10");
  assert.equal(formatCost(600), "$0.50");
  // Nothing invented out of a missing number.
  assert.equal(formatCost(-5), "$0.00");
  assert.equal(formatElapsed(Number.NaN), "00:00");
});

test("the circled ordinals run out gracefully rather than wrongly", () => {
  assert.equal(ordinalBadge(0), "");
  assert.equal(ordinalBadge(3), "③");
  assert.equal(ordinalBadge(20), "⑳");
  assert.equal(ordinalBadge(21), "(21)");
});
