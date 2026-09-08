import { useCallback, useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { listen } from '@tauri-apps/api/event';
import Dashboard from './panes/Dashboard';
import Search from './panes/Search';
import Settings from './panes/Settings';
import Footer from './panes/Footer';
import { fitPanel, frontendReady, getState, hidePanel, quit, revealPanel, type Perform } from './lib/commands';
import { resolveLocale, t } from './lib/i18n';
import type { Snapshot, Tab } from './lib/state';

function languagePreference(): string {
  try { return localStorage.getItem('pkc-desktop.locale') ?? 'system'; } catch { return 'system'; }
}

export default function App({ initial, subscribe }: {
  initial: Snapshot;
  subscribe: (receiver: (state: Snapshot) => void) => () => void;
}) {
  const [state, setState] = useState(initial);
  const [page, setPage] = useState<Tab>('dashboard');
  const [query, setQuery] = useState('');
  const [submitted, setSubmitted] = useState(0);
  const [composing, setComposing] = useState(false);
  const [preference, setPreference] = useState(languagePreference);
  const [languages, setLanguages] = useState(navigator.languages);
  const locale = resolveLocale(preference, languages);
  const [pending, setPending] = useState(0);
  const [status, setStatus] = useState<{ text: string; error: boolean; id: number } | null>(null);
  const [now, setNow] = useState(Date.now());
  const [opened, setOpened] = useState(true);
  const statusTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const statusId = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const body = useRef<HTMLElement>(null);
  const notify = useCallback((text: string, error: boolean) => {
    clearTimeout(statusTimer.current);
    setStatus({ text, error, id: ++statusId.current });
    statusTimer.current = setTimeout(() => setStatus(null), error ? 7000 : 3500);
  }, []);
  const perform: Perform = useCallback(async (operation, success) => {
    setPending(n => n + 1);
    try {
      await operation();
      if (success) notify(success, false);
      return true;
    } catch (error) { notify(String(error), true); return false; }
    finally { setPending(n => n - 1); }
  }, [notify]);

  // The panel takes the height of its content (a paper card does not stretch): after
  // every paint, hand the document's height to the native side. Cheap, idempotent.
  useEffect(() => {
    // The popover is clamped to the viewport, so its own height never says how tall the
    // content is: measure the header and footer as laid out and the body by what it holds.
    const measure = () => {
      const popover = document.querySelector<HTMLElement>('.popover');
      if (!popover) return;
      let total = 0;
      for (const child of Array.from(popover.children) as HTMLElement[]) {
        total += child.id === 'panel-body' ? child.scrollHeight : child.getBoundingClientRect().height;
      }
      void fitPanel(Math.ceil(total)).catch(() => undefined);
    };
    const observer = new ResizeObserver(measure);
    const popover = document.querySelector<HTMLElement>('.popover');
    if (popover) { observer.observe(popover); for (const child of Array.from(popover.children)) observer.observe(child); }
    const mutations = new MutationObserver(measure);
    if (popover) mutations.observe(popover, { childList: true, subtree: true, characterData: true });
    measure();
    return () => { observer.disconnect(); mutations.disconnect(); };
  }, []);
  useEffect(() => subscribe(next => setState(previous => next.fetched_at >= previous.fetched_at ? next : previous)), [subscribe]);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  useEffect(() => {
    const changed = () => setLanguages(navigator.languages);
    window.addEventListener('languagechange', changed);
    return () => window.removeEventListener('languagechange', changed);
  }, []);
  useEffect(() => {
    let disposed = false;
    const listeners: (() => void)[] = [];
    void (async () => {
      listeners.push(await listen<{ state: Snapshot; tab: Tab | null }>('panel-open', ({ payload }) => {
        flushSync(() => {
          setState(payload.state); setNow(Date.now()); setOpened(true);
          if (payload.tab) { setPage(payload.tab); if (payload.tab !== 'search') setQuery(''); }
        });
        // Commit the cached DOM before ordering the native panel onto the screen. Not
        // requestAnimationFrame: a hidden WKWebView never paints, so a frame callback in a
        // window that is not yet on screen never fires and the panel would never open.
        setTimeout(() => { void perform(async () => {
          await revealPanel();
          input.current?.focus();
        }); });
      }));
      listeners.push(await listen('panel-hidden', () => {
        // Unmount secret fields whenever the panel dismisses.
        setPage(previous => previous === 'settings' ? 'dashboard' : previous);
        setComposing(false); setOpened(false);
      }));
      if (disposed) listeners.forEach(unlisten => unlisten());
      else await frontendReady();
    })().catch(error => notify(String(error), true));
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { disposed = true; listeners.forEach(unlisten => unlisten()); clearInterval(clock); clearTimeout(statusTimer.current); };
  }, [perform, notify]);

  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (event.isComposing || composing) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setPage('search'); input.current?.focus(); input.current?.select();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        if (query) { setQuery(''); setPage('dashboard'); input.current?.focus(); }
        else void perform(hidePanel);
      } else if (page === 'search' && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
        const links = Array.from(body.current?.querySelectorAll<HTMLAnchorElement>('[data-result-link]') ?? []);
        const active = links.indexOf(document.activeElement as HTMLAnchorElement);
        if (document.activeElement !== input.current && active < 0) return;
        event.preventDefault();
        const next = active + (event.key === 'ArrowDown' ? 1 : -1);
        if (next < 0) input.current?.focus();
        else links[Math.min(next, links.length - 1)]?.focus();
      } else if (event.key === 'Enter' && document.activeElement === input.current && page === 'search') {
        event.preventDefault();
        const first = body.current?.querySelector<HTMLAnchorElement>('[data-result-link]');
        if (first) first.click(); else setSubmitted(n => n + 1);
      }
    };
    window.addEventListener('keydown', keyboard);
    return () => window.removeEventListener('keydown', keyboard);
  }, [page, query, composing, perform]);

  const busy = pending > 0;
  return <div className="popover" data-open={opened}>
    <header className="search-bar">
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m12.5 12.5 4 4" /></svg>
      <label className="sr-only" htmlFor="search-query">{t(locale, 'ask')}</label>
      <input id="search-query" ref={input} type="search" placeholder={t(locale, 'ask')} autoComplete="off" spellCheck={false}
        maxLength={8000} value={query} aria-controls="panel-body" aria-keyshortcuts="Meta+K Control+K"
        onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)}
        onChange={event => { setQuery(event.target.value); setPage(event.target.value ? 'search' : 'dashboard'); }} />
      <kbd aria-hidden="true">⌘K</kbd>
    </header>
    <main id="panel-body" ref={body} className={page === 'dashboard' ? 'dashboard-body' : undefined} aria-label={t(locale, page === 'dashboard' ? 'back' : page)}>
      {page === 'dashboard' && <Dashboard state={state} busy={busy} perform={perform} now={now} locale={locale} />}
      {page === 'search' && <Search state={state} busy={busy} perform={perform} query={query} composing={composing} locale={locale} submitted={submitted} />}
      {page === 'settings' && <Settings state={state} busy={busy} perform={perform} locale={locale} preference={preference} onLanguage={value => {
        setPreference(value);
        try { localStorage.setItem('pkc-desktop.locale', value); } catch { /* The current session still follows the selected language. */ }
      }} />}
    </main>
    <Footer state={state} busy={busy} status={status} locale={locale} settings={page === 'settings'}
      onSettings={() => { setQuery(''); setPage(page === 'settings' ? 'dashboard' : 'settings'); body.current?.scrollTo(0, 0); }}
      onQuit={() => void perform(quit)} onDismiss={() => setStatus(null)} />
  </div>;
}
// Imported by the entrypoint to fetch cache before the first React render.
export { getState };
