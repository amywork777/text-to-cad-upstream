import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import EditRibbon from '../../../../dist/renderers/xbf/edit/EditRibbon.js';

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// The viewer's tools as the strip hands them to the ribbon, under the strip's names.
const tool = (id: string, label: string) => ({ id, label, icon: <svg />, active: false, disabled: false, onSelect: vi.fn() });
const PART_TOOLS = [tool('select', 'Select'), tool('measure', 'Measure'), tool('clip', 'Clip'), tool('pencil', 'Pencil'), tool('shapes', 'Shapes')];
const ASSEMBLY_TOOLS = [...PART_TOOLS, tool('exploded', 'Explode')];
const SKETCH = { name: 'Sketch1', state: { curves: [], status: 'Fully defined' } };

function edit(patch: Record<string, unknown> = {}) {
  return {
    status: 'ready', saving: false, rolling: false, error: '', state: { units: 'mm', components: [], drawing: null },
    command: null, inspecting: null, picking: false, sketch: null, canUndo: true, canRedo: true,
    undo: vi.fn(), redo: vi.fn(), open: vi.fn(), close: vi.fn(), inspect: vi.fn(), stopInspecting: vi.fn(),
    startPicking: vi.fn(), stopPicking: vi.fn(), exitSketch: vi.fn(), lookNormalTo: vi.fn(), drawing: vi.fn(), 
    sketchTool: null, sketchSelection: [], construction: false, setSketchTool: vi.fn(), setConstruction: vi.fn(), selectInSketch: vi.fn(), sketchOp: vi.fn(),
    ...patch,
  };
}

const tabNames = () => screen.getAllByRole('tab').map(tab => tab.textContent);
const frontTab = () => screen.getAllByRole('tab').find(tab => tab.getAttribute('aria-selected') === 'true')?.textContent;
// A group's title is also its menu; what else is in it are its commands.
const menuButton = (group: HTMLElement) => within(group).getAllByRole('button').find(button => button.getAttribute('aria-haspopup') === 'menu')!;
const commandButtons = (group: HTMLElement) => within(group).queryAllByRole('button').filter(button => button.getAttribute('aria-haspopup') !== 'menu');
const group = (title: string) => screen.getByRole('group', { name: title });
const commandsIn = (title: string) => commandButtons(group(title)).map(button => button.getAttribute('aria-label'));
const command = (title: string, name: string) => commandButtons(group(title)).find(button => button.getAttribute('aria-label') === name)!;
// Every group of the tab in front with the commands it shows as buttons.
const layout = () => Object.fromEntries(screen.getAllByRole('group')
  .map(each => [each.getAttribute('aria-label'), commandButtons(each).map(button => button.getAttribute('aria-label'))]));

it("opens a group's command from its menu", async () => {
  const user = userEvent.setup();
  const onCommand = vi.fn();
  render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} onCommand={onCommand} />);
  // Create's commands show as buttons; the group's title is its menu, with all of them.
  expect(commandsIn('Create')).toEqual(['Sketch', 'Extruded Boss/Base', 'Extruded Cut', 'Revolved Boss/Base', 'Revolved Cut', 'Swept Boss/Base', 'Lofted Boss/Base', 'Rib', 'Hole Wizard', 'Pattern', 'Mirror']);
  await user.click(menuButton(group('Create')));
  const menu = screen.getByRole('menu');
  expect(within(menu).getAllByRole('menuitemcheckbox').map(item => item.textContent)).toEqual(['Sketch', 'Extruded Boss/Base', 'Extruded Cut', 'Revolved Boss/Base', 'Revolved Cut',
    'Swept Boss/Base', 'Lofted Boss/Base', 'Rib', 'Hole Wizard', 'Pattern', 'Mirror']);
  await user.click(within(menu).getByText('Lofted Boss/Base'));
  expect(onCommand).toHaveBeenCalledWith('loft');
  expect(screen.queryByRole('menu')).toBeNull();
});

it("has no agent in it: no Ask the agent group, and no Ask, Add to context or Annotate, though the strip has Pencil and Shapes", () => {
  // The strip's Pencil and Shapes are Annotate's tools; the workspace is no place for them either.
  render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} />);
  expect(Object.keys(layout())).toEqual(['Create', 'Modify', 'Construct']);
  expect(screen.queryByRole('group', { name: 'Ask the agent' })).toBeNull();
  const named = screen.getAllByRole('button').map(button => button.getAttribute('aria-label') || button.textContent);
  expect(named.filter(name => ['Ask', 'Add to context', 'Annotate', 'Pencil', 'Shapes'].includes(name || ''))).toEqual([]);
});

