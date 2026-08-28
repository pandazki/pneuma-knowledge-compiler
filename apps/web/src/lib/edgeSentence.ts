/**
 * An edge's sentence, for a dense row that already names the document at the other end.
 *
 * A neighbourhood row prints the neighbour's title on its first line and, beneath it, THE
 * SENTENCE THAT MADE THE LINK. Most of those sentences are ledger claims, and flattening
 * their inline markdown to its labels is enough. The ones written by the overview's
 * `connections` slot are not: the compile model writes them as a list item whose link label
 * is the target's own path — `- [../projects/x.md](../../projects/x.md) —— why` — and closes
 * them with the ledger anchors they rest on (`c:a1b2c3d4`). Read as prose, that row said
 * "- ../projects/x.md —— why c:a1b2c3d4", which names nothing and counts nothing.
 *
 * So this does four things a claim flattener does not: it drops the list marker, it turns a
 * path-shaped label into the document's title (or its file stem when the title is unknown),
 * it strips the trailing anchor tokens, and it removes the compile machinery a schema-v1
 * export still carries. Import-free, so it is transpiled and tested alone.
 */

const MACHINERY_RE = /<!--[\s\S]*?-->|\[cite:[^\]]*\]|\[inferred\]/gi;
const LIST_MARKER_RE = /^\s*(?:[-*+]|\d+[.)])\s+/;
const LINK_RE = /!?\[([^\]]*)\]\(([^)]*)\)/g;
/** The overview's ledger references, at the end of the line: `c:600ee22a c:9a030a08`. */
const TRAILING_ANCHORS_RE = /(?:\s*\bc:[0-9a-f]{6,12}\b)+\s*$/i;
/** A label that is a path rather than a name: `../projects/x.md`, `people/y.md`, `./z.md`. */
const PATH_LABEL_RE = /^(?:\.{1,2}\/)*[^\s()]+\.md$/i;

/** `../../projects/x.md#frag` → `projects/x.md`: the canonical path a relative link names. */
export function canonicalPathOf(href: string): string {
  return href
    .split("#")[0]!
    .trim()
    .replace(/^(?:\.{1,2}\/)+/, "");
}

function stemOf(path: string): string {
  const file = path.slice(path.lastIndexOf("/") + 1);
  return file.replace(/\.md$/i, "");
}

export function edgeSentence(
  sentence: string,
  titleOf?: (path: string) => string | null,
): string {
  let out = sentence.replace(MACHINERY_RE, "").replace(LIST_MARKER_RE, "");
  out = out.replace(LINK_RE, (_m, label: string, href: string) => {
    if (!PATH_LABEL_RE.test(label.trim())) return label;
    const byLabel = titleOf?.(canonicalPathOf(label));
    if (byLabel) return byLabel;
    const byHref = titleOf?.(canonicalPathOf(href));
    return byHref ?? stemOf(canonicalPathOf(label));
  });
  out = out
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(TRAILING_ANCHORS_RE, "");
  return out.replace(/[ \t]+/g, " ").trim();
}
