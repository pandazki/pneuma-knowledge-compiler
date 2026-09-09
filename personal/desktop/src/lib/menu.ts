// The pure geometry and keyboard arithmetic of the ledger's own drop-down menu. The panel
// is exactly as tall as its content, so a list that opened past the bottom edge would be
// cut by the window: it flips upward when the room below cannot hold it and scrolls when
// neither side can.

export interface MenuOption { value: string; label: string; disabled?: boolean; lang?: string }

export interface Placement { side: 'below' | 'above'; top: number; maxHeight: number }

const MARGIN = 8;

/** Where the list goes, in viewport coordinates, given the trigger's box and the list's own height. */
export function placeMenu(
  trigger: { top: number; bottom: number }, menuHeight: number, viewportHeight: number, gap = 4,
): Placement {
  const below = viewportHeight - trigger.bottom - gap - MARGIN;
  const above = trigger.top - gap - MARGIN;
  if (menuHeight <= below || below >= above) {
    return { side: 'below', top: trigger.bottom + gap, maxHeight: Math.max(0, below) };
  }
  const height = Math.min(menuHeight, Math.max(0, above));
  return { side: 'above', top: trigger.top - gap - height, maxHeight: Math.max(0, above) };
}

/** The next enabled index `delta` steps from `from`, wrapping; -1 when nothing is enabled. */
export function stepOption(options: MenuOption[], from: number, delta: 1 | -1): number {
  const n = options.length;
  if (!n) return -1;
  for (let i = 1; i <= n; i++) {
    const index = (((from < 0 ? (delta > 0 ? -1 : 0) : from) + delta * i) % n + n) % n;
    if (!options[index].disabled) return index;
  }
  return -1;
}

export function edgeOption(options: MenuOption[], edge: 'first' | 'last'): number {
  return stepOption(options, edge === 'first' ? -1 : 0, edge === 'first' ? 1 : -1);
}

/** Type-ahead: the first enabled option whose label starts with the typed prefix, searched after `from`. */
export function matchOption(options: MenuOption[], prefix: string, from: number): number {
  const needle = prefix.toLocaleLowerCase();
  if (!needle) return -1;
  const n = options.length;
  for (let i = 1; i <= n; i++) {
    const index = (from + i) % n;
    const option = options[index];
    if (!option.disabled && option.label.toLocaleLowerCase().startsWith(needle)) return index;
  }
  return -1;
}
