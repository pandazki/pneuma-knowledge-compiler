import { useRef, useState } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "./cn";
import { Mono } from "./Mono";

export interface FootnoteCitation {
  /** source 标题（缺省显示 sourceId）。 */
  title?: string;
  sourceId: string;
  blockStart?: number | null;
  blockEnd?: number | null;
  snippet?: string;
}

export interface FootnoteProps {
  /** 上标编号（1 起）。 */
  index: number;
  citation: FootnoteCitation;
  /** 点击跳 source span（hover 卡片只读，点击才跳）。 */
  onJump?: (citation: FootnoteCitation) => void;
  className?: string;
}

function rangeText(c: FootnoteCitation): string | null {
  if (c.blockStart == null) return null;
  const end = c.blockEnd ?? c.blockStart;
  return end === c.blockStart ? `b${c.blockStart}` : `b${c.blockStart}–b${end}`;
}

/**
 * 签名组件：正文里的上标 accent 编号 [n]；hover/focus 出 citation 卡片，
 * 点击经 onJump 跳 source span。
 */
export function Footnote({ index, citation, onJump, className }: FootnoteProps) {
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
  const title = citation.title?.trim() || "未命名来源";

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          aria-label={`脚注 ${index}`}
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
                  <Mono className="shrink-0 text-12 text-accent">块 {range}</Mono>
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
            {onJump && <p className="text-12 text-ink-3">点击编号跳到原文</p>}
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