it("heads the toolbar with Features, Sketch and Evaluate, and Drawing where a part has its sheet; an assembly with Assembly, then Evaluate", () => {
  const { rerender } = render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} />);
  expect(tabNames()).toEqual(['Features', 'Sketch', 'Evaluate', 'Drawing']);
  expect(frontTab()).toBe('Features');
  // An assembly places its parts, each modeled on its own: no Features or Sketch tab of commands that cannot run there,
  // and no sheet. It opens on Assembly, as SolidWorks' assembly CommandManager does.
  rerender(<EditRibbon tools={ASSEMBLY_TOOLS} edit={edit({ state: { units: 'mm', components: [{ id: 'base' }], drawing: null } }) as never} />);
  expect([tabNames(), frontTab()]).toEqual([['Assembly', 'Evaluate'], 'Assembly']);
});

it("groups the Features tab's commands as the design does, each under SolidWorks' name", () => {
  render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} />);
  expect(layout()).toEqual({
    Create: ['Sketch', 'Extruded Boss/Base', 'Extruded Cut', 'Revolved Boss/Base', 'Revolved Cut', 'Swept Boss/Base', 'Lofted Boss/Base', 'Rib', 'Hole Wizard', 'Pattern', 'Mirror'],
    Modify: ['Move Face', 'Fillet', 'Chamfer', 'Shell', 'Draft', 'Split', 'Delete Face', 'Delete/Keep Body'],
    Construct: ['Plane'],
  });
});

it("leaves the view's own tools to its strip: no Select, Measure, Section View or Exploded View on any tab", async () => {
  const user = userEvent.setup();
  render(<EditRibbon tools={ASSEMBLY_TOOLS} edit={edit({ state: { units: 'mm', components: [{ id: 'base' }], drawing: null } }) as never} onNormalTo={vi.fn()} />);
  for (const name of tabNames()) {
    await user.click(screen.getByRole('tab', { name: name! }));
    const named = screen.getAllByRole('button').map(button => button.getAttribute('aria-label') || button.textContent);
    expect([name, named.filter(each => ['Select', 'Measure', 'Section View', 'Exploded View'].includes(each || ''))]).toEqual([name, []]);
  }
});

it("gives every command of the old Analysis, View and Assemblies tabs a group", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} onNormalTo={vi.fn()} />);
  await user.click(screen.getByRole('tab', { name: 'Evaluate' }));
  expect(layout()).toEqual({
    Mass: ['Mass Properties'],
    Analyze: ['Draft Analysis', 'Interference Detection', 'Compare'],
    Display: ['Normal To', 'Appearance'],
    Equations: ['Equations'],
  });
  // An assembly has no body of its own to analyze or color.
  rerender(<EditRibbon tools={ASSEMBLY_TOOLS} edit={edit({ state: { units: 'mm', components: [{ id: 'base' }], drawing: null } }) as never} onNormalTo={vi.fn()} />);
  expect(layout()).toEqual({
    Mass: ['Mass Properties'],
    Analyze: ['Interference Detection'],
    Display: ['Normal To'],
    Equations: ['Equations'],
  });
  await user.click(screen.getByRole('tab', { name: 'Assembly' }));
  expect(layout()).toEqual({ Constraints: ['Insert Components', 'Mate'] });
});

it("names each group's menu apart from a command of the same name, the group's word in its name", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} onNormalTo={vi.fn()} />);
  // Equations is a group and its one command, so a button called by that name is the command, and one call finds one.
  const menuOf = (title: string) => within(group(title)).getByRole('button', { name: `${title} commands` });
  const namesOnTab = () => screen.getAllByRole('button').map(button => button.getAttribute('aria-label') || '');
  for (const title of ['Create', 'Modify', 'Construct']) {
    // The title is what the menu shows, and is in the name it is called by.
    expect([menuOf(title).getAttribute('aria-haspopup'), menuOf(title).textContent]).toEqual(['menu', title]);
  }
  await user.click(screen.getByRole('tab', { name: 'Evaluate' }));
  expect(screen.getAllByRole('button', { name: 'Equations' })).toHaveLength(1);
  for (const title of ['Mass', 'Analyze', 'Display', 'Equations']) expect(menuOf(title).textContent).toBe(title);
  rerender(<EditRibbon tools={ASSEMBLY_TOOLS} edit={edit({ state: { units: 'mm', components: [{ id: 'base' }], drawing: null } }) as never} onNormalTo={vi.fn()} />);
  await user.click(screen.getByRole('tab', { name: 'Assembly' }));
  expect(menuOf('Constraints').textContent).toBe('Constraints');
  // No two buttons of the toolbar are called alike.
  const names = namesOnTab().filter(Boolean);
  expect(new Set(names).size).toBe(names.length);
});

