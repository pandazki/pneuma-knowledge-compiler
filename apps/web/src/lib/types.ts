/**
 * Types for the public canonical projection returned by pneuma_knowledge_service.dataset.
 * The UI reads this schema rather than reaching into a workspace's internal storage.
 *
 * Fields are defensively optional: the viewer tolerates deviations between the doc
 * schema and a given exporter version (see README "schema deviations").
 */

export type FlagKind = "disputed" | "open_question" | "inferred" | string;

export type RedactionState = "included" | "snippet" | "withheld" | string;

export interface Citation {
  source_id: string;
  /**
   * schema_version 2 exporter always emits from/to/snippet/redaction_state. Kept
   * required so call sites need not re-guard; the loader is tolerant of
   * older exports that omit them (they parse as undefined and the UI degrades).
   */
  from: number;
  to: number;
  snippet: string;
  redaction_state: RedactionState;
}

export interface Claim {
  anchor: string | null;
  kind: "paragraph" | "list_item" | string;
  /** CLEAN display prose (schema v2 strips machinery + list marker), ready to render. */
  text: string;
  /** original block markdown with machinery intact, for audit / round-trip (schema v2). */
  raw_text?: string;
  citations: Citation[];
  flags: FlagKind[];
  /** rationales parsed from inline marks (schema v2); may be {} / absent. */
  notes?: { disputed?: string; open_question?: string };
}

export interface DocumentRecord {
  document_id: string | null;
  path: string;
  title: string;
  frontmatter: Record<string, unknown>;
  body: string;
  claims: Claim[];
}

/**
 * One skill-declared claim-prefix label (dataset meta / GET /skill `claim_labels`). The
 * skill owns this vocabulary; the UI implements a generic render mechanism and hardcodes
 * no specific word. `label` is the bare字面 prefix (no【】brackets); `tier` is the
 * presentation weight hint the badge maps to a visual档位.
 */
export interface ClaimLabel {
  label: string;
  name: string;
  description: string;
  tier: "solid" | "outline" | "muted" | string;
}

export interface DocumentsFile {
  schema_version: number;
  documents: DocumentRecord[];
}

export interface DomainInfo {
  domain_id: string;
  skill_version: number | null;
  ontology: string[];
}

export interface WorkspaceFile {
  schema_version: number;
  workspace_id: string;
  export_policy: "redacted" | "full" | string;
  domains: DomainInfo[];
}

export interface GraphNode {
  id: string;
  type: string | null;
  path: string;
  title: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: "link" | "relationship" | "merge" | string;
}

