import { Suspense, lazy, useEffect, type ComponentType } from "react";
import { useApp } from "./lib/store";
import { useT } from "./lib/useT";
import type { ViewName } from "./lib/types";
import { AppShell } from "./components/AppShell";
import { SourceSpanSheet } from "./components/SourceSpanSheet";
import { ErrorState } from "./ui/ErrorState";
import { Skeleton, SkeletonText } from "./ui/Skeleton";
import OverviewView from "./views/overview/OverviewView";

// View-level code splitting: the main bundle keeps only the front matter; every other view
// loads on first visit, with a Suspense skeleton covering the gap.
const ProfileView = lazy(() => import("./views/profile/ProfileView"));
const SourcesView = lazy(() => import("./views/sources/SourcesView"));
const IngestView = lazy(() => import("./views/ingest/IngestView"));
const ProcessView = lazy(() => import("./views/process/ProcessView"));
const RecallView = lazy(() => import("./views/recall/RecallView"));
const AskView = lazy(() => import("./views/ask/AskView"));
const LiveContextView = lazy(() => import("./views/live_context/LiveContextView"));
const ConsultationsView = lazy(() => import("./views/consultations/ConsultationsView"));
const LibraryView = lazy(() => import("./views/library/LibraryView"));
const GraphView = lazy(() => import("./views/graph/GraphView"));
const HistoryView = lazy(() => import("./views/history/HistoryView"));
const EvolveView = lazy(() => import("./views/evolve/EvolveView"));
const EngineConsoleView = lazy(() => import("./views/engine_console/EngineConsoleView"));
const ComponentsGallery = lazy(() => import("./views/components/ComponentsGallery"));

const VIEWS: Record<ViewName, ComponentType> = {
  overview: OverviewView,
  profile: ProfileView,
  sources: SourcesView,
  ingest: IngestView,
  process: ProcessView,
  recall: RecallView,
  ask: AskView,
  live_context: LiveContextView,
  consultations: ConsultationsView,
  library: LibraryView,
  graph: GraphView,
  history: HistoryView,
  evolve: EvolveView,
  engine_console: EngineConsoleView,
  components: ComponentsGallery,
};

/** Full-screen boot skeleton (status loading): top bar + contents rail + content slot. */
function BootSkeleton() {
  return (
    <div aria-busy className="flex min-h-screen flex-col bg-bg">
      <div className="flex h-12 items-center justify-between border-b border-line bg-surface px-4">
        <Skeleton className="h-4 w-44" />
        <Skeleton className="h-7 w-40" />
      </div>
      <div className="flex flex-1">
        <div className="hidden w-[232px] shrink-0 flex-col gap-2 border-r border-line p-4 lg:flex">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-6 w-full" />
          ))}
        </div>
        <div className="min-w-0 flex-1 px-4 py-6 sm:px-8">
          <div className="mx-auto w-full max-w-content">
            <Skeleton className="mb-2 h-7 w-56" />
            <Skeleton className="mb-8 h-4 w-80" />
            <SkeletonText lines={6} />
          </div>
        </div>
      </div>
    </div>
  );
}

export function App() {
  const status = useApp((s) => s.status);
  const error = useApp((s) => s.error);
  const view = useApp((s) => s.view);
  const t = useT();

  useEffect(() => {
    void useApp.getState().init();
  }, []);

  if (status === "idle" || status === "loading") return <BootSkeleton />;
  if (status === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg p-6">
        <ErrorState
          title={t("common.bootFailed")}
          error={error ?? t("common.unknownError")}
          onRetry={() => void useApp.getState().init()}
        />
      </div>
    );
  }

  const View = VIEWS[view] ?? OverviewView;
  return (
    <AppShell>
      {/* The citation landing rail is global: a [cite] click anywhere opens the source
          galley in place — jumping the whole workspace to the Sources view for what is
          essentially a footnote lookup threw the reader out of their task. */}
      <GlobalSourceSheet />
      <Suspense
        fallback={
          <div className="px-4 py-6 sm:px-8">
            <div className="mx-auto w-full max-w-content">
              <Skeleton className="mb-2 h-7 w-56" />
              <SkeletonText lines={6} />
            </div>
          </div>
        }
      >
        <View />
      </Suspense>
    </AppShell>
  );
}

function GlobalSourceSheet() {
  const sourceFocus = useApp((s) => s.sourceFocus);
  const clearSourceFocus = useApp((s) => s.clearSourceFocus);
  return (
    <SourceSpanSheet
      open={sourceFocus != null}
      onOpenChange={(open) => {
        if (!open) clearSourceFocus();
      }}
      sourceId={sourceFocus?.sourceId ?? null}
      blockStart={sourceFocus?.blockStart ?? null}
      blockEnd={sourceFocus?.blockEnd ?? null}
    />
  );
}
