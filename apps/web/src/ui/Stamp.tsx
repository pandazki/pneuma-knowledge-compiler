import type { ReactNode } from "react";
import { cn } from "./cn";

export type StampTone = "neutral" | "accent" | "ok" | "warn" | "danger";

const TONES: Record<StampTone, string> = {
  neutral: "border-ink-2 text-ink-2",
  accent: "border-accent text-accent",
  ok: "border-ok text-ok",
  warn: "border-warn text-warn",
  danger: "border-danger text-danger",
};

/**
 * Archive stamp: an outlined mark rotated -2deg. Only for read-only / synthetic / real-state
 * facts, outlined in a semantic colour. Not a decorative sticker.
 */
export function Stamp({
  tone = "neutral",
  children,
  className,
}: {
  tone?: StampTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex -rotate-2 items-center gap-1 rounded-1 border-2 px-2 py-0.5",
        "text-12 font-medium tracking-wide whitespace-nowrap select-none",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
