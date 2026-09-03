import { X } from "lucide-react";
import { fmtCount } from "@/lib/format";
import {
  EMPTY_SOURCE_FILTER,
  toggleValue,
  withDimension,
  type FacetDimension,
  type FacetGroup,
  type SourceFilter,
} from "@/lib/sourceFilter";
import { useT, useTOr } from "@/lib/useT";
import { Mono } from "@/ui/Mono";
import { SearchField } from "@/ui/SearchField";
import { Switch } from "@/ui/Switch";
import { cn } from "@/ui/cn";

/** The dictionary family each dimension's VALUES are named by. */
const VALUE_FAMILY: Record<FacetDimension, string> = {
  kind: "enum.sourceKind",
  source_class: "enum.sourceClass",
  origin: "enum.sourceOrigin",
};

const DIMENSION_LABEL = {
  kind: "sources.filter.dimension.kind",
  source_class: "sources.filter.dimension.source_class",
  origin: "sources.filter.dimension.origin",
} as const;

/**
 * The catalogue's control bar: a title box, the chips the inventory actually divides into,
 * and a corpus-time range — pinned above the list, never scrolling with it.
 *
 * It is deliberately three lightweight rows of hairline controls rather than a filter panel.
 * The reader's question ("where is the one about the release?") is answered by typing four
 * characters; anything that costs a dialog first has already lost. The chips carry their own
 * counts because a chip that might return nothing should say so before it is clicked, and the
 * count line states the narrowing as a fact — 5,832 → 214 — so the reader can tell "no hits"
 * from "still loading".
 */
export function SourceFilterBar({
  filter,
  onChange,
  facets,
  total,
  hits,
  bounds,
  loading,
  loaded,
}: {
  filter: SourceFilter;
  onChange: (filter: SourceFilter) => void;
  facets: FacetGroup[];
  /** Rows in the catalogue (everything held), and rows the filter lets through. */
  total: number;
  hits: number;
  /** The span the catalogue covers, offered to the date fields. */
  bounds: { from: string | null; to: string | null };
  loading: boolean;
  loaded: number;
}) {
  const t = useT();
  const tOr = useTOr();
  const narrowed = hits !== total;
  const active =
    filter.query.trim() !== "" ||
    filter.kinds.length > 0 ||
    filter.classes.length > 0 ||
    filter.origins.length > 0 ||
    filter.from != null ||
    filter.to != null ||
    filter.includeArchived;

  return (
    <section
      aria-label={t("sources.filter.aria")}
      className="flex shrink-0 flex-col gap-2.5 border-b border-line pb-3"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <SearchField
          id="sources-filter-query"
          name="query"
          value={filter.query}
          onChange={(query) => onChange({ ...filter, query })}
          aria-label={t("sources.filter.searchAria")}
          placeholder={t("sources.filter.searchPlaceholder")}
          wrapperClassName="min-w-0 flex-1 basis-64"
        />

        <label className="flex shrink-0 items-center gap-1.5 text-12 text-ink-3">
          <span>{t("sources.filter.range")}</span>
          <DayField
            value={filter.from}
            onChange={(from) => onChange({ ...filter, from })}
            label={t("sources.filter.rangeFrom")}
            bounds={bounds}
          />
          <span aria-hidden>–</span>
          <DayField
            value={filter.to}
            onChange={(to) => onChange({ ...filter, to })}
            label={t("sources.filter.rangeTo")}
            bounds={bounds}
          />
        </label>

        {/* The archive dimension, and the only control here that is also a REQUEST: the
            listing route excludes archived sources unless the call asks for them, so this
            toggle re-crawls rather than merely re-filtering what is already held. */}
        <Switch
          checked={filter.includeArchived}
          onCheckedChange={(includeArchived) => onChange({ ...filter, includeArchived })}
          label={<span className="text-12 text-ink-2">{t("archive.sources.show")}</span>}
          aria-label={t("archive.sources.showHint")}
          wrapperClassName="shrink-0"
        />
      </div>

      {facets.map((group) => (
        <div key={group.dimension} className="flex flex-wrap items-baseline gap-1.5">
          <span className="w-10 shrink-0 text-12 text-ink-3">
            {t(DIMENSION_LABEL[group.dimension])}
          </span>
          {group.values.map((value) => (
            <Chip
              key={value.value}
              label={tOr(`${VALUE_FAMILY[group.dimension]}.${value.value}`, value.value)}
              count={value.count}
              selected={value.selected}
              ariaLabel={t("sources.filter.chipAria", {
                dimension: t(DIMENSION_LABEL[group.dimension]),
                value: tOr(`${VALUE_FAMILY[group.dimension]}.${value.value}`, value.value),
                count: value.count,
              })}
              onClick={() =>
                onChange(
                  withDimension(
                    filter,
                    group.dimension,
                    toggleValue(
                      group.dimension === "kind"
                        ? filter.kinds
                        : group.dimension === "origin"
                          ? filter.origins
                          : filter.classes,
                      value.value,
                    ),
                  ),
                )
              }
            />
          ))}
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p aria-live="polite" className="text-12 text-ink-3">
          {loading
            ? t("sources.filter.loading", {
                loaded: fmtCount(loaded),
                total: fmtCount(total),
              })
            : narrowed
              ? t("sources.filter.narrowed", {
                  total: fmtCount(total),
                  shown: fmtCount(hits),
                })
              : t("sources.filter.count", { total: fmtCount(total) })}
        </p>
        {active && (
          <button
            type="button"
            onClick={() => onChange(EMPTY_SOURCE_FILTER)}
            className="inline-flex items-center gap-1 rounded-1 text-12 text-accent hover:underline"
          >
            <X size={12} aria-hidden />
            {t("sources.filter.clear")}
          </button>
        )}
      </div>
    </section>
  );
}

function DayField({
  value,
  onChange,
  label,
  bounds,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  label: string;
  bounds: { from: string | null; to: string | null };
}) {
  return (
    <input
      type="date"
      name={label}
      aria-label={label}
      value={value ?? ""}
      min={bounds.from ?? undefined}
      max={bounds.to ?? undefined}
      onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
      className={cn(
        "h-7 rounded-1 border border-line-2 bg-surface px-1.5 text-12 text-ink",
        "transition-colors duration-120 ease-out",
        "hover:not-focus:border-ink-3",
        "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1",
      )}
    />
  );
}

function Chip({
  label,
  count,
  selected,
  ariaLabel,
  onClick,
}: {
  label: string;
  count: number;
  selected: boolean;
  ariaLabel: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-baseline gap-1 rounded-2 border px-2 py-0.5 text-12",
        "transition-colors duration-120 ease-out",
        "focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1",
        selected
          ? "border-accent bg-accent-soft text-ink"
          : "border-line-2 text-ink-2 hover:border-ink-3 hover:bg-hover",
        // A chip worth nothing under the rest of the filter still shows, dimmed: it is part
        // of the shape of the catalogue, and hiding it would misreport that shape.
        !selected && count === 0 && "opacity-45",
      )}
    >
      <span>{label}</span>
      <Mono className="text-ink-3">{fmtCount(count)}</Mono>
    </button>
  );
}
