import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import EditTree from '../../../../dist/renderers/xbf/edit/EditTree.js';
import { featureTree } from '../../../../dist/renderers/xbf/edit/editMode.js';

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

// A block filleted, the fillet renamed in the tree, and a sketch nothing uses yet.
const STATE = {
  units: 'mm', name: 'block', params: [], rows: [],
  features: [
    { key: 'block.py:6', kind: 'Boss-Extrude', name: 'part', file: 'block.py', line: 6 },
    { key: 'block.py:7', kind: 'Fillet', name: 'part', file: 'block.py', line: 7, named: 'Top edge round' },
    { key: 'block.py:8', kind: 'Fillet', name: 'part', file: 'block.py', line: 8 },
    { key: 'block.py:9', kind: 'Sketch', file: 'block.py', line: 9,
      sketch: { name: 'Sketch1', plane: 'Top', file: 'block.py', line: 9, status: 'Fully defined' } },
  ],
};

function edit(renaming: string | null = null) {
  return { status: 'ready', saving: false, state: STATE, selected: null, renaming, bar: null, sketch: null,
    select: vi.fn(), hover: vi.fn(), rename: vi.fn(), startRename: vi.fn(), stopRename: vi.fn(), remove: vi.fn(), suppress: vi.fn(),
    rollTo: vi.fn(), editFeature: vi.fn() };
}

it("a renamed feature shows its own name and the tree still counts it, and its name is typed over in place", async () => {
  const user = userEvent.setup();
  const tree = featureTree(STATE);
  expect(tree.features.map((feature: { title: string }) => feature.title)).toEqual(['Boss-Extrude1', 'Top edge round', 'Fillet2', 'Sketch1']);
  const renaming = edit('block.py:8');
  render(<EditTree edit={renaming as never} tree={tree} />);
  const input = screen.getByRole('textbox', { name: 'Name' }) as HTMLInputElement;
  expect(input.value).toBe('Fillet2');
  await user.clear(input);
  await user.type(input, 'Lid edge{Enter}');
  expect(renaming.rename).toHaveBeenCalledWith({ feature: 'block.py:8', title: 'Fillet2' }, 'Lid edge');
  cleanup();
  // Escape leaves it; a sketch is renamed by where it is made.
  const sketch = edit('block.py:9');
  render(<EditTree edit={sketch as never} tree={tree} />);
  await user.type(screen.getByRole('textbox', { name: 'Name' }), 'x{Escape}');
  expect(sketch.stopRename).toHaveBeenCalled();
  expect(sketch.rename).not.toHaveBeenCalled();
});

// A bracket: a plate (an extrude a command made, from a sketch of its own), then a fillet and a hole the
// commands made. Numbered as SolidWorks does, each kind on its own: Outline (the sketch's name in its Sketch1's place),
// Boss-Extrude1, Fillet1, Hole1. The engine gives each
// feature its first line as written, and each row of the history its own. The hole is made by a helper the part calls.
const SOURCE = {
  plate: 'plate = extrude(outline, amount=THICKNESS)',
  fillet: 'plate = fillet(plate.edges().filter_by(Axis.Z), radius=WALL)',
  hole: 'plate = drill(plate, HOLE)',
};
const PART = {
  units: 'mm', name: 'bracket',
  rows: [
    { key: 'bracket.py:8', file: 'bracket.py', line: 8, code: SOURCE.plate },
    { key: 'bracket.py:9', file: 'bracket.py', line: 9, code: SOURCE.fillet },
    { key: 'bracket.py:10', file: 'bracket.py', line: 10, code: SOURCE.hole },
  ],
  params: [{ id: 'bracket.py:3', name: 'TRAY_WIDTH', text: '40', unit: 'mm' }, { id: 'bracket.py:4', name: 'WALL', text: '2', unit: 'mm' }],
  features: [
    { key: 'bracket.py:8', kind: 'Boss-Extrude', name: 'plate', file: 'bracket.py', line: 8, text: SOURCE.plate, edit: { command: 'extrude', values: {}, keeps: '' },
      sketch: { name: 'Outline', plane: 'Top', file: 'bracket.py', line: 7, status: 'Fully defined' } },
    { key: 'bracket.py:9', kind: 'Fillet', name: 'plate', file: 'bracket.py', line: 9, text: SOURCE.fillet, edit: { command: 'fillet', values: {}, keeps: '4 edges' } },
    { key: 'bracket.py:10', kind: 'Hole', name: 'plate', file: 'bracket.py', line: 10, text: SOURCE.hole, edit: { command: 'hole', values: {}, keeps: '' } },
  ],
};
const FILLET = 'bracket.py:9', HOLE = 'bracket.py:10';

