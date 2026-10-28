import { useRef, useState, type ReactNode } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CommandSearchBox from '../../../../dist/renderers/xbf/edit/CommandSearchBox.js';
import EditRibbon from '../../../../dist/renderers/xbf/edit/EditRibbon.js';
import { useEditShortcuts } from '../../../../dist/renderers/xbf/edit/useEditShortcuts.js';
import { ViewerElementContext } from '../../../../dist/host/context.js';
import { WORKSPACE_SURFACE_CLASS } from '../../../../dist/lib/floatingSurface.js';

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

type Item = { id: string; label: string; icon: ReactNode; disabled?: boolean; description?: string; run: () => void };
/** One button of the toolbar as the search is handed it: its name, its picture, whether it can be pressed, and what pressing it does. */
const item = (id: string, label: string, patch: Partial<Item> = {}): Item => ({ id, label, icon: <svg data-icon={id} />, disabled: false, run: vi.fn(), ...patch });
const rows = () => screen.getAllByRole('option');
const names = () => rows().map(row => row.textContent);
const box = (items: Item[], options: { sketching?: boolean; onClose?: () => void } = {}) => {
  const onClose = options.onClose ?? vi.fn();
  render(<CommandSearchBox items={items} sketching={options.sketching ?? false} onClose={onClose} />);
  return { onClose, input: screen.getByRole('combobox') };
};

it('lists what the toolbar has, in its order, and narrows as the person types', async () => {
  const user = userEvent.setup();
  const { input } = box([item('hole', 'Hole Wizard'), item('fillet', 'Fillet'), item('extrude', 'Extruded Boss/Base'), item('cut', 'Extruded Cut')]);
  // Every command with nothing typed, in the toolbar's order (Extruded Boss/Base and its Cut, then Hole Wizard, then Fillet).
  expect(names()).toEqual(['Extruded Boss/Base', 'Extruded Cut', 'Hole Wizard', 'Fillet']);
  await user.type(input, 'fillet');
  expect(names()).toEqual(['Fillet']);
  await user.clear(input);
  // Fillet, which another tool calls an edge blend.
  await user.type(input, 'edge blend');
  expect(names()).toEqual(['Fillet']);
  await user.clear(input);
  await user.type(input, 'cut');
  expect(names()).toEqual(['Extruded Cut']);
});

it('leaves out what the toolbar has no button for, so the two never disagree', async () => {
  const user = userEvent.setup();
  const { input } = box([item('hole', 'Hole')]);
  await user.type(input, 'fillet');
  expect(screen.queryAllByRole('option')).toEqual([]);
  expect(screen.getByRole('status').textContent).toBe('No command found.');
  await user.clear(input);
  await user.type(input, 'hole');
  expect(names()).toEqual(['Hole']);
});

