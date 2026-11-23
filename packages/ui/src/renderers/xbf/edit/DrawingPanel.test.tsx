import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import DrawingPanel from '../../../../dist/renderers/xbf/edit/DrawingPanel.js';

afterEach(cleanup);

const DRAWING = { script: 'parts/block_drawing.py', pdf: 'parts/block_drawing.pdf', drawn: true, size: 'A3', scale: '1:1', iso: true,
  title: 'BLOCK', part_number: 'BLOCK', material: '', revision: 'A', author: '' };

it("the drawing's sheet opens as its script has it, and OK sends the title block and views as changed", async () => {
  const user = userEvent.setup();
  const edit = { saving: false, state: { drawing: DRAWING }, drawing: vi.fn(async () => ({ ok: true })), stopInspecting: vi.fn() };
  render(<DrawingPanel edit={edit as never} />);
  expect(screen.getByText('Drawn to parts/block_drawing.pdf by parts/block_drawing.py. Its views and dimensions follow the part.')).toBeTruthy();
  // Nothing changed yet: OK has nothing to write.
  expect((screen.getByRole('button', { name: 'OK' }) as HTMLButtonElement).disabled).toBe(true);
  const revision = screen.getByRole('textbox', { name: 'Revision' });
  await user.clear(revision);
  await user.type(revision, 'B{Enter}');
  const scale = screen.getByRole('textbox', { name: 'Scale' });
  await user.clear(scale);
  await user.type(scale, '1:2{Enter}');
  await user.click(screen.getByRole('checkbox', { name: 'Isometric view' }));
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(edit.drawing).toHaveBeenCalledWith({ sheet: { size: 'A3', scale: '1:2', units: 'mm', iso: false, title: 'BLOCK', part_number: 'BLOCK', material: '',
    revision: 'B', author: '' } });
  expect(edit.stopInspecting).toHaveBeenCalled();
});

it("a drawing written its own way opens, says its sheet is set in its script, and only closes", async () => {
  const user = userEvent.setup();
  const edit = { saving: false, state: { drawing: { script: 'parts/lamp_drawing.py', pdf: '', drawn: false, readable: false } },
    drawing: vi.fn(), stopInspecting: vi.fn() };
  render(<DrawingPanel edit={edit as never} />);
  expect(screen.getByText(/parts\/lamp_drawing\.py draws this part in its own way/)).toBeTruthy();
  expect([screen.queryByRole('combobox', { name: 'Size' }), screen.queryByRole('button', { name: 'OK' })]).toEqual([null, null]);
  await user.click(screen.getByRole('button', { name: 'Close' }));
  expect([edit.stopInspecting.mock.calls.length, edit.drawing.mock.calls.length]).toEqual([1, 0]);
});
