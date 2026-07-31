/**
 * The Canonical contents tree's folding policy: what starts folded at a 95-document scale,
 * and what the reader's own clicks override.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { transformWithEsbuild } from "vite";

const sourceUrl = new URL("../src/lib/documentTree.ts", import.meta.url);
const sourceText = await readFile(sourceUrl, "utf8");
const transformed = await transformWithEsbuild(sourceText, sourceUrl.pathname, {
  loader: "ts",
  format: "esm",
  target: "es2022",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString("base64")}`;
const {
  TOC_COLLAPSE_THRESHOLD,
  collapsedByDefault,
  defaultCollapsedDirs,
  dirFileCount,
  isDirOpen,
} = await import(moduleUrl);

/** files("a", "b") → two file nodes under `parent`. */
function files(parent, ...names) {
  return names.map((name) => ({
    name,
    path: parent ? `${parent}/${name}` : name,
    isDir: false,
    children: [],
  }));
}

function dir(path, children) {
  const parts = path.split("/");
  return { name: parts[parts.length - 1], path, isDir: true, children };
}

/** n numbered files under `parent`. */
function manyFiles(parent, n) {
  return files(parent, ...Array.from({ length: n }, (_, i) => `doc-${i + 1}.md`));
}

const root = (children) => ({ name: "", path: "", isDir: true, children });

test("a folded directory counts every file below it, at any depth", () => {
  const notes = dir("notes", [
    ...files("notes", "a.md", "b.md"),
    dir("notes/deep", [
      ...files("notes/deep", "c.md"),
      dir("notes/deep/deeper", files("notes/deep/deeper", "d.md", "e.md")),
    ]),
  ]);
  assert.equal(dirFileCount(notes), 5);
  assert.equal(dirFileCount(dir("empty", [])), 0);
});

test("a directory below the first level folds when it holds more than 10 files", () => {
  assert.equal(TOC_COLLAPSE_THRESHOLD, 10);
  const big = dir("notes/big", manyFiles("notes/big", 11));
  assert.equal(collapsedByDefault(big, 1), true);
});

test("the >10 boundary is exclusive: exactly 10 files stays open", () => {
  const ten = dir("notes/ten", manyFiles("notes/ten", 10));
  const eleven = dir("notes/eleven", manyFiles("notes/eleven", 11));
  assert.equal(collapsedByDefault(ten, 1), false);
  assert.equal(collapsedByDefault(eleven, 1), true);
});

test("first-level directories are exempt, so the tree never folds down to bare roots", () => {
  const huge = dir("notes", manyFiles("notes", 95));
  assert.equal(collapsedByDefault(huge, 0), false, "depth 0 is the exemption");
  assert.equal(collapsedByDefault(huge, 1), true, "the same directory one level down folds");
  assert.deepEqual([...defaultCollapsedDirs(root([huge]))], []);
});

test("defaultCollapsedDirs walks the whole tree and reports the folded paths", () => {
  const tree = root([
    dir("notes", [
      ...manyFiles("notes", 3),
      dir("notes/archive", manyFiles("notes/archive", 20)),
      dir("notes/small", manyFiles("notes/small", 2)),
    ]),
    dir("specs", [
      dir("specs/v1", [
        dir("specs/v1/rfc", manyFiles("specs/v1/rfc", 12)),
        ...manyFiles("specs/v1", 1),
      ]),
    ]),
  ]);
  // specs/v1 holds 13 files through its child, so it folds too — and its folded child stays
  // in the set, ready for when the reader opens the parent.
  assert.deepEqual(
    [...defaultCollapsedDirs(tree)].sort(),
    ["notes/archive", "specs/v1", "specs/v1/rfc"],
  );
});

test("a custom threshold moves the boundary without touching the first-level exemption", () => {
  const tree = root([dir("notes", [dir("notes/sub", manyFiles("notes/sub", 4))])]);
  assert.deepEqual([...defaultCollapsedDirs(tree, 3)], ["notes/sub"]);
  assert.deepEqual([...defaultCollapsedDirs(tree, 4)], []);
});

test("a reader's own click outranks the default, in both directions, for the session", () => {
  const collapsed = new Set(["notes/archive"]);
  assert.equal(isDirOpen("notes/archive", collapsed, {}), false);
  assert.equal(isDirOpen("notes/archive", collapsed, { "notes/archive": true }), true);
  assert.equal(isDirOpen("notes", collapsed, {}), true);
  assert.equal(isDirOpen("notes", collapsed, { notes: false }), false);
});
