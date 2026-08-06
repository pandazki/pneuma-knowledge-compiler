import { ArrowRight, Braces } from "lucide-react";
import { useEngineDraft } from "@/engine/draft";
import type { EngineKnob, EngineStage, EngineState } from "@/engine/types";
import { effectiveOverlays, knobResolution } from "@/lib/engineConsole";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { EffectBadge, OriginBadge } from "./badges";

export interface OverlaysPickerProps {
  knob: EngineKnob;
  stage: EngineStage;
  state: EngineState;
  onOpen: () => void;
}

/** The stage inspector now explains the destination; authoring happens in Prompt Studio. */
export function OverlaysPicker({ knob, stage, state, onOpen }: OverlaysPickerProps) {
  const t = useT();
  const draft = useEngineDraft();
  const overlays = effectiveOverlays(state, draft, stage.file);
  const total = knob.enum?.length ?? 0;
  const active = Object.keys(overlays).length;

  return (
    <div className="engine-overlays-entry">
      <div className="engine-overlays-entry__meta">
        <OriginBadge origin={knobResolution(state, stage.id, knob)} />
        <EffectBadge apply={knob.apply} />
        <Badge tone={active > 0 ? "accent" : "neutral"}>
          {t("engineConsole.overlays.count", { active, total })}
        </Badge>
      </div>
      <button type="button" className="engine-overlays-entry__button" onClick={onOpen}>
        <span className="engine-overlays-entry__icon" aria-hidden>
          <Braces size={18} />
        </span>
        <span className="engine-overlays-entry__copy">
          <strong>{t("engineConsole.studio.open")}</strong>
          <span>{t("engineConsole.studio.openHint")}</span>
        </span>
        <ArrowRight size={16} aria-hidden />
      </button>
    </div>
  );
}
