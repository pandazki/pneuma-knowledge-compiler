/**
 * pneuma-knowledge service API client (M2). A thin fetch wrapper — no request library, no
 * global cache; panels own their own loading state. Every path is scoped by
 * user_id after `/v1/users/` (invariant I1). The base URL comes from
 * `VITE_API_BASE` (empty → same-origin relative `/v1/...`, proxied to the service
 * by the vite dev server; see vite.config.ts).
 */

import { tx } from "./i18n";
import type { ClaimLabel, UserProfile } from "./types";
import type { HistoryCounts, HistoryItemEnvelope } from "./history";
import { buildPageQuery, type Page } from "./pagination";

const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (e) {
    // Network-level failure (service down, CORS blocked, offline).
    throw new ApiError(tx("service.unreachable", { detail: (e as Error).message }), 0);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body?.detail != null) detail = String(body.detail);
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

/* ---------------------------------------------------------------- Response shapes */

export interface IntakePlan {
  canonical_treatment: "full" | "distill" | "card" | "none" | string;
  semantic_indexing: "full" | "summary" | "none" | string;
  rationale: string;
  user_confirmed: boolean;
}

export interface SourceSummary {
  source_id: string;
  kind: string;
  origin: string;
  source_class: string;
  title: string;
  /** The ingest wall clock. NOT when the material happened — see `occurred_on`. */
  created_at: string;
  /**
   * The day the material happened (`YYYY-MM-DD`), in the subject's own zone. null for a
   * source that never got one; `lib/sourceFilter.ts` owns the fallback and marks it.
   */
  occurred_on: string | null;
  intake_plan: IntakePlan | null;
  block_count: number;
  /** null = not yet compiled into canonical; set once the worker digests it (M3b). */
  digested_at: string | null;
}

export interface ActivityDay {
  date: string;
  count: number;
  kinds: Record<string, number>;
}

export interface ActivityCalendar {
  days: ActivityDay[];
}

export interface SourceBlock {
  index: number;
  text: string;
  section_path: string[];
  images: SourceImage[];
}

export interface DerivedMediaText {
  kind: "caption" | "ocr";
  text: string;
  producer: string;
}

export interface SourceImage {
  image_id: string;
  mime_type: string;
  sha256: string;
  size_bytes: number;
  derived: DerivedMediaText[];
  metadata: Record<string, unknown>;
  url: string;
}

export interface SectionSpan {
  path: string[];
  start_block: number;
  end_block: number;
}

export interface SourceDetail {
  source_id: string;
  kind: string;
  origin: string;
  source_class: string;
  title: string;
  mime: string;
  created_at: string;
  meta: Record<string, unknown>;
  intake_plan: IntakePlan | null;
  structure: { sections: SectionSpan[] };
  blocks: SourceBlock[];
}

export interface RecallHit {
  source_id: string;
  block_start: number;
  block_end: number;
  // Exact char span of the semantic chunk (offsets into the block-joined string);
  // null for a lexical-only hit. The UI keys drill-down on the block interval.
  char_start?: number | null;
  char_end?: number | null;
  text: string;
  paths: string[];
  score: number;
}

export interface IngestResult {
  source_id: string;
  intake_plan: IntakePlan;
  deduplicated: boolean;
}

export interface OfficialImportResult {
  contract_schema: string;
  sources: IngestResult[];
}

export interface ConversationTurnInput {
  speaker: string;
  text: string;
  at?: string | null;
}

/** locator v1: `{ section: [...] }` or `{ blocks: [start, end] }` (source.py). */
export type Locator = { section: string[] } | { blocks: [number, number] };

/* ------------------------------------------------------------------- Endpoints */

const u = encodeURIComponent;

export function listUsers(): Promise<string[]> {
  return req<string[]>("/v1/users");
}

/**
 * The user_id product profile. The service synthesizes deterministically for
 * unknown ids, so this never 404s — any id (incl. a brand-new one) resolves.
 */
export function getUserProfile(userId: string): Promise<UserProfile> {
  return req<UserProfile>(`/v1/users/${u(userId)}/profile`);
}

/**
 * The editable subset of a UserProfile (the onboarding fields). Sent to PUT
 * /profile, which merges + persists it and returns the full profile with
 * `source = "user"`. Read-only/derived fields (avatar, level_style, joined_at,
 * source, user_id) are NOT part of the patch.
 */
export interface UserProfilePatch {
  display_name?: string;
  gender?: string | null;
  birth_year?: number | null;
  industry?: string;
  industry_other?: string | null;
  role?: string;
  role_other?: string | null;
  level?: string;
  occupation?: string;
  bio?: string;
  interests?: string[];
  locale?: { city?: string; country?: string; timezone?: string; language?: string };
  preferences?: { response_language?: string; units?: string; privacy_level?: string };
  workspace?: {
    operating_mode?: string;
    primary_stack?: string;
    automation_level?: string;
    active_since?: string;
  };
}

