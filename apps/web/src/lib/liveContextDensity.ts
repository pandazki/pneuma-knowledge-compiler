/**
 * Suggestion density — three postures, one table.
 *
 * The bench used to expose the raw hyperparameters as four number fields, which asked the
 * reader a question they have no way to answer: what IS a good `max_pending_turns`? Nobody
 * knows in the abstract. What they do know is whether they want the system chattier or
 * quieter, so that is what the panel asks now, and this table is the translation.
 *
 * **Presets are a client vocabulary, not a wire one.** The socket and the SSE endpoint keep
 * taking the raw numbers, the server keeps echoing the resolved numbers back, and the
 * Processing tab keeps showing those — a debug surface that showed a preset NAME would hide
 * the very thing it exists to expose. Nothing about presets reaches the engine directory
 * either: they are how one page's controls are shaped, not a deployment's strategy.
 *
 * A combination matching no preset is `null` — "custom" — which is what an older client's
 * numbers, a hand-edited URL, or a future preset all look like from here. That is a state to
 * DISPLAY, never a state to correct: silently snapping someone's numbers to the nearest
 * preset would change the policy under them.
 */

export type DensityKey = "eager" | "balanced" | "quiet";

export interface DensityValues {
  /** One number, two doors: discover's `worth` floor AND pick's `confidence` floor. */
  min_confidence: number;
  /** Seconds between the end of one evaluation and the earliest start of the next. */
  quiet_period: number;
  /** The ceiling on one tick's pending run. */
  max_pending_turns: number;
}

export interface DensityPreset {
  key: DensityKey;
  values: DensityValues;
}

/**
 * Ordered loud → quiet, which is how the pills read left to right.
 *
 * The three axes move TOGETHER on purpose. A reader who wants more suggestions wants a lower
 * bar (more gets through), a shorter quiet period (the system looks more often) and a shorter
 * pending run (it reacts to what was just said rather than to a paragraph of it) — and the
 * opposite reader wants all three the other way. Splitting them into three dials would let
 * someone build a combination that means nothing, and then wonder why it behaved oddly.
 */
export const DENSITY_PRESETS: readonly DensityPreset[] = [
  { key: "eager", values: { min_confidence: 4, quiet_period: 4, max_pending_turns: 8 } },
  { key: "balanced", values: { min_confidence: 6, quiet_period: 6, max_pending_turns: 12 } },
  { key: "quiet", values: { min_confidence: 8, quiet_period: 10, max_pending_turns: 16 } },
] as const;

/** The posture a fresh page opens in — and the framework's own defaults, exactly. */
export const DEFAULT_DENSITY: DensityKey = "balanced";

export function densityValues(key: DensityKey): DensityValues {
  const found = DENSITY_PRESETS.find((p) => p.key === key);
  return { ...(found ?? DENSITY_PRESETS[1]).values };
}

/** Which preset these numbers ARE, or `null` when they are somebody's own combination. */
export function detectDensity(values: DensityValues): DensityKey | null {
  const match = DENSITY_PRESETS.find(
    (p) =>
      p.values.min_confidence === values.min_confidence &&
      p.values.quiet_period === values.quiet_period &&
      p.values.max_pending_turns === values.max_pending_turns,
  );
  return match ? match.key : null;
}
