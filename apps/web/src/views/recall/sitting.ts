/**
 * Who the sitting belongs to right now — and therefore whose answer may still be written.
 *
 * Recall is the one stateful surface every identity can reach, so a lens change clears its
 * cache and the reading room's session history (`lib/store` IDENTITY_RESET). Clearing is
 * only half of it: a request already in flight is not cancelled by being forgotten. `fetch`
 * cannot be un-sent, an SSE stream can be aborted but its handlers may already be queued,
 * and either way the completion landed a second later and wrote the previous person's
 * question, answer and citations back into the sitting that had just been emptied — the
 * leak the reset existed to close, arriving late.
 *
 * So the mechanism is a generation counter, not a cancellation. A request remembers the
 * epoch it opened under, and every write it makes afterwards asks whether that epoch is
 * still current. It is the same discipline the consultation list uses for out-of-order
 * pages (`views/consultations/listLoading.ts`), applied to a boundary that is a change of
 * PERSON rather than of query — which is why the epoch lives in the store, bumped by the
 * two events that clear the sitting and by nothing else.
 *
 * It lives here rather than inline in the view for a boring reason: this app has no
 * rendering harness, and "the request resolves after the lens changed" is exactly the kind
 * of interleaving only a test that drives the two in that order can catch.
 *
 * EVERY write, not only the settled answer. A streaming lane writes continuously — stages as
 * they open, the answer as it is written, a tool call per trail row — and each of those is
 * the previous person's content arriving in the new sitting exactly as their answer would be.
 * Guarding the completion alone left the live picture leaking, which is why all five writes
 * are named here: the handle is the whole surface a request may write through.
 */
import type { TrailStep } from "@/lib/api";
import type { StageEvent } from "@/lib/stages";
import type { RecallCache, SessionAsk } from "@/lib/store";

/** Everything a recall writes into the sitting — while it runs and when it finishes. */
export interface SittingWrites {
  setRecallCache(patch: Partial<RecallCache>): void;
  pushSessionAsk(ask: SessionAsk): void;
  /** The stage diagram, growing as the lane opens and settles each stage. */
  onStage(event: StageEvent): void;
  /** The answer as the model writes it. */
  onToken(delta: string): void;
  /** deep only: one tool call appended to the live trail. */
  onStep(step: TrailStep): void;
}

/**
 * A handle on the sitting as it is NOW. Every write through it is dropped once the store's
 * identity epoch has moved — the person at the console is not the one who asked.
 */
export function openSitting(
  epoch: () => number,
  writes: SittingWrites,
): SittingWrites & { current(): boolean } {
  const mine = epoch();
  const current = () => epoch() === mine;
  /** One write, dropped once the epoch has moved. Same rule for all of them. */
  const guard =
    <A extends unknown[]>(write: (...args: A) => void) =>
    (...args: A) => {
      if (current()) write(...args);
    };
  return {
    current,
    setRecallCache: guard((patch: Partial<RecallCache>) => writes.setRecallCache(patch)),
    pushSessionAsk: guard((ask: SessionAsk) => writes.pushSessionAsk(ask)),
    onStage: guard((event: StageEvent) => writes.onStage(event)),
    onToken: guard((delta: string) => writes.onToken(delta)),
    onStep: guard((step: TrailStep) => writes.onStep(step)),
  };
}
