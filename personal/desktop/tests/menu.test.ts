import test from 'node:test';
import assert from 'node:assert/strict';
import { edgeOption, matchOption, placeMenu, stepOption, type MenuOption } from '../src/lib/menu.ts';

const options: MenuOption[] = [
  { value: '', label: 'Choose a library', disabled: true },
  { value: 'notes', label: 'notes' },
  { value: 'work', label: 'work' },
  { value: 'nb', label: 'Notebook' },
];

test('the list opens below when there is room, flips above when the panel edge is near, and scrolls when neither fits', () => {
  assert.deepEqual(placeMenu({ top: 100, bottom: 132 }, 120, 600), { side: 'below', top: 136, maxHeight: 456 });
  const flipped = placeMenu({ top: 500, bottom: 532 }, 120, 600);
  assert.equal(flipped.side, 'above');
  assert.equal(flipped.top, 500 - 4 - 120);
  const cramped = placeMenu({ top: 40, bottom: 72 }, 400, 120);
  assert.equal(cramped.side, 'below');
  assert.equal(cramped.maxHeight, 120 - 72 - 4 - 8);
});

test('arrow keys skip disabled options and wrap at both ends', () => {
  assert.equal(stepOption(options, -1, 1), 1);
  assert.equal(stepOption(options, 1, 1), 2);
  assert.equal(stepOption(options, 3, 1), 1);
  assert.equal(stepOption(options, 1, -1), 3);
  assert.equal(edgeOption(options, 'first'), 1);
  assert.equal(edgeOption(options, 'last'), 3);
  assert.equal(stepOption([{ value: 'x', label: 'x', disabled: true }], -1, 1), -1);
  assert.equal(stepOption([], -1, 1), -1);
});

test('type-ahead finds the next enabled label after the highlight, case-insensitively', () => {
  assert.equal(matchOption(options, 'n', -1), 1);
  assert.equal(matchOption(options, 'n', 1), 3);
  assert.equal(matchOption(options, 'NO', 0), 1);
  assert.equal(matchOption(options, 'ch', -1), -1);
  assert.equal(matchOption(options, '', 0), -1);
});
