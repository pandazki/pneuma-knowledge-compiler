/**
 * The owner-statement form's payload builder.
 *
 * The one property worth a test here is the one this contract does NOT share with the other
 * four: order is validated, never repaired. Every other contract sorts what it is handed
 * because a provider archive's order is an artefact of the export; a dialogue's order is its
 * content, so a payload whose times run backwards must be refused before the round trip
 * rather than quietly reordered into a different statement.
 *
 * The i18n lookup is injected — the module is transpiled standalone here, so it cannot reach
 * the dictionary — and the fake returns the key, which is also how a wrong key would show.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/views/ingest/ownerStatement.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  OWNER_DIALOGUE_SCHEMA,
  buildOwnerStatementPayload,
  emptyOwnerTurn,
  hasOwnerTurn,
  localInputValue,
  mintDialogueId,
} = await import(moduleUrl);

const i18n = { t: (key, params) => (params ? `${key} ${JSON.stringify(params)}` : key) };
const BUILD = { ownerId: "u-mei", dialogueId: "owner-fixed-01" };

function turn(saidAt, text, role = "owner") {
  return { role, saidAt, text };
}

test("the turns become one owner-dialogue/v1 payload, in the order they were written", () => {
  const payload = buildOwnerStatementPayload(
    [
      turn("2026-08-31T09:00", "供应商把交期从两周缩短到五天。"),
      turn("2026-08-31T09:05", "记下了，我去更正那条断言。", "steward"),
    ],
    BUILD,
    i18n,
  );
  assert.equal(payload.schema, OWNER_DIALOGUE_SCHEMA);
  assert.equal(payload.provider, "console");
  assert.equal(payload.owner_id, "u-mei");
  assert.equal(payload.dialogue_id, "owner-fixed-01");
  assert.deepEqual(
    payload.turns.map((t) => [t.turn_id, t.role, t.text]),
    [
      ["t1", "owner", "供应商把交期从两周缩短到五天。"],
      ["t2", "steward", "记下了，我去更正那条断言。"],
    ],
  );
  // Aware instants, which the contract requires — the browser's zone does the conversion.
  for (const t of payload.turns) {
    assert.ok(!Number.isNaN(new Date(t.said_at).getTime()));
    assert.match(t.said_at, /Z$/);
  }
  // `steward_id` is absent rather than null when the application names no steward.
  assert.equal("steward_id" in payload, false);
});

test("empty turns are dropped, and the ids renumber over what is left", () => {
  const payload = buildOwnerStatementPayload(
    [
      turn("2026-08-31T09:00", "   "),
      turn("2026-08-31T09:01", "  第二批验收由阿宝签。  "),
    ],
    BUILD,
    i18n,
  );
  assert.deepEqual(
    payload.turns.map((t) => [t.turn_id, t.text]),
    [["t1", "第二批验收由阿宝签。"]],
  );
});

test("a dialogue whose times run backwards is refused, never sorted", () => {
  assert.throws(
    () =>
      buildOwnerStatementPayload(
        [
          turn("2026-08-31T09:05", "……所以那条要改。"),
          turn("2026-08-31T09:00", "交期缩短了。"),
        ],
        BUILD,
        i18n,
      ),
    /ingest\.owner\.error\.outOfOrder/,
  );
});

test("two turns in the same minute are fine — equal is not backwards", () => {
  const payload = buildOwnerStatementPayload(
    [turn("2026-08-31T09:00", "一"), turn("2026-08-31T09:00", "二")],
    BUILD,
    i18n,
  );
  assert.equal(payload.turns.length, 2);
});

test("nothing written, and nothing unreadable, is said before the round trip", () => {
  assert.throws(
    () => buildOwnerStatementPayload([turn("2026-08-31T09:00", "  ")], BUILD, i18n),
    /ingest\.owner\.error\.empty/,
  );
  assert.throws(
    () => buildOwnerStatementPayload([turn("not-a-time", "话")], BUILD, i18n),
    /ingest\.owner\.error\.badTime/,
  );
});

test("a fresh turn is the owner speaking now, in the browser's own local spelling", () => {
  const at = new Date(2026, 7, 31, 9, 5);
  assert.equal(localInputValue(at), "2026-08-31T09:05");
  const fresh = emptyOwnerTurn(at);
  assert.deepEqual(fresh, { role: "owner", saidAt: "2026-08-31T09:05", text: "" });
});

test("a minted dialogue id is readable and does not collide within the minute", () => {
  const at = new Date(2026, 7, 31, 9, 5);
  const first = mintDialogueId(at);
  assert.match(first, /^owner-202608310905-[a-z0-9]+$/);
  assert.notEqual(first, mintDialogueId(at));
});

test("a dialogue of steward turns alone is refused, and the form knows before the button", () => {
  const stewardOnly = [
    turn("2026-08-31T09:00", "我把交期那条改成五天。", "steward"),
    turn("2026-08-31T09:05", "顺带把供应商页也更新了。", "steward"),
  ];
  // What the button asks — dead until the owner has actually said something.
  assert.equal(hasOwnerTurn(stewardOnly), false);
  assert.equal(hasOwnerTurn([turn("2026-08-31T09:00", "   ", "owner"), ...stewardOnly]), false);
  assert.equal(hasOwnerTurn([turn("2026-08-31T09:00", "交期缩短了。"), ...stewardOnly]), true);
  // And the builder refuses, so a caller that skipped the button cannot post one either.
  assert.throws(
    () => buildOwnerStatementPayload(stewardOnly, BUILD, i18n),
    /ingest\.owner\.error\.noOwnerTurn/,
  );
});
