// Copied wire types from the single-machine-edition design §§4.11, 6, 9 and 10.
// This client has no runtime/source dependency on the framework or console projects.
export type Known = boolean | null;
export type Backend = 'codex' | 'claude-code' | 'api';
export type Tab = 'dashboard' | 'search' | 'settings';
export interface Engine { pid: number | null; up: boolean; port: number; uptime: number | null }
export type StepMark = string | boolean | null;
export interface Steps {
  infra: StepMark; credentials: StepMark; profile: StepMark; skill: StepMark; first_compile: StepMark;
}
export const stepLabels: [keyof Steps, string][] = [
  ['infra', 'Infra'], ['credentials', 'Key'], ['profile', 'Profile'],
  ['skill', 'Skill'], ['first_compile', 'Compile'],
];
export interface SyncStatus {
  last_run_at: string | null;
  last_result: { scanned: number; new: number; increments: number; held: number; unchanged: number; rewritten: number; ingested: number; skipped: number } | null;
  watching: string[]; next_due: string | null; running: boolean; held: number;
}
export interface LibraryStatus {
  name: string; current: boolean; engine: Engine;
  queue: { pending: number; failed: number; succeeded?: number; failed_by_kind?: Record<string, number>; last_compile_at: string | null } | null;
  key: Known; engine_dir: string; canonical_head: string | null;
  skill_fresh: Known; steps: Steps; last_used: string | null;
  sync?: SyncStatus | null;
}
export interface Choices { backend: Backend; semantic_retrieval: boolean; embedding: string; unattended: boolean }
export interface ShallowLibrary extends LibraryStatus { tenant: string; choices: Choices; pid_alive: boolean; tcp_up: boolean; watching?: string[] }
export interface StatusDocument {
  home: { path: string; version: string }; docker: { reachable: boolean };
  services: Record<string, { port: number | null; up: Known }>;
  libraries: LibraryStatus[];
}
export interface Shallow extends Omit<StatusDocument, 'libraries'> {
  configured: boolean; libraries: ShallowLibrary[]; errors: string[];
  sync_config?: { interval_minutes: number; enabled: boolean };
}
export interface Snapshot { shallow: Shallow; deep: Record<string, StatusDocument>; fetched_at: number }
export interface Claim {
  anchor: string; document_path: string; text: string;
  citations: { source_id: string; block_start: number; block_end: number }[];
}
export interface SourceWindow { source_id: string; block_start: number; block_end: number; text: string }
export interface RecallResult {
  answer: string; used_claims: Claim[]; used_windows: SourceWindow[];
  citation_handles: Record<string, string>; documents_read: string[];
  used_episode_summaries?: SourceWindow[];
  used_component_evidence?: { claims: Claim[]; windows: SourceWindow[] }[];
  // Resolved by the desktop's read-only API client, because console routes use IDs.
  document_ids: Record<string, string>;
}
export const emptyState: Snapshot = {
  shallow: { configured: false, home: { path: '~/.pkc', version: '' }, docker: { reachable: false }, services: {}, libraries: [], errors: [] },
  deep: {}, fetched_at: 0,
};
export function health(state: Shallow): 'grey' | 'green' | 'amber' | 'red' {
  if (!state.configured) return 'grey';
  if (!state.docker.reachable) return 'red';
  if (state.errors.length || Object.keys(state.services).length !== 4
    || Object.values(state.services).some(s => s.up !== true) || state.libraries.some(l => !l.engine.up)) return 'amber';
  return 'green';
}
export const healthLabels = { grey: 'Set up your home', green: 'All engines ready', amber: 'Needs attention', red: 'Docker is unreachable' };
export function currentLibrary(state: Snapshot): ShallowLibrary | undefined {
  return state.shallow.libraries.find(l => l.current);
}
/**
 * What the pane may say about the stored embedding key, from observation alone.
 * Engine startup is fail-closed — with semantic retrieval on, the engine probes the
 * provider with the stored key and refuses to come up if it is rejected — so a running
 * engine is proof the provider accepted it. A stored key nothing has exercised is
 * reported as stored and no more. Without a library nothing has looked, and the pane
 * must stay usable, so the empty state (the fill-in field) is what the Owner sees.
 */
export type KeyReadout = 'absent' | 'unknown' | 'verified' | 'unverified' | 'unused';
export function keyReadout(library: ShallowLibrary | undefined, deep?: LibraryStatus): KeyReadout {
  if (!library) return 'absent';
  // Only the engine's own document knows whether a credential is present; the disk walk
  // never looks. Same overlay rule as every other readout: the deep answer, or nothing.
  const key = deep?.key ?? library.key;
  if (key === false) return 'absent';
  if (key === null) return 'unknown';
  if (!library.engine.up) return 'unverified';
  return library.choices.semantic_retrieval ? 'verified' : 'unused';
}
/** The credential the library's embedding provider is asked for. */
export function credentialName(embedding: string | undefined): string {
  const provider = embedding?.split(':')[0];
  if (provider === 'openai') return 'OPENAI_API_KEY';
  if (provider === 'google' || provider === 'google-genai') return 'GOOGLE_API_KEY';
  return 'OPENROUTER_API_KEY';
}
export function deepLibrary(state: Snapshot, library: ShallowLibrary): LibraryStatus | undefined {
  // Only the selected engine's own answer supplies its deep overlay. A sibling's
  // cached status cannot make a stopped engine appear healthy.
  return library.tcp_up ? state.deep[library.name]?.libraries.find(l => l.name === library.name) : undefined;
}
export function syncSummary(sync: SyncStatus | null | undefined, watching: string[] = []): string {
  return `watching ${watching.length} dirs · last sync ${sync?.last_run_at ? timeLabel(sync.last_run_at) : 'never'} · held ${sync?.held ?? '—'}`;
}
export function consoleUrl(port: number, kind?: 'document' | 'claim' | 'source', id?: string, anchor?: string | number): string {
  const root = `http://127.0.0.1:${port}/`;
  if (!kind || !id) return root;
  const view = kind === 'source' ? 'sources' : 'library';
  return root + '#/' + [view, kind, id, ...(anchor != null ? [String(anchor)] : [])].map(encodeURIComponent).join('/');
}
export function uptime(seconds: number | null): string {
  if (seconds === null) return 'Uptime unknown';
  if (seconds < 60) return 'Just started';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m uptime`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m uptime`;
}
export function timeLabel(stamp: string | boolean | null | undefined): string {
  if (!stamp) return 'Unknown';
  if (stamp === true) return 'done';
  const date = new Date(stamp);
  return Number.isNaN(date.valueOf()) ? 'Unknown' : date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
