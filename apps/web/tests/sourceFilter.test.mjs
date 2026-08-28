/**
 * The source catalogue's arithmetic.
 *
 * The fixture is shaped around the failure that motivated the module: a catalogue whose rows
 * were ALL ingested in one afternoon, but whose material spans months. Every timeline
 * assertion below would still pass on the broken behaviour if it read `created_at`, except
 * that it would put every row on the same day — which is exactly what the density calendar
 * showed before. The rows carry no domain vocabulary: they are framework kinds and framework
 * classes, with titles built out of the vocabulary of the archive itself.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/sourceFilter.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  EMPTY_SOURCE_FILTER,
  dayKey,
  filterSources,
  isSourceFilterActive,
  matchesQuery,
  matchesSourceFilter,
  orderedRange,
  selectedDay,
  sortByTimeline,
  sourceDensity,
  sourceFacets,
  sourceTimeline,
  timelineBounds,
  toggleDay,
  toggleValue,
  withDimension,
} = await import(moduleUrl);

/* ------------------------------------------------------------------- the fixture */

/** Every row shares one ingest afternoon; only `occurred_on` tells them apart. */
const INGESTED = "2026-07-30T16:05:22.000Z";

function row(id, title, occurredOn, extra = {}) {
  return {
    source_id: id,
    kind: "conversation",
    origin: "context_stream",
    source_class: "workstream",
    title,
    created_at: INGESTED,
    occurred_on: occurredOn,
    ...extra,
  };
}

const CATALOGUE = [
  row("s-1", "Weekly review · topics", "2026-01-09"),
  row("s-2", "Weekly review · people", "2026-03-14"),
  row("s-3", "Experiment log · retrieval sweep", "2026-07-29"),
  row("s-4", "Profile intake notes", "2026-07-29", { source_class: "reference" }),
  // A document that never got a corpus day: it can only be dated by its import.
  row("s-5", "Reference handbook", null, {
    kind: "document",
    origin: "upload",
    source_class: "reference",
  }),
];

/** Fixed at +00:00 so the ingest-day fallback is the same on every machine. */
const UTC = 0;

const filter = (patch) => ({ ...EMPTY_SOURCE_FILTER, ...patch });

/* ------------------------------------------------------------------ corpus time */

test("a source is dated by the material, and only falls back to the import", () => {
  assert.deepEqual(sourceTimeline(CATALOGUE[0], UTC), {
    date: "2026-01-09",
    basis: "occurred",
  });
  // The one row with no stamp lands on the ingest day AND is marked as such, so the reader
  // can tell a real January from a July import.
  assert.deepEqual(sourceTimeline(CATALOGUE[4], UTC), {
    date: "2026-07-30",
    basis: "ingested",
  });
});

test("a blank or malformed stamp is not a date", () => {
  for (const stamp of ["", "   ", "2026-7-9", "2026-01-09T00:00:00Z", "someday"]) {
    assert.equal(
      sourceTimeline(row("s-x", "t", stamp), UTC).basis,
      "ingested",
      `${JSON.stringify(stamp)} must not be taken for a day`,
    );
  }
});

test("the ingest day is read in the reader's own calendar, not in UTC", () => {
  // 23:40 UTC is already the next morning at +08:00 — the offset decides the day.
  assert.equal(dayKey("2026-07-30T23:40:00Z", 0), "2026-07-30");
  assert.equal(dayKey("2026-07-30T23:40:00Z", 480), "2026-07-31");
  assert.equal(dayKey("2026-07-30T02:10:00Z", -300), "2026-07-29");
  assert.equal(dayKey("not-a-time", 0), null);
});

test("an unreadable ingest instant leaves the row undated rather than guessing", () => {
  const broken = { ...row("s-b", "broken", null), created_at: "" };
  assert.deepEqual(sourceTimeline(broken, UTC), { date: null, basis: "ingested" });
  // …and an undated row cannot be claimed to fall inside a range.
  assert.equal(matchesSourceFilter(broken, filter({ from: "2026-01-01" }), UTC), false);
  assert.equal(matchesSourceFilter(broken, EMPTY_SOURCE_FILTER, UTC), true);
});

/* ---------------------------------------------------------------------- the order */

test("the catalogue reads newest material first, not newest import first", () => {
  const ordered = sortByTimeline(CATALOGUE, UTC).map((s) => s.source_id);
  // s-5 has only its import day (2026-07-30), which is genuinely the latest day here.
  assert.deepEqual(ordered, ["s-5", "s-3", "s-4", "s-2", "s-1"]);
});

test("rows sharing a day keep one stable order however they arrived", () => {
  const forward = sortByTimeline(CATALOGUE, UTC).map((s) => s.source_id);
  const reversed = sortByTimeline([...CATALOGUE].reverse(), UTC).map((s) => s.source_id);
  assert.deepEqual(forward, reversed);
});

