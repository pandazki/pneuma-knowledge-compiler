import type { ReactNode } from "react";
import { cn } from "./cn";

export interface SectionRuleProps {
  /** Section number (1 → §01; an already-formed string is accepted too). */
  no: number | string;
  title: ReactNode;
  actions?: ReactNode;
  className?: string;
}

function formatNo(no: number | string): string {
  if (typeof no === "number") return `§${String(no).padStart(2, "0")}`;
  return no.startsWith("§") ? no : `§${no}`;
}

/** Section hairline: § number + title + rule. Structural sectioning, instead of cards. */
export function SectionRule({ no, title, actions, className }: SectionRuleProps) {
  return (
    <div className={cn("flex items-baseline gap-3", className)}>
      <span className="shrink-0 font-mono text-12 text-accent">{formatNo(no)}</span>
      <h2 className="shrink-0 font-serif text-20 text-ink">{title}</h2>
      <hr aria-hidden className="min-w-8 flex-1 border-0 border-t border-line" />
      {actions != null && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
