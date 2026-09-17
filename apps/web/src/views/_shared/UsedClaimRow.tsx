/**
 * One claim an answer rested on, as the answering lanes print it.
 *
 * Shared rather than copied because it is the same object everywhere it appears: the anchor,
 * the document it lives in, the component labels a lookup attached to it, the sentence, and
 * the citations that take a reader back to the source span. Recall prints it under a fast or
 * deep answer; the call surface prints it under the answer the library handed to a voice.
 * One row, so a claim never reads differently depending on which page found it.
 */
import { useMemo } from "react";
import { archiveRecordPaths } from "@/lib/archive";
import { claimOneLine } from "@/lib/claim";
import { useApp } from "@/lib/store";
import { useT, useTOr } from "@/lib/useT";
import type { UsedClaim } from "@/lib/api";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Badge } from "@/ui/Badge";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * The live paths at which archive records stand, when this console happens to hold the
 * canonical projection (it is loaded for Canonical, and kept afterwards).
 *
 * Deliberately NOT a fetch: recall must not pull a whole library projection to decorate a
 * badge, and a mark that is sometimes absent is honest in a way an extra request would not
 * make it. When the projection is there, every claim taken out of a record is marked.
 */
export function useArchiveRecordPaths(): ReadonlySet<string> {
  const model = useApp((s) => s.model);
  return useMemo(
    () => archiveRecordPaths(model?.dataset.documents?.documents ?? []),
    [model],
  );
}

export function UsedClaimRow({
  claim,
  titles,
  onJump,
  showScore = true,
}: {
  claim: UsedClaim;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
  showScore?: boolean;
}) {
  const t = useT();
  const tOr = useTOr();
  // Labels are a component's mechanical marks on a claim (`current`, `superseded`), an open
  // vocabulary: a label this build does not know renders as the word the server sent.
  const labels = claim.labels ?? [];
  const superseded = labels.includes("superseded");
  // A claim quoted out of an archive RECORD is about a subject that has left, but the record
  // itself is live and carries no `archived` label — so the mark comes from the only thing
  // the client already holds that knows the difference: the canonical projection's
  // frontmatter. Absent (recall does not load the projection itself), the row reads exactly
  // as it did before records existed rather than guessing.
  const records = useArchiveRecordPaths();
  const fromRecord = !labels.includes("archived") && records.has(claim.document_path);
  return (
    <div className="border-b border-line py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Mono className="text-12 text-ink-3">{claim.anchor}</Mono>
        <Mono className="text-12 text-ink-3">{claim.document_path}</Mono>
        {claim.paths.map((p) => (
          <Badge key={p}>{p}</Badge>
        ))}
        {fromRecord && <Badge tone="warn">{t("archive.record.badge")}</Badge>}
        {labels.map((label) =>
          // `via:person,timespan` — a component lookup returned this same claim. The paths
          // are dynamic, so the badge is built from the label itself rather than translated.
          label.startsWith("via:") ? (
            <Badge key={label} tone="neutral">
              {tOr("recall.components.via", "via {paths}").replace(
                "{paths}",
                label.slice(4).split(",").join(", "),
              )}
            </Badge>
          ) : (
            <Badge
              key={label}
              // `archived` is the archive's own label on evidence an `include_archived`
              // call admitted — history, shown as history, in the same slot `superseded`
              // has always used.
              tone={label === "superseded" || label === "archived" ? "warn" : "neutral"}
            >
              {tOr(`enum.claimLabel.${label}`, label)}
            </Badge>
          ),
        )}
        {showScore && (
          <Mono className="ml-auto text-12 text-ink-3">score {claim.score.toFixed(4)}</Mono>
        )}
      </div>
      <p className={cn("prose mt-1 max-w-measure text-14", superseded && "text-ink-3")}>
        {/* The service ships the ledger line as written — anchor comments and cross-link
            markup included; the reader gets the sentence, never the machinery. */}
        {claimOneLine(claim.text)}
      </p>
      <CitationList
        className="mt-2 max-w-measure"
        citations={claim.citations.map((c) => ({
          sourceId: c.source_id,
          blockStart: c.block_start,
          blockEnd: c.block_end,
          title: titles[c.source_id],
        }))}
        onJump={onJump}
      />
    </div>
  );
}
