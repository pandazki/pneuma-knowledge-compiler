import { useCallback, useEffect, useMemo, useState } from "react";
import { Inbox } from "lucide-react";
import { useApp } from "@/lib/store";
import { useLocale, useT, useTOr } from "@/lib/useT";
import { getLensReading } from "@/lib/api";
import { fmtCount, fmtDateTime, fmtDelta, shortSha } from "@/lib/format";
import {
  catalogText,
  orderDimensions,
  previousParam,
  PREVIOUS_AUTO,
  type LensDimension,
  type LensMetric,
  type LensReading,
} from "@/lib/lensReport";
import { legacyNodeTarget } from "@/lib/structureLens";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { Select } from "@/ui/Select";
import { SkeletonText } from "@/ui/Skeleton";

/**
 * `#/lens` — the structure lens (docs/design/structure-lens.md §4).
 *
 * The Steward works inside the library, one source at a time, and every compile can be right
 * while the sum drifts. Some of that drift a page shows and a checklist catches, which is what
 * `#/review` is for. What is left is what only the WHOLE shows: whether the library is walkable
 * as a body, where knowledge piles up, how much of it is a log of sessions rather than
 * knowledge about subjects, whether it ever corrects itself, whether the structure its
 * accumulating knowledge implies exists yet, and whether what it holds is what people ask it.
 *
 * So this page is six sections and no list of pages. Each dimension says what it sees (a band,
 * as one word), what that means (the statement), what moved since the previous reading (the
 * metrics), and what to reach for (the direction — a contract clause, an evolve, a groom, a
 * review round, never a page). There is no score: the six bands and their movement are the
 * whole summary.
 *
 * Two things this view deliberately does NOT do. It computes nothing — no band, no threshold,
 * not even which commit "previous" means, which the service reads as HEAD's parent so that the
 * console and `pkc lens` can never disagree about it. And it lists no findings: a finding
 * belongs to the lowest tier that can see it, and every tier below this one has its own face.
 *
 * Old `#/graph/node/<id>` links still work: `lib/hash.ts` maps the retired route name onto
 * this one, and the effect below resolves the node selection to the document (or the source)
 * that node stood for.
 */
