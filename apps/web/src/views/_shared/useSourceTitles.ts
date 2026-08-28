import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getSource } from "@/lib/api";
import {
  claimTitleLookups,
  emptyTitleCache,
  recordTitle,
  rememberTitles,
  type TitleCache,
  type TitleSeed,
} from "@/lib/sourceTitles";

/**
 * `source_id → title` for the ids a page is about to print, fetched one at a time and only
 * once each (`lib/sourceTitles`). Shared by Recall, Ask and Process, which all show source
 * ids they did not list.
 *
 * The cache lives for the life of the mounted view and is dropped when the user changes — a
 * title is a per-user fact, and carrying one across a user switch is exactly the kind of
 * cross-tenant leak I1 exists to prevent.
 */
export function useSourceTitles(userId: string | null, ids: readonly string[]) {
  const cacheRef = useRef<TitleCache>(emptyTitleCache());
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((n) => n + 1), []);

  useEffect(() => {
    cacheRef.current = emptyTitleCache();
    bump();
  }, [userId, bump]);

  // The ids as one stable string: the array is rebuilt on every render, the QUESTION is not.
  const wanted = ids.join(" ");

  useEffect(() => {
    if (!userId) return;
    const missing = claimTitleLookups(cacheRef.current, wanted ? wanted.split(" ") : []);
    if (missing.length === 0) return;
    let alive = true;
    for (const id of missing) {
      getSource(userId, id)
        .then((detail) => {
          recordTitle(cacheRef.current, id, detail.title);
          if (alive) bump();
        })
        .catch(() => {
          /* asked and unknown: the row keeps showing the id */
        });
    }
    return () => {
      alive = false;
    };
  }, [userId, wanted, bump]);

  const remember = useCallback(
    (rows: readonly TitleSeed[]) => {
      if (rememberTitles(cacheRef.current, rows)) bump();
    },
    [bump],
  );

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const titles = useMemo(() => ({ ...cacheRef.current.titles }), [version]);

  return { titles, remember };
}
