import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import EditTimeline from '../../../../dist/renderers/xbf/edit/EditTimeline.js';
import { featureTree, sketchTreeId } from '../../../../dist/renderers/xbf/edit/editMode.js';
import { WORKSPACE_SURFACE_CLASS } from '../../../../dist/lib/floatingSurface.js';

const sketched = (name: string, line: number) => ({ name, plane: 'Top', file: 'bracket.py', line, status: 'Fully defined' });
const command = { command: 'extrude', values: {}, keeps: '' };

// The sample bracket as the engine reads it (`tracer.py`): an extrude takes the sketch it was made from, and the
// engine nests that sketch under the extrude (`sketch`), so a sketch is a feature of its own only while nothing
// uses it. Two extrudes a command made from sketches, then a Fillet written by hand, a Hole and a Pattern.
// The design tree numbers each kind on its own, a sketch just before the extrude that takes it (a sketch shows its
// name in its label's place): SKETCH_000, Boss-Extrude1, SKETCH_001, Boss-Extrude2, Fillet1, Hole1, Pattern1.
const STATE = {
  units: 'mm', name: 'bracket', params: [], rows: [],
  features: [
    { key: 'e1', kind: 'Boss-Extrude', name: 'plate', file: 'bracket.py', line: 8, edit: command, sketch: sketched('SKETCH_000', 5) },
    { key: 'e2', kind: 'Boss-Extrude', name: 'plate', file: 'bracket.py', line: 13, edit: command, sketch: sketched('SKETCH_001', 10) },
    { key: 'b1', kind: 'Fillet', name: 'plate', file: 'bracket.py', line: 15 },
    { key: 'h1', kind: 'Hole', name: 'plate', file: 'bracket.py', line: 17 },
    { key: 'p1', kind: 'Pattern', name: 'plate', file: 'bracket.py', line: 19 },
  ],
};
const TREE = featureTree(STATE);
// What is drawn, left to right: the id each icon is selected by, and the title it is named by.
const ICONS = ['sketch:e1', 'e1', 'sketch:e2', 'e2', 'b1', 'h1', 'p1'];
const TITLES = ['SKETCH_000', 'Boss-Extrude1', 'SKETCH_001', 'Boss-Extrude2', 'Fillet1', 'Hole1', 'Pattern1'];

function edit(patch: Record<string, unknown> = {}) {
  return { status: 'ready', saving: false, state: STATE, selected: null, bar: null, sketch: null,
    select: vi.fn(), rollTo: vi.fn(), editFeature: vi.fn(), ...patch };
}
const timeline = (patch: Record<string, unknown> = {}, onEditSketch = vi.fn()) => {
  const own = edit(patch);
  const view = render(<EditTimeline edit={own as never} tree={featureTree(own.state as never)} onEditSketch={onEditSketch} />);
  return { ...view, own, onEditSketch };
};
const items = () => within(screen.getByRole('group', { name: 'Timeline' })).getAllByRole('button');
const item = (name: string) => screen.getByRole('button', { name });
// The design tree's rollback bar, laid along the timeline: its marker, named as the bar's.
const marker = () => screen.getByRole('slider', { name: "Rollback bar's marker" });
/** Which icons are drawn as the part will not have them: those past the marker. */
const rolledBackIcons = () => items().map(button => button.hasAttribute('data-rolled-back'));

// jsdom lays nothing out: the groups (a feature, with the sketch it was made from just before it) stand 8px
// apart from the left edge, each as wide as its 28px tiles and the 4px between a sketch and its feature. So they
// stand at 0 to 60, 68 to 128, 136 to 164, 172 to 200 and 208 to 236, and their centres, which a pointer is
// read against below, are 30, 98, 150, 186 and 222. Capturing a pointer is the browser's own, so it is stubbed.
const boxOf = Element.prototype.getBoundingClientRect;
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.getBoundingClientRect = function (this: Element) {
    if (!this.hasAttribute('data-cad-timeline-group')) return boxOf.call(this);
    let x = 0;
    for (const group of [...this.parentElement!.children].filter(each => each.hasAttribute('data-cad-timeline-group'))) {
      const width = group.children.length * 28 + (group.children.length - 1) * 4;
      if (group === this) return DOMRect.fromRect({ x, y: 0, width, height: 36 });
      x += width + 8;
    }
    return boxOf.call(this);
  };
  for (const name of ['setPointerCapture', 'releasePointerCapture']) Object.defineProperty(Element.prototype, name, { configurable: true, value() {} });
  Object.defineProperty(Element.prototype, 'hasPointerCapture', { configurable: true, value: () => true });
});
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); Element.prototype.getBoundingClientRect = boxOf;
  for (const name of ['setPointerCapture', 'releasePointerCapture', 'hasPointerCapture']) delete (Element.prototype as any)[name];
});

