import '@emdash/ui/style.css';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { page } from 'vitest/browser';
import { CadParametersContent } from './cad-history-panel';

beforeAll(() => {
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
});

describe('CadParametersContent', () => {
  let host: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
  });

  it('edits deliberate source parameters without duplicating feature history', async () => {
    const onDraftChange = vi.fn();
    const onApply = vi.fn();
    await act(async () => {
      root.render(
        <CadParametersContent
          snapshot={{
            sourceHash: '1234567890abcdef',
            history: {
              diagnostics: [],
              groups: [
                {
                  id: 'gen_step',
                  functionName: 'gen_step',
                  label: 'Model assembly',
                  line: 20,
                  dependencies: ['_body'],
                  features: [
                    {
                      id: 'gen_step:21:AssemblyHelper:1',
                      operation: 'AssemblyHelper',
                      label: 'Assembly',
                      kind: 'assembly',
                      line: 21,
                    },
                  ],
                },
              ],
              parameters: [
                {
                  id: 'width',
                  symbol: 'WIDTH',
                  label: 'Width',
                  unit: 'mm',
                  min: 10,
                  max: 30,
                  step: 1,
                  defaultValue: 20,
                  line: 4,
                  span: [100, 102],
                  groupIds: [],
                  featureIds: [],
                },
              ],
            },
          }}
          drafts={{ width: 24 }}
          loading={false}
          busy={false}
          message={null}
          onDraftChange={onDraftChange}
          onRefresh={vi.fn()}
          onApply={onApply}
          onOpenSource={vi.fn()}
        />
      );
    });

    expect(page.getByText('Design parameters')).toBeVisible();
    expect(page.getByLabelText('Width', { exact: true })).toHaveValue(24);
    expect(page.getByRole('slider', { name: 'Width slider' })).toBeVisible();
    await page.getByRole('button', { name: 'Apply & view' }).click();
    expect(onApply).toHaveBeenCalledOnce();
    expect(page.getByText('Assembly')).not.toBeInTheDocument();
  });
});
