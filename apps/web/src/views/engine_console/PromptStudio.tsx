import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowLeft,
  BookOpenText,
  Check,
  ChevronRight,
  ChevronsDown,
  ChevronsUp,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";
import { getPrompts, rewritePrompt } from "@/engine/api";
import { useEngineDraft } from "@/engine/draft";
import type {
  EnginePrompts,
  EngineStage,
  EngineState,
  PromptRewriteResult,
  PromptSegment,
  PromptSurface,
} from "@/engine/types";
import { ApiError } from "@/lib/api";
import { effectiveOverlays, knobResolution, pickLocalized } from "@/lib/engineConsole";
import {
  defaultExpandedPromptGroups,
  diffPromptText,
  groupPromptSurfaces,
  isFragmentFamily,
  missingPlaceholders,
  promptGroupOverrideCount,
  promptPreview,
  segmentInCurrentRendering,
  segmentOverride,
  surfaceOverrideCount,
  tokenizePromptText,
  type PromptPreviewMode,
} from "@/lib/promptStudio";
import { useLocale, useT, useTOr, type TFunction } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { IconButton } from "@/ui/IconButton";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Skeleton, SkeletonText } from "@/ui/Skeleton";
import { TextArea } from "@/ui/TextArea";
import { EffectBadge, OriginBadge } from "./badges";

export interface PromptStudioProps {
  stage: EngineStage;
  state: EngineState;
  pendingCount: number;
  pendingOverlayKeys: ReadonlySet<string>;
  onBack: () => void;
  onReview: () => void;
}

function promptSegmentLabel(
  segment: PromptSegment,
  locale: "zh" | "en",
  t: TFunction,
): string {
  if (segment.key === "recall.rerank.llm.system") {
    return t("engineConsole.studio.known.recallRerankLlmSystem");
  }
  if (segment.key === "evolve.tool.delete_claim_result") {
    return t("engineConsole.studio.known.evolveDeleteClaimLabel");
  }
  return pickLocalized(segment.label, locale);
}

function promptSegmentContext(
  segment: PromptSegment,
  locale: "zh" | "en",
  t: TFunction,
): string {
  if (segment.key === "evolve.tool.delete_claim_result") {
    return t("engineConsole.studio.known.evolveDeleteClaimContext");
  }
  return segment.context ? pickLocalized(segment.context, locale) : "";
}

