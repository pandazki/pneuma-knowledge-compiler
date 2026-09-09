import { useEffect, useRef, useState } from 'react';
import { openConsole, runAction, search, type Perform } from '../lib/commands';
import { t, textLanguage, type Locale } from '../lib/i18n';
import { searchResults, type Footnote } from '../lib/searchResults';
import { consolePreferences, currentLibrary, type RecallResult, type Snapshot } from '../lib/state';

function Citation({ note, perform, locale }: { note: Footnote; perform: Perform; locale: Locale }) {
  return <sup><a href={note.url} data-result-link title={note.label}
    aria-label={`${t(locale, 'citation', { number: note.number })}: ${note.label}`}
    onClick={event => { event.preventDefault(); void perform(() => openConsole(note.url)); }}>{note.number}</a></sup>;
}

/** Every search is a model call, so typing must not fire one per keystroke: the request
 * waits for the typing to pause, and Enter (`submitted`) asks for it now. */
export const SEARCH_IDLE_MS = 900;

export default function Search({ state, busy, perform, query, composing, locale, submitted }: {
  state: Snapshot; busy: boolean; perform: Perform; query: string; composing: boolean; locale: Locale; submitted: number;
}) {
  const library = currentLibrary(state);
  const [reply, setReply] = useState<{ key: string; result?: RecallResult; error?: string } | null>(null);
  const generation = useRef(0);
  const lastSubmitted = useRef(submitted);
  const [inFlight, setInFlight] = useState<string | null>(null);
  const requestKey = JSON.stringify([library?.name, library?.engine.port, library?.engine.up, query.trim()]);
  useEffect(() => {
    const request = ++generation.current;
    if (!library?.engine.up || !query.trim() || composing) return;
    const now = submitted !== lastSubmitted.current;
    lastSubmitted.current = submitted;
    const timer = setTimeout(() => {
      setInFlight(requestKey);
      void search(library.name, query).then(result => {
        if (generation.current === request) setReply({ key: requestKey, result });
      }).catch(error => {
        if (generation.current === request) setReply({ key: requestKey, error: String(error) });
      });
    }, now ? 0 : SEARCH_IDLE_MS);
    return () => { clearTimeout(timer); generation.current += 1; };
  }, [requestKey, composing, submitted]);

  if (!library) return <p className="muted">{t(locale, 'chooseHelp')}</p>;
  if (!library.engine.up) return <p className="engine-off">{t(locale, 'engineOff')} <button className="primary" disabled={busy}
    onClick={() => void perform(() => runAction({ kind: 'up' }), t(locale, 'started'))}>{t(locale, 'startIt')}</button></p>;
  if (!query.trim() || composing) return <p className="muted">{t(locale, 'searchHint')}</p>;
  const current = reply?.key === requestKey ? reply : null;
  if (!current) return <p className="muted" role="status">{inFlight === requestKey ? t(locale, 'searching', { name: library.name }) : t(locale, 'waitToSearch')}</p>;
  if (current.error) return <p className="inline-error" role="alert">{current.error}</p>;
  if (!current.result) return null;
  const view = searchResults(current.result, library.engine.port, consolePreferences(locale));
  return <section className="search-results" aria-label={t(locale, 'answer')}>
    <p className="answer" lang={textLanguage(current.result.answer)}>{view.answer.map((part, i) => part.citation
      ? <Citation key={i} note={part.citation} perform={perform} locale={locale} /> : <span key={i}>{part.text}</span>)}</p>
    {view.entries.length > 0 && <h2 className="section-label small-caps">{t(locale, 'evidence')}</h2>}
    <ol className="result-entries">{view.entries.map(entry => <li className="result-entry" key={entry.key}>
      {entry.text && <p lang={textLanguage(entry.text)}>{entry.text}</p>}
      <div className="source-line" lang={textLanguage(entry.title)}>
        {entry.citation && <Citation note={entry.citation} perform={perform} locale={locale} />}
        <span className="source-title">{entry.derived ? `${t(locale, 'derivedSummary')} · ` : ''}{entry.title}</span>
        {entry.sources.map((source, i) => <Citation key={`${source.url}:${i}`} note={source} perform={perform} locale={locale} />)}
      </div>
    </li>)}</ol>
    {!view.entries.length && <p className="muted">{t(locale, 'noEvidence')}</p>}
  </section>;
}
