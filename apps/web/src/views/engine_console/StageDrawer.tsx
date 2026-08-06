import { useEffect, useState } from "react";
import { X } from "lucide-react";
import type {
  EngineHistoryEntry,
  EngineKnob,
  EngineStage,
  EngineState,
} from "@/engine/types";
import { useEngineDraft } from "@/engine/draft";
import {
  knobRef,
  knobResolution,
  knobValue,
  pickLocalized,
  type ScalarValue,
} from "@/lib/engineConsole";
import { useLocale, useT } from "@/lib/useT";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { IconButton } from "@/ui/IconButton";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Switch } from "@/ui/Switch";
import { TextField } from "@/ui/TextField";
import { DocumentEditor } from "./ContractEditor";
import { OverlaysPicker } from "./OverlaysPicker";
import { EffectBadge, OriginBadge, statesI2 } from "./badges";

export interface StageInspectorProps {
  stage: EngineStage;
  state: EngineState | null;
  history: EngineHistoryEntry[];
  stateError: string | null;
  onClose: () => void;
  onRepair: () => void;
  onOpenPromptStudio: () => void;
}

/** The always-present right rail's selected-stage face. */
export function StageInspector({
  stage,
  state,
  history,
  stateError,
  onClose,
  onRepair,
  onOpenPromptStudio,
}: StageInspectorProps) {
  const t = useT();
  const locale = useLocale();
  const document = stage.knobs.some((knob) => knob.type === "document");
  const overlays = stage.knobs.some((knob) => knob.type === "overlay_map");
  const switches = stage.knobs.filter((knob) => knob.type === "bool");
  const parameters = stage.knobs.filter(
    (knob) => knob.type !== "bool" && knob.type !== "document" && knob.type !== "overlay_map",
  );
  const envPinnedCount = state
    ? stage.knobs.filter(
        (knob) => Boolean(knob.env) && knobResolution(state, stage.id, knob) === "env",
      ).length
    : 0;

  return (
    <div className="engine-inspector__swap" data-mode="detail">
      <header className="engine-inspector__header">
        <div className="engine-inspector__header-copy">
          <h2>{pickLocalized(stage.title, locale)}</h2>
          <p title={stage.file}>{stage.file}</p>
        </div>
        <IconButton aria-label={t("engineConsole.overview.back")} onClick={onClose}>
          <X size={16} aria-hidden />
        </IconButton>
      </header>

      <div className="engine-inspector__body">
        {state?.keyless && stage.id === "models" && (
          <section className="engine-inspector__section engine-inspector__keyless-note" role="status">
            <span aria-hidden>◇</span>
            <p>{t("engineConsole.models.keylessNotice")}</p>
          </section>
        )}

        <section className="engine-inspector__section">
          <p className="engine-inspector__prose">{pickLocalized(stage.summary, locale)}</p>
          <div className="engine-inspector__meta">
            <span>{t("engineConsole.stage.docPath", { path: stage.doc })}</span>
          </div>
        </section>

        {!state && (
          <section className="engine-inspector__section">
            <Callout tone="danger" variant="inline">
              <span className="flex flex-col items-start gap-2">
                <span className="text-13">{t("engineConsole.stage.valuesUnavailable")}</span>
                {stateError && <code className="break-all text-12">{stateError}</code>}
                <Button size="sm" variant="default" onClick={onRepair}>
                  {t("engineConsole.repair.open")}
                </Button>
              </span>
            </Callout>
          </section>
        )}

        {state && envPinnedCount > 0 && (
          <section className="engine-inspector__section">
            <Callout tone="notice" variant="inline">
              <span className="text-12">
                {t("engineConsole.envOverrideSummary", { count: envPinnedCount })}
              </span>
            </Callout>
          </section>
        )}

        {state && document && (
          <DocumentEditor stage={stage} state={state} history={history} />
        )}

        {state && overlays && (
          <>
            <section className="engine-inspector__section">
              <h3>{t("engineConsole.stage.overlayHeading")}</h3>
              <p className="engine-inspector__prose">
                {t("engineConsole.stage.overlayIntro")}
              </p>
            </section>
            <OverlaysPicker
              knob={stage.knobs.find((knob) => knob.type === "overlay_map")!}
              stage={stage}
              state={state}
              onOpen={onOpenPromptStudio}
            />
          </>
        )}

        {state && switches.length > 0 && (
          <KnobGroup
            title={t("engineConsole.stage.switches")}
            stage={stage}
            knobs={switches}
            state={state}
          />
        )}

        {state && parameters.length > 0 && (
          <KnobGroup
            title={t("engineConsole.stage.parameters")}
            stage={stage}
            knobs={parameters}
            state={state}
          />
        )}

        {state && statesI2(stage.knobs.map((knob) => knob.apply)) && (
          <p className="engine-inspector__i2-note">{t("engineConsole.i2")}</p>
        )}
      </div>
    </div>
  );
}

