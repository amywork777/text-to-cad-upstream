import React, { forwardRef, useEffect } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

// The workspace's frame (`ribbon`, `leftDock`, `bottomDock` and `dialogPlace`): its toolbar, Part
// Navigator, dialog and timeline float over the canvas, whose box is the same whether they are up or
// Simple view's ai layout is in their place, so turning Simple view on or off never moves the model.
// Under the shell harness, with the WebGL viewport replaced by an empty box that counts its mounts.
const viewport = vi.hoisted(() => ({ mounts: 0 }));
vi.mock('../../../../dist/renderers/kit/shell/ShellViewport.js', () => ({
  default: forwardRef(function MockViewport(props: any) {
    useEffect(() => { viewport.mounts += 1; }, []);
    return <div data-mock-viewport=""><canvas />{typeof props.children === 'function'
      ? props.children({ runtimeRef: { current: null }, hostRef: { current: null }, mountRef: { current: null }, viewerReadyTick: 0, commitScene: () => true })
      : null}</div>;
  }),
}));
import HarnessRenderer from '../../../../dist/renderers/shell-harness/HarnessRenderer.js';
import { ViewerHostContext } from '../../../../dist/host/context.js';
import { testHost } from '../../../../dist/host/testing/host.js';
import { ViewerMobileContext } from '../../../../dist/file-viewer/responsive.js';
import { WORKSPACE_SURFACE_CLASS } from '../../../../dist/lib/floatingSurface.js';

// jsdom lays nothing out: the toolbar is given the height it has in the app.
const TOOLBAR_HEIGHT = 114;
const boxOf = Element.prototype.getBoundingClientRect;
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
  Element.prototype.getBoundingClientRect = function (this: Element) {
    return this.matches('[data-cad-dock="toolbar"]') ? DOMRect.fromRect({ x: 0, y: 0, width: 1280, height: TOOLBAR_HEIGHT }) : boxOf.call(this);
  };
  viewport.mounts = 0;
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); Element.prototype.getBoundingClientRect = boxOf; });

// What a renderer hands the frame for its workspace: the toolbar (given the strip's tools), the Part
// Navigator's content, the timeline, and the place its command's dialog mounts in.
const places: (HTMLElement | null)[] = [];
const WORKSPACE = Object.freeze({
  ribbon: (tools: { id: string }[]) => <div role="toolbar" aria-label="Design">{tools.map(tool => tool.id).join(' ')}</div>,
  leftDock: <div role="tree" aria-label="Features" />,
  bottomDock: <div role="toolbar" aria-label="Timeline" />,
  dialogPlace: (place: HTMLElement | null) => { places.push(place); },
});

/** The harness's frame with `workspace` handed to it (none: the ai layout); `show` hands it another. */
function shell(workspace: object = {}) {
  let settings: any = { toolStack: { panels: {}, collapsed: {} } };
  const preferences = { getSnapshot: () => settings, subscribe: () => () => {}, update(patch: object) { settings = { ...settings, ...patch }; } };
  const element = (handed: object) => <ViewerHostContext.Provider value={testHost()}><ViewerMobileContext.Provider value={false}>
    <HarnessRenderer {...({ source: { id: 'one' }, file: { path: '/models/panel.harness', name: 'panel.harness', kind: 'file' }, document: null,
      notice: null, onReady() {}, onOpenFile() {}, appearance: { colorScheme: 'light' }, state: undefined, onStateChange() {}, reload() {},
      data: { services: { preferences }, ...handed } } as any)} />
  </ViewerMobileContext.Provider></ViewerHostContext.Provider>;
  const view = render(element(workspace));
  return { ...view, show: (handed: object) => view.rerender(element(handed)) };
}
// A toolbar that draws what the frame hands it of the view (its own controls, its catching-up), as EditRibbon
// draws them at its tab row's right end.
const WITH_VIEW = Object.freeze({ ...WORKSPACE,
  ribbon: (_tools: unknown[], view: { controls?: React.ReactNode, status?: React.ReactNode } | null) =>
    <div role="toolbar" aria-label="Design">{view?.controls}{view?.status}</div> });
