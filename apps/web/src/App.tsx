import { Suspense, lazy, useEffect, type ComponentType } from "react";
import { useApp } from "./lib/store";
import type { ViewName } from "./lib/types";
import { AppShell } from "./components/AppShell";
import { ErrorState } from "./ui/ErrorState";
import { Skeleton, SkeletonText } from "./ui/Skeleton";
import OverviewView from "./views/overview/OverviewView";

// 视图级分包：主包只留卷首，其余视图首访时加载（Suspense 骨架兜底）。
const ProfileView = lazy(() => import("./views/profile/ProfileView"));
const SourcesView = lazy(() => import("./views/sources/SourcesView"));
const IngestView = lazy(() => import("./views/ingest/IngestView"));
const ProcessView = lazy(() => import("./views/process/ProcessView"));
const RecallView = lazy(() => import("./views/recall/RecallView"));
const AskView = lazy(() => import("./views/ask/AskView"));
const CueView = lazy(() => import("./views/context_stream/CueView"));
const LibraryView = lazy(() => import("./views/library/LibraryView"));
const GraphView = lazy(() => import("./views/graph/GraphView"));
const HistoryView = lazy(() => import("./views/history/HistoryView"));
const EvolveView = lazy(() => import("./views/evolve/EvolveView"));
const ComponentsGallery = lazy(() => import("./views/components/ComponentsGallery"));

const VIEWS: Record<ViewName, ComponentType> = {
  overview: OverviewView,
  profile: ProfileView,
  sources: SourcesView,
  ingest: IngestView,
  process: ProcessView,
  recall: RecallView,
  ask: AskView,
  context_stream: CueView,
  library: LibraryView,
  graph: GraphView,
  history: HistoryView,
  evolve: EvolveView,
  components: ComponentsGallery,
};

/** 全屏启动骨架（status loading）：顶栏 + 目录轨 + 内容位。 */
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

  useEffect(() => {
    void useApp.getState().init();
  }, []);

  if (status === "idle" || status === "loading") return <BootSkeleton />;
  if (status === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg p-6">
        <ErrorState
          title="启动失败"
          error={error ?? "未知错误"}
          onRetry={() => void useApp.getState().init()}
        />
      </div>
    );
  }

  const View = VIEWS[view] ?? OverviewView;
  return (
    <AppShell>
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
