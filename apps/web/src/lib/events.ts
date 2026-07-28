import {
  CheckCircle2,
  CircleDashed,
  CirclePlay,
  FileCheck2,
  FilePlus2,
  Flag,
  GitCommitHorizontal,
  Hammer,
  PackageCheck,
  RefreshCw,
  ShieldAlert,
  ShieldX,
  Sparkles,
  XCircle,
  type LucideIcon,
} from "lucide-react";

export type EventTone = "neutral" | "success" | "warning" | "danger" | "accent";

export interface EventMeta {
  label: string;
  icon: LucideIcon;
  tone: EventTone;
}

/** Journal event model used by the public canonical projection. */
export const EVENT_META: Record<string, EventMeta> = {
  job_created: { label: "Job 创建", icon: CircleDashed, tone: "neutral" },
  job_planned: { label: "Job 规划", icon: CircleDashed, tone: "neutral" },
  driver_started: { label: "Driver 启动", icon: CirclePlay, tone: "neutral" },
  driver_finished: { label: "Driver 完成", icon: Hammer, tone: "neutral" },
  gate_checked: { label: "Gate 校验通过", icon: FileCheck2, tone: "success" },
  gate_rejected: { label: "Gate 拒绝", icon: ShieldX, tone: "danger" },
  gate_repair_retry: { label: "Gate 修复重试", icon: RefreshCw, tone: "warning" },
  patch_committed: { label: "Patch 提交", icon: GitCommitHorizontal, tone: "success" },
  job_failed: { label: "Job 失败", icon: XCircle, tone: "danger" },
  bundle_published: { label: "Bundle 发布", icon: PackageCheck, tone: "accent" },
  viz_exported: { label: "Viz 导出", icon: Sparkles, tone: "accent" },
  bypass_reconciled: { label: "旁路收编", icon: FilePlus2, tone: "warning" },
  rollback: { label: "回滚", icon: RefreshCw, tone: "danger" },
  job_replanned: { label: "Job 重规划", icon: RefreshCw, tone: "warning" },
  limits_exceeded: { label: "超限告警", icon: ShieldAlert, tone: "warning" },
};

export function eventMeta(type: string): EventMeta {
  return EVENT_META[type] ?? { label: type, icon: Flag, tone: "neutral" };
}

export function toneColor(tone: EventTone): string {
  switch (tone) {
    case "success":
      return "var(--color-verified)";
    case "warning":
      return "var(--color-open-question)";
    case "danger":
      return "var(--color-disputed)";
    case "accent":
      return "var(--color-accent)";
    default:
      return "var(--color-text-tertiary)";
  }
}

export const JOB_STATUS_ICON: Record<string, LucideIcon> = {
  compiled: CheckCircle2,
  failed: XCircle,
  running: CircleDashed,
};