const backdrop = () => document.querySelector<HTMLElement>('[data-cad-scene-backdrop]')!;
const column = () => document.querySelector<HTMLElement>('[data-cad-tool-groups]')!;
const dock = (name: string) => document.querySelector<HTMLElement>(`[data-cad-dock="${name}"]`);
const workspaceLayer = () => document.querySelector<HTMLElement>('[data-cad-workspace]');
const stage = (name: string) => act(() => { fireEvent.click(document.querySelector(`[data-harness-stage="${name}"]`)!); });

it("keeps the canvas's box when the workspace shows", async () => {
  const view = shell();
  const box = backdrop();
  const frame = box.parentElement;
  // Nothing stands beside the canvas's box in the frame, in either layout: the chrome is over it.
  const beside = () => [backdrop().previousElementSibling, backdrop().nextElementSibling];
  expect(beside()).toEqual([null, null]);
  view.show(WORKSPACE);
  expect([backdrop(), backdrop().parentElement, beside()]).toEqual([box, frame, [null, null]]);
  const toolbar = screen.getByRole('toolbar', { name: 'Design' });
  for (const part of [toolbar, dock('navigator'), screen.getByRole('toolbar', { name: 'Timeline' })]) expect(box.contains(part)).toBe(true);
  // The strip's tools are the toolbar's.
  expect(toolbar.textContent).toBe('select pencil shapes keep pose');
  // Simple view again: the same box, and the canvas was never mounted again.
  view.show({});
  expect([backdrop(), backdrop().parentElement, beside()]).toEqual([box, frame, [null, null]]);
  await waitFor(() => expect(dock('navigator')).toBeNull());
  expect([screen.queryByRole('toolbar', { name: 'Design' }), screen.queryByRole('toolbar', { name: 'Timeline' }), viewport.mounts]).toEqual([null, null, 1]);
});

