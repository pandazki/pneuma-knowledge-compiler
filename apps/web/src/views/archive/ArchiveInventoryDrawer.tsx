import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, Database, FileText } from "lucide-react";
import {
  getArchiveInventory,
  type ArchiveInventory,
  type ArchiveProposalSeeds,
} from "@/lib/api";
import { fmtDateTime, fmtDay } from "@/lib/format";
import { makeGuard, type RequestGuard } from "@/lib/requestGuard";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Drawer } from "@/ui/Drawer";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SkeletonText } from "@/ui/Skeleton";
import { ArchiveProposalDialog } from "./ArchiveProposalDialog";
import { recordFactsLine } from "./proposal";

/**
 * What is in the archive right now, and the one action that takes something out of it.
 *
 * It reads `GET /archive` rather than the canonical projection, for two reasons: the
 * projection carries no archived SOURCES at all, and the day a document went in is a fact
 * about the move commit, not about the document. Restoring goes through the same proposal
 * dialog an archive does — an unarchive has a closure of its own (an archived document's
 * archived sources come back with it), and the owner confirms that set the same way.
 */
export function ArchiveInventoryDrawer({
  open,
  onOpenChange,
  userId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  userId: string;
}) {
  const t = useT();
  const i18n = useMemo(() => ({ t }), [t]);
  const [inventory, setInventory] = useState<ArchiveInventory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<ArchiveProposalSeeds | null>(null);
  // One inventory belongs to ONE library. A listing for the user the reader just left must
  // never land on the user they are looking at, however slow the wire was — see
  // `lib/requestGuard.ts`.
  const guardRef = useRef<RequestGuard | null>(null);
  guardRef.current ??= makeGuard();
  const guard = guardRef.current;

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const token = guard.next();
      setError(null);
      setInventory(null);
      try {
        const listing = await getArchiveInventory(userId, signal);
        if (guard.isCurrent(token)) setInventory(listing);
      } catch (e) {
        if (guard.isCurrent(token)) setError((e as Error).message);
      }
    },
    [guard, userId],
  );

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void load(controller.signal);
    // Closing the drawer or switching library retires the request as well as aborting it:
    // an abort comes back as a rejection, and a rejection that can still write state is not
    // a guard.
    return () => {
      controller.abort();
      guard.invalidate();
    };
  }, [open, load, guard]);

  const documents = inventory?.documents ?? [];
  const sources = inventory?.sources ?? [];
  const empty = inventory != null && documents.length === 0 && sources.length === 0;

  return (
    <>
      <Drawer
        open={open}
        onOpenChange={onOpenChange}
        side="right"
        title={t("archive.inventory.title")}
        contentClassName="w-[min(34rem,100vw)]"
      >
        <div className="flex flex-col gap-5 p-5">
          <p className="text-13 text-ink-2">{t("archive.inventory.description")}</p>

          {error && (
            <ErrorState
              title={t("archive.inventory.error")}
              error={error}
              onRetry={() => void load()}
            />
          )}
          {!error && inventory == null && <SkeletonText lines={8} />}
          {empty && (
            <EmptyState
              icon={Archive}
              title={t("archive.inventory.empty.title")}
              description={t("archive.inventory.empty.description")}
            />
          )}

          {documents.length > 0 && (
            <section>
              <p className="text-12 uppercase tracking-wide text-ink-3">
                {t("archive.inventory.documents", { count: documents.length })}
              </p>
              <ul className="mt-1 divide-y divide-line border-t border-line">
                {documents.map((doc) => {
                  // The facts are what the RECORD says, and the service nests them
                  // under `record` — the row itself is about the moved copy.
                  const facts = recordFactsLine(doc.record, i18n);
                  return (
                  <li key={doc.path} className="flex items-start gap-2.5 py-2">
                    <FileText size={14} aria-hidden className="mt-1 shrink-0 text-ink-3" />
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span className="text-14 text-ink">{doc.title || doc.live_path}</span>
                        {/* The facts line below states the volume count in words; the badge
                            is what a service that ships no record facts still says. */}
                        {!facts && (doc.volumes ?? 0) > 0 && (
                          <Badge>
                            {t("archive.inventory.volumes", { count: doc.volumes ?? 0 })}
                          </Badge>
                        )}
                      </p>
                      <Mono className="mt-0.5 block break-all text-12 text-ink-3">
                        {doc.path}
                      </Mono>
                      {/* Where the page used to be is not empty: the record stands there,
                          stating the same facts this row states. */}
                      {doc.record_path && (
                        <p className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-12 text-ink-3">
                          <span>{t("archive.record.at")}</span>
                          <Mono className="break-all text-12">{doc.record_path}</Mono>
                        </p>
                      )}
                      {facts && <p className="mt-0.5 text-12 text-ink-3">{facts}</p>}
                      {doc.archived_on && (
                        <p className="mt-0.5 text-12 text-ink-3">
                          {t("archive.inventory.archivedOn", {
                            date: fmtDay(doc.archived_on),
                          })}
                        </p>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setRestoring({ documents: [doc.path], sources: [] })
                      }
                    >
                      {t("archive.action.restore")}
                    </Button>
                  </li>
                  );
                })}
              </ul>
            </section>
          )}

          {sources.length > 0 && (
            <section>
              <p className="text-12 uppercase tracking-wide text-ink-3">
                {t("archive.inventory.sources", { count: sources.length })}
              </p>
              <ul className="mt-1 divide-y divide-line border-t border-line">
                {sources.map((source) => (
                  <li key={source.source_id} className="flex items-start gap-2.5 py-2">
                    <Database size={14} aria-hidden className="mt-1 shrink-0 text-ink-3" />
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span className="text-14 text-ink">{source.title}</span>
                        <Badge>{source.kind}</Badge>
                      </p>
                      <Mono className="mt-0.5 block break-all text-12 text-ink-3">
                        {source.source_id}
                      </Mono>
                      {source.archived_at && (
                        <p className="mt-0.5 text-12 text-ink-3">
                          {t("archive.inventory.archivedOn", {
                            date: fmtDateTime(source.archived_at),
                          })}
                        </p>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setRestoring({ documents: [], sources: [source.source_id] })
                      }
                    >
                      {t("archive.action.restore")}
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </Drawer>

      <RestoreDialog
        userId={userId}
        seeds={restoring}
        onClose={() => setRestoring(null)}
        onQueued={() => void load()}
      />
    </>
  );
}

/**
 * The restore dialog, mounted only while a row is chosen. Keying it on the seeds is what
 * makes "restore A, then restore B" two questions rather than one dialog that remembered the
 * first answer — and the owner is part of that key, so the same row in two libraries is two
 * questions too (the drawer above is keyed by owner for the same reason).
 */
function RestoreDialog({
  userId,
  seeds,
  onClose,
  onQueued,
}: {
  userId: string;
  seeds: ArchiveProposalSeeds | null;
  onClose: () => void;
  onQueued: () => void;
}) {
  const key = useMemo(
    () => (seeds ? `${userId}:${[...seeds.documents, ...seeds.sources].join("|")}` : ""),
    [seeds, userId],
  );
  if (!seeds) return null;
  return (
    <ArchiveProposalDialog
      key={key}
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      userId={userId}
      action="unarchive"
      seeds={seeds}
      onExecuted={onQueued}
    />
  );
}
