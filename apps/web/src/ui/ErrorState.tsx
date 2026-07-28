import { CircleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";
import { Button } from "./Button";
import { Mono } from "./Mono";

export interface ErrorStateProps {
  title?: ReactNode;
  error: Error | string;
  onRetry?: () => void;
  className?: string;
}

/** 全产品唯一 error 实现：错误说明 + detail + 重试。 */
export function ErrorState({ title = "出错了", error, onRetry, className }: ErrorStateProps) {
  const detail = typeof error === "string" ? error : error.message;
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center gap-2 rounded-2 border border-danger bg-danger-soft px-6 py-10 text-center",
        className,
      )}
    >
      <CircleAlert size={20} aria-hidden className="text-danger" />
      <p className="text-14 font-medium text-ink">{title}</p>
      <p className="max-w-measure text-13 text-ink-2">
        <Mono>{detail}</Mono>
      </p>
      {onRetry && (
        <Button size="sm" onClick={onRetry} className="mt-2">
          重试
        </Button>
      )}
    </div>
  );
}
