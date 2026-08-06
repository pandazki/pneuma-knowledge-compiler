import {
  CircleDashed,
  Database,
  FastForward,
  FileCog,
  Lock,
  RotateCw,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { ApplyKind, ResolutionOrigin } from "@/engine/types";
import { useT } from "@/lib/useT";
import type { MessageKey } from "@/lib/i18n";
import { Tooltip } from "@/ui/Tooltip";

const EFFECT_ICON: Record<ApplyKind, LucideIcon> = {
  hot: Zap,
  restart: RotateCw,
  future_compiles: FastForward,
  derived_rebuild: Database,
};

const EFFECT_KEY: Record<ApplyKind, MessageKey> = {
  hot: "engineConsole.effect.hot",
  restart: "engineConsole.effect.restart",
  future_compiles: "engineConsole.effect.future_compiles",
  derived_rebuild: "engineConsole.effect.derived_rebuild",
};

const EFFECT_NOTE_KEY: Record<ApplyKind, MessageKey> = {
  hot: "engineConsole.effectNote.hot",
  restart: "engineConsole.effectNote.restart",
  future_compiles: "engineConsole.effectNote.future_compiles",
  derived_rebuild: "engineConsole.effectNote.derived_rebuild",
};

/**
 * The apply kinds that invariant I2 is actually about. `hot` and `restart` change what the
 * next run does; only these two are statements about already-recorded knowledge, so the "canon
 * is never rewritten" line belongs to them and nowhere else. Saying it under a model name or a
 * retrieval budget makes it noise, and noise is how honest copy stops being read.
 */
export const I2_APPLY_KINDS: ApplyKind[] = ["future_compiles", "derived_rebuild"];

export function statesI2(kinds: Iterable<ApplyKind>): boolean {
  for (const kind of kinds) if (I2_APPLY_KINDS.includes(kind)) return true;
  return false;
}

/**
 * Blast radius of an edit. The icon stays quiet in the everyday surface; review can opt into
 * its short label, and the complete localized meaning stays available on hover and focus.
 */
export function EffectBadge({
  apply,
  showLabel = false,
}: {
  apply: ApplyKind;
  showLabel?: boolean;
}) {
  const t = useT();
  return (
    <SemanticIconBadge
      icon={EFFECT_ICON[apply]}
      label={t(EFFECT_KEY[apply])}
      note={t(EFFECT_NOTE_KEY[apply])}
      showLabel={showLabel}
    />
  );
}

const ORIGIN_ICON: Record<ResolutionOrigin, LucideIcon> = {
  env: Lock,
  engine: FileCog,
  default: CircleDashed,
};

const ORIGIN_KEY: Record<ResolutionOrigin, MessageKey> = {
  env: "engineConsole.origin.env",
  engine: "engineConsole.origin.engine",
  default: "engineConsole.origin.default",
};

const ORIGIN_NOTE_KEY: Record<ResolutionOrigin, MessageKey> = {
  env: "engineConsole.originNote.env",
  engine: "engineConsole.originNote.engine",
  default: "engineConsole.originNote.default",
};

/** Where the resolved value comes from (env > engine file > framework default). */
export function OriginBadge({ origin }: { origin: ResolutionOrigin }) {
  const t = useT();
  return (
    <SemanticIconBadge
      icon={ORIGIN_ICON[origin]}
      label={t(ORIGIN_KEY[origin])}
      note={t(ORIGIN_NOTE_KEY[origin])}
    />
  );
}

function SemanticIconBadge({
  icon: Icon,
  label,
  note,
  showLabel = false,
}: {
  icon: LucideIcon;
  label: string;
  note: string;
  showLabel?: boolean;
}) {
  return (
    <Tooltip content={note} side="top">
      <span
        tabIndex={0}
        role="img"
        aria-label={label}
        className={
          showLabel
            ? "inline-flex h-6 shrink-0 cursor-help items-center justify-center gap-1 rounded-1 px-1.5 text-12 font-medium whitespace-nowrap text-ink-2 transition-colors duration-120 ease-out hover:bg-hover hover:text-ink focus-visible:text-ink"
            : "inline-flex size-6 shrink-0 cursor-help items-center justify-center rounded-1 text-ink-3 transition-colors duration-120 ease-out hover:bg-hover hover:text-ink-2 focus-visible:text-ink-2"
        }
      >
        <Icon size={14} strokeWidth={1.75} aria-hidden />
        {showLabel && <span aria-hidden>{label}</span>}
      </span>
    </Tooltip>
  );
}
