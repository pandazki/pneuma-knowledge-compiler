/**
 * The archive dialog's arithmetic: what a proposal's items mean, what ticking one does, and
 * what a confirm carries.
 *
 * Three rules are load-bearing here, and all three come from the design
 * (docs/design/archive.md §5) rather than from what would be convenient to render.
 *
 * 1. LISTED IS NOT SELECTED. A source another live document still cites is shown, unselected,
 *    with the documents that kept it. That row is often the most useful line on the page —
 *    it is the reason the owner should not archive the thing they just asked to archive — so
 *    it gets its own group rather than being filtered out of the list.
 *
 * 2. TICKING AN UNSELECTED CASCADE ITEM IS A RE-PLAN, NOT A FLAG FLIP. Every item in a
 *    proposal has to be a computation the reason field can explain; adding one by hand would
 *    put an item on the list that no closure produced, with a reason nobody can read. So the
 *    tick goes back through the planner as a new SEED, and what follows from it — the
 *    documents that become fully dependent once that source is selected — comes back with it.
 *    Unticking is the opposite case and needs no round trip: narrowing a computed set is
 *    exactly what the confirm's `items` override is for.
 *
 * 3. THE PLAN IS AGAINST ONE LIBRARY STATE. `library_ref` is the HEAD the closure was
 *    computed against, and a confirm whose HEAD has moved is refused `stale`. This module
 *    therefore never merges two proposals: a re-plan REPLACES what is on screen.
 *
 * Kept free of runtime imports (the type imports are erased) and of the dictionary — every
 * word comes in through the injected `t` — so it transpiles standalone for its test.
 */

import type { MessageKey } from "@/i18n";
import type {
  ArchiveAction,
  ArchiveItemKind,
  ArchiveProposal,
  ArchiveProposalItem,
  ArchiveProposalSeeds,
  ArchiveRecordFacts,
} from "@/lib/api";
import type { RequestGuard, RequestToken } from "@/lib/requestGuard";

/** The wording this module needs, injected: it cannot reach the dictionary itself. */
export interface ProposalI18n {
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}

/** Per-item `selected` overrides the reader made, keyed by `itemKey`. Absent = as planned. */
export type ItemOverrides = Record<string, boolean>;

/** One item's address in the override map. `kind` is part of it: a document path and a
 *  source id can never collide today, and a key that assumed so would be the reason. */
export function itemKey(kind: ArchiveItemKind, ref: string): string {
  return `${kind}:${ref}`;
}

/** What this item's checkbox shows: the reader's override, else what the planner computed. */
export function isSelected(item: ArchiveProposalItem, overrides: ItemOverrides): boolean {
  const override = overrides[itemKey(item.kind, item.ref)];
  return override === undefined ? item.selected : override;
}

/* ------------------------------------------------------------------------ grouping */

export interface ProposalGroups {
  /** What the owner named. */
  seeds: ArchiveProposalItem[];
  /** What follows and is going with it. */
  cascade: ArchiveProposalItem[];
  /** What follows and is STAYING — the list with the reason it stayed. */
  related: ArchiveProposalItem[];
}

/**
 * Three groups, in the order the dialog reads top to bottom: what you asked for, what goes
 * with it, what does not. A seed stays in its own group even when unticked — the owner named
 * it, and moving it into "related" as they untick would make the list jump under the cursor.
 */
export function groupItems(
  items: readonly ArchiveProposalItem[],
  overrides: ItemOverrides = {},
): ProposalGroups {
  const groups: ProposalGroups = { seeds: [], cascade: [], related: [] };
  for (const item of items) {
    if (item.role === "seed") groups.seeds.push(item);
    else if (isSelected(item, overrides)) groups.cascade.push(item);
    else groups.related.push(item);
  }
  return groups;
}

/* -------------------------------------------------------------------- the checkbox */

export type ToggleOutcome =
  /** Narrowing: keep the plan, send the override with the confirm. */
  | { kind: "override"; overrides: ItemOverrides }
  /** Widening: ask the planner again, with this item as one more seed. */
  | { kind: "replan"; seeds: ArchiveProposalSeeds };

/**
 * What a click on one row's checkbox means.
 *
 * The one branch that matters: ticking an item the PLAN left unselected — `item.selected`,
 * not the current override — widens the set, and widening goes back through the planner
 * (rule 2 above). Re-ticking something the reader had just unticked is not widening: it is
 * putting the plan back, and it clears the override instead.
 */
export function toggleItem(
  proposal: Pick<ArchiveProposal, "seeds">,
  overrides: ItemOverrides,
  item: ArchiveProposalItem,
  next: boolean,
): ToggleOutcome {
  if (next && item.role === "cascade" && !item.selected) {
    return { kind: "replan", seeds: withSeed(proposal.seeds, item) };
  }
  const key = itemKey(item.kind, item.ref);
  const out = { ...overrides };
  // An override equal to the plan is not an override — dropping it keeps `confirmSelection`
  // honest about whether the reader changed anything at all.
  if (next === item.selected) delete out[key];
  else out[key] = next;
  return { kind: "override", overrides: out };
}

