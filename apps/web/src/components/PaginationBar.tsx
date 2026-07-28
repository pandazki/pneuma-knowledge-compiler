import { ChevronLeft, ChevronRight } from "lucide-react";
import { visibleRange } from "@/lib/pagination";
import { Button } from "@/ui/Button";

export interface PaginationBarProps {
  pageIndex: number;
  limit: number;
  itemCount: number;
  total: number;
  hasNext: boolean;
  loading?: boolean;
  onPrevious: () => void;
  onNext: () => void;
  noun?: string;
}

export function PaginationBar({
  pageIndex,
  limit,
  itemCount,
  total,
  hasNext,
  loading = false,
  onPrevious,
  onNext,
  noun = "条",
}: PaginationBarProps) {
  const range = visibleRange(pageIndex, limit, itemCount, total);
  const pageCount = total === 0 ? 0 : Math.ceil(total / limit);

  return (
    <nav
      aria-label="分页"
      className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3"
    >
      <p className="text-13 text-ink-2" aria-live="polite">
        <span className="font-serif tabular-nums text-ink">
          {range.from}–{range.to}
        </span>
        <span> / </span>
        <span className="font-serif tabular-nums text-ink">{range.total}</span>
        <span> {noun}</span>
        {pageCount > 0 && (
          <span className="ml-2 text-ink-3">
            第 <span className="tabular-nums">{pageIndex + 1}</span> /{" "}
            <span className="tabular-nums">{pageCount}</span> 页
          </span>
        )}
      </p>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="ghost"
          disabled={loading || pageIndex === 0}
          onClick={onPrevious}
        >
          <ChevronLeft size={14} aria-hidden />
          上一页
        </Button>
        <Button
          size="sm"
          disabled={loading || !hasNext}
          onClick={onNext}
        >
          下一页
          <ChevronRight size={14} aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
