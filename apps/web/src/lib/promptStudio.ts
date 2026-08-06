import type { PromptSegment, PromptSurface } from "@/engine/types";

export type PromptPreviewMode = "framework" | "effective";

export interface PromptSurfaceGroup {
  group: string;
  surfaces: PromptSurface[];
}

export interface PromptTextToken {
  kind: "text" | "placeholder";
  value: string;
  name?: string;
}

export interface PromptDiffPart {
  kind: "same" | "added" | "removed";
  value: string;
}

export interface PromptPreviewPart {
  kind: "text" | "segment";
  value: string;
  start: number;
  end: number;
  segment?: PromptSegment;
}

export interface PromptPreview {
  text: string;
  parts: PromptPreviewPart[];
}

/** The current overlay map already includes both engine state and the local engine draft. */
export function segmentOverride(
  segment: PromptSegment,
  overlays: Record<string, string>,
): string | null {
  if (Object.prototype.hasOwnProperty.call(overlays, segment.key)) return overlays[segment.key];
  return null;
}

export function segmentText(
  segment: PromptSegment,
  overlays: Record<string, string>,
  mode: PromptPreviewMode,
): string {
  if (mode === "framework") return segment.framework_text;
  return segmentOverride(segment, overlays) ?? segment.framework_text;
}

/**
 * A fragment family has no assembled form: its clauses are conditional alternatives and
 * separate emissions, so there is nothing to preview, nothing to toggle, and no notion of
 * "the branch this rendering did not take". Every view below routes on this.
 */
export function isFragmentFamily(surface: PromptSurface): boolean {
  return surface.kind === "fragments";
}

/**
 * The API deliberately exposes assembled bytes rather than the registry's private role
 * metadata. Clauses that occur verbatim, in registry order, participate in this rendering;
 * ordered matching avoids mistaking a tiny variant such as `", "` for unrelated punctuation
 * earlier in the assembly. The remaining clauses are browsable variants for another branch.
 *
 * In a fragment family every clause is first-class — none of them is a variant of a
 * rendering, because there is no rendering.
 */
export function segmentInCurrentRendering(
  surface: PromptSurface,
  segment: PromptSegment,
): boolean {
  if (isFragmentFamily(surface)) return true;
  let cursor = 0;
  for (const candidate of surface.segments) {
    if (candidate.framework_text.length === 0) continue;
    const index = surface.assembled_framework.indexOf(candidate.framework_text, cursor);
    if (index === -1) continue;
    if (candidate.key === segment.key) return true;
    cursor = index + candidate.framework_text.length;
  }
  return false;
}

