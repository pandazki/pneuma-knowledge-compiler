/**
 * Derived indexes over a Dataset. The four projection files are four facets of one
 * object set; this module builds the cross-facet lookups the views jump through
 * (document ↔ graph node ↔ patch ↔ snapshot), all keyed by stable public ids.
 */

import type {
  Dataset,
  DocumentRecord,
  GraphNode,
  JobRecord,
  PatchRecord,
  Snapshot,
} from "./types";

export interface DirNode {
  name: string;
  path: string; // full path for files; dir path for folders
  isDir: boolean;
  children: DirNode[];
  doc?: DocumentRecord;
}

export interface Model {
  dataset: Dataset;
  docById: Map<string, DocumentRecord>;
  docByPath: Map<string, DocumentRecord>;
  nodeById: Map<string, GraphNode>;
  patchById: Map<string, PatchRecord>;
  jobById: Map<string, JobRecord>;
  snapshotById: Map<string, Snapshot>;
  /** ontology type -> ordered index (drives graph shade + legend) */
  typeIndex: Map<string, number>;
  types: string[];
  /** document path -> patches that touched it, oldest first */
  patchesByPath: Map<string, PatchRecord[]>;
  /** document_id -> patches that touched it, oldest first */
  patchesByDocId: Map<string, PatchRecord[]>;
  /**
   * `${document_id}::${anchor}` -> per-claim sidecar notes joined from
   * timeline.patches[].claims[]. Lets the Library surface a disputed/open-question
   * rationale that lives only in the process sidecar (P1-3).
   */
  sidecarNotes: Map<string, SidecarNote>;
  /** adjacency (undirected) for n-degree graph expansion */
  neighbors: Map<string, Set<string>>;
  tree: DirNode;
}

export interface SidecarNote {
  disputed?: string;
  open_question?: string;
  /** every recorded trace for this anchor, oldest first (patch_id + flags + note) */
  traces: { patch_id: string; flags: string[]; note?: string }[];
}

export function claimKey(documentId: string | null, anchor: string | null): string {
  return `${documentId ?? ""}::${anchor ?? ""}`;
}

