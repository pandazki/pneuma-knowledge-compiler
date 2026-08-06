import { useCallback, useEffect, useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import type { EngineHistoryEntry, EngineSchema, EngineState, EngineValue } from "@/engine/types";
import { getHistory, getSchema, getState } from "@/engine/api";
import { useEngineDraft } from "@/engine/draft";
import { effectiveValues, knobRef, pathFromError, pendingChanges } from "@/lib/engineConsole";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { EngineOverview } from "./EngineOverview";
import { PipelineMap } from "./PipelineMap";
import { PromptStudio } from "./PromptStudio";
import { RawFileRepair } from "./RawFileRepair";
import { ReviewSheet } from "./ReviewSheet";
import { StageInspector } from "./StageDrawer";

export default function EngineConsoleView() {
  const t = useT();
  const draft = useEngineDraft();
  const [schema, setSchema] = useState<EngineSchema | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [state, setState] = useState<EngineState | null>(null);
  const [stateError, setStateError] = useState<string | null>(null);
  const [history, setHistory] = useState<EngineHistoryEntry[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [repairOpen, setRepairOpen] = useState(false);
  const [studioOpen, setStudioOpen] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.allSettled([getSchema(), getState(), getHistory()]).then(([nextSchema, nextState, nextHistory]) => {
      if (!live) return;
      if (nextSchema.status === "fulfilled") {
        setSchema(nextSchema.value);
        setSchemaError(null);
      } else {
        setSchemaError((nextSchema.reason as Error).message);
      }
      if (nextState.status === "fulfilled") {
        setState(nextState.value);
        setStateError(null);
      } else {
        setState(null);
        setStateError((nextState.reason as Error).message);
      }
      if (nextHistory.status === "fulfilled") {
        setHistory(nextHistory.value);
        setHistoryError(null);
      } else {
        setHistoryError((nextHistory.reason as Error).message);
      }
      setLoading(false);
    });
    return () => {
      live = false;
    };
  }, [reload]);

  const changes = useMemo(
    () => (schema && state ? pendingChanges(schema, state, draft) : []),
    [schema, state, draft],
  );
  const editedRefs = useMemo(() => new Set(changes.map((change) => change.key)), [changes]);
  const pendingOverlayKeys = useMemo(
    () => new Set(changes.filter((change) => change.kind === "overlay").map((change) => change.catalogKey)),
    [changes],
  );
  const values = useMemo<Record<string, EngineValue>>(() => {
    if (state) return effectiveValues(state, draft);
    if (!schema) return {};
    return Object.fromEntries(
      schema.stages.flatMap((stage) =>
        stage.knobs
          .filter((knob) => knob.type !== "document")
          .map((knob) => [knobRef(stage.id, knob.key), knob.default as EngineValue]),
      ),
    );
  }, [draft, schema, state]);
  const selectedStage =
    schema?.stages.find((stage) => stage.id === selectedStageId) ?? null;
  const promptStage = schema?.stages.find((stage) => stage.id === "prompts") ?? null;
  const refresh = useCallback(() => setReload((value) => value + 1), []);
  const initialLoading = loading && !schema && !state && history.length === 0;

  if (initialLoading) return <EngineConsoleLoading />;

  return (
    <div className="engine-console">
      {studioOpen && promptStage && state ? (
        <PromptStudio
          stage={promptStage}
          state={state}
          pendingCount={changes.length}
          pendingOverlayKeys={pendingOverlayKeys}
          onBack={() => setStudioOpen(false)}
          onReview={() => setReviewOpen(true)}
        />
      ) : (
      <div className="engine-console__workspace">
        <section className="engine-console__canvas">
          <div className="engine-console__toolbar">
            <div className="engine-console__identity">
              <h1>{t("engineConsole.title")}</h1>
              <p>{t("engineConsole.description")}</p>
            </div>
            <div className="engine-console__toolbar-actions">
              {changes.length > 0 && (
                <>
                  <Badge tone="warn">
                    {t("engineConsole.draft.count", { count: changes.length })}
                  </Badge>
                  <Button size="sm" variant="ghost" onClick={draft.clear}>
                    {t("engineConsole.draft.clear")}
                  </Button>
                </>
              )}
              <Button
                size="sm"
                variant="primary"
                disabled={changes.length === 0 || !schema || !state}
                onClick={() => setReviewOpen(true)}
              >
                {t("engineConsole.draft.review")}
              </Button>
            </div>
          </div>

          {schemaError && !schema ? (
            <div className="engine-console__error">
              <ErrorState
                error={schemaError}
                onRetry={refresh}
              />
            </div>
          ) : schema && schema.stages.length === 0 ? (
            <div className="engine-console__empty">
              <EmptyState
                icon={RotateCcw}
                title={t("engineConsole.map.empty")}
                description={t("engineConsole.map.emptyHint")}
              />
            </div>
          ) : schema ? (
            <PipelineMap
              schema={schema}
              values={values}
              state={state}
              editedRefs={editedRefs}
              selectedStageId={selectedStageId}
              onSelect={setSelectedStageId}
            />
          ) : null}

          <div className="engine-console__legend" aria-hidden>
            <span><i />{t("engineConsole.map.active")}</span>
            <span><i />{t("engineConsole.map.inactive")}</span>
            <span><i />{t("engineConsole.map.access")}</span>
          </div>
        </section>

        <aside className="engine-inspector" aria-label={t("engineConsole.inspector.aria")}>
          {selectedStage ? (
            <StageInspector
              key={selectedStage.id}
              stage={selectedStage}
              state={state}
              history={history}
              stateError={stateError}
              onClose={() => setSelectedStageId(null)}
              onRepair={() => setRepairOpen(true)}
              onOpenPromptStudio={() => setStudioOpen(true)}
            />
          ) : (
            <EngineOverview
              key="overview"
              schema={schema}
              state={state}
              history={history}
              stateError={stateError}
              historyError={historyError}
              pendingCount={changes.length}
              onRepair={() => setRepairOpen(true)}
              onLoadVersionDraft={(files) => {
                draft.replaceWithFiles(files);
                setReviewOpen(true);
              }}
            />
          )}
        </aside>
      </div>
      )}

      {schema && state && (
        <ReviewSheet
          schema={schema}
          state={state}
          open={reviewOpen}
          onOpenChange={setReviewOpen}
          onApplied={refresh}
        />
      )}
      <RawFileRepair
        schema={schema}
        suggestedPath={pathFromError(schema, stateError)}
        open={repairOpen}
        onOpenChange={setRepairOpen}
        onApplied={refresh}
      />
    </div>
  );
}

function EngineConsoleLoading() {
  const t = useT();
  return (
    <div className="engine-console" aria-busy aria-label={t("engineConsole.loading")}>
      <div className="engine-console__workspace">
        <div className="engine-console__loading-canvas">
          <div className="engine-console__loading-node" />
          <div className="engine-console__loading-node" />
          <div className="engine-console__loading-node" />
        </div>
        <aside className="engine-inspector">
          <div className="engine-inspector__header" />
          <div className="engine-inspector__section">
            <div className="h-3 w-3/4 animate-pulse rounded-1 bg-line" />
            <div className="mt-3 h-3 w-full animate-pulse rounded-1 bg-line" />
            <div className="mt-2 h-3 w-5/6 animate-pulse rounded-1 bg-line" />
          </div>
        </aside>
      </div>
    </div>
  );
}
