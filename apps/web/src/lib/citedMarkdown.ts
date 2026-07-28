/** A citation extracted from an answer and resolved to a real source id. */
export interface PreparedCitation {
  sourceId: string;
  blockStart: number | null;
  blockEnd: number | null;
}

export interface PreparedCitedMarkdown {
  markdown: string;
  citations: PreparedCitation[];
}

const CITE_GROUP_RE = /\[cite:[^\]]*\](?:\s*\[\s*¶[^\]]*\])*/g;
const BRACKET_RE = /\[(?:cite:)?\s*([^\]]*?)\s*\]/g;
const SPAN_RE = /(?:([^\s,;¶]+)\s*)?¶\s*(\d+)(?:\s*-\s*(\d+))?/g;
const BARE_SID_RE = /[^\s,;¶\]]+/g;

interface CiteRef {
  handle: string;
  from: number | null;
  to: number | null;
}

function parseGroup(group: string): CiteRef[] {
  const refs: CiteRef[] = [];
  let currentSid: string | null = null;
  let first = true;
  const bracketRe = new RegExp(BRACKET_RE.source, "g");
  let bracket: RegExpExecArray | null;
  while ((bracket = bracketRe.exec(group)) !== null) {
    const body = bracket[1] ?? "";
    const spanRe = new RegExp(SPAN_RE.source, "g");
    let span: RegExpExecArray | null;
    let sawSpan = false;
    while ((span = spanRe.exec(body)) !== null) {
      sawSpan = true;
      const sourceId: string | null = span[1] || currentSid;
      if (!sourceId) continue;
      currentSid = sourceId;
      const from = Number(span[2]);
      const to = span[3] ? Number(span[3]) : from;
      refs.push({ handle: sourceId, from, to });
    }
    if (!sawSpan && first) {
      const bareRe = new RegExp(BARE_SID_RE.source, "g");
      let bare: RegExpExecArray | null;
      while ((bare = bareRe.exec(body)) !== null) {
        currentSid = bare[0];
        refs.push({ handle: bare[0], from: null, to: null });
      }
    }
    first = false;
  }
  return refs;
}

function resolveHandle(handle: string, handles: Record<string, string>): string | null {
  const real = handles[handle];
  if (real) return real;
  if (/^s\d+$/.test(handle)) return null;
  return handle;
}

/**
 * Preserve Markdown structure while replacing resolvable citation groups with
 * private-protocol links. The React renderer turns those links into Footnotes.
 */
export function prepareCitedMarkdown(
  text: string,
  handles: Record<string, string> = {},
): PreparedCitedMarkdown {
  const citations: PreparedCitation[] = [];
  const markdown = text.replace(CITE_GROUP_RE, (raw) => {
    const resolved = parseGroup(raw)
      .map((ref) => ({ ...ref, sourceId: resolveHandle(ref.handle, handles) }))
      .filter(
        (ref): ref is CiteRef & { sourceId: string } => ref.sourceId != null,
      );
    if (resolved.length === 0) return raw;
    return resolved
      .map((ref) => {
        const index =
          citations.push({
            sourceId: ref.sourceId,
            blockStart: ref.from,
            blockEnd: ref.to,
          }) - 1;
        return `[citation](pneuma-cite:${index})`;
      })
      .join("");
  });
  return { markdown, citations };
}
