import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Inbox } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT, useTOr } from "@/lib/useT";
import { enqueueReviewRound, getCheckReport, type JobEnqueued } from "@/lib/api";
import { fmtDateTime, shortSha } from "@/lib/format";
import { countByKind, groupByPage, type CheckPage, type CheckReport } from "@/lib/lensReport";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SkeletonText } from "@/ui/Skeleton";
import { FindingRow } from "./FindingRow";

/**
 * `#/review` — the check (docs/design/structure-lens.md §3).
 *
 * The middle tier of the three. A tier-one fault the write mechanism can decide never reaches
 * a reader; a tier-three reading needs the god's-eye and lives at `#/lens`. What is left here
 * is what an insider standing at the page can see against the contract and repair in a round:
 * a hub that leaves its own children unreachable, a page that names another subject twenty
 * times and never links it, a title that exists twice — and the legacy instances of faults the
 * gate now refuses outright.
 *
 * So the page is a worklist, and it is grouped the way the work is done: by PAGE. A Steward
 * opens one document and fixes everything the report says about it, rather than walking a flat
 * list that sends them back to the same file four times. Within a page the report's own order
 * stands — legacy before judgement, because a hook fault is unambiguous.
 *
 * The one act on the page is the review ROUND (§3.2): a canonical-lane job whose task is this
 * report and whose instruction is to repair what a round can repair, under the ordinary gate.
 * It is the Owner's to enqueue and nothing else in this version schedules it. The console
 * hands nothing else to anybody — the report is a reading, and a finding reaches the Steward
 * because the Owner asked for a round, not because a page pushed it.
 */
export default function ReviewView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const libraryRevision = useApp((s) => s.libraryRevision);
  const setView = useApp((s) => s.setView);
  const jump = useApp((s) => s.jump);
  const readOnly = currentSnapshot != null;

  const [report, setReport] = useState<CheckReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const [enqueued, setEnqueued] = useState<JobEnqueued | null>(null);
  const [enqueueing, setEnqueueing] = useState(false);
  const [enqueueError, setEnqueueError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentUser) {
      setReport(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    getCheckReport(currentUser, currentSnapshot)
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
    // `libraryRevision` is the "the library moved" signal a round raises; the report is
    // derived from canonical, so it is stale the moment a round commits.
  }, [currentUser, currentSnapshot, libraryRevision, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const pages = useMemo(() => (report ? groupByPage(report.findings) : []), [report]);
  const counts = useMemo(() => (report ? countByKind(report.findings) : {}), [report]);

  async function runRound() {
    if (!currentUser) return;
    setEnqueueing(true);
    setEnqueueError(null);
    setEnqueued(null);
    try {
      setEnqueued(await enqueueReviewRound(currentUser));
    } catch (e) {
      setEnqueueError((e as Error).message);
    } finally {
      setEnqueueing(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("nav.view.review")}
        description={t("review.description")}
        actions={
          <Button
            variant="primary"
            loading={enqueueing}
            disabled={!currentUser || readOnly || enqueueing}
            title={readOnly ? t("review.round.readOnlyHint") : t("review.round.hint")}
            onClick={() => void runRound()}
          >
            {t("review.round.action")}
          </Button>
        }
      />

      {enqueued && (
        <Callout
          tone="notice"
          title={t("review.round.enqueued")}
          onDismiss={() => setEnqueued(null)}
        >
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Mono className="break-all">{enqueued.job_id || t("review.round.noJobId")}</Mono>
            {enqueued.status && <span className="text-12 text-ink-2">{enqueued.status}</span>}
            {enqueued.job_id && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => jump({ kind: "job", id: enqueued.job_id }, "process")}
              >
                {t("review.round.openJob")}
              </Button>
            )}
          </span>
        </Callout>
      )}

      {enqueueError && (
        <Callout tone="danger" title={t("review.round.failed")} onDismiss={() => setEnqueueError(null)}>
          <Mono className="break-all text-12">{enqueueError}</Mono>
        </Callout>
      )}

      {loading && (
        <div aria-busy>
          <p className="text-12 text-ink-3">{t("review.loading")}</p>
          <SkeletonText className="mt-3" lines={6} />
        </div>
      )}

      {error && !loading && (
        <ErrorState title={t("review.error.title")} error={error} onRetry={retry} />
      )}

      {report && !loading && !error && (
        <>
          <ReportHeader report={report} counts={counts} />
          {report.findings.length === 0 ? (
            report.files === 0 ? (
              <EmptyState
                icon={Inbox}
                title={t("review.empty.title")}
                description={t("review.empty.description")}
                action={
                  <Button size="sm" onClick={() => setView("ingest")}>
                    {t("review.empty.action")}
                  </Button>
                }
              />
            ) : (
              <p className="max-w-measure text-14 text-ink-2">{t("review.clean")}</p>
            )
          ) : (
            <div className="flex flex-col gap-8">
              {pages.map((page) => (
                <PageSection key={page.path || "__library__"} page={page} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** What the report was read over, and how much of it there is to answer. */
function ReportHeader({
  report,
  counts,
}: {
  report: CheckReport;
  counts: Record<string, number>;
}) {
  const t = useT();
  const tOr = useTOr();
  // The kinds the report actually carried, in the order it carried them — a kind this build
  // has never heard of is counted and named rather than folded into "other".
  const kinds = Object.keys(counts);
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-14 text-ink">
          {t("review.counts.findings", { count: report.findings.length })}
        </span>
        {kinds.map((kind) => (
          <span key={kind} className="text-12 text-ink-2">
            {tOr(`review.kind.${kind}`, kind)} · {counts[kind]}
          </span>
        ))}
        <hr aria-hidden className="hidden min-w-8 flex-1 border-0 border-t border-line sm:block" />
        <span className="flex shrink-0 items-baseline gap-2 text-12 text-ink-3">
          <Mono>{shortSha(report.ref)}</Mono>
          {report.read_at && <span>{t("review.readAt", { time: fmtDateTime(report.read_at) })}</span>}
        </span>
      </div>
      <p className="max-w-measure text-13 text-ink-2">
        {t("review.counts.base", {
          files: report.files,
          subjects: report.subjects,
          claims: report.claims,
          edges: report.edges,
        })}
      </p>
    </section>
  );
}

/**
 * One page and everything the check says about it.
 *
 * The heading is the path, and it opens the document — the repair happens there, so the way in
 * is one click from the heading rather than buried in a row. A finding that names no page at
 * all keeps a group of its own, headed as the library rather than as a blank.
 */
function PageSection({ page }: { page: CheckPage }) {
  const t = useT();
  const jump = useApp((s) => s.jump);
  return (
    <section className="min-w-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line-2 pb-1.5">
        <h2 className="min-w-0">
          {page.path ? (
            <button
              type="button"
              title={t("review.openDocument")}
              onClick={() => jump({ kind: "document", id: page.path }, "library")}
              className="inline-flex max-w-full items-baseline gap-1 rounded-1 text-accent transition-colors duration-120 hover:text-ink"
            >
              <Mono className="truncate text-13">{page.path}</Mono>
              <ArrowUpRight size={12} aria-hidden className="shrink-0 translate-y-px" />
            </button>
          ) : (
            <span className="text-13 text-ink-2">{t("review.page.library")}</span>
          )}
        </h2>
        <span className="shrink-0 text-12 text-ink-3">
          {t("review.page.count", { count: page.findings.length })}
        </span>
      </div>
      <ul className="flex flex-col">
        {page.findings.map((finding) => (
          <FindingRow key={finding.key} finding={finding} />
        ))}
      </ul>
    </section>
  );
}
