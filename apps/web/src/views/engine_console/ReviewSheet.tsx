/**
 * Review sheet: every pending draft edit as one honest row — file, knob, old → new, blast
 * radius — then a label and the apply call. Applying writes the engine files and lands as
 * a version; the returned effects are shown back verbatim.
 */
import { useMemo, useState } from "react";
import type { EngineApplyResult, EngineSchema, EngineState } from "@/engine/types";
import { applyChanges } from "@/engine/api";
import { ApiError } from "@/lib/api";
import { useEngineDraft } from "@/engine/draft";
import {
  buildApplyPayload,
  pendingChanges,
  type PendingChange,
} from "@/lib/engineConsole";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Drawer } from "@/ui/Drawer";
import { Mono } from "@/ui/Mono";
import { TextField } from "@/ui/TextField";
import { EffectBadge, statesI2 } from "./badges";

const LABEL_MAX = 60;

export interface ReviewSheetProps {
  schema: EngineSchema;
  state: EngineState;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful apply so the view refetches state + history. */
  onApplied: () => void;
}

export function ReviewSheet({
  schema,
  state,
  open,
  onOpenChange,
  onApplied,
}: ReviewSheetProps) {
  const t = useT();
  const draft = useEngineDraft();
  const [label, setLabel] = useState("");
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** A 409 is not a bad request: the read this draft was composed against went stale. */
  const [stale, setStale] = useState<string | null>(null);
  const [result, setResult] = useState<EngineApplyResult | null>(null);

  const changes = useMemo(
    () => pendingChanges(schema, state, draft),
    [schema, state, draft],
  );
  const payload = useMemo(
    () => buildApplyPayload(schema, state, draft),
    [schema, state, draft],
  );

  const canApply =
    changes.length > 0 && label.trim().length > 0 && label.length <= LABEL_MAX && !applying;

  const apply = async () => {
    setApplying(true);
    setError(null);
    setStale(null);
    try {
      // The HEAD this draft was composed against travels with it: the payload is whole
      // files, so applying it onto a version somebody else moved would revert their edit.
      const res = await applyChanges(payload, label.trim(), state.version.head);
      draft.clear();
      setResult(res);
      onApplied();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // The draft is kept: the edits are still what the person wanted, they just have to
        // be re-composed against the version that landed. Reloading brings it in.
        setStale(e.message);
        onApplied();
      } else {
        setError((e as Error).message);
      }
    } finally {
      setApplying(false);
    }
  };

  const close = (next: boolean) => {
    onOpenChange(next);
    if (!next) {
      setResult(null);
      setError(null);
      setStale(null);
      setLabel("");
    }
  };

  return (
    <Drawer
      open={open}
      onOpenChange={close}
      side="bottom"
      title={t("engineConsole.review.title")}
      actions={
        changes.length > 0 && !result ? (
          <Badge>{t("engineConsole.review.files", { count: payload.length })}</Badge>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-4 px-4 py-4">
        {result ? (
          <div className="flex flex-col gap-3">
            <Callout tone="notice" variant="inline">
              {t("engineConsole.review.applied", { sha: result.sha })}
            </Callout>
            <div className="flex flex-col gap-1.5">
              <p className="text-12 text-ink-3">{t("engineConsole.review.effects")}</p>
              <ul className="flex flex-col gap-1">
                {result.effects.map((e) => (
                  <li key={e.key} className="flex items-center gap-2">
                    <Mono className="text-12 text-ink">{e.key}</Mono>
                    <EffectBadge apply={e.apply} showLabel />
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : changes.length === 0 ? (
          <p className="text-13 text-ink-3">{t("engineConsole.review.empty")}</p>
        ) : (
          <>
            <ul className="flex flex-col divide-y divide-line rounded-2 border border-line">
              {changes.map((change, i) => (
                <ChangeRow key={i} change={change} />
              ))}
            </ul>
            {statesI2(
              changes
                .map((change) => change.apply)
                .filter((apply): apply is NonNullable<typeof apply> => apply != null),
            ) && (
              <p className="text-12 leading-5 text-ink-3">{t("engineConsole.i2")}</p>
            )}
            <TextField
              label={t("engineConsole.review.label")}
              value={label}
              onChange={(e) => setLabel(e.target.value.slice(0, LABEL_MAX))}
              placeholder={t("engineConsole.review.labelPlaceholder")}
              hint={t("engineConsole.review.labelHint")}
              maxLength={LABEL_MAX}
            />
            {stale && (
              <Callout tone="notice" variant="inline">
                <span className="flex flex-col gap-1">
                  <span className="text-13">{t("engineConsole.review.stale")}</span>
                  <Mono className="text-12 text-ink-3">{stale}</Mono>
                </span>
              </Callout>
            )}
            {error && (
              <Callout tone="danger" variant="inline">
                <Mono className="text-12">{error}</Mono>
              </Callout>
            )}
            <div>
              <Button variant="primary" disabled={!canApply} loading={applying} onClick={apply}>
                {t("engineConsole.review.apply")}
              </Button>
            </div>
          </>
        )}
      </div>
    </Drawer>
  );
}

function fmtValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function ChangeRow({ change }: { change: PendingChange }) {
  const t = useT();
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
      <Mono className="text-12 text-ink">{change.key}</Mono>
      <Mono className="text-12 text-ink-3">{change.path}</Mono>
      <span className="min-w-0 flex-1 truncate text-13 text-ink-2">
        {change.kind === "knob" && (
          <>
            <Mono className="text-12">{fmtValue(change.oldValue)}</Mono>
            {" → "}
            <Mono className="text-12 text-ink">{fmtValue(change.newValue)}</Mono>
          </>
        )}
        {change.kind === "document" && t("engineConsole.review.document")}
        {change.kind === "file" && t("engineConsole.review.fileRestore")}
        {change.kind === "overlay" && (
          <>
            <Mono className="text-12">{change.catalogKey}</Mono>
            {" · "}
            {change.clause == null
              ? t("engineConsole.review.overlayRemove")
              : t("engineConsole.review.overlaySet")}
          </>
        )}
      </span>
      {change.apply && <EffectBadge apply={change.apply} showLabel />}
    </li>
  );
}
