import { useEffect, useState } from 'react';
import { autostartEnabled, openConsole, runAction, setAutostart, type Perform } from '../lib/commands';
import { t, type Locale, type Message } from '../lib/i18n';
import { consoleUrl, credentialName, currentLibrary, deepLibrary, keyReadout, timeLabel, type Backend, type KeyReadout, type Snapshot } from '../lib/state';
import { LedgerSelect, Leader, SettingRow } from './Ledger';

const verdicts: Record<Exclude<KeyReadout, 'absent' | 'unknown'>, Message> = {
  verified: 'keyVerified', unverified: 'keyUnverified', unused: 'keyUnused',
};

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
  const [replacing, setReplacing] = useState(false);
  const [login, setLogin] = useState<boolean | null>(null);
  const [directory, setDirectory] = useState('');
  const [interval, setInterval] = useState('15');
  const intervalMinutes = Number(interval);
  const validInterval = Number.isSafeInteger(intervalMinutes) && intervalMinutes >= 1;
  useEffect(() => { setInterval(String(state.shallow.sync_config?.interval_minutes ?? 15)); }, [state.shallow.sync_config?.interval_minutes]);
  useEffect(() => { void perform(async () => { setLogin(await autostartEnabled()); }); }, [perform]);
  const deep = library ? deepLibrary(state, library) : undefined;
  const storedName = credentialName(library?.choices.embedding);
  const readout = keyReadout(library, deep);
  // A stored key is a readout, not a waiting field; the field is revealed to replace it.
  const editing = readout === 'absent' || replacing;
  const stamped = (deep ?? library)?.steps.credentials;
  const savedAt = typeof stamped === 'string' ? stamped : null;
  const verdict = readout === 'absent' || readout === 'unknown' ? null : t(locale, verdicts[readout]);
  const provenance = [savedAt ? t(locale, 'keySavedAt', { time: timeLabel(savedAt) }) : null, verdict].filter(Boolean).join(' · ');
  useEffect(() => { setKeyName(storedName); setKey(''); setReplacing(false); }, [library?.name, storedName]);

  return <form className="settings" onSubmit={event => event.preventDefault()}>
    <h1>{t(locale, 'settings')}</h1>
    <SettingRow id="library" label={t(locale, 'current')}>
      <LedgerSelect id="library" disabled={busy || !state.shallow.libraries.length} value={library?.name ?? ''} placeholder={t(locale, 'chooseLibrary')}
        options={state.shallow.libraries.map(lib => ({ value: lib.name, label: lib.name }))} onChange={name => {
          void perform(() => runAction({ kind: 'use_library', library: name }), t(locale, 'switched', { name }));
        }} />
    </SettingRow>
    {!library && <p className="muted">{t(locale, 'choosePreferences')}</p>}
    <SettingRow id="language" label={t(locale, 'language')}>
      <LedgerSelect id="language" value={preference} onChange={onLanguage} options={[
        { value: 'system', label: t(locale, 'systemLanguage') }, { value: 'en', label: 'English', lang: 'en' }, { value: 'zh-CN', label: '简体中文', lang: 'zh-CN' },
      ]} />
    </SettingRow>

    <section className="setting-group" aria-labelledby="embedding-heading">
      <h2 id="embedding-heading" className="section-label small-caps">{t(locale, 'embeddingKey')}</h2>
      <p className="muted setting-help">{library ? library.choices.embedding : t(locale, 'sharedKey')}</p>
      {readout !== 'absent' && <dl className="ledger"><div className="readout">
        <dt className="small-caps">{t(locale, 'credentialName')}</dt><Leader />
        <dd>{readout === 'unknown' ? t(locale, 'unknown') : storedName}</dd>
        <dd className="readout-action"><button type="button" aria-expanded={replacing} aria-controls="key-controls" disabled={busy}
          onClick={() => { setReplacing(!replacing); setKeyName(storedName); setKey(''); }}>{t(locale, replacing ? 'cancel' : 'replace')}</button></dd>
        {provenance && <dd className="readout-note">{provenance}</dd>}
      </div></dl>}
      {editing && <div id="key-controls" className="key-controls">
        <label className={readout === 'absent' ? undefined : 'sr-only'} htmlFor="key-name">{t(locale, 'credentialName')}</label>
        <input id="key-name" aria-describedby="key-help" value={keyName} disabled={busy || !state.shallow.configured}
          onChange={event => setKeyName(event.target.value)} autoCapitalize="characters" spellCheck={false} />
        <label className="sr-only" htmlFor="embedding-key">{t(locale, 'embeddingKey')}</label>
        <div className="input-action"><input id="embedding-key" type="password" value={key} autoComplete="new-password" autoCorrect="off" autoCapitalize="none"
          spellCheck={false} placeholder={t(locale, 'pasteKey')} disabled={busy || !state.shallow.configured} onChange={event => setKey(event.target.value)} />
          <button disabled={busy || !key.trim() || !/^[A-Z][A-Z0-9_]*$/.test(keyName)} onClick={() => {
            const value = key; setKey('');
            void perform(async () => {
              try { await runAction({ kind: 'credential', key: keyName, value }); }
              catch (error) {
                // The submitted value is scrubbed out of the tool's words on the Rust side,
                // so a refusal can state its reason; only silence falls back to a generic line.
                throw String(error ?? '').trim() || t(locale, 'keySaveFailed');
              }
            }, t(locale, 'keySaved')).then(saved => { if (saved) setReplacing(false); });
          }}>{t(locale, 'save')}</button></div>
        <p id="key-help" className="muted setting-help">{t(locale, 'keyHelp')}</p>
      </div>}
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
        <LedgerSelect id="backend" value={library?.choices.backend ?? 'codex'} disabled={busy || !library} onChange={backend => {
          if (library) void perform(() => runAction({ kind: 'backend', library: library.name, backend: backend as Backend }), t(locale, 'backendSaved'));
        }} options={[{ value: 'codex', label: 'Codex' }, { value: 'claude-code', label: 'Claude Code' }, { value: 'api', label: t(locale, 'modelApi') }]} />
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
