/**
 * The source catalogue's own arithmetic: which day a source belongs to, what a filter lets
 * through, and what the remaining choices would cost.
 *
 * Two decisions are load-bearing here.
 *
 * FIRST, the timeline is CORPUS time, not ingest time. `created_at` is the wall clock of the
 * import; a replay of half a year of capture carries one single afternoon on every row, which
 * is why a density calendar built on it collapses into two lit cells. `occurred_on` is the day
 * the material happened, stamped in the subject's own zone at ingest, and it is what the list
 * order, the calendar and the range filter all read. A source without one falls back to its
 * ingest day and SAYS SO (`basis: "ingested"`) — the reader marks those rows rather than
 * quietly mixing two different meanings of "when".
 *
 * SECOND, this is catalogue lookup, not content retrieval. The query matches TITLES, on
 * metadata already in hand, so it answers while you type; finding a sentence inside the
 * material is what recall is for, and conflating the two would make both worse.
 *
 * Kept free of imports and of the DOM (the row shape is structural) so it can be transpiled
 * and tested on its own.
 */

/** The catalogue row this module reasons over — structurally `SourceSummary`. */
export interface CatalogueSource {
  source_id: string;
  kind: string;
  origin: string;
  source_class: string;
  title: string;
  /** The ingest wall clock, as an ISO instant. */
  created_at: string;
  /** The day the material happened (`YYYY-MM-DD`), when the source carries one. */
  occurred_on?: string | null;
}

/** Where a row's day came from: the material itself, or the moment we imported it. */
export type TimelineBasis = "occurred" | "ingested";

export interface SourceTimeline {
  /** `YYYY-MM-DD`, or null for a row whose ingest instant will not parse either. */
  date: string | null;
  basis: TimelineBasis;
}

export type FacetDimension = "kind" | "source_class" | "origin";

export interface SourceFilter {
  /** Whitespace-separated terms, ALL of which must appear in the title. */
  query: string;
  kinds: string[];
  classes: string[];
  origins: string[];
  /** Inclusive `YYYY-MM-DD` bounds on the timeline day. */
  from: string | null;
  to: string | null;
}

export interface FacetValue {
  value: string;
  count: number;
  selected: boolean;
}

export interface FacetGroup {
  dimension: FacetDimension;
  values: FacetValue[];
}

export interface DensityDay {
  date: string;
  count: number;
  kinds: Record<string, number>;
}

export const EMPTY_SOURCE_FILTER: SourceFilter = {
  query: "",
  kinds: [],
  classes: [],
  origins: [],
  from: null,
  to: null,
};

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MINUTE_MS = 60_000;

/** The dimensions, in the order the control bar offers them. */
export const FACET_DIMENSIONS: readonly FacetDimension[] = ["kind", "source_class", "origin"];

function pad(value: number, width: number): string {
  return String(value).padStart(width, "0");
}

/**
 * The calendar day an instant falls on, at a given UTC offset. The offset defaults to the
 * reader's own at that instant (so a DST boundary is honoured rather than averaged); tests
 * pass one explicitly, which is the only reason it is a parameter.
 */
export function dayKey(iso: string, offsetMinutes?: number): string | null {
  const instant = new Date(iso);
  const time = instant.getTime();
  if (!Number.isFinite(time)) return null;
  const offset = offsetMinutes ?? -instant.getTimezoneOffset();
  const shifted = new Date(time + offset * MINUTE_MS);
  return `${pad(shifted.getUTCFullYear(), 4)}-${pad(shifted.getUTCMonth() + 1, 2)}-${pad(
    shifted.getUTCDate(),
    2,
  )}`;
}

/** Corpus time when the source has it, the ingest day (marked as such) when it does not. */
export function sourceTimeline(
  source: CatalogueSource,
  offsetMinutes?: number,
): SourceTimeline {
  const occurred = (source.occurred_on ?? "").trim();
  if (DAY.test(occurred)) return { date: occurred, basis: "occurred" };
  return { date: dayKey(source.created_at, offsetMinutes), basis: "ingested" };
}

/* --------------------------------------------------------------------- the filter */

export function isSourceFilterActive(filter: SourceFilter): boolean {
  return (
    filter.query.trim() !== "" ||
    filter.kinds.length > 0 ||
    filter.classes.length > 0 ||
    filter.origins.length > 0 ||
    filter.from != null ||
    filter.to != null
  );
}

/** Add or remove one value from a multi-select dimension, keeping the order stable. */
export function toggleValue(values: readonly string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
}

/**
 * Title lookup: every whitespace-separated term must appear, case-folded. AND rather than
 * OR because a catalogue search is narrowing — two words the reader remembers should cut the
 * list down, not widen it.
 */
export function matchesQuery(title: string, query: string): boolean {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = title.toLocaleLowerCase();
  return terms.every((term) => haystack.includes(term));
}

/**
 * The bounds as an ordered pair. A reader who types the end date first means the range
 * between the two days, not the empty set.
 */
export function orderedRange(
  from: string | null,
  to: string | null,
): { from: string | null; to: string | null } {
  if (from != null && to != null && from > to) return { from: to, to: from };
  return { from, to };
}

function matchesDimension(values: readonly string[], value: string): boolean {
  return values.length === 0 || values.includes(value);
}

function matchesRange(date: string | null, filter: SourceFilter): boolean {
  const { from, to } = orderedRange(filter.from, filter.to);
  if (from == null && to == null) return true;
  // A row with no readable day cannot be claimed to fall inside a range.
  if (date == null) return false;
  if (from != null && date < from) return false;
  if (to != null && date > to) return false;
  return true;
}

