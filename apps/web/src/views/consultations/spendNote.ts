/**
 * Which caveat, if any, belongs under a spend line.
 *
 * There are two different reasons a window shows no money, and they are not
 * interchangeable — one is about this DEPLOYMENT, the other about this DATA:
 *
 * - `incomplete` — some of these consultations reported no token usage at all. The provider
 *   stored `{}`, every SQL sum over it is null and coalesces to zero, so after the summation
 *   an unmeasured call looks exactly like one that was free. The tokens shown are a floor,
 *   and no amount is honest over them.
 * - `unpriced` — everything was measured, but this deployment has declared no rate for the
 *   models behind it (or the window mixes currencies), so there are tokens and no money.
 *
 * `incomplete` wins when both hold: a reader who is told the price list is missing would go
 * and declare rates, and still not get a number.
 *
 * A function rather than a ternary in the view, because which of the two is said is the
 * whole point of the finding this closes, and it is worth a test that does not need a DOM.
 */
import type { Spend } from "@/lib/api";

export type SpendNote = "incomplete" | "unpriced" | null;

export function spendNote(spend: Pick<Spend, "consultations" | "with_usage" | "incomplete" | "cost">): SpendNote {
  if (spend.incomplete) return "incomplete";
  if (!spend.cost) return "unpriced";
  return null;
}

/** How many of the window's consultations reported nothing. Never negative. */
export function unmeasuredCount(spend: Pick<Spend, "consultations" | "with_usage">): number {
  return Math.max(0, spend.consultations - spend.with_usage);
}