export function buildModel(dataset: Dataset): Model {
  const docById = new Map<string, DocumentRecord>();
  const docByPath = new Map<string, DocumentRecord>();
  for (const d of dataset.documents.documents) {
    if (d.document_id) docById.set(d.document_id, d);
    docByPath.set(d.path, d);
  }

  const nodeById = new Map(dataset.graph.nodes.map((n) => [n.id, n]));
  const patchById = new Map(dataset.timeline.patches.map((p) => [p.patch_id, p]));
  const jobById = new Map(dataset.timeline.jobs.map((j) => [j.job_id, j]));
  const snapshotById = new Map(
    dataset.timeline.snapshots.map((s) => [s.source_id, s]),
  );

  // ontology types: prefer the skill ontology, fall back to node types present.
  const ont = dataset.workspace.domains.flatMap((d) => d.ontology ?? []);
  const present = dataset.graph.nodes
    .map((n) => n.type)
    .filter((t): t is string => !!t);
  const typeOrder = Array.from(new Set([...ont, ...present]));
  const typeIndex = new Map(typeOrder.map((t, i) => [t, i]));

  // patches by document, oldest first. Prefer the schema v2 `documents` stable-id
  // interlink; fall back to changed_paths when it is absent.
  const patchesByPath = new Map<string, PatchRecord[]>();
  const patchesByDocId = new Map<string, PatchRecord[]>();
  const pushBy = (map: Map<string, PatchRecord[]>, key: string, p: PatchRecord) => {
    const arr = map.get(key) ?? [];
    arr.push(p);
    map.set(key, arr);
  };
  const patchesSorted = [...dataset.timeline.patches].sort(
    (a, b) => cmpPatch(a, b),
  );
  for (const p of patchesSorted) {
    if (p.documents && p.documents.length) {
      for (const d of p.documents) {
        pushBy(patchesByPath, docRelPath(d.path), p);
        if (d.document_id) pushBy(patchesByDocId, d.document_id, p);
      }
    } else {
      for (const cp of p.changed_paths ?? []) {
        const rel = docRelPath(cp);
        pushBy(patchesByPath, rel, p);
        const doc = docByPath.get(rel);
        if (doc?.document_id) pushBy(patchesByDocId, doc.document_id, p);
      }
    }
  }

  // per-claim sidecar notes joined from the timeline (P1-3): a claim's
  // (document_id, anchor) -> the disputed / open_question rationale recorded on the
  // patch that touched it, even when the note never made it inline into the prose.
  const sidecarNotes = new Map<string, SidecarNote>();
  for (const p of patchesSorted) {
    for (const c of p.claims ?? []) {
      const docId = c.anchor?.document_id;
      const anchor = c.anchor?.anchor;
      if (!docId || !anchor) continue;
      const key = claimKey(docId, anchor);
      const entry = sidecarNotes.get(key) ?? { traces: [] };
      const flags = c.flags ?? [];
      entry.traces.push({ patch_id: p.patch_id, flags, note: c.note });
      if (c.note) {
        if (flags.includes("disputed")) entry.disputed = c.note;
        if (flags.includes("open_question")) entry.open_question = c.note;
      }
      sidecarNotes.set(key, entry);
    }
  }

  // undirected adjacency for expansion.
  const neighbors = new Map<string, Set<string>>();
  for (const n of dataset.graph.nodes) neighbors.set(n.id, new Set());
  for (const e of dataset.graph.edges) {
    if (!neighbors.has(e.source)) neighbors.set(e.source, new Set());
    if (!neighbors.has(e.target)) neighbors.set(e.target, new Set());
    neighbors.get(e.source)!.add(e.target);
    neighbors.get(e.target)!.add(e.source);
  }

  const tree = buildTree(dataset.documents.documents);

  return {
    dataset,
    docById,
    docByPath,
    nodeById,
    patchById,
    jobById,
    snapshotById,
    typeIndex,
    types: typeOrder,
    patchesByPath,
    patchesByDocId,
    sidecarNotes,
    neighbors,
    tree,
  };
}

/** patch_id like "kp-3" -> numeric ordering; fall back to ts. */
export function patchNum(id: string): number {
  const m = /kp-(\d+)/.exec(id);
  return m ? Number(m[1]) : Number.MAX_SAFE_INTEGER;
}

function cmpPatch(a: PatchRecord, b: PatchRecord): number {
  const na = patchNum(a.patch_id);
  const nb = patchNum(b.patch_id);
  if (na !== nb) return na - nb;
  return (a.ts ?? "").localeCompare(b.ts ?? "");
}

/** strip the domains/{id}/documents/ prefix so a changed_path matches document.path. */
export function docRelPath(changedPath: string): string {
  const m = /documents\/(.+)$/.exec(changedPath);
  return m ? m[1] : changedPath;
}

/**
 * Classify each changed_path in a patch as created vs modified: the earliest patch
 * (by patch number) that touches a path created it; later ones modified it.
 */
export function classifyChange(
  model: Model,
  patch: PatchRecord,
  changedPath: string,
): "created" | "modified" {
  const rel = docRelPath(changedPath);
  const history = model.patchesByPath.get(rel);
  if (!history || history.length === 0) return "modified";
  return history[0].patch_id === patch.patch_id ? "created" : "modified";
}

export interface PatchDocChange {
  document_id: string | null;
  /** path relative to documents/ (matches DocumentRecord.path) */
  path: string;
  change_type: "created" | "modified";
}

/**
 * The documents a patch touched, with change_type. Prefers the schema v2
 * `patch.documents` stable-id interlink; falls back to changed_paths + classifyChange
 * for older exports. A paged History ledger intentionally has no canonical model;
 * in that bounded context the path remains readable, while identity and create/modify
 * classification conservatively stay unknown/null and modified.
 */
