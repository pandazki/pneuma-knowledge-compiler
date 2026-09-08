import { createRoot } from 'react-dom/client';
import { listen } from '@tauri-apps/api/event';
import App, { getState } from './App';
import type { Snapshot } from './lib/state';
import './styles.css';

async function boot() {
  let latest: Snapshot | undefined;
  let receiver: ((state: Snapshot) => void) | undefined;
  // Subscribe before reading cache so a racing poll cannot disappear between the two.
  await listen<Snapshot>('state', ({ payload }) => { latest = payload; receiver?.(payload); });
  const cached = await getState();
  const initial = latest && latest.fetched_at >= cached.fetched_at ? latest : cached;
  const subscribe = (callback: (state: Snapshot) => void) => {
    receiver = callback;
    if (latest) callback(latest);
    return () => { receiver = undefined; };
  };
  createRoot(document.getElementById('root')!).render(<App initial={initial} subscribe={subscribe} />);
}
void boot().catch(error => {
  // Startup IPC failure is exceptional, and does not impersonate an empty home.
  document.getElementById('root')!.textContent = `PKC could not load its cached state: ${String(error)}`;
});
