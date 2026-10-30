import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const web = new URL('../../../personal/src/pkc_personal/attention/web/', import.meta.url);
const boardSource = await readFile(new URL('board.js', web), 'utf8');
const visualsSource = await readFile(new URL('visuals.js', web), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
const state = () => ({ root: { items: [], used: 0, budget: 64 }, annotations: [], last_event_seq: 0 });
const frame = id => ({ id, at: '2026-01-01T00:00:00Z', state: state() });

function element() {
  return {
    innerHTML: '', textContent: '', hidden: false, dataset: {}, value: '',
    listeners: {}, setAttribute() {}, addEventListener(name, fn) { this.listeners[name] = fn; }, focus() {}, scrollIntoView() {},
    querySelectorAll: () => [], matches: () => false,
  };
}

async function board(settings = false) {
  let newest = 60, offline = false;
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  };
  const root = node('#board');
  root.querySelector = selector => selector === '#theme-note' ? null : node(selector);
  const document = {
    documentElement: { dataset: {} }, hidden: false, activeElement: null,
    querySelector: node, querySelectorAll: () => [], getElementById: id => node('#' + id),
  };
  const polls = [], paints = [], requests = [];
  const context = vm.createContext({
    document, location: { search: '?locale=en' + (settings ? '&settings=1' : '') }, navigator: { language: 'en' },
    URLSearchParams, console, FormData: class { has() { return true; } get() { return '14'; } }, window: { addEventListener() {} },
    setTimeout, clearTimeout, clearInterval() {},
    setInterval(fn, delay) { if (delay === 10000) polls.push(fn); return 1; },
    forms: [['yield', '份额', 'Give & take']], color: () => '#5a9b8e',
    mountVisual(host, ctx) { paints.push(ctx); },
    async fetch(url) {
      requests.push(url);
      if (offline) throw new Error('offline');
      let value;
      if (url.endsWith('/state')) value = {
        library: 'Synthetic', tenant: 'synthetic', state: state(), frames: [{ id: newest }],
        preferences: { board: 'yield', enabled: true }, status: {}, worker_alive: true,
      };
      else if (url.includes('/history')) {
        const before = Number(new URL(url, 'http://test').searchParams.get('before')) || newest + 1;
        value = Array.from({ length: Math.min(60, before - 1) }, (_, i) => frame(before - 1 - i));
      } else if (url.includes('/frames/')) value = frame(Number(url.split('/').at(-1)));
      else throw new Error('Unexpected request ' + url);
      return { ok: true, json: async () => value };
    },
  });
  vm.runInContext(boardSource.replace(/^import .*\n/, ''), context);
  await settle();
  return { document, root, node, paints, requests, newest: n => { newest = n; },
    offline: value => { offline = value; }, async poll() { polls[0](); await settle(); } };
}

test('polling bridges a hidden multi-page gap without losing the historical selection', async () => {
  const b = await board();
  b.node('#timeline').onchange({ target: { value: '29' } });
  await settle();
  assert.equal(b.paints.at(-1).selected, 30);
  b.newest(240);
  await b.poll();
  b.node('#latest').onclick();
  await settle();
  assert.deepEqual(Array.from(b.paints.at(-1).history, f => f.id),
    Array.from({ length: 240 }, (_, i) => i + 1));
  assert.equal(b.paints.at(-2).selected, 30);
  assert.ok(b.requests.includes('/home/attention/history?before=121'));
});

for (const editing of ['note', 'settings']) {
  test(`connection notice appears and clears while preserving ${editing} edits and focus`, async () => {
    const b = await board(editing === 'settings');
    const input = element();
    input.id = editing === 'note' ? 'note-text' : 'threshold';
    input.value = 'unsaved synthetic draft';
    input.matches = () => true;
    b.document.activeElement = input;
    if (editing === 'settings') {
      b.node('#preferences').querySelectorAll = () => [];
      b.node('#preferences').listeners.input({ currentTarget: b.node('#preferences') });
    }
    if (editing === 'settings') b.document.activeElement = null;
    const focused = b.document.activeElement;
    const html = b.root.innerHTML;
    assert.match(html, /id="connection-notice"/);
    const paintCount = b.paints.length;
    b.offline(true);
    await b.poll();
    assert.equal(b.node('#connection-notice').textContent, 'Connection lost; keeping this review.');
    assert.equal(b.node('#connection-notice').hidden, false);
    assert.equal(b.root.innerHTML, html);
    assert.equal(b.document.activeElement, focused);
    assert.equal(input.value, 'unsaved synthetic draft');
    b.offline(false);
    b.newest(61);
    await b.poll();
    assert.equal(b.node('#connection-notice').hidden, true);
    assert.equal(b.node('#connection-notice').textContent, '');
    assert.equal(b.paints.length, paintCount);
    assert.equal(b.document.activeElement, focused);
  });
}

test('new themes reserve colors belonging to identities outside the loaded history', () => {
  const bindings = { 'old-theme': '#5a9b8e' };
  const storage = new Map([['fold-colors-v2:synthetic', JSON.stringify(bindings)]]);
  const context = vm.createContext({
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    matchMedia: () => ({ matches: true }),
  });
  vm.runInContext(visualsSource.replace(/^import .*\n/, '').replace(/export /g, '') +
    '\nglobalThis.visuals = { mountVisual, color };', context);
  const host = element();
  const ctx = { tenant: 'synthetic', form: 'yield', state: state(), history: [], path: [], t: (cn, en) => en };
  // These synthetic IDs hash to the persisted palette slot.
  ctx.state.root.items = [{ id: 'new-0', title: 'New', share: 1 }];
  context.visuals.mountVisual(host, ctx, {});
  const newColor = context.visuals.color('new-0');
  assert.notEqual(newColor, bindings['old-theme']);
  ctx.history = [{ ...frame(1), state: { ...state(), root: { items: [{ id: 'old-theme', share: 1 }] } } }];
  context.visuals.mountVisual(host, ctx, {});
  assert.equal(context.visuals.color('old-theme'), bindings['old-theme']);
  assert.equal(context.visuals.color('new-0'), newColor);
  assert.deepEqual(JSON.parse(storage.get('fold-colors-v2:synthetic')), { ...bindings, 'new-0': newColor });
});
