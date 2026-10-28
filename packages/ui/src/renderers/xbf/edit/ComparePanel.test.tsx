import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import ComparePanel from '../../../../dist/renderers/xbf/edit/ComparePanel.js';

afterEach(cleanup);

it("compare lists the part's earlier versions, newest first, and one picked says what the part gained and lost since it", async () => {
  const user = userEvent.setup();
  const now = Date.now() / 1000;
  const comparison = { now: 3, versions: [{ id: 2, time: now - 120, changed: ['block.py'] }, { id: 1, time: now - 7200, changed: ['sizes.py'] }] };
  const edit = { state: { units: 'mm' }, comparison, compare: vi.fn(async () => ({ ok: true })), stopInspecting: vi.fn() };
  const { rerender } = render(<ComparePanel edit={edit as never} />);
  // Opened, it asks for the versions.
  expect(edit.compare).toHaveBeenCalledWith(null);
  expect(screen.getByRole('button', { name: '2 min ago, before block.py changed' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '2 h ago, before sizes.py changed' })).toBeTruthy();
  await user.click(screen.getByRole('button', { name: '2 min ago, before block.py changed' }));
  expect(edit.compare).toHaveBeenLastCalledWith(2);
  rerender(<ComparePanel edit={{ ...edit, comparison: { ...comparison, version: 2, addedVolume: 0, removedVolume: 4.2920367 } } as never} />);
  expect(screen.getByText('Material it gained: 0 mm³')).toBeTruthy();
  expect(screen.getByText('Material it lost: 4.29 mm³')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Close' }));
  expect(edit.stopInspecting).toHaveBeenCalled();
});
