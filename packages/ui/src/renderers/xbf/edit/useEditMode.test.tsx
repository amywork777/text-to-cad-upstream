import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { ViewerHostContext } from '../../../host/context.js';
import { testHost } from '../../../host/testing/host.js';
import ImportedBody from './ImportedBody.jsx';
import { useEditMode } from './useEditMode.js';

afterEach(cleanup);

const FILE = '/project/parts/plate.step';
const RESOURCE = { kind: 'workspace-file', path: FILE };
const read = (width: string) => ({
  ok: true, units: 'mm', files: { 'sizes.py': width },
  params: [{ id: 'sizes.py:2:8', name: 'WIDTH', text: width, value: Number(width), unit: 'mm', file: 'sizes.py', line: 2 }],
  rows: [{ key: 'r1', name: 'plate', kind: 'Box', inputs: [] }],
  dimensions: [{ id: '0:x', name: 'Length', label: width, display: width, formula: 'WIDTH', leaves: ['sizes.py:2:8'], row: 'r1', anchor: [0, 0, 0], lines: [] }],
  building: { scripts: [], done: 0, error: null },
});

/** A viewer server that keeps one number, WIDTH, in a part's sizes, and every call it is asked. */
function server() {
  let width = '20';
  const changes: object[] = [];
  const client = {
    // A probe asks only whether there is a part script to edit.
    editState: vi.fn(async (_file: string, _files: unknown, options?: { probe?: boolean }) => (options?.probe ? { ok: true, editable: true } : read(width))),
    editChange: vi.fn(async (change: { literal?: string; text: string }) => {
      changes.push(change);
      const from = width;
      width = change.text;
      return { ...read(width), change: { literal: 'sizes.py:2:8', name: 'WIDTH', file: 'sizes.py', line: 2, from, to: width } };
    }),
  };
  return { client, changes, width: () => width };
}

function hostWith(deliver: (context: unknown) => unknown) {
  const host = testHost({ promptContext: { getSnapshot: () => ({ kind: 'composer', available: true }), subscribe: () => () => {}, deliver } as never });
  return ({ children }: { children: ReactNode }) => <ViewerHostContext.Provider value={host}>{children}</ViewerHostContext.Provider>;
}

it('a part reads as its sizes and history, a change applies at once and the agent hears of it with the next message, and Undo puts the number back', async () => {
  const viewer = server();
  const notes: unknown[] = [];
  const { result } = renderHook(() => useEditMode({ client: viewer.client, file: FILE, resource: RESOURCE, active: true }),
    { wrapper: hostWith(context => { notes.push(context); return Promise.resolve({ status: 'added', partIds: [] }); }) });
  // Until the server says the file has a part script, the view is not laid out for editing.
  expect(result.current.status).toBe('probing');
  await act(async () => {});
  expect(result.current.status).toBe('ready');
  // As a CAD tool opens a part: nothing selected until the person picks a feature.
  expect(result.current.selected).toBe(null);
  expect(viewer.client.editState).toHaveBeenCalledWith(FILE, null, { probe: true });
  expect(viewer.client.editState).toHaveBeenCalledWith(FILE, null);

  await act(async () => { await result.current.change({ literal: 'sizes.py:2:8', text: '25' }); });
  expect(viewer.width()).toBe('25');
  expect(viewer.changes.at(-1)).toMatchObject({ file: FILE, literal: 'sizes.py:2:8', text: '25', files: { 'sizes.py': '20' } });
  // Queued for the person's next message, never sent: the agent does not start work because of it.
  expect(JSON.stringify(notes)).toContain('In edit mode I changed Width (WIDTH) from 20 to 25 (sizes.py, line 2).');
  expect(result.current.canUndo).toBe(true);

  await act(async () => { await result.current.undo(); });
  expect(viewer.width()).toBe('20');
  expect(viewer.changes.at(-1)).toMatchObject({ literal: 'sizes.py:2:8', text: '20' });
  expect(result.current.canUndo).toBe(false);
  expect(result.current.canRedo).toBe(true);
});

