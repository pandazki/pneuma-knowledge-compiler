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
          onMouseEnter={openNow}
          onMouseLeave={closeSoon}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="z-50 w-72 rounded-3 border border-line bg-raised p-3 shadow-overlay"
        >
          <div className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-serif text-14 text-ink">
                {citation.title ?? citation.sourceId}
              </span>
              <Mono className="shrink-0 text-12 text-ink-3">{citation.sourceId}</Mono>
            </div>
            {range && (
              <Mono className="text-12 text-accent">块 {range}</Mono>
            )}
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
