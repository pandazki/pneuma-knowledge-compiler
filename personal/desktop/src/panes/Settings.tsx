import { useEffect, useState } from 'react';
import { autostartEnabled, openConsole, runAction, setAutostart, type Perform } from '../lib/commands';
import { t, type Locale } from '../lib/i18n';
import { consoleUrl, currentLibrary, type Backend, type Snapshot } from '../lib/state';
import { LedgerSelect, SettingRow } from './Ledger';

function TextToggle({ id, value, disabled, onChange, locale, describedBy }: {
  id: string; value: boolean | null; disabled: boolean; onChange: (value: boolean) => void; locale: Locale; describedBy?: string;
}) {
  return <button id={id} type="button" className="text-toggle" role="switch" aria-checked={value === true}
    aria-labelledby={`${id}-label`} aria-describedby={describedBy} disabled={disabled || value === null} onClick={() => onChange(!value)}>
    {value === null ? t(locale, 'unknown') : <>
      <span data-active={value}>{t(locale, 'on')}</span>
      <span className="toggle-divider" aria-hidden="true" />
      <span data-active={!value}>{t(locale, 'off')}</span>
    </>}
  </button>;
}

export default function Settings({ state, busy, perform, locale, preference, onLanguage }: {
  state: Snapshot; busy: boolean; perform: Perform; locale: Locale; preference: string; onLanguage: (value: string) => void;
}) {
  const library = currentLibrary(state);
  const [key, setKey] = useState('');
  const [keyName, setKeyName] = useState('OPENROUTER_API_KEY');
  const [login, setLogin] = useState<boolean | null>(null);
  const [directory, setDirectory] = useState('');
  const [interval, setInterval] = useState('15');
  const intervalMinutes = Number(interval);
  const validInterval = Number.isSafeInteger(intervalMinutes) && intervalMinutes >= 1;
  useEffect(() => { setInterval(String(state.shallow.sync_config?.interval_minutes ?? 15)); }, [state.shallow.sync_config?.interval_minutes]);
  useEffect(() => { void perform(async () => { setLogin(await autostartEnabled()); }); }, [perform]);
  useEffect(() => {
    const provider = library?.choices.embedding.split(':')[0];
    setKeyName(provider === 'openai' ? 'OPENAI_API_KEY' : provider === 'google' || provider === 'google-genai' ? 'GOOGLE_API_KEY' : 'OPENROUTER_API_KEY');
    setKey('');
  }, [library?.name, library?.choices.embedding]);

  return <form className="settings" onSubmit={event => event.preventDefault()}>
    <h1>{t(locale, 'settings')}</h1>
    <SettingRow id="library" label={t(locale, 'current')}>
      <LedgerSelect id="library" disabled={busy || !state.shallow.libraries.length} value={library?.name ?? ''} onChange={event => {
        const name = event.target.value;
        void perform(() => runAction({ kind: 'use_library', library: name }), t(locale, 'switched', { name }));
      }}><option value="" disabled>{t(locale, 'chooseLibrary')}</option>{state.shallow.libraries.map(lib => <option key={lib.name} value={lib.name}>{lib.name}</option>)}</LedgerSelect>
    </SettingRow>
    {!library && <p className="muted">{t(locale, 'choosePreferences')}</p>}
    <SettingRow id="language" label={t(locale, 'language')}>
      <LedgerSelect id="language" value={preference} onChange={event => onLanguage(event.target.value)}>
        <option value="system">{t(locale, 'systemLanguage')}</option><option value="en" lang="en">English</option><option value="zh-CN" lang="zh-CN">简体中文</option>
      </LedgerSelect>
    </SettingRow>

    <section className="setting-group" aria-labelledby="embedding-heading">
      <h2 id="embedding-heading" className="section-label small-caps">{t(locale, 'embeddingKey')}</h2>
      <p className="muted setting-help">{library ? library.choices.embedding : t(locale, 'sharedKey')}</p>
      <label htmlFor="key-name">{t(locale, 'credentialName')}</label>
      <input id="key-name" aria-describedby="key-help" value={keyName} disabled={busy || !state.shallow.configured}
        onChange={event => setKeyName(event.target.value)} autoCapitalize="characters" spellCheck={false} />
      <label className="sr-only" htmlFor="embedding-key">{t(locale, 'embeddingKey')}</label>
      <div className="input-action"><input id="embedding-key" type="password" value={key} autoComplete="new-password" autoCorrect="off" autoCapitalize="none"
        spellCheck={false} placeholder={t(locale, 'pasteKey')} disabled={busy || !state.shallow.configured} onChange={event => setKey(event.target.value)} />
        <button disabled={busy || !key.trim() || !/^[A-Z][A-Z0-9_]*$/.test(keyName)} onClick={() => {
          const value = key; setKey('');
          void perform(async () => {
            try { await runAction({ kind: 'credential', key: keyName, value }); }
            // Provider errors must never echo a submitted secret into the footer.
            catch { throw new Error(t(locale, 'keySaveFailed')); }
          }, t(locale, 'keySaved'));
        }}>{t(locale, 'save')}</button></div>
      <p id="key-help" className="muted setting-help">{t(locale, 'keyHelp')}</p>
      <SettingRow id="semantic" label={t(locale, 'semantic')}>
        <TextToggle id="semantic" value={library?.choices.semantic_retrieval ?? false} disabled={busy || !library} locale={locale} onChange={enabled => {
          if (library) void perform(() => runAction({ kind: 'semantic_retrieval', library: library.name, enabled }), t(locale, 'retrievalSaved'));
        }} />
      </SettingRow>
    </section>

    <section className="setting-group" aria-label={t(locale, 'firstCompile')}>
      <SettingRow id="unattended" label={t(locale, 'unattended')}>
        <TextToggle id="unattended" value={library?.choices.unattended ?? true} disabled={busy || !library} locale={locale} describedBy="unattended-help" onChange={enabled => {
          if (library) void perform(() => runAction({ kind: 'unattended', library: library.name, enabled }), t(locale, 'unattendedSaved'));
        }} />
      </SettingRow>
      <p id="unattended-help" className="muted setting-help">{t(locale, 'unattendedHelp')}</p>
      <SettingRow id="backend" label={t(locale, 'backend')}>
        <LedgerSelect id="backend" value={library?.choices.backend ?? 'codex'} disabled={busy || !library} onChange={event => {
          if (library) void perform(() => runAction({ kind: 'backend', library: library.name, backend: event.target.value as Backend }), t(locale, 'backendSaved'));
        }}><option value="codex">Codex</option><option value="claude-code">Claude Code</option><option value="api">{t(locale, 'modelApi')}</option></LedgerSelect>
      </SettingRow>
    </section>

    <section className="setting-group" aria-label={t(locale, 'sync')}>
      <SettingRow id="auto-sync" label={t(locale, 'autoSync')}>
        <TextToggle id="auto-sync" value={state.shallow.sync_config?.enabled ?? true} disabled={busy || !state.shallow.configured} locale={locale} onChange={enabled => {
          void perform(() => runAction({ kind: 'sync_enabled', enabled }), t(locale, 'autoSyncSaved'));
        }} />
      </SettingRow>
      <SettingRow id="sync-interval" label={t(locale, 'interval')}>
        <div className="input-action interval-control">
          <button type="button" className="interval-step" aria-label={t(locale, 'decreaseInterval')} aria-controls="sync-interval"
            disabled={busy || !state.shallow.configured || !validInterval || intervalMinutes <= 1}
            onClick={() => setInterval(String(intervalMinutes - 1))}>−</button>
          <span className="interval-value"><input id="sync-interval" type="number" min="1" step="1" value={interval}
            aria-describedby="interval-unit interval-help" disabled={busy || !state.shallow.configured} onChange={event => setInterval(event.target.value)} />
            <span id="interval-unit">{t(locale, 'minuteUnit')}</span></span>
          <button type="button" className="interval-step" aria-label={t(locale, 'increaseInterval')} aria-controls="sync-interval"
            disabled={busy || !state.shallow.configured || !validInterval || intervalMinutes >= Number.MAX_SAFE_INTEGER}
            onClick={() => setInterval(String(intervalMinutes + 1))}>+</button>
          <button disabled={busy || !state.shallow.configured || !validInterval} onClick={() => void perform(
            () => runAction({ kind: 'sync_interval', minutes: intervalMinutes }), t(locale, 'intervalSaved'))}>{t(locale, 'save')}</button>
        </div>
      </SettingRow>
      <p id="interval-help" className="muted setting-help">{t(locale, 'intervalHelp')}</p>
    </section>

    <section className="setting-group" aria-labelledby="directories-heading">
      <h2 id="directories-heading" className="section-label small-caps">{t(locale, 'directories')}</h2>
      <ul className="directories">{(library?.watching ?? []).map(path => <li key={path}>
        <span className="directory-path" title={path}>{path}</span>
        <button className="remove-directory" disabled={busy} aria-label={t(locale, 'removeDirectory', { path })} onClick={() => { if (library) void perform(
          () => runAction({ kind: 'watch_remove', library: library.name, path }), t(locale, 'removed')); }}>{t(locale, 'remove')}</button>
      </li>)}</ul>
      {!library?.watching?.length && <p className="muted setting-help">{t(locale, 'directoryHint')}</p>}
      <label className="sr-only" htmlFor="watch-directory">{t(locale, 'directories')}</label>
      <div className="input-action"><input id="watch-directory" value={directory} placeholder={t(locale, 'directoryPlaceholder')} disabled={busy || !library} onChange={event => setDirectory(event.target.value)} />
        <button disabled={busy || !library || !directory.trim()} onClick={() => {
          if (library) void perform(async () => {
            await runAction({ kind: 'watch_add', library: library.name, path: directory }); setDirectory('');
          }, t(locale, 'added'));
        }}>{t(locale, 'add')}</button></div>
    </section>

    <section className="setting-group" aria-label={t(locale, 'login')}>
      <SettingRow id="login" label={t(locale, 'login')}>
        <TextToggle id="login" value={login} disabled={busy} locale={locale} onChange={enabled => {
          void perform(async () => { await setAutostart(enabled); setLogin(enabled); });
        }} />
      </SettingRow>
      <button disabled={busy || !library?.engine.up} onClick={() => { if (library) void perform(() => openConsole(consoleUrl(library.engine.port))); }}>{t(locale, 'openConsole')}</button>
      <p className="muted home-path" title={state.shallow.home.path}>{state.shallow.home.path}</p>
    </section>
  </form>;
}