it('a read that finds the part as it was takes who made its features as it is now', async () => {
  vi.useFakeTimers();
  try {
    const viewer = server();
    const { result } = renderHook(() => useEditMode({ client: viewer.client, file: FILE, resource: RESOURCE, active: true }),
      { wrapper: hostWith(() => Promise.resolve()) });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.status).toBe('ready');
    const read = result.current.state;
    // A turn of the agent's ended: the part reads as it did, and the feature the turn made is marked.
    viewer.client.editState.mockResolvedValueOnce({ ok: true, unchanged: true, building: read.building, authors: { r1: 'agent' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(viewer.client.editState).toHaveBeenLastCalledWith(FILE, read.files);
    expect(result.current.state.authors).toEqual({ r1: 'agent' });
    expect(result.current.state.rows).toBe(read.rows);
  } finally {
    vi.useRealTimers();
  }
});

it("a part whose script stops says where it stopped, for as long as that error stands", async () => {
  const stoppedAt = { frames: [{ file: 'plate.py', line: 9, text: 'plate = fillet(plate.edges(), radius=WALL)' }] };
  const trace = 'Traceback (most recent call last):\n  File "/project/parts/plate.py", line 9, in plate\nValueError: Failed creating a fillet';
  const refusal = 'That number is no longer in the source. Look again.';
  const viewer = server();
  // The first read stops; a change is then refused in words; another change makes the script stop again.
  viewer.client.editState.mockImplementation(async (_file: string, _files: unknown, options?: { probe?: boolean }) => (
    options?.probe ? { ok: true, editable: true } : { ok: false, error: trace, failure: stoppedAt }));
  viewer.client.editChange.mockResolvedValueOnce({ ok: false, error: refusal });
  const { result } = renderHook(() => useEditMode({ client: viewer.client, file: FILE, resource: RESOURCE, active: true }),
    { wrapper: hostWith(() => Promise.resolve()) });
  await act(async () => {});
  expect(result.current.error).toBe(trace);
  expect(result.current.failure).toEqual(stoppedAt);

  // A refusal in words is another error: the place was the one before's.
  await act(async () => { await result.current.change({ literal: 'sizes.py:2:8', text: '5' }); });
  expect(result.current.error).toBe(refusal);
  expect(result.current.failure).toBe(null);

  // A change that makes the script stop says where, too, and dismissing the error takes the place with it.
  viewer.client.editChange.mockResolvedValueOnce({ ok: false, error: trace, failure: stoppedAt });
  await act(async () => { await result.current.change({ literal: 'sizes.py:2:8', text: '5000' }); });
  expect(result.current.failure).toEqual(stoppedAt);
  act(() => result.current.dismissError());
  expect(result.current.error).toBe('');
  expect(result.current.failure).toBe(null);
});

it('laid out for the AI, the part is read once and quietly, so Edit by hand opens on it at once', async () => {
  const viewer = server();
  const { result, rerender } = renderHook(({ reading }) => useEditMode({ client: viewer.client, file: FILE, resource: RESOURCE, active: true, reading }),
    { wrapper: hostWith(() => Promise.resolve()), initialProps: { reading: false } });
  await act(async () => {});
  expect(result.current.status).toBe('ready');
  expect(viewer.client.editState).toHaveBeenCalledWith(FILE, null);
  // Nothing more is asked while the AI layout is up: the part is not run again and again.
  const asked = viewer.client.editState.mock.calls.length;
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 1700)); });
  expect(viewer.client.editState).toHaveBeenCalledTimes(asked);
  // Edit by hand finds it read, and its first read asks only whether the files changed.
  rerender({ reading: true });
  expect(result.current.status).toBe('ready');
  await act(async () => {});
  expect(viewer.client.editState).toHaveBeenLastCalledWith(FILE, { 'sizes.py': '20' });
});

