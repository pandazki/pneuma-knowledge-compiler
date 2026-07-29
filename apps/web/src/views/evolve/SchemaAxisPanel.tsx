import { fmtTime } from "@/lib/format";
import {
  groupFamiliesByArea,
  type SchemaAxis,
  type SchemaFamily,
  type SchemaStation,
} from "@/lib/evolve";
import type { ClaimLabel } from "@/lib/types";
import { Badge } from "@/ui/Badge";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { Tooltip } from "@/ui/Tooltip";
import { cn } from "@/ui/cn";

/**
 * Schema 快照轴：family / 路径模板随时间累积的样貌。
 *
 * 不是第三份存储——它完全是「已采纳任务序列 × 当前 skill」的推导（lib/evolve.ts
 * `buildSchemaAxis`）。基线 skill 是第一站，之后每次 adopted 演化是一刻度，闸门上待审的
 * 草案作为「尚未入册」单独一段；某次采纳过、当前 skill 里却查不到的 family 如实标为漂移。
 */

const ORIGIN_LABEL = {
  base: "基线",
  pack: "注册期 pack",
  evolved: "演化加入",
} as const;

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
  const openable = station.kind === "adopted" || station.kind === "pending";
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 py-3">
      {/* 标尺线 + 刻度（刻度中心距行顶 9px：mt-1 + 半个刻度） */}
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
          <span className="font-serif text-14 font-medium text-ink">{station.label}</span>
          {station.kind === "pending" && <Badge tone="warn">尚未入册</Badge>}
          {station.driftedFamilies.length > 0 && (
            <Badge tone="neutral">{station.driftedFamilies.length} 项已漂移</Badge>
          )}
          {station.at && <span className="text-12 text-ink-3">{fmtTime(station.at)}</span>}
          {openable && (
            <button
              type="button"
              onClick={() => onOpenTask(station.id)}
              className="text-12 text-accent underline-offset-2 hover:underline"
            >
              查看这次演化
            </button>
          )}
        </div>

        {station.families.length === 0 ? (
          <p className="mt-1 text-12 text-ink-3">未新增 family。</p>
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
                    title={drifted ? "当前 skill 里已找不到这个 family" : undefined}
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
          {ORIGIN_LABEL[family.origin]}
          {family.origin === "evolved" && family.addedAtOrdinal != null
            ? ` · 第 ${family.addedAtOrdinal} 次`
            : ""}
        </Badge>
        {family.origin === "evolved" && family.addedByTask && (
          <button
            type="button"
            onClick={() => onOpenTask(family.addedByTask as string)}
            className="text-12 text-accent underline-offset-2 hover:underline"
          >
            来源
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
  const groups = groupFamiliesByArea(axis.families);
  const evolvedCount = axis.families.filter((f) => f.origin === "evolved").length;

  return (
    <div className="flex flex-col gap-8">
      <section>
        <SectionRule no={1} title="当前生效 skill" />
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
                  共 {axis.families.length} 个，其中 {evolvedCount} 个由演化加入
                </span>
              ),
            },
          ]}
        />
        {claimLabels.length > 0 && (
          <>
            <p className="mt-3 text-12 text-ink-3">claim 标签词表 · {claimLabels.length}</p>
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {claimLabels.map((label) => (
                <li key={label.label}>
                  <Tooltip content={label.description}>
                    <span
                      tabIndex={0}
                      aria-label={`${label.name}：${label.description}`}
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
        <SectionRule no={2} title={`累积轴 · ${axis.stations.length} 刻度`} />
        {axis.drifted.length > 0 && (
          <Callout tone="warn" title="schema 漂移" className="mt-3">
            这些 family 曾被采纳、但当前 skill 里已经查不到：
            {axis.drifted.join("、")}。轴上以删除线标出，未做任何补齐。
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
        <SectionRule no={3} title={`当前全量 family · ${axis.families.length}`} />
        {axis.families.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">
            当前 skill 未声明任何路径模板——无法推导 family 一览。
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-5">
            {groups.map((group) => (
              <div key={group.area}>
                <p className="flex items-baseline gap-2 border-b border-line-2 pb-1">
                  <Mono className="text-12 text-ink-3">{group.area}/</Mono>
                  <span className="text-12 text-ink-3">{group.families.length} 个</span>
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
          <Callout tone="notice" title="闸门上待审" className="mt-4">
            {axis.proposed.join("、")} 已被提议，但要等你在时间线上采用后才会进入
            schema。
          </Callout>
        )}
      </section>
    </div>
  );
}