/** The seeds of the next plan: the ones this proposal already had, plus this item. */
export function withSeed(
  seeds: ArchiveProposalSeeds,
  item: ArchiveProposalItem,
): ArchiveProposalSeeds {
  const documents = [...(seeds.documents ?? [])];
  const sources = [...(seeds.sources ?? [])];
  const list = item.kind === "document" ? documents : sources;
  if (!list.includes(item.ref)) list.push(item.ref);
  return { documents, sources };
}

/* ---------------------------------------------------------------------- the confirm */

export interface SelectionCounts {
  documents: number;
  sources: number;
  total: number;
}

/** What the footer states, and what the Confirm button is enabled by. */
export function selectionCounts(
  items: readonly ArchiveProposalItem[],
  overrides: ItemOverrides = {},
): SelectionCounts {
  let documents = 0;
  let sources = 0;
  for (const item of items) {
    if (!isSelected(item, overrides)) continue;
    if (item.kind === "document") documents += 1;
    else sources += 1;
  }
  return { documents, sources, total: documents + sources };
}

/**
 * The `items` a confirm carries — or nothing at all when the reader changed nothing, so a
 * plain confirm stays a plain confirm and the service executes the set it computed.
 *
 * When there IS an override the WHOLE list goes, not just the changed rows: the request then
 * states the exact set the owner is confirming, which is the same thing `library_ref` does
 * for the library state.
 */
export function confirmSelection(
  items: readonly ArchiveProposalItem[],
  overrides: ItemOverrides = {},
): { kind: ArchiveItemKind; ref: string; selected: boolean }[] | undefined {
  const changed = items.some((item) => isSelected(item, overrides) !== item.selected);
  if (!changed) return undefined;
  return items.map((item) => ({
    kind: item.kind,
    ref: item.ref,
    selected: isSelected(item, overrides),
  }));
}

/* -------------------------------------------------------------- settling a confirm */

/** What the network said, once a confirm has settled — success, the one refusal with an
 *  action attached, or anything else. */
export type ConfirmResult =
  | { kind: "queued"; jobId: string }
  | { kind: "stale" }
  | { kind: "failed"; message: string };

/** What the dialog is allowed to do about it. `ignored` writes nothing at all. */
export type ConfirmDecision = ConfirmResult | { kind: "ignored" };

/**
 * A confirm is a write for ONE library, and it settles later than the click.
 *
 * The dialog's other request already asks the guard before it paints (`lib/requestGuard.ts`);
 * a confirm has to ask the same question, and for a stronger reason. A plan that lands late
 * paints the previous owner's rows; a CONFIRM that lands late would put the previous owner's
 * notice on screen, hand their job id to `onExecuted`, and close the dialog the current owner
 * is reading — state written into a library the answer was never about. So the decision is
 * mechanical and taken here rather than in the component: if the token that started the
 * confirm is no longer the guard's current one — the reader switched library, the dialog
 * closed, the view unmounted — every one of those writes is dropped, including the failures.
 *
 * The job still ran: `confirm` is an enqueue, and dropping the ANSWER never un-queues it.
 * What is dropped is only the right to speak about it on a screen that has moved on.
 */
export function settleConfirm(
  guard: Pick<RequestGuard, "isCurrent">,
  token: RequestToken,
  result: ConfirmResult,
): ConfirmDecision {
  return guard.isCurrent(token) ? result : { kind: "ignored" };
}

/**
 * Is the plan on screen out of date?
 *
 * TWO WAYS TO LEARN THE SAME FACT, and the panel must not depend on which one arrived. A
 * confirm refused `409 stale` says it to this dialog; the service also moves the row to
 * `stale`, so a proposal read back — by a re-plan that answered with it, or by any surface
 * that opens a stored one — says it about itself. Either way the set on screen was computed
 * against a library that no longer exists, and the only offer is to re-plan.
 */
export function isStalePlan(
  proposal: Pick<ArchiveProposal, "status"> | null | undefined,
  confirmRefused = false,
): boolean {
  return confirmRefused || proposal?.status === "stale";
}

/* ------------------------------------------------------------------------- the copy */

/** How many of a still-cited source's keepers are named before the row says "and N more". */
export const CITED_BY_SHOWN = 3;

/**
 * The mechanical reason as one short line.
 *
 * `note` is a closed vocabulary the service computed; anything this build does not know
 * renders as nothing rather than as a raw code, because a row's checkbox and title already
 * say what it is. The numbers are never re-derived here — `dependence` is `[cited, total]`
 * as the planner counted it, over ledger claims with the overview excluded.
 */
