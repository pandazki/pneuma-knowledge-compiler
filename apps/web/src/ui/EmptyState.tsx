import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";

export interface EmptyStateProps {
  icon: LucideIcon;
  title: ReactNode;
  /** 一行说明，给「下一步动作」。 */
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** 全产品唯一 empty 实现：图标 + 一行说明 + 可选动作。 */
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
