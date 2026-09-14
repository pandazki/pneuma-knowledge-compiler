import { useCallback, useMemo, useState } from "react";
import { useApp } from "@/lib/store";
import { useT, type TFunction } from "@/lib/useT";
import { getDatasetRaw, getLensReport } from "@/lib/api";
import { edgeSentence } from "@/lib/edgeSentence";
import { fmtCount, fmtDelta } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n";
import {
  compareReports,
  type LensComparison,
  type LensCountDelta,
  type LensFinding,
  type LensReport,
} from "@/lib/lensReport";
import {
  buildLinkIndex,
  lensDocuments,
  newEdges,
  type EdgeDiffRow,
} from "@/lib/structureLens";
import type { Dataset } from "@/lib/types";
import { Button } from "@/ui/Button";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { Select } from "@/ui/Select";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";
import { FindingRow } from "./FindingRow";

/** The live base, as a picker value (a ref of "" would be indistinguishable from unset). */
const HEAD = "__head__";
/**
 * A frozen snapshot is picked by its own id and READ at the commit it pinned, so it stays
 * distinguishable from that same commit picked directly — two options, one destination, two
 * different things the reader meant.
 */
const KB_PREFIX = "kb:";
/** New links are listed with their sentence, so the list is capped and states the remainder. */
const NEW_EDGE_SAMPLE = 12;

const METRIC_LABEL: Record<LensCountDelta["metric"], MessageKey> = {
  score: "lens.metric.score",
  subjects: "lens.metric.subjects",
  files: "lens.metric.files",
  claims: "lens.metric.claims",
  edges: "lens.metric.edges",
};

/**
 * The same lens at two refs, subtracted.
 *
 * Deliberately NOT two readings side by side: what a maintainer wants after a groom or an
 * evolve is the difference — which way the score moved, which base counts moved with it, and
 * above all which findings the round actually answered. Findings match by KEY, which hashes
 * the evidence, so "still open" means the same fault on the same page and not merely the same
 * lens firing twice.
 *
 * The new links are a fourth section and a SECOND read, on request. A new link says nothing
 * without the claim that wrote it, that sentence lives only in the canonical projection, and
 * two projections are an expensive thing to fetch for a section a reader may not have come
 * for — so the button is the honest place to spend it.
 */
