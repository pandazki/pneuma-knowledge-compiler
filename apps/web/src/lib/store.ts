import { create } from "zustand";
import type { Dataset, Selection, UserProfile, ViewName } from "./types";
import type { MessageKey, MessageParams } from "./i18n";
import { LOCALE_STORAGE_KEY, detectLocale, setActiveLocale, type Locale } from "./i18n";
import { buildModel, type Model } from "./model";
import { hashToState, sameSelection, selectionToHash } from "./hash";
import { needsCanonicalDataset } from "./datasetLoading";
import { appendUniqueSnapshots } from "./snapshotPagination";
import { briefingSelection } from "./ask";
import type { StageTiming } from "./stages";
import type { ChatMode, LiveRole, LiveTurn } from "./liveContextChat";
import {
  listUsers,
  getDatasetRaw,
  getUserProfile,
  listSnapshots,
  listKbSnapshots,
  createKbSnapshot,
  deleteKbSnapshot,
  type KbSnapshot,
  type SnapshotSummary,
  type RagResult,
  type RecallAnswer,
  type BriefingBuilt,
  type TokenUsage,
} from "./api";

type Theme = "light" | "dark";

const USER_KEY = "pneuma_knowledge-user";
const RECENT_KEY = "pneuma_knowledge-recent-users";
/** Cap on the persisted recent-users MRU list. The top-bar panel shows at most 3. */
const RECENT_MAX = 8;

