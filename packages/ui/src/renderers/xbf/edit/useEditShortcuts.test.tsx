import { cleanup, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { ViewerElementContext } from '../../../host/context.js';
import { useEditShortcuts } from './useEditShortcuts.js';

afterEach(() => {
  cleanup();
  document.body.innerHTML = '';
});

/** A viewer on the page with a button and a text field in it, and edit mode's Undo and Redo. */
function viewer(edit: { canUndo: boolean; canRedo: boolean }) {
  const element = document.createElement('div');
  element.innerHTML = '<button type="button">Fillet</button><input aria-label="Width value" />';
  document.body.append(element);
  const undo = vi.fn(async () => {});
  const redo = vi.fn(async () => {});
  const wrapper = ({ children }: { children: ReactNode }) =>
    <ViewerElementContext.Provider value={{ current: element }}>{children}</ViewerElementContext.Provider>;
  renderHook(() => useEditShortcuts({ ...edit, undo, redo } as never, true), { wrapper });
  return { element, undo, redo };
}

const press = (target: Element, init: KeyboardEventInit) => target.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }));

it('Cmd+Z undoes and Shift+Cmd+Z redoes in the viewer, but a text field keeps its own Undo', () => {
  const { element, undo, redo } = viewer({ canUndo: true, canRedo: true });
  const button = element.querySelector('button')!;
  press(button, { key: 'z', metaKey: true });
  press(button, { key: 'z', metaKey: true, shiftKey: true });
  press(button, { key: 'y', ctrlKey: true });
  expect(undo).toHaveBeenCalledTimes(1);
  expect(redo).toHaveBeenCalledTimes(2);
  press(element.querySelector('input')!, { key: 'z', metaKey: true });
  expect(undo).toHaveBeenCalledTimes(1);
});

it('a key outside the viewer, or with nothing to redo, is left alone', () => {
  const { element, undo, redo } = viewer({ canUndo: true, canRedo: false });
  const outside = document.createElement('button');
  document.body.append(outside);
  press(outside, { key: 'z', metaKey: true });
  expect(undo).not.toHaveBeenCalled();
  press(element.querySelector('button')!, { key: 'z', metaKey: true, shiftKey: true });
  expect(redo).not.toHaveBeenCalled();
});

it('F2 renames what the tree has selected, and Cmd+8 turns the view Normal To, from inside the viewer', () => {
  const element = document.createElement('div');
  element.innerHTML = '<button type="button">Fillet</button><input aria-label="Width value" />';
  document.body.append(element);
  const startRename = vi.fn();
  const lookNormalTo = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) =>
    <ViewerElementContext.Provider value={{ current: element }}>{children}</ViewerElementContext.Provider>;
  renderHook(() => useEditShortcuts({ canUndo: false, canRedo: false, selected: 'block.py:7', startRename, lookNormalTo } as never, true), { wrapper });
  const button = element.querySelector('button')!;
  press(button, { key: 'F2' });
  expect(startRename).toHaveBeenCalledWith('block.py:7');
  press(button, { key: '8', metaKey: true });
  expect(lookNormalTo).toHaveBeenCalledTimes(1);
  // A text field keeps its keys.
  press(element.querySelector('input')!, { key: 'F2' });
  press(element.querySelector('input')!, { key: '8', ctrlKey: true });
  expect(startRename).toHaveBeenCalledTimes(1);
  expect(lookNormalTo).toHaveBeenCalledTimes(1);
});

/** A viewer with a button and a text field in it, edit mode given only the command search to ask for (`active`: the workspace is up). */
function searchViewer(active = true, edit: Record<string, unknown> = {}) {
  const element = document.createElement('div');
  element.innerHTML = '<button type="button">Fillet</button><input aria-label="Width value" />';
  document.body.append(element);
  const findCommand = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) =>
    <ViewerElementContext.Provider value={{ current: element }}>{children}</ViewerElementContext.Provider>;
  renderHook(() => useEditShortcuts({ canUndo: false, canRedo: false, findCommand, ...edit } as never, active), { wrapper });
  return { element, button: element.querySelector('button')!, input: element.querySelector('input')!, findCommand };
}

it('S opens command search, not while typing', () => {
  const { button, input, findCommand } = searchViewer();
  // The key is the search's: nothing else is to take it.
  expect(press(button, { key: 's' })).toBe(false);
  expect(findCommand).toHaveBeenCalledTimes(1);
  // A text field keeps its own S, and the search is not asked again.
  expect(press(input, { key: 's' })).toBe(true);
  expect(findCommand).toHaveBeenCalledTimes(1);
  // Caps Lock types a capital without Shift held.
  press(button, { key: 'S' });
  expect(findCommand).toHaveBeenCalledTimes(2);
});

it('S with a modifier, held down, or pressed outside the viewer is left alone', () => {
  const { button, findCommand } = searchViewer();
  for (const modifier of [{ metaKey: true }, { ctrlKey: true }, { altKey: true }, { shiftKey: true }]) {
    expect(press(button, { key: 's', ...modifier })).toBe(true);
  }
  expect(press(button, { key: 's', repeat: true })).toBe(true);
  const outside = document.createElement('button');
  document.body.append(outside);
  expect(press(outside, { key: 's' })).toBe(true);
  // A key already taken is not taken twice.
  const taken = new KeyboardEvent('keydown', { key: 's', bubbles: true, cancelable: true });
  taken.preventDefault();
  button.dispatchEvent(taken);
  expect(findCommand).not.toHaveBeenCalled();
  // The page's background after a press inside the viewer is the viewer's key, as for the other keys.
  button.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  expect(press(document.body, { key: 's' })).toBe(false);
  expect(findCommand).toHaveBeenCalledTimes(1);
});

it('S is not taken in Simple view', () => {
  const { button, findCommand } = searchViewer(false);
  // Edit mode is not up: whatever the strip gives the key stays the strip's.
  expect(press(button, { key: 's' })).toBe(true);
  expect(findCommand).not.toHaveBeenCalled();
});

it("Ctrl+1 to Ctrl+7 turn to SolidWorks' standard views, from inside the viewer, a text field keeping its keys", () => {
  const element = document.createElement('div');
  element.innerHTML = '<button type="button">Fillet</button><input aria-label="Width value" />';
  document.body.append(element);
  const lookStandard = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) =>
    <ViewerElementContext.Provider value={{ current: element }}>{children}</ViewerElementContext.Provider>;
  renderHook(() => useEditShortcuts({ canUndo: false, canRedo: false, lookStandard } as never, true), { wrapper });
  const button = element.querySelector('button')!;
  ['1', '2', '3', '4', '5', '6', '7'].forEach(key => press(button, { key, ctrlKey: true }));
  expect(lookStandard.mock.calls.map(([name]) => name)).toEqual(['front', 'back', 'left', 'right', 'top', 'bottom', 'isometric']);
  press(element.querySelector('input')!, { key: '1', metaKey: true });
  expect(lookStandard).toHaveBeenCalledTimes(7);
});