function hasOwn<T extends object>(value: T, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

/**
 * Keep the server assembly authoritative. Effective mode only patches client-side draft
 * deltas into the bytes the server assembled; variant clauses naturally have no match and
 * therefore cannot leak into the current rendering.
 */
export function assembledPrompt(
  surface: PromptSurface,
  draftOverlays: Record<string, string | null>,
  mode: PromptPreviewMode,
): string {
  if (isFragmentFamily(surface)) return "";
  if (mode === "framework") return surface.assembled_framework;

  let assembled = surface.assembled_effective;
  let cursor = 0;
  for (const segment of surface.segments) {
    if (!segmentInCurrentRendering(surface, segment)) continue;

    const current = segment.override_text ?? segment.framework_text;
    if (current.length === 0) continue;
    const index = assembled.indexOf(current, cursor);
    if (index === -1) continue;

    const replacement = hasOwn(draftOverlays, segment.key)
      ? draftOverlays[segment.key] ?? segment.framework_text
      : current;
    if (replacement !== current) {
      assembled = assembled.slice(0, index) + replacement + assembled.slice(index + current.length);
    }
    cursor = index + replacement.length;
  }
  return assembled;
}

function previewSegmentText(
  segment: PromptSegment,
  draftOverlays: Record<string, string | null>,
  mode: PromptPreviewMode,
): string {
  if (mode === "framework") return segment.framework_text;
  if (hasOwn(draftOverlays, segment.key)) {
    return draftOverlays[segment.key] ?? segment.framework_text;
  }
  return segment.override_text ?? segment.framework_text;
}

/** Split the exact assembled bytes at located clause offsets for interactive hairlines. */
export function promptPreview(
  surface: PromptSurface,
  draftOverlays: Record<string, string | null>,
  mode: PromptPreviewMode,
): PromptPreview {
  const text = assembledPrompt(surface, draftOverlays, mode);
  const ranges: PromptPreviewPart[] = [];
  let searchFrom = 0;

  for (const segment of surface.segments) {
    if (!segmentInCurrentRendering(surface, segment)) continue;
    const value = previewSegmentText(segment, draftOverlays, mode);
    if (value.length === 0) continue;
    const start = text.indexOf(value, searchFrom);
    if (start === -1) continue;
    const end = start + value.length;
    ranges.push({ kind: "segment", value, start, end, segment });
    searchFrom = end;
  }

  const parts: PromptPreviewPart[] = [];
  let cursor = 0;
  for (const range of ranges) {
    if (range.start > cursor) {
      parts.push({
        kind: "text",
        value: text.slice(cursor, range.start),
        start: cursor,
        end: range.start,
      });
    }
    parts.push(range);
    cursor = range.end;
  }
  if (cursor < text.length || parts.length === 0) {
    parts.push({ kind: "text", value: text.slice(cursor), start: cursor, end: text.length });
  }
  return { text, parts };
}

export function surfaceOverrideCount(
  surface: PromptSurface,
  overlays: Record<string, string>,
): number {
  return new Set(
    surface.segments
      .filter((segment) => segmentOverride(segment, overlays) !== null)
      .map((segment) => segment.key),
  ).size;
}

/** Count catalog keys once per lifecycle group, even when a clause is shared by surfaces. */
export function promptGroupOverrideCount(
  group: PromptSurfaceGroup,
  overlays: Record<string, string>,
): number {
  return new Set(
    group.surfaces.flatMap((surface) =>
      surface.segments
        .filter((segment) => segmentOverride(segment, overlays) !== null)
        .map((segment) => segment.key),
    ),
  ).size;
}

/** Start with relevant branches open; later expansion choices remain component-owned state. */
export function defaultExpandedPromptGroups(
  groups: PromptSurfaceGroup[],
  overlays: Record<string, string>,
  selectedSurfaceId: string | null,
): string[] {
  const selectedGroup = groups.find((group) =>
    group.surfaces.some((surface) => surface.id === selectedSurfaceId),
  )?.group;
  return groups
    .filter(
      (group) =>
        group.group === selectedGroup || promptGroupOverrideCount(group, overlays) > 0,
    )
    .map((group) => group.group);
}

/** Preserve registry order: it is lifecycle order, not an alphabetic label sort. */
export function groupPromptSurfaces(surfaces: PromptSurface[]): PromptSurfaceGroup[] {
  const groups = new Map<string, PromptSurface[]>();
  for (const surface of surfaces) {
    const group = groups.get(surface.group) ?? [];
    group.push(surface);
    groups.set(surface.group, group);
  }
  return [...groups].map(([group, groupedSurfaces]) => ({
    group,
    surfaces: groupedSurfaces,
  }));
}

const SLOT = /\{([A-Za-z_][\w]*)(?:![rsa])?(?::[^{}]*)?\}/g;

export function presentPlaceholders(text: string): Set<string> {
  return new Set([...text.matchAll(SLOT)].map((match) => match[1]));
}

export function missingPlaceholders(text: string, required: string[]): string[] {
  const present = presentPlaceholders(text);
  return required.filter((name) => !present.has(name));
}

/** Split known format slots from verbatim prompt text so the view can render them as chips. */
export function tokenizePromptText(text: string, placeholders: string[]): PromptTextToken[] {
  if (placeholders.length === 0) return [{ kind: "text", value: text }];
  const known = new Set(placeholders);
  const tokens: PromptTextToken[] = [];
  let cursor = 0;
  for (const match of text.matchAll(SLOT)) {
    const index = match.index ?? 0;
    if (!known.has(match[1])) continue;
    if (index > cursor) tokens.push({ kind: "text", value: text.slice(cursor, index) });
    tokens.push({ kind: "placeholder", value: match[0], name: match[1] });
    cursor = index + match[0].length;
  }
  if (cursor < text.length) tokens.push({ kind: "text", value: text.slice(cursor) });
  return tokens.length > 0 ? tokens : [{ kind: "text", value: text }];
}

function diffTokens(text: string): string[] {
  return text.match(/\s+|[\p{L}\p{N}_{}[\].:/-]+|./gu) ?? [];
}

function coalesceDiff(parts: PromptDiffPart[]): PromptDiffPart[] {
  const result: PromptDiffPart[] = [];
  for (const part of parts) {
    const last = result[result.length - 1];
    if (last?.kind === part.kind) last.value += part.value;
    else result.push({ ...part });
  }
  return result;
}

/** A compact word/character diff for one clause; large clauses degrade to a safe whole-text diff. */
export function diffPromptText(original: string, draft: string): PromptDiffPart[] {
  if (original === draft) return [{ kind: "same", value: original }];
  const before = diffTokens(original);
  const after = diffTokens(draft);
  if (before.length * after.length > 40_000) {
    return [
      { kind: "removed", value: original },
      { kind: "added", value: draft },
    ];
  }

  const table = Array.from({ length: before.length + 1 }, () =>
    new Uint16Array(after.length + 1),
  );
  for (let i = before.length - 1; i >= 0; i -= 1) {
    for (let j = after.length - 1; j >= 0; j -= 1) {
      table[i][j] =
        before[i] === after[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const parts: PromptDiffPart[] = [];
  let i = 0;
  let j = 0;
  while (i < before.length || j < after.length) {
    if (i < before.length && j < after.length && before[i] === after[j]) {
      parts.push({ kind: "same", value: before[i] });
      i += 1;
      j += 1;
    } else if (j < after.length && (i === before.length || table[i][j + 1] >= table[i + 1][j])) {
      parts.push({ kind: "added", value: after[j] });
      j += 1;
    } else {
      parts.push({ kind: "removed", value: before[i] });
      i += 1;
    }
  }
  return coalesceDiff(parts);
}
