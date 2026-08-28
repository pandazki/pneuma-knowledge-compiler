import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT, type TFunction } from "@/lib/useT";
import { fmtCount, fmtPercent } from "@/lib/format";
import { familyFromTemplate } from "@/lib/evolve";
import type { Anomaly, StructureHealth, StructureUnit } from "@/lib/structureLens";
import { Badge } from "@/ui/Badge";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { SectionRule } from "@/ui/SectionRule";
import { cn } from "@/ui/cn";

/** Rows past this many go behind the region's own scroll rather than down the page. */
const LIST_ROWS_VISIBLE = 12;

/** A ratio, as the one decimal the eye can actually compare. */
function ratio(n: number): string {
  return n.toFixed(1);
}

/**
 * One anomaly as a sentence. The lens hands over numbers and a kind; the wording — including
 * which clause is optional — belongs to the dictionary, so this is a switch over kinds and
 * nothing else.
 */
function anomalyText(a: Anomaly, t: TFunction): string {
  switch (a.kind) {
    case "deadLink":
      return t("graph.anomaly.deadLink", { count: a.count });
    case "concentration":
      return t("graph.anomaly.concentration", {
        title: a.target?.title ?? a.target?.path ?? "",
        share: fmtPercent(a.value),
        ratio:
          a.extra != null
            ? t("graph.anomaly.concentration.ratio", { ratio: ratio(a.extra) })
            : "",
      });
    case "familyImbalance":
      return t("graph.anomaly.familyImbalance", {
        family: familyFromTemplate(a.template ?? ""),
        pages: a.count,
        share: fmtPercent(a.value),
        factor: ratio(a.extra ?? 0),
      });
    case "zeroPageFamilies":
      return t("graph.anomaly.zeroPageFamilies", { count: a.value, declared: a.count });
    case "arrivalBlind":
      return t("graph.anomaly.arrivalBlind", { count: a.count, share: fmtPercent(a.value) });
    case "deadEnd":
      return t("graph.anomaly.deadEnd", { count: a.count, share: fmtPercent(a.value) });
    case "orphanClaims":
      return t("graph.anomaly.orphanClaims", { count: a.count, share: fmtPercent(a.value) });
  }
}

/**
 * The maintenance dashboard: what this structure looks like from above, and what about it is
 * out of line. Everything is derived client-side from the projection already in hand — the
 * documents, their claims and the links those claims carry.
 *
 * Presentation is the proof-sheet one: ranked lists, difference tables and hairline bars. A
 * force-directed picture of 5927 nodes told a reader nothing; a sentence saying which subject
 * holds two fifths of the base tells them everything, in the time it takes to read it.
 */
