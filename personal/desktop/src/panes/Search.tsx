import { useEffect, useRef, useState, type ReactNode } from 'react';
import { openConsole, runAction, search, type Perform } from '../lib/commands';
import { consoleUrl, currentLibrary, type RecallResult, type Snapshot } from '../lib/state';

function ConsoleLink({ url, children, perform }: { url: string; children: ReactNode; perform: Perform }) {
  return <a href={url} onClick={event => { event.preventDefault(); void perform(() => openConsole(url)); }}>{children}</a>;
}
function Answer({ result, port, perform }: { result: RecallResult; port: number; perform: Perform }) {
  // Render plain text and narrowly parsed citation tokens; never engine-supplied HTML.
  const tokens = result.answer.split(/(\[cite:\s*[^\]]+\])/g);
  return <p className="answer">{tokens.map((token, i) => {
    const match = /^\[cite:\s*([^\s\]]+)(?:\s+¶(\d+)(?:-\d+)?)?\s*\]$/.exec(token);
    if (!match) return <span key={i}>{token}</span>;
    const ref = match[1];
    const claim = [...result.used_claims, ...(result.used_component_evidence ?? []).flatMap(e => e.claims)].find(c => c.anchor === ref);
    const docId = result.document_ids[claim?.document_path ?? ref];
    if (docId) return <ConsoleLink key={i} perform={perform} url={consoleUrl(port, claim ? 'claim' : 'document', docId, claim?.anchor)}>{token}</ConsoleLink>;
    const source = result.citation_handles[ref] ?? (match[2] ? ref : undefined);
    return source ? <ConsoleLink key={i} perform={perform} url={consoleUrl(port, 'source', source, match[2] ? Number(match[2]) : undefined)}>{token}</ConsoleLink> : <span key={i}>{token}</span>;
  })}</p>;
}
export default function Search({ state, busy, perform }: { state: Snapshot; busy: boolean; perform: Perform }) {
  const library = currentLibrary(state);
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<RecallResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    generation.current += 1; setResult(null); setError(null); setSearching(false);
    input.current?.focus();
    return () => { generation.current += 1; };
  }, [library?.name, library?.engine.port, library?.engine.up]);
  if (!library) return <div className="empty"><h1>Choose your library</h1><p>Select a current library in Settings to search its knowledge.</p></div>;
  if (!library.engine.up) return <div className="empty"><h1>{library.name} is resting</h1><p>Start your home to search this library.</p><button className="primary" disabled={busy} onClick={() => void perform(() => runAction({ kind: 'up' }), 'Home started')}>Start engine</button><p className="muted">Starts shared services and all library engines.</p></div>;
  const port = library.engine.port;
  const submit = async () => {
    if (!query.trim() || searching) return;
    const request = ++generation.current;
    setSearching(true); setError(null); setResult(null);
    try {
      const answer = await search(library.name, query);
      if (generation.current === request) setResult(answer);
    } catch (error) {
      if (generation.current === request) setError(String(error));
    } finally { if (generation.current === request) setSearching(false); }
  };
  return <>
    <div className="row search-heading"><h1>Search</h1><span className="muted">{library.name}</span></div>
    <form className="input-action" onSubmit={event => { event.preventDefault(); void submit(); }}>
      <label className="sr-only" htmlFor="search-query">Ask your library</label>
      <input id="search-query" ref={input} type="search" placeholder="Ask your library…" autoComplete="off" maxLength={8000} value={query} onChange={event => setQuery(event.target.value)} />
      <button disabled={!query.trim() || searching} type="submit" className="primary">Ask</button>
    </form>
    {searching && <p className="muted" role="status">Searching {library.name}…</p>}
    {error && <p role="alert" className="inline-error">{error}</p>}
    {!result && !searching && !error && <div className="search-prompt"><p>Find an answer in what you’ve collected.</p><span className="muted">Citations open the evidence in your console.</span></div>}
    {result && <section aria-label="Search answer">
      <Answer result={result} port={port} perform={perform} />
      <div className="section-label">Evidence</div>
      {[...result.used_claims, ...(result.used_component_evidence ?? []).flatMap(e => e.claims)].filter((claim, i, all) => all.findIndex(c => c.anchor === claim.anchor && c.document_path === claim.document_path) === i).map(claim => <article className="evidence" key={`${claim.document_path}:${claim.anchor}`}>
        {result.document_ids[claim.document_path]
          ? <ConsoleLink perform={perform} url={consoleUrl(port, 'claim', result.document_ids[claim.document_path], claim.anchor)}>{claim.document_path} · {claim.anchor} ↗</ConsoleLink>
          : <strong>{claim.document_path} · {claim.anchor}</strong>}
        <p>{claim.text}</p>
        {claim.citations.map(citation => <ConsoleLink key={`${citation.source_id}:${citation.block_start}`} perform={perform} url={consoleUrl(port, 'source', citation.source_id, citation.block_start)}>[cite: {citation.source_id} ¶{citation.block_start}-{citation.block_end}]</ConsoleLink>)}
      </article>)}
      {(result.documents_read ?? []).map(path => result.document_ids[path] && <p key={path}><ConsoleLink perform={perform} url={consoleUrl(port, 'document', result.document_ids[path])}>{path} ↗</ConsoleLink></p>)}
      {[...result.used_windows, ...(result.used_component_evidence ?? []).flatMap(e => e.windows)].filter((hit, i, all) => all.findIndex(h => h.source_id === hit.source_id && h.block_start === hit.block_start && h.block_end === hit.block_end) === i).map(hit => <article className="evidence" key={`${hit.source_id}:${hit.block_start}`}>
        <ConsoleLink perform={perform} url={consoleUrl(port, 'source', hit.source_id, hit.block_start)}>[cite: {hit.source_id} ¶{hit.block_start}-{hit.block_end}] ↗</ConsoleLink><p>{hit.text}</p>
      </article>)}
      {(result.used_episode_summaries ?? []).map(hit => <p key={`summary:${hit.source_id}:${hit.block_start}`}><ConsoleLink perform={perform} url={consoleUrl(port, 'source', hit.source_id, hit.block_start)}>Derived episode summary · {hit.source_id} ¶{hit.block_start}-{hit.block_end} ↗</ConsoleLink></p>)}
      {!result.used_claims.length && !result.used_windows.length && !result.documents_read?.length && <p className="muted">No direct evidence returned.</p>}
    </section>}
  </>;
}