export function PromptStudio({
  stage,
  state,
  pendingCount,
  pendingOverlayKeys,
  onBack,
  onReview,
}: PromptStudioProps) {
  const t = useT();
  const tOr = useTOr();
  const locale = useLocale();
  const draft = useEngineDraft();
  const overlayKnob = stage.knobs.find((knob) => knob.type === "overlay_map") ?? null;
  const overlays = effectiveOverlays(state, draft, stage.file);
  const promptLanguageValue = state.values["prompts.language"];
  const promptLanguage =
    typeof promptLanguageValue === "string" && promptLanguageValue.trim().length > 0
      ? promptLanguageValue.trim()
      : null;
  const promptLanguageName = promptLanguage
    ? tOr(
        `engineConsole.studio.promptLanguage.${promptLanguage}`,
        promptLanguage,
      )
    : t("engineConsole.studio.promptLanguage.unknown");
  const [prompts, setPrompts] = useState<EnginePrompts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [selectedSurfaceId, setSelectedSurfaceId] = useState<string | null>(null);
  const [selectedSegmentKey, setSelectedSegmentKey] = useState<string | null>(null);
  const [previewMode, setPreviewMode] = useState<PromptPreviewMode>("effective");
  const [expandedGroups, setExpandedGroups] = useState<Set<string> | null>(null);
  const selectedSurfaceRowRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    getPrompts().then(
      (result) => {
        if (!live) return;
        setPrompts(result);
        setSelectedSurfaceId((current) => current ?? result.surfaces[0]?.id ?? null);
      },
      (reason: Error) => {
        if (!live) return;
        setError(reason.message);
      },
    );
    return () => {
      live = false;
    };
  }, [reload]);

  const selectedSurface =
    prompts?.surfaces.find((surface) => surface.id === selectedSurfaceId) ?? null;
  const selectedSegment =
    selectedSurface?.segments.find((segment) => segment.key === selectedSegmentKey) ??
    selectedSurface?.segments[0] ??
    null;

  useEffect(() => {
    if (!selectedSurface) return;
    if (!selectedSurface.segments.some((segment) => segment.key === selectedSegmentKey)) {
      setSelectedSegmentKey(selectedSurface.segments[0]?.key ?? null);
    }
  }, [selectedSegmentKey, selectedSurface]);

  const groups = useMemo(
    () => groupPromptSurfaces(prompts?.surfaces ?? []),
    [prompts?.surfaces],
  );
  const surfaceById = useMemo(
    () => new Map((prompts?.surfaces ?? []).map((surface) => [surface.id, surface])),
    [prompts?.surfaces],
  );
  const defaultExpandedGroups = useMemo(
    () => new Set(defaultExpandedPromptGroups(groups, overlays, selectedSurfaceId)),
    [groups, overlays, selectedSurfaceId],
  );
  const visibleGroups = expandedGroups ?? defaultExpandedGroups;
  const allGroupsExpanded = groups.length > 0 && groups.every((group) => visibleGroups.has(group.group));
  const allGroupsCollapsed = groups.every((group) => !visibleGroups.has(group.group));
  const fragments = selectedSurface !== null && isFragmentFamily(selectedSurface);
  const preview = useMemo(
    () => selectedSurface && !isFragmentFamily(selectedSurface)
      ? promptPreview(selectedSurface, draft.overlays, previewMode)
      : null,
    [draft.overlays, previewMode, selectedSurface],
  );
  const variantSegments = useMemo(
    () => selectedSurface?.segments.filter(
      (segment) => !segmentInCurrentRendering(selectedSurface, segment),
    ) ?? [],
    [selectedSurface],
  );

  const selectSurface = (surface: PromptSurface, preferredKey?: string) => {
    setExpandedGroups((current) => {
      const next = new Set(current ?? defaultExpandedGroups);
      next.add(surface.group);
      return next;
    });
    setSelectedSurfaceId(surface.id);
    setSelectedSegmentKey(
      preferredKey && surface.segments.some((segment) => segment.key === preferredKey)
        ? preferredKey
        : surface.segments[0]?.key ?? null,
    );
  };

  useEffect(() => {
    const row = selectedSurfaceRowRef.current;
    if (!row) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    row.scrollIntoView({ block: "nearest", behavior: reducedMotion ? "auto" : "smooth" });
  }, [selectedSurfaceId]);

  const toggleGroup = (group: string) => {
    setExpandedGroups((current) => {
      const next = new Set(current ?? defaultExpandedGroups);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  return (
    <section className="prompt-studio" aria-label={t("engineConsole.studio.title")}>
      <header className="prompt-studio__header">
        <div className="prompt-studio__identity">
          <Button size="sm" variant="ghost" onClick={onBack}>
            <ArrowLeft size={14} aria-hidden />
            {t("engineConsole.studio.back")}
          </Button>
          <div>
            <h1>{t("engineConsole.studio.title")}</h1>
            <p>{t("engineConsole.studio.description")}</p>
          </div>
        </div>
        <div className="prompt-studio__actions">
          <Badge tone="neutral" className="prompt-studio__language">
            {t("engineConsole.studio.promptLanguage", { language: promptLanguageName })}
          </Badge>
          {overlayKnob && (
            <div className="prompt-studio__resolution-badges flex items-center gap-1">
              <OriginBadge origin={knobResolution(state, stage.id, overlayKnob)} />
              <EffectBadge apply={overlayKnob.apply} />
            </div>
          )}
          <Badge
            tone={pendingCount > 0 ? "warn" : "neutral"}
            className="prompt-studio__pending-count"
          >
            {t("engineConsole.draft.count", { count: pendingCount })}
          </Badge>
          <Button
            size="sm"
            variant="primary"
            disabled={pendingCount === 0}
            onClick={onReview}
          >
            {t("engineConsole.draft.review")}
          </Button>
        </div>
      </header>

      {error && !prompts ? (
        <div className="prompt-studio__state">
          <ErrorState error={error} onRetry={() => setReload((value) => value + 1)} />
        </div>
      ) : !prompts ? (
        <PromptStudioLoading />
      ) : prompts.surfaces.length === 0 ? (
        <div className="prompt-studio__state">
          <EmptyState
            icon={BookOpenText}
            title={t("engineConsole.studio.empty")}
            description={t("engineConsole.studio.emptyHint")}
          />
        </div>
      ) : (
        <div className="prompt-studio__grid">
          <nav className="prompt-studio__surfaces" aria-label={t("engineConsole.studio.surfaces") }>
            <div className="prompt-studio__pane-heading prompt-studio__surfaces-heading">
              <div>
                <div className="prompt-studio__surface-heading-row">
                  <h2>{t("engineConsole.studio.surfaces")}</h2>
                  <div className="prompt-studio__tree-controls">
                    <Badge tone="neutral">{prompts.surfaces.length}</Badge>
                    <IconButton
                      size="sm"
                      aria-label={t("engineConsole.studio.expandAll")}
                      title={t("engineConsole.studio.expandAll")}
                      disabled={allGroupsExpanded}
                      onClick={() => setExpandedGroups(new Set(groups.map((group) => group.group)))}
                    >
                      <ChevronsDown size={14} aria-hidden />
                    </IconButton>
                    <IconButton
                      size="sm"
                      aria-label={t("engineConsole.studio.collapseAll")}
                      title={t("engineConsole.studio.collapseAll")}
                      disabled={allGroupsCollapsed}
                      onClick={() => setExpandedGroups(new Set())}
                    >
                      <ChevronsUp size={14} aria-hidden />
                    </IconButton>
                  </div>
                </div>
                <p>{t("engineConsole.studio.surfacesHint")}</p>
              </div>
            </div>
            <ScrollRegion className="min-h-0 flex-1" as="div">
              <div className="prompt-studio__surface-groups">
                {groups.map((group) => {
                  const expanded = visibleGroups.has(group.group);
                  const overrideCount = promptGroupOverrideCount(group, overlays);
                  const branchId = `prompt-studio-group-${group.group}`;
                  return (
                    <section
                      key={group.group}
                      className="prompt-studio__surface-group"
                      data-expanded={expanded || undefined}
                    >
                      <button
                        type="button"
                        className="prompt-studio__group-toggle"
                        aria-expanded={expanded}
                        aria-controls={branchId}
                        onClick={() => toggleGroup(group.group)}
                      >
                        <ChevronRight
                          className="prompt-studio__group-chevron"
                          size={14}
                          aria-hidden
                        />
                        <strong>
                          {tOr(
                            `engineConsole.studio.group.${group.group}`,
                            group.group,
                          )}
                        </strong>
                        <span className="prompt-studio__group-count">
                          {t("engineConsole.studio.surfaceCount", {
                            count: group.surfaces.length,
                          })}
                        </span>
                        <Badge
                          tone={overrideCount > 0 ? "accent" : "neutral"}
                          className="prompt-studio__group-override"
                        >
                          {t("engineConsole.studio.groupOverrideCount", {
                            count: overrideCount,
                          })}
                        </Badge>
                      </button>
                      <div
                        id={branchId}
                        className="prompt-studio__surface-branch"
                        aria-hidden={!expanded}
                      >
                        <div>
                          {group.surfaces.map((surface) => {
                            const count = surfaceOverrideCount(surface, overlays);
                            const selected = surface.id === selectedSurface?.id;
                            return (
                              <button
                                key={surface.id}
                                ref={selected ? selectedSurfaceRowRef : undefined}
                                type="button"
                                className="prompt-studio__surface-row"
                                aria-current={selected ? "true" : undefined}
                                tabIndex={expanded ? 0 : -1}
                                title={pickLocalized(surface.summary, locale)}
                                onClick={() => selectSurface(surface)}
                              >
                                <strong>{pickLocalized(surface.title, locale)}</strong>
                                <Badge tone={count > 0 ? "accent" : "neutral"}>
                                  {t("engineConsole.studio.overrideBadge", { count })}
                                </Badge>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </section>
                  );
                })}
              </div>
            </ScrollRegion>
          </nav>

          <section
            className="prompt-studio__preview"
            aria-label={t("engineConsole.studio.preview")}
          >
            {selectedSurface && (
              <>
                <div className="prompt-studio__preview-heading">
                  <div className="prompt-studio__preview-heading-copy">
                    <div className="prompt-studio__preview-title">
                      <h2>{pickLocalized(selectedSurface.title, locale)}</h2>
                      <Badge tone="neutral" className="prompt-studio__kind-badge">
                        {t(
                          fragments
                            ? "engineConsole.studio.kind.fragments"
                            : "engineConsole.studio.kind.assembled",
                        )}
                      </Badge>
                    </div>
                    <p>{pickLocalized(selectedSurface.summary, locale)}</p>
                  </div>
                  {/* No assembly, no assembly toggle: a fragment family has no framework /
                      effective rendering to switch between — each clause shows its own. */}
                  {!fragments && (
                    <SegmentedControl
                      value={previewMode}
                      onChange={(value) => setPreviewMode(value as PromptPreviewMode)}
                      aria-label={t("engineConsole.studio.previewMode")}
                      size="sm"
                      options={[
                        {
                          value: "framework",
                          label: t("engineConsole.studio.frameworkMode"),
                        },
                        {
                          value: "effective",
                          label: t("engineConsole.studio.effectiveMode"),
                        },
                      ]}
                    />
                  )}
                </div>
                {fragments ? (
                  <FragmentFamily
                    surface={selectedSurface}
                    overlays={overlays}
                    pendingOverlayKeys={pendingOverlayKeys}
                    selectedKey={selectedSegment?.key ?? null}
                    onSelect={setSelectedSegmentKey}
                  />
                ) : (
                <ScrollRegion className="min-h-0 flex-1" as="div">
                  <div className="prompt-studio__assembled">
                    <div
                      className="prompt-studio__model-note"
                      data-template={selectedSurface.note ? true : undefined}
                    >
                      <span aria-hidden>{selectedSurface.note ? "◇" : "→"}</span>
                      {selectedSurface.note ? (
                        <div className="prompt-studio__template-note">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {pickLocalized(selectedSurface.note, locale)}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <p>{t("engineConsole.studio.modelNote")}</p>
                      )}
                    </div>
                    {preview && (
                      <div className="prompt-studio__assembled-text">
                        {selectedSegment && preview.parts.some(
                          (part) => part.segment?.key === selectedSegment.key,
                        ) && (
                          <code
                            className="prompt-studio__selected-source-key"
                            title={selectedSegment.key}
                          >
                            {selectedSegment.key}
                          </code>
                        )}
                        <div className="prompt-studio__assembled-content">
                          {preview.parts.map((part) => {
                            if (part.kind === "text" || !part.segment) {
                              return <span key={`${part.start}:${part.end}`}>{part.value}</span>;
                            }
                            const segment = part.segment;
                            const overridden = segmentOverride(segment, overlays) !== null;
                            const pending = pendingOverlayKeys.has(segment.key);
                            return (
                              <button
                                key={`${segment.key}:${part.start}`}
                                type="button"
                                className="prompt-studio__segment"
                                data-selected={segment.key === selectedSegment?.key || undefined}
                                data-overridden={overridden || undefined}
                                data-pending={pending || undefined}
                                data-start={part.start}
                                data-end={part.end}
                                aria-label={t("engineConsole.studio.editSegment", {
                                  label: promptSegmentLabel(segment, locale, t),
                                })}
                                onClick={() => setSelectedSegmentKey(segment.key)}
                              >
                                <span className="prompt-studio__source-key">{segment.key}</span>
                                <PromptText text={part.value} placeholders={segment.placeholders} />
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}
                    {variantSegments.length > 0 && (
                      <section className="prompt-studio__variants">
                        <h3>{t("engineConsole.studio.variantHeading")}</h3>
                        <div>
                          {variantSegments.map((segment) => {
                            const overridden = segmentOverride(segment, overlays) !== null;
                            const pending = pendingOverlayKeys.has(segment.key);
                            return (
                              <button
                                key={segment.key}
                                type="button"
                                className="prompt-studio__variant-segment"
                                data-selected={segment.key === selectedSegment?.key || undefined}
                                data-overridden={overridden || undefined}
                                data-pending={pending || undefined}
                                onClick={() => setSelectedSegmentKey(segment.key)}
                              >
                                <span>
                                  <strong>{promptSegmentLabel(segment, locale, t)}</strong>
                                  <code>{segment.key}</code>
                                </span>
                                <small>{t("engineConsole.studio.variantNote")}</small>
                              </button>
                            );
                          })}
                        </div>
                      </section>
                    )}
                  </div>
                </ScrollRegion>
                )}
              </>
            )}
          </section>

          <aside className="prompt-studio__editor" aria-label={t("engineConsole.studio.editor") }>
            {selectedSurface && selectedSegment && (
              <SegmentEditor
                key={`${selectedSurface.id}:${selectedSegment.key}`}
                surface={selectedSurface}
                segment={selectedSegment}
                surfaces={surfaceById}
                overlays={overlays}
                onSelectShared={(surfaceId) => {
                  const target = surfaceById.get(surfaceId);
                  if (target) selectSurface(target, selectedSegment.key);
                }}
              />
            )}
          </aside>
        </div>
      )}
    </section>
  );
}

/**
 * A fragment family, itemized. No assembled preview and no framework/effective toggle,
 * because neither exists: the clauses are conditional alternatives and separate emissions,
 * and the concatenation the studio used to show ("the ownera conversationThis is…") was a
 * sentence no model ever received. Each clause instead states when it is used, shows the
 * framework wording in the active language pack, and shows the override in force under it.
 */
function FragmentFamily({
  surface,
  overlays,
  pendingOverlayKeys,
  selectedKey,
  onSelect,
}: {
  surface: PromptSurface;
  overlays: Record<string, string>;
  pendingOverlayKeys: ReadonlySet<string>;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const t = useT();
  const locale = useLocale();
  return (
    <ScrollRegion className="min-h-0 flex-1" as="div">
      <div className="prompt-studio__assembled">
        <div className="prompt-studio__model-note" data-fragments>
          <span aria-hidden>⋮</span>
          <p>{t("engineConsole.studio.fragmentNote")}</p>
        </div>
        <div className="prompt-studio__fragments">
          <div className="prompt-studio__fragments-heading">
            <h3>{t("engineConsole.studio.fragmentsHeading")}</h3>
            <Badge tone="neutral">
              {t("engineConsole.studio.clauseCount", { count: surface.segments.length })}
            </Badge>
          </div>
          {surface.segments.map((segment) => {
            const override = segmentOverride(segment, overlays);
            const pending = pendingOverlayKeys.has(segment.key);
            return (
              <button
                key={segment.key}
                type="button"
                className="prompt-studio__fragment"
                data-selected={segment.key === selectedKey || undefined}
                data-overridden={override !== null || undefined}
                data-pending={pending || undefined}
                aria-label={t("engineConsole.studio.editSegment", {
                  label: promptSegmentLabel(segment, locale, t),
                })}
                onClick={() => onSelect(segment.key)}
              >
                <span className="prompt-studio__fragment-head">
                  <strong>{promptSegmentLabel(segment, locale, t)}</strong>
                  <code>{segment.key}</code>
                  {override !== null && (
                    <Badge tone="accent">{t("engineConsole.overlays.overridden")}</Badge>
                  )}
                </span>
                {segment.context && (
                  <span className="prompt-studio__fragment-context">
                    <em>{t("engineConsole.studio.whenUsed")}</em>
                    {promptSegmentContext(segment, locale, t)}
                  </span>
                )}
                <span className="prompt-studio__fragment-clause">
                  <em>{t("engineConsole.studio.frameworkOriginal")}</em>
                  <PromptText
                    text={segment.framework_text}
                    placeholders={segment.placeholders}
                  />
                </span>
                {override !== null && (
                  <span
                    className="prompt-studio__fragment-clause"
                    data-override
                  >
                    <em>{t("engineConsole.studio.overrideInForce")}</em>
                    <PromptText text={override} placeholders={segment.placeholders} />
                  </span>
                )}
                <span className="prompt-studio__fragment-edit">
                  {t("engineConsole.studio.editClause")}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </ScrollRegion>
  );
}

function SegmentEditor({
  surface,
  segment,
  surfaces,
  overlays,
  onSelectShared,
}: {
  surface: PromptSurface;
  segment: PromptSegment;
  surfaces: Map<string, PromptSurface>;
  overlays: Record<string, string>;
  onSelectShared: (surfaceId: string) => void;
}) {
  const t = useT();
  const locale = useLocale();
  const draft = useEngineDraft();
  const currentOverride = segmentOverride(segment, overlays);
  const [editing, setEditing] = useState(false);
  const [editorValue, setEditorValue] = useState(currentOverride ?? segment.framework_text);
  const [intent, setIntent] = useState("");
  const [rewrite, setRewrite] = useState<PromptRewriteResult | null>(null);
  const [rewriteError, setRewriteError] = useState<ApiError | Error | null>(null);
  const [rewriting, setRewriting] = useState(false);
  const inCurrentRendering = segmentInCurrentRendering(surface, segment);
  const missing = missingPlaceholders(editorValue, segment.placeholders);
  const rewriteMissing = rewrite
    ? missingPlaceholders(rewrite.draft, segment.placeholders)
    : [];
  const editorError =
    editorValue.trim() === ""
      ? t("engineConsole.studio.overrideEmpty")
      : missing.length > 0
        ? t("engineConsole.studio.missingSlots", { slots: missing.map(slotLabel).join(", ") })
        : undefined;

  const startEditing = (value = currentOverride ?? segment.framework_text) => {
    setEditorValue(value);
    setEditing(true);
  };
  const discardEditing = () => {
    setEditorValue(currentOverride ?? segment.framework_text);
    setEditing(false);
  };
  const save = () => {
    if (editorError) return;
    draft.setOverlay(segment.key, editorValue);
    setEditing(false);
  };
  const runRewrite = async () => {
    if (intent.trim() === "") return;
    setRewriting(true);
    setRewriteError(null);
    try {
      setRewrite(await rewritePrompt({ key: segment.key, intent: intent.trim(), locale }));
    } catch (reason) {
      setRewriteError(reason as Error);
    } finally {
      setRewriting(false);
    }
  };
  const acceptRewrite = () => {
    if (!rewrite || rewrite.draft.trim() === "" || rewriteMissing.length > 0) return;
    draft.setOverlay(segment.key, rewrite.draft);
    setEditorValue(rewrite.draft);
    setEditing(false);
    setRewrite(null);
    setRewriteError(null);
  };
  const keyless = rewriteError instanceof ApiError && rewriteError.status === 503;

  return (
    <div className="prompt-studio__editor-inner">
      <div className="prompt-studio__pane-heading prompt-studio__editor-heading">
        <div>
          <h2>{promptSegmentLabel(segment, locale, t)}</h2>
          <code title={segment.key}>{segment.key}</code>
        </div>
        {currentOverride !== null && (
          <Badge tone="accent">{t("engineConsole.overlays.overridden")}</Badge>
        )}
      </div>
      <ScrollRegion className="min-h-0 flex-1" as="div">
        <div className="prompt-studio__editor-body">
          <section className="prompt-studio__editor-section">
            <h3>{t("engineConsole.studio.aboutSegment")}</h3>
            {/* The registry's own account of when the model receives this clause, when it
                has one — a fragment or a variant is not explained by where it sits. */}
            {segment.context ? (
              <p>{promptSegmentContext(segment, locale, t)}</p>
            ) : (
              <p>{t("engineConsole.studio.segmentExplanation", {
                label: promptSegmentLabel(segment, locale, t),
                surface: pickLocalized(surface.title, locale),
              })}</p>
            )}
            {!inCurrentRendering && (
              <p className="prompt-studio__variant-note">
                {t("engineConsole.studio.variantNote")}
              </p>
            )}
            <div className="prompt-studio__shared">
              <span>{t("engineConsole.studio.sharedWith")}</span>
              {segment.shared_with.length === 0 ? (
                <small>{t("engineConsole.studio.onlyHere")}</small>
              ) : (
                <div>
                  {segment.shared_with.map((surfaceId) => {
                    const shared = surfaces.get(surfaceId);
                    return shared ? (
                      <button key={surfaceId} type="button" onClick={() => onSelectShared(surfaceId)}>
                        {pickLocalized(shared.title, locale)}
                      </button>
                    ) : (
                      <code key={surfaceId}>{surfaceId}</code>
                    );
                  })}
                </div>
              )}
            </div>
          </section>

          <section className="prompt-studio__editor-section">
            <div className="prompt-studio__section-heading">
              <h3>{t("engineConsole.studio.frameworkOriginal")}</h3>
              <Badge tone="neutral">{t("engineConsole.studio.readOnly")}</Badge>
            </div>
            <div className="prompt-studio__readonly" aria-label={t("engineConsole.studio.frameworkOriginal") }>
              <PromptText text={segment.framework_text} placeholders={segment.placeholders} />
            </div>
          </section>

          <section className="prompt-studio__editor-section">
            <div className="prompt-studio__section-heading">
              <h3>{t("engineConsole.studio.override")}</h3>
              {!editing && (
                <Button size="sm" variant="ghost" onClick={() => startEditing()}>
                  {t("engineConsole.editor.modify")}
                </Button>
              )}
            </div>
            {editing ? (
              <>
                <TextArea
                  value={editorValue}
                  onChange={(event) => setEditorValue(event.target.value)}
                  aria-label={t("engineConsole.studio.override")}
                  error={editorError}
                  rows={9}
                  className="font-mono text-12 leading-5"
                />
                <div className="prompt-studio__editor-actions">
                  <Button size="sm" variant="primary" disabled={Boolean(editorError)} onClick={save}>
                    <Check size={13} aria-hidden />
                    {t("engineConsole.editor.saveDraft")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={discardEditing}>
                    <X size={13} aria-hidden />
                    {t("engineConsole.editor.discard")}
                  </Button>
                </div>
              </>
            ) : currentOverride === null ? (
              <div className="prompt-studio__inherited">
                <p>{t("engineConsole.studio.inheritedHint")}</p>
              </div>
            ) : (
              <>
                <div className="prompt-studio__override-preview">
                  <PromptText text={currentOverride} placeholders={segment.placeholders} />
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="mt-2"
                  onClick={() => draft.removeOverlay(segment.key)}
                >
                  <RotateCcw size={13} aria-hidden />
                  {t("engineConsole.studio.restoreFramework")}
                </Button>
              </>
            )}
            <PlaceholderContract placeholders={segment.placeholders} />
          </section>

          <section className="prompt-studio__editor-section prompt-studio__rewrite">
            <div className="prompt-studio__rewrite-title">
              <span aria-hidden><Sparkles size={15} /></span>
              <div>
                <h3>{t("engineConsole.studio.aiRewrite")}</h3>
                <p>{t("engineConsole.studio.aiRewriteHint")}</p>
              </div>
            </div>
            <TextArea
              value={intent}
              onChange={(event) => setIntent(event.target.value)}
              label={t("engineConsole.studio.intent")}
              placeholder={t("engineConsole.studio.intentPlaceholder")}
              rows={3}
            />
            <Button
              size="sm"
              variant="default"
              loading={rewriting}
              disabled={intent.trim() === ""}
              onClick={() => void runRewrite()}
            >
              <Sparkles size={13} aria-hidden />
              {rewrite
                ? t("engineConsole.studio.rewriteAgain")
                : t("engineConsole.studio.generateRewrite")}
            </Button>

            {rewriteError && (
              <div className="prompt-studio__rewrite-error" data-keyless={keyless || undefined} role="alert">
                <strong>
                  {keyless
                    ? t("engineConsole.studio.keylessTitle")
                    : t("engineConsole.studio.rewriteFailed")}
                </strong>
                <p>
                  {keyless
                    ? t("engineConsole.studio.keylessHint")
                    : rewriteError.message}
                </p>
                {keyless && <code>{rewriteError.message}</code>}
              </div>
            )}

            {rewrite && (
              <div className="prompt-studio__rewrite-draft">
                <div className="prompt-studio__section-heading">
                  <h3>{t("engineConsole.studio.rewriteDraft")}</h3>
                  <Badge tone="neutral">{t("engineConsole.studio.notSaved")}</Badge>
                </div>
                <p className="prompt-studio__rewrite-notes">{rewrite.notes}</p>
                <div className="prompt-studio__diff" aria-label={t("engineConsole.studio.diff") }>
                  {diffPromptText(segment.framework_text, rewrite.draft).map((part, index) => (
                    <span key={index} data-kind={part.kind}>{part.value}</span>
                  ))}
                </div>
                {rewriteMissing.length > 0 && (
                  <p className="prompt-studio__inline-error" role="alert">
                    {t("engineConsole.studio.missingSlots", {
                      slots: rewriteMissing.map(slotLabel).join(", "),
                    })}
                  </p>
                )}
                <div className="prompt-studio__editor-actions">
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={rewrite.draft.trim() === "" || rewriteMissing.length > 0}
                    onClick={acceptRewrite}
                  >
                    <Check size={13} aria-hidden />
                    {t("engineConsole.studio.acceptDraft")}
                  </Button>
                  <Button size="sm" variant="default" loading={rewriting} onClick={() => void runRewrite()}>
                    <Sparkles size={13} aria-hidden />
                    {t("engineConsole.studio.rewriteAgain")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setRewrite(null);
                      setRewriteError(null);
                    }}
                  >
                    <X size={13} aria-hidden />
                    {t("engineConsole.studio.abandonRewrite")}
                  </Button>
                </div>
              </div>
            )}
          </section>
        </div>
      </ScrollRegion>
    </div>
  );
}

function PlaceholderContract({ placeholders }: { placeholders: string[] }) {
  const t = useT();
  return (
    <div className="prompt-studio__slots">
      <span>{t("engineConsole.studio.requiredSlots")}</span>
      {placeholders.length === 0 ? (
        <small>{t("engineConsole.studio.noSlots")}</small>
      ) : (
        <div>{placeholders.map((name) => <code key={name}>{slotLabel(name)}</code>)}</div>
      )}
    </div>
  );
}

function PromptText({ text, placeholders }: { text: string; placeholders: string[] }) {
  return (
    <span className="prompt-studio__prompt-text">
      {tokenizePromptText(text, placeholders).map((token, index) =>
        token.kind === "placeholder" ? (
          <code key={`${index}:${token.value}`} className="prompt-studio__slot-chip">
            {token.value}
          </code>
        ) : (
          <span key={`${index}:${token.value}`}>{token.value}</span>
        ),
      )}
    </span>
  );
}

function slotLabel(name: string): string {
  return `{${name}}`;
}

function PromptStudioLoading() {
  const t = useT();
  return (
    <div className="prompt-studio__loading" aria-busy aria-label={t("engineConsole.studio.loading") }>
      <div><Skeleton className="h-4 w-20" /><SkeletonText lines={6} className="mt-5" /></div>
      <div><Skeleton className="h-5 w-48" /><SkeletonText lines={10} className="mt-6" /></div>
      <div><Skeleton className="h-4 w-32" /><SkeletonText lines={8} className="mt-5" /></div>
    </div>
  );
}
