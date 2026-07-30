import type { ReactNode } from "react";
import { X } from "lucide-react";
import { useT } from "@/lib/useT";
import { cn } from "./cn";
import { IconButton } from "./IconButton";

export type CalloutTone = "notice" | "info" | "warn" | "danger";

const TONES: Record<CalloutTone, string> = {
  notice: "border-l-accent",
  info: "border-l-ink-3",
  warn: "border-l-warn",
  danger: "border-l-danger",
};

export interface CalloutProps {
  tone?: CalloutTone;
  title?: ReactNode;
  children: ReactNode;
  onDismiss?: () => void;
  /** inline = the full-width notice strip under the top bar; block = an in-content note. */
  variant?: "block" | "inline";
  className?: string;
}

/** Four steps — notice / info / warn / danger: a 2px semantic bar left, neutral ground. */
export function Callout({
  tone = "notice",
  title,
  children,
  onDismiss,
  variant = "block",
  className,
}: CalloutProps) {
  const t = useT();
  return (
    <div
      role={tone === "danger" || tone === "warn" ? "alert" : "status"}
      className={cn(
        "border-l-2 bg-surface text-ink",
        TONES[tone],
        variant === "block"
          ? "rounded-r-2 border-y border-r border-line px-3 py-2.5"
          : "px-4 py-2",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-baseline gap-2 text-13">
          {title != null && <span className="shrink-0 font-medium">{title}</span>}
          <div className="min-w-0 text-ink-2">{children}</div>
        </div>
        {onDismiss && (
          <IconButton
            aria-label={t("common.dismissNotice")}
            size="sm"
            onClick={onDismiss}
            className="-mr-1 -mt-0.5"
          >
            <X size={14} aria-hidden />
          </IconButton>
        )}
      </div>
    </div>
  );
}
