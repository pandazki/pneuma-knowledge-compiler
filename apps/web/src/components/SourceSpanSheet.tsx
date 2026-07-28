import { useCallback, useEffect, useState } from "react";
import { Crosshair } from "lucide-react";
import { fetchLocator, getSource, type SourceDetail } from "@/lib/api";
import { useApp } from "@/lib/store";
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
  /** 高亮的目标 block 区间（闭区间）。 */
  blockStart?: number | null;
  blockEnd?: number | null;
}

/**
 * 引用落点侧栏：source 原文（mono 块号 + serif 正文），目标区间 accent-soft
 * 高亮，附 fetch-locator 精确段按钮。recall / ask / cue / library 共用。
 */
export function SourceSpanSheet({
  open,
  onOpenChange,
  sourceId,
  blockStart = null,
  blockEnd = null,
}: SourceSpanSheetProps) {
  const currentUser = useApp((s) => s.currentUser);
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
      setExactText(`fetch 失败：${(e as Error).message}`);
    } finally {
      setFetching(false);
    }
  };

  const inRange = (index: number) =>
    blockStart != null && index >= blockStart && index <= (blockEnd ?? blockStart);

  return (
    <Drawer open={open} onOpenChange={onOpenChange} side="right" title={detail?.title ?? "原文"}>
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
                  fetch 精确段
                </Button>
              )}
            </div>
            {exactText != null && (
              <div className="rounded-2 border border-accent-line bg-accent-soft p-3">
                <p className="font-serif text-13 leading-[1.75] whitespace-pre-wrap text-ink">
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
                  <p className="min-w-0 font-serif text-14 leading-[1.75] whitespace-pre-wrap text-ink">
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
