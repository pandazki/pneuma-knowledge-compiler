import { create } from "zustand";
import type { Dataset, Selection, UserProfile, ViewName } from "./types";
import { buildModel, type Model } from "./model";
import { hashToState, sameSelection, selectionToHash } from "./hash";
import { needsCanonicalDataset } from "./datasetLoading";
import {
  listUsers,
  getDatasetRaw,
  getUserProfile,
  listSnapshots,
  type SnapshotSummary,
  type RecallHit,
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
  hits: RecallHit[] | null;
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

const EMPTY_RECALL_CACHE: RecallCache = {
  query: "",
  mode: "rag",
  hits: null,
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

interface AppState {
  status: "idle" | "loading" | "ready" | "error";
  error: string | null;
  /** non-blocking, dismissible notice (e.g. invalid ?ds= fell back) — distinct from `error`. */
  notice: string | null;
  dataset: Dataset | null;
  model: Model | null;

  /** pneuma-knowledge service state (M2). Users own all data (invariant I1). */
  users: string[];
  currentUser: string | null;
  /** product profile of the active user (GET /profile); null while loading / unavailable. */
  currentProfile: UserProfile | null;
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
  /** most-recently-selected user_ids (newest first, persisted); drives the "最近" list. */
  recentUsers: string[];
  /** non-fatal API problem (service unreachable / empty) — panels degrade gracefully. */
  usersError: string | null;
  /** cross-panel jump target for the Sources panel (set by Recall hits). */
  sourceFocus: SourceFocus | null;

  /** Recall view's inputs + last result — survives a Sources jump + Back (per user). */
  recallCache: RecallCache;
  /** Ask view's build inputs + conversation — survives a Sources jump + Back (per user). */
  askCache: AskCache;

  /** snapshots for the current user (git commits); [0] is HEAD. Empty = no canonical. */
  snapshots: SnapshotSummary[];
  /** selected snapshot ref, or null = current HEAD (live). Non-HEAD = history, read-only. */
  currentSnapshot: string | null;

  view: ViewName;
  selection: Selection;
  theme: Theme;

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
  /** select a snapshot (null = HEAD); reloads the dataset at that ref (read-only if history). */
  setSnapshot: (ref: string | null) => void;
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
  /** jump to the Sources panel focused on a source (+ optional block range). */
  focusSource: (sourceId: string, range?: { start: number; end: number } | null) => void;
  /** merge a partial into the Recall view cache (inputs / last result). */
  setRecallCache: (patch: Partial<RecallCache>) => void;
  /** merge a partial into the Ask view cache (build inputs / conversation). */
  setAskCache: (patch: Partial<AskCache>) => void;
  setView: (v: ViewName) => void;
  select: (s: Selection) => void;
  /** cross-view jump: set selection and optionally switch the active view */
  jump: (s: Selection, view?: ViewName) => void;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
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
  profileNames: {},
  profileCards: {},
  recentUsers: loadRecent(),
  usersError: null,
  sourceFocus: null,
  recallCache: EMPTY_RECALL_CACHE,
  askCache: EMPTY_ASK_CACHE,
  snapshots: [],
  currentSnapshot: null,
  view: "overview",
  selection: null,
  theme: initialTheme(),

  init: async () => {
    applyTheme(get().theme);

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
      set({ snapshots: [], currentSnapshot: null });
      return;
    }
    try {
      const snaps = await listSnapshots(uid);
      // Keep the selected snapshot only if it still exists; else fall back to HEAD.
      const current = get().currentSnapshot;
      const stillValid = current && snaps.some((s) => s.ref === current);
      set({ snapshots: snaps, currentSnapshot: stillValid ? current : null });
    } catch {
      set({ snapshots: [], currentSnapshot: null });
    }
  },

  setSnapshot: (ref) => {
    datasetToken += 1;
    set({ currentSnapshot: ref, dataset: null, model: null });
    if (needsCanonicalDataset(get().view)) {
      void get().loadUserDataset();
    }
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
        // skill-declared claim-prefix vocabulary (§5强/中/弱) rides the dataset meta.
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
    set((s) => ({
      currentUser: uid,
      currentProfile: null,
      dataset: null,
      model: null,
      sourceFocus: null,
      selection: null,
      currentSnapshot: null,
      // per-user in-memory scratch: never carry one user's recall/ask into another's.
      recallCache: EMPTY_RECALL_CACHE,
      askCache: EMPTY_ASK_CACHE,
      recentUsers: pushRecent(s.recentUsers, uid),
    }));
    void get().loadProfile();
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
    // Land on Ingest — an empty knowledge base's next step is adding data — and nudge.
    set({ view: "ingest", notice: "新知识库 · 去 Ingest 加第一条数据" });
    writeHash("ingest", null);
  },

  focusSource: (sourceId, range) => {
    set({
      view: "sources",
      sourceFocus: {
        sourceId,
        blockStart: range?.start ?? null,
        blockEnd: range?.end ?? null,
      },
    });
    writeHash("sources", get().selection);
  },

  setRecallCache: (patch) => set((s) => ({ recallCache: { ...s.recallCache, ...patch } })),
  setAskCache: (patch) => set((s) => ({ askCache: { ...s.askCache, ...patch } })),

  setView: (view) => {
    set({ view });
    writeHash(view, get().selection);
    if (needsCanonicalDataset(view) && get().dataset == null) {
      void get().loadUserDataset();
    }
  },
  select: (selection) => {
    set({ selection });
    writeHash(get().view, selection);
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
  dismissNotice: () => set({ notice: null }),
}));