export function reasonMessage(item: ArchiveProposalItem, i18n: ProposalI18n): string {
  const keepers = citedByArchivedMessage(item, i18n);
  const note = noteMessage(item, i18n);
  if (!keepers) return note;
  return note ? `${note} · ${keepers}` : keepers;
}

/**
 * The unarchive direction's own half of "still cited": the ARCHIVED pages that also cite
 * this source.
 *
 * It rides beside the note rather than replacing it because the two say different things —
 * the note is why the item is on the list, this is what keeps citing it from the archive —
 * and because the planner may attach it to more than one note. Absent or empty renders as
 * nothing, so an item without it reads exactly as it did before the field existed.
 */
function citedByArchivedMessage(item: ArchiveProposalItem, i18n: ProposalI18n): string {
  const archived = item.reason?.cited_by_archived ?? [];
  if (archived.length === 0) return "";
  return i18n.t("archive.reason.citedByArchived", {
    documents: citedByLabel(archived, i18n),
  });
}

/** The mechanical code, as one short line. */
function noteMessage(item: ArchiveProposalItem, i18n: ProposalI18n): string {
  const reason = item.reason ?? {};
  const note = reason.note ?? "";
  const dependence = reason.dependence ?? null;
  const cited = reason.cited_by_live ?? [];
  switch (note) {
    case "seed":
      return i18n.t("archive.reason.seed");
    case "orphaned":
      return i18n.t("archive.reason.orphaned");
    case "still_cited":
      // Named keepers or nothing: "still cited by: " with an empty list states less than
      // silence does, and in the unarchive direction the keepers are the archived ones
      // `citedByArchivedMessage` prints instead.
      return cited.length === 0
        ? ""
        : i18n.t("archive.reason.stillCited", { documents: citedByLabel(cited, i18n) });
    case "fully_dependent":
      return dependence
        ? i18n.t("archive.reason.fullyDependent", {
            cited: dependence[0],
            total: dependence[1],
          })
        : i18n.t("archive.reason.seed");
    case "partially_dependent":
      return dependence
        ? i18n.t("archive.reason.partiallyDependent", {
            cited: dependence[0],
            total: dependence[1],
          })
        : "";
    case "restored_with_page":
      // The cascade's other direction: a source comes back because a page that is coming
      // back cites it. Not "you named it", not "nothing else cites it" — it travels.
      return i18n.t("archive.reason.restoredWithPage");
    case "already_archived":
      return i18n.t("archive.reason.alreadyArchived");
    case "already_live":
      return i18n.t("archive.reason.alreadyLive");
    default:
      return "";
  }
}

/** `a.md, b.md and 4 more` — the documents that kept a source, bounded. */
export function citedByLabel(paths: readonly string[], i18n: ProposalI18n): string {
  const shown = paths.slice(0, CITED_BY_SHOWN);
  const rest = paths.length - shown.length;
  const joined = shown.join(", ");
  return rest > 0 ? i18n.t("archive.reason.andMore", { shown: joined, count: rest }) : joined;
}

/** The footer's one sentence: how much of what, and which way it is about to move. */
export function summaryMessage(
  action: ArchiveAction,
  counts: SelectionCounts,
  i18n: ProposalI18n,
): string {
  const verb = action === "unarchive" ? "unarchive" : "archive";
  if (counts.total === 0) return i18n.t(`archive.summary.${verb}.none`);
  if (counts.sources === 0) {
    return i18n.t(`archive.summary.${verb}.documents`, { documents: counts.documents });
  }
  if (counts.documents === 0) {
    return i18n.t(`archive.summary.${verb}.sources`, { sources: counts.sources });
  }
  return i18n.t(`archive.summary.${verb}.both`, {
    documents: counts.documents,
    sources: counts.sources,
  });
}

/* --------------------------------------------------- the record left at the live path */

/**
 * The facts an archive record states, as one line: what it covered, how much it held, and
 * who still points at it.
 *
 * The span is the only conditional part — a subject with no dated span has none to state,
 * and "Covered –" would be a sentence about nothing. The four counts are stated even at
 * zero, because they are what the record itself will say and this line is a preview of that
 * page rather than a summary of it: a reader who confirms and then opens the live path must
 * find the same facts in the same order.
 *
 * Every number comes from the planner. Nothing here is re-derived, and a field the service
 * did not send reads as zero rather than as a gap in the line.
 */
