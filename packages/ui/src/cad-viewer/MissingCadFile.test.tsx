import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MissingCadFile } from '../../dist/cad-viewer/MissingCadFile.js';

beforeEach(() => vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const FILE = '/parts/new.step';

it('a missing file stays missing, and opens once the catalog has it at this very path', () => {
  const reload = vi.fn();
  const view = (entry: object | null) => <MissingCadFile file={FILE} entry={entry as never} reload={reload} />;
  const { rerender } = render(view(null));
  expect(screen.getByText('File does not exist')).toBeTruthy();
  rerender(view({ file: '/parts/other.step', hash: 'a', bytes: 10 }));
  expect(reload).not.toHaveBeenCalled();
  rerender(view({ file: FILE, hash: 'a', bytes: 10 }));
  expect(reload).toHaveBeenCalledTimes(1);
  // The same version of it opens once; another version of it opens again.
  rerender(view({ file: FILE, hash: 'a', bytes: 10 }));
  expect(reload).toHaveBeenCalledTimes(1);
  rerender(view({ file: FILE, hash: 'b', bytes: 12 }));
  expect(reload).toHaveBeenCalledTimes(2);
});

it('with no reload it is the missing-file presentation alone', () => {
  render(<MissingCadFile file={FILE} entry={{ file: FILE, hash: 'a', bytes: 10 } as never} />);
  expect(screen.getByText('File does not exist')).toBeTruthy();
});

it('a document the engine does not hold yet is asked again while the screen is up, and opens once the engine knows it', async () => {
  vi.useFakeTimers();
  try {
    const reload = vi.fn();
    const answers = [false, false, true];
    const recheck = vi.fn(() => Promise.resolve(answers.shift() ?? true));
    render(<MissingCadFile file="m_base" entry={null} reload={reload} recheck={recheck} title="This model is not saved" />);
    expect(screen.getByText('This model is not saved')).toBeTruthy();
    expect(recheck).not.toHaveBeenCalled();
    // Soon at first, then less often: 1 s, 2 s, 4 s.
    await vi.advanceTimersByTimeAsync(1000);
    expect(recheck).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(recheck).toHaveBeenCalledTimes(2);
    expect(reload).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(4000);
    expect(recheck).toHaveBeenCalledTimes(3);
    expect(reload).toHaveBeenCalledTimes(1);
    // Opened, it asks no more.
    await vi.advanceTimersByTimeAsync(30000);
    expect(recheck).toHaveBeenCalledTimes(3);
  } finally {
    vi.useRealTimers();
  }
});

it('a recheck that fails, or a screen that closes, never opens the document', async () => {
  vi.useFakeTimers();
  try {
    const reload = vi.fn();
    const recheck = vi.fn(() => Promise.reject(new Error('engine down')));
    const { unmount } = render(<MissingCadFile file="m_base" entry={null} reload={reload} recheck={recheck} />);
    await vi.advanceTimersByTimeAsync(3000);
    expect(recheck).toHaveBeenCalledTimes(2);
    unmount();
    await vi.advanceTimersByTimeAsync(60000);
    expect(recheck).toHaveBeenCalledTimes(2);
    expect(reload).not.toHaveBeenCalled();
  } finally {
    vi.useRealTimers();
  }
});
