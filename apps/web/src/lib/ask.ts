/**
 * Ask-view pure helpers.
 *
 * `briefingSelection` is the one that matters: a briefing and the thread asked against it are
 * a single fact, so pointing Ask at a different pack (built, rebuilt, or picked out of the
 * history list) must reset the thread and the draft question in the same write. Doing it by
 * hand at each call site is what let a new briefing inherit the previous one's turns — hence
 * one helper, applied through `store.selectBriefing`, and a `setAskCache` that cannot touch
 * `briefing` at all.
 *
 * Type-only imports here on purpose: this module must stay runtime-import-free so the node
 * test can transform and load it on its own (same rule as lib/pagination.ts).
 */
import type { AskCache } from "./store";
import type { BriefingBuilt } from "./api";

/** The whole-cache patch for "Ask is now looking at `next`" — thread and draft reset with it. */
export function briefingSelection(
  next: BriefingBuilt | null,
): Pick<AskCache, "briefing" | "turns" | "question"> {
  return { briefing: next, turns: [], question: "" };
}

/** What the briefing-text panel puts above the pack: its size, counted the way a reader sees it. */
export function briefingTextLines(text: string): number {
  if (text === "") return 0;
  return text.split("\n").length;
}
