export interface SnapshotOption {
  ref: string;
  label: string | null;
}

export function appendUniqueSnapshots<T extends SnapshotOption>(
  existing: T[],
  incoming: T[],
): T[] {
  const refs = new Set(existing.map((item) => item.ref));
  return [
    ...existing,
    ...incoming.filter((item) => {
      if (refs.has(item.ref)) return false;
      refs.add(item.ref);
      return true;
    }),
  ];
}