function part(patch: Record<string, unknown> = {}) {
  return { ...edit(), state: PART, error: '', ...patch };
}
const partTree = () => featureTree(PART);
const row = (title: string) => screen.getByText(title).closest<HTMLElement>('[data-tree-row]')!;

/** The words of a row's menu, opened with a right-click. */
function menuOf(title: string) {
  fireEvent.contextMenu(row(title));
  return screen.getAllByRole('menuitem').map(item => item.textContent);
}

it("opens with the part's Material, then the Origin", () => {
  const { rerender } = render(<EditTree edit={part() as never} tree={partTree()} />);
  const rowsOf = () => within(screen.getByRole('tree', { name: 'FeatureManager design tree' })).getAllByRole('treeitem');
  // As SolidWorks lists it: not specified until Edit Material sets it.
  expect(rowsOf()[0].textContent).toBe('Material <not specified>');
  const rows = rowsOf().slice(1);
  expect(rows[0].textContent).toBe('Origin');
  // Drawn with the generator's coordinate system icon, its planes hanging from it, open.
  expect(rows[0].querySelector('use')?.getAttribute('href')).toBe('#nx-csys');
  expect(rows.slice(1, 4).map(each => each.textContent)).toEqual(['Front Plane', 'Top Plane', 'Right Plane']);
  // The features follow, each kind numbered on its own, its variable name at the right.
  expect(rows.slice(4).map(each => each.textContent)).toEqual(['Boss-Extrude1Plate', 'Fillet1Plate', 'Hole1Plate']);
  const named = part();
  rerender(<EditTree edit={{ ...named, state: { ...named.state, materialName: 'PLA' } } as never} tree={partTree()} />);
  expect(rowsOf()[0].textContent).toBe('PLA');
});

