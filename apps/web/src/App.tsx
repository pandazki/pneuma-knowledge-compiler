import { Suspense, lazy, useEffect } from "react";
import {
  BookOpen,
  Bot,
  Braces,
  CircleGauge,
  Database,
  GitBranch,
  History as HistoryIcon,
  Loader2,
  MessageSquarePlus,
  MessagesSquare,
  Network,
  Radar,
  Sparkles,
  UserRound,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { useApp } from "./lib/store";
import { EmptyState } from "./components/ui";
import type { ViewName } from "./lib/types";
import { TopBar } from "./components/TopBar";
import { ProfileView } from "./views/ProfileView";
import { SourcesView } from "./views/SourcesView";
import { IngestView } from "./views/IngestView";
import { RecallView } from "./views/RecallView";
import { AskView } from "./views/AskView";
import { ContextStreamView } from "./views/ContextStreamView";
import { LibraryView } from "./views/LibraryView";
import { ProcessView } from "./views/ProcessView";
import { HistoryView } from "./views/HistoryView";
import { EvolveView } from "./views/EvolveView";
import { OverviewView } from "./views/OverviewView";
import { RouteFrame } from "./components/RouteFrame";
import { cn } from "./lib/cn";

const GraphView = lazy(() =>
  import("./views/GraphView").then((module) => ({ default: module.GraphView })),
);

interface NavItem {
  value: ViewName;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
}

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "线路",
    items: [
      { value: "overview", label: "系统线路", shortLabel: "线路", icon: CircleGauge },
    ],
  },
  {
    label: "运行演示",
    items: [
      { value: "ingest", label: "导入材料", shortLabel: "导入", icon: MessageSquarePlus },
      { value: "recall", label: "检索实验", shortLabel: "检索", icon: Radar },
      { value: "context_stream", label: "主动提示", shortLabel: "提示", icon: Bot },
    ],
  },
  {
    label: "核对证据",
    items: [
      { value: "sources", label: "来源档案", shortLabel: "来源", icon: Database },
      { value: "library", label: "Canonical", shortLabel: "知识", icon: BookOpen },
      { value: "history", label: "版本轨道", shortLabel: "版本", icon: HistoryIcon },
    ],
  },
  {
    label: "探索内部",
    items: [
      { value: "process", label: "编译作业", shortLabel: "作业", icon: Workflow },
      { value: "graph", label: "关系换乘", shortLabel: "关系", icon: Network },
      { value: "ask", label: "连续问答", shortLabel: "问答", icon: MessagesSquare },
      { value: "profile", label: "工作画像", shortLabel: "画像", icon: UserRound },
      { value: "evolve", label: "策略演化", shortLabel: "演化", icon: Sparkles },
    ],
  },
];

const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

function Navigation({
  value,
  onChange,
}: {
  value: ViewName;
  onChange: (view: ViewName) => void;
}) {
  return (
    <aside className="pneuma-navigation" aria-label="主导航">
      <div className="pneuma-brand">
        <span className="pneuma-brand-mark" aria-hidden>
          <i />
          <i />
          <i />
          <i />
        </span>
        <span className="pneuma-brand-copy">
          <strong>Pneuma</strong>
          <span>Knowledge Compiler</span>
        </span>
        <span className="pneuma-mobile-synthetic" title="SYNTHETIC 演示数据">
          SYNTHETIC
        </span>
      </div>

      <nav className="pneuma-nav-groups">
        {NAV_GROUPS.map((group) => (
          <div className="pneuma-nav-group" key={group.label}>
            <div className="pneuma-nav-label">{group.label}</div>
            <div className="pneuma-nav-items">
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = value === item.value;
                return (
                  <button
                    type="button"
                    key={item.value}
                    className={cn("pneuma-nav-item", active && "is-active")}
                    aria-current={active ? "page" : undefined}
                    onClick={() => onChange(item.value)}
                    title={item.label}
                  >
                    <Icon size={15} strokeWidth={1.8} />
                    <span className="pneuma-nav-long">{item.label}</span>
                    <span className="pneuma-nav-short">{item.shortLabel}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="pneuma-synthetic-stamp" title="仓库内置的 OPC 演示数据，不代表真实客户">
        <Braces size={13} />
        <span>
          OPEN DEMO
          <small>SYNTHETIC · OPC</small>
        </span>
      </div>
    </aside>
  );
}

function CanonicalEmpty({ title }: { title: string }) {
  return (
    <EmptyState
      icon={<GitBranch size={28} />}
      title={title}
      hint="该用户还没有 canonical 编译结果。请先从「材料入库」添加内容，再到「编译流水」确认处理完成。"
    />
  );
}

export function App() {
  const { status, dataset, view, setView, init } = useApp();
  const active = NAV_ITEMS.find((item) => item.value === view) ?? NAV_ITEMS[0];

  useEffect(() => {
    void init();
  }, [init]);

  return (
    <div className="pneuma-app-shell">
      <Navigation value={active.value} onChange={setView} />
      <section className="pneuma-operating-shell">
        <TopBar title={active.label} />
        <main className="pneuma-workspace" id="main-content">
          {status === "loading" && (
            <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
              <Loader2 size={18} className="animate-spin" /> 连接知识编译服务…
            </div>
          )}
          {status === "ready" && (
            <>
              {view === "overview" ? (
                <OverviewView />
              ) : (
                <RouteFrame view={view}>
                  {view === "profile" && <ProfileView />}
                  {view === "sources" && <SourcesView />}
                  {view === "ingest" && <IngestView />}
                  {view === "recall" && <RecallView />}
                  {view === "ask" && <AskView />}
                  {view === "context_stream" && <ContextStreamView />}
                  {view === "evolve" && <EvolveView />}
                  {view === "library" &&
                    (dataset ? (
                      <LibraryView />
                    ) : (
                      <CanonicalEmpty title="Canonical · 知识文档" />
                    ))}
                  {view === "history" &&
                    (dataset ? (
                      <HistoryView />
                    ) : (
                      <CanonicalEmpty title="History · 版本与快照" />
                    ))}
                  {view === "process" &&
                    (dataset ? (
                      <ProcessView />
                    ) : (
                      <CanonicalEmpty title="Process · 编译流水" />
                    ))}
                  {view === "graph" &&
                    (dataset ? (
                      <Suspense
                        fallback={
                          <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
                            <Loader2 size={18} className="animate-spin" /> 加载证据图谱…
                          </div>
                        }
                      >
                        <GraphView />
                      </Suspense>
                    ) : (
                      <CanonicalEmpty title="Graph · 证据图谱" />
                    ))}
                </RouteFrame>
              )}
            </>
          )}
        </main>
      </section>
    </div>
  );
}
