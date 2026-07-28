import { useEffect, useMemo, useState } from "react";
import { useApp } from "@/lib/store";
import type { JobRecord } from "@/lib/types";
import { patchNum } from "@/lib/model";
import { JobCard } from "@/components/JobCard";
import { JournalReplay } from "@/components/JournalReplay";
import { Eyebrow, SegmentedControl } from "@/components/ui";
import { cn } from "@/lib/cn";

type StatusFilter = "all" | "failed" | "compiled" | "running";

export function ProcessView() {
  const { model, selection } = useApp();
  const [replayJob, setReplayJob] = useState<string | "all">("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [onlyFlags, setOnlyFlags] = useState(false);
  const [onlyEscalations, setOnlyEscalations] = useState(false);

  const journal = model?.dataset.journal ?? [];

  // Newest-first: an audit starts from the latest compile. Sort by ts desc, then
  // patch number desc as a tiebreak.
  const jobs = useMemo<JobRecord[]>(() => {
    const raw = model?.dataset.timeline.jobs ?? [];
    return [...raw].sort((a, b) => {
      const t = (b.ts ?? "").localeCompare(a.ts ?? "");
      if (t !== 0) return t;
      return patchNum(b.patch_id ?? "") - patchNum(a.patch_id ?? "");
    });
  }, [model]);

  // default replay target = newest job; keep in sync when data changes
  useEffect(() => {
    if (jobs.length && replayJob === "all") setReplayJob(jobs[0].job_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs.length]);

  // respond to cross-view selection of a patch/job by focusing its card + replay
  useEffect(() => {
    if (!selection) return;
    let jid: string | null = null;
    if (selection.kind === "job") jid = selection.id;
    else if (selection.kind === "patch") {
      jid = jobs.find((j) => j.patch_id === selection.id)?.job_id ?? null;
    }
    if (jid) {
      setReplayJob(jid);
      document.getElementById(`job-${jid}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection]);

  const replayEvents = useMemo(
    () => (replayJob === "all" ? journal : journal.filter((e) => e.job_id === replayJob)),
    [journal, replayJob],
  );

  // apply audit filters
  const shownJobs = useMemo(() => {
    if (!model) return [] as JobRecord[];
    return jobs.filter((job) => {
      if (statusFilter !== "all" && job.status !== statusFilter) return false;
      const patch = job.patch_id ? model.patchById.get(job.patch_id) : null;
      if (onlyFlags) {
        const n = patch ? Object.values(patch.flag_counts ?? {}).reduce((s, v) => s + v, 0) : 0;
        if (n === 0) return false;
      }
      if (onlyEscalations && !(patch?.escalations?.length)) return false;
      return true;
    });
  }, [jobs, statusFilter, onlyFlags, onlyEscalations, model]);

  if (!model) return null;

  const activeJobId =
    selection?.kind === "job"
      ? selection.id
      : selection?.kind === "patch"
        ? jobs.find((j) => j.patch_id === selection.id)?.job_id
        : replayJob !== "all"
          ? replayJob
          : null;

  return (
    <div className="flex h-full min-h-0">
      {/* job / patch card stream */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-6">
          <Eyebrow>Process · {jobs.length} 个 compile job</Eyebrow>
          <p className="mt-2 mb-4 text-sm text-muted-foreground max-w-prose">
            每次 compile 是一张卡片：driver 写出的文档按 created / modified / conflict 分行，
            连同 patch 元数据（模型、token、来源、escalation）。审阅先看出问题的地方——
            用下方筛选隔离 failed、带 flag 或带 escalation 的 job；选“回放”在右侧按 journal
            事件序重演该 compile。
          </p>

          {/* audit filters */}
          <div className="flex flex-wrap items-center gap-2 mb-5">
            <SegmentedControl<StatusFilter>
              segments={[
                { value: "all", label: "全部" },
                { value: "failed", label: "失败" },
                { value: "compiled", label: "已编译" },
                { value: "running", label: "运行中" },
              ]}
              value={statusFilter}
              onChange={setStatusFilter}
            />
            <FilterToggle active={onlyFlags} onClick={() => setOnlyFlags((v) => !v)}>
              含 flag
            </FilterToggle>
            <FilterToggle active={onlyEscalations} onClick={() => setOnlyEscalations((v) => !v)}>
              含 escalation
            </FilterToggle>
            <span className="text-[length:var(--text-2xs)] text-muted-foreground ml-auto">
              {shownJobs.length} / {jobs.length} job
            </span>
          </div>

          <div className="space-y-4">
            {shownJobs.map((job) => (
              <JobCard
                key={job.job_id}
                job={job}
                patch={job.patch_id ? (model.patchById.get(job.patch_id) ?? null) : null}
                model={model}
                active={activeJobId === job.job_id}
                onReplay={() => setReplayJob(job.job_id)}
              />
            ))}
            {jobs.length === 0 && (
              <div className="text-sm text-muted-foreground py-8">timeline.json 未记录任何 compile job。</div>
            )}
            {jobs.length > 0 && shownJobs.length === 0 && (
              <div className="text-sm text-muted-foreground py-8">没有符合当前筛选的 job。</div>
            )}
          </div>
        </div>
      </div>

      {/* replay rail */}
      <aside className="w-[24rem] flex-none border-l border-border bg-card flex flex-col min-h-0">
        <div className="px-4 pt-3">
          <SegmentedControl
            className="w-full [&>button]:flex-1"
            segments={[
              { value: "all", label: "全流程" },
              { value: "job", label: "单次 compile" },
            ]}
            value={replayJob === "all" ? "all" : "job"}
            onChange={(v) => setReplayJob(v === "all" ? "all" : jobs[0]?.job_id ?? "all")}
          />
        </div>
        <div className="flex-1 min-h-0 mt-2">
          <JournalReplay
            events={replayEvents}
            label={replayJob === "all" ? "全 workspace 事件流" : replayJob}
          />
        </div>
      </aside>
    </div>
  );
}

function FilterToggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "h-8 px-3 text-[length:var(--text-sm)] font-medium rounded-sm border transition-colors",
        "outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-[var(--color-surface-inverse)] text-[var(--color-text-inverse)] border-[var(--color-surface-inverse)]"
          : "bg-card text-muted-foreground border-border hover:bg-accent hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
