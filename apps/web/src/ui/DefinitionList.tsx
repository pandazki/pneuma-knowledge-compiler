import type { ReactNode } from "react";
import { cn } from "./cn";

export interface DefinitionItem {
  term: ReactNode;
  definition: ReactNode;
}

export interface DefinitionListProps {
  items: DefinitionItem[];
  /** Term column width (defaults to w-28). */
  termClassName?: string;
  className?: string;
}

/** Term / definition two-column list (used for the L0–L3 gloss), hairline between rows. */
export function DefinitionList({ items, termClassName, className }: DefinitionListProps) {
  return (
    <dl className={cn("flex flex-col", className)}>
      {items.map((item, i) => (
        <div
          key={i}
          className={cn(
            "flex flex-col gap-1 py-2.5 sm:flex-row sm:items-baseline sm:gap-4",
            i > 0 && "border-t border-line",
          )}
        >
          <dt className={cn("shrink-0 text-13 font-medium text-ink sm:w-28", termClassName)}>
            {item.term}
          </dt>
          <dd className="min-w-0 text-14 leading-[1.75] text-ink-2">{item.definition}</dd>
        </div>
      ))}
    </dl>
  );
}
