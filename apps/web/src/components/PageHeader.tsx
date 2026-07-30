import type { ReactNode } from "react";
import { cn } from "@/ui/cn";

export interface PageHeaderProps {
  /** Serif page title (24/30). */
  title: ReactNode;
  /** One ink-2 line of description. */
  description?: ReactNode;
  /** Action area on the right. */
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
  return (
    <header className={cn("mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3", className)}>
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="font-serif text-24 text-balance text-ink">{title}</h1>
        {description != null && <p className="max-w-measure text-14 text-ink-2">{description}</p>}
      </div>
      {actions != null && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}
