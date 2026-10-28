import { afterEach, expect, test } from 'vitest';
import { editLayoutHost } from './editLayoutHost.js';

afterEach(() => {
  editLayoutHost.set(false);
  editLayoutHost.reportEditState(null);
});

test('a page lays out its own part until the host says it does', () => {
  expect(editLayoutHost.get()).toBe(false);
  editLayoutHost.set(true);
  expect(editLayoutHost.get()).toBe(true);
});

test('tells its listeners once per change, and not after they leave', () => {
  let calls = 0;
  const leave = editLayoutHost.subscribe(() => { calls += 1; });
  editLayoutHost.set(true);
  editLayoutHost.set(true);
  expect(calls).toBe(1);
  leave();
  editLayoutHost.set(false);
  expect(calls).toBe(1);
});

test('nothing is editable until the part on screen says so, and nothing once it goes', () => {
  expect(editLayoutHost.editState()).toEqual({ editable: false, busy: false });
  editLayoutHost.reportEditState({ editable: true, busy: true });
  expect(editLayoutHost.editState()).toEqual({ editable: true, busy: true });
  // The part leaves the screen (another file, the home): no layouts to switch, nothing holding them.
  editLayoutHost.reportEditState(null);
  expect(editLayoutHost.editState()).toEqual({ editable: false, busy: false });
});

test('tells what the part allows once per change, apart from who lays it out, and not after its listeners leave', () => {
  let heard = 0;
  let laidOut = 0;
  const leave = editLayoutHost.subscribeEditState(() => { heard += 1; });
  const leaveLayout = editLayoutHost.subscribe(() => { laidOut += 1; });
  editLayoutHost.reportEditState({ editable: true, busy: false });
  editLayoutHost.reportEditState({ editable: true, busy: false });
  editLayoutHost.reportEditState({ editable: true, busy: true });
  editLayoutHost.set(true);
  expect([heard, laidOut]).toEqual([2, 1]);
  leave();
  leaveLayout();
  editLayoutHost.reportEditState(null);
  expect(heard).toBe(2);
});

test('a page asks its host for a layout only where the host takes the ask, and says whether it did', () => {
  expect(editLayoutHost.request('manual')).toBe(false);
  const asked: string[] = [];
  const leave = editLayoutHost.setRequester(layout => { asked.push(layout); });
  expect(editLayoutHost.request('manual')).toBe(true);
  expect(editLayoutHost.request('ai')).toBe(true);
  expect(asked).toEqual(['manual', 'ai']);
  // The page's host gone: nothing is asked.
  leave();
  expect(editLayoutHost.request('ai')).toBe(false);
  expect(asked).toEqual(['manual', 'ai']);
});

test('a page hears when its host refuses the layout it asked for, and only then', async () => {
  const refused: string[] = [];
  let answer: Promise<unknown> = Promise.resolve({});
  const leave = editLayoutHost.setRequester(() => answer);
  expect(editLayoutHost.request('manual', { refused: () => { refused.push('taken'); } })).toBe(true);
  answer = Promise.reject(new Error('Finish or cancel the command first'));
  expect(editLayoutHost.request('manual', { refused: () => { refused.push('refused'); } })).toBe(true);
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(refused).toEqual(['refused']);
  // Asked without a way to hear back, a refusal is dropped quietly.
  answer = Promise.reject(new Error('Busy'));
  expect(editLayoutHost.request('ai')).toBe(true);
  await new Promise(resolve => setTimeout(resolve, 0));
  leave();
});

test('counts the builds the part on screen saw end, for the host to list its parts anew, whatever the part says after', () => {
  let heard = 0;
  const leave = editLayoutHost.subscribeEditState(() => { heard += 1; });
  const before = editLayoutHost.builds();
  editLayoutHost.reportBuilt();
  expect(editLayoutHost.builds()).toBe(before + 1);
  expect(heard).toBe(1);
  // The count only grows: the part leaving the screen keeps it, so a host never hears an old count again.
  editLayoutHost.reportEditState({ editable: true, busy: false });
  editLayoutHost.reportEditState(null);
  expect(editLayoutHost.builds()).toBe(before + 1);
  leave();
});
