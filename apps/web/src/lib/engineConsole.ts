/**
 * Engine Console pure logic: draft-aware value resolution, edge-condition evaluation, and
 * the draft → pending-changes → apply-payload derivation. No React, no stores — the zustand
 * draft store in `engine/draft.ts` holds plain `DraftData`, and every derivation here is a
 * function of (schema, state, draft) so the node test harness can drive them directly.
 */
import type {
  ApplyKind,
  EngineEdge,
  EngineKnob,
  EngineSchema,
  EngineStage,
  EngineState,
  EngineValue,
  Localized,
  ResolutionOrigin,
} from "@/engine/types";
import {
  getOverlayMap,
  getYamlScalar,
  removeOverlayEntry,
  setOverlayEntry,
  setYamlScalar,
  unquoteYamlScalar,
} from "./engineYaml";

/** Scalar knob values as the draft carries them (documents/overlays travel differently). */
export type ScalarValue = string | number | boolean;

/**
 * The draft, as plain data. `values` is keyed `<stage>.<key>`; `files` holds whole-file
 * replacements for document knobs; `overlays` holds catalog-key → replacement clause, with
 * null marking a removal.
 */
export interface DraftData {
  values: Record<string, ScalarValue>;
  files: Record<string, string>;
  overlays: Record<string, string | null>;
}

export const EMPTY_DRAFT: DraftData = { values: {}, files: {}, overlays: {} };

export function knobRef(stageId: string, knobKey: string): string {
  return `${stageId}.${knobKey}`;
}

/** Schema content arrives bilingual; pick the active locale with an English fallback. */
export function pickLocalized(text: Localized, locale: string): string {
  if (locale === "zh" && text.zh) return text.zh;
  return text.en || text.zh;
}

/** The value a knob shows right now: draft override → resolved state → schema default. */
export function knobValue(
  state: EngineState,
  draft: DraftData,
  stageId: string,
  knob: EngineKnob,
): EngineValue | undefined {
  const ref = knobRef(stageId, knob.key);
  if (ref in draft.values) return draft.values[ref];
  if (ref in state.values) return state.values[ref];
  return knob.default as EngineValue | undefined;
}

/** state.values with the draft's scalar overrides folded in — what the map reacts to. */
export function effectiveValues(
  state: EngineState,
  draft: DraftData,
): Record<string, EngineValue> {
  return { ...state.values, ...draft.values };
}

/** An edge is active iff it is unconditional or its `<stage>.<key>` condition is truthy. */
export function isEdgeActive(
  edge: EngineEdge,
  values: Record<string, EngineValue>,
): boolean {
  if (!edge.condition) return true;
  return Boolean(values[edge.condition]);
}

/** Coerce a raw YAML scalar back into the knob's declared type. */
export function parseYamlScalar(raw: string, knob: EngineKnob): ScalarValue {
  if (knob.type === "bool") return unquoteYamlScalar(raw) === "true";
  if (knob.type === "int") {
    const n = Number(unquoteYamlScalar(raw));
    return Number.isFinite(n) ? n : 0;
  }
  // Strings are written quoted (see engineYaml.quoteYamlString), so reading one back means
  // undoing that — otherwise an empty value would show in the editor as `""`.
  return unquoteYamlScalar(raw);
}

/* ----------------------------------------------------------- pending changes */

export interface PendingKnobChange {
  kind: "knob";
  /** `<stage>.<key>`. */
  key: string;
  path: string;
  oldValue: EngineValue | undefined;
  newValue: ScalarValue;
  apply: ApplyKind;
}

export interface PendingDocumentChange {
  kind: "document";
  key: string;
  path: string;
  apply: ApplyKind;
}

export interface PendingOverlayChange {
  kind: "overlay";
  key: string;
  path: string;
  /** Catalog key inside the overlay map. */
  catalogKey: string;
  /** The replacement clause; null = the override is removed. */
  clause: string | null;
  apply: ApplyKind;
}

export interface PendingFileChange {
  kind: "file";
  /** Raw whole-file restore; the path is the review identity. */
  key: string;
  path: string;
  /** Null for an engine file such as README.md that has no runtime knob. */
  apply: ApplyKind | null;
}

export type PendingChange =
  | PendingKnobChange
  | PendingDocumentChange
  | PendingOverlayChange
  | PendingFileChange;

function isScalarKnob(knob: EngineKnob): boolean {
  return knob.type === "enum" || knob.type === "bool" || knob.type === "int" || knob.type === "string";
}

/**
 * The human-facing change list: one row per edited knob / document / overlay entry, with
 * old → new and the blast radius. This is what the review sheet renders.
 */
