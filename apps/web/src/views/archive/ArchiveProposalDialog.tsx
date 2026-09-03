import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Database, FileText } from "lucide-react";
import {
  ApiError,
  confirmArchiveProposal,
  dropArchiveProposal,
  planArchive,
  type ArchiveAction,
  type ArchiveProposal,
  type ArchiveProposalItem,
  type ArchiveProposalSeeds,
} from "@/lib/api";
import { makeGuard, type RequestGuard } from "@/lib/requestGuard";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Checkbox } from "@/ui/Checkbox";
import { Dialog } from "@/ui/Dialog";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SkeletonText } from "@/ui/Skeleton";
import { TextArea } from "@/ui/TextArea";
import {
  confirmSelection,
  groupItems,
  isSelected,
  isStalePlan,
  itemKey,
  reasonMessage,
  recordFactsLine,
  recordReasonPreview,
  selectionCounts,
  settleConfirm,
  summaryMessage,
  toggleItem,
  type ConfirmResult,
  type ItemOverrides,
} from "./proposal";

/**
 * The archive's one interactive surface: propose, read what follows, confirm.
 *
 * It opens by ASKING — a `POST /archive/proposals` that moves nothing and answers with the
 * whole closure — because knowledge hangs together and the owner's seed is never the whole
 * set. The three groups below (`views/archive/proposal.ts` computes them) are the point of
 * the dialog: what you named, what goes with it, and what stays and why. That last group is
 * usually the useful one.
 *
 * Two behaviours are mechanical rather than cosmetic:
 *
 * - Ticking a row the plan left unselected RE-PLANS with that row as another seed, so every
 *   item on screen is a computation the reason column can explain. Unticking narrows the
 *   confirm instead, which is exactly what the `items` override is for.
 * - A confirm whose canonical HEAD has moved is refused `stale`, and the answer offered here
 *   is "re-plan", never "force": the set on screen was computed against a library that no
 *   longer exists, so overriding it would move something the owner never saw.
 *
 * Beside each selected document is a preview of the RECORD the archive will leave standing
 * at its live path — the definition, the facts, and the reason it will quote: the note as it
 * is being typed, or, until one is typed, the sentence the planner says the execution will
 * write. It is shown before the confirm rather than after because "what will be here
 * afterwards" is the half of this decision the item list alone never states, and because the
 * record is live knowledge: the owner is writing a page, not only moving one.
 *
 * Both requests it makes — the plan and the confirm — are per user, so both go out under the
 * guard (`lib/requestGuard.ts`) and both carry an abort signal. The parents mount this keyed
 * by `userId`, which is the other half of the same rule: a switch of library REMOUNTS the
 * dialog, so no proposal, override, note or error survives from one owner's library into the
 * next one's, and the `userId` a cancel drops against is always the one the proposal was
 * computed for.
 */
