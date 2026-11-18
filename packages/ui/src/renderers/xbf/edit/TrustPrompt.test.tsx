import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { ViewerHostContext } from '../../../host/context.js';
import { testHost } from '../../../host/testing/host.js';
import TrustPrompt from './TrustPrompt.jsx';
import { useEditMode } from './useEditMode.js';

afterEach(cleanup);

const FILE = '/project/parts/flange.step';
const RESOURCE = { kind: 'workspace-file', path: FILE };
const FILES = [{ file: 'flange_features.py', features: ['Bolt Circle', 'Edge Break'] }];
// What the edit service answers for a project whose custom features are not trusted: nothing of it ran (`cad/edit/trust.py`).
const UNTRUSTED = { ok: false, reason: 'untrusted', error: 'This project contains custom code features.', trust: { digest: 'd1', files: FILES, changed: false } };
const READ = { ok: true, units: 'mm', files: { 'flange.py': 'h' }, params: [], rows: [{ key: 'r1', name: 'body', kind: 'Bolt Circle', inputs: [] }],
  dimensions: [], building: { scripts: [], done: 0, error: null } };

const wrapper = ({ children }: { children: ReactNode }) => <ViewerHostContext.Provider value={testHost()}>{children}</ViewerHostContext.Provider>;

it('an untrusted project is not read: the prompt names its custom code, and Trust and run trusts it by its digest, then reads the part', async () => {
  let trusted = false;
  const client = {
    editState: vi.fn(async (_file: string, _files: unknown, options?: { probe?: boolean }) => (options?.probe ? { ok: true, editable: true } : trusted ? READ : UNTRUSTED)),
    editChange: vi.fn(async (change: { trust?: { digest: string } }) => { trusted = change.trust?.digest === 'd1'; return trusted ? READ : UNTRUSTED; }),
  };
  const { result } = renderHook(() => useEditMode({ client, file: FILE, resource: RESOURCE, active: true }), { wrapper });
  await act(async () => {});
  expect(result.current.status).toBe('untrusted');
  expect(result.current.trust).toMatchObject({ digest: 'd1', files: FILES, declined: false });
  // Not an error of the part's: it never ran.
  expect(result.current.error).toBe('');

  await act(async () => { await result.current.trustProject(); });
  expect(client.editChange).toHaveBeenCalledWith({ file: FILE, trust: { digest: 'd1' } });
  expect(result.current.status).toBe('ready');
  expect(result.current.trust).toBe(null);
  expect(result.current.state.rows[0].kind).toBe('Bolt Circle');
});

it('the prompt asks before any custom code runs, says what changed, and Not now folds it to a line that opens it again', async () => {
  const user = userEvent.setup();
  const onTrust = vi.fn(async () => true);
  const onDecline = vi.fn();
  const onReview = vi.fn();
  const { rerender } = render(<TrustPrompt trust={UNTRUSTED.trust} onTrust={onTrust} onDecline={onDecline} onReview={onReview} />);
  expect(screen.getByRole('alertdialog', { name: 'This project contains custom code features. Trust and run?' })).toBeTruthy();
  expect(screen.getByText('flange_features.py')).toBeTruthy();
  expect(screen.getByText(/Bolt Circle, Edge Break/)).toBeTruthy();
  // It is a trust gate, not a sandbox, and says so.
  expect(screen.getByText(/runs with your permissions/)).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Trust and run' }));
  await waitFor(() => expect(onTrust).toHaveBeenCalledTimes(1));
  await user.click(screen.getByRole('button', { name: 'Not now' }));
  expect(onDecline).toHaveBeenCalledTimes(1);

  rerender(<TrustPrompt trust={{ ...UNTRUSTED.trust, changed: true }} onTrust={onTrust} onDecline={onDecline} onReview={onReview} />);
  expect(screen.getByRole('alertdialog', { name: /custom code features changed\. Trust and run\?/ })).toBeTruthy();
  rerender(<TrustPrompt trust={{ ...UNTRUSTED.trust, declined: true }} onTrust={onTrust} onDecline={onDecline} onReview={onReview} />);
  expect(screen.queryByRole('alertdialog')).toBe(null);
  await user.click(screen.getByRole('button', { name: 'Review' }));
  expect(onReview).toHaveBeenCalledTimes(1);
});
