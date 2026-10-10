/** Collection observations are separate from a source's verbatim evidence and metadata. */
export interface SourceCollectionObservation {
  transport: "local" | "remote";
  device_id: string;
  device_label: string | null;
  project_id: string;
  project_name: string;
  project_path: string;
  remotes: string[];
  first_observed_at: string;
  last_observed_at: string;
}

export interface SourceCollection {
  source_id: string;
  user_id: string;
  relation: "session_observation";
  observations: SourceCollectionObservation[];
}

function record(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

/** Unknown editions and mismatched identities cannot supply another source's context. */
export function parseSourceCollection(
  value: unknown,
  userId: string,
  sourceId: string,
): SourceCollection | null {
  const data = record(value);
  if (!data || data.user_id !== userId || data.source_id !== sourceId ||
    data.relation !== "session_observation" || !Array.isArray(data.observations)) {
    return null;
  }
  const observations: SourceCollectionObservation[] = [];
  for (const value of data.observations) {
    const row = record(value);
    if (!row || (row.transport !== "local" && row.transport !== "remote") ||
      typeof row.device_id !== "string" || !row.device_id ||
      (row.device_label !== null && typeof row.device_label !== "string") ||
      typeof row.project_id !== "string" || typeof row.project_name !== "string" ||
      typeof row.project_path !== "string" ||
      !Array.isArray(row.remotes) || !row.remotes.every((remote) => typeof remote === "string") ||
      typeof row.first_observed_at !== "string" || typeof row.last_observed_at !== "string") {
      return null;
    }
    observations.push({
      transport: row.transport,
      device_id: row.device_id,
      device_label: row.device_label,
      project_id: row.project_id,
      project_name: row.project_name,
      project_path: row.project_path,
      remotes: row.remotes,
      first_observed_at: row.first_observed_at,
      last_observed_at: row.last_observed_at,
    });
  }
  return { source_id: sourceId, user_id: userId, relation: "session_observation", observations };
}
