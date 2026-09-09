/**
 * The React face of the home probe (lib/home.ts, lib/store.ts `loadHome`).
 *
 * `useHome()` is a plain read: null on every project deployment, the machine's status
 * document when a personal edition's engine served this console. `useHomeProbe()` owns the
 * re-poll and is mounted exactly once, at the app root — health is a live thing (an engine
 * stops, a queue drains) and a page that reported it once at boot would be lying by lunch.
 *
 * Two rules keep the probe from being a cost anyone pays for nothing: it starts only once a
 * home has actually answered (a 404 is remembered in the store and never asked again), and
 * it skips while the tab is hidden, because a background tab's health page is not being read
 * by anybody.
 */
import { useEffect } from "react";
import { useApp } from "./store";
import type { HomeStatus } from "./home";

/** Slow on purpose: this is a glance, not a monitor. */
export const HOME_POLL_MS = 30_000;

export function useHome(): HomeStatus | null {
  return useApp((s) => s.home);
}

export function useHomeProbe(): void {
  const present = useApp((s) => s.home != null);
  useEffect(() => {
    if (!present) return;
    const id = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      void useApp.getState().loadHome();
    }, HOME_POLL_MS);
    return () => clearInterval(id);
  }, [present]);
}
