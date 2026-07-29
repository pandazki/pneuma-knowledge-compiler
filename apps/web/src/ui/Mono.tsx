import type { ComponentPropsWithoutRef } from "react";
import { cn } from "./cn";

/** 等宽内联：ID / ref / 路径 / 计数；自动 tabular-nums。不给中文正文用。 */
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
