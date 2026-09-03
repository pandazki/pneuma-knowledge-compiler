/**
 * The message catalogue: every bundle in this directory, merged into one flat map per
 * locale. Keys are dot-namespaced by surface (`nav.*`, `overview.*`, `evolve.*`, …), which
 * is what keeps the split files from turning into a lookup puzzle.
 *
 * Two invariants, both mechanically checked:
 *   1. zh and en carry the SAME keys — enforced at compile time by `defineMessages`
 *      (see ./define) and again at runtime by tests/i18n.test.mjs.
 *   2. No key is declared in two bundles — a silent overwrite would make one of the two
 *      declarations dead copy. `BUNDLES` is exported so the test can count.
 */
import { ask } from "./ask";
import { common } from "./common";
import { consultations } from "./consultations";
import { engineConsole } from "./engineConsole";
import { enums } from "./enums";
import { events } from "./events";
import { evolve } from "./evolve";
import { gallery } from "./gallery";
import { graph } from "./graph";
import { history } from "./history";
import { ingest } from "./ingest";
import { library } from "./library";
import { liveContext } from "./liveContext";
import { nav } from "./nav";
import { overview } from "./overview";
import { process } from "./process";
import { profile } from "./profile";
import { recall } from "./recall";
import { service } from "./service";
import { sources } from "./sources";

export type { Locale, MessageBundle } from "./define";
export { LOCALES, defineMessages } from "./define";

/** Every bundle, for the runtime duplicate-key check. Order is irrelevant to lookup. */
export const BUNDLES = [
  common,
  nav,
  enums,
  consultations,
  engineConsole,
  events,
  service,
  overview,
  profile,
  sources,
  ingest,
  process,
  recall,
  ask,
  liveContext,
  library,
  graph,
  history,
  evolve,
  gallery,
];

export const MESSAGES = {
  zh: {
    ...common.zh,
    ...nav.zh,
    ...enums.zh,
    ...consultations.zh,
    ...engineConsole.zh,
    ...events.zh,
    ...service.zh,
    ...overview.zh,
    ...profile.zh,
    ...sources.zh,
    ...ingest.zh,
    ...process.zh,
    ...recall.zh,
    ...ask.zh,
    ...liveContext.zh,
    ...library.zh,
    ...graph.zh,
    ...history.zh,
    ...evolve.zh,
    ...gallery.zh,
  },
  en: {
    ...common.en,
    ...nav.en,
    ...enums.en,
    ...consultations.en,
    ...engineConsole.en,
    ...events.en,
    ...service.en,
    ...overview.en,
    ...profile.en,
    ...sources.en,
    ...ingest.en,
    ...process.en,
    ...recall.en,
    ...ask.en,
    ...liveContext.en,
    ...library.en,
    ...graph.en,
    ...history.en,
    ...evolve.en,
    ...gallery.en,
  },
};

/**
 * Every declared key. `t()` takes this type, so a typo or a stale key is a build error
 * rather than a string that quietly renders as itself.
 */
export type MessageKey = keyof typeof MESSAGES.en & string;