it("floats the design tree at the canvas's top left, folding to its title, and the dialog's place beside it", () => {
  places.length = 0;
  shell(WORKSPACE);
  const navigator = dock('navigator')!;
  // White, as the toolbar is: opaque, and blurring nothing of the live canvas under it.
  expect(navigator.className.split(/\s+/)).toEqual(expect.arrayContaining(WORKSPACE_SURFACE_CLASS.split(' ')));
  expect(navigator.className).not.toMatch(/\bbackdrop-|bg-background\//);
  const fold = within(navigator).getByRole('button', { name: 'FeatureManager' });
  const tree = within(navigator).getByRole('tree', { name: 'Features' });
  expect(fold.getAttribute('aria-expanded')).toBe('true');
  // Folded to its title, what it holds is kept, unseen; unfolded, it is back as it was.
  fireEvent.click(fold);
  expect([fold.getAttribute('aria-expanded'), navigator.contains(tree), Boolean(tree.closest('[hidden]'))]).toEqual(['false', true, true]);
  fireEvent.click(fold);
  expect([fold.getAttribute('aria-expanded'), Boolean(tree.closest('[hidden]'))]).toEqual(['true', false]);
  // The dialog's place is the renderer's, beside the navigator rather than in it, and over the canvas
  // rather than in the canvas's own layer.
  const place = places.at(-1)!;
  expect(place.hasAttribute('data-cad-command-card-place')).toBe(true);
  expect([place.parentElement, navigator.contains(place), place.closest('[data-mock-viewport]')]).toEqual([navigator.parentElement, false, null]);
});

it("keeps the strip, its panels and Quick Edit under the toolbar, and where they always were in Simple view", () => {
  const view = shell(WORKSPACE);
  const chrome = () => document.querySelector<HTMLElement>('[data-preview-chrome]')!;
  expect(backdrop().style.getPropertyValue('--cad-workspace-top')).toBe(`${TOOLBAR_HEIGHT}px`);
  expect(chrome().style.top).toBe('var(--cad-workspace-top, 0px)');
  view.show({});
  expect([backdrop().style.getPropertyValue('--cad-workspace-top'), chrome().style.top]).toEqual(['', '']);
});

it("opens Quick Edit on the file as a whole when the renderer says it was asked for, and keeps it shut until then", () => {
  const quickEdit = () => screen.queryByRole('region', { name: 'Quick Edit' });
  // Nothing picked and nothing drawn: the renderer that does not say leaves it to what it would carry, which is nothing.
  const view = shell();
  expect(quickEdit()).toBeNull();
  view.show({ quickEditAsked: true });
  expect(quickEdit()).not.toBeNull();
  // The workspace asks for it with Ask, and puts it away again with the answer.
  view.show({ quickEditAsked: false });
  expect(quickEdit()).toBeNull();
  view.show({ quickEditAsked: true, ...WORKSPACE });
  expect(quickEdit()).not.toBeNull();
});

it("fades the workspace out as Simple view takes its place, taking no presses while it goes, and puts it away at once with the rest of the tools", async () => {
  const view = shell();
  view.show(WORKSPACE);
  const layer = workspaceLayer()!;
  // One opacity transition, none where motion is reduced.
  expect(layer.className).toMatch(/\btransition-opacity\b.*\bduration-150\b.*\bmotion-reduce:transition-none\b/);
  expect(layer.hasAttribute('inert')).toBe(false);
  view.show({});
  expect([workspaceLayer(), layer.hasAttribute('inert'), layer.getAttribute('aria-hidden')]).toEqual([layer, true, 'true']);
  await waitFor(() => expect(workspaceLayer()).toBeNull());
  // While the model loads, the tools are put away, the workspace with them: at once.
  view.show(WORKSPACE);
  expect(workspaceLayer()).not.toBeNull();
  stage('finding');
  expect(workspaceLayer()).toBeNull();
  stage('idle');
  expect(workspaceLayer()).not.toBeNull();
});

it("puts Projection, Display and Preview, and the view catching up, in the toolbar while the workspace is up, and leaves them on the strip in Simple view", async () => {
  const view = shell(WITH_VIEW);
  const toolbar = screen.getByRole('toolbar', { name: 'Design' });
  const controls = ['Projection', 'Display mode', 'Preview'];
  // A control by its name, whatever it says it is set to ("Projection: Orthographic" is Projection).
  const named = (root: Element) => [...root.querySelectorAll('button')].map(button => (button.getAttribute('aria-label') || '').split(':')[0])
    .filter(name => controls.includes(name));
  expect([named(toolbar), named(column())]).toEqual([controls, []]);
  // The toolbar holds the tools too: the column keeps no strip at all.
  expect(within(column()).queryByRole('group', { name: 'Interaction tools' })).toBeNull();
  // A newer revision loading behind the model is said with the part's build status, at the toolbar's end.
  stage('editing');
  await waitFor(() => expect(toolbar.querySelector('[data-view-update-status]')).not.toBeNull());
  expect(column().querySelector('[data-view-update-status]')).toBeNull();
  // Simple view: the strip ends with them again, and the view catching up is under it, as it always was.
  view.show({});
  expect(named(column())).toEqual(controls);
  await waitFor(() => expect(column().querySelector('[data-view-update-status]')).not.toBeNull());
});

it("moves the column beside an open dialog, so a tool's own row and its panels never hide under it", () => {
  const view = shell({ ...WORKSPACE, dialogOpen: false });
  // No dialog: the column spans the view, an inset in, and centres what it holds.
  expect([column().style.left, column().className]).toEqual(['8px', expect.not.stringMatching(/\bleft-\[/)]);
  // A dialog beside the design tree: the column is the room past the dialog, or past the dialog alone in a
  // view too narrow for the navigator.
  view.show({ ...WORKSPACE, dialogOpen: true });
  expect(column().style.left).toBe('');
  expect(column().className).toMatch(/\bleft-\[calc\(35rem\+8px\)\] @max-xl\/cad-viewport:left-\[calc\(18rem\+16px\)\]/);
  view.show({ ...WORKSPACE, dialogOpen: false });
  expect(column().style.left).toBe('8px');
  // Simple view has no dialog's place to keep clear of.
  view.show({ dialogOpen: true });
  expect(column().style.left).toBe('8px');
});

// A toolbar that holds the strip's tools as buttons, as EditRibbon does: the Pencil taken up from it brings the drawing
// tools' row under it, the column's one row, and Keep (`panel.harness`'s) a panel to the tool stack under that.
const WITH_TOOLS = Object.freeze({ ...WORKSPACE,
  ribbon: (tools: { id: string, label: string, onSelect: () => void }[]) => <div role="toolbar" aria-label="Design">
    {tools.map(tool => <button key={tool.id} type="button" onClick={tool.onSelect}>{tool.label}</button>)}</div> });
const controls = () => document.querySelector<HTMLElement>('[data-cad-top-controls]')!;
const topRightLeft = () => backdrop().style.getPropertyValue('--cad-top-right-left');
/** How far the column is moved right: its margins, the one shift. */
const shifted = () => [column().style.marginLeft, column().style.marginRight];

/**
 * A view laid out as the app lays it, for the top controls' measure: `view` px wide; the column an inset in from its
 * sides, moved by its margins; its one row (`row` px wide) and the tool stack's panel (`panel`), each centred in it; and
 * the design tree 16rem wide, an inset in, open or folded to its 28px title, or no box at all where a view too narrow
 * for it hides it.
 */
function layOut({ view, row = 0, panel = 0, navigator = 'open' }:
  { view: number, row?: number, panel?: number, navigator?: 'open' | 'folded' | 'hidden' }) {
  const box = (x: number, y: number, width: number, height: number) => DOMRect.fromRect({ x, y, width, height });
  Element.prototype.getBoundingClientRect = function (this: Element) {
    const shift = parseFloat(document.querySelector<HTMLElement>('[data-cad-tool-groups]')?.style.marginLeft ?? '') || 0;
    const centred = (width: number) => 8 + (view - 16 - width) / 2 + shift;
    if (this.matches('[data-cad-dock="toolbar"]')) return box(0, 0, view, TOOLBAR_HEIGHT);
    if (this.matches('[data-cad-scene-backdrop]')) return box(0, 0, view, 700);
    if (this.matches('[data-cad-tool-groups]')) return box(8 + shift, TOOLBAR_HEIGHT + 8, view - 16, 500);
    if (this.matches('[data-cad-dock="navigator"]')) {
      return navigator === 'hidden' ? box(0, 0, 0, 0) : box(8, TOOLBAR_HEIGHT + 8, 256, navigator === 'folded' ? 28 : 400);
    }
    if (this.matches('[data-cad-tool-stack] [data-tool-panel]')) return panel ? box(centred(panel), TOOLBAR_HEIGHT + 60, panel, 120) : box(0, 0, 0, 0);
    const top = this.closest<HTMLElement>('[data-cad-top-controls]');
    if (top && (this === top || this.parentElement === top)) return box(centred(row), TOOLBAR_HEIGHT + 8, row, row ? 36 : 0);
    return boxOf.call(this);
  };
}
/** The frame's resize observers, called as a resize calls them (the controls taking a row, the view narrowed). */
function resizing() {
  const live = new Set<() => void>();
  vi.stubGlobal('ResizeObserver', class {
    callback: () => void;
    constructor(callback: () => void) { this.callback = callback; live.add(callback); }
    observe() {}
    unobserve() {}
    disconnect() { live.delete(this.callback); }
  });
  return () => act(() => { for (const callback of [...live]) callback(); });
}
/** The frame with the workspace up and the Pencil taken up from its toolbar, measured. */
function drawing(resize: () => void, workspace: object = WITH_TOOLS) {
  const view = shell(workspace);
  fireEvent.click(screen.getByRole('button', { name: 'Pencil' }));
  resize();
  expect(controls().children.length).toBeGreaterThan(0);
  return view;
}

it("leaves a row that clears the design tree centred across the view, and Quick Edit's room as it was", () => {
  const resize = resizing();
  // Centred in a 1280px view, a 300px row starts at 490, well past the navigator's right edge and an inset (264 + 8).
  layOut({ view: 1280, row: 300 });
  const view = drawing(resize);
  expect([...shifted(), topRightLeft()]).toEqual(['', '', '798px']);
  // The same as with no design tree at all.
  view.show({ ...WITH_TOOLS, leftDock: null });
  resize();
  expect([...shifted(), topRightLeft()]).toEqual(['', '', '798px']);
});

it("moves the column right by just the overlap of a row that would run under the design tree, and no further than it has room", () => {
  const resize = resizing();
  // Centred in a 700px view, a 300px row starts at 200: 72px short of the navigator's right edge and an inset.
  layOut({ view: 700, row: 300 });
  drawing(resize);
  expect(shifted()).toEqual(['72px', '-72px']);
  // Quick Edit's corner starts an inset past where the row now ends.
  expect(topRightLeft()).toBe(`${200 + 72 + 300 + 8}px`);
  // A row too wide to clear it goes as far as the column lets it: its right edge at the column's, (584 - 500) / 2 on.
  layOut({ view: 600, row: 500 });
  resize();
  expect(shifted()).toEqual(['42px', '-42px']);
});

it("moves the column past the design tree folded to its title too, and not while a narrow view hides it or a dialog stands beside it", () => {
  const resize = resizing();
  layOut({ view: 700, row: 300 });
  const view = drawing(resize);
  expect(shifted()).toEqual(['72px', '-72px']);
  // Folded, its title still stands at the rows' height, as wide: the row clears its right edge and an inset.
  fireEvent.click(within(dock('navigator')!).getByRole('button', { name: 'FeatureManager' }));
  layOut({ view: 700, row: 300, navigator: 'folded' });
  resize();
  expect([...shifted(), topRightLeft()]).toEqual(['72px', '-72px', `${200 + 72 + 300 + 8}px`]);
  // A view too narrow for it hides it: it has no box, and the row is centred again.
  layOut({ view: 700, row: 300, navigator: 'hidden' });
  resize();
  expect([...shifted(), topRightLeft()]).toEqual(['', '', `${200 + 300 + 8}px`]);
  // A dialog beside it: the column is the room past both (above), and is not moved within it.
  layOut({ view: 700, row: 300 });
  view.show({ ...WITH_TOOLS, dialogOpen: true });
  resize();
  expect(shifted()).toEqual(['', '']);
  expect(column().className).toMatch(/\bleft-\[calc\(35rem\+8px\)\]/);
});

it("moves the tool stack's panels with the rows, one shift for the column, so a panel never runs under the design tree", () => {
  const resize = resizing();
  // A 400px panel alone, centred in a 700px view, starts at 150: 122px short of the navigator's edge and an inset.
  layOut({ view: 700, panel: 400 });
  shell(WITH_TOOLS);
  fireEvent.click(screen.getByRole('button', { name: 'Keep' }));
  resize();
  expect(document.querySelector('[data-cad-tool-stack] [data-tool-panel]')).not.toBeNull();
  expect(shifted()).toEqual(['122px', '-122px']);
  // With the drawing tools' row over it, the panel, further left, decides, and both move as one: the row ends 122px on.
  fireEvent.click(screen.getByRole('button', { name: 'Pencil' }));
  layOut({ view: 700, row: 300, panel: 400 });
  resize();
  expect([...shifted(), topRightLeft()]).toEqual(['122px', '-122px', `${200 + 122 + 300 + 8}px`]);
});
