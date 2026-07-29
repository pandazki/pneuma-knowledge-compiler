import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Sprout, UserRoundX } from "lucide-react";
import { useApp } from "@/lib/store";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import {
  buildEvolveTimeline,
  buildSchemaAxis,
  evolveTimelineCounts,
  isTerminalEvolveStatus,
  selectedTimelineEntry,
} from "@/lib/evolve";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { SkeletonText } from "@/ui/Skeleton";
import { Tabs } from "@/ui/Tabs";
import { EvolveTimeline } from "./EvolveTimeline";
import { EvolveTaskDetail } from "./EvolveTaskDetail";
import { SchemaAxisPanel } from "./SchemaAxisPanel";

/**
 * 演化 Evolve（DESIGN.md §5）。三个面：
 *
 * 1. **演化时间线**（`timeline` tab 左栏）：一次演化一刻度，状态即刻度形状与语义色。
 * 2. **任务详情**（`timeline` tab 右栏）：提案理由与证据行、pack 草案全文、消失的锚
 *    （人审重点）、变更文件 diff、闸门操作。
 * 3. **Schema 快照轴**（`schema` tab）：family / 路径模板随时间的累积，由「已采纳任务
 *    序列 × 当前 skill」推导。
 *
 * 数据面只有 `GET /evolve` 与 `GET /skill` 两个读端点，两个 tab 共用同一次取数。
 * hash 路由契约不变：`#/evolve/evolve-task/<id>` 仍然直达任务详情（选中即切回时间线）。
 */

type TabValue = "timeline" | "schema";