it("keeps the drawing's commands in the Drawing tab", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} />);
  await user.click(screen.getByRole('tab', { name: 'Drawing' }));
  expect(layout()).toEqual({ Sheet: ['Make Drawing'] });
  rerender(<EditRibbon tools={PART_TOOLS} edit={edit({ state: { units: 'mm', components: [], drawing: { sheets: 1 } } }) as never} />);
  expect(layout()).toEqual({ Sheet: ['Drawing'] });
});

it("opens Expressions in the place the other Evaluate panels open, and puts it away again", async () => {
  const user = userEvent.setup();
  const hand = edit();
  const { rerender } = render(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  await user.click(screen.getByRole('tab', { name: 'Evaluate' }));
  await user.click(command('Equations', 'Equations'));
  expect(hand.inspect).toHaveBeenCalledWith('expressions');
  const open = edit({ inspecting: 'expressions' });
  rerender(<EditRibbon tools={PART_TOOLS} edit={open as never} />);
  expect(command('Equations', 'Equations').getAttribute('aria-pressed')).toBe('true');
  await user.click(command('Equations', 'Equations'));
  expect(open.stopInspecting).toHaveBeenCalled();
});

it("holds Undo and Redo at the tab row's left, and the build status and units at its right", async () => {
  const user = userEvent.setup();
  const hand = edit({ canRedo: false });
  render(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  const row = screen.getByRole('tablist').parentElement!;
  const undo = within(row).getByRole('button', { name: 'Undo' });
  const redo = within(row).getByRole('button', { name: 'Redo' }) as HTMLButtonElement;
  const tabs = within(row).getAllByRole('tab');
  const after = (first: Element, second: Element) => Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
  expect(after(undo, redo) && after(redo, tabs[0])).toBe(true);
  expect(after(tabs.at(-1)!, within(row).getByText('Saved')) && after(within(row).getByText('Saved'), within(row).getByText('Millimeters'))).toBe(true);
  // They are no group of the toolbar: Undo and Redo are small icons beside the tabs.
  expect(screen.queryByRole('group', { name: 'Edit' })).toBeNull();
  expect(redo.disabled).toBe(true);
  await user.click(undo);
  expect(hand.undo).toHaveBeenCalledTimes(1);
});

it("holds the Sketch command alone in the Sketch tab while no sketch is open", async () => {
  const user = userEvent.setup();
  const onSketch = vi.fn();
  const { rerender } = render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} onSketch={onSketch} />);
  await user.click(screen.getByRole('tab', { name: 'Sketch' }));
  expect(layout()).toEqual({ 'Direct Sketch': ['Sketch'] });
  await user.click(command('Direct Sketch', 'Sketch'));
  expect(onSketch).toHaveBeenCalledTimes(1);
  // Edit Sketch, with a sketch selected in the design tree.
  rerender(<EditRibbon tools={PART_TOOLS} edit={edit() as never} onSketch={onSketch} sketchLabel="Edit Sketch" />);
  expect(layout()).toEqual({ 'Direct Sketch': ['Edit Sketch'] });
});

it("brings the Sketch tab to the front while a sketch is open, and Exit Sketch returns to Features", async () => {
  const user = userEvent.setup();
  const sketching = edit({ sketch: SKETCH });
  const { rerender } = render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} />);
  await user.click(screen.getByRole('tab', { name: 'Evaluate' }));
  expect(frontTab()).toBe('Evaluate');
  // The sketch task environment as it has been: its own tools, Exit Sketch first.
  rerender(<EditRibbon tools={PART_TOOLS} edit={sketching as never} />);
  expect(tabNames()).toEqual(['Sketch']);
  expect(frontTab()).toBe('Sketch');
  expect(Object.keys(layout())).toEqual(['Sketch', 'Curve', 'Edit Curve', 'Constraints', 'Feature']);
  expect(commandsIn('Sketch')).toEqual(['Exit Sketch', 'Smart Dimension', 'Normal To']);
  await user.click(command('Sketch', 'Exit Sketch'));
  expect(sketching.exitSketch).toHaveBeenCalledTimes(1);
  // It ends: Features, not the tab it was opened from.
  rerender(<EditRibbon tools={PART_TOOLS} edit={edit() as never} />);
  expect(tabNames()).toEqual(['Features', 'Sketch', 'Evaluate', 'Drawing']);
  expect(frontTab()).toBe('Features');
});

/**
 * jsdom lays nothing out: each group is 150px wide with its names and 100px without them, its buttons on
 * a 50px pitch, and the row `width`, less the More button's 46px while it stands beside the row. Returns the undo.
 */
