import type {
  JobRecord,
  PatchRecord,
  Selection,
  Snapshot,
} from "./types";

export type HistoryKind = "patch" | "job" | "snapshot";

export interface HistoryItemEnvelope {
  kind: HistoryKind;
  ref: string;
  ts: string;
  payload: Record<string, unknown>;
}

export interface HistoryCounts {
  patches: number;
  jobs: number;
  snapshots: number;
  total: number;
}

export type HistoryTimelineItem =
  | { kind: "patch"; ts: string; ref: string; patch: PatchRecord }
  | { kind: "job"; ts: string; ref: string; job: JobRecord }
  | { kind: "snapshot"; ts: string; ref: string; snapshot: Snapshot };

/**
 * The envelope owns identity and ordering. Payloads carry kind-specific detail,
 * but may be sparse because the paged ledger deliberately avoids building the
 * full canonical projection.
 */
export function normalizeHistoryItem(
  item: HistoryItemEnvelope,
): HistoryTimelineItem {
  if (item.kind === "patch") {
    const payload = item.payload as Partial<PatchRecord>;
    return {
      kind: "patch",
      ref: item.ref,
      ts: item.ts,
      patch: {
        patch_id: item.ref,
        job_id: payload.job_id ?? null,
        ts: item.ts,
        base_commit: payload.base_commit ?? null,
        changed_paths: payload.changed_paths ?? [],
        documents: payload.documents ?? [],
        sources_consumed: payload.sources_consumed ?? [],
        skill_version: payload.skill_version ?? null,
        effort: payload.effort ?? null,
        claims: payload.claims ?? [],
        escalations: payload.escalations ?? [],
        merges: payload.merges ?? [],
        flag_counts: payload.flag_counts ?? {},
        lineage: payload.lineage ?? {},
      },
    };
  }
  if (item.kind === "job") {
    const payload = item.payload as Partial<JobRecord>;
    return {
      kind: "job",
      ref: item.ref,
      ts: item.ts,
      job: {
        job_id: item.ref,
        status: payload.status ?? "running",
        patch_id: payload.patch_id ?? null,
        ts: item.ts,
      },
    };
  }
  const payload = item.payload as Partial<Snapshot>;
  return {
    kind: "snapshot",
    ref: item.ref,
    ts: item.ts,
    snapshot: {
      source_id: item.ref,
      source_type: payload.source_type ?? "unknown",
      captured_at: item.ts,
      checksum: payload.checksum ?? "",
      source_class: payload.source_class,
      source_uri: payload.source_uri,
      consumed_by: payload.consumed_by,
      material_document_id: payload.material_document_id,
    },
  };
}

export function selectedHistoryItem(
  items: HistoryTimelineItem[],
  selection: Selection,
): HistoryTimelineItem | null {
  if (
    selection?.kind !== "patch" &&
    selection?.kind !== "job" &&
    selection?.kind !== "snapshot"
  ) {
    return null;
  }
  return (
    items.find(
      (item) => item.kind === selection.kind && item.ref === selection.id,
    ) ?? null
  );
}
