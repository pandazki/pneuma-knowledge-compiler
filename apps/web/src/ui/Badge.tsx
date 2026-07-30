import type { ReactNode } from "react";
import { cn } from "./cn";

export type BadgeTone = "neutral" | "accent" | "ok" | "warn" | "danger";

const TONES: Record<BadgeTone, string> = {
  neutral: "border-line-2 bg-surface text-ink-2",
  accent: "border-accent-line bg-accent-soft text-accent",
  ok: "border-transparent bg-ok-soft text-ok",
  warn: "border-transparent bg-warn-soft text-warn",
  danger: "border-transparent bg-danger-soft text-danger",
};

/** Small neutral tag; semantic colour is reserved for real state. */
export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-1 border px-1.5 text-12 font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
