import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getHistoryFiles } from "@/engine/api";
import type { EngineHistoryEntry, EngineStage, EngineState } from "@/engine/types";
import { useEngineDraft } from "@/engine/draft";
import { pickLocalized } from "@/lib/engineConsole";
import { fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Tabs } from "@/ui/Tabs";
import { TextArea } from "@/ui/TextArea";
import { DiffBlock } from "./DiffBlock";
import { EffectBadge } from "./badges";
import { SkeletonText } from "@/ui/Skeleton";

export interface DocumentEditorProps {
  stage: EngineStage;
  state: EngineState;
  history: EngineHistoryEntry[];
}

/** Contract and profile stay whole documents inside the persistent inspector. */
export function DocumentEditor({ stage, state, history }: DocumentEditorProps) {
  const t = useT();
  const locale = useLocale();
  const draft = useEngineDraft();
  const [tab, setTab] = useState("preview");
  const [editing, setEditing] = useState(false);
  const [buffer, setBuffer] = useState("");
  const [selectedSha, setSelectedSha] = useState<string | null>(null);
  const knob = stage.knobs.find((candidate) => candidate.type === "document")!;
  const path = stage.file;
  const unavailable = state.skipped?.[path] ?? null;
  const applied = state.files[path] ?? "";
  const content = draft.files[path] ?? applied;
  const dirty = draft.files[path] != null && draft.files[path] !== applied;
  const versions = useMemo(
    () => history.filter((entry) => entry.files.includes(path)),
    [history, path],
  );

  useEffect(() => {
    setTab("preview");
    setEditing(false);
    setBuffer("");
    setSelectedSha(null);
  }, [stage.id]);

  if (unavailable) {
    return (
      <section className="engine-inspector__section">
        <Callout tone="danger" variant="inline">
          <span className="flex flex-col gap-1">
            <span className="text-13">{t("engineConsole.editor.unavailable")}</span>
            <code className="break-all text-12">{unavailable}</code>
          </span>
        </Callout>
      </section>
    );
  }

  return (
    <div className="engine-document">
      <section className="engine-inspector__section">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <EffectBadge apply={knob.apply} />
            {dirty && <Badge tone="accent">{t("engineConsole.editor.dirty")}</Badge>}
          </div>
          {!editing && (
            <Button
              size="sm"
              variant="default"
              onClick={() => {
                setBuffer(content);
                setEditing(true);
              }}
            >
              {t("engineConsole.editor.modify")}
            </Button>
          )}
        </div>
      </section>
      {editing ? (
        <section className="engine-document__editor">
          <TextArea
            value={buffer}
            onChange={(event) => setBuffer(event.target.value)}
            aria-label={path}
            spellCheck={false}
            className="font-mono text-13 leading-6"
          />
          <div className="engine-document__editor-actions">
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                draft.setFile(path, buffer);
                setEditing(false);
                setTab("preview");
              }}
            >
              {t("engineConsole.editor.saveDraft")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setBuffer(content);
                setEditing(false);
                setTab("preview");
              }}
            >
              {t("engineConsole.editor.discard")}
            </Button>
          </div>
        </section>
      ) : (
        <div className="engine-document__tabs">
          <Tabs
            value={tab}
            onChange={setTab}
            aria-label={pickLocalized(stage.title, locale)}
            tabs={[
              {
                value: "preview",
                label: t("engineConsole.editor.preview"),
                panel: (
                  <div className="engine-document__panel">
                    {path.endsWith(".md") ? (
                      <div className="prose engine-document__preview max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                      </div>
                    ) : (
                      <pre className="engine-document__source-preview"><code>{content}</code></pre>
                    )}
                  </div>
                ),
              },
              {
                value: "history",
                label: t("engineConsole.editor.history"),
                panel: (
                  <div className="engine-document__panel">
                    {versions.length === 0 ? (
                      <p className="text-13 text-ink-3">
                        {t("engineConsole.editor.historyEmpty")}
                      </p>
                    ) : (
                      <ol className="engine-history-list">
                        {versions.map((entry) => (
                          <li key={entry.sha}>
                            <button
                              type="button"
                              className="engine-history-list__button"
                              onClick={() =>
                                setSelectedSha(selectedSha === entry.sha ? null : entry.sha)
                              }
                            >
                              <strong>{entry.label}</strong>
                              <span>
                                <code>{entry.sha.slice(0, 8)}</code>
                                <time>{fmtTime(entry.at)}</time>
                              </span>
                            </button>
                            {selectedSha === entry.sha && (
                              <div className="pb-3">
                                <HistoricalDocumentDiff
                                  sha={entry.sha}
                                  path={path}
                                  current={applied}
                                />
                              </div>
                            )}
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                ),
              },
            ]}
          />
        </div>
      )}
    </div>
  );
}

function HistoricalDocumentDiff({
  sha,
  path,
  current,
}: {
  sha: string;
  path: string;
  current: string;
}) {
  const t = useT();
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    setContent(null);
    setError(null);
    getHistoryFiles(sha).then(
      (result) => {
        if (!live) return;
        if (result.files[path] == null) {
          setError(t("engineConsole.history.fileMissing", { path }));
        } else {
          setContent(result.files[path]);
        }
      },
      (reason: Error) => {
        if (live) setError(reason.message);
      },
    );
    return () => {
      live = false;
    };
  }, [path, reload, sha, t]);

  if (error) {
    return (
      <Callout tone="danger" variant="inline">
        <span className="flex flex-col items-start gap-2">
          <code className="break-all text-12">{error}</code>
          <Button size="sm" variant="default" onClick={() => setReload((value) => value + 1)}>
            {t("common.retry")}
          </Button>
        </span>
      </Callout>
    );
  }
  if (content == null) return <SkeletonText lines={4} />;
  return <DiffBlock oldBody={content} newBody={current} />;
}
