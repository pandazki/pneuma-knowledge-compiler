import { forwardRef, useCallback, useEffect, useRef, type HTMLAttributes } from "react";
import { isOverflowing, scrollFade } from "@/lib/scrollRegion";
import { cn } from "./cn";

/** Shortest the hairline rail's thumb is allowed to get, in px. */
const MIN_THUMB = 24;
/** A platform gutter narrower than this means the scrollbar is an overlay one. */
const NATIVE_GUTTER = 2;

/**
 * A scroll region: the one place the scroll charter lives.
 *
 * Each view pins its controls and hands its content areas to a ScrollRegion, so scrolling
 * one pane never drags the page, and a jump to an anchor lands inside the pane it belongs
 * to. The region measures itself and states which edges hide content; the fade is
 * `.scroll-region`'s job in index.css.
 *
 * Two things are deliberate here. The measurements are written straight to the DOM rather
 * than to React state — a scroll handler that re-rendered a 95-row tree every frame would
 * stutter. And the hairline rail on the right is painted by the component only where the
 * platform draws an overlay scrollbar (macOS), which appears mid-gesture and so cannot tell
 * a reader at rest that there is more to read; where the platform draws a real scrollbar,
 * that one shows and the rail stays away.
 *
 * The caller owns the height (`flex-1 min-h-0` inside a pinned pane, `max-h-…` in flow).
 * With no height bound the region simply never overflows, so the same markup degrades to
 * ordinary page flow on narrow screens.
 */
export type ScrollRegionElement = "div" | "nav" | "section" | "aside" | "ol" | "ul";

export interface ScrollRegionProps extends HTMLAttributes<HTMLDivElement> {
  /** Semantic tag for the scrolling element; the behaviour is identical. */
  as?: ScrollRegionElement;
  /** Sizing for the region as a whole (height bound, flex sizing, margins). */
  className?: string;
}

export const ScrollRegion = forwardRef<HTMLDivElement, ScrollRegionProps>(
  function ScrollRegion({ as = "div", className, children, ...rest }, forwardedRef) {
    const scrollerRef = useRef<HTMLDivElement | null>(null);
    const railRef = useRef<HTMLDivElement | null>(null);
    const thumbRef = useRef<HTMLDivElement | null>(null);

    const measure = useCallback(() => {
      const el = scrollerRef.current;
      if (!el) return;
      const m = {
        scrollTop: el.scrollTop,
        clientHeight: el.clientHeight,
        scrollHeight: el.scrollHeight,
      };
      const overflowing = isOverflowing(m);
      el.dataset.fade = scrollFade(m);
      el.dataset.overflowing = String(overflowing);

      const rail = railRef.current;
      const thumb = thumbRef.current;
      if (!rail || !thumb) return;
      const overlayScrollbar = el.offsetWidth - el.clientWidth < NATIVE_GUTTER;
      if (!overflowing || !overlayScrollbar) {
        rail.style.display = "none";
        return;
      }
      rail.style.display = "block";
      const track = rail.clientHeight;
      const height = Math.max(MIN_THUMB, (m.clientHeight / m.scrollHeight) * track);
      const travel = track - height;
      const progress = m.scrollTop / (m.scrollHeight - m.clientHeight);
      thumb.style.height = `${height}px`;
      thumb.style.transform = `translateY(${Math.max(0, Math.min(1, progress)) * travel}px)`;
    }, []);

    // Scroll position, box size and content size all move the edges; a content swap
    // (another document, another result set) is caught by the re-measure after each render.
    useEffect(() => {
      const el = scrollerRef.current;
      if (!el) return;
      measure();
      el.addEventListener("scroll", measure, { passive: true });
      const ro =
        typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => measure()) : null;
      ro?.observe(el);
      const child = el.firstElementChild;
      if (child) ro?.observe(child);
      window.addEventListener("resize", measure);
      return () => {
        el.removeEventListener("scroll", measure);
        ro?.disconnect();
        window.removeEventListener("resize", measure);
      };
    }, [measure, children]);

    useEffect(() => {
      measure();
    });

    const setRefs = (node: HTMLDivElement | null) => {
      scrollerRef.current = node;
      if (typeof forwardedRef === "function") forwardedRef(node);
      else if (forwardedRef) forwardedRef.current = node;
    };

    const Tag = as as "div";
    return (
      <div className={cn("relative flex min-h-0 flex-col", className)}>
        <Tag
          ref={setRefs}
          data-fade="none"
          data-overflowing="false"
          className="scroll-region min-h-0 flex-1"
          {...rest}
        >
          {children}
        </Tag>
        <div
          ref={railRef}
          aria-hidden
          style={{ display: "none" }}
          className="pointer-events-none absolute inset-y-0 right-0 w-[3px]"
        >
          <div ref={thumbRef} className="w-full rounded-1 bg-line-2" />
        </div>
      </div>
    );
  },
);
