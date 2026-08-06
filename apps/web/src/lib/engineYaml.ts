/**
 * Minimal YAML plumbing for engine files — deliberately NOT a YAML library.
 *
 * Engine files are flat `key: value` maps with comments. Prompt overlays are the one nested
 * shape: a single top-level `overlays:` key whose value is the map of catalog key →
 * replacement clause, which is what the service validates and what the scaffold generates
 * (`overlays: {}` when empty). These helpers round-trip exactly that: scalars are read and
 * replaced in place, overlay entries are read/written/removed as whole entries INSIDE the
 * `overlays` mapping, and every line they were not asked to touch — comments included —
 * survives byte-for-byte.
 */

interface EntrySpan {
  /** Index of the `key:` line. */
  start: number;
  /** One past the last line belonging to the entry (block body included). */
  end: number;
  /** Raw text after `key:`, trimmed. */
  value: string;
}

function isTopLevelKey(line: string, key: string): boolean {
  return !line.startsWith(" ") && !line.startsWith("\t") && line.startsWith(`${key}:`);
}

function isBlank(line: string): boolean {
  return line.trim() === "";
}

function isIndented(line: string): boolean {
  return line.startsWith(" ") || line.startsWith("\t");
}

/** Locate a top-level entry, following a `|`/`>` block header over its indented body. */
function findEntry(lines: string[], key: string): EntrySpan | null {
  for (let i = 0; i < lines.length; i++) {
    if (!isTopLevelKey(lines[i], key)) continue;
    const value = lines[i].slice(key.length + 1).trim();
    let end = i + 1;
    if (value === "|" || value === ">") {
      while (end < lines.length && (isIndented(lines[end]) || isBlank(lines[end]))) end++;
    }
    return { start: i, end, value };
  }
  return null;
}

/** De-indent a literal block body and re-join it with its trailing newline (YAML `|`). */
function readBlockBody(body: string[]): string {
  const first = body.find((l) => !isBlank(l));
  const indent = first ? first.length - first.trimStart().length : 0;
  const text = body.map((l) => (isBlank(l) ? "" : l.slice(indent))).join("\n");
  // The slice ends right before the next sibling line; a non-empty body keeps the document's
  // trailing newline, an empty one collapses to "".
  return text.trim() === "" ? "" : `${text.replace(/\n+$/, "")}\n`;
}

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

/**
 * A YAML scalar as the value it denotes: quotes removed, the two escapes we ever write
 * (`\\` and `\"`, plus `\n`) undone. Unquoted scalars are returned verbatim.
 */
