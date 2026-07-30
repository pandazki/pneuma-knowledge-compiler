import type { ReactNode } from "react";
import { cn } from "./cn";

/** Shortcut hint (a small mono keycap). */
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-1 border border-line-2 border-b-2 bg-surface px-1",
        "font-mono text-12 text-ink-2",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
