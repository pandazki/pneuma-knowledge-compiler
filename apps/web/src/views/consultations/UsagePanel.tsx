import { useEffect, useState } from "react";
import {
  getAccessTop,
  getConsultationSpend,
  type AccessTop,
  type Spend,
} from "@/lib/api";
import { useApp } from "@/lib/store";
import { fmtCount, fmtDay, fmtMoney } from "@/lib/format";
import { useT } from "@/lib/useT";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { SkeletonText } from "@/ui/Skeleton";
import { spendNote, unmeasuredCount } from "./spendNote";

const WINDOWS = [7, 30, 90] as const;
const ROWS = 6;

/**
 * The access ledger's two halves, above the record they were derived from: the pages this
 * library's readers actually read, and the questions it answered with nothing.
 *
 * No chart, on purpose. Six rows with a number on each answers "what is being read" without
 * asking a reader to estimate an area, and the honest shape of this data is a short ranked
 * list rather than a distribution — heat is a ranking device, not a quantity anybody should
 * be comparing across libraries.
 *
 * A failure here is silence rather than an error: the panel is context above a page whose
 * own content loads separately, and a library whose ledger is unreachable can still be read.
 */
export function UsagePanel({ userId }: { userId: string }) {
  const t = useT();
  const openConsultations = useApp((s) => s.openConsultations);
  const [days, setDays] = useState<number>(30);
  const [top, setTop] = useState<AccessTop | null>(null);
  const [spend, setSpend] = useState<Spend | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getAccessTop(userId, { days, limit: ROWS })
      .then((next) => {
        if (alive) setTop(next);
      })
      .catch(() => {
        if (alive) setTop(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [userId, days]);

  // The same window, in money. A separate request rather than a field on the ledger above:
  // the two answer different questions (what was READ, what was SPENT) and one being
  // unreachable must not blank the other.
  useEffect(() => {
    let alive = true;
    getConsultationSpend(userId, days)
      .then((next) => {
        if (alive) setSpend(next);
      })
      .catch(() => {
        if (alive) setSpend(null);
      });
    return () => {
      alive = false;
    };
  }, [userId, days]);

  return (
    <section className="flex flex-col gap-3">
      <SectionRule
        no={1}
        title={t("usage.title")}
        actions={
          <SegmentedControl
            size="sm"
            aria-label={t("usage.daysAria")}
            value={String(days)}
            onChange={(v) => setDays(Number(v))}
            options={WINDOWS.map((w) => ({
              value: String(w),
              label: t(`usage.days${w}` as "usage.days7"),
            }))}
          />
        }
      />
      {top && (
        <p className="text-12 text-ink-3">
          {t("usage.window", {
            since: fmtDay(top.since),
            until: fmtDay(top.until),
            halfLife: top.half_life_days,
          })}
        </p>
      )}
      {spend && spend.consultations > 0 && (
        <p className="text-12 text-ink-3">
          {t("usage.spend", { count: spend.consultations })}{" "}
          <Mono>
            total {fmtCount(spend.token_usage.total_tokens ?? 0)}
            {spend.cost ? ` · ${fmtMoney(spend.cost)}` : ""}
          </Mono>
          {/* Two different reasons for no money, and they are not interchangeable — see
              `spendNote`, which decides which one this window is owed. */}
          {spendNote(spend) === "incomplete" && (
            <> {t("usage.spendIncomplete", { missing: unmeasuredCount(spend) })}</>
          )}
          {spendNote(spend) === "unpriced" && <> {t("usage.spendUnpriced")}</>}
        </p>
      )}
      {loading ? (
        <SkeletonText lines={4} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="min-w-0">
            <p className="text-12 text-ink-3">{t("usage.hotDocuments")}</p>
            {top && top.documents.length > 0 ? (
              <ul className="mt-1 flex flex-col">
                {top.documents.map((doc) => (
                  <li key={doc.path} className="border-b border-line last:border-b-0">
                    <button
                      type="button"
                      title={doc.path}
                      onClick={() => openConsultations(doc.path)}
                      className="flex w-full min-w-0 items-baseline gap-3 py-1.5 text-left transition-colors duration-120 hover:bg-hover"
                    >
                      <span className="min-w-0 flex-1 truncate text-13 text-ink">
                        {doc.path}
                      </span>
                      {/* Two numbers on one row need saying apart: the first RANKS this
                          list, the second is the plain count behind it. */}
                      <Mono className="shrink-0 text-12 text-ink-3">
                        {t("access.heat")} {Math.round(doc.heat)}
                      </Mono>
                      <span className="shrink-0 text-12 text-ink-3">
                        {t("access.hits7d")} {t("access.hits", { count: doc.hits_7d })}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-13 text-ink-3">{t("usage.emptyHot")}</p>
            )}
          </div>
          <div className="min-w-0">
            <p className="text-12 text-ink-3">{t("usage.topMisses")}</p>
            {top && top.misses.length > 0 ? (
              <ul className="mt-1 flex flex-col">
                {top.misses.map((miss) => (
                  <li
                    key={miss.question}
                    className="flex min-w-0 flex-col gap-0.5 border-b border-line py-1.5 last:border-b-0"
                  >
                    <span className="min-w-0 text-13 text-ink">{miss.question}</span>
                    <span className="text-12 text-ink-3">
                      {t("usage.missCount", { count: miss.count })} ·{" "}
                      {t("usage.missLastDay", { day: fmtDay(miss.last_day) })}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-13 text-ink-3">{t("usage.emptyMisses")}</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
