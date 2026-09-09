import test from 'node:test';
import assert from 'node:assert/strict';
import { checkedTime, orderedLibraries, readoutRows, relativeTime, shortUptime } from '../src/lib/readouts.ts';
import { resolveLocale, t, textLanguage } from '../src/lib/i18n.ts';
import { emptyState, type ShallowLibrary, type Snapshot } from '../src/lib/state.ts';

const now = Date.parse('2026-09-08T09:37:00Z');
const library = (name: string, current = false): ShallowLibrary => ({
  name, current, tenant: `synthetic-${name}`, engine: { pid: 1, up: true, port: 18300, uptime: 1200 },
  tcp_up: true, pid_alive: true, queue: null, key: null, skill_fresh: null,
  engine_dir: '/synthetic/engine', canonical_head: null, last_used: null,
  steps: { infra: true, credentials: null, profile: null, skill: null, first_compile: null },
  choices: { backend: 'codex', semantic_retrieval: false, embedding: 'synthetic:embedding', unattended: true },
  watching: ['/synthetic/one', '/synthetic/two', '/synthetic/three'],
});
function fixture(): Snapshot {
  const state = structuredClone(emptyState);
  state.fetched_at = now - 60_000;
  state.shallow.configured = true;
  state.shallow.libraries = [library('工作札记'), library('知识编译与长期项目记录：中文标题与 English 共排', true)];
  const current = state.shallow.libraries[1];
  state.deep[current.name] = { ...state.shallow, libraries: [{ ...current, key: true, skill_fresh: false,
    queue: { pending: 0, failed: 40, succeeded: 155, failed_by_kind: { index: 2, evolve: 38, compile: 0 }, last_compile_at: '2026-09-08T09:32:00Z' },
    sync: { watching: current.watching!, held: 177, running: false, last_run_at: '2026-09-08T09:32:00Z', last_result: null, next_due: null },
  }] };
  return state;
}

test('compact uptime handles minute, hour and day boundaries without guessing missing observations', () => {
  assert.deepEqual([null, NaN, Infinity, -1, 0, 59, 60, 3599, 3600, 86400].map(shortUptime),
    ['—', '—', '—', '—', '<1m', '<1m', '1m', '59m', '1h 0m', '1d 0h']);
});

test('relative times are deterministic, bilingual, and tolerate future timestamps and invalid dates', () => {
  const stamp = (seconds: number) => new Date(now - seconds * 1000).toISOString();
  assert.deepEqual([-60, 0, 59, 60, 3599, 3600, 86400].map(seconds => relativeTime(stamp(seconds), now, 'en')),
    ['just now', 'just now', 'just now', '1 min ago', '59 min ago', '1 hr ago', '1d ago']);
  assert.equal(relativeTime(stamp(300), now, 'zh-CN'), '5 分钟前');
  assert.equal(relativeTime(stamp(7200), now, 'zh-CN'), '2 小时前');
  assert.equal(relativeTime(stamp(172800), now, 'zh-CN'), '2 天前');
  for (const invalid of [null, undefined, '', 'not-a-date']) assert.equal(relativeTime(invalid, now, 'en'), '—');
  assert.equal(relativeTime(stamp(60), NaN, 'zh-CN'), '—');
  assert.match(checkedTime(now, 'en'), /^\d{2}:\d{2}$/);
  assert.match(checkedTime(now, 'zh-CN'), /^\d{2}:\d{2}$/);
});

test('readout grammar distinguishes successful work, failures by kind, and held sync increments', () => {
  const state = fixture();
  const rows = readoutRows(state, state.shallow.libraries[1], now, 'en');
  assert.deepEqual(rows.map(r => [r.id, r.value]), [
    ['engine', 'up · 21m'], ['queue', '155 done · 0 pending · 40 failed'], ['lastCompile', '5 min ago'],
    ['sync', 'watching 3 · held 177 · 5 min ago'], ['key', 'present'], ['skill', 'stale'],
  ]);
  assert.equal(rows[1].note, 'evolve 38 · index 2');
  assert.equal(rows[2].title, '2026-09-08T09:32:00Z');
  const zh = readoutRows(state, state.shallow.libraries[1], now, 'zh-CN');
  assert.equal(zh[1].value, '155 完成 · 0 待处理 · 40 失败');
  assert.equal(zh[3].value, '监看 3 · 暂存 177 · 5 分钟前');
});

test('offline readouts keep the shallow probe without borrowing cached deep data or a sibling library', () => {
  const state = fixture();
  const current = state.shallow.libraries[1];
  current.engine.up = false; current.tcp_up = false; current.key = true;
  const rows = readoutRows(state, current, now, 'en');
  assert.equal(rows[0].value, 'off');
  assert.equal(rows[0].note, 'Process running; waiting for its port.');
  assert.equal(rows[1].value, '—');
  assert.equal(rows[2].value, '—');
  assert.equal(rows[3].value, '—');
  assert.equal(rows[4].value, 'present');
  assert.equal(rows[5].value, '—');
  assert.equal(readoutRows(state, state.shallow.libraries[0], now, 'en')[1].value, '—');
});

