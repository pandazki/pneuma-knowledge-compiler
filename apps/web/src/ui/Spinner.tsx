import { cn } from "./cn";

export interface SpinnerProps {
  /** px 边长；仅按钮内使用（内容位请用 Skeleton）。 */
  size?: number;
  className?: string;
}

export function Spinner({ size = 16, className }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-label="加载中"
      style={{ width: size, height: size }}
      className={cn(
        "inline-block shrink-0 animate-spin rounded-full border-2 border-line-2 border-t-accent",
        className,
      )}
    />
  );
}
