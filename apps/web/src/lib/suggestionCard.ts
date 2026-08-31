/**
 * What one suggestion card AFFORDS — decided from the card, not from its kind name.
 *
 * This module exists because of a live defect. A `glance` card is the library's own
 * definition of a subject, delivered a retrieval early with real `[cite: sid ¶a-b]`
 * citations attached; while its tick is still running it cannot be expanded yet, because
 * the material a `want_more` would read is exactly what that tick is still building. The
 * bubble expressed "cannot expand" with one boolean — and the single else-branch behind it
 * printed the WEB card's sentence: 「这张卡出自互联网搜索，展开请直接点下面的来源链接。」
 * on a card whose four citations were library source spans. Two different reasons had been
 * collapsed into one negative, and the reader was told the wrong one.
 *
 * So the two questions are answered separately here, and the first is answered from the
 * CITATIONS rather than from `kind`:
 *
 * - `cardSources` — which citation shape the card carries. A web card fills
 *   `web_citations` and leaves `citations` empty; every other card does the reverse
 *   (service `_suggestion_out`), and the delivery gate refuses a card carrying neither. So
 *   the shape on the wire is the honest test, and `kind` only breaks a tie that construction
 *   never produces.
 * - `expandState` — whether `want_more` is offered, and if not, WHY: `web` (there is no
 *   source block to expand within — the pages themselves are the honest surface) or
 *   `filling` (the tick behind a provisional card has not settled yet, and the affordance
 *   returns the moment it does).
 *
 * Pure and runtime-import-free, so the node test harness can drive it standalone.
 */

import type { ContextSuggestion } from "./api";

/** Which citation apparatus a card carries. `none` is only reachable off the wire. */
export type CardSources = "web" | "library" | "none";

/**
 * WEB means URL citations. Not "the kind says web": the kind is a label the pick stage's
 * pool decided, and the affordances below are about what the reader can actually click.
 */
export function cardSources(suggestion: ContextSuggestion): CardSources {
  if ((suggestion.web_citations ?? []).length > 0) return "web";
  if ((suggestion.citations ?? []).length > 0) return "library";
  // Neither — which delivery refuses to build. The kind is all that is left to go on.
  return suggestion.kind === "web" ? "web" : "none";
}

/** `want_more` is offered, or the reason it is not. */
export type ExpandState = "expandable" | "web" | "filling";

export function expandState(suggestion: ContextSuggestion): ExpandState {
  if (cardSources(suggestion) === "web") return "web";
  // Ordered after `web` deliberately: a provisional card is a library card by construction,
  // so the two can never both be true, and stating the order makes that checkable.
  if (suggestion.provisional === true) return "filling";
  return "expandable";
}
