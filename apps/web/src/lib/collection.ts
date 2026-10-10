/** Personal-edition collection configuration; secrets exist only in mutation responses. */
export type CollectionHarness = "codex" | "claude-code";

export interface CollectionScope {
  projects: string[];
  harnesses: CollectionHarness[];
  since: string | null;
}

export interface CollectionSource {
  id: string;
  label: string;
  kind: "local" | "r2";
  processor_id: string;
  enabled: boolean;
  scope: CollectionScope | null;
  watches?: { path: string; recursive: boolean; harnesses: CollectionHarness[]; since: string | null }[];
  complex_scope?: boolean;
}

export interface CollectionProcessor {
  id: string;
  label: string;
  material_type: "agent-session";
  min_owner_turns: number;
  min_owner_chars: number;
  ack_max_words: number;
  max_part_chars: number;
}

export interface CollectionDevice {
  device_id: string;
  label: string;
  status: "active" | "paused" | "revoked";
  last_seen_at: string | null;
  last_snapshot_at: string | null;
  policy?: { scope: CollectionScope; processor_id: string };
}

export interface CollectionProject {
  project_id: string;
  name: string;
  remotes: string[];
  locations: { device_id: string; path: string }[];
  source_ids: string[];
}

export interface CollectionInvitation {
  invitation_id: string;
  label: string;
  status: "pending" | "redeemed" | "revoked" | "expired";
  expires_at: string;
  device_id: string | null;
}

export interface HomeCollection {
  cloud: { url: string; configured: boolean; error?: string };
  sources: CollectionSource[];
  processors: CollectionProcessor[];
  devices: CollectionDevice[];
  projects: CollectionProject[];
  invitations: CollectionInvitation[];
}

export interface CollectionInvitationRequest {
  label: string;
  scope: CollectionScope;
  processor_id: string;
}

export interface CollectionInvitationSecret {
  invitation_id: string;
  expires_at: string;
  command: string;
  ai_prompt: string;
}

export interface CollectionScopeDraft {
  allProjects: boolean;
  projects: string;
  harnesses: CollectionHarness[];
  since: string;
}

/** A frozen base can have no canonical commit yet; either kind of pin is read-only. */
export function collectionReadOnly(state: {
  currentSnapshot: string | null;
  currentKbSnapshot: object | null;
}): boolean {
  return state.currentSnapshot != null || state.currentKbSnapshot != null;
}

export function scopeDraft(scope?: CollectionScope | null): CollectionScopeDraft {
  return {
    allProjects: scope ? scope.projects.includes("all") : true,
    projects: scope?.projects.filter((path) => path !== "all").join("\n") ?? "",
    harnesses: scope ? [...scope.harnesses] : ["codex", "claude-code"],
    since: scope?.since?.slice(0, 10) ?? "",
  };
}

/** An empty restricted scope must never silently widen into collection of every project. */
export function collectionScope(draft: CollectionScopeDraft): CollectionScope | null {
  const projects = draft.allProjects
    ? ["all"]
    : [...new Set(draft.projects.split("\n").map((path) => path.trim()).filter(Boolean))];
  if (projects.length === 0 || draft.harnesses.length === 0) return null;
  if (!draft.allProjects && projects.includes("all")) return null;
  const since = draft.since ? `${draft.since}T00:00:00.000Z` : null;
  if (since && (Number.isNaN(Date.parse(since)) || new Date(since).toISOString() !== since)) {
    return null;
  }
  return { projects, harnesses: [...draft.harnesses], since };
}

/** Server redemption/revocation wins over this browser's expiry clock. */
export function invitationStatus(
  invitation: Pick<CollectionInvitation, "status" | "expires_at">,
  now: number,
): CollectionInvitation["status"] {
  if (invitation.status !== "pending") return invitation.status;
  const expiry = Date.parse(invitation.expires_at);
  return !Number.isFinite(expiry) || expiry <= now ? "expired" : "pending";
}
