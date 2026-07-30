import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";

export interface EmptyStateProps {
  icon: LucideIcon;
  title: ReactNode;
  /** One line of copy, naming the next action. */
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** The one empty implementation in the product: icon + one line + an optional action. */
export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-2 rounded-2 border border-dashed border-line-2 px-6 py-12 text-center",
        className,
      )}
    >
      <Icon size={20} aria-hidden className="text-ink-3" />
      <p className="text-14 font-medium text-ink">{title}</p>
      {description != null && <p className="max-w-measure text-13 text-ink-2">{description}</p>}
      {action != null && <div className="mt-2">{action}</div>}
    </div>
  );
}