/** Read the persisted recent-users MRU list (newest first), tolerating bad JSON. */
function loadRecent(): string[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const arr = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** Unshift `uid` into the MRU list (deduped, newest first, capped), and persist. */
function pushRecent(list: string[], uid: string): string[] {
  const next = [uid, ...list.filter((u) => u !== uid)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
  return next;
}

/** Where a Recall hit (or any cross-panel jump) wants the Sources panel to land. */
export interface SourceFocus {
  sourceId: string;
  blockStart: number | null;
  blockEnd: number | null;
}

export type RecallMode = "rag" | "fast" | "deep";
export type AskMode = "briefing" | "fast" | "deep";

/**
 * Recall view's inputs + last result, lifted into the store so a view-switch (→ Sources
 * on a citation click) and Back does not evaporate the answer. In-memory only, per active
 * user — cleared on `setUser` so one user's recall never bleeds into another's.
 */
export interface RecallCache {
  query: string;
  mode: RecallMode;
  /** rag's whole result — the hits AND what finding them cost, kept together so a Back
   *  redraws the same diagram the live run drew rather than a bare ledger. */
  rag: RagResult | null;
  answer: RecallAnswer | null;
  error: string | null;
}

export interface AskCitation {
  source_id: string;
  block_start: number;
  block_end: number;
}

/** One answered turn in the Ask conversation (with its handle map for inline cites). */
export interface AskTurn {
  question: string;
  mode: AskMode;
  answer: string;
  citations: AskCitation[];
  handles: Record<string, string>;
  usage: TokenUsage;
  /** The L0 pulls this turn made, held ON the turn. Parked in component state keyed by turn
   * index, they outlived the thread they belonged to and resurfaced under the next briefing. */
  verbatim?: Record<string, unknown>[];
  /** This turn's own per-step wall-clock (`turn:N` / `tool:X` / `total`), held on the turn
   * for the same reason: it belongs to the answer above it, not to the thread. */
  stages?: StageTiming[];
}

/** Ask view's build inputs + conversation, lifted for the same Back-preserves-state reason. */
export interface AskCache {
  scopeQuery: string;
  selected: string[];
  briefing: BriefingBuilt | null;
  askMode: AskMode;
  question: string;
  turns: AskTurn[];
}

/**
 * The Live Context conversation, lifted for the same Back-preserves-state reason as the two
 * caches above — and one of its own. The page holds a conversation the operator TYPED: roles
 * they named, turns they wrote, some already pushed on a socket. Losing that to a glance at
 * the Library and back would be losing work, not losing a view.
 *
 * `roles` starts EMPTY rather than pre-seeded. The default pill names are interface copy, and
 * the store has no translator; the view seeds them once on first mount, after which they are
 * the operator's data and a language switch must not rewrite what they renamed. Same rule the
 * old panel's draft speaker followed.
 */
export interface LiveContextCache {
  roles: LiveRole[];
  activeRoleId: string;
  turns: LiveTurn[];
  /** Which delivery the conversation is on. Held here so a return to the page resumes it. */
  mode: ChatMode;
}

const EMPTY_LIVE_CONTEXT_CACHE: LiveContextCache = {
  roles: [],
  activeRoleId: "",
  turns: [],
  mode: "oneshot",
};

const EMPTY_RECALL_CACHE: RecallCache = {
  query: "",
  mode: "rag",
  rag: null,
  answer: null,
  error: null,
};

const EMPTY_ASK_CACHE: AskCache = {
  scopeQuery: "",
  selected: [],
  briefing: null,
  askMode: "briefing",
  question: "",
  turns: [],
};

/**
 * A dismissible notice, held as a message KEY (plus params) rather than a rendered string,
 * so a language switch re-renders the banner in the new language instead of stranding the
 * sentence it was minted in.
 */
export interface Notice {
  key: MessageKey;
  params?: MessageParams;
}

interface AppState {
  status: "idle" | "loading" | "ready" | "error";
  error: string | null;
  /** non-blocking, dismissible notice (e.g. invalid ?ds= fell back) — distinct from `error`. */
  notice: Notice | null;
  dataset: Dataset | null;
  model: Model | null;

  /** pneuma-knowledge service state (M2). Users own all data (invariant I1). */
  users: string[];
  currentUser: string | null;
  /** product profile of the active user (GET /profile); null while loading / unavailable. */
  currentProfile: UserProfile | null;
  /** User id currently in the explicit create-profile onboarding flow. */
  profileOnboardingUser: string | null;
  /**
   * Best-effort uid → display_name cache for the switcher (so options can show
   * names, not raw ids). Populated lazily/in-parallel; a missing entry falls back
   * to the raw id. Never blocks — the current user's name always resolves via
   * currentProfile.
   */
  profileNames: Record<string, string>;
  /**
   * Best-effort uid → full UserProfile cache for the switcher management modal, so
   * each row can show avatar + core chips (industry/role/level) without an N-serial
   * stall. Populated lazily/in-parallel by `ensureCards`; a missing entry falls back
   * to the raw id with chips omitted.
   */
  profileCards: Record<string, UserProfile>;
  /** most-recently-selected user_ids (newest first, persisted); drives the "recent" list. */
  recentUsers: string[];
  /** non-fatal API problem (service unreachable / empty) — panels degrade gracefully. */
  usersError: string | null;
  /** cross-panel jump target for the Sources panel (set by Recall hits). */
  sourceFocus: SourceFocus | null;

  /** Recall view's inputs + last result — survives a Sources jump + Back (per user). */
  recallCache: RecallCache;
  /** Ask view's build inputs + conversation — survives a Sources jump + Back (per user). */
  askCache: AskCache;
  /** Live Context's roles + conversation, surviving navigation away and back. */
  liveContext: LiveContextCache;

  /** snapshots for the current user (git commits); [0] is HEAD. Empty = no canonical. */
  snapshots: SnapshotSummary[];
  /** total git commits and opaque continuation for the bounded snapshot picker. */
  snapshotTotal: number;
  snapshotNextCursor: string | null;
  snapshotsLoading: boolean;
  snapshotError: string | null;
  /** selected snapshot ref, or null = current HEAD (live). Non-HEAD = history, read-only. */
  currentSnapshot: string | null;

  /**
   * The user's FROZEN knowledge-base snapshots (GET /kb-snapshots) — a different object from
   * `snapshots` above: a git commit is canonical-only and browse-only, a kb-snapshot has its
   * own copies of the retrieval layers and can therefore be ASKED.
   */
  kbSnapshots: KbSnapshot[];
  kbSnapshotsLoading: boolean;
  kbSnapshotError: string | null;
  /**
   * The kb-snapshot the whole app is pinned to, or null = the live base. When set, Recall
   * sends its id and browsing reads canonical at its pinned commit.
   */
  currentKbSnapshot: KbSnapshot | null;

  view: ViewName;
  selection: Selection;
  theme: Theme;
  /** interface language (zh | en); resolved from localStorage → navigator → en. */
  locale: Locale;

  init: () => Promise<void>;
  /** (re)load the pneuma-knowledge user directory from GET /v1/users. */
  loadUsers: () => Promise<void>;
  /** (re)load the active user's product profile from GET /profile (drives Profile view + name). */
  loadProfile: () => Promise<void>;
  /**
   * Merge a freshly saved/edited profile (from PUT /profile) into the switcher caches
   * and — when it is the active user — into `currentProfile`, so an edit reflects
   * everywhere without a round-trip. Also keeps the id selectable in the switcher.
   */
  setProfile: (uid: string, profile: UserProfile) => void;
  /** best-effort populate `profileNames` for the given uids (parallel, deduped, non-blocking). */
  ensureNames: (uids: string[]) => void;
  /**
   * best-effort populate `profileCards` (full profiles) for the given uids — parallel
   * (`Promise.allSettled`), deduped, non-blocking; also seeds `profileNames`. Powers
   * the switcher modal's avatar + core chips without a serial N-request stall.
   */
  ensureCards: (uids: string[]) => void;
  /**
   * (re)load the current user's canonical dataset from GET /v1/users/{uid}/dataset and
   * light up the four canonical views. Empty canonical (no docs, no patches) clears the
   * dataset so the views fall back to their "not yet compiled" empty state.
   */
  loadUserDataset: () => Promise<void>;
  /** (re)load the current user's snapshot list from GET /snapshots. */
  loadSnapshots: () => Promise<void>;
  /** append the next bounded git-history page to the snapshot picker. */
  loadMoreSnapshots: () => Promise<void>;
  /** select a snapshot (null = HEAD); reloads the dataset at that ref (read-only if history). */
  setSnapshot: (ref: string | null) => void;
  /** (re)load the user's frozen knowledge-base snapshots from GET /kb-snapshots. */
  loadKbSnapshots: () => Promise<void>;
  /**
   * Pin the whole app to a frozen snapshot (null = back to the live base). Browsing follows
   * by reading canonical at the snapshot's commit; Recall follows by sending its id.
   */
  setKbSnapshot: (snapshot: KbSnapshot | null) => void;
  /** Freeze the base as it stands now, then poll until the copy pipeline settles. */
  createSnapshot: (label: string) => Promise<void>;
  /** Delete a frozen snapshot (unpins it first when it is the pinned one). */
  removeSnapshot: (snapshotId: string) => Promise<void>;
  /** switch the active pneuma-knowledge user (persists; clears any Sources focus). */
  setUser: (uid: string) => void;
  /**
   * Enter the empty knowledge-base context of a (possibly brand-new) user_id:
   * optimistically add it to `users` so the switcher can render it even before the
   * backend directory knows it, switch to it, land on the Ingest panel, and post the
   * "add your first source" nudge. user_id is an external key — the service mints
   * no user, so a new id is absent from GET /v1/users until its first source lands.
   */
  createUser: (uid: string) => void;
  /** Leave new-profile onboarding and continue to the first-source import step. */
  finishProfileCreation: (saved: boolean) => void;
  /** open the global source galley sheet on a source (+ optional block range), in place —
   * no view switch: a citation is a footnote to follow, not a navigation. */
  focusSource: (sourceId: string, range?: { start: number; end: number } | null) => void;
  /** close the global source galley sheet. */
  clearSourceFocus: () => void;
  /** merge a partial into the Recall view cache (inputs / last result). */
  setRecallCache: (patch: Partial<RecallCache>) => void;
  /** merge a partial into the Ask view cache (build inputs / conversation). `briefing` is
   * deliberately not reachable from here — it moves only through `selectBriefing`, so the
   * thread can never be left attached to a briefing it was not asked against. */
  setAskCache: (patch: Partial<Omit<AskCache, "briefing">>) => void;
  /** point Ask at a briefing (or back at the builder with `null`): the pack, the question
   * thread and the draft question change together, in one write. */
  selectBriefing: (next: BriefingBuilt | null) => void;
  /** merge a partial into the Live Context conversation (roles / turns / active pill / mode). */
  setLiveContext: (patch: Partial<LiveContextCache>) => void;
  /** empty the conversation, keeping the roles the operator set up. */
  clearLiveContextTurns: () => void;
  setView: (v: ViewName) => void;
  select: (s: Selection) => void;
  /** cross-view jump: set selection and optionally switch the active view */
  jump: (s: Selection, view?: ViewName) => void;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
  /** switch the interface language (persists; takes effect without a reload). */
  setLocale: (l: Locale) => void;
  toggleLocale: () => void;
  dismissNotice: () => void;
}

/**
 * Monotonic profile-load token: `loadProfile` claims one before its await so a
 * stale response (user switched away mid-flight) is discarded, and the returned —
 * possibly normalized — user_id can never be mistaken for a staleness key.
 */
let profileToken = 0;
/** Invalidates an in-flight canonical projection when user/snapshot context changes. */
let datasetToken = 0;
/** Invalidates an in-flight snapshot page when user context changes. */
let snapshotToken = 0;
/** Invalidates an in-flight kb-snapshot list when user context changes. */
let kbSnapshotToken = 0;

/** How long to wait between polls while a snapshot's copy pipeline runs. */
const SNAPSHOT_POLL_MS = 1_500;
/** Give up polling after this long and let the list show whatever status it reports. */
const SNAPSHOT_POLL_TIMEOUT_MS = 180_000;

/**
 * Poll a freshly created snapshot until it leaves "creating".
 *
 * Polling rather than streaming because the copy is a one-shot background job whose only
 * observable is the registry row, and the row is already exposed by the list endpoint —
 * a dedicated progress channel would be a second source of truth for the same status.
 * Bounded on both axes (interval and total time) so a stuck pipeline degrades to "still
 * creating" in the picker rather than an endless request loop.
 */
async function pollUntilSettled(
  userId: string,
  snapshotId: string,
  stillCurrent: () => boolean,
): Promise<void> {
  const deadline = Date.now() + SNAPSHOT_POLL_TIMEOUT_MS;
  while (Date.now() < deadline && stillCurrent()) {
    await new Promise((resolve) => setTimeout(resolve, SNAPSHOT_POLL_MS));
    if (!stillCurrent()) return;
    const rows = await listKbSnapshots(userId);
    const row = rows.find((s) => s.snapshot_id === snapshotId);
    if (!row || row.status !== "creating") return;
  }
}

/** In-flight guard for `ensureNames` so a re-render never re-fires a live fetch. */
const namesInFlight = new Set<string>();

/** In-flight guard for `ensureCards` so a re-render never re-fires a live fetch. */
const cardsInFlight = new Set<string>();

/**
 * Ensure the active selection stays selectable in the switcher even when the
 * backend directory (GET /v1/users) does not list it yet — a brand-new user_id
 * only appears there after its first source lands. Dedupes, keeps the current id first.
 */
function withCurrent(list: string[], current: string | null): string[] {
  if (!current) return list;
  if (list.includes(current)) return list;
  return [current, ...list];
}

function initialTheme(): Theme {
  const stored =
    typeof localStorage !== "undefined"
      ? (localStorage.getItem("pneuma-knowledge-theme") as Theme | null)
      : null;
  if (stored === "light" || stored === "dark") return stored;
  if (typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches)
    return "dark";
  return "light";
}

function applyTheme(t: Theme) {
  document.documentElement.setAttribute("data-theme", t);
  try {
    localStorage.setItem("pneuma-knowledge-theme", t);
  } catch {
    /* ignore */
  }
}

/**
 * Same shape as `applyTheme`: persist the explicit choice, mirror it into the module-level
 * active locale that the non-React formatters read, and put it on `<html lang>` so the
 * browser hyphenates and the screen reader switches voice.
 */
function applyLocale(locale: Locale) {
  setActiveLocale(locale);
  document.documentElement.setAttribute("lang", locale === "zh" ? "zh-CN" : "en");
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    /* ignore */
  }
}

/**
 * Push the view + selection into the location hash so it is deep-linkable and the
 * Back button walks the in-app history. Assigning location.hash creates a history
 * entry and emits a hashchange whose parsed state equals the store's, so the
 * listener no-ops (no loop). `replace` is used for the initial normalization.
 */
function writeHash(view: ViewName, selection: Selection, replace = false) {
  if (typeof window === "undefined") return;
  const next = selectionToHash(view, selection);
  if (window.location.hash === next) return;
  if (replace) {
    window.history.replaceState(null, "", next);
  } else {
    window.location.hash = next;
  }
}

export const useApp = create<AppState>((set, get) => ({
  status: "idle",
  error: null,
  notice: null,
  dataset: null,
  model: null,
  users: [],
  currentUser: null,
  currentProfile: null,
  profileOnboardingUser: null,
  profileNames: {},
  profileCards: {},
  recentUsers: loadRecent(),
  usersError: null,
  sourceFocus: null,
  recallCache: EMPTY_RECALL_CACHE,
  askCache: EMPTY_ASK_CACHE,
  liveContext: EMPTY_LIVE_CONTEXT_CACHE,
  snapshots: [],
  snapshotTotal: 0,
  snapshotNextCursor: null,
  snapshotsLoading: false,
  snapshotError: null,
  currentSnapshot: null,
  kbSnapshots: [],
  kbSnapshotsLoading: false,
  kbSnapshotError: null,
  currentKbSnapshot: null,
  view: "overview",
  selection: null,
  theme: initialTheme(),
  locale: detectLocale(),

  init: async () => {
    applyTheme(get().theme);
    applyLocale(get().locale);

    // restore view + selection from a deep link, else normalize the hash.
    if (typeof window !== "undefined") {
      const initial = hashToState(window.location.hash);
      if (initial) {
        set({ view: initial.view, selection: initial.selection });
        writeHash(initial.view, initial.selection, true);
      } else {
        writeHash(get().view, get().selection, true);
      }
      window.addEventListener("hashchange", () => {
        const parsed = hashToState(window.location.hash);
        if (!parsed) return;
        const { view, selection } = get();
        if (parsed.view === view && sameSelection(parsed.selection, selection)) return;
        set({ view: parsed.view, selection: parsed.selection });
        if (needsCanonicalDataset(parsed.view) && get().dataset == null) {
          void get().loadUserDataset();
        }
      });
    }

    // The canonical/derived views load per-user from GET /v1/users/{uid}/dataset:
    // a user with no compiled canonical yet leaves dataset null and those four
    // views render empty states. The live surface is the pneuma-knowledge service — load
    // the user directory and land the UI ready regardless (an empty / unreachable
    // directory is a valid state the panels explain).
    set({ status: "loading", error: null });
    await get().loadUsers();
    // Profile powers the Profile view + the top-bar name — load it non-blocking so
    // "ready" never waits on it (an unreachable /profile degrades gracefully).
    void get().loadProfile();
    await get().loadSnapshots();
    void get().loadKbSnapshots();
    if (needsCanonicalDataset(get().view)) {
      await get().loadUserDataset();
    }
    set({ status: "ready" });
  },

  loadUsers: async () => {
    try {
      const fetched = await listUsers();
      const stored =
        typeof localStorage !== "undefined" ? localStorage.getItem(USER_KEY) : null;
      // Prefer the live in-app selection (may be an optimistic new user the directory
      // hasn't seen yet), then the persisted id, then the first known user. The
      // selection must survive a refresh even if the backend directory omits it.
      const current = get().currentUser ?? stored ?? fetched[0] ?? null;
      set({ users: withCurrent(fetched, current), currentUser: current, usersError: null });
    } catch (e) {
      // Directory unreachable — keep any optimistic selection alive so its empty
      // knowledge-base context still renders instead of snapping back to "no user".
      const current = get().currentUser;
      set({
        users: current ? [current] : [],
        currentUser: current,
        usersError: (e as Error).message,
      });
    }
  },

  loadProfile: async () => {
    const uid = get().currentUser;
    if (!uid) {
      set({ currentProfile: null });
      return;
    }
    const token = ++profileToken;
    try {
      const profile = await getUserProfile(uid);
      if (token !== profileToken) return; // user switched away — discard
      set((s) => ({
        currentProfile: profile,
        // seed the switcher caches under the REQUESTED uid (the key the switcher uses),
        // not the possibly-normalized profile.user_id.
        profileNames: { ...s.profileNames, [uid]: profile.display_name },
        profileCards: { ...s.profileCards, [uid]: profile },
      }));
    } catch {
      if (token !== profileToken) return;
      set({ currentProfile: null }); // /profile unreachable — Profile view degrades
    }
  },

  setProfile: (uid, profile) => {
    set((s) => ({
      users: withCurrent(s.users, uid),
      currentProfile: uid === s.currentUser ? profile : s.currentProfile,
      profileNames: { ...s.profileNames, [uid]: profile.display_name },
      profileCards: { ...s.profileCards, [uid]: profile },
    }));
  },

  ensureNames: (uids) => {
    const have = get().profileNames;
    const todo = uids.filter((id) => id && !(id in have) && !namesInFlight.has(id));
    if (todo.length === 0) return;
    todo.forEach((id) => namesInFlight.add(id));
    // Parallel + best-effort: never a serial N-request stall. Each resolves
    // independently into the cache; failures just leave the id → raw-id fallback.
    void Promise.allSettled(
      todo.map(async (id) => {
        try {
          const profile = await getUserProfile(id);
          set((s) => ({ profileNames: { ...s.profileNames, [id]: profile.display_name } }));
        } finally {
          namesInFlight.delete(id);
        }
      }),
    );
  },

  ensureCards: (uids) => {
    const have = get().profileCards;
    const todo = uids.filter((id) => id && !(id in have) && !cardsInFlight.has(id));
    if (todo.length === 0) return;
    todo.forEach((id) => cardsInFlight.add(id));
    // Parallel + best-effort: never a serial N-request stall. Each resolves
    // independently into the cache; failures just leave the id → raw-id fallback.
    void Promise.allSettled(
      todo.map(async (id) => {
        try {
          const profile = await getUserProfile(id);
          set((s) => ({
            profileCards: { ...s.profileCards, [id]: profile },
            profileNames: { ...s.profileNames, [id]: profile.display_name },
          }));
        } finally {
          cardsInFlight.delete(id);
        }
      }),
    );
  },

  loadSnapshots: async () => {
    const uid = get().currentUser;
    if (!uid) {
      snapshotToken += 1;
      set({
        snapshots: [],
        snapshotTotal: 0,
        snapshotNextCursor: null,
        snapshotsLoading: false,
        snapshotError: null,
        currentSnapshot: null,
      });
      return;
    }
    const token = ++snapshotToken;
    set({ snapshotsLoading: true, snapshotError: null });
    try {
      const page = await listSnapshots(uid, { limit: 25 });
      if (token !== snapshotToken || uid !== get().currentUser) return;
      // A selected older ref may live beyond page one. Preserve its already-loaded
      // label instead of falsely falling back to HEAD merely because the new page is bounded.
      const current = get().currentSnapshot;
      const retained = current
        ? get().snapshots.find((snapshot) => snapshot.ref === current)
        : undefined;
      const snapshots =
        retained && !page.items.some((snapshot) => snapshot.ref === retained.ref)
          ? [retained, ...page.items]
          : page.items;
      set({
        snapshots,
        snapshotTotal: page.page.total,
        snapshotNextCursor: page.page.next_cursor,
        snapshotsLoading: false,
        snapshotError: null,
      });
    } catch (error) {
      if (token !== snapshotToken) return;
      set({
        snapshotsLoading: false,
        snapshotError: (error as Error).message,
      });
    }
  },

  loadMoreSnapshots: async () => {
    const uid = get().currentUser;
    const cursor = get().snapshotNextCursor;
    if (!uid || !cursor || get().snapshotsLoading) return;
    const token = ++snapshotToken;
    set({ snapshotsLoading: true, snapshotError: null });
    try {
      const page = await listSnapshots(uid, { limit: 25, cursor });
      if (token !== snapshotToken || uid !== get().currentUser) return;
      set((state) => ({
        snapshots: appendUniqueSnapshots(state.snapshots, page.items),
        snapshotTotal: page.page.total,
        snapshotNextCursor: page.page.next_cursor,
        snapshotsLoading: false,
        snapshotError: null,
      }));
    } catch (error) {
      if (token !== snapshotToken) return;
      set({
        snapshotsLoading: false,
        snapshotError: (error as Error).message,
      });
    }
  },

  setSnapshot: (ref) => {
    datasetToken += 1;
    // Picking a bare commit is canonical-only browsing, so it also clears any frozen-snapshot
    // pin: the two are alternative read planes and holding both would make "which base is
    // answering?" unanswerable.
    set({
      currentSnapshot: ref,
      currentKbSnapshot: null,
      dataset: null,
      model: null,
    });
    if (needsCanonicalDataset(get().view)) {
      void get().loadUserDataset();
    }
  },

  loadKbSnapshots: async () => {
    const uid = get().currentUser;
    if (!uid) {
      set({ kbSnapshots: [], kbSnapshotError: null, currentKbSnapshot: null });
      return;
    }
    const token = ++kbSnapshotToken;
    set({ kbSnapshotsLoading: true, kbSnapshotError: null });
    try {
      const items = await listKbSnapshots(uid);
      if (token !== kbSnapshotToken || uid !== get().currentUser) return;
      // Refresh the pinned snapshot from the list it came from, so a pin taken while the copy
      // was still running flips to `ready` (or `failed`) without a manual re-select.
      const pinned = get().currentKbSnapshot;
      const refreshed = pinned
        ? (items.find((s) => s.snapshot_id === pinned.snapshot_id) ?? null)
        : null;
      set({
        kbSnapshots: items,
        kbSnapshotsLoading: false,
        kbSnapshotError: null,
        currentKbSnapshot: refreshed,
      });
    } catch (error) {
      if (token !== kbSnapshotToken) return;
      set({
        kbSnapshotsLoading: false,
        kbSnapshotError: (error as Error).message,
      });
    }
  },

  setKbSnapshot: (snapshot) => {
    datasetToken += 1;
    set({
      currentKbSnapshot: snapshot,
      // Browsing follows the pin by reading canonical at the commit the snapshot froze — the
      // existing `at=` path, no new endpoint. null → back to HEAD.
      currentSnapshot: snapshot?.canonical_ref || null,
      dataset: null,
      model: null,
    });
    if (needsCanonicalDataset(get().view)) {
      void get().loadUserDataset();
    }
  },

  createSnapshot: async (label) => {
    const uid = get().currentUser;
    if (!uid || !label.trim()) return;
    set({ kbSnapshotsLoading: true, kbSnapshotError: null });
    try {
      const created = await createKbSnapshot(uid, label.trim());
      // Show it immediately in status "creating" — the copy runs server-side and the row is
      // the only honest progress indicator we have.
      set((s) => ({ kbSnapshots: [created, ...s.kbSnapshots] }));
      await pollUntilSettled(uid, created.snapshot_id, () => get().currentUser === uid);
    } catch (error) {
      set({ kbSnapshotError: (error as Error).message });
    } finally {
      set({ kbSnapshotsLoading: false });
      if (get().currentUser === uid) await get().loadKbSnapshots();
    }
  },

  removeSnapshot: async (snapshotId) => {
    const uid = get().currentUser;
    if (!uid) return;
    // Unpin first: continuing to answer over a tenant that is being purged would produce
    // silently emptying answers rather than an error.
    if (get().currentKbSnapshot?.snapshot_id === snapshotId) {
      get().setKbSnapshot(null);
    }
    try {
      await deleteKbSnapshot(uid, snapshotId);
    } catch (error) {
      set({ kbSnapshotError: (error as Error).message });
    }
    if (get().currentUser === uid) await get().loadKbSnapshots();
  },

  loadUserDataset: async () => {
    const uid = get().currentUser;
    if (!uid) {
      set({ dataset: null, model: null });
      return;
    }
    const token = ++datasetToken;
    try {
      const at = get().currentSnapshot;
      const raw = (await getDatasetRaw(uid, at)) as unknown as Dataset;
      if (token !== datasetToken || uid !== get().currentUser) return;
      const dataset: Dataset = {
        workspace: raw.workspace,
        documents: raw.documents,
        graph: raw.graph,
        timeline: raw.timeline,
        journal: raw.journal,
        // skill-declared claim-prefix vocabulary (§5 strong/medium/weak) rides dataset meta.
        claimLabels: Array.isArray(raw.claimLabels)
          ? raw.claimLabels
          : (raw as { claim_labels?: Dataset["claimLabels"] }).claim_labels ?? [],
      };
      const hasContent =
        (dataset.documents?.documents?.length ?? 0) > 0 ||
        (dataset.timeline?.patches?.length ?? 0) > 0;
      if (!hasContent) {
        set({ dataset: null, model: null });
        return;
      }
      set({ dataset, model: buildModel(dataset) });
    } catch {
      if (token !== datasetToken) return;
      // Canonical read failed (service down / empty) — degrade to the empty state.
      set({ dataset: null, model: null });
    }
  },

  setUser: (uid) => {
    try {
      localStorage.setItem(USER_KEY, uid);
    } catch {
      /* ignore */
    }
    // New user: reset to HEAD, drop the stale profile, reload snapshots then dataset.
    // Record the selection in the MRU list (createUser routes through here too).
    datasetToken += 1;
    snapshotToken += 1;
    set((s) => ({
      currentUser: uid,
      currentProfile: null,
      profileOnboardingUser: null,
      dataset: null,
      model: null,
      sourceFocus: null,
      selection: null,
      currentSnapshot: null,
      snapshots: [],
      snapshotTotal: 0,
      snapshotNextCursor: null,
      snapshotsLoading: false,
      snapshotError: null,
      // A snapshot belongs to one owner, so switching users unpins: carrying a pin across
      // would ask one user's frozen tenant while the shell named another user.
      kbSnapshots: [],
      kbSnapshotError: null,
      currentKbSnapshot: null,
      // per-user in-memory scratch: never carry one user's recall/ask into another's.
      recallCache: EMPTY_RECALL_CACHE,
      askCache: EMPTY_ASK_CACHE,
      // The Live Context conversation goes with them: it was written to be evaluated
      // against THIS user's knowledge base, and a window carried into another user's page
      // would be asking one library about another's conversation.
      liveContext: EMPTY_LIVE_CONTEXT_CACHE,
      recentUsers: pushRecent(s.recentUsers, uid),
    }));
    void get().loadProfile();
    void get().loadKbSnapshots();
    void get().loadSnapshots().then(() => {
      if (needsCanonicalDataset(get().view)) {
        return get().loadUserDataset();
      }
    });
  },

  createUser: (uid) => {
    // Optimistically merge the new id into the switcher options before the switch
    // (the backend directory won't list it until its first source lands).
    set((s) => ({ users: withCurrent(s.users, uid) }));
    get().setUser(uid); // handles persistence + HEAD reset + snapshot/dataset reload
    // Creating a user starts with its profile. AI generation is an onboarding aid,
    // never an action on an existing profile's detail page.
    set({
      view: "profile",
      profileOnboardingUser: uid,
      notice: { key: "nav.notice.newProfile" },
    });
    writeHash("profile", null);
  },

  finishProfileCreation: (saved) => {
    set({
      profileOnboardingUser: null,
      view: "ingest",
      notice: {
        key: saved ? "nav.notice.profileSaved" : "nav.notice.profileSkipped",
      },
    });
    writeHash("ingest", null);
  },

  focusSource: (sourceId, range) => {
    set({
      sourceFocus: {
        sourceId,
        blockStart: range?.start ?? null,
        blockEnd: range?.end ?? null,
      },
    });
  },

  clearSourceFocus: () => set({ sourceFocus: null }),

  setRecallCache: (patch) => set((s) => ({ recallCache: { ...s.recallCache, ...patch } })),
  setAskCache: (patch) => set((s) => ({ askCache: { ...s.askCache, ...patch } })),
  selectBriefing: (next) =>
    set((s) => ({ askCache: { ...s.askCache, ...briefingSelection(next) } })),

  setLiveContext: (patch) => set((s) => ({ liveContext: { ...s.liveContext, ...patch } })),
  // Turns go, roles stay: clearing a conversation is "start a new one", and re-naming the
  // people in it every time would be the opposite of a saved setup.
  clearLiveContextTurns: () => set((s) => ({ liveContext: { ...s.liveContext, turns: [] } })),

  setView: (view) => {
    set({ view });
    writeHash(view, get().selection);
    if (needsCanonicalDataset(view) && get().dataset == null) {
      void get().loadUserDataset();
    }
  },
  select: (selection) => {
    set({ selection });
    // Replace, not push: opening/closing a galley or picking a row is state WITHIN the
    // current page. Pushing every selection filled history with drawer-toggle entries,
    // so Back appeared dead — it was walking invisible selection states instead of
    // leaving the view. Cross-view jumps (jump/setView) still push; Back always returns
    // to the previous VIEW in one step, and the address bar stays deep-linkable.
    writeHash(get().view, selection, true);
  },
  jump: (selection, view) => {
    const nextView = view ?? get().view;
    set({ selection, view: nextView });
    writeHash(nextView, selection);
    if (needsCanonicalDataset(nextView) && get().dataset == null) {
      void get().loadUserDataset();
    }
  },

  toggleTheme: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    applyTheme(next);
    set({ theme: next });
  },
  setTheme: (t) => {
    applyTheme(t);
    set({ theme: t });
  },

  setLocale: (locale) => {
    applyLocale(locale);
    set({ locale });
  },
  toggleLocale: () => {
    const next: Locale = get().locale === "zh" ? "en" : "zh";
    applyLocale(next);
    set({ locale: next });
  },
  dismissNotice: () => set({ notice: null }),
}));