test("an undated row sorts last instead of to the top", () => {
  const broken = { ...row("s-b", "broken", null), created_at: "" };
  const ordered = sortByTimeline([broken, ...CATALOGUE], UTC).map((s) => s.source_id);
  assert.equal(ordered[ordered.length - 1], "s-b");
});

/* ---------------------------------------------------------------------- the search */

test("the title search narrows on every term, in any order and any case", () => {
  assert.equal(matchesQuery("Weekly review · topics", "weekly"), true);
  assert.equal(matchesQuery("Weekly review · topics", "TOPICS weekly"), true);
  assert.equal(matchesQuery("Weekly review · topics", "weekly people"), false);
  // An empty or whitespace-only box is not a filter.
  assert.equal(matchesQuery("anything", ""), true);
  assert.equal(matchesQuery("anything", "   "), true);
});

test("the search reads titles only — it is catalogue lookup, not retrieval", () => {
  const hits = filterSources(CATALOGUE, filter({ query: "review" }), UTC);
  assert.deepEqual(hits.map((s) => s.source_id), ["s-1", "s-2"]);
  // The wire vocabulary a row carries is not searchable text.
  assert.deepEqual(filterSources(CATALOGUE, filter({ query: "conversation" }), UTC), []);
});

/* ---------------------------------------------------------------------- the chips */

test("chips are multi-select and additive within one dimension", () => {
  assert.deepEqual(toggleValue([], "document"), ["document"]);
  assert.deepEqual(toggleValue(["document"], "conversation"), ["document", "conversation"]);
  assert.deepEqual(toggleValue(["document", "conversation"], "document"), ["conversation"]);

  const both = filter({ kinds: ["conversation", "document"] });
  assert.equal(filterSources(CATALOGUE, both, UTC).length, CATALOGUE.length);
});

test("dimensions intersect: a class chip cuts across a kind chip", () => {
  const hits = filterSources(
    CATALOGUE,
    filter({ kinds: ["conversation"], classes: ["reference"] }),
    UTC,
  );
  assert.deepEqual(hits.map((s) => s.source_id), ["s-4"]);
});

test("a chip counts what clicking it would give, ignoring its own dimension", () => {
  const groups = sourceFacets(CATALOGUE, filter({ kinds: ["document"] }), UTC);
  const kinds = groups.find((g) => g.dimension === "kind");
  // Both kinds are still counted at their full weight: the kind selection is set aside for
  // its own chips, so "conversation 4" tells the reader what switching would cost.
  assert.deepEqual(
    kinds.values.map((v) => [v.value, v.count, v.selected]),
    [
      ["conversation", 4, false],
      ["document", 1, true],
    ],
  );
  // …while another dimension IS narrowed by the kind selection. The ORDER is the whole
  // catalogue's (workstream is the larger class), so a narrowing changes numbers, not places.
  const classes = groups.find((g) => g.dimension === "source_class");
  assert.deepEqual(
    classes.values.map((v) => [v.value, v.count]),
    [["workstream", 0], ["reference", 1]],
  );
});

test("a dimension that cannot divide the catalogue is not offered as a control", () => {
  const single = [row("s-a", "one", "2026-02-01"), row("s-b", "two", "2026-02-02")];
  assert.deepEqual(
    sourceFacets(single, EMPTY_SOURCE_FILTER, UTC).map((g) => g.dimension),
    [],
  );
  // …unless something in it is selected, or the chip could never be un-clicked.
  assert.deepEqual(
    sourceFacets(single, filter({ kinds: ["conversation"] }), UTC).map((g) => g.dimension),
    ["kind"],
  );
});

test("every dimension the catalogue holds is offered, in count order", () => {
  assert.deepEqual(
    sourceFacets(CATALOGUE, EMPTY_SOURCE_FILTER, UTC).map((g) => g.dimension),
    ["kind", "source_class", "origin"],
  );
  const [kinds] = sourceFacets(CATALOGUE, EMPTY_SOURCE_FILTER, UTC);
  assert.deepEqual(kinds.values.map((v) => v.value), ["conversation", "document"]);
});

test("chip order follows the catalogue, not the filter — clicking one never reshuffles them", () => {
  // The order is the WHOLE inventory's shape; only the numbers move under a selection. A row
  // that reordered itself moved the chip the reader was about to press next.
  const unfiltered = sourceFacets(CATALOGUE, EMPTY_SOURCE_FILTER, UTC);
  const narrowed = sourceFacets(CATALOGUE, filter({ classes: ["reference"] }), UTC);
  for (const dimension of ["kind", "source_class", "origin"]) {
    const before = unfiltered.find((g) => g.dimension === dimension);
    const after = narrowed.find((g) => g.dimension === dimension);
    assert.deepEqual(
      after.values.map((v) => v.value),
      before.values.map((v) => v.value),
      `${dimension} chips moved under a filter`,
    );
  }
  // …and the counts did narrow, or the assertion above would be vacuous.
  const kinds = narrowed.find((g) => g.dimension === "kind");
  assert.notDeepEqual(
    kinds.values.map((v) => v.count),
    unfiltered.find((g) => g.dimension === "kind").values.map((v) => v.count),
  );
});

