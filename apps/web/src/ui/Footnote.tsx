import { useRef, useState } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { useT } from "@/lib/useT";
import { cn } from "./cn";
import { Mono } from "./Mono";

export interface FootnoteCitation {
  /** Source title (falls back to the sourceId). */
  title?: string;
  sourceId: string;
  blockStart?: number | null;
  blockEnd?: number | null;
  snippet?: string;
}

export interface FootnoteProps {
  /** Superscript number (1-based). */
  index: number;
  citation: FootnoteCitation;
  /** Jump to the source span on click (the hover card is read-only). */
  onJump?: (citation: FootnoteCitation) => void;
  className?: string;
}

function rangeText(c: FootnoteCitation): string | null {
  if (c.blockStart == null) return null;
  const end = c.blockEnd ?? c.blockStart;
  return end === c.blockStart ? `b${c.blockStart}` : `b${c.blockStart}–b${end}`;
}

/**
 * The signature component: an accent superscript [n] inside prose; hover/focus reveals the
 * citation card, a click goes through onJump to the source span.
 */
export function Footnote({ index, citation, onJump, className }: FootnoteProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const openNow = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const closeSoon = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), 120);
  };

  const range = rangeText(citation);
  const title = citation.title?.trim() || t("common.footnote.untitledSource");

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          aria-label={t("common.footnote.aria", { index })}
          onMouseEnter={openNow}
          onMouseLeave={closeSoon}
          onFocus={openNow}
          onBlur={closeSoon}
          onClick={() => onJump?.(citation)}
          className={cn(
            "align-super font-mono text-[0.75em] leading-none text-accent",
            "cursor-pointer rounded-1 hover:bg-accent-soft",
            className,
          )}
        >
          [{index}]
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="top"
          align="start"
          sideOffset={6}
          collisionPadding={16}
          onMouseEnter={openNow}
          onMouseLeave={closeSoon}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="z-50 w-80 max-w-[calc(100vw-2rem)] rounded-3 border border-line bg-raised p-3 shadow-overlay"
        >
          <div className="flex min-w-0 flex-col gap-2">
            <p className="break-words font-serif text-14 leading-relaxed text-ink">
              {title}
            </p>
            <div className="flex min-w-0 items-center gap-2 border-t border-line pt-2">
              {range && (
                <>
                  <Mono className="shrink-0 text-12 text-accent">
                    {t("common.footnote.block", { range })}
                  </Mono>
                  <span aria-hidden className="text-12 text-ink-3">·</span>
                </>
              )}
              <Mono
                className="min-w-0 flex-1 truncate text-12 text-ink-3"
                title={citation.sourceId}
              >
                {citation.sourceId}
              </Mono>
            </div>
            {citation.snippet && (
              <p className="border-l-2 border-line-2 pl-2 font-serif text-13 leading-[1.75] text-ink-2">
                {citation.snippet}
              </p>
            )}
            {onJump && (
              <p className="text-12 text-ink-3">{t("common.footnote.jumpHint")}</p>
            )}
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