it("opens with the text field in hand, and Enter runs the first result and closes", async () => {
  const user = userEvent.setup();
  const fillet = item('fillet', 'Fillet');
  const { input, onClose } = box([item('hole', 'Hole'), fillet]);
  expect(document.activeElement).toBe(input);
  await user.type(input, 'ed');
  await user.keyboard('{Enter}');
  expect(fillet.run).toHaveBeenCalledTimes(1);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it('moves the choice with the arrow keys, round the ends, and Enter runs the one chosen', async () => {
  const user = userEvent.setup();
  const hole = item('hole', 'Hole');
  const fillet = item('fillet', 'Fillet');
  const shell = item('shell', 'Shell');
  const { input } = box([shell, fillet, hole]);
  const chosen = () => rows().findIndex(row => row.getAttribute('aria-selected') === 'true');
  // The toolbar's order, whatever order the buttons are handed over in.
  expect(names()).toEqual(['Hole', 'Fillet', 'Shell']);
  // The first is the choice as it opens; the field names the one chosen.
  expect(chosen()).toBe(0);
  expect(input.getAttribute('aria-activedescendant')).toBe(rows()[0].id);
  await user.keyboard('{ArrowDown}{ArrowDown}');
  expect(chosen()).toBe(2);
  expect(input.getAttribute('aria-activedescendant')).toBe(rows()[2].id);
  await user.keyboard('{ArrowDown}');
  expect(chosen()).toBe(0);
  await user.keyboard('{ArrowUp}');
  expect(chosen()).toBe(2);
  await user.keyboard('{ArrowUp}{Enter}');
  expect([hole, fillet, shell].map(each => (each.run as ReturnType<typeof vi.fn>).mock.calls.length)).toEqual([0, 1, 0]);
});

it('starts the choice over at the first result when the words change', async () => {
  const user = userEvent.setup();
  const { input } = box([item('extrude', 'Extrude'), item('hole', 'Hole'), item('shell', 'Shell')]);
  await user.keyboard('{ArrowDown}{ArrowDown}');
  await user.type(input, 'hol');
  // Hole by its name, then Shell, which another tool calls a hollow; the choice is the first again, not where it was.
  expect(names()).toEqual(['Hole', 'Shell']);
  expect(rows().map(row => row.getAttribute('aria-selected'))).toEqual(['true', 'false']);
});

it('closes on Escape without running anything', async () => {
  const user = userEvent.setup();
  const hole = item('hole', 'Hole');
  const { onClose } = box([hole]);
  await user.keyboard('{Escape}');
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(hole.run).not.toHaveBeenCalled();
});

it('runs a result clicked, and keeps the text field in hand while it is pressed', async () => {
  const user = userEvent.setup();
  const hole = item('hole', 'Hole');
  const { input, onClose } = box([hole, item('shell', 'Shell')]);
  await user.click(screen.getByRole('option', { name: 'Hole' }));
  expect(hole.run).toHaveBeenCalledTimes(1);
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(input);
});

it("lists a command the toolbar shows dimmed as dimmed, says why while it is the choice, and runs nothing", async () => {
  const user = userEvent.setup();
  const why = 'An assembly places its parts. Ask the agent to change a part.';
  const extrude = item('extrude', 'Extrude', { disabled: true, description: why });
  const hole = item('hole', 'Hole');
  const { onClose } = box([extrude, hole]);
  const dimmed = screen.getByRole('option', { name: 'Extrude' });
  expect(dimmed.getAttribute('aria-disabled')).toBe('true');
  expect(screen.getByRole('option', { name: 'Hole' }).getAttribute('aria-disabled')).toBeNull();
  // The first result is the choice, and the reason is said.
  expect(screen.getByRole('status').textContent).toBe(why);
  await user.keyboard('{Enter}');
  await user.click(dimmed);
  expect(extrude.run).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();
  // Moved to a command that works, the reason goes.
  await user.keyboard('{ArrowDown}');
  expect(screen.queryByRole('status')).toBeNull();
  await user.keyboard('{Enter}');
  expect(hole.run).toHaveBeenCalledTimes(1);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("lights the result under the pointer, but not one the toolbar shows dimmed, as it lights none of its dimmed buttons", () => {
  box([item('extrude', 'Extrude'), item('hole', 'Hole', { disabled: true }), item('shell', 'Shell')]);
  const [, dimmed, enabled] = rows();
  expect(enabled.className).toMatch(/hover:bg-cad-ws-hover/);
  expect(dimmed.className).not.toMatch(/hover:bg-cad-ws-hover/);
  expect(dimmed.className).toMatch(/aria-disabled:opacity-40/);
});

it("finds a button by the name the toolbar gives it now", async () => {
  const user = userEvent.setup();
  const { input } = box([item('sketch', 'Edit Sketch')]);
  await user.type(input, 'edit sk');
  expect(names()).toEqual(['Edit Sketch']);
});

it("lists a sketch's tools while a sketch is open", async () => {
  const user = userEvent.setup();
  const line = item('line', 'Line');
  const { input } = box([line, item('fillet', 'Fillet'), item('extrude', 'Extrude')], { sketching: true });
  await user.type(input, 'line');
  expect(names()).toEqual(['Line']);
  await user.keyboard('{Enter}');
  expect(line.run).toHaveBeenCalledTimes(1);
});

it('draws each result with its picture and its name, in the workspace\'s white card, with the pale blue under the pointer', () => {
  box([item('hole', 'Hole Wizard'), item('cut', 'Extruded Cut')]);
  expect(screen.getByRole('dialog', { name: 'Command search' }).className.split(/\s+/)).toEqual(expect.arrayContaining(WORKSPACE_SURFACE_CLASS.split(' ')));
  const [cut, hole] = rows();
  expect(within(hole).getByText('Hole Wizard')).toBeTruthy();
  expect(hole.querySelector('[data-icon="hole"]')).not.toBeNull();
  // A cut is its own command, said by its own name, with nothing after it.
  expect(cut.textContent).toBe('Extruded Cut');
  expect(cut.querySelector('.text-muted-foreground')).toBeNull();
  expect(hole.className).toMatch(/hover:bg-cad-ws-hover/);
  expect(rows()[0].className).toMatch(/bg-cad-ws-selected/);
  expect(rows()[1].className).not.toMatch(/(^|\s)bg-cad-ws-selected/);
  // No monospace, no backdrop blur over the live canvas.
  expect(screen.getByRole('dialog').outerHTML).not.toMatch(/font-mono|backdrop-/);
});

it('goes when a press lands outside it, or focus leaves it, and not when the press is inside', async () => {
  const user = userEvent.setup();
  const outside = document.createElement('button');
  document.body.append(outside);
  const { onClose } = box([item('hole', 'Hole')]);
  await user.click(screen.getByRole('dialog'));
  expect(onClose).not.toHaveBeenCalled();
  await user.click(outside);
  expect(onClose).toHaveBeenCalled();
  outside.remove();
});

it('goes at a press outside that leaves focus where it is, as a drag on the canvas does, and not at one inside', () => {
  const canvas = document.createElement('div');
  document.body.append(canvas);
  const { input, onClose } = box([item('hole', 'Hole')]);
  fireEvent.pointerDown(screen.getByRole('listbox'));
  fireEvent.pointerDown(input);
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.pointerDown(canvas);
  expect(onClose).toHaveBeenCalledTimes(1);
  // Nothing moved focus: the field still has it.
  expect(document.activeElement).toBe(input);
  canvas.remove();
});

it('puts focus back where it was when it goes', () => {
  const before = document.createElement('button');
  document.body.append(before);
  before.focus();
  const { unmount } = render(<CommandSearchBox items={[item('hole', 'Hole')]} sketching={false} onClose={vi.fn()} />);
  expect(document.activeElement).toBe(screen.getByRole('combobox'));
  unmount();
  expect(document.activeElement).toBe(before);
  before.remove();
});

it('leaves focus alone when it went to somewhere on purpose', () => {
  const before = document.createElement('button');
  const elsewhere = document.createElement('input');
  document.body.append(before, elsewhere);
  before.focus();
  const { unmount } = render(<CommandSearchBox items={[item('hole', 'Hole')]} sketching={false} onClose={vi.fn()} />);
  elsewhere.focus();
  unmount();
  expect(document.activeElement).toBe(elsewhere);
  before.remove();
  elsewhere.remove();
});

// ---- S, the toolbar and the search together ----

const tool = (id: string, label: string) => ({ id, label, icon: <svg />, active: false, disabled: false, onSelect: vi.fn() });
const PART_TOOLS = [tool('select', 'Select'), tool('measure', 'Measure'), tool('clip', 'Clip')];
function editMode(patch: Record<string, unknown> = {}) {
  return {
    status: 'ready', saving: false, rolling: false, error: '', state: { units: 'mm', components: [], drawing: null },
    command: null, inspecting: null, picking: false, sketch: null, canUndo: false, canRedo: false,
    undo: vi.fn(), redo: vi.fn(), open: vi.fn(), close: vi.fn(), inspect: vi.fn(), stopInspecting: vi.fn(), startPicking: vi.fn(), stopPicking: vi.fn(),
    exitSketch: vi.fn(), lookNormalTo: vi.fn(), drawing: vi.fn(), 
    sketchTool: null, sketchSelection: [], construction: false, setSketchTool: vi.fn(), setConstruction: vi.fn(), selectInSketch: vi.fn(), sketchOp: vi.fn(),
    ...patch,
  };
}

/** The viewer as the surface lays it out: the toolbar inside it, and edit mode's shortcuts listening for S. */
function Workspace({ onCommand, onSketch, active = true, fresh = 0 }: { onCommand: (id: string) => void; onSketch?: () => void; active?: boolean; fresh?: number }) {
  const viewer = useRef<HTMLDivElement>(null);
  const [asked, setAsked] = useState(fresh);
  const edit = { ...editMode(), findAsked: asked, findCommand: () => setAsked(count => count + 1) };
  return <div ref={viewer} data-viewer="">
    <ViewerElementContext.Provider value={viewer}><Shortcuts edit={edit} active={active} /><EditRibbon tools={PART_TOOLS} edit={edit as never} onCommand={onCommand} onSketch={onSketch} /></ViewerElementContext.Provider>
  </div>;
}
function Shortcuts({ edit, active }: { edit: unknown; active: boolean }) {
  useEditShortcuts(edit as never, active);
  return null;
}

it('S, pressed in the viewer, opens the box under the toolbar, and a command found there is run through the toolbar\'s own onCommand', async () => {
  const user = userEvent.setup();
  const onCommand = vi.fn();
  render(<Workspace onCommand={onCommand} />);
  expect(screen.queryByRole('dialog', { name: 'Command search' })).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Select' }));
  await user.keyboard('s');
  const search = screen.getByRole('dialog', { name: 'Command search' });
  expect(document.activeElement).toBe(within(search).getByRole('combobox'));
  // The box is the toolbar's neighbour, not inside it: the toolbar clips what overflows it.
  expect(screen.getByRole('toolbar').contains(search)).toBe(false);
  expect(search.parentElement).toBe(screen.getByRole('toolbar').parentElement);
  // The S that opened it was not typed into it.
  expect((document.activeElement as HTMLInputElement).value).toBe('');
  await user.keyboard('fillet{Enter}');
  expect(onCommand).toHaveBeenCalledTimes(1);
  expect(onCommand).toHaveBeenCalledWith('fillet');
  expect(screen.queryByRole('dialog', { name: 'Command search' })).toBeNull();
});

it('S types into the box once it is open, and Escape puts it away', async () => {
  const user = userEvent.setup();
  render(<Workspace onCommand={vi.fn()} />);
  await user.click(screen.getByRole('button', { name: 'Select' }));
  await user.keyboard('s');
  await user.keyboard('shell');
  expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('shell');
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog', { name: 'Command search' })).toBeNull();
  // Asked again, it opens empty.
  await user.click(screen.getByRole('button', { name: 'Select' }));
  await user.keyboard('s');
  expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('');
});

it('S does nothing without the workspace, as in Simple view', async () => {
  const user = userEvent.setup();
  render(<Workspace onCommand={vi.fn()} active={false} />);
  await user.click(screen.getByRole('button', { name: 'Select' }));
  await user.keyboard('s');
  expect(screen.queryByRole('dialog', { name: 'Command search' })).toBeNull();
});

it("does not answer an S asked before the toolbar stood", () => {
  render(<Workspace onCommand={vi.fn()} fresh={3} />);
  expect(screen.queryByRole('dialog', { name: 'Command search' })).toBeNull();
});