/**
 * Persist an edited/created profile. The service merges the patch onto the current
 * (or freshly-synthesized) picture, saves it, and returns the full UserProfile with
 * `source = "user"`. Works for a brand-new user_id too (it materializes it).
 */
export function putUserProfile(userId: string, patch: UserProfilePatch): Promise<UserProfile> {
  return req<UserProfile>(`/v1/users/${u(userId)}/profile`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

/**
 * "Generate a persona with AI": expand one sentence into a complete, self-consistent
 * UserProfile via the LLM. Not persisted — the returned draft pre-fills the create form
 * (mirroring the deterministic random fill). Pass a userId to pin the id already typed;
 * otherwise the service derives one from the persona.
 */
export function generateProfile(sentence: string, userId?: string): Promise<UserProfile> {
  return req<UserProfile>("/v1/profile/generate", {
    method: "POST",
    body: JSON.stringify({ sentence, user_id: userId ?? null }),
  });
}

export interface SourcePageParams {
  limit?: number;
  cursor?: string | null;
  query?: string | null;
  kind?: string | null;
}

export interface WorkspaceSummary {
  sources: number;
  jobs: number;
  documents: number;
  claims: number;
  snapshots: number;
}

export function getWorkspaceSummary(userId: string): Promise<WorkspaceSummary> {
  return req<WorkspaceSummary>(`/v1/users/${u(userId)}/summary`);
}

export function listSources(
  userId: string,
  params: SourcePageParams = {},
): Promise<Page<SourceSummary>> {
  const query = buildPageQuery({
    limit: params.limit ?? 25,
    cursor: params.cursor,
    query: params.query,
    kind: params.kind,
  });
  return req<Page<SourceSummary>>(`/v1/users/${u(userId)}/sources${query}`);
}

function browserCalendarOffset(): number {
  return -new Date().getTimezoneOffset();
}

/**
 * Daily source counts by INGEST day, from the service. The Sources view no longer reads it:
 * its calendar counts corpus time (`occurred_on`) off the catalogue it already holds, so the
 * calendar, the list order and the range filter cannot disagree about when something happened.
 * The route stays, and so does its binding.
 */
export function getSourceActivity(userId: string): Promise<ActivityCalendar> {
  return req<ActivityCalendar>(
    `/v1/users/${u(userId)}/sources/activity?offset_minutes=${browserCalendarOffset()}`,
  );
}

/** Progressive compatibility helper for source pickers that still need a full inventory. */
export async function listAllSources(userId: string): Promise<SourceSummary[]> {
  return crawlSources(userId);
}

/** How many rows one catalogue-crawl round trip asks for (the route's stated ceiling). */
const CATALOGUE_PAGE = 500;

/**
 * The whole source catalogue, page by page.
 *
 * Filtering a five-figure inventory by title, kind and date is directory lookup over
 * metadata already on the wire — it belongs in the reader's hands, answering as they type,
 * not in a round trip per keystroke. `onProgress` is called with the rows so far after each
 * page so the list can paint while the tail is still arriving, and `signal` lets a user
 * switch abandon a crawl in flight.
 */
export async function crawlSources(
  userId: string,
  options: {
    onProgress?: (items: SourceSummary[], total: number) => void;
    signal?: AbortSignal;
  } = {},
): Promise<SourceSummary[]> {
  const items: SourceSummary[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  do {
    if (options.signal?.aborted) return items;
    const page: Page<SourceSummary> = await listSources(userId, {
      limit: CATALOGUE_PAGE,
      cursor,
    });
    items.push(...page.items);
    options.onProgress?.(items, page.page.total);
    cursor = page.page.next_cursor;
    if (cursor && seen.has(cursor)) {
      throw new ApiError(tx("service.duplicateCursor"), 500);
    }
    if (cursor) seen.add(cursor);
  } while (cursor);
  return items;
}

export function getSource(userId: string, sourceId: string): Promise<SourceDetail> {
  return req<SourceDetail>(`/v1/users/${u(userId)}/sources/${u(sourceId)}`);
}

export function fetchLocator(
  userId: string,
  sourceId: string,
  locator: Locator,
): Promise<{ text: string }> {
  return req<{ text: string }>(`/v1/users/${u(userId)}/sources/${u(sourceId)}/fetch`, {
    method: "POST",
    body: JSON.stringify({ locator }),
  });
}

export function ingestConversation(
  userId: string,
  body: { title: string; turns: ConversationTurnInput[] },
): Promise<IngestResult> {
  return req<IngestResult>(`/v1/users/${u(userId)}/sources/conversation`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function importOfficialSource(
  userId: string,
  payload: Record<string, unknown>,
): Promise<OfficialImportResult> {
  return req<OfficialImportResult>(`/v1/users/${u(userId)}/sources/import`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function recall(
  userId: string,
  body: { query: string; mode?: string; limit?: number; snapshot?: string | null },
): Promise<RecallHit[]> {
  return req<RecallHit[]>(`/v1/users/${u(userId)}/recall`, {
    method: "POST",
    body: JSON.stringify({ mode: "rag", limit: 10, ...body }),
  });
}

/* ------------------------------------------------------ fast/deep recall (M4) */

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read: number;
  cache_creation: number;
}

export interface UsedClaim {
  anchor: string;
  document_path: string;
  section_path: string[];
  text: string;
  citations: { source_id: string; block_start: number; block_end: number }[];
  paths: string[];
  score: number;
}

/** Dense generated L2 content used by fast recall. It locates back to source blocks but is
 * deliberately not represented as a verbatim excerpt. */
export interface EpisodeSummary {
  source_id: string;
  block_start: number;
  block_end: number;
  text: string;
  score: number;
  source_title: string;
  source_occurred_on: string;
  section_path: string[];
  derived: true;
  verbatim: false;
}

/** One agentic step in a deep recall: which tool ran, with what query/locator, and the
 * (preview-capped) result it returned. */
export interface TrailStep {
  tool: string;
  query?: string;
  source_id?: string;
  locator?: unknown;
  hits?: number;
  chars?: number;
  result?: string;
  error?: string;
}

export interface RecallAnswer {
  mode: "fast" | "deep";
  answer: string;
  /** Citation-free semantic payload for automation; the UI renders the cited `answer`. */
  answer_text: string;
  as_of: string;
  used_claims: UsedClaim[];
  /** fast only: generated, source-addressed L2 episode descriptions shown to the model. */
  used_episode_summaries?: EpisodeSummary[];
  /** L1/L2 body windows fused into the answer — uncompiled content, drill-downable. */
  used_windows?: RecallHit[];
  /** deep only: the agentic search trace, one record per tool call in execution order. */
  trail?: TrailStep[];
  /** {handle: real_source_id} for the query-local `sNN` markers in `answer` (fast lane).
   * Empty for deep (it cites real ids directly). The UI reverse-binds inline `[cite:]`. */
  citation_handles?: Record<string, string>;
  /** The frozen snapshot this answer was scoped to; null for the live base. */
  snapshot?: {
    snapshot_id: string;
    label: string;
    canonical_ref: string;
    created_at: string | null;
  } | null;
  /** Original multimodal evidence actually delivered for this query. */
  included_original_modalities?: OriginalModality[];
  original_modality_counts?: Record<string, number>;
  /** Fast-only context composition and answer-wire telemetry. */
  evidence_strategy?: "ranked" | "select";
  evidence_selection_degraded?: "timeout" | "error" | null;
  claim_candidates?: number;
  episode_summary_candidates?: number;
  window_candidates?: number;
  /** Selector choices before deterministic safety anchors and provenance rollback. */
  model_selected_claims?: number;
  model_selected_episode_summaries?: number;
  model_selected_windows?: number;
  answer_format?: "text" | "structured";
  answer_kind?: "fact" | "list" | "time" | "duration" | "yes_no" | "inference" | "no_record" | null;
  answer_format_degraded?: "timeout" | "error" | null;
  token_usage: TokenUsage;
}

export type OriginalModality = "image";

/** fast/deep recall — an answer over capped canonical claims (as_of server-injected).
 *
 * `snapshot` (a kb-snapshot id or label) pins the answer to a frozen snapshot; omit it for
 * the live base. An unknown or not-yet-ready snapshot is an error, never a quiet fallback to
 * HEAD — see the service's `_resolve_plane`. */
export function recallAnswer(
  userId: string,
  body: {
    query: string;
    mode: "fast" | "deep";
    as_of?: string;
    snapshot?: string | null;
    evidence_strategy?: "ranked" | "select";
    answer_format?: "text" | "structured";
    include_original_modalities?: OriginalModality[];
  },
): Promise<RecallAnswer> {
  return req<RecallAnswer>(`/v1/users/${u(userId)}/recall`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Deep recall over Server-Sent Events: `onStep` fires per agentic tool call as it lands
 * (growing the deep-search trace live), then `onDone` with the full answer. Step-level,
 * not token streaming. Returns when the stream ends; throws/`onError` on failure. */
export async function recallDeepStream(
  userId: string,
  query: string,
  handlers: {
    onStep: (step: TrailStep) => void;
    onDone: (answer: RecallAnswer) => void;
    onError: (message: string) => void;
  },
  signal?: AbortSignal,
  snapshot?: string | null,
  includeOriginalModalities: OriginalModality[] = [],
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/v1/users/${u(userId)}/recall/stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        query,
        mode: "deep",
        snapshot: snapshot ?? null,
        include_original_modalities: includeOriginalModalities,
      }),
      signal,
    });
  } catch (e) {
    handlers.onError((e as Error).message);
    return;
  }
  if (!res.ok || !res.body) {
    handlers.onError(`${res.status} ${res.statusText}`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      let payload: unknown;
      try {
        payload = JSON.parse(data);
      } catch {
        continue;
      }
      if (event === "step") handlers.onStep(payload as TrailStep);
      else if (event === "done") handlers.onDone(payload as RecallAnswer);
      else if (event === "error")
        handlers.onError((payload as { detail?: string }).detail ?? "stream error");
    }
  }
}

/* ------------------------------------------------------------- briefings (M4) */

export interface BriefingBuilt {
  briefing_id: string;
  snapshot_ref: string;
  claims_count: number;
  source_count: number;
  char_count: number;
}

export interface BriefingSummary {
  briefing_id: string;
  scope: { query?: string | null; source_ids?: string[]; budget_chars?: number };
  snapshot_ref: string;
  char_count: number;
  created_at: string | null;
}

export interface AskAnswer {
  answer: string;
  citations: { source_id: string; block_start: number; block_end: number }[];
  verbatim_fetches: Record<string, unknown>[];
  /** {handle: real_source_id} for the query-local `sNN` markers in `answer` — the UI
   * reverse-binds each inline `[cite: sNN]` to its real source. */
  citation_handles?: Record<string, string>;
  token_usage: TokenUsage;
}

export function buildBriefing(
  userId: string,
  body: {
    query?: string | null;
    source_ids?: string[];
    budget_chars?: number;
    snapshot?: string | null;
  },
): Promise<BriefingBuilt> {
  return req<BriefingBuilt>(`/v1/users/${u(userId)}/briefings`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listBriefings(userId: string): Promise<BriefingSummary[]> {
  return req<BriefingSummary[]>(`/v1/users/${u(userId)}/briefings`);
}

export function askBriefing(
  userId: string,
  briefingId: string,
  question: string,
): Promise<AskAnswer> {
  return req<AskAnswer>(
    `/v1/users/${u(userId)}/briefings/${u(briefingId)}/ask`,
    { method: "POST", body: JSON.stringify({ question }) },
  );
}

/* --------------------------------------------------------------- Live Context (Stage 3) */

/**
 * The suggestion focus registry. Closed vocabulary, defined once in core and served here —
 * the UI fetches it rather than inlining a copy (same discipline as
 * `getIntakeArchetypes`; architecture.md:123-124).
 */
export interface ContextFocusOption {
  key: string;
  label: string;
  summary: string;
}

/** The suggestion kind registry (`concept` / `fact`). Same single-source-of-truth rule. */
export interface SuggestionKindOption {
  key: string;
  label: string;
  summary: string;
}

export function getContextFocuses(): Promise<ContextFocusOption[]> {
  return req<ContextFocusOption[]>("/v1/live-context/focuses");
}

export function getSuggestionKinds(): Promise<SuggestionKindOption[]> {
  return req<SuggestionKindOption[]>("/v1/live-context/kinds");
}

export interface SuggestionCitation {
  source_id: string;
  block_start: number;
  block_end: number;
}

/**
 * One card as it leaves the server. `sNN` handles are already resolved away server-side
 * (they are query-local), so `body` is plain prose and provenance lives in `citations`.
 *
 * `confidence` (1-10) travels WITH the card on purpose: the sensitivity gate is a
 * software filter over an already-computed score, so a client can re-apply a different
 * threshold to cards it already holds without re-requesting anything.
 */
export interface ContextSuggestion {
  kind: string;
  title: string;
  body: string;
  /** the transcript fragment that set this card off — the "why did this fire" answer. */
  trigger: string;
  confidence: number;
  citations: SuggestionCitation[];
}

/** The four mechanical gates' kill counts for one evaluation (recall/suggestion.py). */
export interface SuggestionDropped {
  unparsed?: number;
  repeat?: number;
  uncited?: number;
  low_confidence?: number;
  capped?: number;
}

/** SSE terminal frame: what the evaluation produced and what each gate ate. */
export interface LiveContextDone {
  focus: string;
  count: number;
  dropped: SuggestionDropped;
  token_usage: TokenUsage;
  as_of: string;
}

export interface ContextTurnInput {
  speaker: string;
  text: string;
  role: "owner" | "other" | "unknown";
  speaker_id?: string | null;
  at?: string | null;
}

/** `{kind, title}` only — a body may still carry a dead alias epoch's handles. */
export interface SuggestionShown {
  kind: string;
  title: string;
}

export interface LiveContextStreamBody {
  turns: ContextTurnInput[];
  focus: string;
  min_confidence: number;
  max_suggestions: number;
  turn_window: number;
  /** set ⇒ briefing scope (evaluate against the frozen pack, zero retrieval). */
  briefing_id?: string | null;
  already_shown?: SuggestionShown[];
}

/**
 * Shape A — one-shot SSE over a posted transcript window. `onSuggestion` fires per surviving
 * card, then `onDone` carries the gate counters. No session, no dedup, no throttling.
 * Mirrors `recallDeepStream`'s frame parsing.
 */
export async function liveContextStream(
  userId: string,
  body: LiveContextStreamBody,
  handlers: {
    onSuggestion: (suggestion: ContextSuggestion) => void;
    onDone: (done: LiveContextDone) => void;
    onError: (message: string) => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/v1/users/${u(userId)}/live-context/stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    handlers.onError((e as Error).message);
    return;
  }
  if (!res.ok || !res.body) {
    handlers.onError(`${res.status} ${res.statusText}`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      let payload: unknown;
      try {
        payload = JSON.parse(data);
      } catch {
        continue;
      }
      if (event === "suggestion") handlers.onSuggestion(payload as ContextSuggestion);
      else if (event === "done") handlers.onDone(payload as LiveContextDone);
      else if (event === "error")
        handlers.onError((payload as { detail?: string }).detail ?? "stream error");
    }
  }
}

/* ------------------------------------------------------------ shape B: the socket */

/** Effective policy, echoed on accept and after every `config`. */
export interface LiveContextReadyFrame {
  type: "ready";
  focus: string;
  min_confidence: number;
  max_suggestions: number;
  turn_window: number;
  quiet_period: number;
  briefing_id: string | null;
  /** Whether `stats` frames are on for this connection — off unless asked for. */
  stats: boolean;
}

/**
 * Per-evaluation telemetry, the socket's answer to the SSE `done` frame.
 *
 * OFF unless the client sends `stats: true` in a `config`, and that default is the point:
 * a connection with no relevant context must stay actually silent, which is the property
 * the context clients rely on. When on it fires on EVERY evaluation including the ones that
 * delivered zero cards — the evaluation that emitted no `suggestion` frame at all is exactly the
 * one whose gate counters you need.
 */
export interface LiveContextStatsFrame {
  type: "stats";
  seq: number;
  focus: string;
  delivered: number;
  dropped: SuggestionDropped;
  token_usage: TokenUsage;
}

export interface SuggestionDetailFrame {
  type: "suggestion_detail";
  /** Echo of the `ref` the client sent on `want_more`; null when it sent none. */
  ref: string | null;
  title: string;
  detail: string;
  citations: SuggestionCitation[];
  token_usage: TokenUsage;
}

/** `ref` is present only when the failure belongs to a specific `want_more`; a bad frame
 * or a failed evaluation carries none, and must not be attributed to any request. */
export interface LiveContextErrorFrame {
  type: "error";
  detail: string;
  ref?: string | null;
}

export type LiveContextServerFrame =
  | LiveContextReadyFrame
  | LiveContextStatsFrame
  | { type: "suggestion"; seq: number; suggestion: ContextSuggestion }
  | SuggestionDetailFrame
  | LiveContextErrorFrame
  | { type: "ping" };

/** Every field optional; absent means unchanged. `briefing_id: ""` turns scope back off
 * (JSON null would mean "unchanged"), which is why this is `string`, not `string | null`. */
export interface LiveContextConfigMessage {
  focus?: string;
  min_confidence?: number;
  max_suggestions?: number;
  turn_window?: number;
  quiet_period?: number;
  briefing_id?: string;
  turns?: ContextTurnInput[];
  already_shown?: SuggestionShown[];
  /** Opt in to `stats` frames. Debug surfaces ask for them; passive clients need not. */
  stats?: boolean;
}

export type LiveContextSocketStatus = "connecting" | "open" | "closed";

/** ws(s):// URL for an API path, honoring VITE_API_BASE (empty → same origin). */
function wsUrl(path: string): string {
  const href = typeof window !== "undefined" ? window.location.href : "http://localhost/";
  const url = new URL(`${BASE}${path}`, href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

/**
 * Shape B — the long-lived listening connection. A thin typed wrapper: it owns no
 * policy of its own (the server session holds the window / quiet period / dedup) and
 * does not auto-reconnect. Reconnect is a deliberate client act, because the client is
 * the dedup authority and must replay `turns` + `already_shown` in its `config`.
 */
export class LiveContextSocket {
  private ws: WebSocket;

  constructor(
    userId: string,
    private readonly onFrame: (frame: LiveContextServerFrame) => void,
    private readonly onStatus: (status: LiveContextSocketStatus, detail?: string) => void,
  ) {
    this.onStatus("connecting");
    this.ws = new WebSocket(wsUrl(`/v1/users/${u(userId)}/live-context/ws`));
    this.ws.onopen = () => this.onStatus("open");
    this.ws.onclose = (e) =>
      this.onStatus(
        "closed",
        e.reason || (e.wasClean ? tx("service.ws.closed") : `code ${e.code}`),
      );
    // The browser never surfaces WHY a handshake failed (spec-mandated, to avoid a
    // cross-origin probe oracle); onclose carries whatever there is.
    this.ws.onerror = () => this.onStatus("closed", tx("service.ws.error"));
    this.ws.onmessage = (e) => {
      try {
        const frame = JSON.parse(e.data as string) as LiveContextServerFrame;
        this.onFrame(frame);
      } catch {
        this.onFrame({
          type: "error",
          detail: tx("service.ws.badFrame", { detail: String(e.data).slice(0, 120) }),
        });
      }
    };
  }

  get ready(): boolean {
    return this.ws.readyState === WebSocket.OPEN;
  }

  private send(msg: Record<string, unknown>): boolean {
    if (!this.ready) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  config(patch: LiveContextConfigMessage): boolean {
    return this.send({ type: "config", ...patch });
  }

  turn(turn: ContextTurnInput): boolean {
    return this.send({ type: "turn", ...turn });
  }

  /** Evaluate now, skipping the quiet period (not the single-in-flight rule). */
  flush(): boolean {
    return this.send({ type: "flush" });
  }

  /**
   * Hand a received card back for expansion; the reply is a `suggestion_detail` frame.
   *
   * `ref` is the caller's own correlation id, echoed on BOTH `suggestion_detail` and the `error`
   * for this request. Pass one: without it a failure names no request, and the caller is
   * left either guessing from `title` or resetting every pending expansion at once.
   */
  wantMore(suggestion: ContextSuggestion, ref?: string): boolean {
    return this.send({ type: "want_more", suggestion, ...(ref ? { ref } : {}) });
  }

  close(): void {
    this.ws.onclose = null;
    this.ws.onerror = null;
    this.ws.onmessage = null;
    try {
      this.ws.close();
    } catch {
      /* already closing */
    }
    this.onStatus("closed", tx("service.ws.disconnected"));
  }
}

/* ----------------------------------------------------------- document intake (M3b) */

/** @deprecated content-genre axis, kept for back-compat; the UI uses IntakeArchetype. */
export type DeclaredType = "contract" | "novel" | "note" | "other";

/**
 * A named processing intent = a preset of the two knobs. The registry lives in core
 * (single source of truth); the UI fetches it via GET /v1/intake/archetypes rather than
 * inlining a copy.
 */
export interface IntakeArchetype {
  key: string;
  label: string;
  summary: string;
  examples: string;
  canonical_treatment: string;
  semantic_indexing: string;
}

export function getIntakeArchetypes(): Promise<IntakeArchetype[]> {
  return req<IntakeArchetype[]>("/v1/intake/archetypes");
}

export interface SectionNode {
  path: string[];
  start_block: number;
  end_block: number;
  block_count: number;
}

export interface DocumentPreview {
  normalized: { section_tree: SectionNode[]; block_count: number; char_count: number };
  proposed_plan: IntakePlan;
  /** which archetype the proposed plan maps to (null = a custom knob-pair). */
  proposed_archetype?: string | null;
}

export interface DocumentBody {
  title: string;
  text: string;
  /** the user-facing axis: a named processing intent (archetype key); null/omitted = auto. */
  intake_archetype?: string | null;
  declared_type?: DeclaredType | null;
  source_class?: "workstream" | "reference" | null;
}

export function previewDocument(
  userId: string,
  body: DocumentBody,
): Promise<DocumentPreview> {
  return req<DocumentPreview>(`/v1/users/${u(userId)}/sources/document/preview`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function ingestDocument(
  userId: string,
  body: DocumentBody & {
    plan_override?: { canonical_treatment?: string; semantic_indexing?: string } | null;
  },
): Promise<IngestResult> {
  return req<IngestResult>(`/v1/users/${u(userId)}/sources/document`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/* ------------------------------------------------------------- compile queue (M3b) */

export interface JobSummary {
  job_id: string;
  kind: string;
  status: string;
  ok: boolean | null;
  detail: string | null;
  snapshot_ref: string | null;
  source_ids: string[];
  created_at: string | null;
  completed_at: string | null;
}

export interface CompileResult {
  enqueued: string[];
  source_ids: string[];
}

export interface JobPageParams {
  limit?: number;
  cursor?: string | null;
  status?: string | null;
  kind?: string | null;
}

export function listJobs(
  userId: string,
  params: JobPageParams = {},
): Promise<Page<JobSummary>> {
  const query = buildPageQuery({
    limit: params.limit ?? 25,
    cursor: params.cursor,
    status: params.status,
    kind: params.kind,
  });
  return req<Page<JobSummary>>(`/v1/users/${u(userId)}/jobs${query}`);
}

export interface HistoryPage extends Page<HistoryItemEnvelope> {
  counts: HistoryCounts;
}

export function listHistory(
  userId: string,
  params: {
    limit?: number;
    cursor?: string | null;
    kind?: "patch" | "job" | "snapshot" | null;
  } = {},
): Promise<HistoryPage> {
  const query = buildPageQuery({
    limit: params.limit ?? 25,
    cursor: params.cursor,
    kind: params.kind,
  });
  return req<HistoryPage>(`/v1/users/${u(userId)}/history${query}`);
}

export function getHistoryActivity(
  userId: string,
  kind?: "patch" | "job" | "snapshot",
): Promise<ActivityCalendar> {
  const kindQuery = kind ? `&kind=${encodeURIComponent(kind)}` : "";
  return req<ActivityCalendar>(
    `/v1/users/${u(userId)}/history/activity?offset_minutes=${browserCalendarOffset()}${kindQuery}`,
  );
}

export function compile(userId: string): Promise<CompileResult> {
  return req<CompileResult>(`/v1/users/${u(userId)}/compile`, { method: "POST" });
}

/* -------------------------------------------------- canonical read surface (M3b) */

export interface SnapshotSummary {
  ref: string;
  label: string | null;
}

export function listSnapshots(
  userId: string,
  params: { limit?: number; cursor?: string | null } = {},
): Promise<Page<SnapshotSummary>> {
  const query = buildPageQuery({
    limit: params.limit ?? 25,
    cursor: params.cursor,
  });
  return req<Page<SnapshotSummary>>(`/v1/users/${u(userId)}/snapshots${query}`);
}

/* ------------------------------------- knowledge-base snapshots (frozen tenants) */

/**
 * A frozen knowledge-base snapshot — the whole base (raw content, both retrieval indexes,
 * the claim projection) copied under a read-only tenant, plus the canonical commit it pins.
 *
 * Not the same object as `SnapshotSummary` above, which is one canonical git commit: that is
 * free and browse-only, this one can also be ASKED, because its retrieval layers exist.
 */
export interface KbSnapshot {
  snapshot_id: string;
  label: string;
  canonical_ref: string;
  status: "creating" | "ready" | "failed" | string;
  /** Post-copy scale {sources, blocks, claims, points}; empty while creating. */
  counts: Record<string, number>;
  created_at: string | null;
  ready_at: string | null;
  /** Why a failed snapshot failed; null otherwise. */
  detail: string | null;
}

export function listKbSnapshots(userId: string): Promise<KbSnapshot[]> {
  return req<KbSnapshot[]>(`/v1/users/${u(userId)}/kb-snapshots`);
}

/** Freeze the base as it stands now. Returns immediately in status "creating" (202). */
export function createKbSnapshot(userId: string, label: string): Promise<KbSnapshot> {
  return req<KbSnapshot>(`/v1/users/${u(userId)}/kb-snapshots`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export function deleteKbSnapshot(
  userId: string,
  snapshotId: string,
): Promise<{ deleted: boolean }> {
  return req<{ deleted: boolean }>(
    `/v1/users/${u(userId)}/kb-snapshots/${encodeURIComponent(snapshotId)}`,
    { method: "DELETE" },
  );
}

/**
 * Canonical dataset projection for Library / Graph. Audit data is owned by the
 * paged History endpoint and is intentionally not duplicated here.
 */
export function getDatasetRaw(
  userId: string,
  at?: string | null,
): Promise<Record<string, unknown>> {
  const query = new URLSearchParams({ audit: "false" });
  if (at) query.set("at", at);
  return req<Record<string, unknown>>(
    `/v1/users/${u(userId)}/dataset?${query.toString()}`,
  );
}

/* ------------------------------------------------ schema-evolve + skill (Stage C/D) */

/**
 * The service default draft review window (`evolve_draft_ttl_hours`, settings.py). A draft
 * older than this is lazily auto-dropped (→ status `expired`) on the next list/detail read.
 * The API does not echo the TTL, so the UI mirrors the default to render a remaining-TTL
 * countdown; it is advisory only (the server is the authority on actual expiry).
 */
export const EVOLVE_DRAFT_TTL_HOURS = 24;

/** One evolve task's terminal/interim state (evolve.py). */
export type EvolveStatus =
  | "draft"
  | "adopted"
  | "dropped"
  | "expired"
  | "aborted"
  | "no_change"
  | string;

/** The mechanical reorg tally that leads the review (evolve/runner.py). */
export interface EvolveSummary {
  new_documents: number;
  moved_claims: number;
  merged_claims: number;
  /** doc path → how many claims that document adopted. */
  adopted_by_document: Record<string, number>;
}

/** A base anchor that vanished from the new repo — a claim merged/deleted away (gate.py).
 * Carries its original text so the review can show what was dropped. */
export interface EvolveDroppedAnchor {
  anchor: string;
  old_path: string;
  text: string;
}

/** Per-file base(old) vs branch(new) body for the diff drill-down. Empty once the task
 * leaves `draft` (the branch is gone) — the detail degrades to summary-only. */
export interface EvolveChangedFile {
  path: string;
  old_body: string;
  new_body: string;
}

export interface EvolveTaskSummary {
  task_id: string;
  status: EvolveStatus;
  detail: string | null;
  summary: EvolveSummary | null;
  created_at: string | null;
  decided_at: string | null;
  /** Archive families this task proposed, derived server-side from the stored proposal.
   * Optional: an older service omits it, and the UI then reverse-derives from
   * `path_templates` (lib/evolve.ts `proposedFamilies`). */
  families?: string[];
  /** Path templates this task proposed (same server-side derivation). */
  path_templates?: string[];
}

export interface EvolveTaskDetail extends EvolveTaskSummary {
  dropped: EvolveDroppedAnchor[];
  proposal: Record<string, unknown> | null;
  rationale: string | null;
  base_ref: string | null;
  branch: string | null;
  changed_files: EvolveChangedFile[];
}

/** POST /evolve and /adopt both enqueue onto the per-user compile queue. */
export interface EvolveEnqueued {
  job_id: string;
  status: string;
}

/** One composed pack in the owner's effective skill (the tailored-skill surface). */
export interface SkillPack {
  pack_id: string | null;
  /** where the pack came from — `matrix` / `derived` / `evolved`. */
  origin: string | null;
  extra_path_templates: string[];
}

export interface SkillInfo {
  version: string;
  content_hash: string;
  base_version: string;
  path_templates: string[];
  packs: SkillPack[];
  /** The claim-prefix vocabulary this skill version declares (§5 strength tiers). Optional:
   * a v1-style skill declares none, and an older service omits the field entirely. */
  claim_labels?: ClaimLabel[];
}

/** All evolve tasks (newest first); the server runs its lazy stale-draft expiry sweep first. */
export function listEvolveTasks(userId: string): Promise<EvolveTaskSummary[]> {
  return req<EvolveTaskSummary[]>(`/v1/users/${u(userId)}/evolve`);
}

export function getEvolveTask(userId: string, taskId: string): Promise<EvolveTaskDetail> {
  return req<EvolveTaskDetail>(`/v1/users/${u(userId)}/evolve/${u(taskId)}`);
}

/** Manually fire a schema-evolve run. Throws ApiError(409) when a draft is already awaiting
 * review or an evolve job is already queued/in-flight (single-flight per user). */
export function triggerEvolve(userId: string): Promise<EvolveEnqueued> {
  return req<EvolveEnqueued>(`/v1/users/${u(userId)}/evolve`, { method: "POST" });
}

/** Accept a draft: enqueue the adopt job (mechanical merge → commit on main → rebuild L3).
 * Throws ApiError(409) when the task is not a live draft. */
export function adoptEvolveTask(userId: string, taskId: string): Promise<EvolveEnqueued> {
  return req<EvolveEnqueued>(`/v1/users/${u(userId)}/evolve/${u(taskId)}/adopt`, {
    method: "POST",
  });
}

/** Discard a draft: delete its branch, record it dropped (immediate, not queued). */
export function dropEvolveTask(userId: string, taskId: string): Promise<{ dropped: boolean }> {
  return req<{ dropped: boolean }>(`/v1/users/${u(userId)}/evolve/${u(taskId)}/drop`, {
    method: "POST",
  });
}

/** The owner's CURRENT effective composed skill — base version + pack list + path templates. */
export function getSkillInfo(userId: string): Promise<SkillInfo> {
  return req<SkillInfo>(`/v1/users/${u(userId)}/skill`);
}