it("keeps Equations folded at the top", async () => {
  const user = userEvent.setup();
  const { container } = render(<EditTree edit={part() as never} tree={partTree()} />);
  const fold = screen.getByRole('button', { name: 'Equations' });
  // Above the tree, folded: the part's sizes are not listed until it is opened.
  expect(fold.getAttribute('aria-expanded')).toBe('false');
  expect(Boolean(fold.compareDocumentPosition(screen.getByRole('tree')) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
  expect(container.textContent).not.toMatch(/Tray width/);
  expect(screen.queryByRole('textbox', { name: 'Wall value' })).toBeNull();
  // Opened, it lists the part's expressions, typed over in place as the Equations dialog lists them; folded again, it puts them away.
  await user.click(fold);
  expect(fold.getAttribute('aria-expanded')).toBe('true');
  const list = screen.getByRole('group', { name: 'Equations' });
  expect(within(list).getByText('Tray width')).toBeTruthy();
  expect(within(list).getByRole('textbox', { name: 'Wall value' })).toBeTruthy();
  await user.click(fold);
  expect(screen.queryByRole('group', { name: 'Equations' })).toBeNull();
});

it("words the row menu as SolidWorks does", () => {
  // A feature a command made, with no sketch of its own.
  render(<EditTree edit={part() as never} tree={partTree()} />);
  expect(menuOf('Fillet1')).toEqual(['Edit Feature', 'Suppress', 'Rename', 'Delete', 'Rollback']);
  cleanup();
  // With a sketch it edits, Edit Sketch follows.
  render(<EditTree edit={part() as never} tree={partTree()} />);
  expect(menuOf('Boss-Extrude1')).toEqual(['Edit Feature', 'Edit Sketch', 'Suppress', 'Rename', 'Delete', 'Rollback']);
  cleanup();
  // A feature no command made has no Edit Feature.
  render(<EditTree edit={edit() as never} tree={featureTree(STATE)} />);
  expect(menuOf('Boss-Extrude1')).toEqual(['Suppress', 'Rename', 'Delete', 'Rollback']);
  cleanup();
  // A feature set aside is put back by Unsuppress.
  const aside = { ...PART, features: PART.features.map(feature => (feature.key === FILLET ? { ...feature, suppressed: true } : feature)) };
  render(<EditTree edit={part({ state: aside }) as never} tree={featureTree(aside)} />);
  expect(menuOf('Fillet1')).toEqual(['Edit Feature', 'Unsuppress', 'Rename', 'Delete', 'Rollback']);
  cleanup();
  // While the rollback bar is up, Roll to End follows Rollback.
  render(<EditTree edit={part({ bar: { item: FILLET, before: FILLET } }) as never} tree={partTree()} />);
  expect(menuOf('Hole1')).toEqual(['Edit Feature', 'Suppress', 'Rename', 'Delete', 'Rollback', 'Roll to End']);
});

it("words a sketch's menu as SolidWorks does", () => {
  const lid = {
    units: 'mm', name: 'lid', params: [], rows: [],
    features: [
      { key: 'lid.py:5', kind: 'Sketch', file: 'lid.py', line: 5, sketch: { name: 'Outline', plane: 'Top', file: 'lid.py', line: 5, status: 'Fully defined' } },
      { key: 'lid.py:9', kind: 'Boss-Extrude', name: 'lid', file: 'lid.py', line: 9, sketch: { name: 'Rim', plane: 'Top', file: 'lid.py', line: 8, status: 'Fully defined' } },
    ],
  };
  // The sketch under the extrude is shown once the extrude is open (selecting it opens its owner).
  render(<EditTree edit={{ ...part({ state: lid }), selected: 'sketch:lid.py:9' } as never} tree={featureTree(lid)} />);
  // A sketch of its own is deleted and can be rolled back to; it is not suppressed on its own.
  expect(menuOf('Outline')).toEqual(['Edit Sketch', 'Rename', 'Delete', 'Rollback']);
  cleanup();
  // The sketch an extrude is made from goes with the extrude.
  render(<EditTree edit={{ ...part({ state: lid }), selected: 'sketch:lid.py:9' } as never} tree={featureTree(lid)} />);
  expect(menuOf('Rim')).toEqual(['Edit Sketch', 'Rename']);
});

it("marks who made a feature with a dot at its row's right, said on hover, its sketch with its own, and one nobody is known to have made with none", () => {
  vi.useFakeTimers();
  const authored = { ...PART, authors: { 'bracket.py:8': 'agent', [FILLET]: 'you', [HOLE]: 'someone else' } };
  // The extrude open, the sketch it was made from under it.
  render(<EditTree edit={part({ state: authored, selected: 'sketch:bracket.py:8' }) as never} tree={featureTree(authored)} />);
  const dot = (title: string) => row(title).querySelector('[data-cad-edit-tree-author]');
  expect(['Outline', 'Boss-Extrude1', 'Fillet1', 'Hole1'].map(title => dot(title)?.getAttribute('data-cad-edit-tree-author') ?? null))
    .toEqual(['agent', 'agent', 'you', null]);
  // At the row's right, past its variable's name, and named for a screen reader.
  expect(row('Fillet1').lastElementChild?.contains(dot('Fillet1'))).toBe(true);
  expect(within(row('Boss-Extrude1')).getByRole('img', { name: 'Made by the agent' })).toBeTruthy();
  fireEvent.pointerMove(dot('Fillet1')!.parentElement!, { pointerType: 'mouse' });
  act(() => { vi.advanceTimersByTime(450); });
  expect(screen.getByRole('tooltip').textContent).toBe('Made by you');
  cleanup();
  // A part from before Studio kept track has none.
  render(<EditTree edit={part() as never} tree={partTree()} />);
  expect(document.querySelectorAll('[data-cad-edit-tree-author]').length).toBe(0);
});

it("rolls back to a feature, the bar just above it, and rolls to the end again", async () => {
  const user = userEvent.setup();
  const tree = partTree();
  // On the second of the three features, the rollback bar goes just above it: it and the hole rolled back.
  const rolling = part();
  render(<EditTree edit={rolling as never} tree={tree} />);
  fireEvent.contextMenu(row('Fillet1'));
  await user.click(screen.getByRole('menuitem', { name: 'Rollback' }));
  expect(rolling.rollTo).toHaveBeenCalledWith(FILLET);
  cleanup();
  // Nothing rolled back, there is no end to roll to.
  render(<EditTree edit={part() as never} tree={tree} />);
  expect(menuOf('Hole1')).not.toContain('Roll to End');
  cleanup();
  // With the part rolled back above the fillet, Roll to End puts the bar past the last feature.
  const back = part({ bar: { item: FILLET, before: FILLET } });
  render(<EditTree edit={back as never} tree={tree} />);
  fireEvent.contextMenu(row('Hole1'));
  await user.click(screen.getByRole('menuitem', { name: 'Roll to End' }));
  expect(back.rollTo).toHaveBeenCalledTimes(1);
  expect(back.rollTo).toHaveBeenCalledWith(null);
  cleanup();
  // Rollback on a feature below the bar moves the bar down to just above it.
  const further = part({ bar: { item: FILLET, before: FILLET } });
  render(<EditTree edit={further as never} tree={tree} />);
  fireEvent.contextMenu(row('Hole1'));
  await user.click(screen.getByRole('menuitem', { name: 'Rollback' }));
  expect(further.rollTo).toHaveBeenCalledWith(HOLE);
  // The old Make Current Feature is gone.
  cleanup();
  render(<EditTree edit={back as never} tree={tree} />);
  expect(menuOf('Hole1')).not.toContain('Make Current Feature');
});

it("leaves the bar where it is when it already sits just above the feature", async () => {
  const user = userEvent.setup();
  const tree = partTree();
  // The bar just above the fillet: Rollback on the fillet has nowhere to go.
  const rolled = part({ bar: { item: FILLET, before: FILLET } });
  render(<EditTree edit={rolled as never} tree={tree} />);
  fireEvent.contextMenu(row('Fillet1'));
  const here = screen.getByRole('menuitem', { name: 'Rollback' });
  expect(here.getAttribute('aria-disabled')).toBe('true');
  await user.click(here);
  expect(rolled.rollTo).not.toHaveBeenCalled();
  cleanup();
  // Nothing rolled back: Rollback is there on the last feature too.
  render(<EditTree edit={part() as never} tree={tree} />);
  fireEvent.contextMenu(row('Hole1'));
  expect(screen.getByRole('menuitem', { name: 'Rollback' }).getAttribute('aria-disabled')).toBeNull();
});

it("keeps the part's own menu above the tree, its commands in the toolbar's words", () => {
  render(<EditTree edit={part() as never} tree={partTree()} />);
  expect(menuOf('Bracket')).toEqual(['Appearance', 'Mass Properties']);
});

it("opens a sketch on a double-click, as its menu's Edit Sketch does, but not while a change is on its way", () => {
  const lid = {
    units: 'mm', name: 'lid', params: [], rows: [],
    features: [{ key: 'lid.py:5', kind: 'Sketch', file: 'lid.py', line: 5, sketch: { name: 'Outline', plane: 'Top', file: 'lid.py', line: 5, status: 'Fully defined' } }],
  };
  for (const [state, opens] of [[{}, true], [{ saving: true }, false], [{ status: 'reading' }, false]] as const) {
    const onEditSketch = vi.fn();
    render(<EditTree edit={part({ state: lid, ...state }) as never} tree={featureTree(lid)} onEditSketch={onEditSketch} />);
    fireEvent.doubleClick(row('Outline'));
    expect(onEditSketch.mock.calls.map(([sketch]) => sketch.title)).toEqual(opens ? ['Outline'] : []);
    cleanup();
  }
});

it("takes the selected feature out with the Delete key, as it did", () => {
  const selected = part({ selected: FILLET });
  const tree = partTree();
  render(<EditTree edit={selected as never} tree={tree} />);
  fireEvent.keyDown(row('Fillet1'), { key: 'Delete' });
  expect(selected.remove).toHaveBeenCalledWith(FILLET, tree);
});

it("lists an assembly's parts and mates in the tree, under the same header", () => {
  const stack = {
    units: 'mm', name: 'stack', params: [], rows: [], mates: [{ label: 'mate1', name: 'Coincident1', parts: ['base', 'pin'] }],
    components: [{ file: 'parts/base.py', name: 'base', step: 'parts/base.step',
      features: [{ key: 'parts/base.py:6', kind: 'Boss-Extrude', name: 'base', file: 'parts/base.py', line: 6 }] }],
  };
  render(<EditTree edit={part({ state: stack }) as never} tree={featureTree(stack)} onOpenPart={vi.fn()} />);
  const rows = within(screen.getByRole('tree', { name: 'FeatureManager design tree' })).getAllByRole('treeitem');
  expect(rows.map(each => each.textContent)).toEqual(['Origin', 'Front Plane', 'Top Plane', 'Right Plane', 'Base<1>', 'Mates', 'Coincident1 (base, pin)']);
  expect(screen.getByText('Stack')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Equations' })).toBeTruthy();
  expect(menuOf('Base<1>')).toEqual(['Open Part']);
  cleanup();
  render(<EditTree edit={part({ state: stack }) as never} tree={featureTree(stack)} onOpenPart={vi.fn()} />);
  expect(menuOf('Coincident1 (base, pin)')).toEqual(['Delete']);
});

// What the part's script stops with when a fillet cannot be made, as the tracer words it (a real one, its
// paths shortened): build123d's own error, then the tracer's frame, the fillet's line in the part, build123d's.
const failed = (line: number, code = SOURCE.fillet) => [
  'Traceback (most recent call last):',
  '  File "/work/.venv/lib/python3.13/site-packages/build123d/topology/three_d.py", line 367, in fillet',
  '    new_shape = self._make_3d_result(fillet_builder.Shape())',
  'OCP.OCP.Standard.Standard_Failure: BRep_API: command not done',
  '',
  'The above exception was the direct cause of the following exception:',
  '',
  'Traceback (most recent call last):',
  '  File "/work/packages/cadgen/src/cadgen/edit/tracer.py", line 1668, in trace',
  '    shape = model.func()',
  `  File "/work/parts/bracket.py", line ${line}, in bracket`,
  `    ${code}`,
  '  File "/work/.venv/lib/python3.13/site-packages/build123d/topology/three_d.py", line 371, in fillet',
  '    raise ValueError(',
  '    ...<2 lines>...',
  'ValueError: Failed creating a fillet with radius of 40, try a smaller value or use max_fillet() to find the largest valid fillet radius',
].join('\n');
const WHY = 'ValueError: Failed creating a fillet with radius of 40, try a smaller value or use max_fillet() to find the largest valid fillet radius';
// How the engine says where the script stopped: the frames of its traceback in the project's own files, deepest
// first, each with the file as the history names it, the line and the line as read.
const at = (line: number, text: string, file = 'bracket.py') => ({ file, line, text });
const stoppedAt = (...frames: ReturnType<typeof at>[]) => ({ frames });
// The line in a helper's file that raised: it makes no row, and the part's call into it is the hole's.
const IN_DRILL = at(4, 'return plate - Pos(10, 0, 0) * Cylinder(radius, height)', 'helpers.py');
// The rows wearing the warning, by their ids.
const markedRows = () => screen.queryAllByRole('img', { name: 'Did not build' }).map(mark => mark.closest('[data-tree-row]')?.getAttribute('data-cad-edit-tree-row'));

it("marks the feature whose build failed with the viewer's warning, and says why on hover", () => {
  render(<EditTree edit={part({ error: failed(9), failure: stoppedAt(at(9, SOURCE.fillet)) }) as never} tree={partTree()} />);
  // The row the engine's file, line and words name, beside its title, in the alert card's amber.
  const marked = row('Fillet1');
  const mark = within(marked).getByRole('img', { name: 'Did not build' });
  expect(mark.getAttribute('class')).toMatch(/\btext-amber-500\b/);
  expect(marked.getAttribute('title')).toBe(`Did not build: ${WHY}`);
  expect(marked.textContent).toBe('Fillet1Plate');
  // No other row says it.
  expect(markedRows()).toEqual([FILLET]);
  expect(row('Hole1').getAttribute('title')).toBeNull();
});

it("marks the feature that called the helper an error was raised in", () => {
  // The helper's line makes no row; the part's call into it is the hole's, so that is the row.
  render(<EditTree edit={part({ error: failed(10, SOURCE.hole), failure: stoppedAt(IN_DRILL, at(10, SOURCE.hole)) }) as never} tree={partTree()} />);
  expect(markedRows()).toEqual([HOLE]);
  expect(row('Hole1').getAttribute('title')).toBe(`Did not build: ${WHY}`);
});

it("marks nothing for a line that moved: the script has moved on from the tree", () => {
  // A line was written above the fillet, and it stands at 10 now, where the last good part's hole was.
  // Neither the hole, which reads otherwise, nor the fillet, which sat at 9, is that line.
  render(<EditTree edit={part({ error: failed(10), failure: stoppedAt(at(10, SOURCE.fillet)) }) as never} tree={partTree()} />);
  expect(markedRows()).toEqual([]);
});

it("marks nothing for a call that moved, though the helper it called is told of", () => {
  // The call into the helper stands at 11 now, where the last good part had nothing; and at 9, where its fillet was.
  render(<EditTree edit={part({ error: failed(11, SOURCE.hole), failure: stoppedAt(IN_DRILL, at(11, SOURCE.hole)) }) as never} tree={partTree()} />);
  expect(markedRows()).toEqual([]);
  cleanup();
  render(<EditTree edit={part({ error: failed(9, SOURCE.hole), failure: stoppedAt(IN_DRILL, at(9, SOURCE.hole)) }) as never} tree={partTree()} />);
  expect(markedRows()).toEqual([]);
});

it("marks nothing for a line the last good part does not hold", () => {
  // The radius typed over in the line itself: no row of the last good part reads so, though one sits at its number.
  const rewritten = 'plate = fillet(plate.edges().filter_by(Axis.Z), radius=40)';
  render(<EditTree edit={part({ error: failed(9, rewritten), failure: stoppedAt(at(9, rewritten)) }) as never} tree={partTree()} />);
  expect(markedRows()).toEqual([]);
  cleanup();
  // The engine found no frame of the part's own (a script that does not parse): nothing, whatever the traceback holds.
  render(<EditTree edit={part({ error: failed(9), failure: null }) as never} tree={partTree()} />);
  expect(markedRows()).toEqual([]);
});

it("marks nothing for an engine that says no line, though the traceback names one", () => {
  render(<EditTree edit={part({ error: failed(9) }) as never} tree={partTree()} />);
  expect(markedRows()).toEqual([]);
});

it("marks nothing for an error that points at no feature", () => {
  const patches = [{ error: 'Another feature is named Lid. Pick another name.' },
    { error: failed(99), failure: stoppedAt(at(99, 'plate = shell(plate, thickness=1)')) }, { error: '' }];
  for (const patch of patches) {
    render(<EditTree edit={part(patch) as never} tree={partTree()} />);
    expect(markedRows()).toEqual([]);
    cleanup();
  }
});

it("reorders a feature dragged to another place, as SolidWorks' tree does, and a click is still a click", () => {
  const editing = { ...edit(), reorder: vi.fn() };
  const tree = featureTree(STATE);
  render(<EditTree edit={editing as never} tree={tree} />);
  const row = document.querySelector<HTMLElement>('[data-cad-edit-tree-row="block.py:7"]')!;
  // Rows sit 20px apart from the top, so a drop at 65px is above the fourth item.
  document.querySelectorAll<HTMLElement>('[data-cad-edit-bar-slot]').forEach(slot => {
    const top = 20 * Number(slot.getAttribute('data-cad-edit-bar-slot'));
    slot.getBoundingClientRect = () => ({ top, height: 20, bottom: top + 20, left: 0, right: 100, width: 100, x: 0, y: top, toJSON: () => ({}) });
  });
  fireEvent.pointerDown(row, { button: 0, clientY: 30 });
  fireEvent.pointerUp(row, { clientY: 31 });
  expect(editing.reorder).not.toHaveBeenCalled();
  fireEvent.pointerDown(row, { button: 0, clientY: 30 });
  fireEvent.pointerMove(row, { clientY: 65 });
  expect(document.querySelector('[data-cad-edit-drop]')).not.toBeNull();
  fireEvent.pointerUp(row, { clientY: 65 });
  expect(editing.reorder).toHaveBeenCalledWith('block.py:7', 3, tree);
  expect(document.querySelector('[data-cad-edit-drop]')).toBeNull();
});
