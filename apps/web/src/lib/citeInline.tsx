/**
 * Inline citation rendering for recall/ask ANSWER prose.
 *
 * fast/briefing answers carry `[cite: sNN]` / `[cite: sNN ¶a-b]` query-local handles plus
 * a `citation_handles` map back to the real source_id; deep answers cite the real id
 * directly (`[cite: <uuid> ¶a-b]`, no aliasing). This turns each `[cite: …]` fragment in
 * the answer into inline, single-click provenance badges — one per span — that land in the
 * Sources panel on the cited source (+ block), reusing the 溯源动线 (`jump({kind:"source"})`).
 *
 * Parsing mirrors core's consumption-side `iter_answer_citations`
 * (recall/citation_alias.py): a bracket may MERGE spans — `[cite: s01 ¶1-3, s02 ¶2-4]` —
 * and a span with no id of its own inherits the last id seen; a trailing `[¶a-b]` bracket
 * continues the previous bracket's source. A source-level cite (no ¶) is still a badge to
 * the source. Anything that resolves to no real source (garbled handle) is left as plain
 * text — never clickable, never an error.
 */

import { Fragment } from "react";
import type { ReactNode } from "react";
import { Quote } from "lucide-react";
import { Chip } from "@/components/ui";
import { citationRange, citationShortLabel } from "@/lib/claim";
import { useApp } from "@/lib/store";

/** One `[cite: …]` marker plus any trailing `[¶a-b]` continuation brackets. */
const CITE_GROUP_RE = /\[cite:[^\]]*\](?:\s*\[\s*¶[^\]]*\])*/g;
/** A single bracket within a group — leading `[cite: …]` or a continuation `[¶ …]`. */
const BRACKET_RE = /\[(?:cite:)?\s*([^\]]*?)\s*\]/g;
/** One block span inside a bracket body; the id is optional (inherits the previous). */
const SPAN_RE = /(?:([^\s,;¶]+)\s*)?¶\s*(\d+)(?:\s*-\s*(\d+))?/g;
/** A bare source id inside a bracket that carries no `¶` span at all. */
const BARE_SID_RE = /[^\s,;¶\]]+/g;

interface CiteRef {
  /** the raw handle/id as written in the answer (`sNN` alias or a real source_id). */
  handle: string;
  from: number | null;
  to: number | null;
}

/** Parse one `[cite: …]` group into its constituent (handle, span) refs. */
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
      const sid: string | null = span[1] || currentSid;
      if (!sid) continue;
      currentSid = sid;
      const from = Number(span[2]);
      const to = span[3] ? Number(span[3]) : from;
      refs.push({ handle: sid, from, to });
    }
    if (!sawSpan && first) {
      // A leading bracket with no ¶ span: source-level cite(s), e.g. `[cite: s01]`.
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

/**
 * Resolve a written handle to a real source_id.
 * - present in the map → the real id (fast/briefing alias);
 * - an unmapped `sNN` handle → null (a dead alias epoch — leave as plain text);
 * - anything else → itself (deep cites the real id directly).
 */
function resolveHandle(handle: string, handles: Record<string, string>): string | null {
  const real = handles[handle];
  if (real) return real;
  if (/^s\d+$/.test(handle)) return null;
  return handle;
}

/** `sNN ¶a-b` / `<short-id> ¶a-b` (¶ omitted for a source-level cite). */
function badgeLabel(handle: string, from: number | null, to: number | null): string {
  const range = citationRange(from, to);
  const head = citationShortLabel(handle);
  return range ? `${head} ${range}` : head;
}

/**
 * Render answer prose with its `[cite: …]` markers replaced by clickable provenance
 * badges. Non-cite text passes through verbatim; a group that resolves to no real source
 * is left as its original text.
 */
export function CitedAnswer({
  text,
  handles,
}: {
  text: string;
  handles?: Record<string, string> | null;
}) {
  const { jump } = useApp();
  const map = handles ?? {};
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  const groupRe = new RegExp(CITE_GROUP_RE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = groupRe.exec(text)) !== null) {
    const start = m.index;
    const raw = m[0];
    if (start > last) nodes.push(<Fragment key={key++}>{text.slice(last, start)}</Fragment>);
    const resolvable = parseGroup(raw)
      .map((r) => ({ ...r, real: resolveHandle(r.handle, map) }))
      .filter((r): r is CiteRef & { real: string } => r.real != null);
    if (resolvable.length === 0) {
      // Nothing bindable in this bracket — keep it readable, not clickable.
      nodes.push(<Fragment key={key++}>{raw}</Fragment>);
    } else {
      nodes.push(
        <span
          key={key++}
          className="mx-0.5 inline-flex flex-wrap items-center gap-1 align-middle"
        >
          {resolvable.map((r, i) => (
            <Chip
              key={i}
              dotColor="var(--color-verified)"
              title="定位到 Sources"
              onClick={() =>
                jump({ kind: "source", id: r.real, block: r.from ?? undefined }, "sources")
              }
            >
              <Quote size={11} />
              {badgeLabel(r.handle, r.from, r.to)}
            </Chip>
          ))}
        </span>,
      );
    }
    last = start + raw.length;
  }
  if (last < text.length) nodes.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return <>{nodes}</>;
}
