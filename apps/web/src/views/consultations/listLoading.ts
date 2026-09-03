/**
 * Who owns the consultation list right now — and therefore whose response may write to it.
 *
 * The ledger is loaded by two paths (a first page whenever the user or the filters change,
 * and a load-more that appends), and both are plain awaits over the network. Without a
 * guard the SLOWER response wins whichever way it lands: switch library while a request is
 * in flight and the previous tenant's questions render under the new library's name, which
 * is the isolation invariant broken in the one place a reader would believe it least (I1).
 * Change a filter and the old filter's page can overwrite the new one's.
 *
 * The mechanism is a generation counter, not a cancellation: `fetch` cannot be un-sent, so
 * the discipline is that a response proves it is still the current query before it is
 * allowed to touch any state. `claim()` is called by the first-page load — a new (user,
 * filters) query takes the list — and `holds(token)` is what every response asks on its way
 * back. A load-more does not claim; it rides the token of the query it is extending, so a
 * page appended after the query moved on is dropped rather than mixed into another
 * library's list.
 *
 * Loading lives here rather than inline in the view for a boring reason: this app has no
 * rendering harness, and an interleaving bug is exactly the kind that only a test with two
 * responses resolving out of order can catch.
 */
import type { ConsultationParams, ConsultationSummary } from "@/lib/api";
import type { Page } from "@/lib/pagination";

export interface QueryOwner {
  /** A new query takes the list, and every earlier response is now stale. */
  claim(): number;
  /** The token of the query that owns the list right now. */
  token(): number;
  /** Is this token still the owner's? Asked by every response before it writes. */
  holds(token: number): boolean;
}

export function createQueryOwner(): QueryOwner {
  let current = 0;
  return {
    claim: () => ++current,
    token: () => current,
    holds: (token: number) => token === current,
  };
}

/** What a page load reports back, so the view keeps the state and this keeps the order. */
export interface ListSink {
  setLoading(value: boolean): void;
  setError(message: string | null): void;
  replace(items: ConsultationSummary[], total: number, cursor: string | null): void;
  append(items: ConsultationSummary[], cursor: string | null): void;
}

export type FetchPage = (params: ConsultationParams) => Promise<Page<ConsultationSummary>>;

/**
 * The first page of a (user, filters) query. Claims the list, and writes nothing at all if
 * a newer query claimed it while this one was in flight — not the items, not the error, not
 * even the end of the loading state, which belongs to whoever owns the list now.
 */
export async function loadFirstPage(
  owner: QueryOwner,
  fetchPage: FetchPage,
  params: ConsultationParams,
  sink: ListSink,
): Promise<void> {
  const mine = owner.claim();
  sink.setLoading(true);
  sink.setError(null);
  try {
    const page = await fetchPage(params);
    if (!owner.holds(mine)) return;
    sink.replace(page.items, page.page.total, page.page.next_cursor);
  } catch (caught) {
    if (!owner.holds(mine)) return;
    sink.setError((caught as Error).message);
    sink.replace([], 0, null);
  } finally {
    if (owner.holds(mine)) sink.setLoading(false);
  }
}

/**
 * One more page of the query that currently owns the list. It rides that query's token
 * rather than claiming one of its own: a page fetched under filters the reader has since
 * changed is not an extension of what is on screen, it is somebody else's list.
 */
export async function loadNextPage(
  owner: QueryOwner,
  fetchPage: FetchPage,
  params: ConsultationParams,
  sink: ListSink,
): Promise<void> {
  const mine = owner.token();
  try {
    const page = await fetchPage(params);
    if (!owner.holds(mine)) return;
    sink.append(page.items, page.page.next_cursor);
  } catch (caught) {
    if (!owner.holds(mine)) return;
    sink.setError((caught as Error).message);
  }
}