export interface GraphFile {
  schema_version: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Snapshot {
  source_id: string;
  source_type: string;
  captured_at: string;
  checksum: string;
  // Additive source metadata: all optional so older exported projections still open.
  source_class?: string;
  source_uri?: string;
  consumed_by?: string | null;
  material_document_id?: string | null;
}

export interface JobRecord {
  job_id: string;
  status: "compiled" | "failed" | "running" | string;
  patch_id: string | null;
  ts: string | null;
}

export interface SidecarClaimRef {
  anchor?: { document_id?: string; anchor?: string };
  flags?: FlagKind[];
  note?: string;
}

/**
 * A patch escalation as it actually appears in exported timeline.json. The label
 * field varies by producer (`reason` / `trigger` / `category` / `policy`) and the
 * body field varies too (`note` / `detail` / `question`); the viewer must read all
 * of them (see escalationText) rather than a single guessed pair — the previous
 * `policy`/`question`-only shape rendered blank rows for every real dataset
 * (fable F14). `anchor` is a string in some exports, an object in others.
 */
export interface Escalation {
  reason?: string;
  trigger?: string;
  category?: string;
  policy?: string;
  note?: string;
  detail?: string;
  question?: string;
  document_id?: string;
  source_id?: string;
  blocks?: string;
  anchor?: string | { document_id?: string; anchor?: string };
}

export interface Lineage {
  model?: string;
  provider?: string;
  tokens?: number;
  driver?: string;
  producer?: string;
}

export interface PatchRecord {
  patch_id: string;
  job_id: string | null;
  ts: string | null;
  base_commit: string | null;
  changed_paths: string[];
  /**
   * schema_version 2: stable-id interlink between a patch and the documents it
   * touched. Preferred over changed_paths for cross-view jumps.
   * changed_paths is retained for display / back-compat.
   */
  documents?: {
    document_id: string;
    path: string;
    change_type: "created" | "modified";
  }[];
  sources_consumed: string[];
  skill_version: number | null;
  effort: string | null;
  claims: SidecarClaimRef[];
  escalations: Escalation[];
  merges: unknown[];
  flag_counts: Record<string, number>;
  lineage: Lineage;
}

export interface BundleVersion {
  tag: string;
  version: number | null;
  ts: string | null;
}

export interface TimelineFile {
  schema_version: number;
  snapshots: Snapshot[];
  jobs: JobRecord[];
  patches: PatchRecord[];
  bundle_versions: BundleVersion[];
}

export interface JournalEvent {
  event_id: string;
  ts: string;
  job_id: string | null;
  patch_id: string | null;
  type: string;
  payload: Record<string, unknown>;
}

/**
 * user_id profile (GET /v1/users/{id}/profile). The backend deterministically
 * SYNTHESIZES a profile for any id (unknown ids never 404), so every user_id —
 * including a brand-new one — resolves to a full UserProfile. `source` marks its
 * origin ("mock" today). Note the returned `user_id` may be a NORMALIZED form
 * of the requested id, so never key staleness on it.
 */
export interface UserProfile {
  user_id: string;
  display_name: string;
  avatar: { initial: string; color: string };
  gender: string | null;
  birth_year: number | null;
  locale: {
    city: string | null;
    country: string | null;
    timezone: string | null;
    language: string | null;
  };
  /** core onboarding field; when "other", read `industry_other`. */
  industry: string;
  industry_other: string | null;
  /** core onboarding field; when "other", read `role_other`. */
  role: string;
  role_other: string | null;
  /** core onboarding field — one of 6 seniority tiers; drives the AI answer style. */
  level: string;
  /** human description of the AI answer style implied by `level`. */
  level_style: string;
  occupation: string | null;
  bio: string | null;
  interests: string[];
  workspace: {
    operating_mode: string | null;
    primary_stack: string | null;
    automation_level: string | null;
    active_since: string | null;
  };
  preferences: {
    response_language: string | null;
    units: string | null;
    privacy_level: string | null;
  };
  joined_at: string | null;
  source: string;
}

/** The full parsed dataset the viewer operates on. */
export interface Dataset {
  workspace: WorkspaceFile;
  documents: DocumentsFile;
  graph: GraphFile;
  timeline: TimelineFile;
  journal: JournalEvent[];
  /**
   * The effective skill's claim-prefix vocabulary (§5强/中/弱), carried in the dataset
   * top-level meta so the dataset-driven views can lift the字面【强】prefix into a badge
   * without a second request. When absent, prose remains unchanged and no badge is shown.
   */
  claimLabels?: ClaimLabel[];
}

/** A cross-view jump target. All views resolve selection through these stable ids. */
export type Selection =
  | { kind: "document"; id: string }
  | { kind: "node"; id: string }
  | { kind: "patch"; id: string }
  | { kind: "job"; id: string }
  | { kind: "snapshot"; id: string }
  | { kind: "claim"; documentId: string; anchor: string }
  // A source's original text, optionally focused on one block (溯源动线的落点).
  | { kind: "source"; id: string; block?: number }
  | { kind: "evolve-task"; id: string }
  | null;

export type ViewName =
  // open-source system map + deterministic demo journey
  | "overview"
  // pneuma-knowledge user product profile
  | "profile"
  // M2 pneuma-knowledge live API panels
  | "sources"
  | "ingest"
  | "recall"
  // M4 briefing Q&A panel
  | "ask"
  // Live Context：实时接收工作流片段并融合可引用知识（SSE / WS 双链路）
  | "live_context"
  // canonical/derived views (light up once the user has compiled canonical)
  | "library"
  | "process"
  | "history"
  | "graph"
  // schema-evolve review + 量身定制 skill 面
  | "evolve"
  // 隐藏路由：primitives 状态矩阵页（验收截图用，不进目录）
  | "components";
