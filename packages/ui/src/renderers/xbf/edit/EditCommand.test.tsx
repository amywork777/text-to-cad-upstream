import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import EditCommand from '../../../../dist/renderers/xbf/edit/EditCommand.js';
import MassProperties from '../../../../dist/renderers/xbf/edit/MassProperties.js';
import Appearance from '../../../../dist/renderers/xbf/edit/Appearance.js';

afterEach(cleanup);

const ROWS = [{ key: 'block.py:6', kind: 'Box', inputs: [] }, { key: 'block.py:7', kind: 'Hole', inputs: [] }];
const NAMES = [{ key: 'block.py:6', kind: 'Box', title: 'Box1', name: '' }, { key: 'block.py:7', kind: 'Hole', title: 'Hole1', name: '' }];
// Picked on an engine document: named by the engine's ref, as the xbf viewer names a pick (`selectors.js`).
const EDGE = { id: 'ref-e3', selectorType: 'edge', displaySelector: 'block/edge 3', pickData: { curveType: 'line', center: [0, 5, 2], length: 20 } };

function edit(command: string, selected = 'block.py:6') {
  return { command, selected, status: 'ready', saving: false, state: { units: 'mm', rows: ROWS }, run: vi.fn(), close: vi.fn(),
    select: vi.fn(), setPreview: vi.fn() };
}

it('a fillet waits for edges, then OK writes it with the radius typed', async () => {
  const user = userEvent.setup();
  const fillet = edit('fillet');
  const { rerender } = render(<EditCommand edit={fillet as never} names={NAMES} references={[]} />);
  // Choose names the pick wanted, and the empty box says how to pick.
  expect(screen.getByText('1 of 1: Select edges to round')).toBeTruthy();
  expect(screen.getByText('Click edges on the model to add them. Click one again to take it out.')).toBeTruthy();
  expect((screen.getByRole('button', { name: 'OK' }) as HTMLButtonElement).disabled).toBe(true);

  // An edge picked on the model while the panel is open is listed, and OK can go.
  rerender(<EditCommand edit={fillet as never} names={NAMES} references={[EDGE]} />);
  expect(screen.getByText('Edge 3')).toBeTruthy();
  const radius = screen.getByRole('textbox', { name: 'Radius' });
  await user.clear(radius);
  await user.type(radius, '2.5{Enter}');
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(fillet.run).toHaveBeenCalledWith({
    command: 'fillet', inputs: { radius: '2.5' },
    selection: [{ selector: 'block/edge 3', type: 'line', center: [0, 5, 2], size: 20 }],
  });
});

it('a pattern copies the feature picked in the history, and Cancel leaves the script alone', async () => {
  const user = userEvent.setup();
  const pattern = edit('pattern', 'block.py:7');
  render(<EditCommand edit={pattern as never} names={NAMES} references={[]} />);
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(pattern.run).toHaveBeenCalledWith({
    command: 'pattern', selection: [], inputs: { type: 'linear', count: '3', direction: 'X', spacing: '10' },
    feature: { row: 'block.py:7', name: 'Hole1' },
  });
  await user.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(pattern.close).toHaveBeenCalled();
});