function layOutRibbon(width = 260) {
  const keys = ['offsetWidth', 'clientWidth', 'offsetLeft'] as const;
  const saved = keys.map(key => Object.getOwnPropertyDescriptor(HTMLElement.prototype, key));
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get(this: HTMLElement) {
    if (this.hasAttribute('data-cad-ribbon-group')) return this.closest('[data-compact="true"]') ? 100 : 150;
    return this.hasAttribute('data-cad-ribbon-more') ? 46 : 0;
  } });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get(this: HTMLElement) {
    if (!this.hasAttribute('data-compact')) return 0;
    return this.parentElement?.querySelector('[data-cad-ribbon-more]') ? width - 46 : width;
  } });
  Object.defineProperty(HTMLElement.prototype, 'offsetLeft', { configurable: true, get(this: HTMLElement) {
    const item = this.parentElement!;
    return item.parentElement?.hasAttribute('data-cad-ribbon-items') ? [...item.parentElement.children].indexOf(item) * 50 : 0;
  } });
  return () => keys.forEach((key, index) => {
    const descriptor = saved[index];
    if (descriptor) Object.defineProperty(HTMLElement.prototype, key, descriptor); else delete (HTMLElement.prototype as any)[key];
  });
}

// A folded group is hidden from the accessibility tree, so it has no name to be found by.
const foldedGroups = () => ['Create', 'Modify', 'Construct'].map(title =>
  document.querySelector<HTMLElement>(`[role="group"][aria-label="${title}"]`)!.getAttribute('aria-hidden'));

it("shows as much of the next group as fits, its title the menu of all of it, and folds the rest into More", () => {
  const restore = layOutRibbon();
  try {
    render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} />);
    // Three groups need 450px with their names in a 260px row: one fits beside More, named as it is on a wide
    // row, and one button of the next (150 + 4 + 50 of 215px); the last is whole behind More.
    expect(screen.getByRole('button', { name: 'More commands' })).toBeTruthy();
    expect(foldedGroups()).toEqual([null, null, 'true']);
    expect(command('Create', 'Extruded Boss/Base').textContent).toBe('Extruded Boss/Base');
    const modify = screen.getByRole('group', { name: 'Modify' });
    const buttons = [...modify.querySelectorAll('[data-cad-ribbon-items] > *')];
    expect(buttons.filter(button => !button.className.includes('invisible'))).toHaveLength(1);
    expect(within(modify).getByRole('button', { name: 'Modify commands' })).toBeTruthy();
  } finally {
    restore();
  }
});

it("shows no More while only part of the last group is off the row", () => {
  const restore = layOutRibbon(660);
  try {
    render(<EditRibbon tools={PART_TOOLS} edit={edit({ sketch: SKETCH }) as never} />);
    // The Sketch tab's four groups and a button of its last fit in 660px: no whole group is off the row.
    expect(screen.queryByRole('button', { name: 'More commands' })).toBeNull();
    expect(screen.getByRole('group', { name: 'Feature' }).getAttribute('aria-hidden')).toBeNull();
    expect(screen.getByRole('button', { name: 'Feature commands' })).toBeTruthy();
  } finally {
    restore();
  }
});

it("drops the names only where not even one named group fits beside More", () => {
  const restore = layOutRibbon(180);
  try {
    render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} />);
    // A named group's 150px does not fit in 180px less More's 46px; 100px without its names does.
    expect(foldedGroups()).toEqual([null, 'true', 'true']);
    expect(command('Create', 'Extruded Boss/Base').textContent).toBe('');
  } finally {
    restore();
  }
});

it("holds the view's own controls and its catching-up at the tab row's right end, before the build status and units", () => {
  // What the frame hands the toolbar of the view (`RendererShell`'s `ribbon(tools, view)`): Projection, Display and
  // Preview as small tiles, and the view catching up.
  const view = { controls: <button type="button" aria-label="Display mode: Solid" />, status: <span>Updating model…</span> };
  const { rerender } = render(<EditRibbon tools={PART_TOOLS} edit={edit() as never} view={view} />);
  const after = (first: Element, second: Element) => Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
  const order = () => {
    const row = screen.getByRole('tablist').parentElement!;
    const display = within(row).getByRole('button', { name: 'Display mode: Solid' }), status = within(row).getByText('Updating model…');
    const build = within(row).getByText(/^(Saved|Editing Sketch1)$/), units = within(row).queryByText('Millimeters') || build;
    return [after(screen.getAllByRole('tab').at(-1)!, display), after(display, status), after(status, build), build === units || after(build, units)];
  };
  expect(order()).toEqual([true, true, true, true]);
  // A sketch's tab row has them too.
  rerender(<EditRibbon tools={PART_TOOLS} edit={edit({ sketch: SKETCH }) as never} view={view} />);
  expect(order()).toEqual([true, true, true, true]);
});