export function matchesSourceFilter(
  source: CatalogueSource,
  filter: SourceFilter,
  offsetMinutes?: number,
): boolean {
  return (
    matchesQuery(source.title, filter.query) &&
    matchesDimension(filter.kinds, source.kind) &&
    matchesDimension(filter.classes, source.source_class) &&
    matchesDimension(filter.origins, source.origin) &&
    matchesRange(sourceTimeline(source, offsetMinutes).date, filter)
  );
}

export function filterSources<T extends CatalogueSource>(
  sources: readonly T[],
  filter: SourceFilter,
  offsetMinutes?: number,
): T[] {
  return sources.filter((source) => matchesSourceFilter(source, filter, offsetMinutes));
}

/**
 * Newest corpus day first. Ties break on the ingest instant and then the id, so a replay
 * that stamped one day across thousands of rows still has ONE order rather than whichever
 * one the last sort happened to produce.
 */
export function sortByTimeline<T extends CatalogueSource>(
  sources: readonly T[],
  offsetMinutes?: number,
): T[] {
  const keyed = sources.map((source) => ({
    source,
    date: sourceTimeline(source, offsetMinutes).date,
  }));
  keyed.sort((left, right) => {
    if (left.date !== right.date) {
      // A row with no readable day sorts last rather than to the top of the catalogue.
      if (left.date == null) return 1;
      if (right.date == null) return -1;
      return left.date < right.date ? 1 : -1;
    }
    if (left.source.created_at !== right.source.created_at) {
      return left.source.created_at < right.source.created_at ? 1 : -1;
    }
    return left.source.source_id.localeCompare(right.source.source_id);
  });
  return keyed.map((entry) => entry.source);
}

/* ---------------------------------------------------------------------- the facets */

function dimensionValue(source: CatalogueSource, dimension: FacetDimension): string {
  if (dimension === "kind") return source.kind;
  if (dimension === "origin") return source.origin;
  return source.source_class;
}

function selectionFor(filter: SourceFilter, dimension: FacetDimension): string[] {
  if (dimension === "kind") return filter.kinds;
  if (dimension === "origin") return filter.origins;
  return filter.classes;
}

export function withDimension(
  filter: SourceFilter,
  dimension: FacetDimension,
  values: string[],
): SourceFilter {
  if (dimension === "kind") return { ...filter, kinds: values };
  if (dimension === "origin") return { ...filter, origins: values };
  return { ...filter, classes: values };
}

/**
 * What each chip is worth, counted against every OTHER part of the filter. A chip therefore
 * reads as "click me and you get this many", which is the only count a reader can act on;
 * counting a dimension against its own selection would show every unselected chip as zero.
 *
 * A dimension holding a single value is dropped: a control that cannot divide the catalogue
 * is noise. It comes back the moment it is selected, so a chip can always be un-clicked.
 */
export function sourceFacets(
  sources: readonly CatalogueSource[],
  filter: SourceFilter,
  offsetMinutes?: number,
): FacetGroup[] {
  const groups: FacetGroup[] = [];
  for (const dimension of FACET_DIMENSIONS) {
    const selected = selectionFor(filter, dimension);
    const others = withDimension(filter, dimension, []);
    const counts = new Map<string, number>();
    for (const source of sources) {
      const value = dimensionValue(source, dimension);
      // Every value in this dimension is listed, even at zero: a chip that vanishes as you
      // narrow makes the catalogue look like it has fewer kinds than it does.
      if (!counts.has(value)) counts.set(value, 0);
      if (matchesSourceFilter(source, others, offsetMinutes)) {
        counts.set(value, counts.get(value)! + 1);
      }
    }
    if (counts.size < 2 && selected.length === 0) continue;
    const values = [...counts.entries()]
      .map(([value, count]) => ({ value, count, selected: selected.includes(value) }))
      .sort((left, right) =>
        left.count === right.count
          ? left.value.localeCompare(right.value)
          : right.count - left.count,
      );
    groups.push({ dimension, values });
  }
  return groups;
}

/* --------------------------------------------------------------------- the calendar */

/** Daily counts on the timeline day, ascending — the density calendar's input. */
export function sourceDensity(
  sources: readonly CatalogueSource[],
  offsetMinutes?: number,
): DensityDay[] {
  const byDate = new Map<string, DensityDay>();
  for (const source of sources) {
    const { date } = sourceTimeline(source, offsetMinutes);
    if (date == null) continue;
    let day = byDate.get(date);
    if (!day) {
      day = { date, count: 0, kinds: {} };
      byDate.set(date, day);
    }
    day.count += 1;
    day.kinds[source.kind] = (day.kinds[source.kind] ?? 0) + 1;
  }
  return [...byDate.values()].sort((left, right) => left.date.localeCompare(right.date));
}

/** The day the range is pinned to, when it is pinned to exactly one. */
export function selectedDay(filter: SourceFilter): string | null {
  const { from, to } = orderedRange(filter.from, filter.to);
  return from != null && from === to ? from : null;
}

/** Clicking a calendar cell pins that day; clicking the pinned day again lets go of it. */
export function toggleDay(filter: SourceFilter, date: string): SourceFilter {
  if (selectedDay(filter) === date) return { ...filter, from: null, to: null };
  return { ...filter, from: date, to: date };
}

/** The span the catalogue actually covers — the bounds the date fields offer. */
export function timelineBounds(
  sources: readonly CatalogueSource[],
  offsetMinutes?: number,
): { from: string | null; to: string | null } {
  let from: string | null = null;
  let to: string | null = null;
  for (const source of sources) {
    const { date } = sourceTimeline(source, offsetMinutes);
    if (date == null) continue;
    if (from == null || date < from) from = date;
    if (to == null || date > to) to = date;
  }
  return { from, to };
}