it('Choose lists each pick with an X to take it out, and Preview asks for what OK would make and says what it drew', async () => {
  const user = userEvent.setup();
  const fillet = { ...edit('fillet'), previewOn: true, featurePreview: null, previewFeature: vi.fn(), setPreviewOn: vi.fn() };
  const onDeselect = vi.fn();
  const { rerender } = render(<EditCommand edit={fillet as never} names={NAMES} references={[EDGE]} onDeselect={onDeselect} />);
  expect(screen.getByText('Review the preview, then press OK.')).toBeTruthy();
  const request = { command: 'fillet', inputs: { radius: '1' }, selection: [{ selector: 'block/edge 3', type: 'line', center: [0, 5, 2], size: 20 }] };
  await waitFor(() => expect(fillet.previewFeature).toHaveBeenLastCalledWith(request));
  await user.click(screen.getByRole('button', { name: 'Remove Edge 3' }));
  expect(onDeselect).toHaveBeenCalledWith('ref-e3');

  // While it is made, then what it takes away, then why it could not be made.
  rerender(<EditCommand edit={{ ...fillet, featurePreview: { status: 'updating' } } as never} names={NAMES} references={[EDGE]} onDeselect={onDeselect} />);
  expect(screen.getByText('Updating the preview')).toBeTruthy();
  rerender(<EditCommand edit={{ ...fillet, featurePreview: { status: 'ready', removed: { positions: [], triangles: [], edges: [] }, added: null } } as never}
    names={NAMES} references={[EDGE]} onDeselect={onDeselect} />);
  expect(screen.getByText('Material it takes away')).toBeTruthy();
  expect(screen.queryByText('Material it adds')).toBeNull();
  rerender(<EditCommand edit={{ ...fillet, featurePreview: { status: 'failed', error: 'Try a smaller radius.' } } as never} names={NAMES} references={[EDGE]}
    onDeselect={onDeselect} />);
  expect(screen.getByText('Try a smaller radius.')).toBeTruthy();

  // Preview switched off: none asked, and the line asks only for OK.
  await user.click(screen.getByRole('checkbox', { name: 'Preview' }));
  expect(fillet.setPreviewOn).toHaveBeenCalledWith(false);
  rerender(<EditCommand edit={{ ...fillet, previewOn: false } as never} names={NAMES} references={[EDGE]} onDeselect={onDeselect} />);
  expect(screen.getByText('Press OK to make it.')).toBeTruthy();
  await waitFor(() => expect(fillet.previewFeature).toHaveBeenLastCalledWith(null));
});

it('each command that goes somewhere previews the way it goes: an extrude its depth, a hole into its face, a mirror its plane', () => {
  // A sketch selected in the design tree, made a solid of by Extruded Boss/Base.
  const sketch = { id: 'block.py:9', title: 'Sketch1', plane: 'Top', file: 'block.py', line: 9, constrained: true };
  const tree = { assembly: false, features: [{ id: 'block.py:9', kind: 'Sketch', title: 'Sketch1', rows: [], sketch }] };
  const extrude = edit('extrude', 'block.py:9');
  render(<EditCommand edit={extrude as never} names={NAMES} references={[]} tree={tree} />);
  expect(extrude.setPreview).toHaveBeenLastCalledWith({ kind: 'boss', end: 'blind', file: 'block.py', line: 9, taper: 0, depth: 5, reverse: false,
    units: 'mm', label: '5 mm', text: '5', text2: '5', onDepth: expect.any(Function), onReverse: expect.any(Function) });
  cleanup();
  // A hole goes into the face picked, Blind as SolidWorks' Hole Wizard opens it.
  const hole = edit('hole');
  const FACE = { id: 'ref-f1', selectorType: 'face', displaySelector: 'f1', pickData: { surfaceType: 'plane', center: [0, 0, 2], normal: [0, 0, 1], area: 200 } };
  render(<EditCommand edit={hole as never} names={NAMES} references={[FACE]} />);
  expect(hole.setPreview).toHaveBeenLastCalledWith({ mark: 'hole', at: [0, 0, 2], into: [0, 0, -1], label: '5 mm' });
  cleanup();
  const mirror = edit('mirror');
  render(<EditCommand edit={mirror as never} names={NAMES} references={[]} />);
  expect(mirror.setPreview).toHaveBeenLastCalledWith({ mark: 'mirror', plane: 'YZ' });
});

