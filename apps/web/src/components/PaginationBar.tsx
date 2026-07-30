import { ChevronLeft, ChevronRight } from "lucide-react";
import { visibleRange } from "@/lib/pagination";
import { useT } from "@/lib/useT";
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
  noun,
}: PaginationBarProps) {
  const t = useT();
  const range = visibleRange(pageIndex, limit, itemCount, total);
  const pageCount = total === 0 ? 0 : Math.ceil(total / limit);

  return (
    <nav
      aria-label={t("common.pagination.aria")}
      className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3"
    >
      <p className="text-13 text-ink-2" aria-live="polite">
        <span className="font-serif tabular-nums text-ink">
          {range.from}–{range.to}
        </span>
        <span> / </span>
        <span className="font-serif tabular-nums text-ink">{range.total}</span>
        <span> {noun ?? t("common.pagination.noun")}</span>
        {pageCount > 0 && (
          <span className="ml-2 tabular-nums text-ink-3">
            {t("common.pagination.page", { current: pageIndex + 1, total: pageCount })}
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
          {t("common.pagination.previous")}
        </Button>
        <Button
          size="sm"
          disabled={loading || !hasNext}
          onClick={onNext}
        >
          {t("common.pagination.next")}
          <ChevronRight size={14} aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
