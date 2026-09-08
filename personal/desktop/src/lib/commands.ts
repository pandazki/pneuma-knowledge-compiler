import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-shell';
import type { Backend, RecallResult, Snapshot } from './state';

export type Action = { kind: 'up' | 'down' | 'restart' }
  | { kind: 'use_library'; library: string }
  | { kind: 'semantic_retrieval'; library: string; enabled: boolean }
  | { kind: 'unattended'; library: string; enabled: boolean }
  | { kind: 'backend'; library: string; backend: Backend }
  | { kind: 'credential'; key: string; value: string };
export type SyncAction = { kind: 'sync'; library: string }
  | { kind: 'sync_interval'; minutes: number }
  | { kind: 'sync_enabled'; enabled: boolean }
  | { kind: 'watch_add' | 'watch_remove'; library: string; path: string };
export const getState = () => invoke<Snapshot>('get_state');
export const runAction = (action: Action | SyncAction) => invoke<void>('run_action', { action });
export const search = (library: string, query: string) => invoke<RecallResult>('search', { library, query });
export const hidePanel = () => invoke<void>('hide_panel');
export const revealPanel = () => invoke<void>('reveal_panel');
export const frontendReady = () => invoke<void>('frontend_ready');
export const quit = () => invoke<void>('quit');
export const autostartEnabled = () => invoke<boolean>('plugin:autostart|is_enabled');
export const setAutostart = (enabled: boolean) => invoke<void>(`plugin:autostart|${enabled ? 'enable' : 'disable'}`);
export async function openConsole(url: string) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port || parsed.username || parsed.password) {
    throw new Error('Only a local engine console can be opened');
  }
  await open(url);
}
export type Perform = (operation: () => Promise<unknown>, success?: string) => Promise<boolean>;
export const fitPanel = (height: number) => invoke<void>('fit_panel', { height });
