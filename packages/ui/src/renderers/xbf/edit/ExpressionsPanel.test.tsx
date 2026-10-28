import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import EditBrowser from '../../../../dist/renderers/xbf/edit/EditBrowser.js';
import ExpressionsPanel from '../../../../dist/renderers/xbf/edit/ExpressionsPanel.js';
import { featureTree } from '../../../../dist/renderers/xbf/edit/editMode.js';

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const STATE = {
  units: 'mm', name: 'block', rows: [], features: [],
  params: [{ id: 'block.py:3', name: 'TRAY_WIDTH', text: '40', unit: 'mm' }, { id: 'block.py:4', name: 'WALL', text: '2', unit: 'mm' }],
};

function edit(patch: Record<string, unknown> = {}) {
  return { status: 'ready', saving: false, state: STATE, selected: null, renaming: null, bar: null, sketch: null, command: null, picking: false,
    inspecting: 'expressions', change: vi.fn(), addParameter: vi.fn(), stopInspecting: vi.fn(),
    select: vi.fn(), hover: vi.fn(), ...patch };
}

it("lists the part's user expressions, each typed over in place, and Close puts the panel away", async () => {
  const user = userEvent.setup();
  const open = edit();
  render(<ExpressionsPanel edit={open as never} />);
  // SolidWorks' dialog is Equations, and what it lists the part's Global Variables.
  const dialog = screen.getByRole('dialog', { name: 'Equations' });
  expect(within(dialog).getByText('Global Variables')).toBeTruthy();
  expect(within(dialog).getByText('Tray width')).toBeTruthy();
  const wall = within(dialog).getByRole('textbox', { name: 'Wall value' });
  await user.clear(wall);
  await user.type(wall, '2.5{Enter}');
  expect(open.change).toHaveBeenCalledWith({ literal: 'block.py:4', text: '2.5' });
  // A new one is added by name and value, as the design tree's list adds it.
  await user.click(within(dialog).getByRole('button', { name: '+ Add expression' }));
  expect(within(dialog).getByRole('form', { name: 'Add expression' })).toBeTruthy();
  await user.click(within(dialog).getByRole('button', { name: 'Close' }));
  expect(open.stopInspecting).toHaveBeenCalledTimes(1);
});

it("says so when the part has none, and while it is being read", () => {
  const { rerender } = render(<ExpressionsPanel edit={edit({ state: { ...STATE, params: [] } }) as never} />);
  expect(screen.getByText('No expressions yet.')).toBeTruthy();
  rerender(<ExpressionsPanel edit={edit({ status: 'reading', state: null }) as never} />);
  expect(screen.getByText('Reading the part')).toBeTruthy();
});

it("opens in the browser's command card, where the other Inspect panels open", () => {
  const card = document.createElement('div');
  document.body.append(card);
  render(<EditBrowser edit={edit() as never} names={[]} tree={featureTree(STATE)} card={card} />);
  expect(card.contains(screen.getByRole('dialog', { name: 'Equations' }))).toBe(true);
  cleanup();
  card.remove();
  // Not asked for, it is not there; the design tree keeps its own list of them, folded at the top.
  render(<EditBrowser edit={edit({ inspecting: null }) as never} names={[]} tree={featureTree(STATE)} />);
  expect(screen.queryByRole('dialog', { name: 'Equations' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Equations' }).getAttribute('aria-expanded')).toBe('false');
});
