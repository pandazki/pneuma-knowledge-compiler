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
 * 档案戳：旋转 -2deg 的线框章。仅用于「只读 / synthetic / 真实状态」，
 * 用语义色描边；不要当装饰贴纸到处贴。
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
