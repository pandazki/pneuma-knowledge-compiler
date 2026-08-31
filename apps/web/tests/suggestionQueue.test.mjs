/**
 * The suggestion bubble's queue and its thirty-second countdown.
 *
 * The whole module exists to hold one rule: **an arriving suggestion never replaces the one on
 * screen.** A live evaluation can deliver two cards a second apart, and a bubble that
 * overwrote itself would mean the operator saw a flash of something they can never get back.
 * Queued instead, the flash becomes a "+N" badge and a turn to be taken.
 *
 * Everything here is asserted at exact millisecond boundaries, which is possible only because
 * `now` is an argument rather than something the module reads (the `liveStages` discipline).
 * "The bubble expired" is a claim about a return value; nobody has to sit and wait thirty
 * seconds to check it.
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
  SUGGESTION_TTL_MS,
  emptyQueue,
  arrive,
  tick,
  dismiss,
  pin,
  remainingMs,
  remainingFraction,
  remainingSeconds,
  pendingCount,
  upgrade,
} = await import(await tsModuleUrl(new URL("../src/lib/suggestionQueue.ts", import.meta.url)));

const T0 = 1_700_000_000_000;

const card = (id, seq = 1) => ({
  id,
  seq,
  arrivedAt: T0,
  suggestion: {
    kind: "concept",
    title: `卡 ${id}`,
    body: "解释",
    trigger: "触发",
    confidence: 8,
    citations: [],
  },
});

test("the first suggestion takes the bubble; the clock starts when it is shown", () => {
  const state = arrive(emptyQueue, card("a"), T0);
  assert.equal(state.current.id, "a");
  assert.equal(state.current.shownAt, T0);
  assert.equal(state.current.pinned, false);
  assert.equal(pendingCount(state), 0);
});

test("a second suggestion queues — it never overwrites what is on screen", () => {
  // The rule this module exists for. Overwriting would show a card for a frame and lose it.
  let state = arrive(emptyQueue, card("a"), T0);
  state = arrive(state, card("b"), T0 + 1_000);
  state = arrive(state, card("c"), T0 + 2_000);
  assert.equal(state.current.id, "a", "the bubble is untouched");
  assert.deepEqual(state.queue.map((c) => c.id), ["b", "c"]);
  assert.equal(pendingCount(state), 2, "the +N badge reads 2");
});

test("the countdown drains but does not expire a moment early", () => {
  const state = arrive(emptyQueue, card("a"), T0);
  assert.equal(remainingMs(state, T0), SUGGESTION_TTL_MS);
  assert.equal(remainingFraction(state, T0), 1);
  assert.equal(remainingMs(state, T0 + 10_000), SUGGESTION_TTL_MS - 10_000);
  assert.equal(remainingFraction(state, T0 + 15_000), 0.5);
  // One millisecond short of the deadline the card is still up.
  assert.equal(tick(state, T0 + SUGGESTION_TTL_MS - 1).current.id, "a");
});

test("the ring's seconds round up so a live bubble never reads zero", () => {
  const state = arrive(emptyQueue, card("a"), T0);
  assert.equal(remainingSeconds(state, T0), 30);
  assert.equal(remainingSeconds(state, T0 + 29_001), 1, "999ms left still reads 1s");
  assert.equal(remainingSeconds(state, T0 + SUGGESTION_TTL_MS), 0);
});

test("expiry retires the card as expired and promotes the next with a full ring", () => {
  let state = arrive(emptyQueue, card("a"), T0);
  state = arrive(state, card("b"), T0 + 1_000);
  state = tick(state, T0 + SUGGESTION_TTL_MS);

  assert.equal(state.current.id, "b");
  assert.equal(state.current.shownAt, T0 + SUGGESTION_TTL_MS, "b gets its own full thirty seconds");
  assert.equal(remainingMs(state, T0 + SUGGESTION_TTL_MS), SUGGESTION_TTL_MS);
  assert.equal(state.history.length, 1);
  assert.equal(state.history[0].id, "a");
  assert.equal(state.history[0].fate, "expired");
  assert.equal(state.history[0].retiredAt, T0 + SUGGESTION_TTL_MS);
  assert.equal(pendingCount(state), 0);
});

test("a backgrounded tab catches up in one tick instead of showing a dead bubble", () => {
  // `tick` compares timestamps rather than counting frames, so a tab that missed a hundred
  // of them settles correctly on the first call after it wakes.
  let state = arrive(emptyQueue, card("a"), T0);
  state = arrive(state, card("b"), T0 + 500);
  state = tick(state, T0 + 5 * SUGGESTION_TTL_MS);
  assert.equal(state.current.id, "b");
  assert.equal(state.history[0].fate, "expired");
});

test("an empty bubble with an empty queue is left alone", () => {
  assert.deepEqual(tick(emptyQueue, T0 + 999_999), emptyQueue);
  assert.deepEqual(dismiss(emptyQueue, T0), emptyQueue);
  assert.deepEqual(pin(emptyQueue), emptyQueue);
  assert.equal(remainingMs(emptyQueue, T0), 0);
});

test("dismissing retires the card as dismissed and shows the next immediately", () => {
  let state = arrive(emptyQueue, card("a"), T0);
  state = arrive(state, card("b"), T0 + 1_000);
  state = dismiss(state, T0 + 4_000);
  assert.equal(state.current.id, "b");
  assert.equal(state.history[0].fate, "dismissed");
  assert.equal(state.history[0].retiredAt, T0 + 4_000);
});

test("want-more pins the bubble: the ring freezes full and time cannot expire it", () => {
  // The expansion arrives over the socket seconds later. A bubble that expired while its own
  // answer was in flight would deliver the answer to nobody.
  let state = pin(arrive(emptyQueue, card("a"), T0));
  assert.equal(state.current.pinned, true);
  assert.equal(remainingMs(state, T0 + 10 * SUGGESTION_TTL_MS), SUGGESTION_TTL_MS);
  state = tick(state, T0 + 10 * SUGGESTION_TTL_MS);
  assert.equal(state.current.id, "a", "still there long after it would have expired");
  assert.equal(state.history.length, 0);
});

test("a pinned card is recorded as pinned when it is finally dismissed", () => {
  // Its own fate, not "dismissed": "why did that one stay" and "why did I not see that one"
  // are different questions, and the history tab answers both.
  let state = pin(arrive(emptyQueue, card("a"), T0));
  state = dismiss(state, T0 + 90_000);
  assert.equal(state.history[0].fate, "pinned");
  assert.equal(state.current, null);
});

test("pinning twice is not a second pin, and the queue keeps waiting behind it", () => {
  let state = arrive(emptyQueue, card("a"), T0);
  state = arrive(state, card("b"), T0 + 100);
  const pinned = pin(state);
  assert.strictEqual(pin(pinned), pinned, "idempotent");
  assert.equal(pendingCount(pinned), 1, "b is still waiting, not dropped");
});

test("history is newest first and every retirement lands in it", () => {
  let state = arrive(emptyQueue, card("a"), T0);
  state = arrive(state, card("b"), T0 + 100);
  state = arrive(state, card("c"), T0 + 200);
  state = dismiss(state, T0 + 1_000); // a
  state = tick(state, T0 + 1_000 + SUGGESTION_TTL_MS); // b expires, c up
  state = dismiss(state, T0 + 40_000); // c

  assert.deepEqual(state.history.map((h) => [h.id, h.fate]), [
    ["c", "dismissed"],
    ["b", "expired"],
    ["a", "dismissed"],
  ]);
  assert.equal(state.current, null);
  assert.equal(pendingCount(state), 0);
});

test("a card that waited keeps its real arrival time in history", () => {
  // The countdown measures from when it was SHOWN, but "when did this suggestion happen" is
  // still the moment it arrived — the two are different and history shows the honest one.
  let state = arrive(emptyQueue, card("a"), T0);
  const waited = { ...card("b"), arrivedAt: T0 + 3_000 };
  state = arrive(state, waited, T0 + 3_000);
  state = tick(state, T0 + SUGGESTION_TTL_MS);
  assert.equal(state.current.arrivedAt, T0 + 3_000);
  assert.equal(state.current.shownAt, T0 + SUGGESTION_TTL_MS);
});

test("an emptied bubble promotes on the next tick even with no time passing", () => {
  let state = dismiss(arrive(emptyQueue, card("a"), T0), T0 + 1);
  assert.equal(state.current, null);
  state = arrive(state, card("b"), T0 + 2);
  assert.equal(state.current.id, "b");
});

// ───────────────────────────────── the glance short-circuit's provisional card
//
// The one card that CAN change after it arrives: the subject's own definition, shown a
// retrieval early while the tick behind it is still running. When that tick settles, the
// card either becomes the full one IN PLACE or simply stops shimmering — never a second
// bubble about the same subject.

const glance = (id, seq = 1) => ({
  ...card(id, seq),
  suggestion: { ...card(id, seq).suggestion, kind: "glance", provisional: true },
});

const full = (title) => ({
  kind: "concept",
  title,
  body: "完整的卡片",
  trigger: "触发",
  confidence: 9,
  citations: [],
});

test("an upgrade replaces the provisional card in place, keeping its slot and its clock", () => {
  let state = arrive(emptyQueue, glance("a"), T0);
  state = upgrade(state, 1, full("完整"));
  assert.equal(state.current.id, "a", "the same bubble");
  assert.equal(state.current.shownAt, T0, "not a fresh thirty seconds");
  assert.equal(state.current.suggestion.title, "完整");
  assert.equal(state.current.suggestion.provisional, false);
  assert.equal(pendingCount(state), 0, "the queue did not grow");
});

test("an upgrade with no card settles the provisional one where it stands", () => {
  let state = arrive(emptyQueue, glance("a"), T0);
  state = upgrade(state, 1, null);
  assert.equal(state.current.suggestion.title, "卡 a", "the same true sentence");
  assert.equal(state.current.suggestion.provisional, false, "it just stopped shimmering");
});

test("a pinned card upgrades without unpinning", () => {
  // Pinning is the reader saying "hold this one", and the upgrade is that same one
  // arriving in full — taking the pin off would drop it out from under them.
  let state = pin(arrive(emptyQueue, glance("a"), T0));
  state = upgrade(state, 1, full("完整"));
  assert.equal(state.current.pinned, true);
  assert.equal(state.current.suggestion.title, "完整");
  assert.equal(remainingMs(state, T0 + SUGGESTION_TTL_MS * 2), SUGGESTION_TTL_MS);
});

test("a provisional card still waiting in the queue upgrades where it sits", () => {
  let state = arrive(emptyQueue, card("a"), T0);
  state = arrive(state, glance("b", 2), T0 + 1_000);
  state = upgrade(state, 2, full("完整"));
  assert.equal(state.queue[0].suggestion.title, "完整");
  assert.equal(state.queue[0].suggestion.provisional, false);
  assert.equal(state.current.id, "a", "the bubble on screen was not touched");
});

test("an upgrade only ever touches the provisional card of its own evaluation", () => {
  let state = arrive(emptyQueue, glance("a", 1), T0);
  state = arrive(state, glance("b", 2), T0 + 1_000);
  state = upgrade(state, 2, full("完整"));
  assert.equal(state.current.suggestion.provisional, true, "seq 1 is another tick's card");
  assert.equal(state.queue[0].suggestion.title, "完整");
});

test("an upgrade naming a card that already left changes nothing", () => {
  // History records the final form, and a card that expired before its tick finished is
  // exactly what the reader saw.
  let state = arrive(emptyQueue, glance("a"), T0);
  state = tick(state, T0 + SUGGESTION_TTL_MS);
  const after = upgrade(state, 1, full("完整"));
  assert.equal(after.current, null);
  assert.equal(after.history[0].suggestion.title, "卡 a");
});

test("an ordinary card is never touched by an upgrade", () => {
  let state = arrive(emptyQueue, card("a"), T0);
  assert.deepEqual(upgrade(state, 1, full("完整")), state);
});
