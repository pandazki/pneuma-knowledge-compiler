/**
 * The prose inside an answer that is still being written (`lib/answerStream.ts`).
 *
 * A `text` answer streams as prose. A `structured` answer streams as JSON, because JSON is
 * what the provider emits token by token — so without this the reader of a structured lane
 * watches `{"answer_kind":"fact","answer":"林薇负` assemble itself, which is worse than
 * watching nothing at all.
 *
 * Everything here is about reading a string that may STOP ANYWHERE. The rule throughout is
 * that a partial token is held back rather than guessed: a glyph that appears and then
 * changes reads as a bug, and "nothing yet" is always the honest answer.
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

const { extractAnswerString, provisionalAnswer } = await import(
  await tsModuleUrl(new URL("../src/lib/answerStream.ts", import.meta.url))
);

test("nothing is shown until the answer key itself has arrived", () => {
  assert.equal(extractAnswerString(""), "");
  assert.equal(extractAnswerString("{"), "");
  assert.equal(extractAnswerString('{"answer_kind":"fact","ans'), "");
  // The key is complete but its value has not opened yet: still nothing to show.
  assert.equal(extractAnswerString('{"answer_kind":"fact","answer"'), "");
  assert.equal(extractAnswerString('{"answer_kind":"fact","answer":'), "");
  assert.equal(extractAnswerString('{"answer_kind":"fact","answer": '), "");
});

test("the field that PRECEDES the answer is never mistaken for it", () => {
  // `answer_kind` shares a prefix with `answer` and arrives first in the real schema. The
  // key's own closing quote is what keeps them apart.
  assert.equal(extractAnswerString('{"answer_kind":"fact"}'), "");
  assert.equal(
    extractAnswerString('{"answer_kind":"fact","answer":"林薇负责采购"}'),
    "林薇负责采购",
  );
});

test("the prose grows one token at a time as the buffer does", () => {
  const whole = '{"answer_kind":"fact","answer":"林薇负责采购","citations":[]}';
  const seen = [];
  for (let i = 0; i <= whole.length; i += 1) seen.push(extractAnswerString(whole.slice(0, i)));
  // Never shrinks, and lands on the finished answer.
  for (let i = 1; i < seen.length; i += 1) {
    assert.ok(seen[i].length >= seen[i - 1].length, `shrank at ${i}`);
  }
  assert.equal(seen.at(-1), "林薇负责采购");
});

test("escapes are decoded, not printed", () => {
  assert.equal(extractAnswerString('{"answer":"a\\nb"}'), "a\nb");
  assert.equal(extractAnswerString('{"answer":"她说\\"好\\""}'), '她说"好"');
  assert.equal(extractAnswerString('{"answer":"a\\\\b"}'), "a\\b");
  assert.equal(extractAnswerString('{"answer":"\\u6797\\u8587"}'), "林薇");
});

test("an escape the buffer stopped inside is held back rather than printed raw", () => {
  // A trailing backslash: what it escapes is not knowable yet.
  assert.equal(extractAnswerString('{"answer":"ab\\'), "ab");
  // A half-written \\u: printing "00" and then replacing it with a glyph is worse than a
  // one-frame pause.
  assert.equal(extractAnswerString('{"answer":"ab\\u67'), "ab");
  assert.equal(extractAnswerString('{"answer":"ab\\u6797'), "ab林");
});

test("half a surrogate pair waits for its other half", () => {
  // 😀 is \\ud83d\\ude00. The high surrogate alone is not a character.
  assert.equal(extractAnswerString('{"answer":"hi \\ud83d'), "hi ");
  assert.equal(extractAnswerString('{"answer":"hi \\ud83d\\ude00'), "hi 😀");
});

test("everything after the answer string closes is not the answer", () => {
  assert.equal(
    extractAnswerString(
      '{"answer":"林薇负责采购","citations":["[cite: s01 ¶3-4]"],"answer_kind":"fact"}',
    ),
    "林薇负责采购",
  );
});

test("a prose answer passes through untouched and a JSON one is read", () => {
  // The viewer is never told which format the deployment answers in — the buffer's own first
  // character is what decides, and a prose answer's is not `{`.
  assert.equal(provisionalAnswer("林薇负责"), "林薇负责");
  assert.equal(provisionalAnswer(""), "");
  assert.equal(provisionalAnswer('{"answer_kind":"fact","answer":"林薇负'), "林薇负");
  assert.equal(provisionalAnswer('\n  {"answer":"x"}'), "x");
});
