import { fmtTime } from "@/lib/format";
import {
  groupFamiliesByArea,
  type SchemaAxis,
  type SchemaFamily,
  type SchemaStation,
} from "@/lib/evolve";
import type { ClaimLabel } from "@/lib/types";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { Tooltip } from "@/ui/Tooltip";
import { cn } from "@/ui/cn";

/**
 * The schema axis: how families / path templates look as they accumulate over time.
 *
 * Not a third store — it is entirely derived from "the adopted task sequence × the current
 * skill" (lib/evolve.ts `buildSchemaAxis`). The baseline skill is the first station, each
 * adopted evolution is one station after it, and the drafts still at the gate get their own
 * "not yet enrolled" segment; a family that was adopted once but is no longer in the current
 * skill is reported as drift rather than hidden.
 */

const ORIGIN_LABEL_KEY: Record<SchemaFamily["origin"], MessageKey> = {
  base: "evolve.origin.base",
  pack: "evolve.origin.pack",
  evolved: "evolve.origin.evolved",
};

function StationMark({ kind }: { kind: SchemaStation["kind"] }) {
  if (kind === "pending") {
    return (
      <span
        aria-hidden
        className="relative z-1 mt-1 size-2.5 rotate-45 border-2 border-warn bg-bg"
      />
    );
  }
  if (kind === "adopted") {
    return <span aria-hidden className="relative z-1 mt-1 size-2.5 bg-ok" />;
  }
  return (
    <span aria-hidden className="relative z-1 mt-1 size-2.5 border-2 border-ink-2 bg-bg" />
  );
}

function StationRow({
  station,
  first,
  last,
  onOpenTask,
}: {
  station: SchemaStation;
  first: boolean;
  last: boolean;
  onOpenTask: (taskId: string) => void;
}) {
  const t = useT();
  const openable = station.kind === "adopted" || station.kind === "pending";
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 py-3">
      {/* The ruler line + the station (station centre 9px below the row top: mt-1 + half a station) */}
      <span className="relative flex w-2.5 justify-center">
        {!(first && last) && (
          <span
            aria-hidden
            className={cn(
              "absolute left-1/2 w-px -translate-x-1/2 bg-line",
              first ? "top-[9px] bottom-0" : last ? "top-0 h-[9px]" : "top-0 bottom-0",
            )}
          />
        )}
        <StationMark kind={station.kind} />
      </span>

      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-serif text-14 font-medium text-ink">
            {t(station.labelKey, station.labelParams)}
          </span>
          {station.kind === "pending" && (
            <Badge tone="warn">{t("evolve.axis.notEnrolled")}</Badge>
          )}
          {station.driftedFamilies.length > 0 && (
            <Badge tone="neutral">
              {t("evolve.axis.driftedCount", { count: station.driftedFamilies.length })}
            </Badge>
          )}
          {station.at && <span className="text-12 text-ink-3">{fmtTime(station.at)}</span>}
          {openable && (
            <button
              type="button"
              onClick={() => onOpenTask(station.id)}
              className="text-12 text-accent underline-offset-2 hover:underline"
            >
              {t("evolve.axis.openTask")}
            </button>
          )}
        </div>

        {station.families.length === 0 ? (
          <p className="mt-1 text-12 text-ink-3">{t("evolve.axis.noNewFamily")}</p>
        ) : (
          <ul className="mt-1.5 flex flex-wrap gap-1">
            {station.families.map((family) => {
              const drifted = station.driftedFamilies.includes(family);
              return (
                <li key={family}>
                  <Mono
                    className={cn(
                      "rounded-1 border px-1.5 py-px text-12",
                      drifted
                        ? "border-line-2 bg-surface text-ink-3 line-through"
                        : station.kind === "pending"
                          ? "border-warn bg-warn-soft text-warn"
                          : "border-line-2 bg-surface text-ink-2",
                    )}
                    title={drifted ? t("evolve.axis.driftedTitle") : undefined}
                  >
                    {station.kind === "base" || station.kind === "pack" ? family : `+${family}`}
                  </Mono>
                </li>
              );
            })}
          </ul>
        )}

        {station.templates.length > 0 && (
          <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
            {station.templates.map((template) => (
              <Mono key={template} className="text-12 text-ink-3">
                {template}
              </Mono>
            ))}
          </p>
        )}
      </div>
    </li>
  );
}

