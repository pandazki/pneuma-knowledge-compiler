import { Wrench } from "lucide-react";
import type { EngineHistoryEntry, EngineSchema, EngineState, EngineValue } from "@/engine/types";
import { fmtTime } from "@/lib/format";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { VersionTimeline } from "./VersionTimeline";

export interface EngineOverviewProps {
  schema: EngineSchema | null;
  state: EngineState | null;
  history: EngineHistoryEntry[];
  stateError: string | null;
  historyError: string | null;
  pendingCount: number;
  onRepair: () => void;
  onLoadVersionDraft: (files: Record<string, string>) => void;
}

export function EngineOverview({
  schema,
  state,
  history,
  stateError,
  historyError,
  pendingCount,
  onRepair,
  onLoadVersionDraft,
}: EngineOverviewProps) {
  const t = useT();
  const values = state?.values ?? {};
  const latest = history[0] ?? null;
  const overlayStage = schema?.stages.find((stage) =>
    stage.knobs.some((knob) => knob.type === "overlay_map"),
  );
  const overlayKnob = overlayStage?.knobs.find((knob) => knob.type === "overlay_map");
  const activeOverlays = objectSize(values["prompts.overlays"]);
  const overlayCoverage = overlayKnob
    ? t("engineConsole.overview.overlayCoverage", {
        active: activeOverlays,
        total: overlayKnob.enum?.length ?? 0,
      })
    : t("engineConsole.value.unavailable");

  const macroRows: Array<[Parameters<typeof t>[0], string]> = [
    ["engineConsole.overview.chunking", showValue(values["intake.chunk_strategy"], t)],
    [
      "engineConsole.overview.challenge",
      state
        ? t(
            Boolean(values["challenge.enabled"])
              ? "engineConsole.overview.challengeOn"
              : "engineConsole.overview.challengeOff",
            { rounds: Number(values["challenge.max_rounds"] ?? 0) },
          )
        : t("engineConsole.value.unavailable"),
    ],
    [
      "engineConsole.overview.evolve",
      state
        ? t(
            Boolean(values["evolve.auto_trigger"])
              ? "engineConsole.overview.evolveAuto"
              : "engineConsole.overview.evolveManual",
            {
              docs: Number(values["evolve.trigger_topic_docs"] ?? 0),
              claims: Number(values["evolve.trigger_new_claims"] ?? 0),
            },
          )
        : t("engineConsole.value.unavailable"),
    ],
    ["engineConsole.overview.answerStyle", showValue(values["recall.answer_style"], t)],
    ["engineConsole.overview.compileModel", showValue(values["models.compile"], t)],
    ["engineConsole.overview.overlays", overlayCoverage],
  ];

  if (state?.keyless) {
    macroRows.splice(4, 0, [
      "engineConsole.overview.modelAvailability",
      t("engineConsole.models.keylessNotice"),
    ]);
  }

  return (
    <div className="engine-inspector__swap" data-mode="overview">
      <header className="engine-inspector__header">
        <div className="engine-inspector__header-copy">
          <h2>{t("engineConsole.overview.title")}</h2>
          <p>
            {state?.version.head
              ? t("engineConsole.overview.head", { sha: state.version.head.slice(0, 8) })
              : t("engineConsole.overview.noHead")}
          </p>
        </div>
        <Badge tone={state?.version.dirty ? "warn" : state ? "ok" : "neutral"}>
          {state
            ? t(state.version.dirty ? "engineConsole.version.dirtyShort" : "engineConsole.version.cleanShort")
            : t("engineConsole.value.unavailable")}
        </Badge>
      </header>

      <div className="engine-inspector__body">
        {stateError && (
          <section className="engine-inspector__section">
            <Callout tone="danger" variant="inline">
              <span className="flex flex-col items-start gap-2">
                <span className="text-13">{t("engineConsole.state.error")}</span>
                <code className="break-all text-12">{stateError}</code>
                <Button size="sm" variant="default" onClick={onRepair}>
                  <Wrench size={13} aria-hidden />
                  {t("engineConsole.repair.open")}
                </Button>
              </span>
            </Callout>
          </section>
        )}

        <section className="engine-inspector__section">
          <h3>{t("engineConsole.overview.ideaHeading")}</h3>
          <p className="engine-inspector__prose">{t("engineConsole.overview.idea")}</p>
          <ul className="engine-overview__principles">
            <li>{t("engineConsole.overview.principleEvidence")}</li>
            <li>{t("engineConsole.overview.principleAccess")}</li>
            <li>{t("engineConsole.overview.principleBoundary")}</li>
            <li>{t("engineConsole.overview.principleDirectory")}</li>
          </ul>
        </section>

        <section className="engine-inspector__section">
          <h3>{t("engineConsole.overview.configHeading")}</h3>
          <dl className="engine-overview__rows">
            {macroRows.map(([labelKey, value]) => (
              <div
                key={labelKey}
                data-keyless={
                  labelKey === "engineConsole.overview.modelAvailability" || undefined
                }
              >
                <dt>{t(labelKey)}</dt>
                <dd title={value}>{value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="engine-inspector__section">
          <h3>{t("engineConsole.overview.statusHeading")}</h3>
          <dl className="engine-overview__status">
            <div>
              <dt>{t("engineConsole.overview.headLabel")}</dt>
              <dd>{state?.version.head?.slice(0, 12) ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("engineConsole.overview.versionCount")}</dt>
              <dd>{history.length}</dd>
            </div>
            <div>
              <dt>{t("engineConsole.overview.latestApply")}</dt>
              <dd>
                {latest
                  ? t("engineConsole.overview.latestApplyValue", {
                      label: latest.label,
                      at: fmtTime(latest.at),
                    })
                  : t("engineConsole.overview.none")}
              </dd>
            </div>
            <div>
              <dt>{t("engineConsole.overview.overlayCount")}</dt>
              <dd>{activeOverlays}</dd>
            </div>
          </dl>
        </section>

        <VersionTimeline
          history={history}
          state={state}
          pendingCount={pendingCount}
          error={historyError}
          onLoadDraft={onLoadVersionDraft}
        />
      </div>
    </div>
  );
}

function objectSize(value: EngineValue | undefined): number {
  return value && typeof value === "object" ? Object.keys(value).length : 0;
}

function showValue(value: EngineValue | undefined, t: ReturnType<typeof useT>): string {
  if (value == null || value === "") return t("engineConsole.value.inherit");
  if (typeof value === "boolean") {
    return t(value ? "engineConsole.value.on" : "engineConsole.value.off");
  }
  if (typeof value === "object") {
    return t("engineConsole.value.overrides", { count: Object.keys(value).length });
  }
  return String(value);
}
