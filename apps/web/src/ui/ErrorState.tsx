import { CircleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useT } from "@/lib/useT";
import { cn } from "./cn";
import { Button } from "./Button";
import { Mono } from "./Mono";

export interface ErrorStateProps {
  title?: ReactNode;
  error: Error | string;
  onRetry?: () => void;
  className?: string;
}

/** The one error implementation in the product: message + detail + retry. */
export function ErrorState({ title, error, onRetry, className }: ErrorStateProps) {
  const t = useT();
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
      <p className="text-14 font-medium text-ink">{title ?? t("common.errorTitle")}</p>
      <p className="max-w-measure text-13 text-ink-2">
        <Mono>{detail}</Mono>
      </p>
      {onRetry && (
        <Button size="sm" onClick={onRetry} className="mt-2">
          {t("common.retry")}
        </Button>
      )}
    </div>
  );
}
