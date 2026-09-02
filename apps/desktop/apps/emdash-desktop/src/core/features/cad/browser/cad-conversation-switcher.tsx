import { Button, DropdownMenu, Input } from '@emdash/ui/react/primitives';
import { Archive, Check, Ellipsis, MessageSquare, Pencil, Plus, Trash2, X } from 'lucide-react';
import { useState } from 'react';

export interface CadConversationOption {
  id: string;
  title: string;
  isActive: boolean;
}

function conversationLabel(conversation: CadConversationOption): string {
  return conversation.title.trim() || 'Untitled chat';
}

export function CadConversationSwitcher({
  activeConversation,
  disabled,
  archiveDisabledReason,
  deleteDisabledReason,
  onCreate,
  onRename,
  onArchive,
  onDelete,
}: {
  activeConversation: CadConversationOption | null;
  disabled: boolean;
  archiveDisabledReason: string | null;
  deleteDisabledReason: string | null;
  onCreate: () => Promise<void>;
  onRename: (title: string) => Promise<void>;
  onArchive: () => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const beginRename = () => {
    setTitle(activeConversation?.title ?? '');
    setError(null);
    setRenaming(true);
  };

  const submitRename = async () => {
    const nextTitle = title.trim();
    if (busy || !nextTitle) return;
    setBusy(true);
    setError(null);
    try {
      await onRename(nextTitle);
      setRenaming(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not rename this chat.');
    } finally {
      setBusy(false);
    }
  };

  const createConversation = async () => {
    if (busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not create a new chat.');
    } finally {
      setBusy(false);
    }
  };

  const deleteActive = async () => {
    if (!activeConversation || deleteDisabledReason || busy) return;
    if (
      !window.confirm(
        `Delete “${conversationLabel(activeConversation)}” and its message history? This cannot be undone.`
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onDelete();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not delete this chat.');
    } finally {
      setBusy(false);
    }
  };

  const archiveActive = async () => {
    if (!activeConversation || archiveDisabledReason || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onArchive();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not archive this chat.');
    } finally {
      setBusy(false);
    }
  };

  if (renaming) {
    return (
      <form
        className="flex min-w-0 flex-1 items-center gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          void submitRename();
        }}
      >
        <Input
          autoFocus
          value={title}
          maxLength={100}
          aria-label="Chat name"
          className="h-7 min-w-0 flex-1 text-xs"
          onChange={(event) => setTitle(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setRenaming(false);
          }}
        />
        <Button
          type="submit"
          variant="ghost"
          size="xs"
          icon
          aria-label="Save chat name"
          disabled={busy || !title.trim()}
        >
          <Check className="size-3.5" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          icon
          aria-label="Cancel rename"
          onClick={() => setRenaming(false)}
        >
          <X className="size-3.5" />
        </Button>
      </form>
    );
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex min-w-0 items-center gap-1">
        <MessageSquare className="size-3.5 shrink-0 text-foreground-muted" />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">
          {activeConversation ? conversationLabel(activeConversation) : 'CAD chat'}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          icon
          disabled={disabled || busy}
          aria-label="New chat with the same CAD context"
          title="New chat"
          onClick={() => void createConversation()}
        >
          <Plus className="size-3.5" />
        </Button>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="xs"
                icon
                disabled={!activeConversation || disabled}
                aria-label="Chat actions"
                title="Chat actions"
              />
            }
          >
            <Ellipsis className="size-3.5" />
          </DropdownMenu.Trigger>
          <DropdownMenu.Content align="end" className="min-w-44">
            <DropdownMenu.Item onClick={beginRename}>
              <Pencil />
              Rename
            </DropdownMenu.Item>
            <DropdownMenu.Item
              disabled={Boolean(archiveDisabledReason) || busy}
              title={archiveDisabledReason ?? 'Archive this chat'}
              onClick={() => void archiveActive()}
            >
              <Archive />
              Archive chat
            </DropdownMenu.Item>
            <DropdownMenu.Separator />
            <DropdownMenu.Item
              variant="destructive"
              disabled={Boolean(deleteDisabledReason) || busy}
              title={deleteDisabledReason ?? 'Delete this chat'}
              onClick={() => void deleteActive()}
            >
              <Trash2 />
              Delete
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Root>
      </div>
      {error ? <p className="text-destructive px-5 pt-1 text-micro">{error}</p> : null}
    </div>
  );
}
