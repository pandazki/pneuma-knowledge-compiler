/**
 * Markdown that is still being written.
 *
 * A streamed answer is re-rendered on every delta, and the tail of it is always a half-typed
 * sentence — which Markdown mostly tolerates. Two constructs do not: a fenced code block and
 * a GFM table are both *frames*, and while the frame is open the parser has to guess. An
 * unclosed ``` swallows every following paragraph into a code block that un-swallows itself
 * the moment the closing fence arrives; a table whose delimiter row has not been typed yet
 * flickers between a paragraph and a one-column table as the pipes land. Either way the page
 * jumps, and the Owner is reading a layout instead of an answer.
 *
 * So the tail is cut off before the parser sees it: `splitStreamingMarkdown` returns the part
 * that is settled Markdown and, separately, the unfinished frame at the end. The view renders
 * the first through the ordinary renderer and the second as plain preformatted text, which is
 * what it will look like anyway once it closes. Nothing is hidden — every character typed so
 * far is on the screen — and the reflow happens once, when the frame actually closes.
 *
 * Pure, with no imports: the node tests transpile this file standalone.
 */

export type PendingKind = "code" | "table";

export interface PendingBlock {
  kind: PendingKind;
  /** A fence's info string (`ts`, `bash`) — empty for a table or a bare fence. */
  info: string;
  /** The text inside the unfinished frame, as typed so far. */
  text: string;
}

export interface StreamingMarkdown {
  /** Settled Markdown: safe to hand to the Markdown renderer. */
  body: string;
  /** The unfinished frame at the tail, or null when the text ends on solid ground. */
  pending: PendingBlock | null;
}

const FENCE_RE = /^(\s{0,3})(`{3,}|~{3,})(.*)$/;

/** Is this line a table delimiter row — `| --- | :-: |` — as GFM defines one? */
export function isDelimiterRow(line: string): boolean {
  const trimmed = line.trim();
  if (trimmed === "") return false;
  if (!/^\|?[\s:|-]+\|?$/.test(trimmed)) return false;
  const cells = trimmed.replace(/^\|/, "").replace(/\|$/, "").split("|");
  return cells.length > 0 && cells.every((cell) => /^\s*:?-{1,}:?\s*$/.test(cell));
}

function looksLikeTableRow(line: string): boolean {
  return line.trim().startsWith("|");
}

/**
 * Cut the unfinished frame off the end of a streaming Markdown text.
 *
 * A fence wins over a table: inside a code block a line of pipes is code, not a row.
 */
export function splitStreamingMarkdown(text: string): StreamingMarkdown {
  if (text === "") return { body: "", pending: null };
  const lines = text.split("\n");

  // 1. An open fence: walk the whole text tracking fence state, and remember where the last
  //    still-open fence started.
  let openAt = -1;
  let openMarker = "";
  for (let i = 0; i < lines.length; i += 1) {
    const match = FENCE_RE.exec(lines[i]);
    if (!match) continue;
    const marker = match[2];
    if (openAt < 0) {
      openAt = i;
      openMarker = marker;
    } else if (marker[0] === openMarker[0] && marker.length >= openMarker.length && match[3].trim() === "") {
      openAt = -1;
      openMarker = "";
    }
  }
  if (openAt >= 0) {
    const opener = FENCE_RE.exec(lines[openAt]);
    return {
      body: lines.slice(0, openAt).join("\n"),
      pending: {
        kind: "code",
        info: (opener?.[3] ?? "").trim(),
        text: lines.slice(openAt + 1).join("\n"),
      },
    };
  }

  // 2. A table whose delimiter row has not landed yet. Only the block at the very END of the
  //    text can be unfinished; anything earlier was settled by the line that followed it.
  let start = lines.length;
  while (start > 0 && looksLikeTableRow(lines[start - 1])) start -= 1;
  if (start < lines.length) {
    const rows = lines.slice(start);
    const settled = rows.length >= 2 && isDelimiterRow(rows[1]);
    if (!settled) {
      return {
        body: lines.slice(0, start).join("\n"),
        pending: { kind: "table", info: "", text: rows.join("\n") },
      };
    }
  }

  return { body: text, pending: null };
}
