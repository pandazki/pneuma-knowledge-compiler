import { useMemo, useState } from "react";
import { useApp } from "@/lib/store";
import { useT, type TFunction } from "@/lib/useT";
import { getDatasetRaw } from "@/lib/api";
import { edgeSentence } from "@/lib/edgeSentence";
import { fmtDelta } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n";
import type { Dataset } from "@/lib/types";
import {
  buildLinkIndex,
  deltaRows,
  diffUnits,
  lensDocuments,
  newEdges,
  structureHealth,
  summarize,
  type DeltaRow,
  type EdgeDiffRow,
  type StructureUnit,
  type SummaryMetric,
} from "@/lib/structureLens";
import { Button } from "@/ui/Button";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { SectionRule } from "@/ui/SectionRule";
import { Select } from "@/ui/Select";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";

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

const METRIC_LABEL: Record<SummaryMetric, MessageKey> = {
  files: "graph.metric.files",
  subjects: "graph.metric.subjects",
  claims: "graph.metric.claims",
  edges: "graph.metric.edges",
  arrivalBlind: "graph.metric.arrivalBlind",
  deadEnd: "graph.metric.deadEnd",
  orphanClaims: "graph.metric.orphanClaims",
  deadLinks: "graph.metric.deadLinks",
  leadShare: "graph.metric.leadShare",
  leadRatio: "graph.metric.leadRatio",
};

/** The two metrics that are ratios rather than counts, and so print with a decimal. */
const DECIMAL_METRICS: SummaryMetric[] = ["leadShare", "leadRatio"];

interface Side {
  ref: string | null;
  dataset: Dataset;
}

/**
 * Structure, twice: the same readings taken at two canonical commits, subtracted.
 *
 * Deliberately NOT two pictures side by side — an unreadable drawing does not become readable
 * by being duplicated. What a maintainer wants after a groom or an evolve is the difference:
 * which numbers moved, which subjects appeared or vanished, and which new threads were written
 * (each with the sentence that wrote it, because a new edge without its claim says nothing).
 */
