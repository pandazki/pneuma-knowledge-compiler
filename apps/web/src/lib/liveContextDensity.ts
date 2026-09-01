/**
 * Suggestion density — three postures, one table.
 *
 * The bench used to expose the raw hyperparameters as four number fields, which asked the
 * reader a question they have no way to answer: what IS a good `max_pending_turns`? Nobody
 * knows in the abstract. What they do know is whether they want the system chattier or
 * quieter, so that is what the panel asks now, and this table is the translation.
 *
 * **The posture is now a wire field, and the numbers still are too.** That split is the
 * lesson of a live miss: on the eager preset the single turn 「建议这个事情还是交给我们日本市场
 * 的负责人来做吧。」 was skipped outright, because the three numbers only move how MUCH gets
 * through and the contract still said the same thing about WHAT is worth looking up. So
 * `density` travels beside them and varies one clause of the discover contract, while the
 * numbers stay exactly what they were — and the Processing tab keeps showing the resolved
 * numbers rather than a preset name, because a debug surface that showed only the name
 * would hide the very thing it exists to expose.
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
 *
 * Quiet's floor is 7 and not 8, and that number is measured rather than chosen. Replayed over
 * a real 21-turn conversation, quiet delivered ZERO cards — and the one that died at the gate
 * was a question somebody had asked ALOUD, which discover scored 8 and the pick scored just
 * under the floor. Quiet's own contract clause is "only a question somebody actually asked",
 * so a posture that then declines to answer it is not quiet, it is mute. The gap to balanced
 * is what carries the posture; 8 was that gap plus one card.
 */
export const DENSITY_PRESETS: readonly DensityPreset[] = [
  { key: "eager", values: { min_confidence: 4, quiet_period: 4, max_pending_turns: 8 } },
  { key: "balanced", values: { min_confidence: 6, quiet_period: 6, max_pending_turns: 12 } },
  { key: "quiet", values: { min_confidence: 7, quiet_period: 10, max_pending_turns: 16 } },
] as const;

/** The posture a fresh page opens in — and the framework's own defaults, exactly. */
export const DEFAULT_DENSITY: DensityKey = "balanced";

export function densityValues(key: DensityKey): DensityValues {
  const found = DENSITY_PRESETS.find((p) => p.key === key);
  return { ...(found ?? DENSITY_PRESETS[1]).values };
}

/**
 * What a preset pill sends: the posture AND the numbers it resolves to.
 *
 * Both, always. The numbers alone were what the pills used to send, and that is exactly the
 * shape that let an eager connection skip a turn naming a role nobody had named — the floors
 * were low and the contract was unchanged. The posture alone would drop the three dials a
 * custom setting is built out of. They answer different questions, so they both travel.
 */
export function densityConfig(key: DensityKey): DensityValues & { density: DensityKey } {
  return { density: key, ...densityValues(key) };
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