it('a switch to Edit by hand while the quiet read is out waits for that read, not for another', async () => {
  const viewer = server();
  let answer: (value: unknown) => void = () => {};
  viewer.client.editState.mockImplementation(async (_file: string, _files: unknown, options?: { probe?: boolean }) =>
    (options?.probe ? { ok: true, editable: true } : new Promise(resolve => { answer = resolve; })));
  const { result, rerender } = renderHook(({ reading }) => useEditMode({ client: viewer.client, file: FILE, resource: RESOURCE, active: true, reading }),
    { wrapper: hostWith(() => Promise.resolve()), initialProps: { reading: false } });
  await act(async () => {});
  expect(result.current.status).toBe('idle');
  rerender({ reading: true });
  await act(async () => {});
  expect(result.current.status).toBe('reading');
  // One read of the part, shared by both layouts.
  expect(viewer.client.editState.mock.calls.filter(call => call[1] === null && call.length === 2)).toHaveLength(1);
  await act(async () => { answer(read('20')); });
  expect(result.current.status).toBe('ready');
});

it('a model with no part script beside it is not edited, and the view stays as it was', async () => {
  const client = { editState: vi.fn(async () => ({ ok: true, editable: false })), editChange: vi.fn() };
  const { result } = renderHook(() => useEditMode({ client, file: '/project/imported.step', resource: RESOURCE, active: true }),
    { wrapper: hostWith(() => Promise.resolve()) });
  await act(async () => {});
  expect(result.current.status).toBe('none');
  // The part is never run to find out.
  expect(client.editState).toHaveBeenCalledTimes(1);
});

it('a server without edit mode leaves the view as it was', async () => {
  const client = { editState: vi.fn(async () => { throw new Error('404'); }), editChange: vi.fn() };
  const { result } = renderHook(() => useEditMode({ client, file: FILE, resource: RESOURCE, active: true }),
    { wrapper: hostWith(() => Promise.resolve()) });
  await act(async () => {});
  expect(result.current.status).toBe('none');
});

it('a client without edit mode has nothing to edit', () => {
  const { result } = renderHook(() => useEditMode({ client: {}, file: FILE, resource: RESOURCE, active: true }),
    { wrapper: hostWith(() => Promise.resolve()) });
  expect(result.current.status).toBe('none');
});

it('a command writes its line, the new feature is selected and its panel shut, the agent hears of it, and Undo takes the line back', async () => {
  const base = { ok: true, units: 'mm', files: { 'block.py': 'h1' }, params: [], dimensions: [], building: { scripts: [], done: 0, error: null },
    rows: [{ key: 'block.py:6', name: 'part', kind: 'Box', inputs: [] }] };
  const undo = { file: 'block.py', hunks: [{ start: 6, old: ['    part = fillet(...)\n'], new: [] }] };
  const filleted = { ...base, files: { 'block.py': 'h2' },
    rows: [...base.rows, { key: 'block.py:7', name: 'part', kind: 'Fillet', inputs: [] }],
    change: { kind: 'command', command: 'fillet', feature: 'Fillet', what: '4 edges', inputs: [{ label: 'Radius', display: '1', unit: 'mm' }],
      file: 'block.py', line: 7, row: 'block.py:7', undo, redo: { file: 'block.py', hunks: [] } } };
  const client = {
    editState: vi.fn(async (_file: string, _files: unknown, options?: { probe?: boolean }) => (options?.probe ? { ok: true, editable: true } : base)),
    editChange: vi.fn(async (request: { command?: object; splice?: object }) => (request.command ? filleted
      : { ...base, change: { kind: 'splice', file: 'block.py', line: 7 } })),
  };
  const notes: unknown[] = [];
  const { result } = renderHook(() => useEditMode({ client, file: FILE, resource: RESOURCE, active: true }),
    { wrapper: hostWith(context => { notes.push(context); return Promise.resolve({ status: 'added', partIds: [] }); }) });
  await act(async () => {});
  act(() => result.current.open('fillet'));
  expect(result.current.command).toBe('fillet');

  const request = { command: 'fillet', selection: [{ selector: 'e3' }], inputs: { radius: '1' } };
  await act(async () => { await result.current.run(request); });
  expect(client.editChange).toHaveBeenLastCalledWith({ command: request, file: FILE, files: { 'block.py': 'h1' } });
  expect(result.current.selected).toBe('block.py:7');
  expect(result.current.command).toBe(null);
  expect(JSON.stringify(notes)).toContain('In edit mode I added Fillet1, radius 1 mm, 4 edges (block.py, line 7).');

  await act(async () => { await result.current.undo(); });
  expect(client.editChange).toHaveBeenLastCalledWith({ splice: undo, file: FILE, files: { 'block.py': 'h2' } });
  expect(JSON.stringify(notes)).toContain('In edit mode I removed Fillet1 (block.py, line 7).');
  expect(result.current.canRedo).toBe(true);
});

