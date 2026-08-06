import { useEffect, useMemo, useState } from "react";
import { GitCommitHorizontal, RotateCcw } from "lucide-react";
import { getHistoryFiles } from "@/engine/api";
import type {
  EngineHistoryEntry,
  EngineHistoryFiles,
  EngineState,
} from "@/engine/types";
import { fmtTime } from "@/lib/format";
import { changedHistoryFiles } from "@/lib/engineConsole";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Drawer } from "@/ui/Drawer";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";
import { SkeletonText } from "@/ui/Skeleton";
import { DiffBlock } from "./DiffBlock";

export interface VersionTimelineProps {
  history: EngineHistoryEntry[];
  state: EngineState | null;
  pendingCount: number;
  error?: string | null;
  onLoadDraft: (files: Record<string, string>) => void;
}

/** The overview rail's version ledger; it remains readable when /state is broken. */
export function VersionTimeline({
  history,
  state,
  pendingCount,
  error,
  onLoadDraft,
}: VersionTimelineProps) {
  const t = useT();
  const [selectedSha, setSelectedSha] = useState<string | null>(null);
  const [detail, setDetail] = useState<EngineHistoryFiles | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailReload, setDetailReload] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const selected = history.find((entry) => entry.sha === selectedSha) ?? null;

  useEffect(() => {
    if (!selectedSha) {
      setDetail(null);
      setDetailError(null);
      setDetailLoading(false);
      setConfirming(false);
      return;
    }
    let live = true;
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    setConfirming(false);
    getHistoryFiles(selectedSha).then(
      (next) => {
        if (!live) return;
        setDetail(next);
        setDetailLoading(false);
      },
      (reason: Error) => {
        if (!live) return;
        setDetailError(reason.message);
        setDetailLoading(false);
      },
    );
    return () => {
      live = false;
    };
  }, [detailReload, selectedSha]);

  const changedFiles = useMemo(() => {
    if (!detail || !state) return [];
    return changedHistoryFiles(detail.files, state.files);
  }, [detail, state]);

  const loadDraft = () => {
    onLoadDraft(Object.fromEntries(changedFiles));
    setSelectedSha(null);
  };

  return (
    <section className="engine-inspector__section">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 text-13 font-medium text-ink">
          {t("engineConsole.history.title")}
        </h3>
        {state && (
          <Badge tone={state.version.dirty ? "warn" : "neutral"}>
            {t(
              state.version.dirty
                ? "engineConsole.version.dirtyShort"
                : "engineConsole.version.cleanShort",
            )}
          </Badge>
        )}
      </div>

      {error && <p className="mt-2 break-all text-12 text-danger">{error}</p>}
      {!error && history.length === 0 ? (
        <EmptyState
          icon={GitCommitHorizontal}
          title={t("engineConsole.history.empty")}
          className="mt-3"
        />
      ) : (
        <ol className="engine-history-list mt-2">
          {history.map((entry) => (
            <li key={entry.sha}>
              <button
                type="button"
                className="engine-history-list__button"
                onClick={() => setSelectedSha(entry.sha)}
              >
                <strong>{entry.label}</strong>
                <span>
                  <time>{fmtTime(entry.at)}</time>
                  <code>{entry.sha.slice(0, 8)} · {t("engineConsole.history.files", { count: entry.files.length })}</code>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}

      <Drawer
        open={selected != null}
        onOpenChange={(open) => {
          if (!open) setSelectedSha(null);
        }}
        side="right"
        contentClassName="w-[min(680px,100vw)]"
        title={
          selected ? (
            <span className="flex min-w-0 items-baseline gap-2">
              <Mono className="shrink-0 text-12 text-ink-3">{selected.sha.slice(0, 8)}</Mono>
              <span className="truncate">{selected.label}</span>
            </span>
          ) : undefined
        }
        actions={
          detail ? (
            <Badge>
              {t("engineConsole.history.changedFiles", { count: changedFiles.length })}
            </Badge>
          ) : undefined
        }
      >
        {selected && (
          <div className="flex flex-col gap-5 px-4 py-4">
            <p className="text-12 text-ink-3">
              {fmtTime(selected.at)} · {t("engineConsole.history.vsCurrent")}
            </p>

            {detailLoading && <SkeletonText lines={5} />}

            {detailError && (
              <Callout tone="danger" variant="inline">
                <span className="flex flex-col items-start gap-2">
                  <Mono className="break-all text-12">{detailError}</Mono>
                  <Button
                    size="sm"
                    variant="default"
                    onClick={() => setDetailReload((value) => value + 1)}
                  >
                    {t("common.retry")}
                  </Button>
                </span>
              </Callout>
            )}

            {detail && state && changedFiles.length === 0 && (
              <p className="text-13 text-ink-3">
                {t("engineConsole.history.matchesCurrent")}
              </p>
            )}

            {detail && !state && (
              <p className="text-13 text-ink-3">
                {t("engineConsole.history.stateUnavailable")}
              </p>
            )}

            {changedFiles.map(([path, content]) => (
              <section key={path} className="flex flex-col gap-1.5">
                <Mono className="text-12 text-ink">{path}</Mono>
                <DiffBlock
                  oldBody={content}
                  newBody={state?.files[path] ?? ""}
                />
              </section>
            ))}

            {detail && state && changedFiles.length > 0 && (
              <section className="engine-history-restore">
                {!confirming ? (
                  <Button size="sm" variant="default" onClick={() => setConfirming(true)}>
                    <RotateCcw size={14} aria-hidden />
                    {t("engineConsole.history.loadDraft")}
                  </Button>
                ) : (
                  <Callout tone="warn" variant="inline">
                    <span className="flex flex-col items-start gap-3">
                      <span className="text-13">
                        {t("engineConsole.history.restoreConfirm", {
                          count: changedFiles.length,
                        })}
                      </span>
                      {pendingCount > 0 && (
                        <span className="text-12 text-ink-2">
                          {t("engineConsole.history.replaceDraft", { count: pendingCount })}
                        </span>
                      )}
                      <span className="flex flex-wrap gap-2">
                        <Button size="sm" variant="primary" onClick={loadDraft}>
                          {t("engineConsole.history.confirmLoad")}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                          {t("engineConsole.history.cancelLoad")}
                        </Button>
                      </span>
                    </span>
                  </Callout>
                )}
              </section>
            )}
          </div>
        )}
      </Drawer>
    </section>
  );
}
