/**
 * The identity lens: who is at this console.
 *
 * Role is an IDENTITY, not a request parameter. One top-level choice decides BOTH what the
 * app shows and what `visitor_class` its answering calls carry — the class is derived from
 * the lens rather than picked beside a question, because a person does not change who they
 * are between two questions in the same sitting.
 *
 * Three lenses. `owner` is the cockpit — every view the console has. `visitor` and `silent`
 * are the reading room: ask the library something, and read the pages it answers from.
 * There is no `audit` lens: audit is an API caller's stance (a consultation that must be
 * reconstructible but must not steer the Steward), not a person sitting at this console.
 *
 * This module is the ONE declaration. The nav rail, the router guard, the shell chrome and
 * the answering calls all read it; nothing keeps a second list. It imports nothing at
 * runtime, so the guard test can load it on its own.
 */
import type { ViewName, VisitorClass } from "./types";

export type Lens = "owner" | "visitor" | "silent";

export const LENSES: readonly Lens[] = ["owner", "visitor", "silent"];

export function isLens(value: unknown): value is Lens {
  return typeof value === "string" && (LENSES as readonly string[]).includes(value);
}

const OWNER_ONLY: readonly Lens[] = ["owner"];
const EVERY_LENS: readonly Lens[] = ["owner", "visitor", "silent"];

/**
 * The route table AND the visibility declaration, in one place: every view this app can
 * show, mapped to the lenses that may see it.
 *
 * `Record<ViewName, …>` is the mechanism — a view added to `ViewName` and forgotten here is
 * a build error, not a page that quietly leaks into the reading room. `ROUTED_VIEWS` below
 * is derived from these keys, so the hash router and the lens guard cannot disagree about
 * what a view even is.
 *
 * The reading room is exactly two entries: the answering surface (`recall`, whose fast and
 * deep lanes take a question and answer it with citations, with no pack to build first) and
 * read-only canonical browsing (`library`, whose citations open the source galley as they
 * always did). Everything else is the owner's machinery.
 */
export const VIEW_LENSES: Record<ViewName, readonly Lens[]> = {
  overview: OWNER_ONLY,
  profile: OWNER_ONLY,
  sources: OWNER_ONLY,
  ingest: OWNER_ONLY,
  recall: EVERY_LENS,
  ask: OWNER_ONLY,
  live_context: OWNER_ONLY,
  consultations: OWNER_ONLY,
  library: EVERY_LENS,
  process: OWNER_ONLY,
  history: OWNER_ONLY,
  graph: OWNER_ONLY,
  evolve: OWNER_ONLY,
  engine_console: OWNER_ONLY,
  // hidden route: the primitives state matrix (for acceptance shots; not in the contents)
  components: OWNER_ONLY,
};

/** Every view a URL hash may name — derived, so the router has no list of its own. */
export const ROUTED_VIEWS = Object.keys(VIEW_LENSES) as ViewName[];

/**
 * The top bar's chrome, declared the same way the views are: which lenses see each control.
 *
 * The top bar is the console's GLOBAL administration — which library is on the bench, which
 * copy of it answers, and the reader's own language and theme. Identity is not one of those:
 * it decides what the whole app is, so it belongs where the app's contents are listed, at
 * the foot of the rail, and it is not declared here.
 *
 * `userPicker` is every lens because this console is a demo and operator bench: which
 * library you are looking at is the first thing anyone sitting down here needs, and a
 * visitor lens that could only ever read one library would be a worse bench without being a
 * safer one. `snapshotPin` stays the owner's, for a mechanical reason rather than a
 * hierarchical one — the reading room draws no pin banner, so a pin taken there would answer
 * from a frozen copy while the page said nothing about it.
 */
export const SHELL_CHROME_LENSES = {
  userPicker: EVERY_LENS,
  snapshotPin: OWNER_ONLY,
} as const satisfies Record<string, readonly Lens[]>;

export type ShellChrome = keyof typeof SHELL_CHROME_LENSES;

export function showsShellChrome(item: ShellChrome, lens: Lens): boolean {
  return SHELL_CHROME_LENSES[item].includes(lens);
}

/** Where a lens lands when it has nowhere else to be: the cockpit's front matter, or the
 *  reading room's answering surface. */
export const LENS_HOME: Record<Lens, ViewName> = {
  owner: "overview",
  visitor: "recall",
  silent: "recall",
};

export function isViewVisible(view: ViewName, lens: Lens): boolean {
  return (VIEW_LENSES[view] ?? OWNER_ONLY).includes(lens);
}

/**
 * The router guard: the view this lens actually gets. A deep link into the cockpit under a
 * visitor lens lands on the reading room's home rather than on a broken page.
 */
export function resolveView(view: ViewName, lens: Lens): ViewName {
  return isViewVisible(view, lens) ? view : LENS_HOME[lens];
}

/**
 * The lens decides the class, mechanically. Owner and visitor both count as use — a question
 * asked here IS the library being used, and a use nobody counted leaves the library
 * reporting itself unread. The silent lens is the one that opts out, and it says so on the
 * badge and on the page rather than hiding in a dropdown.
 */
export function deriveVisitorClass(lens: Lens): VisitorClass {
  return lens === "silent" ? "silent" : "business";
}