it('a preview is made without writing anything, one at a time, the newest asked the one shown, and none once the panel shuts', async () => {
  const viewer = server();
  const asked: Array<{ preview?: object }> = [];
  const answers: Array<(reply: object) => void> = [];
  viewer.client.editChange.mockImplementation((change: { preview?: object }) => {
    asked.push(change);
    return new Promise(resolve => answers.push(resolve));
  });
  const { result } = renderHook(() => useEditMode({ client: viewer.client, file: FILE, resource: RESOURCE, active: true }),
    { wrapper: hostWith(() => Promise.resolve({ status: 'added', partIds: [] })) });
  await act(async () => {});
  act(() => result.current.open('fillet'));
  const first = { command: 'fillet', selection: [{ selector: 'e1' }], inputs: { radius: '1' } };
  const second = { ...first, inputs: { radius: '2' } };
  act(() => result.current.previewFeature(first));
  expect(result.current.featurePreview).toMatchObject({ status: 'updating' });
  // Asked again while the first is made: the second waits for it, and the first's answer is not shown.
  act(() => result.current.previewFeature(second));
  expect(asked).toEqual([{ preview: first, file: FILE, files: { 'sizes.py': '20' } }]);
  await act(async () => { answers[0]({ ok: true, preview: { removed: { positions: [], triangles: [], edges: [] }, added: null, error: null } }); });
  await waitFor(() => expect(asked).toHaveLength(2));
  expect(asked[1]).toEqual({ preview: second, file: FILE, files: { 'sizes.py': '20' } });
  expect(result.current.featurePreview).toMatchObject({ status: 'updating' });
  await act(async () => { answers[1]({ ok: true, preview: { error: 'Try a smaller radius.' } }); });
  await waitFor(() => expect(result.current.featurePreview).toMatchObject({ status: 'failed', error: 'Try a smaller radius.', removed: null }));
  // The same again is not asked again; the panel shut, none is shown. Nothing was written.
  act(() => result.current.previewFeature(second));
  expect(asked).toHaveLength(2);
  act(() => result.current.close());
  expect(result.current.featurePreview).toBe(null);
  expect(viewer.width()).toBe('20');
});

it('S asks the toolbar for its command search by counting, so each ask is heard once and an old one is not heard again', async () => {
  const viewer = server();
  const { result } = renderHook(() => useEditMode({ client: viewer.client, file: FILE, resource: RESOURCE, active: true }),
    { wrapper: hostWith(() => Promise.resolve()) });
  await act(async () => {});
  expect(result.current.findAsked).toBe(0);
  act(() => result.current.findCommand());
  expect(result.current.findAsked).toBe(1);
  act(() => result.current.findCommand());
  expect(result.current.findAsked).toBe(2);
});