export function ArchiveProposalDialog({
  open,
  onOpenChange,
  userId,
  action,
  seeds,
  onExecuted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  userId: string;
  action: ArchiveAction;
  /** What the owner named — one document or one source, in practice. */
  seeds: ArchiveProposalSeeds;
  /** Called once the job is on the queue, so a view can refresh what it shows. */
  onExecuted?: (jobId: string) => void;
}) {
  const t = useT();
  const setNotice = useApp((s) => s.setNotice);

  const [proposal, setProposal] = useState<ArchiveProposal | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<ItemOverrides>({});
  const [note, setNote] = useState("");
  // Whether the owner TOUCHED the note field. `note === ""` is two different facts — nothing
  // typed yet, and a note deliberately deleted — and they lead to two different records, so
  // the emptiness alone cannot be read. Untouched, the confirm mentions no note and the
  // plan's stands; touched, it sends what is in the box, `""` included, which clears it.
  const [noteEdited, setNoteEdited] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  // A plan is computed for ONE library. If the reader switches user (or closes the dialog)
  // while `POST /archive/proposals` is on the wire, the answer that comes back describes a
  // library nobody is looking at — see `lib/requestGuard.ts`.
  const guardRef = useRef<RequestGuard | null>(null);
  guardRef.current ??= makeGuard();
  const guard = guardRef.current;
  // The confirm in flight, so closing, cancelling or unmounting can abort it rather than
  // leaving a write on the wire whose answer has nowhere to land.
  const confirmAbortRef = useRef<AbortController | null>(null);

  const i18n = useMemo(() => ({ t }), [t]);

  /**
   * Compute (or re-compute) the plan. A re-plan REPLACES what is on screen and drops the
   * proposal it replaces: two open proposals over one library state would be two answers to
   * the same question, and only one of them is the one the owner is reading.
   */
  const plan = useCallback(
    async (
      next: ArchiveProposalSeeds,
      noteText: string,
      previousId?: string,
      signal?: AbortSignal,
    ) => {
      const token = guard.next();
      setPlanning(true);
      setPlanError(null);
      setStale(false);
      setConfirmError(null);
      try {
        const computed = await planArchive(
          userId,
          {
            action,
            documents: next.documents,
            sources: next.sources,
            note: noteText.trim() || null,
          },
          signal,
        );
        if (previousId && previousId !== computed.proposal_id) {
          // Best effort: a proposal nobody confirms is a kept record either way, and failing
          // to close it must not fail the plan the owner is looking at.
          void dropArchiveProposal(userId, previousId).catch(() => undefined);
        }
        if (!guard.isCurrent(token)) {
          // The question moved on while this one was computing. Nothing of it reaches the
          // screen, and the proposal it left behind is closed the same way a replaced one is.
          void dropArchiveProposal(userId, computed.proposal_id).catch(() => undefined);
          return null;
        }
        setProposal(computed);
        setOverrides({});
        return computed;
      } catch (e) {
        if (guard.isCurrent(token)) setPlanError((e as Error).message);
        return null;
      } finally {
        if (guard.isCurrent(token)) setPlanning(false);
      }
    },
    [action, guard, userId],
  );

  // Opening is the request. Closing forgets everything: a proposal is computed against one
  // library state, so a stale one held across a close would be a preview of the past.
  useEffect(() => {
    if (!open) {
      setProposal(null);
      setOverrides({});
      setNote("");
      setNoteEdited(false);
      setPlanError(null);
      setConfirmError(null);
      setStale(false);
      return;
    }
    const controller = new AbortController();
    void plan(seeds, "", undefined, controller.signal);
    // Closing, unmounting or switching library retires the plan as well as aborting it: an
    // abort comes back as a rejection, and a rejection that can still write state is not a
    // guard.
    return () => {
      controller.abort();
      confirmAbortRef.current?.abort();
      confirmAbortRef.current = null;
      guard.invalidate();
    };
    // The seeds are the identity of this dialog's question; re-planning on every render of
    // an unchanged array literal is what the join guards against.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, seeds.documents.join("|"), seeds.sources.join("|"), plan, guard]);

  // Out of date either because this dialog's confirm was refused, or because the proposal
  // itself came back saying so (`views/archive/proposal.ts::isStalePlan`).
  const outOfDate = isStalePlan(proposal, stale);
  const items = proposal?.items ?? [];
  const groups = useMemo(() => groupItems(items, overrides), [items, overrides]);
  const counts = useMemo(() => selectionCounts(items, overrides), [items, overrides]);

  const onToggle = (item: ArchiveProposalItem, next: boolean) => {
    if (!proposal) return;
    const outcome = toggleItem(proposal, overrides, item, next);
    if (outcome.kind === "override") setOverrides(outcome.overrides);
    else void plan(outcome.seeds, note, proposal.proposal_id);
  };

  /**
   * Cancel closes the plan as well as the dialog: an unconfirmed proposal is `dropped`.
   *
   * The drop names `userId` and `proposal.proposal_id` together, and those two always agree:
   * the dialog is keyed by `userId` at the parents, so a proposal computed for a previous
   * owner is unmounted with the component rather than left in state for this line to drop
   * against the current owner's library. A confirm still on the wire is retired here too —
   * cancelling means the answer to it must not reopen or repaint what it just closed.
   */
  const close = () => {
    confirmAbortRef.current?.abort();
    confirmAbortRef.current = null;
    guard.invalidate();
    if (proposal && proposal.status === "proposed") {
      void dropArchiveProposal(userId, proposal.proposal_id).catch(() => undefined);
    }
    onOpenChange(false);
  };

  async function onConfirm() {
    if (!proposal) return;
    // The confirm takes a token like every other per-user request here: what comes back is
    // allowed to write only while it is still the answer to the question on screen.
    const token = guard.next();
    const controller = new AbortController();
    confirmAbortRef.current = controller;
    setConfirming(true);
    setConfirmError(null);
    let result: ConfirmResult;
    try {
      // The note travels with the decision: `confirm` carries it, so the set on screen is
      // the set confirmed, byte for byte, with no second plan in between.
      const confirmed = await confirmArchiveProposal(
        userId,
        proposal.proposal_id,
        confirmSelection(proposal.items, overrides),
        // `null` is "untouched", so the plan's note stands. Anything else REPLACES it, and
        // an emptied box replaces it with nothing — the clearing the owner just previewed.
        noteEdited ? note : null,
        controller.signal,
      );
      result = { kind: "queued", jobId: confirmed.job_id };
    } catch (e) {
      const error = e as ApiError;
      // `stale` is the one refusal with an action attached, so it gets its own panel rather
      // than the generic error line.
      result =
        error instanceof ApiError && error.code === "stale"
          ? { kind: "stale" }
          : { kind: "failed", message: error.message };
    } finally {
      if (confirmAbortRef.current === controller) confirmAbortRef.current = null;
    }

    const decision = settleConfirm(guard, token, result);
    // Not even `setConfirming(false)`: an ignored confirm belongs to a library this dialog is
    // no longer showing, and the component it started in has been closed or remounted.
    if (decision.kind === "ignored") return;
    setConfirming(false);
    if (decision.kind === "queued") {
      setNotice({ key: "archive.queued", params: { job: decision.jobId } });
      onExecuted?.(decision.jobId);
      onOpenChange(false);
    } else if (decision.kind === "stale") {
      setStale(true);
    } else {
      setConfirmError(decision.message);
    }
  }

  const title = t(
    action === "unarchive" ? "archive.dialog.unarchive.title" : "archive.dialog.archive.title",
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
        else onOpenChange(true);
      }}
      title={title}
      description={t(
        action === "unarchive"
          ? "archive.dialog.unarchive.description"
          : "archive.dialog.archive.description",
      )}
      contentClassName="max-w-2xl"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <p className="text-12 text-ink-2">{summaryMessage(action, counts, i18n)}</p>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="ghost" size="sm" onClick={close}>
              {t("archive.cancel")}
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={confirming}
              disabled={!proposal || planning || outOfDate || counts.total === 0}
              onClick={() => void onConfirm()}
            >
              {t(
                action === "unarchive" ? "archive.confirm.unarchive" : "archive.confirm.archive",
              )}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {planning && <SkeletonText lines={6} />}
        {!planning && planError && (
          <ErrorState
            title={t("archive.dialog.planFailed")}
            error={planError}
            onRetry={() => void plan(seeds, note)}
          />
        )}

        {!planning && proposal && !planError && (
          <>
            <ItemGroup
              title={t("archive.group.seeds")}
              items={groups.seeds}
              overrides={overrides}
              onToggle={onToggle}
              note={note}
              noteEdited={noteEdited}
            />
            <ItemGroup
              title={t(
                action === "unarchive"
                  ? "archive.group.cascade.unarchive"
                  : "archive.group.cascade.archive",
              )}
              items={groups.cascade}
              overrides={overrides}
              onToggle={onToggle}
              note={note}
              noteEdited={noteEdited}
              emptyText={t("archive.group.empty")}
            />
            {groups.related.length > 0 && (
              <ItemGroup
                title={t("archive.group.related")}
                caption={t("archive.group.related.note")}
                items={groups.related}
                overrides={overrides}
                onToggle={onToggle}
                note={note}
                noteEdited={noteEdited}
              />
            )}

            <TextArea
              label={t("archive.note.label")}
              placeholder={t(
                action === "unarchive"
                  ? "archive.note.placeholder.unarchive"
                  : "archive.note.placeholder.archive",
              )}
              value={note}
              rows={2}
              onChange={(e) => {
                setNoteEdited(true);
                setNote(e.target.value);
              }}
            />

            <p className="flex flex-wrap items-baseline gap-x-2 text-12 text-ink-3">
              <span>{t("archive.plan.libraryRef")}</span>
              <Mono className="break-all text-12">{proposal.library_ref}</Mono>
            </p>
          </>
        )}

        {outOfDate && !planning && (
          <Callout tone="warn" title={t("archive.stale.title")}>
            <p className="text-13 text-ink-2">{t("archive.stale.body")}</p>
            <p className="mt-2">
              <Button
                size="sm"
                onClick={() =>
                  void plan(proposal?.seeds ?? seeds, note, proposal?.proposal_id)
                }
              >
                {t("archive.stale.replan")}
              </Button>
            </p>
          </Callout>
        )}
        {confirmError && (
          <Callout tone="danger" title={t("archive.confirmFailed")}>
            <Mono className="text-12 break-all">{confirmError}</Mono>
          </Callout>
        )}
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------------ one group */

function ItemGroup({
  title,
  caption,
  items,
  overrides,
  onToggle,
  note,
  noteEdited,
  emptyText,
}: {
  title: string;
  /** The group's own explanatory line, when it has one. */
  caption?: string;
  items: ArchiveProposalItem[];
  overrides: ItemOverrides;
  onToggle: (item: ArchiveProposalItem, next: boolean) => void;
  /** The owner's note, as typed — the record preview quotes it live. */
  note: string;
  /** Whether that field was touched: an emptied note is a clearing, not an absence. */
  noteEdited: boolean;
  emptyText?: string;
}) {
  if (items.length === 0 && !emptyText) return null;
  return (
    <section>
      <p className="text-12 uppercase tracking-wide text-ink-3">{title}</p>
      {caption && <p className="mt-1 text-12 text-ink-3">{caption}</p>}
      {items.length === 0 ? (
        <p className="mt-1 text-13 text-ink-3">{emptyText}</p>
      ) : (
        <ul className="mt-1 divide-y divide-line border-t border-line">
          {items.map((item) => (
            <ItemRow
              key={itemKey(item.kind, item.ref)}
              item={item}
              checked={isSelected(item, overrides)}
              onToggle={onToggle}
              note={note}
              noteEdited={noteEdited}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function ItemRow({
  item,
  checked,
  onToggle,
  note,
  noteEdited,
}: {
  item: ArchiveProposalItem;
  checked: boolean;
  onToggle: (item: ArchiveProposalItem, next: boolean) => void;
  note: string;
  noteEdited: boolean;
}) {
  const t = useT();
  const i18n = useMemo(() => ({ t }), [t]);
  const Icon = item.kind === "document" ? FileText : Database;
  const reason = reasonMessage(item, i18n);
  const volumes = item.volumes ?? [];
  /**
   * Archiving a page does not empty its path: it leaves a short record standing there, and
   * that record is live knowledge the glance and recall will read. So the dialog shows it
   * before the owner confirms it — the definition, the facts, and the reason it will quote —
   * because "what will be here afterwards" is the half of this decision the item list alone
   * never states.
   *
   * Only for a SELECTED document: an unticked row leaves nothing behind, and neither does a
   * source (its mark is a timestamp on L0, not a page).
   */
  const record = checked && item.kind === "document" ? item.record ?? null : null;
  return (
    <li className="flex items-start gap-2.5 py-2">
      <span className="pt-0.5">
        <Checkbox
          checked={checked}
          onCheckedChange={(next) => onToggle(item, next === true)}
          aria-label={t("archive.item.aria", { title: item.title || item.ref })}
        />
      </span>
      <Icon size={14} aria-hidden className="mt-1 shrink-0 text-ink-3" />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-14 text-ink">{item.title || item.ref}</span>
          {volumes.length > 0 && (
            <Badge>{t("archive.item.volumes", { count: volumes.length })}</Badge>
          )}
        </p>
        <Mono className="mt-0.5 block break-all text-12 text-ink-3">{item.ref}</Mono>
        {reason && <p className="mt-0.5 text-12 text-ink-2">{reason}</p>}
        {record && (
          <RecordPreview record={record} note={note} noteEdited={noteEdited} />
        )}
      </div>
    </li>
  );
}

/** The record that will stand at the live path, as it will read. */
function RecordPreview({
  record,
  note,
  noteEdited,
}: {
  record: NonNullable<ArchiveProposalItem["record"]>;
  note: string;
  noteEdited: boolean;
}) {
  const t = useT();
  const i18n = useMemo(() => ({ t }), [t]);
  const facts = recordFactsLine(record, i18n);
  // The note as it is being typed; emptied after touching the field, the sentence an empty
  // note yields; untouched, the sentence the planner says the record will quote. The
  // execution writes a reason in all three cases, and the owner confirms what they were shown.
  const reason = recordReasonPreview(record, note, noteEdited, i18n);
  return (
    <div className="mt-1.5 rounded-1 border border-line bg-surface px-2.5 py-2">
      <p className="text-12 uppercase tracking-wide text-ink-3">
        {t("archive.record.preview")}
      </p>
      {record.definition && (
        <p className="mt-1 text-13 leading-relaxed text-ink-2">{record.definition}</p>
      )}
      {facts && <p className="mt-1 text-12 text-ink-3">{facts}</p>}
      {reason && <p className="mt-1 text-12 text-ink-3">{reason}</p>}
    </div>
  );
}