export function StructureHealthPanel({
  health,
  files,
  templatesAvailable,
}: {
  health: StructureHealth;
  /** canonical files before volumes are folded in — the number the projection reports */
  files: number;
  /** false when the skill's declared path templates could not be read */
  templatesAvailable: boolean;
}) {
  const t = useT();
  const jump = useApp((s) => s.jump);
  const openUnit = (unit: { path: string; documentId: string | null }) =>
    jump({ kind: "document", id: unit.documentId ?? unit.path }, "library");

  const { concentration: conc, connectivity: conn, families, anomalies } = health;
  const headline = anomalies.slice(0, 3);
  const rest = anomalies.length - headline.length;

  return (
    <div className="flex flex-col gap-8">
      <p className="max-w-measure text-13 text-ink-3">
        {t("graph.health.summary", {
          files,
          subjects: health.units.length,
          claims: conc.totalClaims,
          edges: conn.edges,
        })}
      </p>

      {/* The headline: the whole point of landing here. Three sentences, worst first. */}
      <section aria-label={t("graph.health.headline", { count: headline.length })}>
        {headline.length === 0 ? (
          <p className="max-w-measure text-14 text-ink-2">{t("graph.health.clean")}</p>
        ) : (
          <>
            <p className="text-12 text-ink-3">
              {t("graph.health.headline", { count: headline.length })}
            </p>
            <ol className="mt-2 flex flex-col border-t border-line">
              {headline.map((a, i) => {
                const target = a.target;
                const body = (
                  <>
                    <Mono
                      className={cn(
                        "mt-0.5 shrink-0 text-12",
                        a.tone === "danger" ? "text-danger" : "text-warn",
                      )}
                    >
                      {String(i + 1).padStart(2, "0")}
                    </Mono>
                    <span className="min-w-0 flex-1 font-serif text-20 leading-[1.35] text-balance text-ink">
                      {anomalyText(a, t)}
                    </span>
                    {target && (
                      <ArrowUpRight
                        size={14}
                        aria-hidden
                        className="mt-1.5 shrink-0 text-ink-3"
                      />
                    )}
                  </>
                );
                return (
                  <li key={`${a.kind}-${a.template ?? a.target?.path ?? i}`} className="border-b border-line">
                    {target ? (
                      <button
                        type="button"
                        onClick={() => openUnit(target)}
                        title={t("graph.health.openDocument")}
                        className="flex w-full items-start gap-3 py-3 text-left transition-colors duration-120 hover:bg-hover"
                      >
                        {body}
                      </button>
                    ) : (
                      <div className="flex w-full items-start gap-3 py-3">{body}</div>
                    )}
                  </li>
                );
              })}
            </ol>
            {rest > 0 && (
              <p className="mt-2 text-12 text-ink-3">{t("graph.health.rest", { count: rest })}</p>
            )}
          </>
        )}
      </section>

      {/* -------------------------------------------------------- §01 concentration */}
      <section>
        <SectionRule no={1} title={t("graph.concentration.title")} />
        <p className="mt-2 max-w-measure text-12 text-ink-3">{t("graph.concentration.note")}</p>
        <div className="mt-4 flex flex-wrap gap-x-12 gap-y-4">
          <Figure
            label={t("graph.concentration.lead")}
            value={fmtPercent(conc.leadShare)}
            alarmed={conc.rows[0]?.overThreshold ?? false}
          />
          <Figure
            label={t("graph.concentration.ratio")}
            value={conc.leadRatio != null ? `${ratio(conc.leadRatio)}×` : "—"}
            alarmed={(conc.leadRatio ?? 0) > 4}
          />
        </div>
        <ul className="mt-5 flex flex-col">
          {conc.rows.map((row) => (
            <li key={row.path} className="border-b border-line">
              <button
                type="button"
                onClick={() => openUnit(row)}
                className="flex w-full flex-col gap-1 py-2 text-left transition-colors duration-120 hover:bg-hover"
              >
                <span className="flex min-w-0 items-baseline gap-3">
                  <span className="min-w-0 flex-1 truncate text-13 text-ink">{row.title}</span>
                  {row.volumes.length > 0 && (
                    <span className="shrink-0 text-12 text-ink-3">
                      {t("graph.concentration.volumes", { count: row.volumes.length })}
                    </span>
                  )}
                  <Mono className="shrink-0 text-12 text-ink-3">
                    {t("graph.concentration.claims", { count: row.claims })}
                  </Mono>
                  <Mono
                    className={cn(
                      "w-14 shrink-0 text-right text-12",
                      row.overThreshold ? "text-warn" : "text-ink-2",
                    )}
                  >
                    {fmtPercent(row.share)}
                  </Mono>
                </span>
                <ShareBar share={row.share} alarmed={row.overThreshold} />
                <Mono className="truncate text-12 text-ink-3">{row.path}</Mono>
              </button>
            </li>
          ))}
          {conc.tail && (
            <li className="flex items-baseline gap-3 border-b border-line py-2 text-12 text-ink-3">
              <span className="min-w-0 flex-1 truncate">
                {t("graph.concentration.tail", { units: conc.tail.units })}
              </span>
              <Mono>{t("graph.concentration.claims", { count: conc.tail.claims })}</Mono>
              <Mono className="w-14 text-right">{fmtPercent(conc.tail.share)}</Mono>
            </li>
          )}
        </ul>
      </section>

      {/* --------------------------------------------------------- §02 connectivity */}
      <section>
        <SectionRule no={2} title={t("graph.connectivity.title")} />
        <p className="mt-2 max-w-measure text-12 text-ink-3">{t("graph.connectivity.note")}</p>
        <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-2 border border-line bg-line sm:grid-cols-4">
          <Count
            label={t("graph.connectivity.arrivalBlind")}
            value={conn.arrivalBlind.length}
            tone="warn"
          />
          <Count label={t("graph.connectivity.deadEnd")} value={conn.deadEnd.length} tone="warn" />
          <Count
            label={t("graph.connectivity.deadLinks")}
            value={conn.deadLinks.length}
            tone="danger"
          />
          <Count
            label={t("graph.connectivity.orphanClaims")}
            value={conn.orphanClaims}
            tone="warn"
          />
        </dl>
        {conn.arrivalBlind.length === 0 && conn.deadEnd.length === 0 && conn.deadLinks.length === 0 ? (
          <p className="mt-4 max-w-measure text-13 text-ink-2">{t("graph.connectivity.clean")}</p>
        ) : (
          <div className="mt-5 flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-10">
            <UnitList
              title={t("graph.connectivity.arrivalBlindList")}
              units={conn.arrivalBlind}
              onOpen={openUnit}
              note={
                conn.isolated.length > 0
                  ? t("graph.connectivity.isolated", { count: conn.isolated.length })
                  : null
              }
            />
            <UnitList
              title={t("graph.connectivity.deadEndList")}
              units={conn.deadEnd}
              onOpen={openUnit}
              note={null}
            />
          </div>
        )}
      </section>

      {/* ---------------------------------------------------------- §03 family balance */}
      <section>
        <SectionRule no={3} title={t("graph.families.title")} />
        <p className="mt-2 max-w-measure text-12 text-ink-3">{t("graph.families.note")}</p>
        {!templatesAvailable ? (
          <p className="mt-4 max-w-measure text-13 text-ink-3">{t("graph.families.unavailable")}</p>
        ) : (
          <>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[34rem] border-collapse text-13">
                <thead>
                  <tr className="border-b border-line text-12 text-ink-3">
                    <th scope="col" className="py-1.5 pr-3 text-left font-normal">
                      {t("graph.families.family")}
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                      {t("graph.families.pages")}
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                      {t("graph.families.claims")}
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-normal">
                      {t("graph.families.claimShare")}
                    </th>
                    <th scope="col" className="py-1.5 text-right font-normal">
                      {t("graph.families.textShare")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {families.rows.map((row) => (
                    <tr key={row.template} className="border-b border-line last:border-b-0">
                      <td className="py-1.5 pr-3">
                        <span className="flex min-w-0 items-baseline gap-2">
                          <span className="truncate text-ink">
                            {familyFromTemplate(row.template)}
                          </span>
                          <Mono className="min-w-0 truncate text-12 text-ink-3">
                            {row.template}
                          </Mono>
                        </span>
                      </td>
                      <td
                        className={cn(
                          "py-1.5 pr-3 text-right font-mono text-12 tabular-nums",
                          row.pages === 0 ? "text-warn" : "text-ink-2",
                        )}
                      >
                        {fmtCount(row.pages)}
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono text-12 text-ink-2 tabular-nums">
                        {fmtCount(row.claims)}
                      </td>
                      <td
                        className={cn(
                          "py-1.5 pr-3 text-right font-mono text-12 tabular-nums",
                          row.imbalanced ? "text-warn" : "text-ink-2",
                        )}
                      >
                        {fmtPercent(row.claimShare)}
                        {row.imbalanced && row.imbalance != null && (
                          <span className="ml-1.5">{ratio(row.imbalance)}×</span>
                        )}
                      </td>
                      <td className="py-1.5 text-right font-mono text-12 text-ink-2 tabular-nums">
                        {fmtPercent(row.charShare)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {families.zeroPage.length > 0 && (
              <p className="mt-3 flex flex-wrap items-baseline gap-2 text-12">
                <Badge tone="warn">
                  {t("graph.families.zeroPage", { count: families.zeroPage.length })}
                </Badge>
                {families.zeroPage.map((template) => (
                  <Mono key={template} className="text-12 text-ink-3">
                    {template}
                  </Mono>
                ))}
              </p>
            )}
            {families.unowned.length > 0 && (
              <p className="mt-2 text-12 text-ink-3">
                {t("graph.families.unowned", { count: families.unowned.length })}
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}

/** One headline number: label above, figure below. No cards, no grid of tiles. */
function Figure({
  label,
  value,
  alarmed,
}: {
  label: string;
  value: string;
  alarmed: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-12 text-ink-3">{label}</span>
      <span
        className={cn(
          "font-mono text-38 leading-none tabular-nums",
          alarmed ? "text-warn" : "text-ink",
        )}
      >
        {value}
      </span>
    </div>
  );
}

/** A hairline share bar. Width is data; the only colour it can take is a real warning. */
function ShareBar({ share, alarmed }: { share: number; alarmed: boolean }) {
  return (
    <span aria-hidden className="block h-[3px] w-full bg-line">
      <span
        className={cn("block h-full", alarmed ? "bg-warn" : "bg-ink-3")}
        style={{ width: `${Math.max(share * 100, 0.4)}%` }}
      />
    </span>
  );
}

function Count({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "warn" | "danger";
}) {
  return (
    <div className="flex flex-col gap-1 bg-surface px-3 py-2.5">
      <dt className="text-12 text-ink-3">{label}</dt>
      <dd
        className={cn(
          "font-mono text-20 tabular-nums",
          value === 0 ? "text-ink-3" : tone === "danger" ? "text-danger" : "text-warn",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/** A named list of subjects, each a way into the document it names. */
function UnitList({
  title,
  units,
  note,
  onOpen,
}: {
  title: string;
  units: StructureUnit[];
  note: string | null;
  onOpen: (unit: StructureUnit) => void;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  if (units.length === 0) return null;
  const overflowing = units.length > LIST_ROWS_VISIBLE;
  return (
    <section className="min-w-0 flex-1">
      <p className="text-12 text-ink-3">
        {title} · {units.length}
      </p>
      <ScrollRegion
        className={cn("mt-1", overflowing && !expanded && "max-h-64")}
        aria-label={title}
      >
        <ul className="flex flex-col">
          {units.map((unit) => (
            <li key={unit.path} className="border-b border-line last:border-b-0">
              <button
                type="button"
                onClick={() => onOpen(unit)}
                className="flex w-full min-w-0 flex-col py-1.5 text-left transition-colors duration-120 hover:bg-hover"
              >
                <span className="truncate text-13 text-ink">{unit.title}</span>
                <Mono className="truncate text-12 text-ink-3">{unit.path}</Mono>
              </button>
            </li>
          ))}
        </ul>
      </ScrollRegion>
      {overflowing && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-12 text-accent transition-colors duration-120 hover:underline"
        >
          {expanded ? t("common.list.collapse") : t("common.list.showAll", { count: units.length })}
        </button>
      )}
      {note && <p className="mt-1 text-12 text-ink-3">{note}</p>}
    </section>
  );
}
