import { t, type Locale, type Message } from './i18n.ts';
import { deepLibrary, type Snapshot, type ShallowLibrary } from './state.ts';

export function shortUptime(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 60) return '<1m';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h ${minutes % 60}m` : `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

export function relativeTime(stamp: string | null | undefined, now: number, locale: Locale): string {
  if (!stamp) return t(locale, 'unknown');
  const time = Date.parse(stamp);
  if (!Number.isFinite(time) || !Number.isFinite(now)) return t(locale, 'unknown');
  const minutes = Math.floor(Math.max(0, now - time) / 60_000);
  if (minutes < 1) return t(locale, 'justNow');
  if (minutes < 60) return t(locale, 'minuteAgo', { count: minutes });
  if (minutes < 1440) return t(locale, 'hourAgo', { count: Math.floor(minutes / 60) });
  return t(locale, 'dayAgo', { count: Math.floor(minutes / 1440) });
}

export function checkedTime(stamp: number, locale: Locale): string {
  return new Date(stamp).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function orderedLibraries(state: Snapshot): ShallowLibrary[] {
  return [...state.shallow.libraries].sort((a, b) => Number(b.current) - Number(a.current));
}

export interface Readout { id: Message; value: string; note?: string; title?: string }

export function readoutRows(state: Snapshot, library: ShallowLibrary, now: number, locale: Locale): Readout[] {
  const deep = deepLibrary(state, library);
  // A shallow observation can be known even while the deep endpoint is unavailable.
  // Never read an unrelated engine's cached response or invent a zero for unknown data.
  const queue = deep?.queue ?? library.queue;
  const sync = deep?.sync ?? library.sync;
  const seconds = library.engine.uptime === null ? null
    : library.engine.uptime + Math.max(0, now - state.fetched_at) / 1000;
  const known = (value: boolean | null | undefined, yes: Message, no: Message) =>
    value == null ? t(locale, 'unknown') : t(locale, value ? yes : no);
  const isCount = (value: number | null | undefined): value is number =>
    value != null && Number.isSafeInteger(value) && value >= 0;
  const number = (value: number) => value.toLocaleString(locale);
  const queueKnown = queue && isCount(queue.succeeded) && isCount(queue.pending) && isCount(queue.failed);
  const watching = sync?.watching ?? library.watching;
  const syncTime = sync?.running ? t(locale, 'syncing') : sync?.last_run_at
    ? relativeTime(sync.last_run_at, now, locale) : t(locale, 'never');
  const elapsed = shortUptime(seconds);
  const failures = Object.entries(queue?.failed_by_kind ?? {}).filter(([, count]) => count > 0)
    .sort(([a], [b]) => a.localeCompare(b)).map(([kind, count]) => `${kind} ${number(count)}`).join(' · ');
  return [
    { id: 'engine', value: library.engine.up ? elapsed === '—' ? t(locale, 'unknown') : `${t(locale, 'up')} · ${elapsed}` : t(locale, 'down'),
      note: !library.engine.up && library.pid_alive ? t(locale, 'processWaiting') : undefined },
    { id: 'queue', value: queueKnown ? `${number(queue.succeeded!)} ${t(locale, 'done')} · ${number(queue.pending)} ${t(locale, 'pending')} · ${number(queue.failed)} ${t(locale, 'failed')}` : t(locale, 'unknown'),
      note: queueKnown && failures ? failures : undefined },
    { id: 'lastCompile', value: queue ? queue.last_compile_at ? relativeTime(queue.last_compile_at, now, locale) : t(locale, 'noneYet') : t(locale, 'unknown'),
      title: queue?.last_compile_at ?? undefined },
    { id: 'sync', value: sync && watching && isCount(sync.held) && syncTime !== t(locale, 'unknown')
      ? `${t(locale, 'watching')} ${number(watching.length)} · ${t(locale, 'held')} ${number(sync.held)} · ${syncTime}` : t(locale, 'unknown'),
      title: sync?.last_run_at ?? undefined },
    { id: 'key', value: known(deep?.key ?? library.key, 'present', 'absent') },
    { id: 'skill', value: known(deep?.skill_fresh ?? library.skill_fresh, 'fresh', 'stale') },
  ];
}