/** The marker pressed, dragged through `xs` and let go at the last. */
function drag(xs: number[], { release = true } = {}) {
  fireEvent.pointerDown(marker(), { button: 0, pointerId: 1, clientX: 300 });
  for (const clientX of xs) fireEvent.pointerMove(marker(), { pointerId: 1, clientX });
  if (release) fireEvent.pointerUp(marker(), { pointerId: 1, clientX: xs.at(-1) });
}

it("shows every item as its icon, in the design tree's order, a feature's own sketch just before it", () => {
  timeline();
  expect(items().map(button => button.getAttribute('aria-label'))).toEqual(TITLES);
  expect(items().map(button => button.querySelector('use')?.getAttribute('href')))
    .toEqual(['#nx-sketch', '#nx-extrude', '#nx-sketch', '#nx-extrude', '#nx-blend', '#nx-hole', '#nx-pattern']);
  expect(items().map(button => button.getAttribute('data-cad-timeline-item'))).toEqual(ICONS);
});

it("keeps a feature and its sketch in one group, which is what the marker steps over", () => {
  timeline();
  const groups = [...document.querySelectorAll('[data-cad-timeline-group]')];
  expect(groups.map(group => [...group.querySelectorAll('button')].map(button => button.getAttribute('aria-label'))))
    .toEqual([[TITLES[0], TITLES[1]], [TITLES[2], TITLES[3]], [TITLES[4]], [TITLES[5]], [TITLES[6]]]);
});

it("selects on a click and edits on a double-click: Edit Feature on a feature, Edit Sketch on a sketch", () => {
  const { own, onEditSketch } = timeline();
  fireEvent.click(item('Boss-Extrude2'));
  expect(own.select).toHaveBeenLastCalledWith('e2');
  fireEvent.doubleClick(item('Boss-Extrude2'));
  expect(own.editFeature).toHaveBeenCalledTimes(1);
  expect(own.editFeature).toHaveBeenLastCalledWith(TREE.features[1]);
  expect(onEditSketch).not.toHaveBeenCalled();
  // The sketch an extrude was made from opens as the design tree's row for it does.
  fireEvent.doubleClick(item('SKETCH_001'));
  expect(onEditSketch).toHaveBeenCalledTimes(1);
  expect(onEditSketch).toHaveBeenLastCalledWith(TREE.features[1].sketch);
  expect(own.editFeature).toHaveBeenCalledTimes(1);
  // A feature no command made has no Edit Feature: a double-click does nothing, as in the design tree.
  fireEvent.doubleClick(item('Fillet1'));
  expect([own.editFeature, onEditSketch].map(each => each.mock.calls.length)).toEqual([1, 1]);
});

it("selects a sketch an extrude was made from by the id the design tree selects it by, and marks it selected", () => {
  const { own } = timeline();
  fireEvent.click(item('SKETCH_001'));
  // The id a sketch picked on the model selects too (`sketchTreeId`).
  expect(own.select).toHaveBeenLastCalledWith(sketchTreeId(TREE, { file: 'bracket.py', line: 10 }));
  expect(own.select).toHaveBeenLastCalledWith('sketch:e2');
  cleanup();
  timeline({ selected: 'sketch:e2' });
  expect(items().map(button => button.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'true', 'false', 'false', 'false', 'false']);
});

it("draws a sketch nothing uses yet once, as an item of its own", () => {
  const loose = { ...STATE, features: [STATE.features[0],
    { key: 's9', kind: 'Sketch', file: 'bracket.py', line: 12, sketch: sketched('SKETCH_001', 12) }] };
  const { own, onEditSketch } = timeline({ state: loose, selected: 's9' });
  expect(items().map(button => button.getAttribute('data-cad-timeline-item'))).toEqual(['sketch:e1', 'e1', 's9']);
  expect(items().map(button => button.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'true']);
  fireEvent.doubleClick(item('SKETCH_001'));
  expect(onEditSketch).toHaveBeenLastCalledWith(featureTree(loose).features[1].sketch);
  fireEvent.click(item('SKETCH_001'));
  expect(own.select).toHaveBeenLastCalledWith(sketchTreeId(featureTree(loose), { file: 'bracket.py', line: 12 }));
});

