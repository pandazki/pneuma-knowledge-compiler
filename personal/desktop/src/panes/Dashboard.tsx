import { runAction, type Perform } from '../lib/commands';
import { deepLibrary, health, healthLabels, stepLabels, syncSummary, timeLabel, uptime, type Known, type Snapshot } from '../lib/state';

export function Dot({ up }: { up: Known }) {
  return <span className={`dot ${up === null ? 'grey' : up ? 'green' : 'red'}`} aria-hidden="true" />;
}
function observation(value: Known, yes: string, no: string) { return value === null || value === undefined ? 'Unknown' : value ? yes : no; }
export default function Dashboard({ state, busy, perform, now }: { state: Snapshot; busy: boolean; perform: Perform; now: number }) {
  const { shallow } = state;
  if (!shallow.configured) return <div className="empty">
    <span className="book-mark" aria-hidden="true">▤</span><h1>A place for what you know</h1>
    <p>Set up your personal knowledge home in a terminal. Your libraries will appear here.</p>
    <code>pkchome setup</code><p className="muted">The tray will notice when setup finishes.</p>
  </div>;
  return <>
    <section className="system-health" aria-label="Machine health">
      <div className="row"><h1><span className={`dot ${health(shallow)}`} />{healthLabels[health(shallow)]}</h1><span className="muted">Docker {shallow.docker.reachable ? 'up' : 'down'}</span></div>
      <div className="services">{Object.entries(shallow.services).map(([name, service]) =>
        <div key={name} title={`${name}: ${observation(service.up, 'up', 'down')} · port ${service.port ?? 'unconfigured'}`}>
          <Dot up={service.up} /><span>{({ postgres: 'Postgres', qdrant: 'Qdrant', meili: 'Meili', rustfs: 'RustFS' } as Record<string, string>)[name] ?? name}</span>
        </div>)}</div>
      <div className="actions">
        <button disabled={busy} onClick={() => void perform(() => runAction({ kind: 'up' }), 'Home started')}>Start</button>
        <button disabled={busy} onClick={() => void perform(() => runAction({ kind: 'down' }), 'Home stopped')}>Stop</button>
        <button disabled={busy} onClick={() => void perform(() => runAction({ kind: 'restart' }), 'Home restarted')}>Restart</button>
        <span className="muted">All libraries</span>
      </div>
    </section>
    {shallow.errors.map(error => <p className="inline-error" key={error}>{error}</p>)}
    <div className="section-label">Libraries <span>{shallow.libraries.length}</span></div>
    {!shallow.libraries.length && <p className="muted">Create a library with <code>pkchome library create notes</code>.</p>}
    {shallow.libraries.map(library => {
      const deep = deepLibrary(state, library);
      const queue = deep?.queue;
      const seconds = library.engine.uptime == null ? null : library.engine.uptime + Math.max(0, now - state.fetched_at) / 1000;
      const steps = deep?.steps ?? library.steps;
      return <section className="library-card" key={library.name} aria-label={`${library.name} library`}>
        <div className="row"><h2>{library.name}</h2>{library.current && <span className="badge">Current</span>}</div>
        <div className="row engine-line"><span><Dot up={library.engine.up} />Engine {library.engine.up ? 'up' : 'down'}</span>
          <span className="muted">{library.engine.up ? uptime(seconds) : `Port ${library.engine.port}`}</span></div>
        {!library.engine.up && library.pid_alive && <p className="muted">Process is running; waiting for its port.</p>}
        <dl className="metrics">
          <div><dt>Pending</dt><dd>{queue?.pending ?? '—'}</dd></div>
          <div><dt>Failed</dt><dd className={queue?.failed ? 'failure' : ''}>{queue?.failed ?? '—'}</dd></div>
          <div><dt>Last compile</dt><dd>{queue ? queue.last_compile_at ? timeLabel(queue.last_compile_at) : 'None yet' : 'Unknown'}</dd></div>
        </dl>
        <p className="muted compact">{syncSummary(deep?.sync, library.watching)}</p>
        {!!deep?.sync?.last_result?.rewritten && <p className="inline-error">{deep.sync.last_result.rewritten} rewritten sessions need review.</p>}
        {!!deep?.sync?.last_result?.skipped && <p className="muted compact">{deep.sync.last_result.skipped} skipped on the last pass. Run a dry sync in the terminal for details.</p>}
        <div className="actions"><button disabled={busy || !library.engine.up || deep?.sync?.running === true} onClick={() => void perform(
          () => runAction({ kind: 'sync', library: library.name }), 'Sync requested')}>{deep?.sync?.running ? 'Syncing…' : 'Sync now'}</button></div>
        <div className="row details"><span>Key <strong>{observation(deep?.key ?? null, 'present', 'absent')}</strong></span>
          <span>Skill <strong>{observation(deep?.skill_fresh ?? null, 'fresh', 'drifted')}</strong></span></div>
        <ol className="steps" aria-label="Setup progress">{stepLabels.map(([key, label], i) => <li key={key} title={steps[key] ? `${label}: ${timeLabel(steps[key])}` : `${label}: not completed`}>
          <span className={steps[key] ? 'complete' : ''} aria-hidden="true">{steps[key] ? '✓' : i + 1}</span>
          <span>{label}</span><span className="sr-only">: {steps[key] ? 'complete' : 'not completed'}</span>
        </li>)}</ol>
        {!deep && <p className="muted compact">{library.engine.up ? 'Detailed health is unavailable.' : 'Detailed health returns when the engine starts.'}</p>}
        {!!queue?.failed && <span className="disabled-hint" tabIndex={0} title="Retry failed jobs is not available in this release. Use the console to inspect failures.">
          <button disabled>Retry failed jobs</button><span className="muted"> Coming later</span>
        </span>}
      </section>;
    })}
  </>;
}
