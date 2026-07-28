import { useState, type ReactNode } from "react";
import { PanelLeft } from "lucide-react";
import { useApp } from "@/lib/store";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Drawer } from "@/ui/Drawer";
import { IconButton } from "@/ui/IconButton";
import { Mono } from "@/ui/Mono";
import { Stamp } from "@/ui/Stamp";
import { TocNav } from "./TocNav";
import { UserPicker } from "./UserPicker";
import { SnapshotPicker } from "./SnapshotPicker";
import { ThemeToggle } from "./ThemeToggle";

/**
 * 应用外壳：顶栏（字标 + 移动端目录按钮 + UserPicker / SnapshotPicker /
 * ThemeToggle）+ 桌面目录轨（232px）+ 内容栏（max-w-content）。
 * notice 条、offline 提示、历史快照档案戳横幅都长在这里。
 */
export function AppShell({ children }: { children: ReactNode }) {
  const notice = useApp((s) => s.notice);
  const dismissNotice = useApp((s) => s.dismissNotice);
  const usersError = useApp((s) => s.usersError);
  const loadUsers = useApp((s) => s.loadUsers);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const setSnapshot = useApp((s) => s.setSnapshot);
  const [tocOpen, setTocOpen] = useState(false);

  return (
    <div className="min-h-screen bg-bg text-ink">
      <header className="sticky top-0 z-40 flex h-12 items-center justify-between gap-2 border-b border-line bg-surface px-2 sm:px-4">
        <div className="flex min-w-0 items-center gap-1">
          <IconButton
            aria-label="打开目录"
            className="lg:hidden"
            onClick={() => setTocOpen(true)}
          >
            <PanelLeft size={16} aria-hidden />
          </IconButton>
          <button
            type="button"
            onClick={() => useApp.getState().setView("overview")}
            className="truncate rounded-1 font-serif text-14 font-medium text-ink"
          >
            Pneuma
            <span className="hidden sm:inline">
              {" "}
              <span className="text-ink-3">·</span> Knowledge Compiler
            </span>
          </button>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <UserPicker />
          <SnapshotPicker />
          <ThemeToggle />
        </div>
      </header>

      {usersError && (
        <Callout tone="warn" variant="inline" className="border-b border-line">
          <span className="inline-flex flex-wrap items-center gap-2">
            <span>
              无法连接 pneuma-knowledge 服务（<Mono>{usersError}</Mono>），面板已降级。
            </span>
            <Button size="sm" variant="ghost" onClick={() => void loadUsers()}>
              重试
            </Button>
          </span>
        </Callout>
      )}
      {notice && (
        <Callout tone="notice" variant="inline" onDismiss={dismissNotice} className="border-b border-line">
          {notice}
        </Callout>
      )}

      <div className="flex items-start">
        <aside className="sticky top-12 hidden h-[calc(100vh-3rem)] w-[232px] shrink-0 overflow-y-auto border-r border-line lg:block">
          <TocNav />
        </aside>
        <main className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-content px-4 py-6 sm:px-8">
            {currentSnapshot && (
              <div className="mb-6 flex flex-wrap items-center gap-3 border-b border-line pb-4">
                <Stamp tone="warn">历史快照 · 只读</Stamp>
                <Mono className="text-13 text-ink-2">{currentSnapshot}</Mono>
                <Button size="sm" variant="ghost" onClick={() => setSnapshot(null)}>
                  回到 HEAD
                </Button>
              </div>
            )}
            {children}
          </div>
        </main>
      </div>

      <Drawer open={tocOpen} onOpenChange={setTocOpen} side="left" title="目录">
        <TocNav onNavigate={() => setTocOpen(false)} />
      </Drawer>
    </div>
  );
}