it("a STEP brought in with no part script is offered as a part to edit, made beside it, built, and named by its id to open", async () => {
  const imported = '/project/vendor/pico.step';
  const PART = '3f2a9c1e-7b4d-5e6f-8a9b-0c1d2e3f4a5b';
  // The engine holds the part only once its build is done: the probe says it is building, then built.
  const probes = [{ ok: true, editable: false, importable: true }, { ok: true, editable: false, importable: true, part: PART, partBuilt: false, partBuilding: true },
    { ok: true, editable: false, importable: true, part: PART, partBuilt: true, partBuilding: false }];
  const client = {
    editState: vi.fn(async () => probes.shift() || probes.at(-1)),
    editChange: vi.fn(async () => ({ ok: true, part: PART, script: '/project/vendor/pico_part.py' })),
  };
  const { result } = renderHook(() => useEditMode({ client, file: imported, active: true }), { wrapper: hostWith(() => {}) });
  await waitFor(() => expect(result.current.status).toBe('none'));
  expect(result.current.imported).toEqual({ part: null, error: '' });
  vi.useFakeTimers({ toFake: ['setTimeout'] });
  try {
    let made: unknown = 'waiting';
    const adopting = result.current.adopt().then(reply => { made = reply; });
    await vi.advanceTimersByTimeAsync(0);
    // Not opened while it builds: an id never built is not built by opening it.
    expect(made).toBe('waiting');
    await vi.advanceTimersByTimeAsync(1000);
    await adopting;
    expect(client.editChange).toHaveBeenCalledWith({ file: imported, adopt: {} });
    expect(made).toMatchObject({ ok: true, part: PART });
  } finally {
    vi.useRealTimers();
  }
  // A build that ended without the part names none to open.
  probes.push({ ok: true, editable: false, importable: true, part: PART, partBuilt: false, partBuilding: false });
  await expect(result.current.importedPart()).resolves.toBe(null);
});

it("a part made of a STEP whose build failed says why, and a second press opens it rather than making another", async () => {
  const user = userEvent.setup();
  const imported = '/project/vendor/pico.step';
  const PART = '3f2a9c1e-7b4d-5e6f-8a9b-0c1d2e3f4a5b';
  let made = false;
  const client = {
    editState: vi.fn(async () => (made
      ? { ok: true, editable: false, importable: true, part: PART, partBuilt: false, partBuilding: false, partError: 'pico_part.py: the STEP this part reads is gone' }
      : { ok: true, editable: false, importable: true })),
    editChange: vi.fn(async () => { made = true; return { ok: true, part: PART, script: '/project/vendor/pico_part.py' }; }),
  };
  const onOpen = vi.fn();
  function Chip() {
    const edit = useEditMode({ client, file: imported, active: true });
    return edit.imported ? <ImportedBody imported={edit.imported} onAdopt={edit.adopt} onOpenPart={edit.importedPart} onOpen={onOpen} /> : null;
  }
  render(<Chip />, { wrapper: hostWith(() => {}) });
  await user.click(await screen.findByRole('button', { name: 'Edit as a part' }));
  await waitFor(() => expect(screen.getByText(/Its part did not build: pico_part\.py: the STEP this part reads is gone/)).toBeTruthy());
  // The part is made: pressed again it is asked after, never made a second time.
  await user.click(screen.getByRole('button', { name: 'Open its part' }));
  await waitFor(() => expect(client.editState.mock.calls.length).toBeGreaterThanOrEqual(3));
  expect(client.editChange).toHaveBeenCalledTimes(1);
  expect(onOpen).not.toHaveBeenCalled();
  expect(screen.getByText(/Its part did not build/)).toBeTruthy();
});

