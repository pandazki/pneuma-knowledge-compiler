/**
 * The Canonical contents tree's folding policy.
 *
 * At 95 documents a fully expanded tree is a wall of filenames, so a directory holding more
 * than `TOC_COLLAPSE_THRESHOLD` files starts folded — except the first level, which always
 * stays open: fold those and the reader is left staring at the bare roots with nothing to
 * read. Folding is presentation only; the tree itself (lib/model buildTree) is untouched.
 *
 * Import-free by design (the DirNode import is type-only), so it transpiles standalone for
 * its test.
 */

import type { DirNode } from "./model";

/** A directory folds by default past this many files (exclusive). */
export const TOC_COLLAPSE_THRESHOLD = 10;

/** Every file below a directory, at any depth — the number its folded row reports. */
export function dirFileCount(node: DirNode): number {
  let n = 0;
  for (const child of node.children) {
    if (child.isDir) n += dirFileCount(child);
    else n += 1;
  }
  return n;
}

/**
 * Whether a directory starts folded. `depth` counts from the tree root's children: depth 0
 * is a first-level directory and is exempt whatever it holds.
 */
export function collapsedByDefault(
  node: DirNode,
  depth: number,
  threshold: number = TOC_COLLAPSE_THRESHOLD,
): boolean {
  if (!node.isDir) return false;
  if (depth === 0) return false;
  return dirFileCount(node) > threshold;
}

/** The paths of every directory that starts folded, walked from the tree root. */
export function defaultCollapsedDirs(
  root: DirNode,
  threshold: number = TOC_COLLAPSE_THRESHOLD,
): Set<string> {
  const out = new Set<string>();
  const walk = (node: DirNode, depth: number) => {
    if (!node.isDir) return;
    if (collapsedByDefault(node, depth, threshold)) out.add(node.path);
    for (const child of node.children) walk(child, depth + 1);
  };
  for (const child of root.children) walk(child, 0);
  return out;
}

/**
 * Is this directory open right now? The default policy decides until the reader touches the
 * row; from then on their choice wins for the rest of the session.
 */
export function isDirOpen(
  path: string,
  collapsedDefaults: Set<string>,
  overrides: Record<string, boolean>,
): boolean {
  const manual = overrides[path];
  if (manual !== undefined) return manual;
  return !collapsedDefaults.has(path);
}
