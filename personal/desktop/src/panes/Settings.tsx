import { useEffect, useState } from 'react';
import { autostartEnabled, openConsole, runAction, setAutostart, type Perform } from '../lib/commands';
import { consoleUrl, currentLibrary, type Backend, type Snapshot } from '../lib/state';

export default function Settings({ state, busy, perform }: { state: Snapshot; busy: boolean; perform: Perform }) {
  const library = currentLibrary(state);
  const [key, setKey] = useState('');
  const [keyName, setKeyName] = useState('OPENROUTER_API_KEY');
  const [login, setLogin] = useState<boolean | null>(null);
  const [directory, setDirectory] = useState('');
  const [interval, setInterval] = useState('15');
  useEffect(() => { setInterval(String(state.shallow.sync_config?.interval_minutes ?? 15)); }, [state.shallow.sync_config?.interval_minutes]);
  useEffect(() => { void perform(async () => { setLogin(await autostartEnabled()); }); }, [perform]);
  useEffect(() => {
    const provider = library?.choices.embedding.split(':')[0];
    setKeyName(provider === 'openai' ? 'OPENAI_API_KEY' : provider === 'google' || provider === 'google-genai' ? 'GOOGLE_API_KEY' : 'OPENROUTER_API_KEY');
    setKey('');
  }, [library?.name, library?.choices.embedding]);
  return <form className="settings" onSubmit={event => event.preventDefault()}>
    <h1>Your home</h1>
    <label htmlFor="library">Current library</label>
    <select id="library" disabled={busy || !state.shallow.libraries.length} value={library?.name ?? ''} onChange={event => {
      const name = event.target.value;
      void perform(() => runAction({ kind: 'use_library', library: name }), `Switched to ${name}`);
    }}><option value="" disabled>Choose a library</option>{state.shallow.libraries.map(lib => <option key={lib.name} value={lib.name}>{lib.name}</option>)}</select>
    {!library && <p className="muted">Choose a library to set its retrieval and compile preferences.</p>}
    <div className="setting-group">
      <label htmlFor="embedding-key">Embedding key</label>
      <p className="muted compact">{library ? library.choices.embedding : 'Shared across your libraries'}</p>
      <label className="sr-only" htmlFor="key-name">Credential name</label>
      <input id="key-name" aria-describedby="key-help" value={keyName} disabled={busy || !state.shallow.configured} onChange={event => setKeyName(event.target.value)} autoCapitalize="characters" spellCheck={false} />
      <div className="input-action"><input id="embedding-key" type="password" value={key} autoComplete="new-password" spellCheck={false} placeholder="Paste your key" disabled={busy || !state.shallow.configured} onChange={event => setKey(event.target.value)} />
        <button disabled={busy || !key.trim() || !/^[A-Z][A-Z0-9_]*$/.test(keyName)} onClick={() => {
          const value = key; setKey('');
          void perform(() => runAction({ kind: 'credential', key: keyName, value }), 'Embedding key saved');
        }}>Save</button></div>
      <p id="key-help" className="muted compact">Use the credential name required by your embedding provider.</p>
    </div>
    <label className="toggle"><span>Semantic retrieval</span><input type="checkbox" role="switch" checked={library?.choices.semantic_retrieval ?? false} disabled={busy || !library} onChange={event => {
      if (library) void perform(() => runAction({ kind: 'semantic_retrieval', library: library.name, enabled: event.target.checked }), 'Retrieval preference saved');
    }} /></label>
    <div className="setting-group">
      <label className="toggle"><span>Compile unattended</span><input type="checkbox" role="switch" checked={library?.choices.unattended ?? true} disabled={busy || !library} onChange={event => {
        if (library) void perform(() => runAction({ kind: 'unattended', library: library.name, enabled: event.target.checked }), 'Worker posture saved · engine restarted');
      }} /></label>
      <p className="muted compact">Off leaves compile jobs queued for your own session; changing it restarts this library's engine.</p>
    </div>
    <label htmlFor="backend">Compile backend</label>
    <select id="backend" value={library?.choices.backend ?? 'codex'} disabled={busy || !library} onChange={event => {
      if (library) void perform(() => runAction({ kind: 'backend', library: library.name, backend: event.target.value as Backend }), 'Compile backend saved');
    }}><option value="codex">Codex</option><option value="claude-code">Claude Code</option><option value="api">Model API</option></select>
    <div className="setting-group">
      <label className="toggle"><span>Sync coding sessions automatically</span><input type="checkbox" role="switch" checked={state.shallow.sync_config?.enabled ?? true} disabled={busy || !state.shallow.configured} onChange={event => {
        void perform(() => runAction({ kind: 'sync_enabled', enabled: event.target.checked }), 'Sync preference saved');
      }} /></label>
      <label htmlFor="sync-interval">Sync interval in minutes · all libraries</label>
      <div className="input-action"><input id="sync-interval" type="number" min="1" step="1" value={interval} disabled={busy || !state.shallow.configured} onChange={event => setInterval(event.target.value)} />
        <button disabled={busy || !state.shallow.configured || !Number.isSafeInteger(Number(interval)) || Number(interval) < 1} onClick={() => void perform(
          () => runAction({ kind: 'sync_interval', minutes: Number(interval) }), 'Sync interval saved')}>Save</button></div>
      <label htmlFor="watch-directory">Watched directories · {library?.name ?? 'choose a library'}</label>
      {(library?.watching ?? []).map(path => <div className="input-action" key={path}><span className="home-path" title={path}>{path}</span>
        <button disabled={busy} aria-label={`Remove ${path}`} onClick={() => { if (library) void perform(
          () => runAction({ kind: 'watch_remove', library: library.name, path }), 'Directory removed'); }}>Remove</button></div>)}
      {!library?.watching?.length && <p className="muted compact">Add a project directory to bring its coding sessions into this library.</p>}
      <div className="input-action"><input id="watch-directory" value={directory} placeholder="~/projects/momo" disabled={busy || !library} onChange={event => setDirectory(event.target.value)} />
        <button disabled={busy || !library || !directory.trim()} onClick={() => {
          if (library) void perform(async () => {
            await runAction({ kind: 'watch_add', library: library.name, path: directory }); setDirectory('');
          }, 'Directory added');
        }}>Add</button></div>
    </div>
    <label className="toggle login"><span>Launch at login</span><input type="checkbox" role="switch" checked={login === true} disabled={busy || login === null} onChange={event => {
      const enabled = event.target.checked;
      void perform(async () => { await setAutostart(enabled); setLogin(enabled); });
    }} /></label>
    <button disabled={busy || !library?.engine.up} onClick={() => { if (library) void perform(() => openConsole(consoleUrl(library.engine.port))); }}>Open console ↗</button>
    <p className="muted home-path" title={state.shallow.home.path}>{state.shallow.home.path}</p>
  </form>;
}