export function ComparePanel() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const snapshots = useApp((s) => s.snapshots);
  const kbSnapshots = useApp((s) => s.kbSnapshots);

  const [beforeRef, setBeforeRef] = useState<string>(snapshots[1]?.ref ?? snapshots[0]?.ref ?? "");
  const [afterRef, setAfterRef] = useState<string>(HEAD);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pair, setPair] = useState<{ before: LensReport; after: LensReport } | null>(null);

  const [edges, setEdges] = useState<EdgeDiffRow[] | null>(null);
  const [edgesLoading, setEdgesLoading] = useState(false);
  const [edgesError, setEdgesError] = useState<string | null>(null);

  const options = useMemo(
    () => [
      { value: HEAD, label: t("lens.compare.head") },
      ...kbSnapshots
        .filter((s) => s.status === "ready" && s.canonical_ref)
        .map((s) => ({ value: `${KB_PREFIX}${s.snapshot_id}`, label: s.label })),
      ...snapshots.map((s) => ({
        value: s.ref,
        // A commit subject can be a paragraph; the ref is the identity and the subject is the
        // hint, so the hint is the part that gets cut.
        label: `${s.ref.slice(0, 10)} · ${(s.label ?? "").slice(0, 44)}`.trim(),
      })),
    ],
    [kbSnapshots, snapshots, t],
  );

  const toRef = useCallback(
    (value: string): string | null => {
      if (value === HEAD) return null;
      if (!value.startsWith(KB_PREFIX)) return value;
      const id = value.slice(KB_PREFIX.length);
      return kbSnapshots.find((s) => s.snapshot_id === id)?.canonical_ref ?? null;
    },
    [kbSnapshots],
  );
  const same = beforeRef === afterRef;

  const run = async () => {
    if (!currentUser || same) return;
    setLoading(true);
    setError(null);
    setEdges(null);
    setEdgesError(null);
    try {
      const [before, after] = await Promise.all([
        getLensReport(currentUser, toRef(beforeRef)),
        getLensReport(currentUser, toRef(afterRef)),
      ]);
      setPair({ before, after });
    } catch (e) {
      setPair(null);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const loadEdges = async () => {
    if (!currentUser) return;
    setEdgesLoading(true);
    setEdgesError(null);
    try {
      const [before, after] = await Promise.all([
        getDatasetRaw(currentUser, toRef(beforeRef)) as unknown as Promise<Dataset>,
        getDatasetRaw(currentUser, toRef(afterRef)) as unknown as Promise<Dataset>,
      ]);
      setEdges(
        newEdges(
          buildLinkIndex(lensDocuments(before.documents?.documents ?? [])),
          buildLinkIndex(lensDocuments(after.documents?.documents ?? [])),
        ),
      );
    } catch (e) {
      setEdges(null);
      setEdgesError((e as Error).message);
    } finally {
      setEdgesLoading(false);
    }
  };

  const diff: LensComparison | null = useMemo(
    () => (pair ? compareReports(pair.before, pair.after) : null),
    [pair],
  );

  if (options.length < 2) {
    return <p className="max-w-measure text-13 text-ink-3">{t("lens.compare.none")}</p>;
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <p className="max-w-measure text-12 text-ink-3">{t("lens.compare.note")}</p>
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label={t("lens.compare.before")}
            value={beforeRef}
            onChange={setBeforeRef}
            options={options}
            wrapperClassName="min-w-52"
          />
          <Select
            label={t("lens.compare.after")}
            value={afterRef}
            onChange={setAfterRef}
            options={options}
            wrapperClassName="min-w-52"
          />
          <Button size="sm" loading={loading} disabled={same || loading} onClick={() => void run()}>
            {t("lens.compare.run")}
          </Button>
        </div>
        {same && <p className="text-12 text-warn">{t("lens.compare.same")}</p>}
      </div>

      {loading && (
        <div aria-busy>
          <p className="text-12 text-ink-3">{t("lens.compare.loading")}</p>
          <SkeletonText className="mt-3" lines={6} />
        </div>
      )}
      {error && !loading && (
        <ErrorState title={t("lens.compare.error")} error={error} onRetry={() => void run()} />
      )}

      {diff && !loading && !error && (
        <>
          <section>
            <SectionRule no={1} title={t("lens.compare.countsTitle")} />
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[30rem] border-collapse text-13">
                <thead>
                  <tr className="border-b border-line text-12 text-ink-3">
                    <th scope="col" className="py-1.5 pr-3 text-left font-normal">
                      {t("lens.compare.metric")}
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                      {t("lens.compare.before")}
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                      {t("lens.compare.after")}
                    </th>
                    <th scope="col" className="py-1.5 text-right font-normal">
                      Δ
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {diff.counts.map((row) => (
                    <DeltaTableRow key={row.metric} row={row} t={t} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <SectionRule no={2} title={t("lens.compare.findingsTitle")} />
            {diff.resolved.length === 0 &&
            diff.added.length === 0 &&
            diff.stillOpen.length === 0 ? (
              <p className="mt-3 max-w-measure text-13 text-ink-3">
                {t("lens.compare.noFindingChange")}
              </p>
            ) : (
              <div className="mt-3 flex flex-col gap-6">
                <FindingBucket
                  title={t("lens.compare.resolved", { count: diff.resolved.length })}
                  findings={diff.resolved}
                />
                <FindingBucket
                  title={t("lens.compare.added", { count: diff.added.length })}
                  findings={diff.added}
                />
                <FindingBucket
                  title={t("lens.compare.stillOpen", { count: diff.stillOpen.length })}
                  findings={diff.stillOpen}
                />
              </div>
            )}
          </section>

          <section>
            <SectionRule no={3} title={t("lens.compare.edgesTitle")} />
            <p className="mt-2 max-w-measure text-12 text-ink-3">{t("lens.compare.edgesNote")}</p>
            {edges == null && !edgesLoading && !edgesError && (
              <Button
                size="sm"
                variant="default"
                className="mt-3"
                onClick={() => void loadEdges()}
              >
                {t("lens.compare.edgesLoad")}
              </Button>
            )}
            {edgesLoading && (
              <div aria-busy className="mt-3">
                <p className="text-12 text-ink-3">{t("lens.compare.edgesLoading")}</p>
                <SkeletonText className="mt-2" lines={3} />
              </div>
            )}
            {edgesError && !edgesLoading && (
              <ErrorState
                className="mt-3"
                title={t("lens.compare.edgesError")}
                error={edgesError}
                onRetry={() => void loadEdges()}
              />
            )}
            {edges != null && !edgesLoading && <NewEdgeList edges={edges} />}
          </section>
        </>
      )}
    </div>
  );
}

function DeltaTableRow({ row, t }: { row: LensCountDelta; t: TFunction }) {
  const moved = row.delta !== 0;
  // The score is the one reading where a fall is a regression; every other row here is a
  // count of what the library holds, and more of it is not news.
  const regressed = moved && row.metric === "score" && row.delta < 0;
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="py-1.5 pr-3 text-ink">{t(METRIC_LABEL[row.metric])}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-12 text-ink-2 tabular-nums">
        {fmtCount(Math.round(row.before))}
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-12 text-ink-2 tabular-nums">
        {fmtCount(Math.round(row.after))}
      </td>
      <td
        className={cn(
          "py-1.5 text-right font-mono text-12 tabular-nums",
          regressed ? "text-warn" : moved ? "text-ink" : "text-ink-3",
        )}
      >
        {fmtDelta(Math.round(row.delta))}
      </td>
    </tr>
  );
}

/** One side of the finding difference. An empty bucket says so rather than disappearing. */
function FindingBucket({ title, findings }: { title: string; findings: LensFinding[] }) {
  const t = useT();
  return (
    <section className="min-w-0">
      <p className="text-12 text-ink-3">{title}</p>
      {findings.length === 0 ? (
        <p className="mt-1 text-13 text-ink-3">{t("lens.compare.bucketEmpty")}</p>
      ) : (
        <ul className="mt-1 flex flex-col border-t border-line">
          {findings.map((finding) => (
            <FindingRow key={finding.key} finding={finding} />
          ))}
        </ul>
      )}
    </section>
  );
}

/** A new thread: who now points at whom, and the sentence that says why. */
function NewEdgeList({ edges }: { edges: EdgeDiffRow[] }) {
  const t = useT();
  const jump = useApp((s) => s.jump);
  if (edges.length === 0) {
    return <p className="mt-3 max-w-measure text-13 text-ink-3">{t("lens.compare.noNewEdges")}</p>;
  }
  return (
    <>
      <ul className="mt-3 flex flex-col">
        {edges.slice(0, NEW_EDGE_SAMPLE).map((edge) => (
          <li key={`${edge.fromPath}→${edge.toPath}`} className="border-b border-line">
            <button
              type="button"
              onClick={() => jump({ kind: "document", id: edge.toDocumentId ?? edge.toPath }, "library")}
              className="flex w-full min-w-0 flex-col gap-1 py-2 text-left transition-colors duration-120 hover:bg-hover"
            >
              <span className="flex min-w-0 items-baseline gap-2 text-13">
                <span className="min-w-0 truncate text-ink-2">{edge.fromTitle}</span>
                <Mono className="shrink-0 text-12 text-ink-3">→</Mono>
                <span className="min-w-0 truncate text-ink">{edge.toTitle}</span>
              </span>
              <span className="line-clamp-2 text-12 leading-relaxed text-ink-3">
                {edgeSentence(edge.sentence)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {edges.length > NEW_EDGE_SAMPLE && (
        <p className="mt-2 text-12 text-ink-3">
          {t("lens.compare.newEdgeMore", { count: edges.length - NEW_EDGE_SAMPLE })}
        </p>
      )}
    </>
  );
}
