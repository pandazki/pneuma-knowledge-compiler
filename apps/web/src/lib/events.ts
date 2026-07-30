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
import { txOr } from "./i18n";

export type EventTone = "neutral" | "success" | "warning" | "danger" | "accent";

export interface EventMeta {
  label: string;
  icon: LucideIcon;
  tone: EventTone;
}

/**
 * Journal event model used by the public canonical projection. Icon + tone are presentation
 * facts and live here; the name comes from the dictionary, keyed by event type, and an
 * unknown type degrades to its raw machine name rather than to a blank.
 */
export const EVENT_ICONS: Record<string, { icon: LucideIcon; tone: EventTone }> = {
  job_created: { icon: CircleDashed, tone: "neutral" },
  job_planned: { icon: CircleDashed, tone: "neutral" },
  driver_started: { icon: CirclePlay, tone: "neutral" },
  driver_finished: { icon: Hammer, tone: "neutral" },
  gate_checked: { icon: FileCheck2, tone: "success" },
  gate_rejected: { icon: ShieldX, tone: "danger" },
  gate_repair_retry: { icon: RefreshCw, tone: "warning" },
  patch_committed: { icon: GitCommitHorizontal, tone: "success" },
  job_failed: { icon: XCircle, tone: "danger" },
  bundle_published: { icon: PackageCheck, tone: "accent" },
  viz_exported: { icon: Sparkles, tone: "accent" },
  bypass_reconciled: { icon: FilePlus2, tone: "warning" },
  rollback: { icon: RefreshCw, tone: "danger" },
  job_replanned: { icon: RefreshCw, tone: "warning" },
  limits_exceeded: { icon: ShieldAlert, tone: "warning" },
};

export function eventMeta(type: string): EventMeta {
  const known = EVENT_ICONS[type];
  return {
    label: txOr(`event.${type}`, type),
    icon: known?.icon ?? Flag,
    tone: known?.tone ?? "neutral",
  };
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