test("withDimension writes back to the field the dimension owns", () => {
  assert.deepEqual(withDimension(EMPTY_SOURCE_FILTER, "kind", ["a"]).kinds, ["a"]);
  assert.deepEqual(withDimension(EMPTY_SOURCE_FILTER, "origin", ["a"]).origins, ["a"]);
  assert.deepEqual(withDimension(EMPTY_SOURCE_FILTER, "source_class", ["a"]).classes, ["a"]);
});

/* ----------------------------------------------------------------- the date range */

test("the range is inclusive at both ends and reads the corpus day", () => {
  const hits = filterSources(CATALOGUE, filter({ from: "2026-01-09", to: "2026-03-14" }), UTC);
  assert.deepEqual(hits.map((s) => s.source_id), ["s-1", "s-2"]);
  // A one-sided range is a legitimate half-open question.
  assert.deepEqual(
    filterSources(CATALOGUE, filter({ from: "2026-07-29" }), UTC).map((s) => s.source_id),
    ["s-3", "s-4", "s-5"],
  );
  assert.deepEqual(
    filterSources(CATALOGUE, filter({ to: "2026-01-09" }), UTC).map((s) => s.source_id),
    ["s-1"],
  );
});

test("a range typed end-first is the same range, not the empty set", () => {
  assert.deepEqual(orderedRange("2026-03-14", "2026-01-09"), {
    from: "2026-01-09",
    to: "2026-03-14",
  });
  const inverted = filterSources(
    CATALOGUE,
    filter({ from: "2026-03-14", to: "2026-01-09" }),
    UTC,
  );
  assert.deepEqual(inverted.map((s) => s.source_id), ["s-1", "s-2"]);
});

test("a calendar cell pins one day, and the same cell lets go of it", () => {
  const pinned = toggleDay(EMPTY_SOURCE_FILTER, "2026-07-29");
  assert.deepEqual([pinned.from, pinned.to], ["2026-07-29", "2026-07-29"]);
  assert.equal(selectedDay(pinned), "2026-07-29");
  assert.deepEqual(
    filterSources(CATALOGUE, pinned, UTC).map((s) => s.source_id),
    ["s-3", "s-4"],
  );

  const released = toggleDay(pinned, "2026-07-29");
  assert.deepEqual([released.from, released.to], [null, null]);
  // Another cell moves the pin rather than widening the range.
  assert.equal(selectedDay(toggleDay(pinned, "2026-01-09")), "2026-01-09");
  // A span of several days is not "a pinned day".
  assert.equal(selectedDay(filter({ from: "2026-01-09", to: "2026-03-14" })), null);
});

test("the range fields are offered the span the catalogue actually covers", () => {
  assert.deepEqual(timelineBounds(CATALOGUE, UTC), {
    from: "2026-01-09",
    to: "2026-07-30",
  });
  assert.deepEqual(timelineBounds([], UTC), { from: null, to: null });
});

/* ------------------------------------------------------------------- the calendar */

test("density is counted on corpus days, so months of material show as months", () => {
  const days = sourceDensity(CATALOGUE, UTC);
  assert.deepEqual(days.map((d) => d.date), [
    "2026-01-09",
    "2026-03-14",
    "2026-07-29",
    "2026-07-30",
  ]);
  assert.deepEqual(days[2], {
    date: "2026-07-29",
    count: 2,
    kinds: { conversation: 2 },
  });
  // The one import-dated row is the only thing on the import day — the old calendar put all
  // five here.
  assert.deepEqual(days[3], { date: "2026-07-30", count: 1, kinds: { document: 1 } });
});

/* ------------------------------------------------------------------- the clear key */

test("a filter is active when any one part of it is set, and clearing means all of it", () => {
  assert.equal(isSourceFilterActive(EMPTY_SOURCE_FILTER), false);
  assert.equal(isSourceFilterActive(filter({ query: "  " })), false);
  for (const patch of [
    { query: "a" },
    { kinds: ["document"] },
    { classes: ["reference"] },
    { origins: ["upload"] },
    { from: "2026-01-01" },
    { to: "2026-01-01" },
  ]) {
    assert.equal(isSourceFilterActive(filter(patch)), true, JSON.stringify(patch));
  }
  assert.equal(filterSources(CATALOGUE, EMPTY_SOURCE_FILTER, UTC).length, CATALOGUE.length);
});