export default function EvolveView() {
  const currentUser = useApp((s) => s.currentUser);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const readOnly = currentSnapshot != null;

  const [skill, setSkill] = useState<api.SkillInfo | null>(null);
  const [skillState, setSkillState] = useState<"loading" | "ready" | "error">("loading");
  const [skillError, setSkillError] = useState<string | null>(null);

  const [tasks, setTasks] = useState<api.EvolveTaskSummary[]>([]);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [listError, setListError] = useState<string | null>(null);

  const [triggering, setTriggering] = useState(false);
  const [notice, setNotice] = useState<{
    tone: "warn" | "danger" | "notice";
    text: string;
  } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [tab, setTab] = useState<TabValue>("timeline");
  const detailRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  /* skill 面 */
  useEffect(() => {
    if (!currentUser) return;
    let live = true;
    setSkillState("loading");
    api
      .getSkillInfo(currentUser)
      .then((s) => {
        if (!live) return;
        setSkill(s);
        setSkillState("ready");
      })
      .catch((e: Error) => {
        if (!live) return;
        setSkillError(e.message);
        setSkillState("error");
      });
    return () => {
      live = false;
    };
  }, [currentUser, reloadKey]);

  /* 任务账 */
  useEffect(() => {
    if (!currentUser) return;
    let live = true;
    api
      .listEvolveTasks(currentUser)
      .then((rows) => {
        if (!live) return;
        setTasks(rows);
        setListState("ready");
      })
      .catch((e: Error) => {
        if (!live) return;
        setListError(e.message);
        setListState("error");
      });
    return () => {
      live = false;
    };
  }, [currentUser, reloadKey]);

  /* 轮询：有未决任务时每 5s 刷新；卸载清理。 */
  const needsPoll = tasks.some((t) => !isTerminalEvolveStatus(t.status));
  useEffect(() => {
    if (!currentUser || !needsPoll) return;
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [currentUser, needsPoll, refresh]);

  const timeline = useMemo(() => buildEvolveTimeline(tasks), [tasks]);
  const counts = useMemo(() => evolveTimelineCounts(timeline), [timeline]);
  const axis = useMemo(() => buildSchemaAxis(tasks, skill), [tasks, skill]);

  const selectedId = selection?.kind === "evolve-task" ? selection.id : null;
  const selectedEntry = selectedTimelineEntry(timeline, selectedId);

  /* 深链进来时（#/evolve/evolve-task/<id>）保证停在时间线 tab。 */
  useEffect(() => {
    if (selectedId) setTab("timeline");
  }, [selectedId]);

  const openTask = useCallback(
    (taskId: string) => {
      select({ kind: "evolve-task", id: taskId });
      setTab("timeline");
      if (window.matchMedia("(max-width: 1023px)").matches) {
        window.requestAnimationFrame(() => {
          detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      }
    },
    [select],
  );

  async function onTrigger() {
    if (!currentUser) return;
    setTriggering(true);
    setNotice(null);
    try {
      await api.triggerEvolve(currentUser);
      setNotice({
        tone: "notice",
        text: "已入队演化任务——worker 跑完后草案会出现在时间线顶端。",
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // single-flight：已有 draft 待审或任务进行中。
        setNotice({ tone: "warn", text: e.message });
      } else {
        setNotice({ tone: "danger", text: `触发失败：${(e as Error).message}` });
      }
    } finally {
      setTriggering(false);
      refresh();
    }
  }

  if (!currentUser) {
    return (
      <>
        <PageHeader
          title="演化 Evolve"
          description="schema 重组提案的评审台与 family 累积轴。"
        />
        <EmptyState
          icon={UserRoundX}
          title="未选择用户"
          description="在右上角选择一个 user_id，以查看它的演化时间线与量身定制 skill。"
        />
      </>
    );
  }

  const timelinePanel = (
    <>
      {listState === "loading" && <SkeletonText lines={6} />}
      {listState === "error" && (
        <ErrorState
          title="演化时间线加载失败"
          error={listError ?? "未知错误"}
          onRetry={refresh}
        />
      )}
      {listState === "ready" && timeline.length === 0 && (
        <EmptyState
          icon={Sprout}
          title="暂无演化任务"
          description="点右上角「触发演化」发起一次 schema 重组提案；草案会停在这里等待你的裁决。"
        />
      )}
      {listState === "ready" && timeline.length > 0 && (
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <div className="w-full shrink-0 lg:w-80">
            <p className="mb-2 text-12 text-ink-3">
              共 {counts.total} 次 · 待审 {counts.awaitingReview} · 已采用{" "}
              {counts.adopted} · 已否决 {counts.declined}
              {counts.noChange > 0 && ` · 无变化 ${counts.noChange}`}
            </p>
            <EvolveTimeline
              entries={timeline}
              selectedTaskId={selectedEntry?.taskId ?? null}
              onSelect={openTask}
            />
          </div>
          <div
            ref={detailRef}
            className="min-w-0 flex-1 scroll-mt-16 lg:border-l lg:border-line lg:pl-6"
          >
            {selectedEntry ? (
              <EvolveTaskDetail
                key={selectedEntry.taskId}
                userId={currentUser}
                taskId={selectedEntry.taskId}
                ordinal={selectedEntry.ordinal}
                readOnly={readOnly}
                onDecided={refresh}
              />
            ) : (
              <p className="text-13 text-ink-3">在左侧时间线选中一次演化查看详情。</p>
            )}
          </div>
        </div>
      )}
    </>
  );

  const schemaPanel = (
    <>
      {skillState === "loading" && <SkeletonText lines={6} />}
      {skillState === "error" && (
        <ErrorState
          title="skill 加载失败"
          error={skillError ?? "未知错误"}
          onRetry={refresh}
        />
      )}
      {skillState === "ready" && (
        <SchemaAxisPanel
          axis={axis}
          claimLabels={skill?.claim_labels ?? []}
          onOpenTask={openTask}
        />
      )}
    </>
  );

  return (
    <>
      <PageHeader
        title="演化 Evolve"
        description="演化时间线 · 草案评审（采用 / 放弃）· family 与路径模板的累积轴。"
        actions={
          <Button
            variant="primary"
            size="sm"
            loading={triggering}
            disabled={readOnly}
            title={readOnly ? "历史快照为只读" : undefined}
            onClick={onTrigger}
          >
            触发演化
          </Button>
        }
      />

      {notice && (
        <Callout tone={notice.tone} className="mb-6" onDismiss={() => setNotice(null)}>
          {notice.text}
        </Callout>
      )}

      <Tabs
        aria-label="演化视图"
        value={tab}
        onChange={(v) => setTab(v as TabValue)}
        tabs={[
          {
            value: "timeline",
            label: `时间线${counts.awaitingReview > 0 ? ` · ${counts.awaitingReview} 待审` : ""}`,
            panel: timelinePanel,
          },
          { value: "schema", label: "Schema 快照轴", panel: schemaPanel },
        ]}
      />
    </>
  );
}
