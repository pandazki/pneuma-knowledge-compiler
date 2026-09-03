/**
 * The request guard: a late response for a previous token is ignored.
 *
 * The finding this covers is `I1` at the last inch. The archive drawer and the archive
 * proposal dialog both fetch per user; a `GET /archive` or `POST /archive/proposals` issued
 * for the library the reader has just left can resolve AFTER the switch and paint the
 * previous user's rows over the current one's. The tests below play that race out in-process
 * — two overlapping requests resolved out of order — and assert that only the newest one is
 * allowed to write.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/requestGuard.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const { makeGuard } = await import(moduleUrl);

/** A view that keeps one piece of per-user state behind one guard. */
function view() {
  const guard = makeGuard();
  const state = { user: null };
  return {
    /** Issue a request for `user`; returns the settle function the "network" calls back. */
    request(user) {
      const token = guard.next();
      return {
        resolve(payload) {
          if (!guard.isCurrent(token)) return false;
          state.user = user;
          state.payload = payload;
          return true;
        },
        rejected() {
          return guard.isCurrent(token);
        },
      };
    },
    leave() {
      guard.invalidate();
    },
    state,
  };
}

test("a late response for a previous token is ignored", () => {
  const v = view();
  const forAda = v.request("ada");
  const forBo = v.request("bo"); // the reader switched library

  assert.equal(forBo.resolve("bo rows"), true, "the current request writes");
  assert.equal(
    forAda.resolve("ada rows"),
    false,
    "the previous user's answer, arriving second, writes nothing",
  );
  assert.deepEqual(v.state, { user: "bo", payload: "bo rows" });
});

test("order of arrival does not matter — identity does", () => {
  const v = view();
  const forAda = v.request("ada");
  const forBo = v.request("bo");

  // Same switch, the other arrival order: the stale answer lands FIRST and is still dropped.
  assert.equal(forAda.resolve("ada rows"), false);
  assert.deepEqual(v.state, { user: null }, "nothing was painted in between");
  assert.equal(forBo.resolve("bo rows"), true);
  assert.equal(v.state.user, "bo");
});

test("a token stays current until another request replaces it", () => {
  const guard = makeGuard();
  const token = guard.next();
  assert.equal(guard.isCurrent(token), true);
  assert.equal(guard.isCurrent(token), true, "asking twice does not retire it");
  const later = guard.next();
  assert.equal(guard.isCurrent(token), false);
  assert.equal(guard.isCurrent(later), true);
});

test("no token but the guard's own is ever current", () => {
  const guard = makeGuard();
  assert.equal(
    guard.isCurrent(Symbol("request")),
    false,
    "nothing is current before the first request",
  );
  const token = guard.next();
  assert.equal(guard.isCurrent(Symbol("request")), false, "a look-alike token is not the token");
  assert.equal(guard.isCurrent(token), true);
});

test("invalidate retires the in-flight request without starting one", () => {
  const v = view();
  const forAda = v.request("ada");
  v.leave(); // unmount, or the drawer closing: the request is aborted

  assert.equal(
    forAda.rejected(),
    false,
    "the abort's own rejection is not allowed to write an error either",
  );
  assert.equal(forAda.resolve("ada rows"), false);
  assert.deepEqual(v.state, { user: null });

  // …and the next request the view makes is current again.
  const forBo = v.request("bo");
  assert.equal(forBo.resolve("bo rows"), true);
  assert.equal(v.state.user, "bo");
});