// ---- command search: the box S opens (`CommandSearchBox.jsx`), under the toolbar, listing what the toolbar has ----

const search = () => screen.getByRole('dialog', { name: 'Command search' });
const searchGone = () => expect(screen.queryByRole('dialog', { name: 'Command search' })).toBeNull();
const found = () => within(search()).queryAllByRole('option');
const foundNames = () => found().map(row => row.textContent);
const foundRow = (name: string) => within(search()).getByRole('option', { name });
type Hand = ReturnType<typeof edit>;
/** The toolbar with the box open, as S asks for it: edit mode counts one more ask than it had. */
function openSearch(patch: Record<string, unknown> = {}, props: Record<string, unknown> = {}) {
  const hand = edit({ findAsked: 0, ...patch });
  const view = render(<EditRibbon tools={PART_TOOLS} edit={hand as never} {...props} />);
  const ask = () => { hand.findAsked = (hand.findAsked as number) + 1; view.rerender(<EditRibbon tools={PART_TOOLS} edit={hand as never} {...props} />); };
  ask();
  return { hand: hand as Hand, ask, ...view };
}
const PART_NAMES = ['Sketch', 'Extruded Boss/Base', 'Extruded Cut', 'Revolved Boss/Base', 'Revolved Cut', 'Swept Boss/Base', 'Swept Cut',
  'Lofted Boss/Base', 'Lofted Cut', 'Rib', 'Hole Wizard', 'Pattern', 'Mirror', 'Move Face', 'Fillet', 'Chamfer', 'Shell', 'Draft',
  'Split', 'Delete Face', 'Delete/Keep Body', 'Plane', 'Measure', 'Mass Properties', 'Draft Analysis', 'Interference Detection', 'Compare',
  'Section View', 'Normal To', 'Appearance', 'Equations', 'Make Drawing'];
const ASSEMBLY = { units: 'mm', components: [{ id: 'base' }], drawing: null };

it("opens the box when S asks, beside the toolbar and not in it, listing the commands of every tab and not the one in front", () => {
  const { hand } = openSearch();
  expect(foundNames()).toEqual(PART_NAMES);
  // The toolbar clips what overflows it, so the box is its neighbour; the Features tab is in front all the while.
  expect(screen.getByRole('toolbar').contains(search())).toBe(false);
  expect(search().parentElement).toBe(screen.getByRole('toolbar').parentElement);
  expect(frontTab()).toBe('Features');
  expect(hand.open).not.toHaveBeenCalled();
});