export function pendingChanges(
  schema: EngineSchema,
  state: EngineState,
  draft: DraftData,
): PendingChange[] {
  const rows: PendingChange[] = [];
  for (const stage of schema.stages) {
    for (const knob of stage.knobs) {
      const ref = knobRef(stage.id, knob.key);
      if (isScalarKnob(knob)) {
        if (!(ref in draft.values)) continue;
        const newValue = draft.values[ref];
        const oldValue = state.values[ref] ?? (knob.default as EngineValue | undefined);
        if (oldValue === newValue) continue;
        rows.push({
          kind: "knob",
          key: ref,
          path: stage.file,
          oldValue,
          newValue,
          apply: knob.apply,
        });
      } else if (knob.type === "document") {
        const content = draft.files[stage.file];
        if (content == null || content === state.files[stage.file]) continue;
        rows.push({ kind: "document", key: ref, path: stage.file, apply: knob.apply });
      }
    }
  }
  const overlayStage = schema.stages.find((s) =>
    s.knobs.some((k) => k.type === "overlay_map"),
  );
  const overlayKnob = overlayStage?.knobs.find((k) => k.type === "overlay_map");
  if (overlayStage && overlayKnob) {
    const currentOverlays = getOverlayMap(state.files[overlayStage.file] ?? "");
    for (const [catalogKey, clause] of Object.entries(draft.overlays)) {
      if (clause == null ? !(catalogKey in currentOverlays) : currentOverlays[catalogKey] === clause) {
        continue;
      }
      rows.push({
        kind: "overlay",
        key: knobRef(overlayStage.id, overlayKnob.key),
        path: overlayStage.file,
        catalogKey,
        clause,
        apply: overlayKnob.apply,
      });
    }
  }
  const documentPaths = new Set(
    schema.stages
      .filter((stage) => stage.knobs.some((knob) => knob.type === "document"))
      .map((stage) => stage.file),
  );
  for (const [path, content] of Object.entries(draft.files)) {
    if (content === state.files[path] || documentPaths.has(path)) continue;
    const stage = schema.stages.find((candidate) => candidate.file === path);
    rows.push({
      kind: "file",
      key: path,
      path,
      apply: stage?.knobs[0]?.apply ?? null,
    });
  }
  return rows;
}

/**
 * The wire payload for POST /v1/engine/apply: draft edits folded into whole-file contents.
 * Scalar edits on the same file compose (challenge.yaml carries four knobs); overlay edits
 * compose over the base file. Only files whose content actually changes are returned.
 */
export function buildApplyPayload(
  schema: EngineSchema,
  state: EngineState,
  draft: DraftData,
): { path: string; content: string }[] {
  const contents: Record<string, string> = { ...state.files, ...draft.files };
  for (const stage of schema.stages) {
    for (const knob of stage.knobs) {
      if (!isScalarKnob(knob)) continue;
      const ref = knobRef(stage.id, knob.key);
      if (!(ref in draft.values)) continue;
      const oldValue = state.values[ref] ?? (knob.default as EngineValue | undefined);
      if (oldValue === draft.values[ref]) continue;
      const base = contents[stage.file] ?? "";
      contents[stage.file] = setYamlScalar(base, knob.key, draft.values[ref]);
    }
  }
  const overlayStage = schema.stages.find((s) =>
    s.knobs.some((k) => k.type === "overlay_map"),
  );
  if (overlayStage && Object.keys(draft.overlays).length > 0) {
    let content = contents[overlayStage.file] ?? "";
    for (const [catalogKey, clause] of Object.entries(draft.overlays)) {
      content =
        clause == null
          ? removeOverlayEntry(content, catalogKey)
          : setOverlayEntry(content, catalogKey, clause);
    }
    contents[overlayStage.file] = content;
  }
  return Object.entries(contents)
    .filter(([path, content]) => content !== (state.files[path] ?? ""))
    .map(([path, content]) => ({ path, content }));
}

/** Historical files that would actually replace current HEAD, in stable path order. */
export function changedHistoryFiles(
  historical: Record<string, string>,
  current: Record<string, string>,
): [string, string][] {
  return Object.entries(historical)
    .filter(([path, content]) => content !== current[path])
    .sort(([a], [b]) => a.localeCompare(b));
}

/**
 * What an apply reports back: one effect row per touched knob. Falls back to reading the
 * knob values out of the new file contents so it also works against a bare path list.
 */
export function applyEffects(
  schema: EngineSchema,
  changes: { path: string; content: string }[],
): { key: string; apply: ApplyKind }[] {
  const effects: { key: string; apply: ApplyKind }[] = [];
  const seen = new Set<string>();
  for (const change of changes) {
    for (const stage of schema.stages) {
      if (stage.file !== change.path) continue;
      for (const knob of stage.knobs) {
        const ref = knobRef(stage.id, knob.key);
        if (seen.has(ref)) continue;
        if (knob.type === "document" || knob.type === "overlay_map") {
          seen.add(ref);
          effects.push({ key: ref, apply: knob.apply });
        } else {
          const oldRaw = getYamlScalar(change.content, knob.key);
          if (oldRaw == null) continue;
          seen.add(ref);
          effects.push({ key: ref, apply: knob.apply });
        }
      }
    }
  }
  return effects;
}

/* ----------------------------------------------------------- derived lookups */

export function findStage(schema: EngineSchema, id: string): EngineStage | undefined {
  return schema.stages.find((s) => s.id === id);
}

/** The resolution badge for a knob, once an edit lands it always reads "engine". */
export function knobResolution(
  state: EngineState,
  stageId: string,
  knob: EngineKnob,
): ResolutionOrigin {
  return state.resolution[knobRef(stageId, knob.key)] ?? "default";
}

/**
 * The engine file a `/state` failure is about, when its message names one.
 *
 * The service always puts the engine-relative path in the detail
 * (`recall/recall.yaml is not valid YAML: …`), so matching the schema's own file list against
 * the message is exact — no parsing of the wording, and an unrecognized message yields null
 * rather than a guess. This is what lets the repair drawer open already pointed at the file.
 */
export function pathFromError(
  schema: EngineSchema | null,
  error: string | null,
): string | null {
  if (!schema || !error) return null;
  return schema.stages.map((s) => s.file).find((file) => error.includes(file)) ?? null;
}

/** Overlay overrides currently in force: file contents with the draft folded over them. */
export function effectiveOverlays(
  state: EngineState,
  draft: DraftData,
  path: string,
): Record<string, string> {
  const base = getOverlayMap(state.files[path] ?? "");
  for (const [catalogKey, clause] of Object.entries(draft.overlays)) {
    if (clause == null) delete base[catalogKey];
    else base[catalogKey] = clause;
  }
  return base;
}
