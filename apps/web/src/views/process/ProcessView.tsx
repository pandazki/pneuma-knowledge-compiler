import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PackageOpen, UserRound } from "lucide-react";
import {
  compile,
  listJobs,
  type CompileResult,
  type JobSummary,
} from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { splitGateDetail } from "@/lib/jobDetail";
import { locateStep, type LocateWalk } from "@/lib/jobLocate";
import {
  firstPage,
  nextPage,
  previousPage,
  type CursorPageState,
  type Page,
} from "@/lib/pagination";
import { useApp } from "@/lib/store";
import { useT, type TFunction } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { UsageLine } from "@/views/_shared/UsageLine";
import { SkeletonText } from "@/ui/Skeleton";
import { PageHeader } from "@/components/PageHeader";
import { PaginationBar } from "@/components/PaginationBar";
import { useSourceTitles } from "../_shared/useSourceTitles";
import { cn } from "@/ui/cn";

/** The statuses still in the pipeline (what keeps the poll going). */
const ACTIVE_STATUSES = new Set(["queued", "running", "claimed"]);
const PAGE_SIZE = 25;

/**
 * How far a deep link will page forward looking for its job before saying it cannot find it.
 * A bound rather than a full crawl: a queue runs to five figures, and a link into one is
 * always into recent work — walking two hundred pages to prove a negative is not a search,
 * it is a denial of service against one's own API. There is no `GET /jobs/{id}` route to ask
 * directly (see the report's API gaps), which is the only reason this pages at all.
 */
const LOCATE_PAGE_LIMIT = 8;

/**
 * Status as words + an ink step, `failed` in danger text; no coloured lamps. An unknown
 * status renders as its raw machine name rather than as a blank.
 */
function statusText(
  t: TFunction,
  status: string,
  ok: boolean | null,
): { label: string; className: string } {
  switch (status) {
    // The queue's terminal status is `done`, and `ok` says whether the job actually landed:
    // a gate-rejected compile is `done` with `ok: false`, and that is a failed job.
    case "done":
      if (ok === false) return { label: t("process.status.failed"), className: "text-danger" };
      return { label: t("process.status.compiled"), className: "text-ink" };
    case "compiled":
      return { label: t("process.status.compiled"), className: "text-ink" };
    case "failed":
      return { label: t("process.status.failed"), className: "text-danger" };
    case "running":
    case "claimed":
      return { label: t("process.status.running"), className: "text-ink-2" };
    case "queued":
      return { label: t("process.status.queued"), className: "text-ink-3" };
    default:
      return { label: status, className: "text-ink-2" };
  }
}