export function recordFactsLine(
  record: ArchiveRecordFacts | null | undefined,
  i18n: ProposalI18n,
): string {
  if (!record) return "";
  const parts: string[] = [];
  const span = record.span;
  const dated = !!(span && span.length === 2 && span[0] && span[1]);
  // A record that states nothing states nothing: a service that ships none of these fields
  // must read as it did before they existed, not as a subject with zero of everything.
  const stated =
    dated ||
    record.claims != null ||
    record.sources != null ||
    record.volumes != null ||
    record.inbound != null;
  if (!stated) return "";
  if (dated && span) {
    parts.push(i18n.t("archive.record.span", { from: span[0], to: span[1] }));
  }
  parts.push(i18n.t("archive.record.claims", { count: record.claims ?? 0 }));
  parts.push(i18n.t("archive.record.sources", { count: record.sources ?? 0 }));
  parts.push(i18n.t("archive.record.volumes", { count: record.volumes ?? 0 }));
  parts.push(i18n.t("archive.record.inbound", { count: record.inbound ?? 0 }));
  return parts.join(" · ");
}

/**
 * The reason line as it will stand on the record page, previewed while the owner types it.
 *
 * THE BOX AND NOTHING ELSE. What the record quotes is the note this console sends with the
 * CONFIRM — the service keeps no reason of its own at plan time and composes none ever — so
 * the preview is a function of the textarea alone. Anything else would preview a sentence
 * that is not the one about to be sent: the plan's own `record.reason` is null unless the
 * owner named a statement, and a line drawn from it beside an empty box would show a reason
 * for a confirm the console has already disabled.
 *
 * Trimmed exactly as the confirm trims it, so the line shows what the record will carry and
 * not a near-miss differing by whitespace nobody sees. An empty box previews nothing, and
 * nothing is the honest preview: that state cannot be confirmed at all (`noteRequired`), so
 * there is no future record to draw.
 */
export function recordReasonPreview(note: string, i18n: ProposalI18n): string {
  const quoted = note.trim();
  return quoted ? i18n.t("archive.record.reason", { note: quoted }) : "";
}

/* --------------------------------------------------------------- the owner's own words */

/**
 * The names the suggested note is built from: the documents this proposal would move.
 *
 * Titles, falling back to the ref — a page with no title still has a path, and a suggestion
 * naming an empty string is one the owner has to rewrite from nothing. Overrides are
 * respected, so unticking a box before touching the note changes what the suggestion names.
 *
 * A SOURCES-ONLY proposal names its sources instead. That set leaves no record behind and
 * the design says so — the reason is still kept on the proposal, and a suggestion reading
 * "Archived:" with nothing after it is one the owner has to write from scratch, which is the
 * friction the prefill exists to remove.
 */
export function suggestionTitles(
  items: readonly ArchiveProposalItem[],
  overrides: ItemOverrides = {},
): string[] {
  const named = (kind: ArchiveItemKind) =>
    items
      .filter((item) => item.kind === kind && isSelected(item, overrides))
      .map((item) => item.title || item.ref)
      .filter((title) => title.trim() !== "");
  const documents = named("document");
  return documents.length > 0 ? documents : named("source");
}

/**
 * The sentence the dialog PREFILLS the note box with — a suggestion, never a default.
 *
 * The distinction is the whole of correction #1. The archive records the owner's reason as
 * an `owner-dialogue/v1` source: L0 labelled as the owner SPEAKING. A sentence the service
 * composed when they typed nothing would stand there as words they never said, and no later
 * reader of L0 could tell it from a real statement. So the service composes none and refuses
 * (`note_required`), and the friction that removes is paid HERE instead: the owner is shown
 * a sentence, may edit it or replace it, and SENDS it — which is what makes it theirs.
 *
 * Built client-side from the titles alone, which is why it lives in this module and not
 * behind a request: a suggestion the service produced would be the same default sentence
 * arriving by a longer road. It goes into the TEXTAREA and nowhere else — never into the
 * plan request — for the same reason: a suggestion the service was handed and kept would be
 * a sentence sitting on a kept row, one step from being quoted back as the owner's.
 */
export function suggestedNote(
  action: ArchiveAction,
  titles: readonly string[],
  i18n: ProposalI18n,
): string {
  return i18n.t(
    action === "unarchive" ? "archive.note.suggested.unarchive" : "archive.note.suggested.archive",
    { titles: titles.join(", ") },
  );
}

/** Whether the note box is empty in the only sense that counts — the one the service reads.
 *  Whitespace is not a reason: `sanitize_note` folds it to nothing on the other side. */
export function noteRequired(note: string): boolean {
  return note.trim() === "";
}

/**
 * What a refused confirm should SAY. `note_required` is the one refusal with wording of its
 * own here, because the service's sentence explains a rule the box beside it already states;
 * everything else keeps the service's own words, which are the only ones that can be right
 * about a failure this console did not predict.
 */
export function confirmErrorMessage(
  error: { code?: string; message: string },
  i18n: ProposalI18n,
): string {
  return error.code === "note_required"
    ? i18n.t("archive.note.required")
    : error.message;
}
