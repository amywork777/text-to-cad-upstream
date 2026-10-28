import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import EditSizes, { sharedFiles, sizeRows } from '../../../../dist/renderers/xbf/edit/EditSizes.js';

afterEach(cleanup);

const ROW = {
  key: 'geometry.py:9', file: 'geometry.py', kind: 'Hole',
  inputs: [
    { label: 'Diameter', display: '4.4', unit: 'mm', leaves: ['geometry.py:9:40'] },
    { label: 'X', display: '-10', unit: 'mm', leaves: ['geometry.py:8:15'] },
    { label: 'X', display: '10', unit: 'mm', leaves: ['sizes.py:2:8'] },
  ],
};

it("labels a row's sizes as the row has them, two of one told apart, and names the other files they are in", () => {
  const rows = sizeRows(ROW);
  expect(rows.map(row => row.label)).toEqual(['Diameter', 'X', 'X (2)']);
  expect(sharedFiles(rows, ROW.file)).toEqual(['sizes.py']);
});

it("writes only the sizes typed over, together, and says where a shared one lives", async () => {
  const user = userEvent.setup();
  const setSizes = vi.fn(async () => ({ ok: true }));
  const previewSizes = vi.fn();
  const edit = { editing: { row: ROW.key, title: 'Hole (3)', kind: 'Hole' }, state: { rows: [ROW] }, saving: false, setSizes, close: vi.fn(),
    previewOn: true, previewSizes, previewFeature: vi.fn() };
  render(<EditSizes edit={edit as never} />);
  expect(screen.getByRole('note').textContent).toContain('sizes.py');
  const diameter = screen.getByRole('textbox', { name: 'Diameter' });
  await user.clear(diameter);
  await user.type(diameter, '5{Enter}');
  // Previewed as typed, as a command's preview is: what the new size adds and takes away.
  await waitFor(() => expect(previewSizes).toHaveBeenCalledWith({ row: ROW.key, values: [{ index: 0, text: '5' }] }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(setSizes).toHaveBeenCalledWith(ROW.key, [{ index: 0, text: '5' }], ['diameter 5 mm']);
  // Nothing typed over: OK closes it, writing nothing.
  cleanup();
  setSizes.mockClear();
  render(<EditSizes edit={edit as never} />);
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(setSizes).not.toHaveBeenCalled();
  expect(edit.close).toHaveBeenCalled();
});
