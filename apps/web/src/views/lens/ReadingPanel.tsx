import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, Inbox } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT, useTOr } from "@/lib/useT";
import { getLensReport } from "@/lib/api";
import { fmtCount, fmtDateTime, fmtPercent, shortSha } from "@/lib/format";
import { groupByLevel, headline, type LensGroup, type LensReport } from "@/lib/lensReport";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";
import { FindingRow } from "./FindingRow";

/** How many findings the page leads with (§3.4: "the three things to do first"). */
const HEADLINE_COUNT = 3;

/**
 * The reading: one report, rendered.
 *
 * The score leads because it is the one number worth watching between two readings, and it is
 * immediately followed by the sentence that says what it is NOT (a grade). Then the three
 * things to do first, at reading size — these are the whole reason the page exists. Everything
 * else is the same findings again, by level, behind a fold: present for the maintainer who
 * came to work through them, silent for the Owner who came to glance.
 */
export function ReadingPanel() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const libraryRevision = useApp((s) => s.libraryRevision);
  const setView = useApp((s) => s.setView);

  const [report, setReport] = useState<LensReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!currentUser) {
      setReport(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    getLensReport(currentUser, currentSnapshot)
      .then((next) => {
        if (!alive) return;
        setReport(next);
        setLoading(false);
      })
      .catch((e: Error) => {
        if (!alive) return;
        setReport(null);
        setError(e.message);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
    // `libraryRevision` is the "the library moved" signal a Steward round raises; the report
    // is derived from canonical, so it is stale the moment a round commits.
  }, [currentUser, currentSnapshot, libraryRevision, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const groups = useMemo(
    () => (report ? groupByLevel(report.findings) : []),
    [report],
  );

  if (loading) {
    return (
      <div aria-busy>
        <p className="text-12 text-ink-3">{t("lens.loading")}</p>
        <SkeletonText className="mt-3" lines={6} />
      </div>
    );
  }

  if (error) {
    return <ErrorState title={t("lens.error.title")} error={error} onRetry={retry} />;
  }

  // Nothing compiled AND nothing to say about it. A library with no documents can still
  // carry findings — a contract declaring families no page lives under is exactly that — and
  // an empty state would swallow them.
  if (!report || (report.files === 0 && report.findings.length === 0)) {
    return (
      <EmptyState
        icon={Inbox}
        title={t("lens.empty.title")}
        description={t("lens.empty.description")}
        action={
          <Button size="sm" onClick={() => setView("ingest")}>
            {t("lens.empty.action")}
          </Button>
        }
      />
    );
  }

  const top = headline(report.findings, HEADLINE_COUNT);
  const rest = report.findings.length - top.length;

  return (
    <div className="flex flex-col gap-8">
      <section>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-serif text-38 leading-none tabular-nums text-ink">
            {Math.round(report.score)}
          </span>
          <span className="text-13 text-ink-2">{t("lens.score.label")}</span>
          <hr aria-hidden className="hidden min-w-8 flex-1 border-0 border-t border-line sm:block" />
          <span className="flex shrink-0 items-baseline gap-2 text-12 text-ink-3">
            <Mono>{shortSha(report.ref)}</Mono>
            <span>{t("lens.readAt", { time: fmtDateTime(report.read_at) })}</span>
          </span>
        </div>
        <p className="mt-2 max-w-measure text-12 text-ink-3">{t("lens.score.meaning")}</p>
        <p className="mt-3 max-w-measure text-13 text-ink-2">
          {t("lens.counts", {
            files: report.files,
            subjects: report.subjects,
            claims: report.claims,
            edges: report.edges,
          })}
        </p>
      </section>

      {/* ------------------------------------------------------------- the headline */}
      <section>
        <SectionRule no={1} title={t("lens.headline.title")} />
        {top.length === 0 ? (
          <p className="mt-3 max-w-measure text-14 text-ink-2">{t("lens.headline.clean")}</p>
        ) : (
          <>
            <ol className="mt-3 flex flex-col border-t border-line">
              {top.map((finding, i) => (
                <FindingRow key={finding.key} finding={finding} rank={i + 1} emphasis />
              ))}
            </ol>
            {rest > 0 && (
              <p className="mt-2 text-12 text-ink-3">{t("lens.headline.rest", { count: rest })}</p>
            )}
          </>
        )}
      </section>

      {/* --------------------------------------------------------- every finding, by level */}
      {groups.map((group, i) => (
        <LevelSection key={group.level} group={group} no={i + 2} />
      ))}

      {/* ---------------------------------------------------------------- family balance */}
      <section>
        <SectionRule no={groups.length + 2} title={t("lens.families.title")} />
        <p className="mt-2 max-w-measure text-12 text-ink-3">{t("lens.families.note")}</p>
        {report.families.length === 0 ? (
          <p className="mt-3 max-w-measure text-13 text-ink-3">{t("lens.families.empty")}</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[28rem] border-collapse text-13">
              <thead>
                <tr className="border-b border-line text-12 text-ink-3">
                  <th scope="col" className="py-1.5 pr-3 text-left font-normal">
                    {t("lens.families.name")}
                  </th>
                  <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                    {t("lens.families.pages")}
                  </th>
                  <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                    {t("lens.families.claims")}
                  </th>
                  <th scope="col" className="py-1.5 text-right font-normal">
                    {t("lens.families.share")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {report.families.map((family) => (
                  <tr key={family.name} className="border-b border-line last:border-b-0">
                    <td className="py-1.5 pr-3">
                      <Mono className="text-12 text-ink">{family.name}</Mono>
                    </td>
                    <td
                      className={cn(
                        "py-1.5 pr-3 text-right font-mono text-12 tabular-nums",
                        // A declared family that never took a page is a fact about the
                        // structure, not a zero to skim past.
                        family.pages === 0 ? "text-ink" : "text-ink-2",
                      )}
                    >
                      {fmtCount(family.pages)}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-12 text-ink-2 tabular-nums">
                      {fmtCount(family.claims)}
                    </td>
                    <td className="py-1.5 text-right font-mono text-12 text-ink-2 tabular-nums">
                      {fmtPercent(family.share)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/**
 * One level, folded. The count is on the header because that is what a reader wants before
 * deciding to open it, and the level's one-line note is what tells them whether it is theirs
 * to act on at all.
 */
function LevelSection({ group, no }: { group: LensGroup; no: number }) {
  const t = useT();
  const tOr = useTOr();
  const [open, setOpen] = useState(false);
  // The level and its note are looked up by a runtime string: a level this build has never
  // heard of is shown under its own name rather than dropped from the page.
  const level = tOr(`lens.level.${group.level}`, group.level);
  const note = tOr(`lens.level.${group.level}.note`, "");
  const count = group.findings.length;

  return (
    <section>
      <SectionRule no={no} title={level} />
      {note && <p className="mt-2 max-w-measure text-12 text-ink-3">{note}</p>}
      {count === 0 ? (
        <p className="mt-2 text-13 text-ink-3">{t("lens.group.empty")}</p>
      ) : (
        <>
          <button
            type="button"
            aria-expanded={open}
            aria-label={t(open ? "lens.group.collapse" : "lens.group.expand", { level, count })}
            onClick={() => setOpen((v) => !v)}
            className="mt-2 flex w-full items-center gap-1.5 rounded-1 py-1 text-left text-13 text-ink-2 transition-colors duration-120 hover:bg-hover"
          >
            <ChevronRight
              size={12}
              aria-hidden
              className={cn(
                "shrink-0 text-ink-3 transition-transform duration-120",
                open && "rotate-90",
              )}
            />
            <span>{t("lens.group.count", { count })}</span>
          </button>
          {open && (
            <ul className="mt-1 flex flex-col border-t border-line">
              {group.findings.map((finding) => (
                <FindingRow key={finding.key} finding={finding} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