export default function LensView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const libraryRevision = useApp((s) => s.libraryRevision);
  const snapshots = useApp((s) => s.snapshots);
  const kbSnapshots = useApp((s) => s.kbSnapshots);
  const selection = useApp((s) => s.selection);
  const setView = useApp((s) => s.setView);
  const jump = useApp((s) => s.jump);

  const [previous, setPrevious] = useState<string>(PREVIOUS_AUTO);
  const [reading, setReading] = useState<LensReading | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // A node deep link is an address for a subject, and subjects are read in Canonical.
  useEffect(() => {
    if (selection?.kind !== "node") return;
    const target = legacyNodeTarget(selection.id);
    // `jump` rather than `focusSource`: it rewrites the address into the destination's own
    // deep-link shape, so a shared old link does not stay spelled as a graph node forever.
    jump(target, target.kind === "source" ? "sources" : "library");
  }, [selection, jump]);

  /**
   * The refs a previous reading can be taken at: the service's own default first, then the
   * frozen snapshots, then the canonical commits. A frozen snapshot is picked by its own id
   * and READ at the commit it pinned, so it stays distinguishable from that same commit picked
   * directly — two options, one destination, two different things the reader meant.
   */
  const options = useMemo(
    () => [
      { value: PREVIOUS_AUTO, label: t("lens.previous.auto") },
      ...kbSnapshots
        .filter((s) => s.status === "ready" && s.canonical_ref)
        .map((s) => ({ value: s.canonical_ref as string, label: s.label })),
      ...snapshots.map((s) => ({
        // A commit subject can be a paragraph; the ref is the identity and the subject is the
        // hint, so the hint is the part that gets cut.
        value: s.ref,
        label: `${s.ref.slice(0, 10)} · ${(s.label ?? "").slice(0, 44)}`.trim(),
      })),
    ],
    [kbSnapshots, snapshots, t],
  );

  useEffect(() => {
    if (!currentUser) {
      setReading(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    getLensReading(currentUser, currentSnapshot, previousParam(previous))
      .then((next) => {
        if (!alive) return;
        setReading(next);
        setLoading(false);
      })
      .catch((e: Error) => {
        if (!alive) return;
        setReading(null);
        setError(e.message);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
    // `libraryRevision` is the "the library moved" signal a round raises; the reading is
    // derived from canonical, so it is stale the moment a round commits.
  }, [currentUser, currentSnapshot, libraryRevision, previous, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const dimensions = useMemo(
    () => (reading ? orderDimensions(reading.dimensions) : []),
    [reading],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("nav.view.lens")} description={t("lens.description")} />

      <div className="flex flex-wrap items-end gap-3">
        <Select
          label={t("lens.previous.label")}
          value={previous}
          onChange={setPrevious}
          options={options}
          wrapperClassName="min-w-56"
        />
        <p className="max-w-measure pb-1.5 text-12 text-ink-3">{t("lens.previous.note")}</p>
      </div>

      {loading && (
        <div aria-busy>
          <p className="text-12 text-ink-3">{t("lens.loading")}</p>
          <SkeletonText className="mt-3" lines={6} />
        </div>
      )}

      {error && !loading && (
        <ErrorState title={t("lens.error.title")} error={error} onRetry={retry} />
      )}

      {reading && !loading && !error && (
        <>
          <ReadingHeader reading={reading} />
          {dimensions.length === 0 ? (
            reading.files === 0 ? (
              <EmptyState
                icon={Inbox}
                title={t("lens.empty.title")}
                description={t("lens.empty.description")}
                action={
                  <Button size="sm" onClick={() => setView("ingest")}>
                    {t("lens.empty.action")}
                  </Button>
                }
              />
            ) : (
              <p className="max-w-measure text-14 text-ink-2">{t("lens.noDimensions")}</p>
            )
          ) : (
            <div className="flex flex-col gap-8">
              {dimensions.map((dimension, i) => (
                <DimensionSection key={dimension.id} dimension={dimension} no={i + 1} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** What was read, where, and against what. */
function ReadingHeader({ reading }: { reading: LensReading }) {
  const t = useT();
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-13 text-ink-2">
          {t("lens.counts", {
            files: reading.files,
            subjects: reading.subjects,
            claims: reading.claims,
            edges: reading.edges,
          })}
        </span>
        <hr aria-hidden className="hidden min-w-8 flex-1 border-0 border-t border-line sm:block" />
        <span className="flex shrink-0 items-baseline gap-2 text-12 text-ink-3">
          <Mono>{shortSha(reading.ref)}</Mono>
          {reading.read_at && <span>{t("lens.readAt", { time: fmtDateTime(reading.read_at) })}</span>}
        </span>
      </div>
      <p className="text-12 text-ink-3">
        {reading.previous_ref ? (
          <>
            {t("lens.against")} <Mono className="text-12">{shortSha(reading.previous_ref)}</Mono>
          </>
        ) : (
          t("lens.againstNone")
        )}
      </p>
    </section>
  );
}

/**
 * One dimension: the band as a word, the statement, the metrics with their movement, the
 * direction, the evidence.
 *
 * The band takes no colour. It is a READING and not a state — a library leaning its knowledge
 * into one subject is not an error, it is a fact its Owner may have meant — and this design
 * spends semantic ink only where a state is real.
 *
 * The title, the question and the band's word are chrome: the console's own small table,
 * looked up by a runtime string, so a dimension or a band this build has never heard of
 * renders under its own name rather than as a blank. The statement and the direction never
 * are: they arrive already rendered in both packs and the console keeps no copy of them.
 */
function DimensionSection({ dimension, no }: { dimension: LensDimension; no: number }) {
  const t = useT();
  const tOr = useTOr();
  const locale = useLocale();

  const title = tOr(`lens.dimension.${dimension.id}`, dimension.id);
  const question = tOr(`lens.dimension.${dimension.id}.question`, "");
  const band = dimension.band ? tOr(`lens.band.${dimension.band}`, dimension.band) : "";
  const statement = catalogText(locale, dimension.statement);
  const direction = catalogText(locale, dimension.direction);

  return (
    <section className="min-w-0">
      <SectionRule
        no={no}
        title={title}
        actions={
          band ? (
            <Badge>
              {/* Visually the word; to a screen reader what the word is saying about the
                  dimension, because a bare "Thin" beside a heading names nothing. */}
              <span className="sr-only">{t("lens.band.aria", { band })}</span>
              <span aria-hidden>{band}</span>
            </Badge>
          ) : null
        }
      />
      {question && <p className="mt-2 max-w-measure text-12 text-ink-3">{question}</p>}

      {statement && (
        <p className="mt-3 max-w-measure text-balance font-serif text-20 leading-[1.35] text-ink">
          {statement}
        </p>
      )}

      {dimension.metrics.length > 0 && <MetricTable metrics={dimension.metrics} />}

      {direction && (
        <p className="mt-3 flex items-baseline gap-2 text-13 text-ink-2">
          <Mono aria-hidden className="shrink-0 text-12 text-ink-3">
            →
          </Mono>
          <span className="min-w-0 max-w-measure">{direction}</span>
        </p>
      )}

      {dimension.evidence.length > 0 && (
        <ul
          className="mt-3 flex flex-col gap-0.5"
          aria-label={t("lens.evidence.label", { dimension: title })}
        >
          {dimension.evidence.map((line, i) => (
            <li key={`${line}-${i}`} className="flex min-w-0 items-baseline gap-2">
              <Mono aria-hidden className="shrink-0 text-12 text-ink-3">
                ·
              </Mono>
              <span className="min-w-0 break-words text-12 leading-[1.5] text-ink-3">{line}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * A metric's number.
 *
 * Rendered as it came: a count as a count, anything else to two decimals. The console does not
 * guess that a metric between 0 and 1 is a share — a lens that sent 14 under a name spelled
 * like a share would then read as 1 400 %, and a reading that lies about its own units is
 * worse than one that asks to be read literally. The name says what the number is.
 */
function metricNumber(value: number | null): string {
  if (value == null) return "—";
  return Number.isInteger(value) ? fmtCount(value) : value.toFixed(2);
}

/** The dimension's metrics and their movement: what it is now, what it was, and the step. */
function MetricTable({ metrics }: { metrics: readonly LensMetric[] }) {
  const t = useT();
  const tOr = useTOr();
  const moved = metrics.some((m) => m.previous != null || m.delta != null);
  return (
    // Bounded to the reading measure: a metric name and its three numbers flung to opposite
    // edges of a wide screen stop being one row a reader takes in at a glance.
    <div className="mt-3 max-w-measure overflow-x-auto">
      <table className="w-full min-w-[26rem] border-collapse text-13">
        <thead>
          <tr className="border-b border-line text-12 text-ink-3">
            <th scope="col" className="py-1.5 pr-3 text-left font-normal">
              {t("lens.metric.name")}
            </th>
            <th scope="col" className="py-1.5 pr-3 text-right font-normal">
              {t("lens.metric.value")}
            </th>
            <th scope="col" className="py-1.5 pr-3 text-right font-normal">
              {t("lens.metric.previous")}
            </th>
            <th scope="col" className="py-1.5 text-right font-normal">
              Δ
            </th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => (
            <tr key={metric.name} className="border-b border-line last:border-b-0">
              <td className="py-1.5 pr-3 text-ink">
                {/* A metric name this build has never heard of reads as itself, spaced out —
                    never as a blank cell beside a number nobody can then interpret. */}
                {tOr(`lens.metric.${metric.name}`, humanize(metric.name))}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono text-12 text-ink tabular-nums">
                {metricNumber(metric.value)}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono text-12 text-ink-2 tabular-nums">
                {metricNumber(metric.previous)}
              </td>
              <td className="py-1.5 text-right font-mono text-12 text-ink-2 tabular-nums">
                {metric.delta == null
                  ? "—"
                  : fmtDelta(metric.delta, Number.isInteger(metric.delta) ? 0 : 2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!moved && <p className="mt-2 text-12 text-ink-3">{t("lens.metric.noPrevious")}</p>}
    </div>
  );
}

/** `dead_end_share` → `dead end share`: the last-resort label for an unknown metric name. */
function humanize(name: string): string {
  return name.replace(/[_-]+/g, " ").trim() || name;
}
