/**
 * The arithmetic behind a partitioned scroll area (DESIGN.md §2.5 / the scroll charter):
 * an overflowing region fades at whichever edge still has content behind it, so "there is
 * more above / below" is visible without a dedicated scroll-hint graphic.
 *
 * Kept free of imports and of the DOM so it can be transpiled and tested on its own; the
 * component feeds it three numbers read off the element.
 */

export interface ScrollMetrics {
  scrollTop: number;
  clientHeight: number;
  scrollHeight: number;
}

/** Which edges are hiding content: nothing / above / below / both. */
export type ScrollFade = "none" | "top" | "bottom" | "both";

/** Sub-pixel layout noise (fractional zoom, borders) must not count as overflow. */
const EPSILON = 1;

export function isOverflowing(m: ScrollMetrics, epsilon: number = EPSILON): boolean {
  return m.scrollHeight - m.clientHeight > epsilon;
}

export function scrollFade(m: ScrollMetrics, epsilon: number = EPSILON): ScrollFade {
  if (!isOverflowing(m, epsilon)) return "none";
  const above = m.scrollTop > epsilon;
  const below = m.scrollTop + m.clientHeight < m.scrollHeight - epsilon;
  if (above && below) return "both";
  if (above) return "top";
  if (below) return "bottom";
  // Scrolled past both ends (elastic overscroll): no edge is hiding anything.
  return "none";
}
