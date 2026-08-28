/**
 * Source titles, on demand.
 *
 * A footnote, a hit row and a failed job all name a source by its TITLE, and all three hold
 * nothing but its id: the recall/ask/jobs routes address sources and do not describe them.
 * The viewer used to answer that two different ways — Recall downloaded the entire catalogue
 * (six round trips of 500 rows, to read a dozen titles), Ask looked each missing one up once
 * — so the same question cost wildly different amounts depending on which page asked it.
 *
 * This is the one answer: ask for the ids you are about to print, once each, and show the id
 * until the title lands. The whole catalogue is downloaded by the page whose subject IS the
 * catalogue (Sources), and by nobody else.
 *
 * Import-free on purpose — the cache and the id collection are pure, so they are transpiled
 * and tested standalone; the fetching half is `views/_shared/useSourceTitles.ts`.
 */

/** What a listing row already knows: the two fields every source page has in hand. */
export interface TitleSeed {
  source_id: string;
  title: string;
}

/** A per-user title cache: what is known, and what has already been asked for. */
export interface TitleCache {
  titles: Record<string, string>;
  /** Ids a lookup has been started for — a second render must not ask again. */
  asked: Set<string>;
}

export function emptyTitleCache(): TitleCache {
  return { titles: {}, asked: new Set() };
}

/** Fold rows a page already holds into the cache. Returns whether anything was new. */
export function rememberTitles(cache: TitleCache, rows: readonly TitleSeed[]): boolean {
  let changed = false;
  for (const row of rows) {
    if (!row.source_id || cache.titles[row.source_id] === row.title) continue;
    cache.titles[row.source_id] = row.title;
    cache.asked.add(row.source_id);
    changed = true;
  }
  return changed;
}

/**
 * The ids that must be fetched for these to be printable: unknown, and not already asked
 * for. Marks them asked, so the caller's effect running twice is one request, not two.
 */
export function claimTitleLookups(cache: TitleCache, ids: Iterable<string>): string[] {
  const out: string[] = [];
  for (const id of ids) {
    if (!id || id in cache.titles || cache.asked.has(id)) continue;
    cache.asked.add(id);
    out.push(id);
  }
  return out;
}

/** One resolved lookup. A failure is recorded as asked-and-unknown: the id stays on screen. */
export function recordTitle(cache: TitleCache, id: string, title: string): void {
  cache.titles[id] = title;
}

/* ------------------------------------------------------- which ids a result cites */

interface Addressed {
  source_id: string;
}

interface Cited {
  citations?: readonly Addressed[];
}

/**
 * Every source id a recall result puts on the page — the ranked ledger's citations, the
 * episode summaries, the fused windows, the component lookups' own evidence, and the answer
 * text's `sNN` handles. Structural on purpose: it reads the fields it names and ignores
 * everything else, so a lane that grows a face costs one line here and no type surgery.
 */
export function recallSourceIds(
  rag: { hits?: readonly Addressed[] } | null | undefined,
  answer:
    | {
        used_claims?: readonly Cited[];
        used_episode_summaries?: readonly Addressed[];
        used_windows?: readonly Addressed[];
        used_component_evidence?: readonly {
          claims?: readonly Cited[];
          windows?: readonly Addressed[];
        }[];
        citation_handles?: Record<string, string>;
      }
    | null
    | undefined,
): string[] {
  const ids = new Set<string>();
  const add = (rows: readonly Addressed[] | undefined) => {
    for (const row of rows ?? []) if (row?.source_id) ids.add(row.source_id);
  };
  const addCited = (rows: readonly Cited[] | undefined) => {
    for (const row of rows ?? []) add(row?.citations);
  };
  add(rag?.hits);
  addCited(answer?.used_claims);
  add(answer?.used_episode_summaries);
  add(answer?.used_windows);
  for (const evidence of answer?.used_component_evidence ?? []) {
    addCited(evidence?.claims);
    add(evidence?.windows);
  }
  for (const real of Object.values(answer?.citation_handles ?? {})) {
    if (real) ids.add(real);
  }
  return [...ids];
}