it("a part opened as its STEP names its document, builds it as New part does where the engine holds none, and counts the build", async () => {
  const DOCUMENT = '7c1e2d3f-4a5b-5c6d-8e7f-9a0b1c2d3e4f';
  // Never built (as the view opens, and as it is asked again): asked to build, then building, then built.
  const never = { ok: true, editable: true, document: DOCUMENT, partBuilt: false, partBuilding: false };
  const probes = [never, never, { ok: true, editable: true, document: DOCUMENT, partBuilt: false, partBuilding: true },
    { ok: true, editable: true, document: DOCUMENT, partBuilt: true, partBuilding: false }];
  const client = {
    editState: vi.fn(async (_file: string, _files: unknown, options?: { probe?: boolean }) => (options?.probe ? probes.shift() || probes.at(-1) : read('20'))),
    editChange: vi.fn(async () => ({ ok: true, document: DOCUMENT, building: { scripts: ['plate.py'], documents: [DOCUMENT], done: 0, error: null } })),
  };
  const { result } = renderHook(() => useEditMode({ client, file: FILE, active: true }), { wrapper: hostWith(() => {}) });
  await waitFor(() => expect(result.current.model).toEqual({ id: DOCUMENT, built: false, building: false }));
  expect(result.current.builds).toBe(0);
  vi.useFakeTimers({ toFake: ['setTimeout'] });
  try {
    let opened: unknown = 'waiting';
    const building = result.current.builtModel().then(id => { opened = id; });
    await vi.advanceTimersByTimeAsync(0);
    expect(client.editChange).toHaveBeenCalledWith({ file: FILE, build: true });
    // Not named to open while it builds: an id never built is not built by opening it.
    expect(opened).toBe('waiting');
    await vi.advanceTimersByTimeAsync(1000);
    await building;
    expect(opened).toBe(DOCUMENT);
  } finally {
    vi.useRealTimers();
  }
  expect(client.editChange).toHaveBeenCalledTimes(1);
  // Studio lists the part it built.
  await waitFor(() => expect(result.current.builds).toBe(1));
});

it("a part opened as its STEP whose build fails says why in the one phrase, and names nothing to open", async () => {
  const DOCUMENT = '7c1e2d3f-4a5b-5c6d-8e7f-9a0b1c2d3e4f';
  let asked = false;
  const client = {
    editState: vi.fn(async (_file: string, _files: unknown, options?: { probe?: boolean }) => (!options?.probe ? read('20') : asked
      ? { ok: true, editable: true, document: DOCUMENT, partBuilt: false, partBuilding: false, partError: "plate.py: NameError: name 'HEIGHTT' is not defined" }
      : { ok: true, editable: true, document: DOCUMENT, partBuilt: false, partBuilding: false })),
    editChange: vi.fn(async () => { asked = true; return { ok: true, document: DOCUMENT }; }),
  };
  const { result } = renderHook(() => useEditMode({ client, file: FILE, active: true }), { wrapper: hostWith(() => {}) });
  await waitFor(() => expect(result.current.model?.id).toBe(DOCUMENT));
  let opened: unknown = 'waiting';
  await act(async () => { opened = await result.current.builtModel(); });
  expect(opened).toBe(null);
  expect(result.current.error).toBe("Its part did not build: plate.py: NameError: name 'HEIGHTT' is not defined");
  expect(result.current.builds).toBe(0);
});

it("a build a change starts is counted once it ends, and one that fails is not", async () => {
  const viewer = server();
  const building = (done: number, error: string | null = null) => ({ ...read('20'), building: { scripts: ['plate.py'], documents: ['d'], done, error } });
  const replies = [building(0), building(1)];
  viewer.client.editState.mockImplementation(async (_file: string, _files: unknown, options?: { probe?: boolean }) => (options?.probe
    ? { ok: true, editable: true } : replies.shift() || building(1)));
  const { result } = renderHook(() => useEditMode({ client: viewer.client, file: FILE, active: true }), { wrapper: hostWith(() => {}) });
  await waitFor(() => expect(result.current.status).toBe('ready'));
  expect(result.current.builds).toBe(0);
  await waitFor(() => expect(result.current.builds).toBe(1), { timeout: 4000 });
  // A batch that failed is not a part Studio lists anew.
  replies.push(building(0), building(1, 'plate.py: the build failed'));
  await new Promise(resolve => setTimeout(resolve, 3400));
  expect(result.current.builds).toBe(1);
}, 10000);
