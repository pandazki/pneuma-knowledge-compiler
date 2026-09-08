import test from 'node:test';
import assert from 'node:assert/strict';
import { searchResults } from '../src/lib/searchResults.ts';
import type { RecallResult } from '../src/lib/state.ts';

function result(): RecallResult {
  return {
    answer: '中文结论 [cite: c:42]，原文 [cite: S1 ¶7-9]。再次引用 [cite: c:42]',
    used_claims: [{ anchor: 'c:42', document_path: '知识编译/一次会议.md', text: '这是合成的测试结论。',
      citations: [{ source_id: 'source:一', block_start: 7, block_end: 9 }] }],
    used_windows: [{ source_id: 'source:一', block_start: 7, block_end: 9, text: '合成原始材料。' }],
    citation_handles: { S1: 'source:一' }, documents_read: [],
    document_ids: { '知识编译/一次会议.md': 'doc:one' },
  };
}

test('footnotes are stable, reuse destinations, and retain exact claim and source routing', () => {
  const view = searchResults(result(), 18300);
  const notes = view.answer.flatMap(part => part.citation ? [part.citation] : []);
  assert.deepEqual(notes.map(note => note.number), [1, 2, 1]);
  assert.equal(notes[0].url, 'http://127.0.0.1:18300/#/library/claim/doc%3Aone/c%3A42');
  assert.equal(notes[1].url, 'http://127.0.0.1:18300/#/sources/source/source%3A%E4%B8%80/7');
  assert.equal(view.entries[0].title, '知识编译/一次会议.md');
  assert.equal(view.entries[0].citation?.number, 1);
  assert.equal(view.entries[0].sources[0].number, 2);
  assert.equal(view.entries[1].citation?.number, 2);
  assert.match(view.entries[0].sources[0].label, /¶7-9$/);
});

test('component claims and windows are deduplicated without dropping their evidence', () => {
  const input = result();
  input.used_component_evidence = [{ claims: input.used_claims, windows: input.used_windows }];
  const before = structuredClone(input);
  assert.equal(searchResults(input, 18300).entries.length, 2);
  assert.deepEqual(input, before);
});

test('unresolved citations and engine-supplied markup stay plain text', () => {
  const input = result();
  input.answer = '<img src=x onerror=alert(1)> [cite: missing] [cite: source:direct ¶3-4]';
  const answer = searchResults(input, 18300).answer;
  assert.equal(answer[0].text, '<img src=x onerror=alert(1)> ');
  assert.equal(answer[0].citation, undefined);
  assert.equal(answer[1].text, '[cite: missing]');
  assert.equal(answer[1].citation, undefined);
  assert.equal(answer[3].citation?.url, 'http://127.0.0.1:18300/#/sources/source/source%3Adirect/3');
});

test('document-only and derived-summary evidence stays reachable and explicitly marked', () => {
  const input = result();
  input.used_claims = []; input.used_windows = [];
  input.documents_read = ['知识编译/一次会议.md', '知识编译/一次会议.md', 'missing.md'];
  input.used_episode_summaries = [{ source_id: 'summary-source', block_start: 2, block_end: 8, text: 'Derived text' }];
  const entries = searchResults(input, 18400).entries;
  assert.equal(entries.length, 2);
  assert.equal(entries[0].citation?.url, 'http://127.0.0.1:18400/#/library/document/doc%3Aone');
  assert.equal(entries[1].derived, true);
  assert.equal(entries[1].text, undefined);
  assert.equal(entries[1].citation?.url, 'http://127.0.0.1:18400/#/sources/source/summary-source/2');
});
