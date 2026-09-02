import '@emdash/ui/style.css';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { page } from 'vitest/browser';
import { CadExecutionContextView, displayWorkspaceLabel } from './cad-execution-context';

describe('displayWorkspaceLabel', () => {
  it('removes the legacy implementation prefix from generated worktree names', () => {
    expect(displayWorkspaceLabel('emdash/wheel-edit')).toBe('wheel-edit');
    expect(displayWorkspaceLabel('feature/wheel-edit')).toBe('feature/wheel-edit');
  });
});

beforeAll(() => {
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
});

describe('CadExecutionContextView', () => {
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

  it('identifies the model worktree and local execution host', async () => {
    await act(async () => {
      root.render(
        <CadExecutionContextView
          workspaceLabel="feature/wheel-edit"
          workspacePath="/worktrees/wheel-edit"
          isWorktree
          locationLabel="This Mac"
          isRemote={false}
        />
      );
    });

    await expect
      .element(page.getByLabelText('Isolated worktree, feature/wheel-edit, runs on This Mac'))
      .toBeVisible();
  });

  it('identifies a remote project workspace without creating a second thread type', async () => {
    await act(async () => {
      root.render(
        <CadExecutionContextView
          workspaceLabel="main"
          workspacePath="/srv/projects/hardcore"
          isWorktree={false}
          locationLabel="Workshop Mac"
          isRemote
        />
      );
    });

    await expect
      .element(page.getByLabelText('Project folder, main, runs on Workshop Mac'))
      .toBeVisible();
  });
});