it("opens for each ask made while the toolbar stands, once, and not for one made before it stood", async () => {
  const user = userEvent.setup();
  const hand = edit({ findAsked: 2 });
  const view = render(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  searchGone();
  hand.findAsked = 3;
  view.rerender(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  expect(search()).toBeTruthy();
  // Put away, it stays so through the toolbar being drawn again, until it is asked for once more.
  await user.keyboard('{Escape}');
  searchGone();
  view.rerender(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  searchGone();
  hand.findAsked = 4;
  view.rerender(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  expect(search()).toBeTruthy();
});

it("shows the search in the tab row, as SolidWorks' Search Commands is, and opens the box from it as S does", async () => {
  const user = userEvent.setup();
  const hand = edit({ findAsked: 0 });
  render(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  searchGone();
  const finder = screen.getByRole('button', { name: /Search commands/ });
  expect(finder.getAttribute('aria-keyshortcuts')).toBe('S');
  await user.click(finder);
  expect(foundNames()).toEqual(PART_NAMES);
});

it("lists only the tabs the toolbar has: Assembly for an assembly, Drawing for a part that has its sheet", () => {
  const withSheet = openSearch({ state: { units: 'mm', components: [], drawing: { sheets: 1 } } });
  expect(foundNames()).toEqual(expect.arrayContaining(['Drawing']));
  for (const name of ['Make Drawing', 'Mate', 'Exploded View']) expect(foundNames()).not.toContain(name);
  withSheet.unmount();
  openSearch({ state: ASSEMBLY }, { tools: ASSEMBLY_TOOLS });
  expect(foundNames()).toEqual(expect.arrayContaining(['Mate', 'Exploded View', 'Interference Detection']));
  // An assembly has no body of its own to analyze or color, and no sheet.
  for (const name of ['Draft Analysis', 'Compare', 'Appearance', 'Make Drawing', 'Drawing']) expect(foundNames()).not.toContain(name);
});

it("runs a command through the toolbar's own onCommand, a fillet and a cut by the words other tools use", async () => {
  const user = userEvent.setup();
  const onCommand = vi.fn();
  const first = openSearch({}, { onCommand });
  await user.keyboard('round{Enter}');
  expect(onCommand).toHaveBeenLastCalledWith('fillet');
  searchGone();
  first.unmount();
  const second = openSearch({}, { onCommand });
  await user.keyboard('pocket{Enter}');
  expect(onCommand).toHaveBeenLastCalledWith('cut');
  expect(onCommand).toHaveBeenCalledTimes(2);
  expect(second.hand.open).not.toHaveBeenCalled();
});

it("leaves the command open that is already open, and turns an open Extruded Boss/Base to its Cut", async () => {
  const user = userEvent.setup();
  const onCommand = vi.fn();
  const open = openSearch({ command: 'extrude' }, { onCommand });
  await user.keyboard('extrude{Enter}');
  expect(onCommand).not.toHaveBeenCalled();
  expect(open.hand.close).not.toHaveBeenCalled();
  open.unmount();
  const turned = openSearch({ command: 'extrude' }, { onCommand });
  await user.keyboard('cut{Enter}');
  expect(onCommand).toHaveBeenCalledWith('cut');
  expect(turned.hand.close).not.toHaveBeenCalled();
});

it("starts Sketch as the Sketch button does, and leaves one that waits for its plane waiting", async () => {
  const user = userEvent.setup();
  const onSketch = vi.fn();
  // Found by another tool's word for it (Make Drawing is found by its name before it, so "draw" no longer leads to it).
  const first = openSearch({}, { onSketch });
  await user.keyboard('profile{Enter}');
  expect(onSketch).toHaveBeenCalledTimes(1);
  first.unmount();
  const waiting = openSearch({ picking: true }, { onSketch });
  await user.keyboard('sketch{Enter}');
  expect(onSketch).toHaveBeenCalledTimes(1);
  expect(waiting.hand.stopPicking).not.toHaveBeenCalled();
  waiting.unmount();
  // On a sketch selected in the design tree the button reads Edit Sketch, and so does the box.
  openSearch({}, { onSketch, sketchLabel: 'Edit Sketch' });
  await user.keyboard('edit sk');
  expect(foundNames()).toEqual(['Edit Sketch']);
  await user.keyboard('{Enter}');
  expect(onSketch).toHaveBeenCalledTimes(2);
});

it("opens an Evaluate panel as its button does, from any tab, and leaves one that is open", async () => {
  const user = userEvent.setup();
  const first = openSearch();
  expect(frontTab()).toBe('Features');
  await user.keyboard('draft analysis{Enter}');
  expect(first.hand.inspect).toHaveBeenCalledWith('draft');
  first.unmount();
  const open = openSearch({ inspecting: 'draft' });
  await user.keyboard('draft analysis{Enter}');
  expect(open.hand.inspect).not.toHaveBeenCalled();
  expect(open.hand.stopInspecting).not.toHaveBeenCalled();
  open.unmount();
  const weighed = openSearch();
  await user.keyboard('mass properties{Enter}');
  expect(weighed.hand.inspect).toHaveBeenCalledWith('mass');
});

it("selects a tool of the strip as its button does, and not again one that is in hand", async () => {
  const user = userEvent.setup();
  const section = tool('clip', 'Clip');
  const measure = { ...tool('measure', 'Measure'), active: true };
  const tools = [tool('select', 'Select'), measure, section];
  const first = openSearch({}, { tools });
  await user.keyboard('section{Enter}');
  expect(section.onSelect).toHaveBeenCalledTimes(1);
  first.ask();
  await user.keyboard('distance{Enter}');
  expect(measure.onSelect).not.toHaveBeenCalled();
  searchGone();
});

it("lists a command the toolbar shows dimmed as dimmed, with the toolbar's reason, and runs none of them", async () => {
  const user = userEvent.setup();
  const onCommand = vi.fn();
  openSearch({ state: ASSEMBLY }, { onCommand, tools: ASSEMBLY_TOOLS, canOpenParts: true });
  await user.keyboard('extrude');
  expect(foundRow('Extruded Boss/Base').getAttribute('aria-disabled')).toBe('true');
  expect(within(search()).getByRole('status').textContent).toBe('This is the assembly. Isolate a part to edit it: double-click it in the design tree.');
  await user.keyboard('{Enter}');
  expect(onCommand).not.toHaveBeenCalled();
  expect(search()).toBeTruthy();
  // The toolbar has no tab for them at all in an assembly.
  await user.keyboard('{Escape}');
  expect(tabNames()).not.toContain('Features');
});

it("dims what the toolbar dims while a change is made, and Normal To until there is something to look at", async () => {
  const user = userEvent.setup();
  const onNormalTo = vi.fn();
  const busy = openSearch({ saving: true });
  const dimmed = found().filter(row => row.getAttribute('aria-disabled') === 'true').map(row => row.textContent);
  expect(dimmed).toEqual(expect.arrayContaining(['Sketch', 'Extruded Boss/Base', 'Hole Wizard', 'Plane', 'Make Drawing']));
  expect(busy.hand.open).not.toHaveBeenCalled();
  busy.unmount();
  const nothing = openSearch({}, { onNormalTo: null });
  // Found by NX's Orient View, now another tool's word for it.
  await user.keyboard('orient');
  expect(foundRow('Normal To').getAttribute('aria-disabled')).toBe('true');
  expect(within(search()).getByRole('status').textContent).toMatch(/Select a flat face/);
  await user.keyboard('{Enter}');
  expect(onNormalTo).not.toHaveBeenCalled();
  nothing.unmount();
  openSearch({}, { onNormalTo });
  await user.keyboard('look at{Enter}');
  expect(onNormalTo).toHaveBeenCalledTimes(1);
});

it("lists a sketch's own tools and the features made of it while a sketch is open, and runs each as its button does", async () => {
  const user = userEvent.setup();
  const onCommand = vi.fn();
  const exitSketch = vi.fn().mockResolvedValue({ ok: true });
  const first = openSearch({ sketch: SKETCH, exitSketch }, { onCommand });
  const names = foundNames();
  expect(names.slice(0, 3)).toEqual(['Exit Sketch', 'Smart Dimension', 'Normal To']);
  expect(names).toEqual(expect.arrayContaining(['Line', 'Corner Rectangle', 'Center Rectangle', 'Perimeter Circle', 'Tangent Arc',
    'Centerpoint Straight Slot', 'Spline', 'Smart Dimension', 'Construction Geometry', 'Trim Entities', 'Copy Entities', 'Circular Sketch Pattern']));
  // The features it is made into, but not what the sketch environment does not have.
  expect(names).toEqual(expect.arrayContaining(['Extruded Boss/Base', 'Extruded Cut', 'Revolved Boss/Base', 'Swept Boss/Base', 'Lofted Boss/Base', 'Rib']));
  for (const name of ['Hole Wizard', 'Fillet', 'Plane', 'Measure', 'Sketch', 'Draft Analysis', 'Make Drawing', 'Mirror']) expect(names).not.toContain(name);
  // Fillet is the sketch's own fillet here.
  await user.keyboard('fillet');
  expect(foundNames()).toEqual(['Sketch Fillet']);
  await user.keyboard('{Enter}');
  expect(first.hand.setSketchTool).toHaveBeenCalledWith('fillet');
  expect(onCommand).not.toHaveBeenCalled();
  first.unmount();
  // A feature finishes the sketch first, then opens, as its button in the Feature group does.
  const made = openSearch({ sketch: SKETCH, exitSketch }, { onCommand });
  await user.keyboard('pocket{Enter}');
  await vi.waitFor(() => expect(onCommand).toHaveBeenCalledWith('cut'));
  expect(exitSketch).toHaveBeenCalledTimes(1);
  expect(made.hand.open).not.toHaveBeenCalled();
});

it("leaves the sketch tool in hand in hand when its name is run, and finishes the sketch from the box", async () => {
  const user = userEvent.setup();
  const holding = openSearch({ sketch: SKETCH, sketchTool: 'line' });
  await user.keyboard('line{Enter}');
  expect(holding.hand.setSketchTool).not.toHaveBeenCalled();
  holding.unmount();
  const done = openSearch({ sketch: SKETCH });
  await user.keyboard('finish{Enter}');
  expect(done.hand.exitSketch).toHaveBeenCalledTimes(1);
});

it("presses Construction Geometry whether it is on or off, as it is a switch", async () => {
  const user = userEvent.setup();
  const off = openSearch({ sketch: SKETCH });
  await user.keyboard('construction{Enter}');
  expect(off.hand.setConstruction).toHaveBeenCalledWith(true);
  off.unmount();
  const on = openSearch({ sketch: SKETCH, construction: true });
  await user.keyboard('construction{Enter}');
  expect(on.hand.setConstruction).toHaveBeenCalledWith(false);
});

// What the toolbar has: every group's whole menu, tab by tab, and a sketch's flyouts. A menu names a tool by its key too ("Line (L)").
const unkeyed = (text: string) => text.replace(/ \([A-Z]\)$/, '');
async function menuOf(user: ReturnType<typeof userEvent.setup>, trigger: HTMLElement) {
  await user.click(trigger);
  const menu = screen.getByRole('menu');
  const names = [...within(menu).queryAllByRole('menuitem'), ...within(menu).queryAllByRole('menuitemcheckbox')].map(row => unkeyed(row.textContent || ''));
  await user.keyboard('{Escape}');
  return names;
}
async function toolbarHas(user: ReturnType<typeof userEvent.setup>) {
  const names = new Set<string>();
  const titles = () => screen.getAllByRole('button').filter(button => button.getAttribute('aria-haspopup') === 'menu' && button.getAttribute('aria-label') !== 'More commands');
  for (const tab of screen.getAllByRole('tab')) {
    await user.click(tab);
    for (const trigger of titles()) (await menuOf(user, trigger)).forEach(name => names.add(name));
  }
  return names;
}

it("never disagrees with the toolbar: it lists each command of every tab the toolbar has, under the same name, and nothing else", async () => {
  const user = userEvent.setup();
  // The strip's tools are the view's, found by the search though the toolbar has no button for them.
  const STRIP = new Set(['Select', 'Measure', 'Section View', 'Exploded View']);
  const states: [string, Record<string, unknown>, Record<string, unknown>][] = [
    ['a part', {}, {}],
    ['a part with its sheet', { state: { units: 'mm', components: [], drawing: { sheets: 1 } } }, {}],
    ['an assembly', { state: ASSEMBLY }, { tools: ASSEMBLY_TOOLS }],
  ];
  for (const [name, patch, props] of states) {
    const shown = { onNormalTo: vi.fn(), ...props };
    const hand = edit({ findAsked: 0, ...patch });
    const view = render(<EditRibbon tools={PART_TOOLS} edit={hand as never} {...shown} />);
    const has = await toolbarHas(user);
    hand.findAsked = 1;
    view.rerender(<EditRibbon tools={PART_TOOLS} edit={hand as never} {...shown} />);
    // A cut is the Cut of its Boss/Base's Boolean: the toolbar has it in Extruded Boss/Base's dialog, not as a button.
    const listed = new Set(foundNames().filter(text => text !== 'Swept Cut' && text !== 'Lofted Cut'));
    // An assembly's search finds the part commands too, though it has no tab of them, each dimmed.
    const dimmed = new Set(found().filter(row => row.getAttribute('aria-disabled') === 'true').map(row => row.textContent));
    const partOnly = name === 'an assembly' ? [...listed].filter(each => !has.has(each) && !STRIP.has(each)) : [];
    expect([name, partOnly.filter(each => !dimmed.has(each))]).toEqual([name, []]);
    expect([name, [...listed].filter(each => !STRIP.has(each) && !partOnly.includes(each)).sort()]).toEqual([name, [...has].sort()]);
    cleanup();
  }
});

it("never disagrees with the toolbar while a sketch is open: every tool of every flyout, and the Feature group", async () => {
  const user = userEvent.setup();
  const hand = edit({ findAsked: 0, sketch: SKETCH });
  const view = render(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  const has = new Set(screen.getAllByRole('group').flatMap(group => commandButtons(group).map(button => button.getAttribute('aria-label') || '')));
  // A family's button is the tool last picked of it; its flyout has them all.
  for (const flyout of ['Rectangle tools', 'Circle tools', 'Arc tools', 'Slot tools', 'Move Entities tools']) {
    (await menuOf(user, screen.getByRole('button', { name: flyout }))).forEach(name => has.add(name));
  }
  hand.findAsked = 1;
  view.rerender(<EditRibbon tools={PART_TOOLS} edit={hand as never} />);
  // The cuts are each Boss/Base's Boolean in its dialog, not buttons of the Feature group.
  const listed = new Set(foundNames().filter(text => !text.endsWith(' Cut')));
  expect([...listed].sort()).toEqual([...has].sort());
});

it("opens a model effect's row under the toolbar when the search runs it, for a tool with nothing to take in hand", async () => {
  const user = userEvent.setup();
  // Section View and Exploded View come from the strip as popovers, with no onSelect.
  const popover = vi.fn(({ open }: { open: boolean }) => (open ? <div role="dialog" aria-label="Clip row" /> : null));
  const clip = { id: 'clip', label: 'Clip', icon: <svg />, disabled: false, popover };
  openSearch({}, { tools: [tool('select', 'Select'), tool('measure', 'Measure'), clip] });
  await user.keyboard('section{Enter}');
  expect(screen.getByRole('dialog', { name: 'Clip row' })).toBeTruthy();
  const asked = popover.mock.calls.at(-1)![0] as unknown as { open: boolean; anchor: { current: Element } };
  expect(asked.open).toBe(true);
  expect(asked.anchor.current.contains(screen.getByRole('toolbar'))).toBe(true);
});
