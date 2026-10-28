import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { chosenThrough, useAsked, useChosenFeature } from './selectionBarState.js';

afterEach(cleanup);

// The workspace with a face picked and nothing open, on one part.
const WORKSPACE = { editing: true, picked: true, held: false, file: 'bracket.step' };
function asking(props = WORKSPACE) {
  const view = renderHook((next: typeof WORKSPACE) => useAsked(next), { initialProps: props });
  return { ...view, show: (patch: Partial<typeof WORKSPACE>) => view.rerender({ ...props, ...patch }) };
}

it('is asked by Ask, and put away by Clear: what Escape, a send and the box\'s X each do', () => {
  const view = asking();
  expect(view.result.current.asked).toBe(false);
  act(() => view.result.current.ask());
  expect(view.result.current.asked).toBe(true);
  act(() => view.result.current.clear());
  expect(view.result.current.asked).toBe(false);
});

it('is cleared when the picks empty, and asking with nothing picked is not that', () => {
  const view = asking();
  act(() => view.result.current.ask());
  // Another pick instead of the one before is not an emptying.
  view.show({ picked: true });
  expect(view.result.current.asked).toBe(true);
  view.show({ picked: false });
  expect(view.result.current.asked).toBe(false);
  // Ask with nothing picked is Quick Edit on the whole part, and stays until something puts it away.
  act(() => view.result.current.ask());
  expect(view.result.current.asked).toBe(true);
  view.show({ picked: false });
  expect(view.result.current.asked).toBe(true);
  // Picked then, and let go again, it goes.
  view.show({ picked: true });
  expect(view.result.current.asked).toBe(true);
  view.show({ picked: false });
  expect(view.result.current.asked).toBe(false);
});

it('is cleared when a command or a sketch opens, and asking while one is open is not that', () => {
  const view = asking();
  act(() => view.result.current.ask());
  view.show({ held: true });
  expect(view.result.current.asked).toBe(false);
  // Asked with the command already open (the toolbar's Ask waits for it now, but the latch does not rely on that), it stays while that one is.
  act(() => view.result.current.ask());
  expect(view.result.current.asked).toBe(true);
  view.show({ held: true, picked: true });
  expect(view.result.current.asked).toBe(true);
  // The next one that opens, once it has closed, puts it away again.
  view.show({ held: false });
  expect(view.result.current.asked).toBe(true);
  view.show({ held: true });
  expect(view.result.current.asked).toBe(false);
});

it('is the workspace\'s alone: Simple view takes it away, and Ask there asks for nothing', () => {
  const view = asking();
  act(() => view.result.current.ask());
  view.show({ editing: false });
  expect(view.result.current.asked).toBe(false);
  act(() => view.result.current.ask());
  expect(view.result.current.asked).toBe(false);
  // Back in the workspace, it is not asked for again.
  view.show({ editing: true });
  expect(view.result.current.asked).toBe(false);
});

it('is the file\'s: another file opening does not inherit it', () => {
  const view = asking();
  act(() => view.result.current.ask());
  view.show({ file: 'plate.step' });
  expect(view.result.current.asked).toBe(false);
});

it('keeps the same functions between renders, so what is wired to them is wired once', () => {
  const view = asking();
  const { ask, clear } = view.result.current;
  view.show({ picked: false });
  expect([view.result.current.ask, view.result.current.clear]).toEqual([ask, clear]);
});

// A part in the workspace with nothing open.
const PART = { editing: true, held: false, file: 'bracket.step' };
function choosing(props = PART) {
  const view = renderHook((next: typeof PART) => useChosenFeature(next), { initialProps: props });
  return { ...view, show: (patch: Partial<typeof PART>) => view.rerender({ ...props, ...patch }) };
}

it('a feature is chosen by the person pressing it, and not by anything else selecting it', () => {
  const view = choosing();
  // A command's OK selects the feature it made; nobody chose it.
  expect(view.result.current.chosen).toBe(false);
  act(() => view.result.current.choose());
  expect(view.result.current.chosen).toBe(true);
  // Their next press on the model puts it away.
  act(() => view.result.current.drop());
  expect(view.result.current.chosen).toBe(false);
});

it('a chosen feature is put away when a command or a sketch opens, and chosen again after it', () => {
  const view = choosing();
  act(() => view.result.current.choose());
  view.show({ held: true });
  expect(view.result.current.chosen).toBe(false);
  // The command's OK selects what it made; the person has chosen nothing, and the bar does not stand over the part.
  view.show({ held: false });
  expect(view.result.current.chosen).toBe(false);
  act(() => view.result.current.choose());
  expect(view.result.current.chosen).toBe(true);
});

it('a chosen feature goes with the workspace and with the file', () => {
  const view = choosing();
  act(() => view.result.current.choose());
  view.show({ editing: false });
  expect(view.result.current.chosen).toBe(false);
  act(() => view.result.current.choose());
  expect(view.result.current.chosen).toBe(false);
  view.show({ editing: true });
  act(() => view.result.current.choose());
  view.show({ file: 'plate.step' });
  expect(view.result.current.chosen).toBe(false);
});

it('a row the design tree or the timeline selects is chosen; clearing the selection chooses nothing', () => {
  const edit = { select: vi.fn(), selected: 'e1', status: 'ready' };
  const choose = vi.fn();
  const handed = chosenThrough(edit, choose);
  // All else of the edit state is its own.
  expect([handed.selected, handed.status]).toEqual(['e1', 'ready']);
  handed.select('e2');
  expect([edit.select.mock.calls, choose.mock.calls.length]).toEqual([[['e2']], 1]);
  handed.select(null);
  expect([edit.select.mock.calls.at(-1), choose.mock.calls.length]).toEqual([[null], 1]);
});

it('letting go of the feature chosen, as its chip\'s X does, ends the ask that was about it alone; another pick keeps it', () => {
  type Props = { editing: boolean; held: boolean; file: string; others: boolean };
  const both = ({ others, ...state }: Props) => {
    const feature = useChosenFeature(state);
    // What is picked: the feature chosen, and what else (a face).
    const asking = useAsked({ ...state, picked: feature.chosen || others });
    return { feature, asking };
  };
  const base = { ...PART, others: false };
  const view = renderHook((props: Props) => both(props), { initialProps: base });
  act(() => view.result.current.feature.choose());
  act(() => view.result.current.asking.ask());
  expect(view.result.current.asking.asked).toBe(true);
  act(() => view.result.current.feature.drop());
  expect(view.result.current.asking.asked).toBe(false);
  // With a face picked as well, the ask is about it too, and stays.
  view.rerender({ ...base, others: true });
  act(() => view.result.current.feature.choose());
  act(() => view.result.current.asking.ask());
  act(() => view.result.current.feature.drop());
  expect(view.result.current.asking.asked).toBe(true);
});
