import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import EditCustomFeature from '../../../../dist/renderers/xbf/edit/EditCustomFeature.js';

afterEach(cleanup);

// Edit Feature on a flange's Bolt Circle, as the engine reads its call (`test_edit_custom_features.py`).
const PARAMS = [
  { name: 'diameter', kind: 'length', label: 'Diameter', group: null, value: '60', code: 'BOLT_CIRCLE', input: 0, unit: 'mm' },
  { name: 'count', kind: 'count', label: 'Count', group: null, value: '6', code: '6', input: 1, unit: '' },
  { name: 'spread', kind: 'enum', label: 'Spread', group: 'Options', value: 'full', code: null, default: 'full',
    choices: [{ value: 'full', label: 'Full circle' }, { value: 'half', label: 'Half circle' }] },
  { name: 'staggered', kind: 'bool', label: 'Staggered', group: 'Options', value: false, code: null, default: false },
];
function edit(run = vi.fn(async () => ({ ok: true }))) {
  return {
    state: { units: 'mm', rows: [{ key: 'flange.py:12', custom: { name: 'Bolt Circle', function: 'flange_features.bolt_circle', params: PARAMS,
      collapsed: ['Options'] } }] },
    command: 'custom', editing: { command: 'custom', row: 'flange.py:12', id: 'flange.py:12' },
    saving: false, previewOn: false, previewFeature: vi.fn(), featurePreview: null, run, close: vi.fn(),
  };
}

it("opens on the call's values, its folded group closed, and OK writes what changed", async () => {
  const user = userEvent.setup();
  const opened = edit();
  render(<EditCustomFeature edit={opened as never} />);
  expect(screen.getByRole('dialog', { name: 'Bolt Circle' })).toBeTruthy();
  expect((screen.getByLabelText('Diameter') as HTMLInputElement).value).toBe('60');
  // Options is folded, as the feature asks: its parameters are not shown until it is opened.
  expect(screen.queryByLabelText('Staggered')).toBeNull();
  await user.click(screen.getByRole('checkbox', { name: 'Options' }));
  expect(screen.getByLabelText('Staggered')).toBeTruthy();
  const count = screen.getByLabelText('Count');
  await user.clear(count);
  await user.type(count, '8{Enter}');
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(opened.run).toHaveBeenCalledWith({ command: 'custom', function: 'flange_features.bolt_circle', inputs: { count: '8' }, picks: {},
    replace: { row: 'flange.py:12' } });
});

it('marks the parameter a refusal is about, as FeatureScript marks its faulty parameters', async () => {
  const user = userEvent.setup();
  const opened = edit(vi.fn(async () => ({ ok: false, error: 'Bolt Circle: count must be at least 1 (was 0). Nothing changed.',
    featureError: { message: 'Bolt Circle: count must be at least 1 (was 0)', feature: 'Bolt Circle', param: 'count' } })));
  render(<EditCustomFeature edit={opened as never} />);
  const count = screen.getByLabelText('Count');
  await user.clear(count);
  await user.type(count, '0{Enter}');
  await user.click(screen.getByRole('button', { name: 'OK' }));
  expect(screen.getByLabelText('Count').getAttribute('aria-invalid')).toBe('true');
  expect(screen.getByLabelText('Diameter').getAttribute('aria-invalid')).toBeNull();
});
