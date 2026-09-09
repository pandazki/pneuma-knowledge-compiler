/**
 * The model-backed views, and the one condition that closes them.
 *
 * In the personal edition the library holds no model of its own: every judgement is the
 * agent's, and the console's Recall / Ask / Live Context pages are QUALITY-TESTING TOOLS
 * over the API's model lanes rather than the way anybody retrieves anything day to day.
 * Those lanes need an API key. When the machine says this library has none, the three pages
 * cannot answer, and a form that posts into a lane nobody can run is worse than a page that
 * says so — so they render a notice instead, and the daily path (the Steward reading the
 * library for you) is named on it.
 *
 * Two things keep this from spreading into a rule nobody can find:
 *
 * 1. **One declaration.** `MODEL_LANE_VIEWS` is the list; the router (App.tsx), the notice
 *    and the contents rail's badge all ask this module, and none of them keeps a second
 *    list. The Steward is deliberately NOT on it — it is where retrieval went, not another
 *    thing the key closes.
 * 2. **Only a home can close them.** Without a home — every project deployment — nothing is
 *    locked and every page renders byte for byte as it always did. A home that answered but
 *    named no current library decides nothing either: an unread key is not a missing one.
 *
 * Pure: types, a list, two predicates. No React, no store, no network.
 */
import { currentLibrary, type HomeStatus } from "./home";
import type { ViewName } from "./types";

/** The three views whose forms post into a model lane. */
export const MODEL_LANE_VIEWS = ["recall", "ask", "live_context"] as const;

export type ModelLaneView = (typeof MODEL_LANE_VIEWS)[number];

export function isModelLaneView(view: ViewName): view is ModelLaneView {
  return (MODEL_LANE_VIEWS as readonly ViewName[]).includes(view);
}

/**
 * Does this machine's current library lack the key the lanes need?
 *
 * `false` for a console with no home, and `false` when no library on the home claims to be
 * the current one — in both cases nobody said the key was missing, and the console must not
 * invent a lock out of an absence.
 */
export function modelLanesLocked(home: HomeStatus | null): boolean {
  const library = currentLibrary(home);
  return library != null && !library.key;
}

/** Is THIS view one of the three, on a machine that cannot run them? */
export function modelLaneLocked(view: ViewName, home: HomeStatus | null): boolean {
  return isModelLaneView(view) && modelLanesLocked(home);
}

/** The command that fixes it — a command, not copy: it is the same in every language. */
export const MODEL_LANE_KEY_COMMAND = "pkchome credentials set OPENROUTER_API_KEY";
