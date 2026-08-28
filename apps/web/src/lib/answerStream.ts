/**
 * The prose inside an answer that is still being written.
 *
 * A `text` answer streams as prose and needs nothing done to it. A `structured` answer
 * streams as JSON — `{"answer_kind":"fact","answer":"…","citations":[…]}` — because JSON is
 * what the provider emits token by token when the schema rides native structured output. Both
 * arrive through the same `token` frames, so without this the reader of a structured lane
 * watches raw JSON assemble itself, which is worse than watching nothing.
 *
 * WHY IT SNIFFS RATHER THAN BEING TOLD. The viewer does not choose the answer format — the
 * deployment does, server-side — so there is no request flag to branch on, and the one place
 * the format is stated (`answer_format` on the finished answer) arrives at the moment the
 * provisional text stops mattering. The shape is decided by the buffer itself: a structured
 * answer's first non-space character is `{` and a prose answer's is not.
 *
 * PURE AND RE-RUN WHOLE. Given the accumulated raw text it returns the prose so far — it does
 * not accumulate anything of its own and holds no state between frames, so a dropped or
 * re-ordered render can never leave it half-decoded. The buffer is a few KB at most.
 *
 * PARTIAL BY CONSTRUCTION. Everything here reads a string that may stop mid-token: before the
 * `answer` key has arrived there is nothing to show (`""`, not a guess); a truncated escape
 * (`\`, `\u00`) is HELD BACK rather than printed as its own characters, because a glyph that
 * appears and then changes reads as a bug. Text after the answer string closes — the
 * citations, the rest of the object — is not the answer and is ignored.
 */

/** The JSON key whose string value is the answer's prose. */
const ANSWER_VALUE = /"answer"\s*:\s*"/;

const ESCAPES: Record<string, string> = {
  n: "\n",
  t: "\t",
  r: "\r",
  b: "\b",
  f: "\f",
  '"': '"',
  "\\": "\\",
  "/": "/",
};

const HEX = /^[0-9a-fA-F]{4}$/;

/** A lone high surrogate at the tail is half a character: hold it back until its pair lands. */
function dropDanglingSurrogate(text: string): string {
  const last = text.charCodeAt(text.length - 1);
  return last >= 0xd800 && last <= 0xdbff ? text.slice(0, -1) : text;
}

/**
 * The decoded value of the `"answer"` string in a JSON buffer that may still be arriving.
 *
 * `""` when the key has not appeared yet — including when the buffer stops inside the key
 * itself (`…,"ans`) or before its opening quote (`"answer":`), which is why the match requires
 * the quote. `"answer_kind"` is not `"answer"`: the key's own closing quote is in the pattern,
 * so the field that precedes the answer in the schema can never be mistaken for it.
 */
export function extractAnswerString(raw: string): string {
  const match = ANSWER_VALUE.exec(raw);
  if (!match) return "";
  let out = "";
  for (let i = match.index + match[0].length; i < raw.length; i += 1) {
    const ch = raw[i];
    if (ch === '"') break; // the string closed — everything after it is not the answer
    if (ch !== "\\") {
      out += ch;
      continue;
    }
    const next = raw[i + 1];
    // The buffer stops on the backslash: the escape is not knowable yet.
    if (next === undefined) break;
    if (next === "u") {
      const hex = raw.slice(i + 2, i + 6);
      if (!HEX.test(hex)) break; // `\u00` — wait for the rest rather than print the digits
      out += String.fromCharCode(parseInt(hex, 16));
      i += 5;
      continue;
    }
    out += ESCAPES[next] ?? next;
    i += 1;
  }
  return dropDanglingSurrogate(out);
}

/**
 * What to SHOW for an answer still being written, whichever format the lane is answering in.
 *
 * A buffer that opens with `{` is a structured answer's JSON and yields its `answer` field;
 * anything else is prose and is itself. A prose answer that genuinely opens with a brace is
 * the one case this reads wrong, and it reads wrong by showing nothing for a moment rather
 * than by showing something false — the finished answer replaces it either way.
 */
export function provisionalAnswer(raw: string): string {
  return /^\s*\{/.test(raw) ? extractAnswerString(raw) : raw;
}
