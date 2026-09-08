import { useCallback, useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { listen } from '@tauri-apps/api/event';
import Dashboard from './panes/Dashboard';
import Search from './panes/Search';
import Settings from './panes/Settings';
import { frontendReady, getState, hidePanel, quit, revealPanel, type Perform } from './lib/commands';
import { health, healthLabels, type Snapshot, type Tab } from './lib/state';

const tabs: Tab[] = ['dashboard', 'search', 'settings'];
export default function App({ initial, subscribe }: {
  initial: Snapshot;
  subscribe: (receiver: (state: Snapshot) => void) => () => void;
}) {
  const [state, setState] = useState(initial);
  const [tab, setTab] = useState<Tab>('dashboard');
  const [pending, setPending] = useState(0);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const [now, setNow] = useState(Date.now());
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const perform: Perform = useCallback(async (operation, success) => {
    setPending(n => n + 1);
    try {
      await operation();
      if (success) { setToast({ text: success, error: false }); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(null), 3500); }
      return true;
    } catch (error) {
      clearTimeout(toastTimer.current); setToast({ text: String(error), error: true }); return false;
    } finally { setPending(n => n - 1); }
  }, []);
  useEffect(() => subscribe(next => setState(previous => next.fetched_at >= previous.fetched_at ? next : previous)), [subscribe]);
  useEffect(() => {
    let disposed = false;
    const listeners: (() => void)[] = [];
    void (async () => {
      listeners.push(await listen<{ state: Snapshot; tab: Tab | null }>('panel-open', ({ payload }) => {
        flushSync(() => { setState(payload.state); setNow(Date.now()); if (payload.tab) setTab(payload.tab); });
        // Commit the cached DOM before ordering the native panel onto the screen. Not
        // requestAnimationFrame: a hidden WKWebView never paints, so a frame callback in a
        // window that is not yet on screen never fires and the panel would never open.
        setTimeout(() => { void perform(async () => {
          await revealPanel();
          const focus = document.getElementById('search-query') ?? document.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
          focus?.focus();
        }); });
      }));
      listeners.push(await listen('panel-hidden', () => {
        // Secret fields are unmounted when a popover dismisses.
        setTab(previous => previous === 'settings' ? 'dashboard' : previous);
      }));
      if (disposed) listeners.forEach(unlisten => unlisten());
      else await frontendReady();
    })().catch(error => { setToast({ text: String(error), error: true }); });
    const clock = setInterval(() => setNow(Date.now()), 1000);
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); void perform(hidePanel); } };
    window.addEventListener('keydown', escape);
    return () => { disposed = true; listeners.forEach(unlisten => unlisten()); clearInterval(clock); clearTimeout(toastTimer.current); window.removeEventListener('keydown', escape); };
  }, [perform]);
  const busy = pending > 0;
  return <div className="popover">
    <header><span className="brand"><span className="brand-glyph" aria-hidden="true">▤</span> PKC</span>
      <span className={`dot ${health(state.shallow)}`} role="img" aria-label={healthLabels[health(state.shallow)]} />
      <button className="icon-button" aria-label="Close panel" onClick={() => void perform(hidePanel)}>×</button></header>
    <nav role="tablist" aria-label="PKC panes">{tabs.map((item, index) => <button key={item} role="tab" id={`tab-${item}`} aria-controls={`pane-${item}`} aria-selected={tab === item} tabIndex={tab === item ? 0 : -1} onClick={() => setTab(item)} onKeyDown={event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
      if (next >= 0) { event.preventDefault(); setTab(tabs[next]); document.getElementById(`tab-${tabs[next]}`)?.focus(); }
    }}>{item[0].toUpperCase() + item.slice(1)}</button>)}</nav>
    <main role="tabpanel" id={`pane-${tab}`} aria-labelledby={`tab-${tab}`} tabIndex={0}>
      {tab === 'dashboard' && <Dashboard state={state} busy={busy} perform={perform} now={now} />}
      {tab === 'search' && <Search state={state} busy={busy} perform={perform} />}
      {tab === 'settings' && <Settings state={state} busy={busy} perform={perform} />}
    </main>
    {toast && <aside className={`toast ${toast.error ? 'toast-error' : ''}`} role={toast.error ? 'alert' : 'status'}><span>{toast.text}</span><button aria-label="Dismiss message" onClick={() => setToast(null)}>×</button></aside>}
    <footer><span>{busy ? 'Applying…' : state.fetched_at ? `Checked ${new Date(state.fetched_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Status unavailable'}</span>
      <button onClick={() => void perform(quit)}>Quit</button></footer>
  </div>;
}
// Imported by the entrypoint to fetch cache before the first React render.
export { getState };
