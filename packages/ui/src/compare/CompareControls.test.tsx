import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CompareControls } from '../../dist/compare/CompareControls.js';
import { I18nProvider } from '../../dist/i18n/index.js';
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '../../dist/primitives/dropdown-menu.js';

Object.assign(globalThis, { React });
beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// A folder of revisions, as the host's files list it: the STEP on screen, two others, a drawing and a subfolder.
const FOLDER = [
  { path: '/m/bracket.step', name: 'bracket.step', kind: 'file' },
  { path: '/m/bracket-rev-b.stp', name: 'bracket-rev-b.stp', kind: 'file' },
  { path: '/m/bracket-rev-a.step', name: 'bracket-rev-a.step', kind: 'file' },
  { path: '/m/bracket.dxf', name: 'bracket.dxf', kind: 'file' },
  { path: '/m/old.step', name: 'old.step', kind: 'directory' },
];
const files = (entries = FOLDER) => ({ id: 'test', stat: vi.fn(), list: vi.fn(async () => entries) });
// Compare's view as the host loads it: here a stand-in that shows what it was handed.
function View({ before, after, onSwap, onClose }: any) {
  return <div data-testid="view">{`${before} → ${after}`}<button type="button" onClick={onSwap}>swap</button><button type="button" onClick={onClose}>close</button></div>;
}
const load = () => Promise.resolve({ StepCompare: View });
const readFile = vi.fn(async () => new Uint8Array());

function mount(file: string, props: Record<string, unknown> = {}, source = files()) {
  const ui = (shown: string) => <I18nProvider locale="en"><CompareControls file={shown} files={source} readFile={readFile} load={load} {...props}>
    {({ menu, overlay }: any) => <>{menu ? <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild><button type="button" aria-label="File actions">⋯</button></DropdownMenuTrigger>
      <DropdownMenuContent>{menu}</DropdownMenuContent>
    </DropdownMenu> : null}{overlay}</>}
  </CompareControls></I18nProvider>;
  const view = render(ui(file));
  return { ...view, show: (next: string) => view.rerender(ui(next)), source };
}
async function openCompare(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'File actions' }));
  await user.click(screen.getByRole('menuitem', { name: 'Compare with' }));
  return screen.findByRole('menu', { name: 'Compare with' });
}

it('a STEP offers the other STEP files in its folder, by name, read as the submenu opens', async () => {
  const user = userEvent.setup();
  const { source } = mount('/m/bracket.step');
  expect(source.list).not.toHaveBeenCalled();
  const menu = await openCompare(user);
  await waitFor(() => expect(within(menu).getAllByRole('menuitem').map(item => item.textContent)).toEqual(['bracket-rev-a.step', 'bracket-rev-b.stp']));
  expect(source.list).toHaveBeenCalledWith('/m', expect.anything());
});

it('a folder with no other STEP says so', async () => {
  const user = userEvent.setup();
  mount('/m/bracket.step', {}, files([FOLDER[0]!, FOLDER[3]!]));
  const menu = await openCompare(user);
  expect(await within(menu).findByRole('menuitem', { name: 'No other STEP file in this folder' })).toBeTruthy();
  expect(within(menu).getByRole('menuitem').getAttribute('aria-disabled')).toBe('true');
});

it('there is no Compare for a file that is not a STEP, nor where the host cannot read files or load the view', () => {
  for (const [file, props] of [['/m/bracket.dxf', {}], ['/m/bracket.step', { readFile: undefined }], ['/m/bracket.step', { load: undefined }]] as const) {
    const { unmount } = mount(file, props);
    expect(screen.queryByRole('button', { name: 'File actions' })).toBeNull();
    unmount();
  }
});

it('the file picked is before and the one on screen after; swapped, closed, and closed by another file shown', async () => {
  const user = userEvent.setup();
  const { show } = mount('/m/bracket.step');
  const menu = await openCompare(user);
  const item = await within(menu).findByRole('menuitem', { name: 'bracket-rev-a.step' });
  fireEvent.click(item);
  expect((await screen.findByTestId('view')).textContent).toContain('/m/bracket-rev-a.step → /m/bracket.step');
  await user.click(screen.getByRole('button', { name: 'swap' }));
  expect(screen.getByTestId('view').textContent).toContain('/m/bracket.step → /m/bracket-rev-a.step');
  await user.click(screen.getByRole('button', { name: 'close' }));
  expect(screen.queryByTestId('view')).toBeNull();

  // A pick is a click on the row (user-event's pointer stops at the submenu's pointer-events in jsdom).
  fireEvent.click(await within(await openCompare(user)).findByRole('menuitem', { name: 'bracket-rev-b.stp' }));
  expect(await screen.findByTestId('view')).toBeTruthy();
  show('/m/bracket-rev-b.stp');
  await waitFor(() => expect(screen.queryByTestId('view')).toBeNull());
});
