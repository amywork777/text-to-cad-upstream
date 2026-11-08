import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import ImportedBody from '../../../../dist/renderers/xbf/edit/ImportedBody.js';

afterEach(cleanup);

const PART = '3f2a9c1e-7b4d-5e6f-8a9b-0c1d2e3f4a5b';

it("makes a STEP brought in a part and opens it by its id once built, or opens the part made of it before", async () => {
  const user = userEvent.setup();
  const onOpen = vi.fn();
  const onAdopt = vi.fn(async () => ({ part: PART }));
  const onOpenPart = vi.fn(async () => PART);
  const { rerender } = render(<ImportedBody imported={{ part: null }} onAdopt={onAdopt} onOpenPart={onOpenPart} onOpen={onOpen} />);
  await user.click(screen.getByRole('button', { name: 'Edit as a part' }));
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith(PART));
  // Made before: it opens that part once the engine holds it, and makes no other.
  rerender(<ImportedBody imported={{ part: PART }} onAdopt={onAdopt} onOpenPart={onOpenPart} onOpen={onOpen} />);
  await user.click(screen.getByRole('button', { name: 'Open its part' }));
  await waitFor(() => expect(onOpen).toHaveBeenCalledTimes(2));
  expect([onAdopt.mock.calls.length, onOpenPart.mock.calls.length]).toEqual([1, 1]);
});

it("opens the part made of it before on its own in CAD mode, once, and never one whose build failed", async () => {
  const onOpen = vi.fn();
  const onOpenPart = vi.fn(async () => PART);
  const { rerender } = render(<ImportedBody imported={{ part: PART, error: 'no solid' }} onAdopt={async () => null}
    onOpenPart={onOpenPart} onOpen={onOpen} opensOnItsOwn />);
  expect(screen.getByText(/did not build: no solid/)).toBeTruthy();
  rerender(<ImportedBody imported={{ part: PART }} onAdopt={async () => null} onOpenPart={onOpenPart} onOpen={onOpen} opensOnItsOwn />);
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith(PART));
  rerender(<ImportedBody imported={{ part: PART }} onAdopt={async () => null} onOpenPart={onOpenPart} onOpen={onOpen} opensOnItsOwn />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Open its part' }).hasAttribute('disabled')).toBe(false));
  expect(onOpenPart).toHaveBeenCalledTimes(1);
});

it("says so when the part could not be made, opened or did not build, and opens nothing", async () => {
  const user = userEvent.setup();
  const onOpen = vi.fn();
  const { rerender } = render(<ImportedBody imported={{ part: null }} onAdopt={async () => null} onOpenPart={async () => PART} onOpen={onOpen} />);
  await user.click(screen.getByRole('button', { name: 'Edit as a part' }));
  await waitFor(() => expect(screen.getByText(/couldn't make it a part/)).toBeTruthy());
  rerender(<ImportedBody imported={{ part: PART }} onAdopt={async () => null} onOpenPart={async () => null} onOpen={onOpen} opensOnItsOwn />);
  await waitFor(() => expect(screen.getByText(/couldn't open its part/)).toBeTruthy());
  expect(onOpen).not.toHaveBeenCalled();
});
