import { cn } from "./cn";

export interface SkeletonProps {
  className?: string;
}

/** Content-slot skeleton block (the one loading treatment; spinners stay in buttons). */
export function Skeleton({ className }: SkeletonProps) {
  return <div aria-hidden className={cn("animate-pulse rounded-1 bg-active", className)} />;
}

export interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

/** Multi-line prose skeleton: the last line is shortened to read as a paragraph. */
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