test('older queue observations collapse to one dash; known zero counts and no compile remain meaningful', () => {
  const state = fixture();
  const current = state.shallow.libraries[1];
  state.deep[current.name].libraries[0].queue = { pending: 0, failed: 0, last_compile_at: null };
  const rows = readoutRows(state, current, now, 'en');
  assert.equal(rows[1].value, '—');
  assert.equal(rows[2].value, 'None yet');
  assert.equal(rows[1].note, undefined);
  state.deep[current.name].libraries[0].queue!.succeeded = 0;
  assert.equal(readoutRows(state, current, now, 'en')[1].value, '0 done · 0 pending · 0 failed');
});

test('every unknown ledger readout is exactly one em dash in both languages', () => {
  for (const locale of ['en', 'zh-CN'] as const) {
    const state = fixture();
    state.deep = {};
    const current = state.shallow.libraries[1];
    current.engine.uptime = null;
    current.sync = null;
    const before = structuredClone(state);
    assert.deepEqual(readoutRows(state, current, now, locale).map(row => row.value), Array(6).fill('—'));
    assert.deepEqual(state, before);
  }
});

test('partial or invalid queue counters never attach a label to an unknown value', () => {
  for (const locale of ['en', 'zh-CN'] as const) {
    for (const counter of ['succeeded', 'pending', 'failed']) {
      for (const missing of [null, undefined, NaN, Infinity, -1]) {
        const state = fixture();
        const current = state.shallow.libraries[1];
        Object.assign(state.deep[current.name].libraries[0].queue!, { [counter]: missing });
        const row = readoutRows(state, current, now, locale)[1];
        assert.equal(row.value, '—', `${locale}: ${counter}=${missing}`);
        assert.equal(row.note, undefined);
      }
    }
  }
});

test('sync readouts distinguish missing observations from known zero, never run, and running states', () => {
  for (const locale of ['en', 'zh-CN'] as const) {
    const state = fixture();
    const current = state.shallow.libraries[1];
    const deep = state.deep[current.name].libraries[0];
    for (const missing of [null, undefined]) {
      deep.sync = missing;
      assert.equal(readoutRows(state, current, now, locale)[3].value, '—');
    }
    deep.sync = { watching: [], held: 0, running: false, last_run_at: null, last_result: null, next_due: null };
    assert.equal(readoutRows(state, current, now, locale)[3].value,
      locale === 'en' ? 'watching 0 · held 0 · never' : '监看 0 · 暂存 0 · 尚未同步');
    deep.sync.running = true;
    assert.equal(readoutRows(state, current, now, locale)[3].value,
      locale === 'en' ? 'watching 0 · held 0 · Syncing…' : '监看 0 · 暂存 0 · 同步中…');
    deep.sync.running = false;
    deep.sync.last_run_at = 'not-a-date';
    assert.equal(readoutRows(state, current, now, locale)[3].value, '—');
    deep.sync.last_run_at = null;
    for (const missing of [null, undefined, NaN, Infinity]) {
      Object.assign(deep.sync, { held: missing });
      assert.equal(readoutRows(state, current, now, locale)[3].value, '—');
    }
  }
});

test('current library sorts first without mutating the wire snapshot or shortening mixed Chinese titles', () => {
  const state = fixture();
  const original = structuredClone(state);
  const ordered = orderedLibraries(state);
  assert.equal(ordered[0].name, '知识编译与长期项目记录：中文标题与 English 共排');
  assert.equal(ordered[1].name, '工作札记');
  assert.deepEqual(state, original);
  assert.equal(textLanguage(ordered[0].name), 'zh-CN');
  assert.equal(textLanguage('Field notes'), undefined);
});

test('locale follows the system until explicitly selected and translations interpolate user text literally', () => {
  assert.equal(resolveLocale(null, ['zh-Hans-CN', 'en']), 'zh-CN');
  assert.equal(resolveLocale('en', ['zh-CN']), 'en');
  assert.equal(resolveLocale('zh-CN', ['en']), 'zh-CN');
  assert.equal(resolveLocale('system', ['en', 'zh-CN']), 'en');
  assert.equal(resolveLocale(null, []), 'en');
  assert.equal(t('zh-CN', 'switched', { name: '札记 {private}' }), '已切换到 札记 {private}');
  assert.equal(t('zh-CN', 'skill'), 'skill 包');
  assert.equal(t('en', 'skill'), 'Skill');
});
