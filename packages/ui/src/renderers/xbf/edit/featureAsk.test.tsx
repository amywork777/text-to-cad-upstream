import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import QuickEdit from '../../../../dist/renderers/kit/tools/quick-edit/QuickEdit.js';
import { ViewerHostContext } from '../../../../dist/host/context.js';
import { testHost } from '../../../../dist/host/testing/host.js';
import { featureTree } from '../../../../dist/renderers/xbf/edit/editMode.js';
import { featureAsk } from '../../../../dist/renderers/xbf/edit/featureAsk.js';
import { featurePick, pickedReferences } from '../../../../dist/renderers/xbf/edit/selectionBar.js';

afterEach(cleanup);

const sketched = (name: string, line: number) => ({ name, plane: 'Top', file: 'bracket.py', line, status: 'Fully defined' });
const command = { command: 'extrude', values: {}, keeps: '' };
// The sample bracket as the engine reads it, with the project the engine says it starts in: Sketch1, Boss-Extrude1,
// Sketch2, Boss-Extrude2, Fillet1, Hole1.
const STATE = {
  units: 'mm', name: 'bracket', root: '/work/bracket', script: '/work/bracket/bracket.py', files: { 'bracket.py': 'ab12' },
  features: [
    { key: 'e1', kind: 'Boss-Extrude', name: 'plate', file: 'bracket.py', line: 8, edit: command, sketch: sketched('SKETCH_000', 5) },
    { key: 'e2', kind: 'Boss-Extrude', name: 'plate', file: 'bracket.py', line: 13, edit: command, sketch: sketched('SKETCH_001', 10) },
    { key: 'b1', kind: 'Fillet', name: 'plate', file: 'bracket.py', line: 15 },
    { key: 'h1', kind: 'Hole', name: 'plate', file: 'bracket.py', line: 17 },
  ],
};
const TREE = featureTree(STATE);
const resource = { kind: 'workspace-file', path: '/work/bracket/bracket.step', revision: 'r1' } as const;
const composer = { kind: 'composer', available: true } as const;
const ask = (id: string, onRemove = vi.fn()) => featureAsk({ state: STATE, tree: TREE, pick: featurePick(TREE, id), onRemove } as never);

it('names the feature chosen as a chip in the design tree\'s words, with the range of its script it stands for', () => {
  const hole = ask('h1')!;
  expect(hole.chip.key).toBe('feature:h1');
  expect(hole.chip.label).toBe('Hole1');
  expect(hole.reference.label).toBe('Hole1');
  expect(hole.reference.target).toEqual({ kind: 'text-range', start: { line: 16, character: 0 }, end: { line: 17, character: 0 } });
  expect(hole.reference.resource).toEqual({ kind: 'workspace-file', path: '/work/bracket/bracket.py' });
  // A sketch is named as the tree names it, and stands for its own lines.
  const sketch = ask('sketch:e2')!;
  expect([sketch.chip.label, sketch.reference.target.start.line]).toEqual(['Sketch2', 9]);
});

it('makes nothing of a feature whose place in the script it cannot give', () => {
  const lost = featureAsk({ state: { ...STATE, root: undefined, script: undefined, files: undefined }, tree: TREE, pick: featurePick(TREE, 'h1'), onRemove: vi.fn() } as never);
  expect(lost).toBeNull();
});

it('Ask on a feature: Quick Edit shows its chip, whose X lets go of it, and Send carries its statement beside the file and the note', async () => {
  const send = vi.fn(async () => ({ status: 'sent' as const, partIds: [] }));
  const host = testHost({ promptContext: { getSnapshot: () => composer, subscribe: () => () => {}, deliver: vi.fn(), send } as never });
  const onRemove = vi.fn();
  const feature = ask('h1', onRemove)!;
  const { references, chips } = pickedReferences({ selectionActionVisible: false, selection: [], selectionChips: [], feature });
  render(<ViewerHostContext.Provider value={host}><div data-slot="cad-file-view">
    <QuickEdit resource={resource} asked references={references as never} chips={chips as never} />
  </div></ViewerHostContext.Provider>);
  const box = screen.getByRole('region', { name: 'Quick Edit' });
  // The chip shows, named as the design tree names the hole, and its X lets go of the pick.
  expect(within(box).getByRole('button', { name: 'Hole1' })).toBeTruthy();
  fireEvent.click(within(box).getByRole('button', { name: 'Remove Hole1' }));
  expect(onRemove).toHaveBeenCalledTimes(1);
  // Send: the note, the file, and the range of the script the hole is made on.
  const note = screen.getByRole('textbox', { name: 'Describe your changes' });
  note.textContent = 'Make it 3.4 mm.';
  fireEvent.input(note);
  fireEvent.click(within(box).getByRole('button', { name: 'Send' }));
  await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
  const context = (send.mock.calls[0] as unknown[])[0] as any;
  expect(context.parts.map((part: any) => [part.id, part.kind])).toEqual([['text', 'text'], ['file', 'reference'], ['reference-0', 'reference']]);
  const range = context.parts[2].reference;
  expect([range.resource.path, range.target.kind, range.label]).toEqual(['/work/bracket/bracket.py', 'text-range', 'Hole1']);
  expect(range.target.start).toEqual({ line: 16, character: 0 });
});
