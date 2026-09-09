import { openConsole, runAction, type Perform } from '../lib/commands';
import { t, textLanguage, type Locale, type Message } from '../lib/i18n';
import { orderedLibraries, readoutRows, relativeTime } from '../lib/readouts';
import { consoleHome, consolePreferences, deepLibrary, health, type Snapshot, type Steps } from '../lib/state';
import { Leader } from './Ledger';

const steps: [keyof Steps, Message][] = [
  ['infra', 'infra'], ['credentials', 'credentials'], ['profile', 'profile'],
  ['skill', 'skill'], ['first_compile', 'firstCompile'],
];
const healthMessages = { grey: 'healthGrey', green: 'healthGreen', amber: 'healthAmber', red: 'healthRed' } as const;

export default function Dashboard({ state, busy, perform, now, locale }: {
  state: Snapshot; busy: boolean; perform: Perform; now: number; locale: Locale;
}) {
  const { shallow } = state;
  if (!shallow.configured) return <section className="empty-home">
    <h1>{t(locale, 'noLibrary')}</h1>
    <p className="muted">{t(locale, 'pasteHint')}</p>
    <p className="setup-prompt">{t(locale, 'setupPrompt')}</p>
    {shallow.errors.map(error => <p className="inline-error" key={error}>{error}</p>)}
  </section>;

  const libraries = orderedLibraries(state);
  const primaryStart = libraries.find(library => !library.engine.up)?.name;
  const machine = [['docker', 'Docker'], ['postgres', 'Postgres'], ['qdrant', 'Qdrant'], ['meili', 'Meili'], ['rustfs', 'RustFS']];
  return <div className="dashboard">
    {shallow.errors.map(error => <p className="inline-error" key={error}>{error}</p>)}
    {!libraries.length && <p className="setup-prompt">{t(locale, 'emptyLibraries')}</p>}
    {libraries.map((library, index) => {
      const deep = deepLibrary(state, library);
      const marks = deep?.steps ?? library.steps;
      const currentStep = steps.find(([key]) => !marks[key])?.[0];
      const sync = deep?.sync ?? library.sync;
      const status = health({ ...shallow, libraries: [library] });
      return <section className="library" key={library.name} aria-label={library.name}>
        <div className="running-head">
          <h1 lang={textLanguage(library.name)} title={library.name}>
            <span className={`health-dot ${status}`} role="img" aria-label={t(locale, healthMessages[status])} />
            <span className="library-name">{library.name}</span>
            {library.current && <span className="sr-only"> · {t(locale, 'current')}</span>}
          </h1>
          {index === 0 && <div className="head-actions" title={t(locale, 'allLibraries')}>
            {!library.engine.up && <button className="primary" disabled={busy} onClick={() => void perform(() => runAction({ kind: 'up' }), t(locale, 'started'))}>{t(locale, 'start')}</button>}
            {library.engine.up && <button disabled={busy} onClick={() => void perform(() => runAction({ kind: 'down' }), t(locale, 'stopped'))}>{t(locale, 'stop')}</button>}
            <button disabled={busy} onClick={() => void perform(() => runAction({ kind: 'restart' }), t(locale, 'restarted'))}>{t(locale, 'restart')}</button>
          </div>}
        </div>
        <dl className="ledger">{readoutRows(state, library, now, locale).map(row =>
          <div className="readout" key={row.id}>
            <dt className="small-caps">{t(locale, row.id)}</dt><Leader /><dd title={row.title}>{row.value}</dd>
            {row.note && <dd className="readout-note" lang={textLanguage(row.note)}>{row.note}</dd>}
          </div>)}</dl>
        <ol className="setup-steps small-caps" aria-label={t(locale, 'setup')}>
          {steps.map(([key, label]) => <li key={key} className={marks[key] ? 'complete' : 'incomplete'} aria-current={key === currentStep ? 'step' : undefined}
            title={`${t(locale, label)}: ${typeof marks[key] === 'string' ? relativeTime(marks[key], now, locale) : t(locale, marks[key] ? 'complete' : 'incomplete')}`}>
            <span className="step-word">{t(locale, label)}</span><span className="sr-only">: {t(locale, marks[key] ? 'complete' : 'incomplete')}</span>
          </li>)}
        </ol>
        <div className="library-actions">
          <button disabled={busy || !library.engine.up || sync?.running === true} onClick={() => void perform(
            () => runAction({ kind: 'sync', library: library.name }), t(locale, 'synced'))}>{t(locale, sync?.running ? 'syncing' : 'syncNow')}</button>
          <button disabled={busy || !library.engine.up} onClick={() => void perform(() => openConsole(consoleHome(library.engine.port, consolePreferences(locale))))}>{t(locale, 'openConsole')}</button>
          {index > 0 && !library.engine.up && <button className={library.name === primaryStart ? 'primary' : undefined} disabled={busy} title={t(locale, 'allLibraries')} onClick={() => void perform(() => runAction({ kind: 'up' }), t(locale, 'started'))}>{t(locale, 'start')}</button>}
        </div>
        {!deep && <p className="muted library-note">{t(locale, library.engine.up ? 'detailedUnavailable' : 'detailedOffline')}</p>}
        {!!sync?.last_result?.rewritten && <p className="muted library-note">{t(locale, 'rewritten', { count: sync.last_result.rewritten })}</p>}
        {!!sync?.last_result?.skipped && <p className="muted library-note">{t(locale, 'skipped', { count: sync.last_result.skipped })}</p>}
      </section>;
    })}
    <div className="machine-line" aria-label={t(locale, 'machine')}>
      {machine.map(([key, label]) => {
        const up = key === 'docker' ? shallow.docker.reachable : shallow.services[key]?.up;
        const status = t(locale, up == null ? 'unknown' : up ? 'serviceUp' : 'serviceDown');
        return <span key={key} title={`${label}: ${status}`}>
          {up !== true && <span className="machine-mark" aria-hidden="true">{up === false ? '•' : '◦'}</span>}
          {label}<span className="sr-only">: {status}</span>
        </span>;
      })}
    </div>
  </div>;
}
