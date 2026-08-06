/**
 * The Engine Console draft: every edit lands here first and NOTHING touches the engine
 * files until review → apply. Plain `DraftData` in a small zustand store, so all
 * derivations (`lib/engineConsole.ts`) stay pure and the store stays a dumb container.
 */
import { create } from "zustand";
import type { DraftData, ScalarValue } from "@/lib/engineConsole";

export interface EngineDraftStore extends DraftData {
  /** Set (or, passing the resolved value back, re-set) a scalar knob, keyed `<stage>.<key>`. */
  setValue: (ref: string, value: ScalarValue) => void;
  /** Stage a whole-file replacement (document knobs: contract, persona profile). */
  setFile: (path: string, content: string) => void;
  /** Replace every pending edit with a historical set of whole-file replacements. */
  replaceWithFiles: (files: Record<string, string>) => void;
  /** Stage an overlay replacement clause for a catalog key. */
  setOverlay: (catalogKey: string, clause: string) => void;
  /** Stage the removal of an overlay override. */
  removeOverlay: (catalogKey: string) => void;
  clear: () => void;
}

export const useEngineDraft = create<EngineDraftStore>((set) => ({
  values: {},
  files: {},
  overlays: {},
  setValue: (ref, value) =>
    set((s) => ({ values: { ...s.values, [ref]: value } })),
  setFile: (path, content) =>
    set((s) => ({ files: { ...s.files, [path]: content } })),
  replaceWithFiles: (files) =>
    set({ values: {}, files: { ...files }, overlays: {} }),
  setOverlay: (catalogKey, clause) =>
    set((s) => ({ overlays: { ...s.overlays, [catalogKey]: clause } })),
  removeOverlay: (catalogKey) =>
    set((s) => ({ overlays: { ...s.overlays, [catalogKey]: null } })),
  clear: () => set({ values: {}, files: {}, overlays: {} }),
}));

/** Number of staged edits — the header's quiet draft indicator. */
export function draftCount(draft: DraftData): number {
  return (
    Object.keys(draft.values).length +
    Object.keys(draft.files).length +
    Object.keys(draft.overlays).length
  );
}
