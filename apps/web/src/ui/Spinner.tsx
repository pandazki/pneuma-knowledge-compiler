import { useT } from "@/lib/useT";
import { cn } from "./cn";

export interface SpinnerProps {
  /** Side length in px. Buttons only — content slots use Skeleton. */
  size?: number;
  className?: string;
}

export function Spinner({ size = 16, className }: SpinnerProps) {
  const t = useT();
  return (
    <span
      role="status"
      aria-label={t("common.loading")}
      style={{ width: size, height: size }}
      className={cn(
        "inline-block shrink-0 animate-spin rounded-full border-2 border-line-2 border-t-accent",
        className,
      )}
    />
  );
}
