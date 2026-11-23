import { afterEach, expect, test } from 'vitest';
import { selectHost } from './selectHost.js';
import { workingHost } from './workingHost.js';

afterEach(() => { selectHost.set(null); workingHost.set(null); });

test('takes a select ask only as reference strings and a number, blank references dropped', () => {
  expect(selectHost.get()).toBeNull();
  selectHost.set({ references: ['doc#plate/face 3', '  ', 7, 'doc#plate'], nonce: 2, more: true });
  expect(selectHost.get()).toEqual({ references: ['doc#plate/face 3', 'doc#plate'], nonce: 2 });
  for (const asked of [{ references: [], nonce: 3 }, { references: ['  '], nonce: 3 }, { references: 'doc#plate', nonce: 3 },
    { references: ['doc#plate'] }, { references: ['doc#plate'], nonce: '3' }, null, undefined]) {
    selectHost.set({ references: ['doc#plate'], nonce: 2 });
    selectHost.set(asked);
    expect(selectHost.get()).toBeNull();
  }
});

test('tells its listeners once per ask, and its takers what each ask found and lost', () => {
  let heard = 0;
  const taken: unknown[] = [];
  const leave = selectHost.subscribe(() => { heard += 1; });
  const leaveTaken = selectHost.subscribeTaken(answer => { taken.push(answer); });
  selectHost.set({ references: ['doc#plate'], nonce: 3 });
  selectHost.set({ references: ['doc#plate'], nonce: 3 });
  selectHost.set({ references: ['doc#plate', 'doc#arm'], nonce: 4 });
  selectHost.take(4, 1, 1);
  expect([heard, taken]).toEqual([2, [{ nonce: 4, found: 1, missing: 1 }]]);
  leave();
  leaveTaken();
  selectHost.take(5, 0, 0);
  expect(taken.length).toBe(1);
});

test('a turn runs only while the host says { working: true }, and each start is counted once', () => {
  let heard = 0;
  const leave = workingHost.subscribe(() => { heard += 1; });
  const before = workingHost.turns();
  for (const said of [true, 'working', { working: 'yes' }, null]) {
    workingHost.set(said);
    expect(workingHost.get()).toBe(false);
  }
  workingHost.set({ working: true });
  workingHost.set({ working: true, label: 'again' });
  expect([workingHost.get(), workingHost.turns() - before, heard]).toEqual([true, 1, 1]);
  workingHost.set({ working: false });
  workingHost.set({ working: true });
  expect([workingHost.get(), workingHost.turns() - before, heard]).toEqual([true, 2, 3]);
  leave();
});
