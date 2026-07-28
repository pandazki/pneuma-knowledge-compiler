export interface PageMeta {
  limit: number;
  total: number;
  next_cursor: string | null;
}

export interface Page<T> {
  items: T[];
  page: PageMeta;
}

export interface CursorPageState {
  cursor: string | null;
  previous: Array<string | null>;
}

export function firstPage(): CursorPageState {
  return { cursor: null, previous: [] };
}

export function nextPage(state: CursorPageState, cursor: string): CursorPageState {
  return {
    cursor,
    previous: [...state.previous, state.cursor],
  };
}

export function previousPage(state: CursorPageState): CursorPageState {
  if (state.previous.length === 0) return state;
  return {
    cursor: state.previous[state.previous.length - 1] ?? null,
    previous: state.previous.slice(0, -1),
  };
}

export function visibleRange(
  pageIndex: number,
  limit: number,
  itemCount: number,
  total: number,
): { from: number; to: number; total: number } {
  if (itemCount === 0 || total === 0) return { from: 0, to: 0, total };
  const from = pageIndex * limit + 1;
  return {
    from,
    to: Math.min(total, from + itemCount - 1),
    total,
  };
}

export function buildPageQuery(
  params: Record<string, string | number | null | undefined>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === "") continue;
    query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}
