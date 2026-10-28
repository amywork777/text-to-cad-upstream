import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import InsertComponents from '../../../../dist/renderers/xbf/edit/InsertComponents.js';

afterEach(cleanup);

it("lists the project's parts, waits for one, and inserts the one picked", async () => {
  const user = userEvent.setup();
  const edit = { saving: false, insertable: vi.fn(async () => ['fixtures/cap.py', 'parts/pin.py']),
    mate: vi.fn(async () => ({ ok: true })), stopInspecting: vi.fn() };
  render(<InsertComponents edit={edit as never} />);
  const ok = screen.getByRole('button', { name: 'OK' }) as HTMLButtonElement;
  expect(ok.disabled).toBe(true);
  await user.click(await screen.findByRole('option', { name: 'fixtures/cap.py' }));
  expect(ok.disabled).toBe(false);
  await user.click(ok);
  expect(edit.mate).toHaveBeenCalledWith({ insert: 'fixtures/cap.py' });
  await waitFor(() => expect(edit.stopInspecting).toHaveBeenCalled());
});
