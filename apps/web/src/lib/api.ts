/**
 * pneuma-knowledge service API client (M2). A thin fetch wrapper — no request library, no
 * global cache; panels own their own loading state. Every path is scoped by
 * user_id after `/v1/users/` (invariant I1). The base URL comes from
 * `VITE_API_BASE` (empty → same-origin relative `/v1/...`, proxied to the service
 * by the vite dev server; see vite.config.ts).
 */

import { tx } from "./i18n";
import type { ClaimLabel, UserProfile, VisitorClass } from "./types";
import type { HistoryCounts, HistoryItemEnvelope } from "./history";
import type { StageEvent, StageTiming } from "./stages";
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

/** rag recall — the fused hit list, and the per-stage wall-clock of finding it. */
export interface RagResult {
  mode: "rag";
  hits: RecallHit[];
  /** `embed` → `retrieve` (`lexical`, `vector`) → `fuse` → `expand`, plus `total`. */
  stages: StageTiming[];
}

export function recall(
  userId: string,
  body: { query: string; mode?: string; limit?: number; snapshot?: string | null },
): Promise<RagResult> {
  return req<RagResult>(`/v1/users/${u(userId)}/recall`, {
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

/** What those tokens cost, derived at read time from the rates this deployment declared
 *  (`model_pricing`). `null` — or absent — wherever it declared none for the models a call
 *  used, or where one lane's roles are priced differently: the tokens are shown either way,
 *  and no figure is invented to sit beside them. */
export interface Cost {
  amount: number;
  currency: string;
}

export interface UsedClaim {
  anchor: string;
  document_path: string;
  section_path: string[];
  text: string;
  citations: { source_id: string; block_start: number; block_end: number }[];
  paths: string[];
  score: number;
  /**
   * Mechanical labels, never prose: the ones a component path attached to its own item
   * (`current`, `superseded`), plus `via:<path>` on a ranked claim that a lookup also
   * returned. Absent altogether from a server that predates the seam.
   */
  labels?: string[];
}

/**
 * fast only: one routed component lookup (core `recall/paths.py`). A component path answers a
 * STRUCTURED query — `person({"alias": "…"})` — with exact hits, so it stays its own evidence
 * face instead of being fused into the ranked pool. `degraded` names why a chosen path
 * contributed nothing.
 *
 * The path returns everything it knows and the framework decides what is shown: `dropped`
 * counts what the cap and the character budget left out and `dropped_summary` describes it
 * per section (claims) or per day/source (windows), while `already_shown` counts the hits
 * the ranked faces above already carry — hidden here rather than repeated, which is why a
 * ranked claim may carry a `via:<path>` label.
 */
export interface ComponentEvidence {
  path: string;
  args: Record<string, unknown>;
  claims: UsedClaim[];
  windows: RecallHit[];
  degraded?: string | null;
  dropped?: number;
  dropped_summary?: [string, number][];
  already_shown?: number;
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
  /** This call's measured wall-clock in ms, stamped by the service before the step was
   * streamed — so a live-growing trail shows a real duration, not one timed from arrival
   * gaps. The same number the closing `stages` list reports for `tool:<tool>`. */
  ms?: number;
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
  /** fast only: the routed component lookups and what each returned. */
  used_component_evidence?: ComponentEvidence[];
  /** Per-stage wall-clock, in the lane's own vocabulary (see `lib/stages.ts`). fast sends
   * the whole fixed list in order — a stage that did not run is present with
   * `status: "skipped"` and `ms: 0`; deep sends the agentic run's own sequence
   * (`turn:N`, `tool:<name>`, `finalize`), never skipped, `total` last. Optional: an answer
   * restored from the session cache has none. */
  stages?: StageTiming[];
  /** fast only: which paths the routing turn was offered, and which it chose (`name({…})`). */
  route_offered?: string[];
  route_chosen?: string[];
  /** "timeout" | "error" when the routing call itself failed; choosing nothing is not that. */
  route_degraded?: string | null;
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
  evidence_strategy?: "ranked" | "select" | "all";
  /** "timeout" / "error" from the selector, or "all:truncated" when the whole-pool
   *  strategy hit its context ceiling. Free-form on purpose: a reason is shown, not
   *  branched on. */
  evidence_selection_degraded?: string | null;
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
  /** The answering call's own evidence review, when the schema asked for one (the `all`
   *  strategy). Model output about the evidence — never evidence, never a citation. */
  deliberation?: string | null;
  token_usage: TokenUsage;
  cost?: Cost | null;
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
    evidence_strategy?: "ranked" | "select" | "all";
    answer_format?: "text" | "structured";
    include_original_modalities?: OriginalModality[];
    /** Who is asking, as far as the record is concerned. Omitted = the service's own
     *  default, `silent`, which leaves no trace at all. */
    visitor_class?: VisitorClass;
  },
): Promise<RecallAnswer> {
  return req<RecallAnswer>(`/v1/users/${u(userId)}/recall`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * One SSE reader for every stream this client speaks.
 *
 * Written once because the parsing is the same everywhere and only the vocabulary differs:
 * frames separated by a blank line, an `event:` name, one or more `data:` lines to join. The
 * caller supplies a handler per event kind; an event nobody handles is skipped rather than
 * treated as an error, so a service that grows a frame kind does not break an older viewer.
 *
 * Resolves when the stream closes. Transport failures and non-2xx statuses are reported
 * through `onError` rather than thrown, so a caller has exactly one failure path.
 */
async function readEventStream(
  path: string,
  body: unknown,
  handlers: Record<string, (payload: unknown) => void>,
  onError: (message: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    onError((e as Error).message);
    return;
  }
  if (!res.ok || !res.body) {
    // A stream route refuses BEFORE it opens (an unknown briefing, a keyless deployment),
    // so the JSON detail is the real reason and worth more than the status line.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const parsed = (await res.json()) as { detail?: unknown };
      if (parsed?.detail != null) detail = String(parsed.detail);
    } catch {
      /* non-JSON error body — keep the status line */
    }
    onError(detail);
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
      if (event === "error") {
        onError((payload as { detail?: string }).detail ?? "stream error");
        continue;
      }
      handlers[event]?.(payload);
    }
  }
}

/** What every answering stream reports while it runs, beside its own extras. */
export interface LiveHandlers {
  /** A stage beginning or settling — fold these with `liveStages` (lib/stages.ts). */
  onStage?: (event: StageEvent) => void;
  /** A delta of the answer text as the model writes it; append them in arrival order. */
  onToken?: (text: string) => void;
  onError: (message: string) => void;
}

function liveFrames(handlers: LiveHandlers): Record<string, (p: unknown) => void> {
  return {
    stage: (p) => handlers.onStage?.(p as StageEvent),
    token: (p) => handlers.onToken?.((p as { text: string }).text),
  };
}

/**
 * fast or deep recall over Server-Sent Events — the same answer the plain POST returns, and
 * the stages, tokens and (deep) tool calls as they happen.
 *
 * Step-level and token-level, never a partial answer object: `onDone` carries the whole
 * `RecallAnswer`, which is what every panel below the strip renders from.
 */
export async function recallStream(
  userId: string,
  query: string,
  mode: "fast" | "deep",
  handlers: LiveHandlers & {
    /** deep only: one agentic tool call as it lands, its own `ms` already stamped. */
    onStep?: (step: TrailStep) => void;
    onDone: (answer: RecallAnswer) => void;
  },
  signal?: AbortSignal,
  snapshot?: string | null,
  includeOriginalModalities: OriginalModality[] = [],
  visitorClass: VisitorClass = "silent",
): Promise<void> {
  await readEventStream(
    `/v1/users/${u(userId)}/recall/stream`,
    {
      query,
      mode,
      snapshot: snapshot ?? null,
      include_original_modalities: includeOriginalModalities,
      visitor_class: visitorClass,
    },
    {
      ...liveFrames(handlers),
      step: (p) => handlers.onStep?.(p as TrailStep),
      done: (p) => handlers.onDone(p as RecallAnswer),
    },
    handlers.onError,
    signal,
  );
}

/**
 * rag recall over Server-Sent Events — the same hit list the plain POST returns, and the
 * stages as they happen.
 *
 * Deliberately its own function rather than a third `mode` on `recallStream`: the `done`
 * payload is a different shape (hits, not an answer) and the lane has no model, so there are
 * no `token` frames and no `onToken` to offer. Widening the other client would have meant a
 * union every caller had to narrow.
 */
export async function ragStream(
  userId: string,
  query: string,
  handlers: {
    onStage?: (event: StageEvent) => void;
    onDone: (result: RagResult) => void;
    onError: (message: string) => void;
  },
  signal?: AbortSignal,
  snapshot?: string | null,
  limit = 10,
): Promise<void> {
  await readEventStream(
    `/v1/users/${u(userId)}/recall/stream`,
    { query, mode: "rag", limit, snapshot: snapshot ?? null },
    {
      stage: (p) => handlers.onStage?.(p as StageEvent),
      done: (p) => handlers.onDone(p as RagResult),
    },
    handlers.onError,
    signal,
  );
}

/* ------------------------------------------------------------- briefings (M4) */

export interface BriefingBuilt {
  briefing_id: string;
  snapshot_ref: string;
  claims_count: number;
  source_count: number;
  char_count: number;
  /** The BUILD's per-stage wall-clock: `retrieve` (with its `claims` / `passages` lookups),
   * `expand`, `pack`, `total` — a fixed vocabulary, so a half that did not run is present and
   * marked `skipped`. Absent on a briefing picked from history (see `BriefingDetail`). */
  stages?: StageTiming[];
}

export interface BriefingSummary {
  briefing_id: string;
  scope: { query?: string | null; source_ids?: string[]; budget_chars?: number };
  snapshot_ref: string;
  char_count: number;
  created_at: string | null;
}

/** One stored briefing read back whole — `text` is the literal system pack, not markdown. */
export interface BriefingDetail {
  briefing_id: string;
  snapshot_ref: string;
  created_at: string | null;
  char_count: number;
  scope: { query?: string | null; source_ids?: string[]; budget_chars?: number };
  text: string;
  /** The build's breakdown as it was measured, persisted with the row. Empty for a briefing
   * built before the service measured builds — "not recorded", not "took no time". */
  stages?: StageTiming[];
}

export interface AskAnswer {
  answer: string;
  citations: { source_id: string; block_start: number; block_end: number }[];
  verbatim_fetches: Record<string, unknown>[];
  /** {handle: real_source_id} for the query-local `sNN` markers in `answer` — the UI
   * reverse-binds each inline `[cite: sNN]` to its real source. */
  citation_handles?: Record<string, string>;
  token_usage: TokenUsage;
  cost?: Cost | null;
  /** The ask LOOP's per-step wall-clock, agentic-shaped like deep's: `turn:N`, `tool:<name>`
   * (the same call the matching `verbatim_fetches` record carries `ms` for), an optional
   * `finalize`, then `total`. The pack is not inside that total — it was built earlier. */
  stages?: StageTiming[];
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

/**
 * The same build, narrated. A build runs no model at all — it is retrieval, provenance
 * expansion and assembly — which is exactly why watching it matters: when a build takes nine
 * seconds the whole question is which of those three it spent them in.
 */
export async function buildBriefingStream(
  userId: string,
  body: {
    query?: string | null;
    source_ids?: string[];
    budget_chars?: number;
    snapshot?: string | null;
  },
  handlers: LiveHandlers & { onDone: (built: BriefingBuilt) => void },
  signal?: AbortSignal,
): Promise<void> {
  await readEventStream(
    `/v1/users/${u(userId)}/briefings/stream`,
    body,
    {
      ...liveFrames(handlers),
      done: (p) => handlers.onDone(p as BriefingBuilt),
    },
    handlers.onError,
    signal,
  );
}

export function listBriefings(userId: string): Promise<BriefingSummary[]> {
  return req<BriefingSummary[]>(`/v1/users/${u(userId)}/briefings`);
}

/** Read one briefing back, text included — the pack the answers are actually grounded in. */
export function getBriefing(userId: string, briefingId: string): Promise<BriefingDetail> {
  return req<BriefingDetail>(`/v1/users/${u(userId)}/briefings/${u(briefingId)}`);
}

export function askBriefing(
  userId: string,
  briefingId: string,
  question: string,
  visitorClass: VisitorClass = "silent",
): Promise<AskAnswer> {
  return req<AskAnswer>(
    `/v1/users/${u(userId)}/briefings/${u(briefingId)}/ask`,
    {
      method: "POST",
      body: JSON.stringify({ question, visitor_class: visitorClass }),
    },
  );
}

/** One question over a stored briefing, narrated: turns, the tools they reach for, and the
 * answer as it is written. `onDone` carries the same `AskAnswer` the plain POST returns. */
export async function askBriefingStream(
  userId: string,
  briefingId: string,
  question: string,
  handlers: LiveHandlers & { onDone: (answer: AskAnswer) => void },
  signal?: AbortSignal,
  visitorClass: VisitorClass = "silent",
): Promise<void> {
  await readEventStream(
    `/v1/users/${u(userId)}/briefings/${u(briefingId)}/ask/stream`,
    { question, visitor_class: visitorClass },
    {
      ...liveFrames(handlers),
      done: (p) => handlers.onDone(p as AskAnswer),
    },
    handlers.onError,
    signal,
  );
}

/* ------------------------------------------------- consultations + the access ledger */

/** One address, and nothing else — no text, no score, no rank (invariant I4).
 *
 * `ref` is a claim anchor (`c:xxxx`), a `<source_id> ¶a-b` span, or a canonical page path;
 * `path` is the page a claim lives on, and is empty for every other kind. */
export interface EvidenceRef {
  kind: string;
  ref: string;
  path: string;
}

/** One consultation as a listing row. The evidence stays on the detail route. */
export interface ConsultationSummary {
  consultation_id: string;
  created_at: string;
  lane: "fast" | "deep" | "briefing_ask" | string;
  visitor_class: "audit" | "business" | string;
  question: string;
  /** The library answered with nothing — `no_record`, or (for a retrieving lane) nothing
   *  reaching the model at all. */
  miss: boolean;
  answer_kind: string | null;
  /** The canonical HEAD sampled when the consultation began — the snapshot id for a pinned
   *  call, which is the same field in its other exact form. */
  library_ref: string;
  citation_count: number;
  evidence_count: number;
  /** What the consultation spent. `{}` for a record written before it was kept. */
  token_usage: Partial<TokenUsage>;
  cost: Cost | null;
}

/** The whole record: the audit chain for one answer. `citations` is a subset of
 *  `evidence_handed` by construction — a marker is admitted only when its resolved address
 *  is in the manifest the lane published. */
export interface Consultation extends ConsultationSummary {
  as_of: string | null;
  answer: string;
  evidence_handed: EvidenceRef[];
  citations: EvidenceRef[];
  degraded: string[][];
}

export interface ConsultationParams {
  limit?: number;
  cursor?: string | null;
  lane?: string | null;
  visitor_class?: string | null;
  miss?: boolean | null;
  /** The reverse lookup: which consultations handed or cited ONE address. Takes a claim
   *  anchor, a `<source_id> ¶a-b` span, or a canonical page path — a page matches both
   *  when it was read whole and when a claim living on it travelled. */
  target?: string | null;
}

export function listConsultations(
  userId: string,
  params: ConsultationParams = {},
): Promise<Page<ConsultationSummary>> {
  const query = buildPageQuery({
    limit: params.limit ?? 25,
    cursor: params.cursor,
    lane: params.lane,
    visitor_class: params.visitor_class,
    miss: params.miss == null ? null : String(params.miss),
    target: params.target,
  });
  return req<Page<ConsultationSummary>>(
    `/v1/users/${u(userId)}/consultations${query}`,
  );
}

export function getConsultation(
  userId: string,
  consultationId: string,
): Promise<Consultation> {
  return req<Consultation>(
    `/v1/users/${u(userId)}/consultations/${u(consultationId)}`,
  );
}

/** One slice of a spend window: a lane name or a visitor class, what it spent, what it
 *  cost. `cost` is null when the slice's models are not all priced, or it mixes currencies. */
export interface SpendGroup {
  key: string;
  consultations: number;
  /** How many of them reported any token counter at all. */
  with_usage: number;
  /** `with_usage < consultations` — some calls reported nothing, so the tokens are a floor
   *  rather than the total, and the money withdraws instead of showing a partial as exact. */
  incomplete: boolean;
  token_usage: Partial<TokenUsage>;
  cost: Cost | null;
}

/** What this library's RECORDED consultations spent over a window — not the deployment's
 *  bill: a `silent` visitor leaves no record, and the Live Context lane records none. */
export interface Spend {
  window_days: number;
  since: string;
  until: string;
  consultations: number;
  with_usage: number;
  incomplete: boolean;
  token_usage: Partial<TokenUsage>;
  cost: Cost | null;
  by_lane: SpendGroup[];
  by_visitor_class: SpendGroup[];
}

export function getConsultationSpend(userId: string, days = 30): Promise<Spend> {
  return req<Spend>(
    `/v1/users/${u(userId)}/consultations/spend?days=${encodeURIComponent(days)}`,
  );
}

/** What this library's readers have done with one target, joined at read time out of the
 *  derived layer. Never canonical — nothing here is written into a page. A target nobody
 *  has read answers with zeros and `last_accessed_at: null`: "never read" is an answer. */
export interface AccessStats {
  kind: string;
  ref: string;
  last_accessed_at: string | null;
  hits_7d: number;
  hits_30d: number;
  heat: number;
}

export function getAccessStats(
  userId: string,
  kind: "claim" | "document" | "source",
  ref: string,
): Promise<AccessStats> {
  const query = buildPageQuery({ kind, ref });
  return req<AccessStats>(`/v1/users/${u(userId)}/access-stats${query}`);
}

export interface TopDocument {
  path: string;
  heat: number;
  hits_7d: number;
  hits_30d: number;
  last_accessed_at: string | null;
}

export interface TopMiss {
  question: string;
  count: number;
  last_day: string;
}

/** The ledger's face for a dashboard. `heat` ranks over `window_days`; the two hit counts
 *  are the read face's own fixed windows, so a page reads the same here as on its card. */
export interface AccessTop {
  window_days: number;
  since: string;
  until: string;
  half_life_days: number;
  documents: TopDocument[];
  misses: TopMiss[];
}

export function getAccessTop(
  userId: string,
  params: { days?: number; limit?: number } = {},
): Promise<AccessTop> {
  const query = buildPageQuery({ days: params.days, limit: params.limit });
  return req<AccessTop>(`/v1/users/${u(userId)}/access-stats/top${query}`);
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
  /**
   * The LEDE: one or two sentences guessing what this reader needs right now. A model wrote
   * this and nothing else on the card.
   */
  body: string;
  /**
   * The verbatim material the card rests on — claim text and excerpts, rendered mechanically
   * from what was retrieved. No model touched it, which is exactly why it is a separate
   * field: the bubble shows it collapsed under the lede rather than blended into it.
   * Empty on the briefing path, which has no candidate behind it.
   */
  evidence?: string;
  /** The canonical document / source this card is ABOUT, for the session's own ledger. */
  subject?: string;
  /** A short human name for that subject — what the ledger digest calls it. */
  subject_label?: string;
  /** the transcript fragment that set this card off — the "why did this fire" answer. */
  trigger: string;
  confidence: number;
  /**
   * True only on a `kind: "glance"` card that has not settled yet — the subject's own
   * one-sentence definition, verbatim and cited, shown while the tick behind it is still
   * running. The `upgrade` frame on the same `seq` clears it, either by replacing the card
   * in place or by settling it where it stands.
   */
  provisional?: boolean;
  citations: SuggestionCitation[];
  /**
   * The SECOND citation shape, carried by `kind: "web"` cards and empty on every other one.
   * A web card rests on pages rather than on source blocks, so it points at URLs — there is
   * no span to open in-app and nothing to fetch verbatim. Which list a card carries is
   * stated by `kind`; a card never carries both, and the collapsed evidence section renders
   * whichever it has the same way.
   */
  web_citations?: WebCitation[];
}

/** One page a `web` card rests on. The URL is the address; the title is what a person reads. */
export interface WebCitation {
  title: string;
  url: string;
}

/** One stage of one evaluation, as the lane measured itself (recall/stage_timing.py). */
export interface LiveContextStage {
  name: string;
  ms: number;
  status: "ran" | "skipped" | "degraded";
  detail?: string | null;
}

/** One mechanically assembled candidate the pick stage was offered. */
export interface LiveContextCandidate {
  index: number;
  kind: string;
  title: string;
  subject: string;
  origin: string;
  /** Which POOL it came out of — `library` or `web`. The pick contract ranks by match and
   * never by this, which is a rule about something only because the card states it. */
  provenance?: string;
  citations: number;
}

/** What the supplementary internet face did this tick, and what it cost.
 *
 * `tier` separates the two ways it can be reached: `planned` (discover asked for it, so it
 * ran concurrently with the library faces) from `fallback` (discover did not ask, the
 * library came back with an empty pool, so it ran after). `off` is the steady state. */
export interface LiveContextWeb {
  tier: "off" | "planned" | "fallback";
  searches: number;
  cost: number;
  /** Pages the searches named. Zero beside a non-zero cost means the answer cited nothing
   * and was refused at construction — the one outcome that is otherwise invisible. */
  pages?: number;
}

/**
 * What one tick DID — the answer to "why did nothing fire", which is the question this
 * feature gets asked most, because silence is its steady state.
 *
 * `skipped` is `""` on a delivery and otherwise names which door closed: a discover reason
 * (`small_talk` / `already_mined` / `nothing_new`), or one of the mechanical ones —
 * `low_worth`, `no_plan`, `no_candidates`, `no_coverage`, `none_chosen`, `low_confidence`,
 * `uncited`, `duplicate`,
 * `unparsed`, `pick_failed`.
 */
export interface LiveContextProcessing {
  skipped: string;
  dropped: SuggestionDropped;
  intent: string;
  worth: number;
  plan: string[];
  rejected: string[];
  candidates: LiveContextCandidate[];
  chosen: number;
  web?: LiveContextWeb;
  stages: LiveContextStage[];
}

/** The four mechanical gates' kill counts for one evaluation (recall/suggestion.py). */
export interface SuggestionDropped {
  unparsed?: number;
  repeat?: number;
  uncited?: number;
  low_confidence?: number;
  capped?: number;
}

/** SSE terminal frame: what the evaluation produced, and what it did to get there. */
export interface LiveContextDone extends LiveContextProcessing {
  focus: string;
  count: number;
  token_usage: TokenUsage;
  cost?: Cost | null;
  as_of: string;
}

export interface ContextTurnInput {
  speaker: string;
  text: string;
  role: "owner" | "other" | "unknown";
  speaker_id?: string | null;
  at?: string | null;
}

/**
 * What the client replays so the server can pick up where it left off.
 *
 * `(kind, title)` is still the only dedup KEY. `body` rides along because the discover stage
 * answers "已挖掘过" against it and a bare title cannot tell it whether the thing the room is
 * circling has already been said; `subject` restores the session's ledger so a reconnect does
 * not re-introduce a subject this reader has already met. The server strips any `[cite: sNN]`
 * residue from the body — a handle from a dead alias epoch names a different source.
 */
export interface SuggestionShown {
  kind: string;
  title: string;
  body?: string;
  subject?: string;
  subject_label?: string;
}

export interface LiveContextStreamBody {
  turns: ContextTurnInput[];
  focus: string;
  /**
   * How eagerly the lane digs: `eager` | `balanced` | `quiet`. Absent or unknown ⇒
   * `balanced` server-side — a density arrives from a preset pill, from an older client
   * that has none, and from a custom setting carrying only numbers, and none of those is a
   * reason to fail the request.
   *
   * It is sent BESIDE the numbers, not instead of them: the numbers say how much gets
   * through, the density says what is looked for at all, and the two are different
   * questions. See `liveContextDensity.ts`.
   */
  density?: string;
  min_confidence: number;
  max_pending_turns: number;
  /** Ask for the supplementary internet search on this one-shot evaluation. */
  web_search?: boolean;
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
  /** The EFFECTIVE posture — already coerced, so this is the truth, not the request. */
  density: string;
  min_confidence: number;
  /** The ceiling on one tick's pending run — not a sliding tail. */
  max_pending_turns: number;
  quiet_period: number;
  /**
   * Whether this connection may use the supplementary internet search — the EFFECTIVE
   * value, not what was asked for. A client can request it; the deployment grants it. Read
   * `false` back after asking for `true` and you have been told no, mechanically.
   */
  web_search: boolean;
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
export interface LiveContextStatsFrame extends LiveContextProcessing {
  type: "stats";
  seq: number;
  focus: string;
  delivered: number;
  /** How many pending turns this tick read. */
  turns?: number;
  token_usage: TokenUsage;
  cost?: Cost | null;
}

export interface SuggestionDetailFrame {
  type: "suggestion_detail";
  /** Echo of the `ref` the client sent on `want_more`; null when it sent none. */
  ref: string | null;
  title: string;
  detail: string;
  citations: SuggestionCitation[];
  token_usage: TokenUsage;
  cost?: Cost | null;
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
  | {
      type: "suggestion";
      seq: number;
      suggestion: ContextSuggestion;
      /** Set on the glance short-circuit's early card; see `ContextSuggestion.provisional`. */
      provisional?: boolean;
    }
  /**
   * One provisional card's ending, on the seq that delivered it. `suggestion` present ⇒ the
   * full card is about the SAME subject and takes the provisional one's place, in that slot,
   * so the queue does not grow; `null` ⇒ settle where it stands — the same card, no longer
   * provisional, with anything else the tick produced arriving as ordinary `suggestion`
   * frames beside it.
   */
  | { type: "upgrade"; seq: number; suggestion: ContextSuggestion | null }
  | SuggestionDetailFrame
  | LiveContextErrorFrame
  | { type: "ping" };

/** Every field optional; absent means unchanged. `briefing_id: ""` turns scope back off
 * (JSON null would mean "unchanged"), which is why this is `string`, not `string | null`. */
export interface LiveContextConfigMessage {
  focus?: string;
  /** `eager` | `balanced` | `quiet`. Unknown values are coerced, never rejected. */
  density?: string;
  min_confidence?: number;
  max_pending_turns?: number;
  quiet_period?: number;
  /** Ask for the supplementary internet search. Granted only where the deployment enabled
   * one — read the `ready` frame's `web_search` for the answer. */
  web_search?: boolean;
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
   * The conversation was cleared: the server session drops everything it learned from it.
   *
   * The client is the dedup authority, so clearing only the client's stores left the SERVER
   * holding the ledger, the context tail and the mined list of a conversation nobody can see
   * any more — and the next mention of a subject from before the clear came back skipped as
   * `already_mined`. The server answers with a fresh `ready`.
   */
  reset(): boolean {
    return this.send({ type: "reset" });
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
  /** What this job's model calls spent — the compile loop's own sum. `{}` when the job ran
   *  no model, or predates the column. */
  token_usage: Partial<TokenUsage>;
  cost: Cost | null;
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
