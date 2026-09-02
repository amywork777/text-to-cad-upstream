import '@emdash/ui/style.css';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../renderer/index.css';
import { CadSessionModelSelector } from './cad-session-model-selector';

beforeAll(() => {
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
});

describe('CadSessionModelSelector', () => {
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

  it('shows the active provider model and changes the live conversation model', async () => {
    const onChange = vi.fn();
    const onProviderChange = vi.fn(async () => {});
    await act(async () => {
      root.render(
        <CadSessionModelSelector
          providerId="claude"
          modelId="default"
          modelLabel="Default (recommended)"
          options={[
            { id: 'default', name: 'Default (recommended)', description: 'Provider default' },
            { id: 'sonnet', name: 'Sonnet', description: 'Efficient for routine tasks' },
          ]}
          providerOptions={['claude', 'codex']}
          disabled={false}
          onProviderChange={onProviderChange}
          onChange={onChange}
        />
      );
    });

    const selector = page.getByRole('button', { name: 'Choose agent and model' });
    expect(selector).toBeVisible();
    expect(selector).toHaveTextContent('Claude·Default');

    await selector.click();
    const defaultModel = page.getByRole('button', { name: /Default \(recommended\)/ });
    const sonnetModel = page.getByRole('button', { name: /Sonnet/ });
    expect(defaultModel).toBeVisible();
    expect(sonnetModel).toBeVisible();
    expect(getComputedStyle(defaultModel.query() as HTMLElement).borderRadius).toBe('8px');
    await defaultModel.hover();
    expect(getComputedStyle(defaultModel.query() as HTMLElement).borderRadius).toBe('8px');
    await page.getByRole('button', { name: /Sonnet/ }).click();
    expect(onChange).toHaveBeenCalledWith('sonnet');

    await selector.click();
    await page.getByRole('button', { name: 'Continue with Codex' }).click();
    expect(onProviderChange).toHaveBeenCalledWith('codex');
  });

  it('keeps selection available when the provider has not named its default yet', async () => {
    await act(async () => {
      root.render(
        <CadSessionModelSelector
          providerId="codex"
          modelId={null}
          modelLabel={null}
          options={[{ id: 'recommended', name: 'Recommended' }]}
          providerOptions={['claude', 'codex']}
          disabled={false}
          onProviderChange={vi.fn(async () => {})}
          onChange={vi.fn()}
        />
      );
    });

    expect(page.getByRole('button', { name: 'Choose agent and model' })).toHaveTextContent(
      'Recommended'
    );
  });

  it('shows the preloaded CAD skill state beside the agent choices', async () => {
    const onRepairCadRuntime = vi.fn(async () => {});
    await act(async () => {
      root.render(
        <CadSessionModelSelector
          providerId="codex"
          modelId="recommended"
          modelLabel="Recommended"
          options={[{ id: 'recommended', name: 'Recommended' }]}
          providerOptions={['codex']}
          cadRuntimeStatus={{
            state: 'error',
            packageName: 'cad@text-to-cad',
            message: 'Plugin setup failed',
            updatedAt: null,
          }}
          disabled={false}
          onProviderChange={vi.fn(async () => {})}
          onChange={vi.fn()}
          onRepairCadRuntime={onRepairCadRuntime}
        />
      );
    });

    await page.getByRole('button', { name: 'Choose agent and model' }).click();
    expect(page.getByText('CAD skills need attention')).toBeVisible();
    await page.getByRole('button', { name: 'Retry' }).click();
    expect(onRepairCadRuntime).toHaveBeenCalledOnce();
  });
});
