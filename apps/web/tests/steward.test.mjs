/**
 * The Steward conversation: the event reducer, the invalidation rule, and the lens table.
 *
 * Three things are worth pinning here rather than in a browser:
 *
 * 1. **A flat event stream becomes a readable transcript.** Text deltas coalesce into one
 *    block; a step's result lands under the step that ran it, not at the end of the page.
 * 2. **A step that changed the library says so.** `invalidates` is the whole of "the history
 *    view moved while the Steward was still typing" — matched on the command's own text,
 *    because that text is what the harness reported and the console invents nothing.
 * 3. **The Steward is the Owner's.** A visitor deep-linking into it lands in the reading room,
 *    which is a property of the one lens table and is asserted against it.
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
  INVALIDATING,
  clearInvalidations,
  emptyConversation,
  formatDuration,
  invalidates,
  ownerSaid,
  reduce,
  usageEntries,
} = await import(await tsModuleUrl(new URL("../src/lib/steward.ts", import.meta.url)));

const { VIEW_LENSES, isViewVisible, resolveView } = await import(
  await tsModuleUrl(new URL("../src/lib/lenses.ts", import.meta.url))
);

function fold(frames, state = emptyConversation()) {
  return frames.reduce((acc, frame) => reduce(acc, frame), state);
}

const TURN = [
  { type: "turn_started", turn_id: "trn-1" },
  { type: "text_delta", text: "reading " },
  { type: "text_delta", text: "the ledger" },
  { type: "step_started", step_id: "s1", command: "pkc jobs --limit 5", tool: "Bash" },
  {
    type: "step_finished",
    step_id: "s1",
    exit_code: 0,
    output_preview: "2 jobs",
    duration_ms: 340,
    failed: false,
  },
  {
    type: "turn_finished",
    usage: { input_tokens: 42, output_tokens: 12 },
    cost_usd: 0.0214,
    duration_ms: 4123,
    error: "",
  },
];

test("a stream of events becomes a transcript: prose in one block, a step with its result", () => {
  const state = fold(TURN);
  assert.deepEqual(
    state.items.map((i) => i.kind),
    ["text", "step", "usage"],
  );
  assert.equal(state.items[0].text, "reading the ledger");
  const step = state.items[1];
  // The agent's OWN command, unchanged.
  assert.equal(step.command, "pkc jobs --limit 5");
  assert.equal(step.running, false);
  assert.equal(step.exitCode, 0);
  assert.equal(step.output, "2 jobs");
  assert.equal(step.durationMs, 340);
  assert.equal(state.busy, false);
});

test("a turn in flight is busy until it finishes", () => {
  const running = fold(TURN.slice(0, 4));
  assert.equal(running.busy, true);
  assert.equal(running.items.at(-1).running, true);
  assert.equal(fold(TURN).busy, false);
});

test("a message typed mid-turn is marked queued on the message itself", () => {
  let state = fold(TURN.slice(0, 2));
  state = ownerSaid(state, "and check the tender too");
  state = reduce(state, { type: "notice", code: "queued", detail: "and check…" });
  const owner = state.items.find((i) => i.kind === "owner");
  assert.equal(owner.queued, true);
  // Nothing was resent and no second turn was opened: the marker IS the whole behaviour.
  assert.equal(state.items.filter((i) => i.kind === "owner").length, 1);
});

test("a permission request renders as a step that stopped", () => {
  const state = fold([
    {
      type: "permission_request",
      request_id: "req-1",
      method: "item/commandExecution/requestApproval",
      detail: '{"command":"rm -rf /"}',
      declined: true,
    },
  ]);
  const step = state.items[0];
  assert.equal(step.kind, "step");
  assert.equal(step.stopped, true);
  assert.equal(step.failed, true);
});

test("an exit is reported and never turns into a fresh conversation on its own", () => {
  const state = fold([...TURN, { type: "session_exited", exit_code: 3, detail: "" }]);
  assert.equal(state.exited, true);
  assert.equal(state.exitCode, 3);
  // The transcript stays: the Owner reads what happened before deciding to start again.
  assert.equal(state.items.length, 3);
});

test("a snapshot repaints a reconnecting tab through the same reducer", () => {
  const live = fold(TURN);
  const repainted = reduce(emptyConversation(), {
    type: "snapshot",
    configured: true,
    backend: "codex",
    label: "Codex",
    protocol: "jsonrpc",
    spec: "agent:codex",
    live: true,
    exited: false,
    exit_code: null,
    agent_session_id: "thr-1",
    project_dir: "/srv",
    session_id: "stw-1",
    events: TURN,
  });
  assert.deepEqual(
    repainted.items.map((i) => i.kind),
    live.items.map((i) => i.kind),
  );
  assert.equal(repainted.agentSessionId, "thr-1");
  // A repaint is not a change to the library: it must not re-fire invalidations.
  assert.deepEqual(repainted.invalidations, []);
});

test("a deployment with no coding agent says so rather than showing an empty chat", () => {
  const state = reduce(emptyConversation(), {
    type: "not_configured",
    detail: "this deployment compiles with openrouter:some/model",
  });
  assert.match(state.notConfigured, /openrouter/);
});

test("the five library-changing commands invalidate the other views, and reads do not", () => {
  for (const command of INVALIDATING) {
    assert.equal(invalidates(`${command} --json`), true, command);
  }
  assert.equal(invalidates("pkc jobs --limit 5"), false);
  assert.equal(invalidates("pkc recall --evidence 'the tender'"), false);
  assert.equal(invalidates("pkc draft open j-1"), false);
  assert.equal(invalidates(""), false);
  // Whitespace the harness happened to report is not a different command.
  assert.equal(invalidates("pkc   owner\n  say --text-file -"), true);
});

test("an invalidating step raises it once, and clearing it is the caller's acknowledgement", () => {
  let state = fold([
    { type: "step_started", step_id: "s9", command: "pkc draft finish", tool: "Bash" },
    {
      type: "step_finished",
      step_id: "s9",
      exit_code: 0,
      output_preview: "committed",
      duration_ms: 900,
      failed: false,
    },
  ]);
  assert.deepEqual(state.invalidations, ["pkc draft finish"]);
  state = clearInvalidations(state);
  assert.deepEqual(state.invalidations, []);
  // A step that only READ leaves the other views alone.
  state = fold(
    [
      { type: "step_started", step_id: "s10", command: "pkc jobs", tool: "Bash" },
      {
        type: "step_finished",
        step_id: "s10",
        exit_code: 0,
        output_preview: "",
        duration_ms: 10,
        failed: false,
      },
    ],
    state,
  );
  assert.deepEqual(state.invalidations, []);
});

test("a step result lands under its own step even when two are open at once", () => {
  const state = fold([
    { type: "step_started", step_id: "a", command: "pkc jobs", tool: "Bash" },
    { type: "step_started", step_id: "b", command: "pkc sources", tool: "Bash" },
    {
      type: "step_finished",
      step_id: "a",
      exit_code: 0,
      output_preview: "from a",
      duration_ms: 5,
      failed: false,
    },
  ]);
  assert.equal(state.items[0].output, "from a");
  assert.equal(state.items[1].running, true);
});

test("a harness that reported no usage shows none, never a zero", () => {
  const state = fold([
    { type: "turn_finished", usage: null, cost_usd: null, duration_ms: 0, error: "" },
  ]);
  assert.deepEqual(usageEntries(state.items[0].usage), []);
  assert.equal(state.items[0].costUsd, null);
});

test("the Steward view is the owner's, and a visitor deep link lands in the reading room", () => {
  assert.deepEqual(VIEW_LENSES.steward, ["owner"]);
  assert.equal(isViewVisible("steward", "owner"), true);
  assert.equal(isViewVisible("steward", "visitor"), false);
  assert.equal(isViewVisible("steward", "silent"), false);
  assert.equal(resolveView("steward", "visitor"), "recall");
  assert.equal(resolveView("steward", "owner"), "steward");
});

test("a duration reads in the unit a person reads it in", () => {
  assert.equal(formatDuration(340), "340ms");
  assert.equal(formatDuration(4123), "4.1s");
  assert.equal(formatDuration(0), "");
});