function FamilyRow({
  family,
  onOpenTask,
}: {
  family: SchemaFamily;
  onOpenTask: (taskId: string) => void;
}) {
  const t = useT();
  return (
    <li className="flex flex-col gap-1 border-b border-line py-2 last:border-b-0 sm:flex-row sm:items-baseline sm:gap-3">
      <span className="shrink-0 font-serif text-14 font-medium text-ink sm:w-32">
        {family.family}
      </span>
      <Mono className="min-w-0 flex-1 truncate text-12 text-ink-2" title={family.template}>
        {family.template}
      </Mono>
      <span className="flex shrink-0 items-baseline gap-2">
        <Badge tone={family.origin === "evolved" ? "accent" : "neutral"}>
          {t(ORIGIN_LABEL_KEY[family.origin])}
          {family.origin === "evolved" && family.addedAtOrdinal != null
            ? ` · ${t("evolve.axis.originOrdinal", { n: family.addedAtOrdinal })}`
            : ""}
        </Badge>
        {family.origin === "evolved" && family.addedByTask && (
          <button
            type="button"
            onClick={() => onOpenTask(family.addedByTask as string)}
            className="text-12 text-accent underline-offset-2 hover:underline"
          >
            {t("evolve.axis.originLink")}
          </button>
        )}
      </span>
    </li>
  );
}

export function SchemaAxisPanel({
  axis,
  claimLabels,
  onOpenTask,
}: {
  axis: SchemaAxis;
  claimLabels: ClaimLabel[];
  onOpenTask: (taskId: string) => void;
}) {
  const t = useT();
  const groups = groupFamiliesByArea(axis.families);
  const separator = t("evolve.listSeparator");
  const evolvedCount = axis.families.filter((f) => f.origin === "evolved").length;

  return (
    <div className="flex flex-col gap-8">
      <section>
        <SectionRule no={1} title={t("evolve.axis.currentSkill")} />
        <DefinitionList
          className="mt-2"
          items={[
            {
              term: "version",
              definition: <Mono>{axis.skillVersion ?? "—"}</Mono>,
            },
            {
              term: "base_version",
              definition: <Mono>{axis.baseVersion ?? "—"}</Mono>,
            },
            {
              term: "content_hash",
              definition: (
                <Mono className="break-all">{axis.contentHash ?? "—"}</Mono>
              ),
            },
            {
              term: "family",
              definition: (
                <span className="text-14 text-ink-2">
                  {t("evolve.axis.familyCount", {
                    total: axis.families.length,
                    evolved: evolvedCount,
                  })}
                </span>
              ),
            },
          ]}
        />
        {claimLabels.length > 0 && (
          <>
            <p className="mt-3 text-12 text-ink-3">
              {t("evolve.axis.claimLabels", { count: claimLabels.length })}
            </p>
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {claimLabels.map((label) => (
                <li key={label.label}>
                  <Tooltip content={label.description}>
                    <span
                      tabIndex={0}
                      aria-label={t("evolve.axis.labelAria", {
                        name: label.name,
                        description: label.description,
                      })}
                      className="inline-flex rounded-1 outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1"
                    >
                      <Badge
                        tone={label.tier === "solid" ? "accent" : "neutral"}
                        className={label.tier === "muted" ? "opacity-70" : undefined}
                      >
                        {label.name}
                        <Mono className="text-12 text-ink-3">{label.label}</Mono>
                      </Badge>
                    </span>
                  </Tooltip>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section>
        <SectionRule
          no={2}
          title={t("evolve.axis.stationsTitle", { count: axis.stations.length })}
        />
        {axis.drifted.length > 0 && (
          <Callout tone="warn" title={t("evolve.axis.driftTitle")} className="mt-3">
            {t("evolve.axis.driftBody", { families: axis.drifted.join(separator) })}
          </Callout>
        )}
        <ol className="mt-2 flex flex-col">
          {axis.stations.map((station, index) => (
            <StationRow
              key={`${station.kind}-${station.id}`}
              station={station}
              first={index === 0}
              last={index === axis.stations.length - 1}
              onOpenTask={onOpenTask}
            />
          ))}
        </ol>
      </section>

      <section>
        <SectionRule
          no={3}
          title={t("evolve.axis.familiesTitle", { count: axis.families.length })}
        />
        {axis.families.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">{t("evolve.axis.noTemplates")}</p>
        ) : (
          <div className="mt-3 flex flex-col gap-5">
            {groups.map((group) => (
              <div key={group.area}>
                <p className="flex items-baseline gap-2 border-b border-line-2 pb-1">
                  <Mono className="text-12 text-ink-3">{group.area}/</Mono>
                  <span className="text-12 text-ink-3">
                    {t("evolve.axis.groupCount", { count: group.families.length })}
                  </span>
                </p>
                <ul className="flex flex-col">
                  {group.families.map((family) => (
                    <FamilyRow
                      key={family.template}
                      family={family}
                      onOpenTask={onOpenTask}
                    />
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
        {axis.proposed.length > 0 && (
          <Callout tone="notice" title={t("evolve.axis.proposedTitle")} className="mt-4">
            {t("evolve.axis.proposedBody", { families: axis.proposed.join(separator) })}
          </Callout>
        )}
      </section>
    </div>
  );
}
