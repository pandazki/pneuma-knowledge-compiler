import { useEffect, useState } from "react";
import { getAccessStats, type AccessStats } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Mono } from "@/ui/Mono";

/**
 * What this library's readers have done with THIS page: when it was last read, how often in
 * the last 7 and 30 days, and its decayed heat.
 *
 * Derived and joined at read time — nothing here is written into the page, because a read
 * must never become a write to the authority. The page itself is byte-identical whether or
 * not anybody has ever opened it.
 *
 * The card asks about ONE target, the document, and that is the honest unit: the ledger
 * counts a page once per pass however many of its claims travelled, so a per-claim card
 * would be ranking claims by nothing anybody meant. A page nobody has read says so quietly —
 * "no recorded access" is an answer, not an error — and so does a ledger that cannot be
 * reached at all: a canonical page must remain readable when the derived layer is down.
 */
export function AccessCard({ userId, path }: { userId: string; path: string }) {
  const t = useT();
  const openConsultations = useApp((s) => s.openConsultations);
  const [stats, setStats] = useState<AccessStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setStats(null);
    getAccessStats(userId, "document", path)
      .then((next) => {
        if (alive) setStats(next);
      })
      .catch(() => {
        // A card, not a page. An unreachable ledger renders as "no recorded access" rather
        // than as an error banner over a document that is perfectly readable without it.
        if (alive) setStats(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [userId, path]);

  const read = stats != null && stats.last_accessed_at != null;

  return (
    <div className="mt-3 flex flex-col gap-2">
      {loading ? (
        <p className="text-13 text-ink-3">{t("access.loading")}</p>
      ) : read ? (
        <dl className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <div className="flex items-baseline gap-2">
            <dt className="text-12 text-ink-3">{t("access.lastAccessed")}</dt>
            <dd className="text-13 text-ink">{fmtTime(stats!.last_accessed_at)}</dd>
          </div>
          <div className="flex items-baseline gap-2">
            <dt className="text-12 text-ink-3">{t("access.hits7d")}</dt>
            <dd className="text-13 text-ink">
              {t("access.hits", { count: stats!.hits_7d })}
            </dd>
          </div>
          <div className="flex items-baseline gap-2">
            <dt className="text-12 text-ink-3">{t("access.hits30d")}</dt>
            <dd className="text-13 text-ink">
              {t("access.hits", { count: stats!.hits_30d })}
            </dd>
          </div>
          <div className="flex items-baseline gap-2">
            <dt className="text-12 text-ink-3">{t("access.heat")}</dt>
            <dd>
              <Mono className="text-13 text-ink">{Math.round(stats!.heat)}</Mono>
            </dd>
          </div>
        </dl>
      ) : (
        <p className="text-13 text-ink-3">{t("access.never")}</p>
      )}
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <button
          type="button"
          onClick={() => openConsultations(path)}
          className="text-13 text-accent transition-colors duration-120 hover:underline"
        >
          {t("access.related")}
        </button>
        <p className="text-12 text-ink-3">{t("access.note")}</p>
      </div>
    </div>
  );
}