it("marks the selected item", () => {
  timeline({ selected: 'e1' });
  // The extrude alone: its sketch is selected by an id of its own.
  expect(items().map(button => button.getAttribute('aria-pressed'))).toEqual(['false', 'true', 'false', 'false', 'false', 'false', 'false']);
});

it("is the workspace's white card, and lights an item in its pale blue under the pointer and its deeper blue selected", () => {
  timeline({ selected: 'e1' });
  // Opaque, a hairline and 6px corners, blurring nothing of the live canvas under it.
  const card = screen.getByRole('group', { name: 'Timeline' });
  expect(card.className.split(/\s+/)).toEqual(expect.arrayContaining(WORKSPACE_SURFACE_CLASS.split(' ')));
  expect(card.className).not.toMatch(/\bbackdrop-|bg-background\//);
  // Jsdom has no pointer to rest on an item: the colours are the workspace's tokens, which are all it takes.
  const tile = (name: string) => item(name).firstElementChild!.className;
  expect(tile('Boss-Extrude1')).toMatch(/\bbg-cad-ws-selected\b/);
  expect(tile('Boss-Extrude2')).toMatch(/group-hover\/item:bg-cad-ws-hover/);
  expect(tile('SKETCH_000')).toMatch(/group-hover\/item:bg-cad-ws-hover/);
});

it("edits nothing while the part is busy, as the design tree's rows do not", () => {
  const { own, onEditSketch } = timeline({ saving: true });
  fireEvent.doubleClick(item('Boss-Extrude1'));
  fireEvent.doubleClick(item('SKETCH_000'));
  expect([own.editFeature, onEditSketch].map(each => each.mock.calls.length)).toEqual([0, 0]);
  fireEvent.click(item('Boss-Extrude1'));
  expect(own.select).toHaveBeenCalledWith('e1');
  cleanup();
  // A sketch open takes Edit Feature away, not the way into another sketch.
  const sketching = timeline({ sketch: { file: 'bracket.py', line: 5 } });
  fireEvent.doubleClick(item('Boss-Extrude1'));
  expect(sketching.own.editFeature).not.toHaveBeenCalled();
  fireEvent.doubleClick(item('SKETCH_001'));
  expect(sketching.onEditSketch).toHaveBeenCalledTimes(1);
});

it("stands the marker after the last item the part has, and greys what the rollback bar leaves out", () => {
  timeline();
  expect([marker().getAttribute('aria-valuenow'), marker().getAttribute('aria-valuetext')]).toEqual(['5', 'At the end']);
  expect(rolledBackIcons().some(Boolean)).toBe(false);
  cleanup();
  timeline({ bar: { item: 'e2' } });
  // Above the second extrude, which goes with the sketch it was made from; the marker's places are the features'.
  expect([marker().getAttribute('aria-valuenow'), marker().getAttribute('aria-valuetext'), marker().getAttribute('aria-valuemax')]).toEqual(['1', 'Above Boss-Extrude2', '5']);
  expect(rolledBackIcons()).toEqual([false, false, true, true, true, true, true]);
});

it("says on hover the marker is the rollback bar's, as the design tree names the bar", () => {
  vi.useFakeTimers();
  timeline();
  fireEvent.pointerMove(marker(), { pointerType: 'mouse' });
  act(() => { vi.advanceTimersByTime(450); });
  expect(screen.getByRole('tooltip').textContent).toBe("Rollback bar's marker: drag it back to see the part as it was there");
});

it("draws the marker in the gap before the first item the part leaves out, past every sketch drawn before the items ahead of it", () => {
  // In px at 16px a rem, from the list's left edge. The tiles are 28px, 8px apart with a 4px gap between a sketch and its
  // feature, in 8px of padding: the groups stand at 8 to 68, 76 to 136, 144 to 172, 180 to 208 and 216 to 244.
  const at = () => parseFloat(/translateX\((.*)rem\)/.exec(marker().style.transform)![1]) * 16;
  timeline();
  expect(at()).toBe(244);
  cleanup();
  // Before the second extrude and its sketch, where the first and its sketch end.
  timeline({ bar: { item: 'e2' } });
  expect(at()).toBe(68);
  cleanup();
  timeline({ bar: { item: 'b1' } });
  expect(at()).toBe(136);
  cleanup();
  timeline({ bar: { item: 'p1' } });
  expect(at()).toBe(208);
});

it("greys a suppressed item and its sketch where they stand, rolled back or not", () => {
  const aside = { ...STATE, features: STATE.features.map(feature => (feature.key === 'e1' ? { ...feature, suppressed: true } : feature)) };
  timeline({ state: aside });
  expect(items().map(button => button.hasAttribute('data-suppressed'))).toEqual([true, true, false, false, false, false, false]);
  expect(rolledBackIcons().some(Boolean)).toBe(false);
});

it("marks who made an item with a dot, a sketch with its feature's, and an item nobody is known to have made with none", () => {
  timeline({ state: { ...STATE, authors: { e2: 'agent', b1: 'you', p1: 'someone else' } } });
  const dots = items().map(button => button.querySelector('[data-cad-timeline-author]')?.getAttribute('data-cad-timeline-author') ?? null);
  expect(dots).toEqual([null, null, 'agent', 'agent', 'you', null, null]);
  cleanup();
  // A part from before Studio kept track has neither.
  timeline();
  expect(document.querySelectorAll('[data-cad-timeline-author]').length).toBe(0);
});

it("says on hover what an item is, who made it and whether it is set aside", () => {
  vi.useFakeTimers();
  const aside = { ...STATE, authors: { e2: 'agent', b1: 'you' },
    features: STATE.features.map(feature => (feature.key === 'e1' ? { ...feature, suppressed: true } : feature)) };
  timeline({ state: aside });
  const hover = (node: Element) => { fireEvent.pointerMove(node, { pointerType: 'mouse' }); act(() => { vi.advanceTimersByTime(450); }); };
  const said = (name: string) => { hover(item(name)); const text = screen.getByRole('tooltip').textContent; fireEvent.pointerLeave(item(name)); return text; };
  expect(said('Boss-Extrude2')).toBe('Boss-Extrude2Made by the agent');
  expect(said('SKETCH_001')).toBe('SKETCH_001Made by the agent');
  expect(said('Fillet1')).toBe('Fillet1Made by you');
  expect(said('SKETCH_000')).toBe('SKETCH_000Suppressed');
  // Nothing more to say of an item from before Studio kept track.
  expect(said('Hole1')).toBe('Hole1');
});

it("moves the marker under the pointer, and rolls the part back only when it is let go", () => {
  const { own } = timeline();
  drag([250, 160], { release: false });
  // The marker stands between the third and fourth features, and what is past it is greyed, but the part has not moved.
  expect(rolledBackIcons()).toEqual([false, false, false, false, false, true, true]);
  expect(own.rollTo).not.toHaveBeenCalled();
  fireEvent.pointerUp(marker(), { pointerId: 1, clientX: 160 });
  expect(own.rollTo).toHaveBeenCalledTimes(1);
  expect(own.rollTo).toHaveBeenCalledWith('h1');
  // The bar is the part's to move: until it does, the timeline shows where it is.
  expect(rolledBackIcons().some(Boolean)).toBe(false);
});

it("moves a feature and the sketch it was made from as one, the marker never standing between them", () => {
  const { own } = timeline();
  // The second extrude and its sketch stand from 68px to 128px, their middle at 98. Over the sketch, short of the
  // middle, the marker is before both: the sketch goes with the extrude.
  drag([90], { release: false });
  expect(rolledBackIcons()).toEqual([false, false, true, true, true, true, true]);
  // Over the extrude, past the middle, it is after both: they stay.
  fireEvent.pointerMove(marker(), { pointerId: 1, clientX: 110 });
  expect(rolledBackIcons()).toEqual([false, false, false, false, true, true, true]);
  fireEvent.pointerUp(marker(), { pointerId: 1, clientX: 110 });
  expect(own.rollTo).toHaveBeenCalledTimes(1);
  expect(own.rollTo).toHaveBeenCalledWith('b1');
});

it("rolls to the end when the marker is let go past the last item, as Make Current Feature on the last feature does", () => {
  const { own } = timeline({ bar: { item: 'h1' } });
  drag([200, 400]);
  expect(own.rollTo).toHaveBeenCalledTimes(1);
  expect(own.rollTo).toHaveBeenCalledWith(null);
});

it("never rolls back past the first item, nor does anything for a marker let go where it was", () => {
  const { own } = timeline();
  drag([100, -50]);
  expect(own.rollTo).toHaveBeenLastCalledWith('e2');
  own.rollTo.mockClear();
  // Out and back to the slot it began at, or never out of it.
  drag([100, 290]);
  drag([280]);
  expect(own.rollTo).not.toHaveBeenCalled();
});

it("puts the marker back where it was when the drag is cancelled", () => {
  const { own } = timeline();
  drag([60], { release: false });
  expect(rolledBackIcons()).toEqual([false, false, true, true, true, true, true]);
  fireEvent.pointerCancel(marker(), { pointerId: 1 });
  expect(rolledBackIcons().some(Boolean)).toBe(false);
  expect(own.rollTo).not.toHaveBeenCalled();
});

it("lets go of a drag when the marker is taken away in the middle of it", () => {
  const own = edit();
  const tree = featureTree(STATE);
  const { rerender } = render(<EditTimeline edit={own as never} tree={tree} />);
  drag([60], { release: false });
  expect(rolledBackIcons()).toEqual([false, false, true, true, true, true, true]);
  // The part is read again: no marker, then the part is back and the marker is where the part has it.
  rerender(<EditTimeline edit={{ ...own, status: 'reading' } as never} tree={tree} />);
  rerender(<EditTimeline edit={own as never} tree={tree} />);
  expect(rolledBackIcons().some(Boolean)).toBe(false);
  expect(marker().getAttribute('aria-valuenow')).toBe('5');
  expect(own.rollTo).not.toHaveBeenCalled();
});

it("moves the marker an item at a time with the arrow keys", () => {
  const { own } = timeline({ bar: { item: 'h1' } });
  const key = (name: string) => fireEvent.keyDown(marker(), { key: name });
  // Above the fourth feature: back one is above the third, on one is above the fifth.
  key('ArrowLeft');
  expect(own.rollTo).toHaveBeenLastCalledWith('b1');
  key('ArrowRight');
  expect(own.rollTo).toHaveBeenLastCalledWith('p1');
  key('Home');
  expect(own.rollTo).toHaveBeenLastCalledWith('e2');
  key('End');
  expect(own.rollTo).toHaveBeenLastCalledWith(null);
  expect(own.rollTo).toHaveBeenCalledTimes(4);
  cleanup();
  // At the end it can only go back.
  const whole = timeline();
  fireEvent.keyDown(marker(), { key: 'ArrowRight' });
  fireEvent.keyDown(marker(), { key: 'End' });
  expect(whole.own.rollTo).not.toHaveBeenCalled();
  fireEvent.keyDown(marker(), { key: 'ArrowLeft' });
  expect(whole.own.rollTo).toHaveBeenCalledWith('p1');
});

it("keeps the marker still while the part is busy", () => {
  const { own } = timeline({ saving: true });
  expect(marker().getAttribute('aria-disabled')).toBe('true');
  drag([60]);
  fireEvent.keyDown(marker(), { key: 'ArrowLeft' });
  expect(own.rollTo).not.toHaveBeenCalled();
  cleanup();
  const sketching = timeline({ sketch: { file: 'bracket.py', line: 5 } });
  drag([60]);
  expect(sketching.own.rollTo).not.toHaveBeenCalled();
});

it("has no marker where there is nothing to roll back to, and no timeline where there is nothing", () => {
  // One feature, drawn with the sketch it was made from, has no earlier part to roll back to.
  const one = { ...STATE, features: STATE.features.slice(0, 1) };
  timeline({ state: one });
  expect(items().length).toBe(2);
  expect(screen.queryByRole('slider')).toBeNull();
  cleanup();
  // Not until the part is read.
  timeline({ status: 'reading' });
  expect(screen.queryByRole('slider')).toBeNull();
  cleanup();
  const empty = timeline({ state: { ...STATE, features: [] } });
  expect(empty.container.firstChild).toBeNull();
  cleanup();
  // An assembly's design tree has no bar, and its parts are opened to be modeled.
  const assembly = { ...STATE, features: undefined, components: [{ file: 'tray.py', name: 'tray', features: STATE.features }] };
  expect(timeline({ state: assembly }).container.firstChild).toBeNull();
});
