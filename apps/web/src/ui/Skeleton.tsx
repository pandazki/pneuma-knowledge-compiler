import { cn } from "./cn";

export interface SkeletonProps {
  className?: string;
}

/** 内容位骨架块（统一 loading；spinner 仅按钮内）。 */
export function Skeleton({ className }: SkeletonProps) {
  return <div aria-hidden className={cn("animate-pulse rounded-1 bg-active", className)} />;
}

export interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

/** 多行正文骨架：末行缩短，模拟段落。 */
export function SkeletonText({ lines = 3, className }: SkeletonTextProps) {
  return (
    <div aria-hidden className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton
          key={i}
          className={cn("h-3.5", i === lines - 1 && lines > 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}