export function patchChanges(model: Model | null, patch: PatchRecord): PatchDocChange[] {
  if (patch.documents && patch.documents.length) {
    return patch.documents.map((d) => ({
      document_id: d.document_id,
      path: docRelPath(d.path),
      change_type: d.change_type,
    }));
  }
  return (patch.changed_paths ?? []).map((cp) => {
    const rel = docRelPath(cp);
    return {
      document_id: model?.docByPath.get(rel)?.document_id ?? null,
      path: rel,
      change_type: model ? classifyChange(model, patch, cp) : "modified",
    };
  });
}

/** BFS expansion from a center node out to `degree` hops. */
export function expandNeighborhood(
  model: Model,
  center: string,
  degree: number,
): { ids: Set<string>; depth: Map<string, number> } {
  const depth = new Map<string, number>([[center, 0]]);
  const ids = new Set<string>([center]);
  let frontier = [center];
  for (let d = 1; d <= degree; d++) {
    const next: string[] = [];
    for (const cur of frontier) {
      for (const nb of model.neighbors.get(cur) ?? []) {
        if (!ids.has(nb)) {
          ids.add(nb);
          depth.set(nb, d);
          next.push(nb);
        }
      }
    }
    frontier = next;
  }
  return { ids, depth };
}

function buildTree(docs: DocumentRecord[]): DirNode {
  const root: DirNode = { name: "", path: "", isDir: true, children: [] };
  const dirMap = new Map<string, DirNode>([["", root]]);

  const ensureDir = (dirPath: string): DirNode => {
    if (dirMap.has(dirPath)) return dirMap.get(dirPath)!;
    const parts = dirPath.split("/");
    const name = parts[parts.length - 1];
    const parentPath = parts.slice(0, -1).join("/");
    const parent = ensureDir(parentPath);
    const node: DirNode = { name, path: dirPath, isDir: true, children: [] };
    parent.children.push(node);
    dirMap.set(dirPath, node);
    return node;
  };

  for (const doc of [...docs].sort((a, b) => a.path.localeCompare(b.path))) {
    const parts = doc.path.split("/");
    const fileName = parts[parts.length - 1];
    const dirPath = parts.slice(0, -1).join("/");
    const parent = ensureDir(dirPath);
    parent.children.push({
      name: fileName,
      path: doc.path,
      isDir: false,
      children: [],
      doc,
    });
  }

  const sortRec = (node: DirNode) => {
    node.children.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    node.children.forEach(sortRec);
  };
  sortRec(root);
  return root;
}

/** Theme-adaptive ink-alpha shade for an ontology type (monochrome discipline). */
export function typeShade(model: Model, type: string | null): string {
  if (!type) return "color-mix(in srgb, var(--color-text) 26%, transparent)";
  const i = model.typeIndex.get(type) ?? 0;
  const total = Math.max(model.types.length, 1);
  // Wider-spaced ramp (35 → 92%) so adjacent types read as distinct ink weights.
  const pct = Math.round(35 + (57 * i) / Math.max(total - 1, 1));
  return `color-mix(in srgb, var(--color-text) ${pct}%, transparent)`;
}

/**
 * Redundant SHAPE per ontology type (P1-2). Monochrome shade alone is
 * near-indistinguishable between adjacent types, so we pair it with a shape the
 * graph and legend both render via typeGlyph.
 */
export type NodeShape = "circle" | "square" | "diamond" | "triangle" | "pentagon" | "hexagon";

const NODE_SHAPES: NodeShape[] = [
  "circle",
  "square",
  "diamond",
  "triangle",
  "pentagon",
  "hexagon",
];

export function nodeShape(model: Model, type: string | null): NodeShape {
  if (!type) return "circle";
  const i = model.typeIndex.get(type) ?? 0;
  return NODE_SHAPES[i % NODE_SHAPES.length];
}

/** Distinguishable per-type encoding shared by the graph nodes and the legend. */
export function typeGlyph(
  model: Model,
  type: string | null,
): { shade: string; shape: NodeShape } {
  return { shade: typeShade(model, type), shape: nodeShape(model, type) };
}