export function unquoteYamlScalar(raw: string): string {
  const text = raw.trim();
  if (text.length >= 2 && text[0] === '"' && text.endsWith('"')) {
    return text
      .slice(1, -1)
      .replace(/\\n/g, "\n")
      .replace(/\\t/g, "\t")
      .replace(/\\(["\\])/g, "$1");
  }
  if (text.length >= 2 && text[0] === "'" && text.endsWith("'")) {
    return text.slice(1, -1).replace(/''/g, "'");
  }
  return text;
}

/**
 * The scalar value of a top-level `key:` line, or null when the key is absent or heads a
 * block. Comments and quoting are the caller's business — engine files use neither on
 * scalar lines.
 */
export function getYamlScalar(content: string, key: string): string | null {
  const span = findEntry(content.split("\n"), key);
  if (!span || span.value === "|" || span.value === ">") return null;
  return span.value;
}

/**
 * A string as a YAML scalar: ALWAYS double-quoted, with the escapes that makes necessary.
 *
 * Not "quoted when it looks like it needs to be". A model name holding `: `, a clause with a
 * `#`, a value that happens to spell `null`/`yes`/`1.0`, and above all the empty string —
 * `rerank_model: ""` is a supported configuration, and unquoted it becomes `rerank_model:`,
 * which is YAML null and a 400 the person cannot explain. Quoting everything removes the
 * judgement call, and the shape of a knob's value is never a UI decision.
 */
export function quoteYamlString(value: string): string {
  const escaped = value
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\n/g, "\\n")
    .replace(/\r/g, "\\r")
    .replace(/\t/g, "\\t");
  return `"${escaped}"`;
}

/** A knob value as the YAML scalar text for its line. Strings are always quoted. */
export function yamlScalar(value: string | number | boolean): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return quoteYamlString(value);
}

/**
 * Replace the scalar of a top-level `key:` line in place, preserving every other line
 * (comments included). Appends the entry at the end when the key is absent. A block entry
 * under the same key is replaced whole — scalar knobs never head blocks in practice.
 *
 * Takes the VALUE, not pre-serialised text: serialising here is what guarantees every write
 * goes through `yamlScalar` and no caller can hand-assemble an unquoted string.
 */
export function setYamlScalar(
  content: string,
  key: string,
  value: string | number | boolean,
): string {
  const lines = content.split("\n");
  const span = findEntry(lines, key);
  const entry = `${key}: ${yamlScalar(value)}`;
  if (!span) {
    const out = content.endsWith("\n") || content === "" ? content : `${content}\n`;
    return `${out}${entry}\n`;
  }
  lines.splice(span.start, span.end - span.start, entry);
  return lines.join("\n");
}

/* --------------------------------------------------------------- prompt overlays
 *
 * The file's real shape (scaffold-generated, service-validated) is ONE top-level `overlays`
 * key over the map:
 *
 *     # comments about overlays
 *     overlays:
 *       recall.close.answer_honestly: |
 *         Say so plainly.
 *
 * Empty is written `overlays: {}` — a flow mapping, so the file always has an `overlays` key
 * of the right type. Treating the catalog keys as top-level entries (which this module used
 * to do) reads one fake overlay named "overlays" and writes keys the service refuses.
 */

const OVERLAYS_KEY = "overlays";
const ENTRY_INDENT = "  ";

interface OverlaysBlock {
  /** Index of the `overlays:` line. */
  header: number;
  /** Text after `overlays:`, trimmed — "{}" or "" in practice. */
  inline: string;
  /** First line of the nested mapping. */
  bodyStart: number;
  /** One past its last line (blank padding included). */
  bodyEnd: number;
}

function findOverlaysBlock(lines: string[]): OverlaysBlock | null {
  const header = lines.findIndex((line) => isTopLevelKey(line, OVERLAYS_KEY));
  if (header < 0) return null;
  const inline = lines[header].slice(OVERLAYS_KEY.length + 1).trim();
  let bodyEnd = header + 1;
  while (bodyEnd < lines.length && (isIndented(lines[bodyEnd]) || isBlank(lines[bodyEnd]))) {
    bodyEnd++;
  }
  return { header, inline, bodyStart: header + 1, bodyEnd };
}

interface OverlayEntry {
  key: string;
  /** Index of the `key:` line. */
  start: number;
  /** One past the last line of the entry (block body included). */
  end: number;
  /** Raw text after `key:`, trimmed. */
  value: string;
}

/** Every entry of the `overlays` mapping, in file order. */
function overlayEntries(lines: string[], block: OverlaysBlock): OverlayEntry[] {
  if (block.inline === "{}" || block.inline.startsWith("{")) return [];
  const body = lines.slice(block.bodyStart, block.bodyEnd);
  const first = body.find((l) => !isBlank(l));
  if (!first) return [];
  const base = indentOf(first);
  const entries: OverlayEntry[] = [];
  for (let i = 0; i < body.length; i++) {
    const line = body[i];
    if (isBlank(line) || indentOf(line) !== base || line.trimStart().startsWith("#")) continue;
    const text = line.trimStart();
    const colon = text.indexOf(":");
    if (colon <= 0) continue;
    const key = unquoteYamlScalar(text.slice(0, colon));
    const value = text.slice(colon + 1).trim();
    let end = i + 1;
    if (value === "|" || value === ">") {
      while (end < body.length && (isBlank(body[end]) || indentOf(body[end]) > base)) end++;
      // Blank lines are part of a clause when something indented follows them and padding
      // when nothing does. Leaving the padding out of the entry is what keeps a replace or a
      // remove from eating the blank line before the next entry — or the file's own last one.
      while (end > i + 1 && isBlank(body[end - 1])) end--;
    }
    entries.push({
      key,
      start: block.bodyStart + i,
      end: block.bodyStart + end,
      value,
    });
    i = end - 1;
  }
  return entries;
}

/** The clause an entry denotes: a literal block de-indented, a scalar unquoted. */
function readEntry(lines: string[], entry: OverlayEntry): string {
  if (entry.value === "|" || entry.value === ">") {
    return readBlockBody(lines.slice(entry.start + 1, entry.end));
  }
  return unquoteYamlScalar(entry.value);
}

/** The lines one entry is serialised as: `  key: |` plus its further-indented body. */
function entryLines(key: string, clause: string): string[] {
  const body = clause.replace(/\n+$/, "").split("\n");
  return [
    `${ENTRY_INDENT}${key}: |`,
    ...body.map((l) => (isBlank(l) ? "" : `${ENTRY_INDENT}${ENTRY_INDENT}${l}`)),
  ];
}

/** Every override in the file's `overlays` mapping as `catalog key → clause`. */
export function getOverlayMap(content: string): Record<string, string> {
  const lines = content.split("\n");
  const block = findOverlaysBlock(lines);
  if (!block) return {};
  const map: Record<string, string> = {};
  for (const entry of overlayEntries(lines, block)) {
    map[entry.key] = readEntry(lines, entry);
  }
  return map;
}

/**
 * Insert or replace one override inside the `overlays` mapping — in place when the key is
 * already there, appended after the last entry otherwise. The clause is always written as a
 * literal block so multi-line replacements round-trip. A file with no `overlays` key at all
 * gains one; `overlays: {}` becomes a real mapping.
 */
export function setOverlayEntry(content: string, key: string, clause: string): string {
  const lines = content.split("\n");
  const block = findOverlaysBlock(lines);
  const entry = entryLines(key, clause);
  if (!block) {
    const out = content.endsWith("\n") || content === "" ? content : `${content}\n`;
    return `${out}${OVERLAYS_KEY}:\n${entry.join("\n")}\n`;
  }
  const existing = overlayEntries(lines, block).find((e) => e.key === key);
  if (existing) {
    lines.splice(existing.start, existing.end - existing.start, ...entry);
    return lines.join("\n");
  }
  if (block.inline !== "") {
    // `overlays: {}` (or any flow value) — the mapping starts here, so the header line is
    // rewritten and the body it never had is inserted under it.
    lines.splice(block.header, 1, `${OVERLAYS_KEY}:`, ...entry);
    return lines.join("\n");
  }
  // Append after the last non-blank body line, so trailing blank padding stays trailing.
  let at = block.bodyEnd;
  while (at > block.bodyStart && isBlank(lines[at - 1])) at--;
  lines.splice(at, 0, ...entry);
  return lines.join("\n");
}

/**
 * Drop one override (its `key:` line and block body). A missing key changes nothing. Removing
 * the last one restores `overlays: {}` rather than leaving a keyless `overlays:` — the file
 * keeps stating an empty override map instead of stating nothing.
 */
export function removeOverlayEntry(content: string, key: string): string {
  const lines = content.split("\n");
  const block = findOverlaysBlock(lines);
  if (!block) return content;
  const entries = overlayEntries(lines, block);
  const target = entries.find((e) => e.key === key);
  if (!target) return content;
  if (entries.length === 1) {
    lines.splice(block.header, block.bodyEnd - block.header, `${OVERLAYS_KEY}: {}`);
  } else {
    lines.splice(target.start, target.end - target.start);
  }
  const joined = lines.join("\n");
  // The removed span could have swallowed the file's trailing newline; hand it back.
  return content.endsWith("\n") && !joined.endsWith("\n") ? `${joined}\n` : joined;
}
