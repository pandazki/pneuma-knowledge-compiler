import type { ComponentPropsWithoutRef } from "react";
import { cn } from "./cn";

/** Inline monospace: ids / refs / paths / counts, tabular-nums. Never for CJK prose. */
export function Mono({
  children,
  className,
  ...props
}: ComponentPropsWithoutRef<"span">) {
  return (
    <span
      className={cn("font-mono text-[0.92em] tabular-nums", className)}
      {...props}
    >
      {children}
    </span>
  );
}
