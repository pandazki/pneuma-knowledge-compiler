import { useCallback, useEffect, useState } from "react";
import { PackageOpen, UserRound } from "lucide-react";
import {
  compile,
  listJobs,
  type CompileResult,
  type JobSummary,
} from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { useApp } from "@/lib/store";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SkeletonText } from "@/ui/Skeleton";
import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/ui/cn";

/** 仍在流水线里的状态（轮询继续的依据）。 */
const ACTIVE_STATUSES = new Set(["queued", "running", "claimed"]);

/** 状态用文字 + 墨阶表达，failed 用 danger 文字；不用彩色灯。 */
function statusText(status: string): { label: string; className: string } {
  switch (status) {
    case "compiled":
      return { label: "已编译", className: "text-ink" };
    case "failed":
      return { label: "失败", className: "text-danger" };
    case "running":
    case "claimed":
      return { label: "运行中", className: "text-ink-2" };
    case "queued":
      return { label: "排队中", className: "text-ink-3" };
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

  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [compiling, setCompiling] = useState(false);
  const [compileResult, setCompileResult] = useState<CompileResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  // job 账页：装载一次；存在 running/queued（含 claimed）job 时每 3s 轮询，卸载清理。
  useEffect(() => {
    if (!currentUser) {
      setJobs(null);
      setLoadError(null);
      return;
    }
    let live = true;
    let timer: number | undefined;
    let loaded = false;
    const tick = async () => {
      try {
        const rows = await listJobs(currentUser);
        if (!live) return;
        loaded = true;
        setJobs(rows);
        setLoadError(null);
        if (rows.some((j) => ACTIVE_STATUSES.has(j.status))) {
          timer = window.setTimeout(tick, 3000);
        }
      } catch (e) {
        if (!live) return;
        // 首轮失败进 ErrorState；轮询中途失败保留旧列表，稍后重试。
        if (!loaded) setLoadError((e as Error).message);
        timer = window.setTimeout(tick, 3000);
      }
    };
    void tick();
    return () => {
      live = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [currentUser, reloadKey]);

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
        title="未选择用户"
        description="先在顶栏选择一个 user_id，再查看它的编译任务账页。"
      />
    );
  }

  return (
    <div className="flex max-w-measure flex-col gap-6">
      <PageHeader
        title="工序 Process"
        description="compile job 账页：每次编译一行——状态、来源、耗时与落版 ref。"
        actions={
          <Button
            variant="primary"
            loading={compiling}
            disabled={readOnly || compiling}
            title={readOnly ? "历史快照为只读" : "把未消化的 source 入 compile 队列"}
            onClick={() => void onCompile()}
          >
            触发编译
          </Button>
        }
      />

      {readOnly && (
        <Callout tone="info" title="历史快照 · 只读">
          正在查看历史快照，触发编译已禁用；切回 HEAD 后才能操作。
        </Callout>
      )}

      {/* patch deep-link：patch 归 History 管，这里只给跳转，不报错。 */}
      {patchSel && (
        <Callout tone="info">
          <span className="flex flex-wrap items-center gap-2">
            <span>
              此 patch <Mono>{patchSel.id}</Mono> 在「版本 History」查看。
            </span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => jump({ kind: "patch", id: patchSel.id }, "history")}
            >
              去版本 History
            </Button>
          </span>
        </Callout>
      )}

      {compileResult && (
        <Callout tone="notice" title="已入队" onDismiss={() => setCompileResult(null)}>
          {compileResult.enqueued.length > 0 ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {compileResult.enqueued.map((id) => (
                <Mono key={id} className="break-all">
                  {id}
                </Mono>
              ))}
            </span>
          ) : (
            "没有待编译的 source（全部已消化）。"
          )}
        </Callout>
      )}
      {compileError && (
        <Callout tone="danger" title="触发编译失败" onDismiss={() => setCompileError(null)}>
          <Mono className="break-all">{compileError}</Mono>
        </Callout>
      )}

      {loadError ? (
        <ErrorState title="加载 job 账页失败" error={loadError} onRetry={reload} />
      ) : jobs == null ? (
        <SkeletonText lines={8} />
      ) : jobs.length === 0 ? (
        <EmptyState
          icon={PackageOpen}
          title="尚无编译任务"
          description="先在「导入 Ingest」添加原料，再回到这里触发编译。"
          action={
            <Button size="sm" onClick={() => setView("ingest")}>
              去导入
            </Button>
          }
        />
      ) : (
        <ul className="flex flex-col border-y border-line">
          {jobs.map((j) => {
            const expanded = j.job_id === selectedJobId;
            const st = statusText(j.status);
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
                      创建 <Mono>{fmtTime(j.created_at)}</Mono>
                    </span>
                    <span>
                      完成 <Mono>{fmtTime(j.completed_at)}</Mono>
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
      )}
    </div>
  );
}

/** 选中 job 的展开详情：来源、detail 与落版信息。 */
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