export default function ProcessView() {
  const currentUser = useApp((s) => s.currentUser);
  const readOnly = useApp((s) => s.currentSnapshot != null);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const setView = useApp((s) => s.setView);
  const jump = useApp((s) => s.jump);
  const t = useT();

  const [jobPage, setJobPage] = useState<Page<JobSummary> | null>(null);
  /** The cursor `jobPage` was loaded with — the walk below must know which page it is reading. */
  const [jobPageCursor, setJobPageCursor] = useState<string | null>(null);
  const [pageState, setPageState] = useState<CursorPageState>(firstPage);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [compiling, setCompiling] = useState(false);
  const [compileResult, setCompileResult] = useState<CompileResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);

  const jobs = jobPage?.items ?? null;
  const selectedJobId = selection?.kind === "job" ? selection.id : null;

  /**
   * L4 — a deep link into the ledger lands on whichever page the job is on.
   *
   * `#/process/job/<id>` used to do nothing at all when the job was not in the 25 rows
   * already loaded: the row it wanted to expand was not in the DOM. The page now walks
   * forward from the first page until it finds it, and says so plainly when it does not.
   */
  const [locating, setLocating] = useState(false);
  const [locateFailed, setLocateFailed] = useState<string | null>(null);
  const locateRef = useRef<LocateWalk | null>(null);

  const reload = useCallback(() => {
    setPageState(firstPage());
    setReloadKey((k) => k + 1);
  }, []);

  useEffect(() => {
    setPageState(firstPage());
  }, [currentUser]);

  // The job ledger: loaded once; polled every 3s while a running/queued (or claimed) job is
  // present, and cleaned up on unmount.
  useEffect(() => {
    if (!currentUser) {
      setJobPage(null);
      setLoadError(null);
      return;
    }
    let live = true;
    let timer: number | undefined;
    let loaded = false;
    const tick = async () => {
      try {
        const page = await listJobs(currentUser, {
          limit: PAGE_SIZE,
          cursor: pageState.cursor,
        });
        if (!live) return;
        const rows = page.items;
        loaded = true;
        setJobPage(page);
        setJobPageCursor(pageState.cursor);
        setLoadError(null);
        if (rows.some((j) => ACTIVE_STATUSES.has(j.status))) {
          timer = window.setTimeout(tick, 3000);
        }
      } catch (e) {
        if (!live) return;
        // A first-round failure becomes an ErrorState; a failure mid-poll keeps the old list
        // and retries shortly.
        if (!loaded) setLoadError((e as Error).message);
        timer = window.setTimeout(tick, 3000);
      }
    };
    void tick();
    return () => {
      live = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [currentUser, pageState.cursor, reloadKey]);

  useEffect(() => {
    if (!selectedJobId) {
      locateRef.current = null;
      setLocating(false);
      setLocateFailed(null);
      return;
    }
    if (!jobPage) return;
    const step = locateStep(
      locateRef.current,
      selectedJobId,
      {
        ids: jobPage.items.map((j) => j.job_id),
        loadedCursor: jobPageCursor,
        nextCursor: jobPage.page.next_cursor,
      },
      LOCATE_PAGE_LIMIT,
    );
    switch (step.kind) {
      case "settled":
        return;
      case "found":
        locateRef.current = step.walk;
        setLocating(false);
        setLocateFailed(null);
        return;
      case "restart":
        // Start from the top — the job may be on a page BEHIND the one being read.
        locateRef.current = step.walk;
        setLocateFailed(null);
        setLocating(true);
        setPageState(firstPage());
        return;
      case "give-up":
        locateRef.current = step.walk;
        setLocating(false);
        setLocateFailed(selectedJobId);
        return;
      case "advance":
        locateRef.current = step.walk;
        setLocateFailed(null);
        setLocating(true);
        setPageState((state) => nextPage(state, step.cursor));
        return;
    }
  }, [jobPage, jobPageCursor, selectedJobId]);

  async function onCompile() {
    if (!currentUser) return;
    setCompiling(true);
    setCompileResult(null);
    setCompileError(null);
    try {
      setCompileResult(await compile(currentUser));
      reload();
    } catch (e) {
      setCompileError((e as Error).message);
    } finally {
      setCompiling(false);
    }
  }

  const patchSel = selection?.kind === "patch" ? selection : null;

  if (!currentUser) {
    return (
      <EmptyState
        icon={UserRound}
        title={t("process.noUser.title")}
        description={t("process.noUser.description")}
      />
    );
  }

  return (
    <div className="flex max-w-measure flex-col gap-6">
      <PageHeader
        title={t("nav.view.process")}
        description={t("process.description")}
        actions={
          <Button
            variant="primary"
            loading={compiling}
            disabled={readOnly || compiling}
            title={
              readOnly ? t("process.compile.readOnlyHint") : t("process.compile.hint")
            }
            onClick={() => void onCompile()}
          >
            {t("process.compile.action")}
          </Button>
        }
      />

      {readOnly && (
        <Callout tone="info" title={t("nav.snapshotBanner")}>
          {t("process.readOnly.body")}
        </Callout>
      )}

      {/* patch deep-link: patches belong to History, so this only offers the jump — no error. */}
      {patchSel && (
        <Callout tone="info">
          <span className="flex flex-wrap items-center gap-2">
            <span>
              {t("process.patch.prefix")} <Mono>{patchSel.id}</Mono>{" "}
              {t("process.patch.suffix")}
            </span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => jump({ kind: "patch", id: patchSel.id }, "history")}
            >
              {t("process.patch.goHistory")}
            </Button>
          </span>
        </Callout>
      )}

      {compileResult && (
        <Callout
          tone="notice"
          title={t("process.enqueued.title")}
          onDismiss={() => setCompileResult(null)}
        >
          {compileResult.enqueued.length > 0 ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {compileResult.enqueued.map((id) => (
                <Mono key={id} className="break-all">
                  {id}
                </Mono>
              ))}
            </span>
          ) : (
            t("process.enqueued.none")
          )}
        </Callout>
      )}
      {compileError && (
        <Callout
          tone="danger"
          title={t("process.compile.failed")}
          onDismiss={() => setCompileError(null)}
        >
          <Mono className="break-all">{compileError}</Mono>
        </Callout>
      )}

      {locating && (
        <Callout tone="info">
          {t("process.locate.searching", { job: selectedJobId ?? "" })}
        </Callout>
      )}
      {locateFailed && (
        <Callout tone="warn" onDismiss={() => setLocateFailed(null)}>
          {t("process.locate.notFound", {
            job: locateFailed,
            count: LOCATE_PAGE_LIMIT * PAGE_SIZE,
          })}
        </Callout>
      )}

      {loadError ? (
        <ErrorState title={t("process.loadFailed")} error={loadError} onRetry={reload} />
      ) : jobs == null ? (
        <SkeletonText lines={8} />
      ) : jobs.length === 0 ? (
        <EmptyState
          icon={PackageOpen}
          title={t("process.empty.title")}
          description={t("process.empty.description")}
          action={
            <Button size="sm" onClick={() => setView("ingest")}>
              {t("process.empty.action")}
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-3">
          <ul className="flex flex-col border-y border-line">
            {jobs.map((j) => {
              const expanded = j.job_id === selectedJobId;
              const st = statusText(t, j.status, j.ok);
              return (
                <li key={j.job_id} className="border-b border-line last:border-b-0">
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() =>
                      select(expanded ? null : { kind: "job", id: j.job_id })
                    }
                    className={cn(
                      "relative flex w-full flex-col gap-1.5 px-3 py-2.5 text-left",
                      "transition-colors duration-120 ease-out",
                      expanded ? "bg-accent-soft" : "hover:bg-hover",
                    )}
                  >
                    {expanded && (
                      <span aria-hidden className="absolute inset-y-0 left-0 w-0.5 bg-accent" />
                    )}
                    <span className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
                      <Mono className="min-w-0 break-all text-13 text-ink">{j.job_id}</Mono>
                      <Badge>{j.kind}</Badge>
                      <span className={cn("text-13", st.className)}>{st.label}</span>
                    </span>
                    <span className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-12 text-ink-3">
                      <span>
                        {t("process.row.created")} <Mono>{fmtTime(j.created_at)}</Mono>
                      </span>
                      <span>
                        {t("process.row.completed")} <Mono>{fmtTime(j.completed_at)}</Mono>
                      </span>
                      {j.snapshot_ref && (
                        <span>
                          snapshot <Mono className="break-all">{j.snapshot_ref}</Mono>
                        </span>
                      )}
                    </span>
                  </button>
                  {expanded && <JobDetail job={j} userId={currentUser} />}
                </li>
              );
            })}
          </ul>
          <PaginationBar
            pageIndex={pageState.previous.length}
            limit={PAGE_SIZE}
            itemCount={jobs.length}
            total={jobPage?.page.total ?? jobs.length}
            hasNext={jobPage?.page.next_cursor != null}
            noun={t("process.jobNoun")}
            onPrevious={() => setPageState((state) => previousPage(state))}
            onNext={() => {
              const cursor = jobPage?.page.next_cursor;
              if (cursor) setPageState((state) => nextPage(state, cursor));
            }}
          />
        </div>
      )}
    </div>
  );
}

