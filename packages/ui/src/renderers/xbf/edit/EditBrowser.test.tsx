import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import EditBrowser, { floatsCard } from '../../../../dist/renderers/xbf/edit/EditBrowser.js';
import { featureTree } from '../../../../dist/renderers/xbf/edit/editMode.js';
import { WORKSPACE_SURFACE_CLASS } from '../../../../dist/lib/floatingSurface.js';

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); document.querySelectorAll('[data-test-card]').forEach(node => node.remove()); });

const STATE = { units: 'mm', name: 'block', rows: [], params: [], features: [] };
function edit(patch: Record<string, unknown> = {}) {
  return { status: 'ready', saving: false, state: STATE, selected: null, renaming: null, bar: null, sketch: null, command: null, picking: false,
    inspecting: null, error: 'The fillet could not be built.', redraw: null, dismissError: vi.fn(), select: vi.fn(), hover: vi.fn(), ...patch };
}
// The place beside the design tree the frame gives the open command's dialog (`dialogPlace`).
function place() {
  const card = document.createElement('div');
  card.setAttribute('data-test-card', '');
  document.body.append(card);
  return card;
}

it("says what went wrong in the card beside the design tree, so the tree folded to its title never hides it", () => {
  const card = place();
  const { container } = render(<EditBrowser edit={edit() as never} names={[]} tree={featureTree(STATE)} card={card} />);
  const alert = screen.getByRole('alert');
  expect([card.contains(alert), container.contains(alert), alert.textContent]).toEqual([true, false, 'The fillet could not be built.']);
  // The card is the workspace's white surface: opaque, blurring nothing of the live canvas under it.
  const surface = card.querySelector<HTMLElement>('[data-cad-command-card]')!;
  expect(surface.className.split(/\s+/)).toEqual(expect.arrayContaining(WORKSPACE_SURFACE_CLASS.split(' ')));
  expect(surface.className).not.toMatch(/\bbackdrop-|bg-background\//);
  cleanup();
  // With a command's dialog open it heads the dialog, in the same card.
  render(<EditBrowser edit={edit({ inspecting: 'expressions', change: vi.fn(), addParameter: vi.fn(), stopInspecting: vi.fn() }) as never}
    names={[]} tree={featureTree(STATE)} card={card} />);
  const dialog = within(card).getByRole('dialog', { name: 'Equations' });
  expect(Boolean(within(card).getByRole('alert').compareDocumentPosition(dialog) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
  cleanup();
  // With no place to float in, it heads the tree, as it did.
  render(<EditBrowser edit={edit() as never} names={[]} tree={featureTree(STATE)} />);
  expect(screen.getByRole('alert').closest('[data-cad-edit-browser]')).not.toBeNull();
});

it("says whether it floats a card in the dialog's place, as the frame keeps the column clear of one", () => {
  const card = place();
  const panel = { change: vi.fn(), addParameter: vi.fn(), stopInspecting: vi.fn() };
  const states = {
    nothing: edit({ error: '' }),
    'what went wrong': edit(),
    'an Inspect panel': edit({ error: '', inspecting: 'expressions', ...panel }),
    'the drawing, with no sheet yet': edit({ error: '', inspecting: 'drawing' }),
  };
  const floated = Object.fromEntries(Object.entries(states).map(([name, state]) => {
    render(<EditBrowser edit={state as never} names={[]} tree={featureTree(STATE)} card={card} />);
    const shown = card.childElementCount > 0;
    cleanup();
    return [name, [floatsCard(state), shown]];
  }));
  expect(floated).toEqual({ nothing: [false, false], 'what went wrong': [true, true], 'an Inspect panel': [true, true],
    'the drawing, with no sheet yet': [false, false] });
});

it("asks Confirm Delete in the card, naming the child features, and deletes them all only on Delete All", () => {
  const card = place();
  const asked = edit({ error: '', confirming: { id: 'tray.py:7', title: 'Boss-Extrude1', children: [{ key: 'tray.py:8', title: 'Fillet1' }, { key: 'tray.py:9', title: 'Cut-Extrude1' }] },
    confirmDelete: vi.fn(), dismissDelete: vi.fn() });
  expect(floatsCard(asked)).toBe(true);
  render(<EditBrowser edit={asked as never} names={[]} tree={featureTree(STATE)} card={card} />);
  const dialog = within(card).getByRole('alertdialog', { name: 'Confirm Delete' });
  expect(dialog.textContent).toContain('Boss-Extrude1 has child features: Fillet1, Cut-Extrude1. Delete them too?');
  within(dialog).getByRole('button', { name: 'Cancel' }).click();
  expect([asked.dismissDelete.mock.calls.length, asked.confirmDelete.mock.calls.length]).toEqual([1, 0]);
  within(dialog).getByRole('button', { name: 'Delete All' }).click();
  expect(asked.confirmDelete).toHaveBeenCalledTimes(1);
});
