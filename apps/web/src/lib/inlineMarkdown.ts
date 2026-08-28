/**
 * The inline markdown a claim may carry — links, code spans, emphasis — split into segments
 * a renderer can lay out without a markdown engine. Claims are one sentence of prose: the
 * compile writes `[Title](../people/x.md)` cross-links and `code` spans into them, and the
 * page must turn those into jumps and code rather than printing the brackets.
 *
 * Import-free on purpose so it transpiles standalone under the node tests.
 */
export type InlineSegment =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; label: string; href: string };

// One pass, first match wins: link, code span, bold. Emphasis with a single `*` is left
// alone — in claim prose a lone asterisk is far more often a literal than a marker.
const INLINE_RE = /\[([^\]\n]+)\]\(([^)\s]+)\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*/g;

export function splitInlineMarkdown(md: string): InlineSegment[] {
  const out: InlineSegment[] = [];
  let last = 0;
  for (const m of md.matchAll(INLINE_RE)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: "text", text: md.slice(last, at) });
    if (m[1] != null && m[2] != null) out.push({ kind: "link", label: m[1], href: m[2] });
    else if (m[3] != null) out.push({ kind: "code", text: m[3] });
    else if (m[4] != null) out.push({ kind: "strong", text: m[4] });
    last = at + m[0].length;
  }
  if (last < md.length) out.push({ kind: "text", text: md.slice(last) });
  return out;
}

/** True for an absolute web URL — the one kind of link a claim can carry that leaves the app. */
export function isExternalHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}