/**
 * The selected job, expanded: its sources, `detail` and where it landed.
 *
 * Two things a bare ledger row could not say. A job's sources are named — the titles are
 * fetched on demand through the shared cache, and a row that opens the galley is the shortest
 * path from "this compile failed" to "on what material". And a gate rejection is shown as the
 * findings it is: the gate joins its reasons with `; `, and one paragraph of five refusals is
 * a paragraph nobody counts.
 */
function JobDetail({ job, userId }: { job: JobSummary; userId: string }) {
  const t = useT();
  const jump = useApp((s) => s.jump);
  const { titles } = useSourceTitles(userId, job.source_ids);
  const reasons = useMemo(() => splitGateDetail(job.detail), [job.detail]);
  return (
    <div className="border-t border-line bg-surface px-3 py-3">
      <DefinitionList
        termClassName="sm:w-32"
        items={[
          {
            term: "source_ids",
            definition:
              job.source_ids.length > 0 ? (
                <span className="flex flex-col gap-1">
                  {job.source_ids.map((id) => (
                    <button
                      key={id}
                      type="button"
                      title={t("process.job.openSource")}
                      onClick={() => jump({ kind: "source", id }, "sources")}
                      className="flex min-w-0 flex-col items-start gap-0.5 rounded-1 px-1 py-0.5 text-left transition-colors duration-120 hover:bg-hover"
                    >
                      <span className="min-w-0 text-13 text-accent">
                        {titles[id] ?? t("process.job.sourceUntitled")}
                      </span>
                      <Mono className="break-all text-12 text-ink-3">{id}</Mono>
                    </button>
                  ))}
                </span>
              ) : (
                "—"
              ),
          },
          {
            term: "detail",
            definition:
              reasons.length === 0 ? (
                "—"
              ) : reasons.length === 1 ? (
                <span className="text-13">{reasons[0]}</span>
              ) : (
                <ol className="flex flex-col gap-1">
                  {reasons.map((reason, i) => (
                    <li key={i} className="flex gap-2 text-13">
                      <Mono className="shrink-0 text-12 text-ink-3">{i + 1}</Mono>
                      <span className="min-w-0">{reason}</span>
                    </li>
                  ))}
                </ol>
              ),
          },
          {
            term: "snapshot_ref",
            definition: job.snapshot_ref ? (
              <Mono className="break-all">{job.snapshot_ref}</Mono>
            ) : (
              "—"
            ),
          },
          {
            term: "ok",
            definition:
              job.ok == null ? "—" : job.ok ? "true" : "false",
          },
          // Compile is the system's biggest spender. Until the job row carried its own
          // usage, this was the one place money went and nothing said how much.
          {
            term: "token_usage",
            definition:
              job.token_usage && Object.keys(job.token_usage).length > 0 ? (
                <UsageLine usage={job.token_usage} cost={job.cost} className="mt-0" />
              ) : (
                "—"
              ),
          },
        ]}
      />
    </div>
  );
}
