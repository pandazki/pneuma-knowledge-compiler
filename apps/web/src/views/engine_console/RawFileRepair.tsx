/**
 * Raw file repair — the way out of a broken engine.
 *
 * `GET /v1/engine/state` refuses to guess at a file that does not parse, which is right, and
 * leaves the console with no values and no editor, which is not. This drawer reads ONE file
 * verbatim through `GET /v1/engine/file`, lets it be fixed, and applies it through the ordinary
 * apply path — same validation, same labelled version. No `expected_head`: there is no readable
 * state to have composed against, and inventing one would only refuse the repair.
 */
import { useEffect, useState } from "react";
import type { EngineSchema } from "@/engine/types";
import { applyChanges, getFile } from "@/engine/api";
import { useT } from "@/lib/useT";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Drawer } from "@/ui/Drawer";
import { Mono } from "@/ui/Mono";
import { Select } from "@/ui/Select";
import { TextArea } from "@/ui/TextArea";
import { TextField } from "@/ui/TextField";

const LABEL_MAX = 60;

export interface RawFileRepairProps {
  schema: EngineSchema | null;
  /** Pre-selected path — the stage file the state error named, when it named one. */
  suggestedPath?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful apply so the console refetches everything. */
  onApplied: () => void;
}

export function RawFileRepair({
  schema,
  suggestedPath,
  open,
  onOpenChange,
  onApplied,
}: RawFileRepairProps) {
  const t = useT();
  const files = (schema?.stages ?? []).map((s) => s.file);
  const [path, setPath] = useState<string | null>(suggestedPath ?? null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);

  useEffect(() => {
    if (open) setPath((current) => current ?? suggestedPath ?? null);
  }, [open, suggestedPath]);

  // Read the chosen file verbatim. Nothing is prefilled from a resolved state: the whole point
  // is that the state is unreadable, so an empty editor here would be a blank waiting to
  // overwrite the file it was meant to fix.
  useEffect(() => {
    if (!open || !path) return;
    let live = true;
    setBusy(true);
    setError(null);
    setApplied(null);
    getFile(path)
      .then((file) => {
        if (!live) return;
        setContent(file.content);
        setLoaded(file.path);
      })
      .catch((e: Error) => {
        if (!live) return;
        setContent("");
        setLoaded(null);
        setError(e.message);
      })
      .finally(() => {
        if (live) setBusy(false);
      });
    return () => {
      live = false;
    };
  }, [open, path]);

  const apply = async () => {
    if (!loaded || label.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      const result = await applyChanges([{ path: loaded, content }], label.trim());
      setApplied(result.sha);
      onApplied();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const close = (next: boolean) => {
    onOpenChange(next);
    if (!next) {
      setError(null);
      setApplied(null);
      setLabel("");
    }
  };

  return (
    <Drawer
      open={open}
      onOpenChange={close}
      side="bottom"
      contentClassName="h-[85vh] max-h-[85vh]"
      title={t("engineConsole.repair.title")}
    >
      <div className="flex h-full flex-col gap-3 px-4 py-3">
        <p className="shrink-0 text-13 leading-6 text-ink-2">{t("engineConsole.repair.hint")}</p>
        <Select
          value={path}
          onChange={setPath}
          options={files.map((f) => ({ value: f, label: f }))}
          placeholder={t("engineConsole.repair.pick")}
          aria-label={t("engineConsole.repair.pick")}
        />
        {applied && (
          <Callout tone="notice" variant="inline">
            {t("engineConsole.review.applied", { sha: applied })}
          </Callout>
        )}
        {error && (
          <Callout tone="danger" variant="inline">
            <Mono className="text-12">{error}</Mono>
          </Callout>
        )}
        {loaded && (
          <>
            <TextArea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              aria-label={loaded}
              spellCheck={false}
              className="min-h-[40vh] font-mono text-13 leading-6"
              wrapperClassName="py-3"
            />
            <TextField
              label={t("engineConsole.review.label")}
              value={label}
              onChange={(e) => setLabel(e.target.value.slice(0, LABEL_MAX))}
              placeholder={t("engineConsole.review.labelPlaceholder")}
              maxLength={LABEL_MAX}
            />
            <div>
              <Button
                variant="primary"
                loading={busy}
                disabled={busy || label.trim() === ""}
                onClick={apply}
              >
                {t("engineConsole.repair.apply")}
              </Button>
            </div>
          </>
        )}
      </div>
    </Drawer>
  );
}