it("Direction 2 switched on goes the other way by its own depth, its arrow a handle for it", async () => {
  const user = userEvent.setup();
  const sketch = { id: 'block.py:9', title: 'Sketch1', plane: 'Top', file: 'block.py', line: 9, constrained: true };
  const tree = { assembly: false, features: [{ id: 'block.py:9', kind: 'Sketch', title: 'Sketch1', rows: [], sketch }] };
  const extrude = edit('extrude', 'block.py:9');
  render(<EditCommand edit={extrude as never} names={NAMES} references={[]} tree={tree} />);
  await user.click(screen.getByRole('checkbox', { name: 'Direction 2' }));
  const depths = screen.getAllByRole('textbox', { name: 'Depth' });
  expect(depths).toHaveLength(2);
  await user.clear(depths[1]);
  await user.type(depths[1], '3{Enter}');
  expect(extrude.setPreview).toHaveBeenLastCalledWith(expect.objectContaining({ depth: 5, depth2: 3, label2: '3 mm', onDepth2: expect.any(Function) }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(extrude.run).toHaveBeenCalledWith({ command: 'extrude', sketch: { file: 'block.py', line: 9, name: 'Sketch1' },
    inputs: { end: 'blind', depth: '5', reverse: false, direction2: true, end2: 'blind', depth2: '3' } });
});

it('a sweep takes the sketch selected as its profile, then the next as its path, and a rib grows the side it is turned', async () => {
  const user = userEvent.setup();
  const sketch = (id: string, title: string, line: number) => ({ id, kind: 'Sketch', title, rows: [],
    sketch: { id, title, plane: 'Top', file: 'block.py', line, constrained: true } });
  const tree = { assembly: false, features: [sketch('block.py:9', 'Sketch1', 9), sketch('block.py:12', 'Sketch2', 12)] };
  const sweep = edit('sweep', 'block.py:9');
  const { rerender } = render(<EditCommand edit={sweep as never} names={NAMES} references={[]} tree={tree} />);
  expect(screen.getByText('2 of 2: Select the path sketch')).toBeTruthy();
  // The path picked in the design tree: both boxes full, and OK sends them in order.
  rerender(<EditCommand edit={{ ...sweep, selected: 'block.py:12' } as never} names={NAMES} references={[]} tree={tree} />);
  expect(screen.getByText('Review the preview, then press OK.')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(sweep.run).toHaveBeenCalledWith({ command: 'sweep', inputs: {},
    sketches: [{ file: 'block.py', line: 9, name: 'Sketch1' }, { file: 'block.py', line: 12, name: 'Sketch2' }] });
  // Its profile let go by its X: the first box waits again.
  await user.click(screen.getByRole('button', { name: 'Remove Sketch1' }));
  expect(screen.getByText('1 of 2: Select the profile sketch')).toBeTruthy();
  cleanup();
  const rib = edit('rib', 'block.py:9');
  render(<EditCommand edit={rib as never} names={NAMES} references={[]} tree={tree} />);
  await user.click(screen.getByRole('checkbox', { name: 'Flip material side' }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(rib.run).toHaveBeenCalledWith({ command: 'rib', sketch: { file: 'block.py', line: 9, name: 'Sketch1' }, inputs: { thickness: '1', flip: true } });
});

const SIDE = { id: 'ref-f2', selectorType: 'face', displaySelector: 'f2', pickData: { surfaceType: 'plane', center: [10, 0, 0], area: 40, normal: [1, 0, 0] } };
const BOTTOM = { id: 'ref-f6', selectorType: 'face', displaySelector: 'f6', pickData: { surfaceType: 'plane', center: [0, 0, -2], area: 200, normal: [0, 0, -1] } };
const SIDE_ITEM = { selector: 'f2', type: 'plane', center: [10, 0, 0], size: 40 };

it('a draft takes the first face clicked as its neutral plane, apart from the faces it drafts, and pulls into the part', async () => {
  const user = userEvent.setup();
  const draft = edit('draft', '');
  const onDeselect = vi.fn();
  const { rerender } = render(<EditCommand edit={draft as never} names={NAMES} references={[]} onDeselect={onDeselect} />);
  expect(screen.getByText('1 of 2: Select the neutral plane')).toBeTruthy();
  // Clicked on the model, the face goes to the Neutral Plane box and is let go there.
  rerender(<EditCommand edit={draft as never} names={NAMES} references={[BOTTOM]} onDeselect={onDeselect} />);
  expect(onDeselect).toHaveBeenCalledWith('ref-f6');
  rerender(<EditCommand edit={draft as never} names={NAMES} references={[]} onDeselect={onDeselect} />);
  expect(screen.getByText('Face 6')).toBeTruthy();
  expect(screen.getByText('2 of 2: Select faces to draft')).toBeTruthy();
  // The next face is one it drafts.
  rerender(<EditCommand edit={draft as never} names={NAMES} references={[SIDE]} onDeselect={onDeselect} />);
  expect(onDeselect).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Face 2')).toBeTruthy();
  await waitFor(() => expect(draft.setPreview).toHaveBeenLastCalledWith(
    { mark: 'draft', center: [0, 0, -2], normal: [0, 0, -1], at: [0, 0, -2], pull: [0, 0, 1] }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(draft.run).toHaveBeenCalledWith({
    command: 'draft', selection: [SIDE_ITEM], inputs: { angle: '1', neutral: 'face', reverse: true },
    neutral: { selector: 'f6', type: 'plane', center: [0, 0, -2], size: 200 },
  });
});

it("a plane clicked in the design tree is a draft's neutral plane, and Clear lets it go for another", async () => {
  const user = userEvent.setup();
  const draft = { ...edit('draft', 'plane:Top'), state: { units: 'mm', rows: ROWS, bounds: [[-10, -5, 0], [10, 5, 4]] } };
  render(<EditCommand edit={draft as never} names={NAMES} references={[SIDE]} />);
  expect(screen.getByText('Top Plane')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(draft.run).toHaveBeenCalledWith({ command: 'draft', selection: [SIDE_ITEM], inputs: { angle: '1', neutral: 'Top', reverse: false } });
  await user.click(screen.getByRole('button', { name: 'Clear Top Plane' }));
  expect(draft.select).toHaveBeenCalledWith(null);
  expect(screen.getByText('1 of 2: Select the neutral plane')).toBeTruthy();
});

it("a hole opens as Hole Wizard's M3 clearance hole, and a size typed over is the engineer's own", async () => {
  const user = userEvent.setup();
  const hole = edit('hole');
  const FACE = { id: 'ref-f1', selectorType: 'face', displaySelector: 'f1', pickData: { surfaceType: 'plane', center: [0, 0, 2], normal: [0, 0, 1], area: 200 } };
  const selection = [{ selector: 'f1', type: 'plane', center: [0, 0, 2], size: 200 }];
  render(<EditCommand edit={hole as never} names={NAMES} references={[FACE]} />);
  expect(screen.getByRole('combobox', { name: 'Size' }).textContent).toBe('M3');
  expect((screen.getByRole('textbox', { name: 'Diameter' }) as HTMLInputElement).value).toBe('3.4');
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(hole.run).toHaveBeenLastCalledWith({ command: 'hole', selection, inputs: { diameter: '3.4', depth: '5', callout: 'M3 clearance hole, normal fit' } });
  const diameter = screen.getByRole('textbox', { name: 'Diameter' });
  await user.clear(diameter);
  await user.type(diameter, '3.3{Enter}');
  expect(screen.getByRole('combobox', { name: 'Size' }).textContent).toBe('Custom');
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(hole.run).toHaveBeenLastCalledWith({ command: 'hole', selection, inputs: { diameter: '3.3', depth: '5' } });
});

it("each click on a hole's face after the first adds a hole there, listed with an X to take it out", async () => {
  const user = userEvent.setup();
  const FACE = { id: 'ref-f1', selectorType: 'face', displaySelector: 'f1', pickData: { surfaceType: 'plane', center: [0, 0, 2], normal: [0, 0, 1], area: 200 } };
  const click = (point: number[], id = 'ref-f1') => ({ id, point, center: [0, 0, 2], normal: [0, 0, 1] });
  const hole = edit('hole');
  const { rerender } = render(<EditCommand edit={{ ...hole, facePoint: click([5, 0, 2]) } as never} names={NAMES} references={[FACE]} />);
  expect((screen.getByRole('textbox', { name: 'X from center' }) as HTMLInputElement).value).toBe('5');
  rerender(<EditCommand edit={{ ...hole, facePoint: click([-5, 0, 2]) } as never} names={NAMES} references={[FACE]} />);
  rerender(<EditCommand edit={{ ...hole, facePoint: click([0, 2.5, 2]) } as never} names={NAMES} references={[FACE]} />);
  expect((screen.getByRole('textbox', { name: 'Hole 2 X' }) as HTMLInputElement).value).toBe('-5');
  expect((screen.getByRole('textbox', { name: 'Hole 3 Y' }) as HTMLInputElement).value).toBe('2.5');
  await user.click(screen.getByRole('button', { name: 'Remove Hole 2' }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(hole.run).toHaveBeenLastCalledWith(expect.objectContaining({ inputs: expect.objectContaining({ x: '5', more: [{ x: '0', y: '2.5' }] }) }));
  // A click on another face starts the holes over there.
  rerender(<EditCommand edit={{ ...hole, facePoint: click([1, 1, 2], 'ref-f9') } as never} names={NAMES} references={[FACE]} />);
  expect(screen.queryByRole('textbox', { name: 'Hole 2 X' })).toBeNull();
});

it('a face picked before Hole opened holds its hole until it is clicked, and the first click puts the hole there', () => {
  // A tray's rim: its center is over the opening, so the hole has to be clicked onto it.
  const RIM = { id: 'ref-f3', selectorType: 'face', displaySelector: 'f3', pickData: { surfaceType: 'plane', center: [0, 0, 5], normal: [0, 0, 1], area: 220.566 } };
  const hole = edit('hole');
  const { rerender } = render(<EditCommand edit={hole as never} names={NAMES} references={[RIM]} />);
  expect(screen.getByText('Click the face where the hole goes.')).toBeTruthy();
  rerender(<EditCommand edit={{ ...hole, facePoint: { id: 'ref-f3', point: [19, 0, 5], center: [0, 0, 5], normal: [0, 0, 1] } } as never}
    names={NAMES} references={[RIM]} />);
  expect((screen.getByRole('textbox', { name: 'X from center' }) as HTMLInputElement).value).toBe('19');
  expect((screen.getByRole('textbox', { name: 'Y from center' }) as HTMLInputElement).value).toBe('0');
  expect(screen.queryByRole('textbox', { name: 'Hole 2 X' })).toBeNull();
  expect(screen.getByText('Click the face again to add a hole there.')).toBeTruthy();
});

it("Mass Properties weigh the part in the project's material, or one picked, and close", async () => {
  const user = userEvent.setup();
  const materials = [{ key: 'aluminum-6061-t6', name: 'Aluminum 6061-T6', density: 2.7 }, { key: 'petg', name: 'PETG', density: 1.27 }];
  const inspected = { ...edit(''), stopInspecting: vi.fn(),
    mass: { status: 'ready', volume: 800, area: 640, center: [0, 0, 0], box: [[-10, -5, -2], [10, 5, 2]], material: 'petg', materials } };
  render(<MassProperties edit={inspected as never} />);
  expect(screen.getByText('1.27 g/cm³')).toBeTruthy();
  expect(screen.getByText('1.02 g')).toBeTruthy();
  expect(screen.getByText('20 x 10 x 4 mm')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Close' }));
  expect(inspected.stopInspecting).toHaveBeenCalled();
  cleanup();
  // No material named: no mass until one is picked.
  render(<MassProperties edit={{ ...inspected, mass: { ...inspected.mass, material: null } } as never} />);
  expect(screen.getByText('Pick a material to weigh the part.')).toBeTruthy();
  expect(screen.queryByText('1.02 g')).toBeNull();
});

it("Appearance opens on the part's color, and OK writes the swatch or the hex picked", async () => {
  const user = userEvent.setup();
  const painting = { ...edit(''), state: { units: 'mm', rows: ROWS, color: '#B7A1D7' }, stopInspecting: vi.fn(), paint: vi.fn(async () => ({ ok: true })) };
  render(<Appearance edit={painting as never} />);
  expect((screen.getByRole('textbox', { name: 'Hex' }) as HTMLInputElement).value).toBe('#B7A1D7');
  // Its own color again is nothing to write.
  expect((screen.getByRole('button', { name: 'OK' }) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Teal' }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(painting.paint).toHaveBeenLastCalledWith('#2E9C95');
  await waitFor(() => expect(painting.stopInspecting).toHaveBeenCalled());
  const hex = screen.getByRole('textbox', { name: 'Hex' });
  await user.clear(hex);
  await user.type(hex, '2e3742{Enter}');
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(painting.paint).toHaveBeenLastCalledWith('#2E3742');
});

it("a plane is offset from the origin plane clicked in the design tree, drawn where it would be", async () => {
  const user = userEvent.setup();
  const plane = { ...edit('plane', 'plane:Front'), state: { units: 'mm', rows: ROWS, bounds: [[-10, -5, 0], [10, 5, 4]] } };
  render(<EditCommand edit={plane as never} names={NAMES} references={[]} />);
  expect(screen.getByText('Front Plane')).toBeTruthy();
  expect(screen.getByText('Review the preview, then press OK.')).toBeTruthy();
  expect(plane.setPreview).toHaveBeenLastCalledWith({ mark: 'plane', center: [0, -5, 2], normal: [0, -1, 0], at: [0, 0, 2], along: [0, -1, 0],
    label: '5 mm' });
  await user.click(screen.getByRole('checkbox', { name: 'Flip offset' }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(plane.run).toHaveBeenCalledWith({ command: 'plane', selection: [], inputs: { reference: 'Front', distance: '5', flip: true } });
});

it("a reference plane clicked in the design tree is a draft's neutral plane, by the name the script holds it in", async () => {
  const user = userEvent.setup();
  const tree = { assembly: false, features: [{ id: 'block.py:7', kind: 'Plane', title: 'Plane1', variable: 'plane1', rows: [],
    plane: { origin: [0, 0, 2], x: [1, 0, 0], z: [0, 0, 1] } }] };
  const draft = { ...edit('draft', 'block.py:7'), state: { units: 'mm', rows: ROWS, bounds: [[-10, -5, -2], [10, 5, 2]] } };
  render(<EditCommand edit={draft as never} names={NAMES} references={[SIDE]} tree={tree} />);
  expect(screen.getByText('Plane1')).toBeTruthy();
  // The block lies under the plane: the pull goes down into it.
  await waitFor(() => expect(draft.setPreview).toHaveBeenLastCalledWith({ mark: 'draft', center: [0, 0, 2], normal: [0, 0, 1], at: [0, 0, 2],
    pull: [0, 0, -1] }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(draft.run).toHaveBeenCalledWith({ command: 'draft', selection: [SIDE_ITEM], inputs: { angle: '1', neutral: 'named:plane1', reverse: true } });
});

it("puts a fillet's radius on the model by its first edge, typed over there as in the dialog, as SolidWorks' callout is", () => {
  const fillet = { ...edit('fillet'), setCallout: vi.fn() };
  const EDGE = { id: 'ref-e1', selectorType: 'edge', displaySelector: 'e1', pickData: { center: [0, -5, 2] } };
  render(<EditCommand edit={fillet as never} names={NAMES} references={[EDGE]} />);
  const callout = fillet.setCallout.mock.calls.at(-1)[0];
  expect({ at: callout.at, label: callout.label, text: callout.text }).toEqual({ at: [0, -5, 2], label: 'Radius', text: '1' });
  act(() => callout.onCommit('2'));
  expect(screen.getByRole('textbox', { name: 'Radius' }) as HTMLInputElement).toHaveProperty('value', '2');
});
