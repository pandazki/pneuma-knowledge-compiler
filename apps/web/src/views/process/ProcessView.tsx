import { useCallback, useEffect, useState } from "react";
import { PackageOpen, UserRound } from "lucide-react";
import {
  compile,
  listJobs,
  type CompileResult,
  type JobSummary,
} from "@/lib/api";
import { fmtTime } from "@/lib/format";
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
import { SkeletonText } from "@/ui/Skeleton";
import { PageHeader } from "@/components/PageHeader";
import { PaginationBar } from "@/components/PaginationBar";
import { cn } from "@/ui/cn";

/** The statuses still in the pipeline (what keeps the poll going). */
const ACTIVE_STATUSES = new Set(["queued", "running", "claimed"]);
const PAGE_SIZE = 25;

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
  const [pageState, setPageState] = useState<CursorPageState>(firstPage);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [compiling, setCompiling] = useState(false);
  const [compileResult, setCompileResult] = useState<CompileResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);

  const jobs = jobPage?.items ?? null;

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

  const selectedJobId = selection?.kind === "job" ? selection.id : null;
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
                  {expanded && <JobDetail job={j} />}
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

/** The selected job, expanded: its sources, `detail` and where it landed. */
function JobDetail({ job }: { job: JobSummary }) {
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
                    <Mono key={id} className="break-all">
                      {id}
                    </Mono>
                  ))}
                </span>
              ) : (
                "—"
              ),
          },
          { term: "detail", definition: job.detail ?? "—" },
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
        ]}
      />
    </div>
  );
}