function KnobGroup({
  title,
  stage,
  knobs,
  state,
}: {
  title: string;
  stage: EngineStage;
  knobs: EngineKnob[];
  state: EngineState;
}) {
  return (
    <section className="engine-knob-group">
      <header className="engine-knob-group__header">
        <h3 className="engine-inspector__group-title">{title}</h3>
      </header>
      {knobs.map((knob) => (
        <KnobRow key={knob.key} stage={stage} knob={knob} state={state} />
      ))}
    </section>
  );
}

function KnobRow({
  stage,
  knob,
  state,
}: {
  stage: EngineStage;
  knob: EngineKnob;
  state: EngineState;
}) {
  const locale = useLocale();
  const draft = useEngineDraft();
  const ref = knobRef(stage.id, knob.key);
  const origin = knobResolution(state, stage.id, knob);
  const envPinned = origin === "env";
  const value = knobValue(state, draft, stage.id, knob);

  return (
    <div className="engine-knob-row">
      <div
        className="engine-knob-row__heading"
        data-wide={knob.type === "enum" || knob.type === "string" || undefined}
      >
        <div className="engine-knob-row__title">
          <h4>{pickLocalized(knob.label, locale)}</h4>
          <div className="engine-knob-row__badges">
            <OriginBadge origin={origin} />
            <EffectBadge apply={knob.apply} />
          </div>
        </div>
        <div className="engine-knob-row__control">
          <KnobControl
            knob={knob}
            value={value}
            disabled={envPinned}
            onChange={(next) => draft.setValue(ref, next)}
          />
        </div>
      </div>
      <p className="engine-knob-row__description">
        {pickLocalized(knob.description, locale)}
      </p>
      {knob.env && <code className="engine-knob-row__env" title={knob.env}>{knob.env}</code>}
    </div>
  );
}

function KnobControl({
  knob,
  value,
  disabled,
  onChange,
}: {
  knob: EngineKnob;
  value: unknown;
  disabled: boolean;
  onChange: (value: ScalarValue) => void;
}) {
  const locale = useLocale();
  const label = pickLocalized(knob.label, locale);
  if (knob.type === "bool") {
    return (
      <Switch
        checked={Boolean(value)}
        onCheckedChange={onChange}
        disabled={disabled}
        aria-label={label}
      />
    );
  }
  if (knob.type === "enum") {
    return (
      <SegmentedControl
        value={String(value ?? knob.default ?? "")}
        onChange={onChange}
        options={(knob.enum ?? []).map((option) => ({ value: option, label: option, disabled }))}
        aria-label={label}
        size="sm"
      />
    );
  }
  if (knob.type === "int") {
    return (
      <ValidatedNumberKnob
        value={typeof value === "number" ? value : null}
        onChange={onChange}
        aria-label={label}
        disabled={disabled}
      />
    );
  }
  return (
    <TextField
      value={String(value ?? "")}
      onChange={(event) => onChange(event.target.value)}
      aria-label={label}
      disabled={disabled}
      wrapperClassName="w-full"
    />
  );
}

function ValidatedNumberKnob({
  value,
  onChange,
  disabled,
  "aria-label": ariaLabel,
}: {
  value: number | null;
  onChange: (value: number) => void;
  disabled: boolean;
  "aria-label": string;
}) {
  const t = useT();
  const [raw, setRaw] = useState(value == null ? "" : String(value));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRaw(value == null ? "" : String(value));
    setError(null);
  }, [value]);

  const restore = () => setRaw(value == null ? "" : String(value));
  const commit = () => {
    const trimmed = raw.trim();
    if (!/^\d+$/.test(trimmed) || !Number.isSafeInteger(Number(trimmed))) {
      restore();
      setError(t("engineConsole.number.invalid"));
      return;
    }
    const next = Number(trimmed);
    setRaw(String(next));
    setError(null);
    if (next !== value) onChange(next);
  };

  return (
    <TextField
      type="text"
      inputMode="numeric"
      value={raw}
      onChange={(event) => {
        setRaw(event.target.value);
        setError(null);
      }}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          event.currentTarget.blur();
        } else if (event.key === "Escape") {
          restore();
          setError(null);
          event.currentTarget.blur();
        }
      }}
      error={error}
      aria-label={ariaLabel}
      disabled={disabled}
      wrapperClassName="w-32"
      className="tabular-nums"
    />
  );
}
