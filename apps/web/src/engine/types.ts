/**
 * Engine Console data contract — mirrors the FROZEN shapes in
 * docs/design/engine-console.md. The fixtures under ./fixtures and the real `/v1/engine/*`
 * routes both speak these types; the UI never knows which side of the seam it is on.
 */

export type Localized = { en: string; zh: string };

export type KnobType = "enum" | "bool" | "int" | "string" | "document" | "overlay_map";

/** Blast radius of an edit, surfaced on every change before it is applied. */
export type ApplyKind = "hot" | "restart" | "future_compiles" | "derived_rebuild";

export type ResolutionOrigin = "env" | "engine" | "default";

export interface EngineKnob {
  /** Key inside the stage's engine file. */
  key: string;
  /** The env var it maps to; "" when the knob has no env mapping. */
  env: string;
  type: KnobType;
  /** Value vocabulary when type === "enum"; catalog keys when type === "overlay_map". */
  enum?: string[];
  default?: unknown;
  apply: ApplyKind;
  label: Localized;
  description: Localized;
}

export type StageId =
  | "intake"
  | "compile"
  | "challenge"
  | "evolve"
  | "recall"
  | "persona"
  | "prompts"
  | string;

export interface EngineStage {
  id: StageId;
  title: Localized;
  summary: Localized;
  /** Repo-relative doc deep link. */
  doc: string;
  /** Engine-relative file path. */
  file: string;
  knobs: EngineKnob[];
}

export interface EngineEdge {
  from: string;
  to: string;
  /**
   * `<stage>.<key>` reference into state.values; the edge is active iff the (draft-aware)
   * value is truthy. Absent = unconditional edge.
   */
  condition?: string;
  label: Localized;
}

/** One informational access lane over the same source material. */
export interface EngineAccessRoute {
  id: string;
  from: string;
  to: string;
  /** `intake_plan.<field>` means the route is decided independently for each source. */
  condition?: string;
  title: Localized;
  summary: Localized;
}

export interface EngineSchema {
  schema_version: number;
  stages: EngineStage[];
  edges: EngineEdge[];
  access_routes: EngineAccessRoute[];
}

export type EngineValue = string | number | boolean | Record<string, string> | null;

export interface EngineState {
  /** True when this deployment has no model API key and model-backed roles cannot run. */
  keyless: boolean;
  /** Engine-relative path → full file content. */
  files: Record<string, string>;
  /**
   * Engine-relative path → why it is NOT in `files` (oversized, not UTF-8, unreadable).
   * Never treat a path missing from `files` as an empty file: check here first, or an editor
   * offers a blank and the next save overwrites content that is still on disk.
   */
  skipped?: Record<string, string>;
  /** `<stage>.<key>` → resolved value. */
  values: Record<string, EngineValue>;
  /** `<stage>.<key>` → where the resolved value came from (env > engine > default). */
  resolution: Record<string, ResolutionOrigin>;
  version: { head: string | null; dirty: boolean };
}

export interface EngineHistoryEntry {
  sha: string;
  label: string;
  /** ISO timestamp. */
  at: string;
  /** Engine-relative paths this version touched. */
  files: string[];
}

/** All readable engine files as one historical commit held them. */
export interface EngineHistoryFiles {
  /** Full resolved commit sha, even when the request used an abbreviation. */
  sha: string;
  files: Record<string, string>;
}

/** One engine file read verbatim through `GET /v1/engine/file`. */
export interface EngineFile {
  path: string;
  content: string;
}

export interface EngineApplyChange {
  path: string;
  content: string;
}

export interface EngineApplyEffect {
  key: string;
  apply: ApplyKind;
}

export interface EngineApplyResult {
  sha: string;
  effects: EngineApplyEffect[];
}

/** One ordered catalog clause inside a model-visible prompt surface. */
export interface PromptSegment {
  key: string;
  label: Localized;
  /**
   * When the model actually receives this clause. `null` for a clause whose position in an
   * assembled prompt already answers that; a sentence for every clause of a fragment family
   * and every variant, where position answers nothing.
   */
  context: Localized | null;
  framework_text: string;
  override_text: string | null;
  placeholders: string[];
  shared_with: string[];
}

/**
 * One model-visible prompt, expressed as auditable catalog clauses — or one family of
 * clauses the model receives independently.
 *
 * `assembled`: the assembled strings are the bytes a composition function really produces.
 * `fragments`: they are empty, because the clauses are conditional alternatives and separate
 * emissions; concatenating them would show prose no model has ever received.
 */
export interface PromptSurface {
  id: string;
  group: string;
  kind: "assembled" | "fragments";
  title: Localized;
  summary: Localized;
  /** Registry-authored explanation when assembled text is still a runtime template. */
  note?: Localized | null;
  segments: PromptSegment[];
  assembled_framework: string;
  assembled_effective: string;
}

export interface EnginePrompts {
  surfaces: PromptSurface[];
}

export interface PromptRewriteRequest {
  key: string;
  intent: string;
  locale: "zh" | "en";
}

export interface PromptRewriteResult {
  draft: string;
  notes: string;
}
