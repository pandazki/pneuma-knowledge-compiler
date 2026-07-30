import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Sprout, UserRoundX } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
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
 * Evolve (DESIGN.md §5). Three surfaces:
 *
 * 1. **The evolution timeline** (left column of the `timeline` tab): one station per
 *    evolution, where the status IS the station's shape and semantic colour.
 * 2. **The task detail** (right column of the `timeline` tab): the proposal's reasoning and
 *    evidence lines, the pack drafts in full, the anchors that disappear (what a human review
 *    turns on), the changed-file diffs, and the gate actions.
 * 3. **The schema axis** (`schema` tab): how families / path templates accumulate over time,
 *    derived from "the adopted task sequence × the current skill".
 *
 * There are only two read endpoints behind it, `GET /evolve` and `GET /skill`, and both tabs
 * share one fetch. The hash-route contract is unchanged: `#/evolve/evolve-task/<id>` still
 * lands on the task detail (a selection switches back to the timeline).
 */

type TabValue = "timeline" | "schema";

export default function EvolveView() {
  const t = useT();
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

  /* The skill surface */
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

  /* The task ledger */
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

  /* Polling: refresh every 5s while a task is unsettled; cleared on unmount. */
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

  /* Arriving by deep link (#/evolve/evolve-task/<id>) must land on the timeline tab. */
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
      setNotice({ tone: "notice", text: t("evolve.notice.queued") });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // single-flight: a draft is already awaiting review, or a task is in flight.
        setNotice({ tone: "warn", text: e.message });
      } else {
        setNotice({
          tone: "danger",
          text: t("evolve.notice.triggerFailed", { detail: (e as Error).message }),
        });
      }
    } finally {
      setTriggering(false);
      refresh();
    }
  }

  if (!currentUser) {
    return (
      <>
        <PageHeader title={t("evolve.title")} description={t("evolve.descriptionShort")} />
        <EmptyState
          icon={UserRoundX}
          title={t("evolve.noUser.title")}
          description={t("evolve.noUser.description")}
        />
      </>
    );
  }

  const timelinePanel = (
    <>
      {listState === "loading" && <SkeletonText lines={6} />}
      {listState === "error" && (
        <ErrorState
          title={t("evolve.timeline.loadFailed")}
          error={listError ?? t("common.unknownError")}
          onRetry={refresh}
        />
      )}
      {listState === "ready" && timeline.length === 0 && (
        <EmptyState
          icon={Sprout}
          title={t("evolve.timeline.empty.title")}
          description={t("evolve.timeline.empty.description")}
        />
      )}
      {listState === "ready" && timeline.length > 0 && (
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <div className="w-full shrink-0 lg:w-80">
            <p className="mb-2 text-12 text-ink-3">
              {t("evolve.timeline.counts", {
                total: counts.total,
                awaiting: counts.awaitingReview,
                adopted: counts.adopted,
                declined: counts.declined,
              })}
              {counts.noChange > 0 &&
                ` · ${t("evolve.timeline.countsNoChange", { count: counts.noChange })}`}
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
              <p className="text-13 text-ink-3">{t("evolve.detail.pickHint")}</p>
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
          title={t("evolve.skill.loadFailed")}
          error={skillError ?? t("common.unknownError")}
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
        title={t("evolve.title")}
        description={t("evolve.description")}
        actions={
          <Button
            variant="primary"
            size="sm"
            loading={triggering}
            disabled={readOnly}
            title={readOnly ? t("evolve.readOnlyHint") : undefined}
            onClick={onTrigger}
          >
            {t("evolve.trigger")}
          </Button>
        }
      />

      {notice && (
        <Callout tone={notice.tone} className="mb-6" onDismiss={() => setNotice(null)}>
          {notice.text}
        </Callout>
      )}

      <Tabs
        aria-label={t("evolve.tabs.aria")}
        value={tab}
        onChange={(v) => setTab(v as TabValue)}
        tabs={[
          {
            value: "timeline",
            label:
              counts.awaitingReview > 0
                ? t("evolve.tab.timelineAwaiting", { count: counts.awaitingReview })
                : t("evolve.tab.timeline"),
            panel: timelinePanel,
          },
          { value: "schema", label: t("evolve.tab.schema"), panel: schemaPanel },
        ]}
      />
    </>
  );
}
