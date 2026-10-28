import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { focusHost } from '../../../tab-store/focusHost.js';
import { featureTree } from './editMode.js';
import { useHostFocus } from './useHostFocus.js';

afterEach(() => {
  cleanup();
  focusHost.set(null);
});

// A bracket as the engine reads it: its base on line 11, and its hole one statement over lines 14 to 17.
const features = [
  { key: 'parts/bracket.py:11', kind: 'Boss-Extrude', file: 'parts/bracket.py', line: 11, end: 11 },
  { key: 'parts/bracket.py:14', kind: 'Hole', file: 'parts/bracket.py', line: 14, end: 17 },
];
const READ = { onScreen: true, layout: 'manual', status: 'ready', tree: featureTree({ features }) };
type Part = typeof READ;

/** The part on screen, as CAD mode hands the hook its edit state; what it selects, and the asks it says taken. */
function hosting(props: Part) {
  const select = vi.fn();
  const taken: { nonce: number, found: boolean }[] = [];
  const leave = focusHost.subscribeTaken(answer => { taken.push(answer); });
  const view = renderHook((next: Part) => useHostFocus({ ...next, select }), { initialProps: props });
  return { ...view, select, taken, leave, show: (patch: Partial<Part>) => view.rerender({ ...props, ...patch }) };
}
const ask = (line: number, nonce: number) => act(() => focusHost.set({ path: 'parts/bracket.py', line, nonce }));

it('waits while the part is read, then selects the feature whose statement holds the line and says the ask taken, found, once', () => {
  const view = hosting({ ...READ, status: 'probing' });
  ask(16, 1);
  view.show({ status: 'reading' });
  expect([view.select.mock.calls, view.taken]).toEqual([[], []]);
  view.show({ status: 'ready' });
  expect([view.select.mock.calls, view.taken]).toEqual([[['parts/bracket.py:14']], [{ nonce: 1, found: true }]]);
  // The part is read again before the host lets the ask go: it is not answered twice.
  view.show({ status: 'ready', tree: featureTree({ features: [...features] }) });
  expect([view.select.mock.calls.length, view.taken]).toEqual([1, [{ nonce: 1, found: true }]]);
  // The next ask is its own: at the blank line after the hole nothing is selected, and it is answered all the same, as
  // found nowhere, for the host to open the script there.
  ask(18, 2);
  expect([view.select.mock.calls.length, view.taken]).toEqual([1, [{ nonce: 1, found: true }, { nonce: 2, found: false }]]);
  view.leave();
});

it('answers a file with no part script, and a part whose build failed, selecting nothing and finding nothing', () => {
  for (const [status, nonce] of [['none', 3], ['error', 4]] as const) {
    const view = hosting({ ...READ, status, tree: featureTree(null) });
    ask(16, nonce);
    expect([view.select.mock.calls, view.taken]).toEqual([[], [{ nonce, found: false }]]);
    view.leave();
    view.unmount();
    // The host lets it go once taken.
    act(() => focusHost.set(null));
  }
});

it('laid out for the AI the view answers at once, and the library\'s out-of-sight picture answers nothing', () => {
  const ai = hosting({ ...READ, layout: 'ai', status: 'idle' });
  ask(16, 5);
  expect([ai.select.mock.calls, ai.taken]).toEqual([[], [{ nonce: 5, found: false }]]);
  ai.leave();
  ai.unmount();
  act(() => focusHost.set(null));
  const picture = hosting({ ...READ, onScreen: false });
  ask(16, 6);
  expect([picture.select.mock.calls, picture.taken]).toEqual([[], []]);
  picture.leave();
});
