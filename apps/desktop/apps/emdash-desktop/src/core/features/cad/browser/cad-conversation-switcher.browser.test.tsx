import '@emdash/ui/style.css';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { page } from 'vitest/browser';
import { CadConversationSwitcher } from './cad-conversation-switcher';

beforeAll(() => {
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
});

describe('CadConversationSwitcher', () => {
  let host: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await act(async () => root.unmount());
    host.remove();
  });

  it('keeps the current chat header quiet and puts actions in one menu', async () => {
    const onRename = vi.fn(async () => {});
    const onArchive = vi.fn(async () => {});
    const onDelete = vi.fn(async () => {});
    const onCreate = vi.fn(async () => {});

    await act(async () => {
      root.render(
        <CadConversationSwitcher
          activeConversation={{
            id: 'review',
            title: 'Review',
            isActive: true,
          }}
          disabled={false}
          archiveDisabledReason={null}
          deleteDisabledReason={null}
          onCreate={onCreate}
          onRename={onRename}
          onArchive={onArchive}
          onDelete={onDelete}
        />
      );
    });

    expect(page.getByText('Review', { exact: true })).toBeVisible();
    expect(page.getByRole('button', { name: 'Switch model chat' }).query()).toBeNull();
    const newChatButton = page.getByRole('button', {
      name: 'New chat with the same CAD context',
    });
    expect(newChatButton).toBeVisible();

    await newChatButton.click();
    await vi.waitFor(() => expect(onCreate).toHaveBeenCalledOnce());

    await page.getByRole('button', { name: 'Chat actions' }).click();
    expect(page.getByRole('menuitem', { name: 'Rename' })).toBeVisible();
    expect(page.getByRole('menuitem', { name: 'Archive chat' })).toBeVisible();
    expect(page.getByRole('menuitem', { name: 'Delete' })).toBeVisible();

    await page.getByRole('menuitem', { name: 'Archive chat' }).click();
    await vi.waitFor(() => expect(onArchive).toHaveBeenCalledOnce());

    await page.getByRole('button', { name: 'Chat actions' }).click();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await page.getByRole('menuitem', { name: 'Delete' }).click();
    await vi.waitFor(() => expect(onDelete).toHaveBeenCalledOnce());

    await page.getByRole('button', { name: 'Chat actions' }).click();
    await page.getByRole('menuitem', { name: 'Rename' }).click();
    const renameInput = page.getByRole('textbox', { name: 'Chat name' });
    expect(renameInput).toBeVisible();
    await renameInput.fill('Supplier review');
    await page.getByRole('button', { name: 'Save chat name' }).click();
    await vi.waitFor(() => expect(onRename).toHaveBeenCalledWith('Supplier review'));
  });
});
