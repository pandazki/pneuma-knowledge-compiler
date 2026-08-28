import { useState, type ReactNode } from "react";
import { PanelLeft } from "lucide-react";
import { useApp } from "@/lib/store";
import type { ViewName } from "@/lib/types";
import { useT } from "@/lib/useT";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Drawer } from "@/ui/Drawer";
import { IconButton } from "@/ui/IconButton";
import { Mono } from "@/ui/Mono";
import { Stamp } from "@/ui/Stamp";
import { cn } from "@/ui/cn";
import { TocNav } from "./TocNav";
import { UserPicker } from "./UserPicker";
import { SnapshotPicker } from "./SnapshotPicker";
import { ThemeToggle } from "./ThemeToggle";
import { LocaleToggle } from "./LocaleToggle";

/**
 * Views that own their scrolling (the scroll charter): their content column is bounded to
 * the viewport on wide screens so the view can pin its controls and let each content area
 * scroll on its own. Every other view keeps the ordinary page scroll, unchanged — the list
 * grows one view at a time as the charter rolls out.
 */
const VIEWPORT_PANE_VIEWS: ReadonlySet<ViewName> = new Set<ViewName>([
  "library",
  "recall",
  "sources",
  "engine_console",
]);

/**
 * The app shell: top bar (wordmark + mobile contents button + UserPicker / SnapshotPicker /
 * LocaleToggle / ThemeToggle) + the desktop contents rail (232px) + the content column
 * (max-w-content). The notice strip, the offline warning and the historical-snapshot archive
 * stamp banner all live here.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const view = useApp((s) => s.view);
  const notice = useApp((s) => s.notice);
  const dismissNotice = useApp((s) => s.dismissNotice);
  const usersError = useApp((s) => s.usersError);
  const loadUsers = useApp((s) => s.loadUsers);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const currentKbSnapshot = useApp((s) => s.currentKbSnapshot);
  const setKbSnapshot = useApp((s) => s.setKbSnapshot);
  const setSnapshot = useApp((s) => s.setSnapshot);
  const [tocOpen, setTocOpen] = useState(false);
  const t = useT();

  return (
    <div className="min-h-screen bg-bg text-ink">
      <header className="sticky top-0 z-40 flex h-12 items-center justify-between gap-2 border-b border-line bg-surface px-2 sm:px-4">
        <div className="flex min-w-0 items-center gap-1">
          <IconButton
            aria-label={t("nav.toc.open")}
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
          <LocaleToggle />
          <ThemeToggle />
        </div>
      </header>

      {usersError && (
        <Callout tone="warn" variant="inline" className="border-b border-line">
          <span className="inline-flex flex-wrap items-center gap-2">
            <span>{t("nav.offline")}</span>
            <Mono className="text-12 text-ink-2">{usersError}</Mono>
            <Button size="sm" variant="ghost" onClick={() => void loadUsers()}>
              {t("common.retry")}
            </Button>
          </span>
        </Callout>
      )}
      {notice && (
        <Callout tone="notice" variant="inline" onDismiss={dismissNotice} className="border-b border-line">
          {t(notice.key, notice.params)}
        </Callout>
      )}

      <div className="flex items-start">
        <aside className="sticky top-12 hidden h-[calc(100vh-3rem)] w-[232px] shrink-0 overflow-y-auto border-r border-line lg:block">
          <TocNav />
        </aside>
        <main className="min-w-0 flex-1">
          <div
            className={cn(
              "w-full",
              view === "engine_console"
                ? "flex h-[calc(100dvh-3rem)] min-h-0 flex-col overflow-hidden"
                : "mx-auto max-w-content px-4 py-6 sm:px-8",
              // The snapshot banner is inside the box, so the panes below it shrink by
              // exactly its height instead of guessing at it.
              VIEWPORT_PANE_VIEWS.has(view) && view !== "engine_console" &&
                "flex flex-col lg:h-[calc(100dvh-3rem)] lg:min-h-0",
            )}
          >
            {currentSnapshot && (
              // Same visual language for both read planes, different words: a frozen snapshot
              // is named by its label (it answers questions), a bare commit by its ref (it is
              // canonical-only browsing).
              <div
                className={cn(
                  "flex shrink-0 flex-wrap items-center gap-3 border-b border-line",
                  view === "engine_console" ? "px-4 py-3" : "mb-6 pb-4",
                )}
              >
                <Stamp tone="warn">
                  {t(currentKbSnapshot ? "nav.snapshot.kbBanner" : "nav.snapshotBanner")}
                </Stamp>
                <Mono
                  className="min-w-0 max-w-full truncate text-13 text-ink-2"
                  title={currentKbSnapshot ? currentKbSnapshot.label : currentSnapshot}
                >
                  {currentKbSnapshot ? currentKbSnapshot.label : currentSnapshot}
                </Mono>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setKbSnapshot(null);
                    setSnapshot(null);
                  }}
                >
                  {t("nav.backToHead")}
                </Button>
              </div>
            )}
            {children}
          </div>
        </main>
      </div>

      <Drawer
        open={tocOpen}
        onOpenChange={setTocOpen}
        side="left"
        title={t("nav.toc.aria")}
      >
        <TocNav onNavigate={() => setTocOpen(false)} />
      </Drawer>
    </div>
  );
}
