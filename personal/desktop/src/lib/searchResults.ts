import { consoleUrl, type ConsolePreferences, type RecallResult } from './state.ts';

export interface Footnote { number: number; url: string; label: string }
export interface AnswerPart { text: string; citation?: Footnote }
export interface SearchEntry { key: string; title: string; text?: string; citation?: Footnote; sources: Footnote[]; derived?: boolean }

export function searchResults(result: RecallResult, port: number, preferences?: ConsolePreferences): { answer: AnswerPart[]; entries: SearchEntry[] } {
  // Every citation opens the same console the Open-console button does, so it carries the
  // same face: a footnote must not be the one door that lands the Owner in another language.
  const link = (kind: 'document' | 'claim' | 'source', id: string, anchor?: string | number) =>
    consoleUrl(port, kind, id, anchor, preferences);
  const notes = new Map<string, Footnote>();
  const cite = (url: string, label: string) => {
    if (!notes.has(url)) notes.set(url, { number: notes.size + 1, url, label });
    return notes.get(url)!;
  };
  const claims = [...result.used_claims, ...(result.used_component_evidence ?? []).flatMap(e => e.claims)]
    .filter((claim, i, all) => all.findIndex(c => c.anchor === claim.anchor && c.document_path === claim.document_path) === i);
  const windows = [...result.used_windows, ...(result.used_component_evidence ?? []).flatMap(e => e.windows)]
    .filter((hit, i, all) => all.findIndex(h => h.source_id === hit.source_id && h.block_start === hit.block_start && h.block_end === hit.block_end) === i);
  // Engine text is always plain text. Only a resolved citation becomes a link.
  const answer = result.answer.split(/(\[cite:\s*[^\]]+\])/g).map(text => {
    const match = /^\[cite:\s*([^\s\]]+)(?:\s+¶(\d+)(?:-(\d+))?)?\s*\]$/.exec(text);
    if (!match) return { text };
    const ref = match[1];
    const claim = claims.find(c => c.anchor === ref);
    const docId = result.document_ids[claim?.document_path ?? ref];
    if (docId) return { text, citation: cite(link(claim ? 'claim' : 'document', docId, claim?.anchor), claim?.document_path ?? ref) };
    const source = result.citation_handles[ref] ?? (match[2] ? ref : undefined);
    return source ? { text, citation: cite(link('source', source, match[2] ? Number(match[2]) : undefined), `${source}${match[2] ? ` ¶${match[2]}${match[3] ? `-${match[3]}` : ''}` : ''}`) } : { text };
  });
  const entries: SearchEntry[] = claims.map(claim => ({
    key: `claim:${claim.document_path}:${claim.anchor}`, title: claim.document_path, text: claim.text,
    citation: result.document_ids[claim.document_path] ? cite(link('claim', result.document_ids[claim.document_path], claim.anchor), claim.document_path) : undefined,
    sources: claim.citations.map(c => cite(link('source', c.source_id, c.block_start), `${c.source_id} ¶${c.block_start}-${c.block_end}`)),
  }));
  for (const path of [...new Set(result.documents_read ?? [])]) {
    if (result.document_ids[path]) entries.push({ key: `document:${path}`, title: path, sources: [],
      citation: cite(link('document', result.document_ids[path]), path) });
  }
  for (const hit of windows) {
    const title = `${hit.source_id} ¶${hit.block_start}-${hit.block_end}`;
    entries.push({ key: `source:${title}`, title, text: hit.text, sources: [],
      citation: cite(link('source', hit.source_id, hit.block_start), title) });
  }
  for (const hit of result.used_episode_summaries ?? []) {
    const title = `${hit.source_id} ¶${hit.block_start}-${hit.block_end}`;
    entries.push({ key: `summary:${title}`, title, derived: true, sources: [],
      citation: cite(link('source', hit.source_id, hit.block_start), title) });
  }
  return { answer, entries };
}
