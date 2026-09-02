/**
 * The consultation ledger's loading discipline: a response proves it is still the current
 * query before it writes anything.
 *
 * `fetch` cannot be un-sent, so the guard is a generation counter rather than a
 * cancellation. What it defends is the isolation invariant at the one place a reader would
 * believe it least: switch library while a request is in flight, and without the guard the
 * slower response renders the PREVIOUS tenant's questions under the new library's name.
 * The same applies to a filter change, and to a load-more that comes back after either.
 *
 * Every test below resolves two requests OUT OF ORDER on purpose — the ordering a real
 * network produces by itself and a test never does unless it is asked to.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/views/consultations/listLoading.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { createQueryOwner, loadFirstPage, loadNextPage } = await import(moduleUrl);

/** A list as the view holds it, with the four writes the loaders are allowed to make. */
function makeSink() {
  const state = { items: [], total: 0, cursor: null, error: null, loading: false };
  return {
    state,
    setLoading: (v) => {
      state.loading = v;
    },
    setError: (m) => {
      state.error = m;
    },
    replace: (items, total, cursor) => {
      state.items = items;
      state.total = total;
      state.cursor = cursor;
    },
    append: (items, cursor) => {
      state.items = [...state.items, ...items];
      state.cursor = cursor;
    },
  };
}

const page = (ids, cursor = null) => ({
  items: ids.map((id) => ({ consultation_id: id })),
  page: { total: ids.length, next_cursor: cursor },
});

/** A fetch that hands back a resolver, so the test decides which response lands first. */
function deferred() {
  let settle;
  const promise = new Promise((resolve, reject) => {
    settle = { resolve, reject };
  });
  return { promise, ...settle };
}

const ids = (sink) => sink.state.items.map((i) => i.consultation_id);

test("a slow response for the previous library never lands on the new one's list", async () => {
  const owner = createQueryOwner();
  const sink = makeSink();
  const mei = deferred();
  const bao = deferred();

  const first = loadFirstPage(owner, () => mei.promise, { limit: 25 }, sink);
  const second = loadFirstPage(owner, () => bao.promise, { limit: 25 }, sink);

  // The new library answers first; the old one's request is still out there.
  bao.resolve(page(["k-bao-1", "k-bao-2"]));
  await second;
  mei.resolve(page(["k-mei-1"]));
  await first;

  assert.deepEqual(ids(sink), ["k-bao-1", "k-bao-2"]);
  // …and the stale response does not end the loading state either: it is not its to end.
  assert.equal(sink.state.loading, false);
});

test("a stale request's FAILURE is not reported over a list that answered fine", async () => {
  const owner = createQueryOwner();
  const sink = makeSink();
  const stale = deferred();
  const fresh = deferred();

  const first = loadFirstPage(owner, () => stale.promise, { limit: 25 }, sink);
  const second = loadFirstPage(owner, () => fresh.promise, { limit: 25 }, sink);
  fresh.resolve(page(["k-1"]));
  await second;
  stale.reject(new Error("the network gave up on the query nobody is showing"));
  await first;

  assert.equal(sink.state.error, null);
  assert.deepEqual(ids(sink), ["k-1"]);
});

test("a load-more that comes back after the filters changed is dropped, not appended", async () => {
  const owner = createQueryOwner();
  const sink = makeSink();

  await loadFirstPage(owner, async () => page(["k-1", "k-2"], "cursor-1"), { limit: 25 }, sink);

  // The reader clicks Load more, then changes a filter before that page arrives.
  const more = deferred();
  const appending = loadNextPage(owner, () => more.promise, { cursor: "cursor-1" }, sink);
  await loadFirstPage(owner, async () => page(["k-9"]), { limit: 25, miss: true }, sink);
  more.resolve(page(["k-3", "k-4"]));
  await appending;

  assert.deepEqual(ids(sink), ["k-9"]);
  assert.equal(sink.state.cursor, null);
});

test("a load-more for the query that still owns the list does append", async () => {
  const owner = createQueryOwner();
  const sink = makeSink();

  await loadFirstPage(owner, async () => page(["k-1"], "cursor-1"), { limit: 25 }, sink);
  await loadNextPage(owner, async () => page(["k-2"], null), { cursor: "cursor-1" }, sink);

  assert.deepEqual(ids(sink), ["k-1", "k-2"]);
  assert.equal(sink.state.cursor, null);
});

test("without the guard the same interleaving does leak — the counter is what stops it", async () => {
  // The pre-fix view had no generation at all, which is exactly an owner that says yes to
  // everyone. Run the first scenario against one, and the previous library's questions
  // land under the new library's name.
  const everyoneOwns = { claim: () => 0, token: () => 0, holds: () => true };
  const sink = makeSink();
  const mei = deferred();
  const bao = deferred();

  const first = loadFirstPage(everyoneOwns, () => mei.promise, { limit: 25 }, sink);
  const second = loadFirstPage(everyoneOwns, () => bao.promise, { limit: 25 }, sink);
  bao.resolve(page(["k-bao-1"]));
  await second;
  mei.resolve(page(["k-mei-1"]));
  await first;

  assert.deepEqual(ids(sink), ["k-mei-1"]);
});
