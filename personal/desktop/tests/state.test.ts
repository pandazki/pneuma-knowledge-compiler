import test from 'node:test';
import assert from 'node:assert/strict';
import { consoleUrl, currentLibrary, deepLibrary, emptyState, health, syncSummary, type Snapshot, type ShallowLibrary } from '../src/lib/state.ts';

const library = (name: string, current = false): ShallowLibrary => ({
  name, tenant: `lib-${name}`, current,
  engine: { port: 18300, pid: 100, up: true, uptime: 60 },
  tcp_up: true, pid_alive: true, queue: null, key: null, engine_dir: `/synthetic/${name}/engine`,
  canonical_head: null, skill_fresh: null, last_used: null,
  steps: { infra: null, credentials: null, profile: null, skill: null, first_compile: null },
  choices: { backend: 'codex', semantic_retrieval: false, embedding: 'synthetic:embedding', unattended: true },
});
function ready(): Snapshot {
  const state = structuredClone(emptyState);
  state.shallow.configured = true;
  state.shallow.docker.reachable = true;
  state.shallow.services = Object.fromEntries(['postgres', 'qdrant', 'meili', 'rustfs'].map((name, i) => [name, { port: 18000 + i, up: true }]));
  state.shallow.libraries = [library('notes', true), library('work')];
  return state;
}
test('icon health degrades on either daemon, service, or engine failure without deep status', () => {
  assert.equal(health(emptyState.shallow), 'grey');
  const state = ready();
  assert.equal(health(state.shallow), 'green');
  state.shallow.libraries[1].engine.up = false;
  assert.equal(health(state.shallow), 'amber');
  state.shallow.libraries[1].engine.up = true;
  state.shallow.services.postgres.up = false;
  assert.equal(health(state.shallow), 'amber');
  state.shallow.docker.reachable = false;
  assert.equal(health(state.shallow), 'red');
});
test('missing probes and malformed configuration never imply healthy', () => {
  const state = ready(); delete state.shallow.services.meili;
  assert.equal(health(state.shallow), 'amber');
  const configured = ready(); configured.shallow.errors = ['Invalid library notes'];
  assert.equal(health(configured.shallow), 'amber');
});
test('library selection is explicit and never falls back to the first row', () => {
  const state = ready(); state.shallow.libraries[0].current = false;
  assert.equal(currentLibrary(state), undefined);
  state.shallow.libraries[1].current = true;
  assert.equal(currentLibrary(state)?.name, 'work');
});
test('deep overlays cannot be borrowed from a sibling engine or survive a down port', () => {
  const state = ready();
  state.deep.work = { ...state.shallow, libraries: [{ ...library('notes'), key: true }] };
  assert.equal(deepLibrary(state, state.shallow.libraries[0]), undefined);
  state.deep.notes = state.deep.work;
  assert.equal(deepLibrary(state, state.shallow.libraries[0])?.key, true);
  state.shallow.libraries[0].tcp_up = false;
  assert.equal(deepLibrary(state, state.shallow.libraries[0]), undefined);
});
test('console links encode each routing segment and preserve exact source span', () => {
  assert.equal(consoleUrl(18300, 'document', 'doc:a/b #1'), 'http://127.0.0.1:18300/#/library/document/doc%3Aa%2Fb%20%231');
  assert.equal(consoleUrl(18300, 'claim', 'doc-1', 'c:42'), 'http://127.0.0.1:18300/#/library/claim/doc-1/c%3A42');
  assert.equal(consoleUrl(18300, 'source', 'src:1', 7), 'http://127.0.0.1:18300/#/sources/source/src%3A1/7');
});

test('sync summary keeps held increments separate from queue and unknown observations', () => {
  assert.equal(syncSummary(null, ['/synthetic/momo']), 'watching 1 dirs · last sync never · held —');
  assert.equal(syncSummary({ last_run_at: null, last_result: null, watching: ['/synthetic/momo'],
    next_due: null, held: 2, running: false }, ['/synthetic/momo']), 'watching 1 dirs · last sync never · held 2');
});
