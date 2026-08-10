import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUpRight, Crosshair } from "lucide-react";
import { fetchLocator, getSource, type SourceDetail } from "@/lib/api";
import { useApp } from "@/lib/store";
import { useT, useTOr } from "@/lib/useT";
import { Button } from "@/ui/Button";
import { IconButton } from "@/ui/IconButton";
import { Drawer } from "@/ui/Drawer";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";
import { SourceImageGallery } from "@/views/sources/SourceReaders";

export interface SourceSpanSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceId: string | null;
  /** The highlighted target block range (inclusive). */
  blockStart?: number | null;
  blockEnd?: number | null;
}

type SourceMetadataKey =
  | "occurredOn"
  | "author"
  | "createdAt"
  | "updatedAt"
  | "timezone"
  | "participants";

interface SourceMetadataItem {
  key: SourceMetadataKey;
  value: string;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function displayValue(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (Array.isArray(value)) {
    const values = value.map(displayValue).filter((item): item is string => item != null);
    return values.length > 0 ? values.join(" · ") : null;
  }
  return null;
}

function nestedDisplayValue(meta: Record<string, unknown>, key: string): string | null {
  return (
    displayValue(meta[key]) ??
    displayValue(recordValue(meta.frontmatter)[key]) ??
    displayValue(recordValue(meta.metadata)[key])
  );
}

function participantNames(meta: Record<string, unknown>): string | null {
  const participants = Array.isArray(meta.participants) ? meta.participants : [];
  const names = participants
    .map((participant) => {
      const value = recordValue(participant);
      return displayValue(value.display_name) ?? displayValue(value.name);
    })
    .filter((name): name is string => name != null);
  return names.length > 0 ? names.join(" · ") : null;
}

/** Credibility metadata only: render values the source actually carries, never placeholders. */
function sourceMetadata(detail: SourceDetail): SourceMetadataItem[] {
  const meta = detail.meta ?? {};
  const candidates: Array<[SourceMetadataKey, string | null]> = [
    ["occurredOn", nestedDisplayValue(meta, "occurred_on")],
    [
      "author",
      nestedDisplayValue(meta, "author") ?? nestedDisplayValue(meta, "authors"),
    ],
    ["createdAt", nestedDisplayValue(meta, "created_at")],
    [
      "updatedAt",
      nestedDisplayValue(meta, "updated_at") ?? nestedDisplayValue(meta, "modified_at"),
    ],
    ["timezone", nestedDisplayValue(meta, "timezone")],
    ["participants", participantNames(meta)],
  ];
  return candidates.flatMap(([key, value]) => (value == null ? [] : [{ key, value }]));
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
  const jump = useApp((s) => s.jump);
  const t = useT();
  const tOr = useTOr();
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

  const metadata = detail ? sourceMetadata(detail) : [];

  // The landing IS the feature: once the galley is in, carry the reader to the cited span
  // (smooth unless reduced-motion) instead of leaving them at the top of a long source.
  const firstHitRef = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    if (!open || !detail || blockStart == null) return;
    const el = firstHitRef.current;
    if (!el) return;
    const frame = requestAnimationFrame(() =>
      el.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
    return () => cancelAnimationFrame(frame);
  }, [open, detail, blockStart]);

  // The sheet is a footnote lookup; this corner action is the deliberate opposite — leave
  // the current task and open the same source (same span) in the full Sources catalogue.
  const openInSources = useCallback(() => {
    if (!sourceId) return;
    onOpenChange(false);
    jump({ kind: "source", id: sourceId, block: blockStart ?? undefined }, "sources");
  }, [sourceId, blockStart, jump, onOpenChange]);

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      side="right"
      title={detail?.title ?? t("common.sourceSpan.title")}
      actions={
        sourceId != null && (
          <IconButton
            aria-label={t("common.sourceSpan.openInSources")}
            title={t("common.sourceSpan.openInSources")}
            size="sm"
            onClick={openInSources}
          >
            <ArrowUpRight size={15} aria-hidden />
          </IconButton>
        )
      }
    >
      <div className="flex flex-col gap-4 p-4">
        {loading && <SkeletonText lines={8} />}
        {error && <ErrorState error={error} onRetry={() => void load()} />}
        {detail && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-baseline gap-2">
                <Mono className="text-12 text-ink-3">{detail.source_id}</Mono>
                <span className="text-12 text-ink-3">
                  {tOr(`enum.sourceKind.${detail.kind}`, detail.kind)}
                </span>
              </div>
              {blockStart != null && (
                <Button size="sm" variant="ghost" loading={fetching} onClick={() => void fetchExact()}>
                  <Crosshair size={13} aria-hidden />
                  {t("common.sourceSpan.fetchExact")}
                </Button>
              )}
            </div>
            {metadata.length > 0 && (
              <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 border-y border-line py-3 text-12">
                {metadata.map((item) => (
                  <div key={item.key} className="contents">
                    <dt className="text-ink-3">
                      {t(`common.sourceSpan.metadata.${item.key}`)}
                    </dt>
                    <dd className="min-w-0 break-words text-ink-2">{item.value}</dd>
                  </div>
                ))}
              </dl>
            )}
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
                  ref={b.index === blockStart ? firstHitRef : undefined}
                  className={cn(
                    "flex gap-3 border-b border-line px-1 py-2",
                    inRange(b.index) && "cite-pulse bg-accent-soft",
                  )}
                >
                  <Mono className="w-8 shrink-0 pt-0.5 text-right text-12 text-ink-3">
                    b{b.index}
                  </Mono>
                  <div className="min-w-0 flex-1">
                    <p className="prose text-14 whitespace-pre-wrap">{b.text}</p>
                    <SourceImageGallery images={b.images} />
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </Drawer>
  );
}
