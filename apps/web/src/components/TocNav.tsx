import { useApp } from "@/lib/store";
import type { ViewName } from "@/lib/types";
import { cn } from "@/ui/cn";

interface TocItem {
  view: ViewName;
  no: string;
  label: string;
}

interface TocGroup {
  group: string;
  items: TocItem[];
}

/** DESIGN.md §3 的章节目录（「components」隐藏路由不进目录）。 */
export const TOC: TocGroup[] = [
  { group: "卷首", items: [{ view: "overview", no: "01", label: "卷首 · 这是一个编译器" }] },
  {
    group: "原料篇",
    items: [
      { view: "sources", no: "02", label: "原料 Sources" },
      { view: "ingest", no: "03", label: "导入 Ingest" },
    ],
  },
  { group: "工序篇", items: [{ view: "process", no: "04", label: "工序 Process" }] },
  {
    group: "取用篇",
    items: [
      { view: "recall", no: "05", label: "检索 Recall" },
      { view: "ask", no: "06", label: "问答 Ask" },
      { view: "live_context", no: "07", label: "即时上下文 Live Context" },
    ],
  },
  {
    group: "正典篇",
    items: [
      { view: "library", no: "08", label: "正典 Canonical" },
      { view: "graph", no: "09", label: "图谱 Graph" },
      { view: "history", no: "10", label: "版本 History" },
    ],
  },
  { group: "演化篇", items: [{ view: "evolve", no: "11", label: "演化 Evolve" }] },
  { group: "卷末", items: [{ view: "profile", no: "12", label: "画像 Profile" }] },
];

export interface TocNavProps {
  /** 选中某项后回调（移动端 Drawer 用来关闭自己）。 */
  onNavigate?: () => void;
}

/** 目录轨：章节分组 + §编号 + 当前页 accent 左标线。 */
export function TocNav({ onNavigate }: TocNavProps) {
  const view = useApp((s) => s.view);
  const setView = useApp((s) => s.setView);

  return (
    <nav aria-label="目录" className="flex flex-col gap-5 px-3 py-4">
      {TOC.map((group) => (
        <div key={group.group} className="flex flex-col gap-0.5">
          <p className="px-2 pb-1 text-12 text-ink-3">{group.group}</p>
          {group.items.map((item) => {
            const active = item.view === view;
            return (
              <button
                key={item.view}
                type="button"
                aria-current={active ? "page" : undefined}
                onClick={() => {
                  setView(item.view);
                  onNavigate?.();
                }}
                className={cn(
                  "flex items-baseline gap-2 border-l-2 px-2 py-1.5 text-left text-13",
                  "transition-colors duration-120 ease-out",
                  active
                    ? "border-accent font-medium text-ink"
                    : "border-transparent text-ink-2 hover:bg-hover hover:text-ink",
                )}
              >
                <span
                  className={cn(
                    "w-6 shrink-0 font-mono text-12",
                    active ? "text-accent" : "text-ink-3",
                  )}
                >
                  §{item.no}
                </span>
                <span className="min-w-0 truncate">{item.label}</span>
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