export function SnapshotComparePanel({ templates }: { templates: string[] }) {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const snapshots = useApp((s) => s.snapshots);
  const kbSnapshots = useApp((s) => s.kbSnapshots);
  const jump = useApp((s) => s.jump);

  const [beforeRef, setBeforeRef] = useState<string>(snapshots[1]?.ref ?? snapshots[0]?.ref ?? "");
  const [afterRef, setAfterRef] = useState<string>(HEAD);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pair, setPair] = useState<{ before: Side; after: Side } | null>(null);

  const options = useMemo(
    () => [
      { value: HEAD, label: t("graph.compare.head") },
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

  const toRef = (value: string): string | null => {
    if (value === HEAD) return null;
    if (!value.startsWith(KB_PREFIX)) return value;
    const id = value.slice(KB_PREFIX.length);
    return kbSnapshots.find((s) => s.snapshot_id === id)?.canonical_ref ?? null;
  };
  const same = beforeRef === afterRef;

  const run = async () => {
    if (!currentUser || same) return;
    setLoading(true);
    setError(null);
    try {
      const [before, after] = await Promise.all([
        getDatasetRaw(currentUser, toRef(beforeRef)) as unknown as Promise<Dataset>,
        getDatasetRaw(currentUser, toRef(afterRef)) as unknown as Promise<Dataset>,
      ]);
      setPair({
        before: { ref: toRef(beforeRef), dataset: before },
        after: { ref: toRef(afterRef), dataset: after },
      });
    } catch (e) {
      setPair(null);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const result = useMemo(() => {
    if (!pair) return null;
    const beforeDocs = lensDocuments(pair.before.dataset.documents?.documents ?? []);
    const afterDocs = lensDocuments(pair.after.dataset.documents?.documents ?? []);
    const beforeHealth = structureHealth(beforeDocs, templates);
    const afterHealth = structureHealth(afterDocs, templates);
    return {
      rows: deltaRows(
        summarize(beforeHealth, beforeDocs.length),
        summarize(afterHealth, afterDocs.length),
      ),
      units: diffUnits(beforeHealth.units, afterHealth.units),
      edges: newEdges(buildLinkIndex(beforeDocs), buildLinkIndex(afterDocs)),
    };
  }, [pair, templates]);

  if (options.length < 2) {
    return <p className="max-w-measure text-13 text-ink-3">{t("graph.compare.none")}</p>;
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <p className="max-w-measure text-12 text-ink-3">{t("graph.compare.note")}</p>
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label={t("graph.compare.before")}
            value={beforeRef}
            onChange={setBeforeRef}
            options={options}
            wrapperClassName="min-w-52"
          />
          <Select
            label={t("graph.compare.after")}
            value={afterRef}
            onChange={setAfterRef}
            options={options}
            wrapperClassName="min-w-52"
          />
          <Button size="sm" loading={loading} disabled={same || loading} onClick={() => void run()}>
            {t("graph.compare.run")}
          </Button>
        </div>
        {same && <p className="text-12 text-warn">{t("graph.compare.same")}</p>}
      </div>

      {loading && (
        <div aria-busy>
          <p className="text-12 text-ink-3">{t("graph.compare.loading")}</p>
          <SkeletonText className="mt-3" lines={6} />
        </div>
      )}
      {error && !loading && <ErrorState title={t("graph.compare.error")} error={error} onRetry={() => void run()} />}

      {result && !loading && !error && (
        <>
          <section>
            <SectionRule no={1} title={t("graph.compare.deltaTitle")} />
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[30rem] border-collapse text-13">
                <thead>
                  <tr className="border-b border-line text-12 text-ink-3">
                    <th scope="col" className="py-1.5 pr-3 text-left font-normal">
                      {t("graph.compare.metric")}
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                      {t("graph.compare.before")}
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                      {t("graph.compare.after")}
                    </th>
                    <th scope="col" className="py-1.5 text-right font-normal">
                      Δ
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row) => (
                    <DeltaTableRow key={row.metric} row={row} t={t} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <SectionRule no={2} title={t("graph.compare.docsTitle")} />
            {result.units.added.length === 0 && result.units.removed.length === 0 ? (
              <p className="mt-3 max-w-measure text-13 text-ink-3">
                {t("graph.compare.noDocChange")}
              </p>
            ) : (
              <div className="mt-3 flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-10">
                <UnitColumn
                  title={t("graph.compare.added", { count: result.units.added.length })}
                  units={result.units.added}
                  onOpen={(u) => jump({ kind: "document", id: u.documentId ?? u.path }, "library")}
                />
                <UnitColumn
                  title={t("graph.compare.removed", { count: result.units.removed.length })}
                  units={result.units.removed}
                  onOpen={null}
                />
              </div>
            )}
          </section>

          <section>
            <SectionRule no={3} title={t("graph.compare.edgesTitle")} />
            {result.edges.length === 0 ? (
              <p className="mt-3 max-w-measure text-13 text-ink-3">
                {t("graph.compare.noNewEdges")}
              </p>
            ) : (
              <>
                <ul className="mt-3 flex flex-col">
                  {result.edges.slice(0, NEW_EDGE_SAMPLE).map((edge) => (
                    <EdgeRow
                      key={`${edge.fromPath}→${edge.toPath}`}
                      edge={edge}
                      onOpen={() =>
                        jump({ kind: "document", id: edge.toDocumentId ?? edge.toPath }, "library")
                      }
                    />
                  ))}
                </ul>
                {result.edges.length > NEW_EDGE_SAMPLE && (
                  <p className="mt-2 text-12 text-ink-3">
                    {t("graph.compare.newEdgeMore", {
                      count: result.edges.length - NEW_EDGE_SAMPLE,
                    })}
                  </p>
                )}
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function DeltaTableRow({ row, t }: { row: DeltaRow; t: TFunction }) {
  const decimals = DECIMAL_METRICS.includes(row.metric) ? 1 : 0;
  const moved = row.delta !== 0;
  // A movement is only ever coloured when it is a real regression: growth in claims is not
  // news, growth in unreachable subjects is.
  const regressed = moved && row.lowerIsBetter && row.delta > 0;
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="py-1.5 pr-3 text-ink">{t(METRIC_LABEL[row.metric])}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-12 text-ink-2 tabular-nums">
        {row.before.toFixed(decimals)}
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-12 text-ink-2 tabular-nums">
        {row.after.toFixed(decimals)}
      </td>
      <td
        className={cn(
          "py-1.5 text-right font-mono text-12 tabular-nums",
          regressed ? "text-warn" : moved ? "text-ink" : "text-ink-3",
        )}
      >
        {fmtDelta(row.delta, decimals)}
      </td>
    </tr>
  );
}

function UnitColumn({
  title,
  units,
  onOpen,
}: {
  title: string;
  units: StructureUnit[];
  onOpen: ((unit: StructureUnit) => void) | null;
}) {
  return (
    <section className="min-w-0 flex-1">
      <p className="text-12 text-ink-3">{title}</p>
      <ScrollRegion className="mt-1 max-h-64" aria-label={title}>
        <ul className="flex flex-col">
          {units.map((unit) => (
            <li key={unit.path} className="border-b border-line last:border-b-0 py-1.5">
              {onOpen ? (
                <button
                  type="button"
                  onClick={() => onOpen(unit)}
                  className="flex w-full min-w-0 flex-col text-left transition-colors duration-120 hover:bg-hover"
                >
                  <span className="truncate text-13 text-ink">{unit.title}</span>
                  <Mono className="truncate text-12 text-ink-3">{unit.path}</Mono>
                </button>
              ) : (
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-13 text-ink-2">{unit.title}</span>
                  <Mono className="truncate text-12 text-ink-3">{unit.path}</Mono>
                </span>
              )}
            </li>
          ))}
        </ul>
      </ScrollRegion>
    </section>
  );
}

/** A new thread: who now points at whom, and the sentence that says why. */
function EdgeRow({ edge, onOpen }: { edge: EdgeDiffRow; onOpen: () => void }) {
  return (
    <li className="border-b border-line">
      <button
        type="button"
        onClick={onOpen}
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
  );
}
