import { useCallback, useEffect, useState } from "react";
import { Crosshair } from "lucide-react";
import { fetchLocator, getSource, type SourceDetail } from "@/lib/api";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Button } from "@/ui/Button";
import { Drawer } from "@/ui/Drawer";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";

export interface SourceSpanSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceId: string | null;
  /** The highlighted target block range (inclusive). */
  blockStart?: number | null;
  blockEnd?: number | null;
}

/**
 * The citation landing rail: a source's original text (mono block numbers + serif prose) with
 * the target range highlighted accent-soft, plus a fetch-locator exact-span button. Shared by
 * recall / ask / suggestion / library.
 */
export function SourceSpanSheet({
  open,
  onOpenChange,
  sourceId,
  blockStart = null,
  blockEnd = null,
}: SourceSpanSheetProps) {
  const currentUser = useApp((s) => s.currentUser);
  const t = useT();
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exactText, setExactText] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  const load = useCallback(async () => {
    if (!currentUser || !sourceId) return;
    setLoading(true);
    setError(null);
    try {
      setDetail(await getSource(currentUser, sourceId));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [currentUser, sourceId]);

  useEffect(() => {
    if (open) {
      setDetail(null);
      setExactText(null);
      void load();
    }
  }, [open, load]);

  const fetchExact = async () => {
    if (!currentUser || !sourceId || blockStart == null) return;
    setFetching(true);
    try {
      const res = await fetchLocator(currentUser, sourceId, {
        blocks: [blockStart, blockEnd ?? blockStart],
      });
      setExactText(res.text);
    } catch (e) {
      setExactText(t("common.sourceSpan.fetchFailed", { detail: (e as Error).message }));
    } finally {
      setFetching(false);
    }
  };

  const inRange = (index: number) =>
    blockStart != null && index >= blockStart && index <= (blockEnd ?? blockStart);

  return (
    <Drawer open={open} onOpenChange={onOpenChange} side="right" title={detail?.title ?? t("common.sourceSpan.title")}>
      <div className="flex flex-col gap-4 p-4">
        {loading && <SkeletonText lines={8} />}
        {error && <ErrorState error={error} onRetry={() => void load()} />}
        {detail && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-baseline gap-2">
                <Mono className="text-12 text-ink-3">{detail.source_id}</Mono>
                <span className="text-12 text-ink-3">{detail.kind}</span>
              </div>
              {blockStart != null && (
                <Button size="sm" variant="ghost" loading={fetching} onClick={() => void fetchExact()}>
                  <Crosshair size={13} aria-hidden />
                  {t("common.sourceSpan.fetchExact")}
                </Button>
              )}
            </div>
            {exactText != null && (
              <div className="rounded-2 border border-accent-line bg-accent-soft p-3">
                <p className="prose text-13 whitespace-pre-wrap">
                  {exactText}
                </p>
              </div>
            )}
            <ol className="flex flex-col">
              {detail.blocks.map((b) => (
                <li
                  key={b.index}
                  className={cn(
                    "flex gap-3 border-b border-line px-1 py-2",
                    inRange(b.index) && "bg-accent-soft",
                  )}
                >
                  <Mono className="w-8 shrink-0 pt-0.5 text-right text-12 text-ink-3">
                    b{b.index}
                  </Mono>
                  <p className="prose min-w-0 text-14 whitespace-pre-wrap">
                    {b.text}
                  </p>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </Drawer>
  );
}
