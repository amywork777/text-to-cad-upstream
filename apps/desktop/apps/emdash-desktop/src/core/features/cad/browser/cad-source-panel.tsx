import type { HostFileRef } from '@emdash/core/primitives/path/api';
import { Badge, Button, DropdownMenu } from '@emdash/ui/react/primitives';
import {
  AlertTriangle,
  CheckCircle2,
  Code2,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  RotateCcw,
  Save,
} from 'lucide-react';
import { observer } from 'mobx-react-lite';
import { useCallback, useMemo, useRef, useState } from 'react';
import type { CadMigrationResult } from '@core/features/browser/api';
import { getBrowserClient } from '@core/features/browser/api/browser/client';
import {
  cadSourcePanelPresentation,
  migratedCadSourcePath,
} from '@core/features/cad/api/cad-source-path';
import type { SaveFileError } from '@core/features/editor/api/browser/open-file-store/open-file-store';
import { useEmbeddedSourceEditor } from '@core/features/editor/contributions/browser/use-embedded-source-editor';
import type { TaskTabContext } from '@core/features/workbench/api/browser/tabs/task-tab-context';
import { useOpenModal } from '@core/manifests/browser/modal-api';
import { hostFileRefFromNativePath } from '@core/primitives/desktop-runtime/api';
import { useTheme } from '@core/primitives/theme/browser';
import type { CadTabResource } from '../api/browser/cad-tab-resource';
import { useCadSourceRebuild } from './use-cad-source-rebuild';

export const CadSourcePanel = observer(function CadSourcePanel({
  resource,
  task,
  sourcePath,
  onMigrated,
}: {
  resource: CadTabResource;
  task: TaskTabContext;
  sourcePath: string;
  onMigrated: (result: Extract<CadMigrationResult, { success: true }>) => Promise<void> | void;
}) {
  const connectionId = task.getRemoteConnectionId?.();
  const presentation = cadSourcePanelPresentation(sourcePath);
  const migratedName = migratedCadSourcePath(sourcePath)?.split(/[\\/]/).at(-1);
  const openConfirm = useOpenModal('confirmActionModal');
  const fileRef = useMemo<HostFileRef>(
    () => hostFileRefFromNativePath(sourcePath, connectionId),
    [connectionId, sourcePath]
  );
  const [saving, setSaving] = useState(false);
  const [migrating, setMigrating] = useState(false);
  const [needsRebuild, setNeedsRebuild] = useState(false);
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);
  const saveShortcutRef = useRef<() => void>(() => {});
  const { effectiveTheme } = useTheme();
  const {
    entry,
    editorHostRef,
    save: saveEditorBuffer,
    discard,
    loading,
  } = useEmbeddedSourceEditor({
    fileRef,
    effectiveTheme,
    onSavedByKeyboard: () => saveShortcutRef.current(),
    readOnly: presentation.readOnly,
  });
  const { rebuildSource, rebuilding, runInProgress } = useCadSourceRebuild({
    resource,
    task,
    sourcePath,
  });

  const saveBuffer = useCallback(async (): Promise<boolean> => {
    if (!entry || presentation.readOnly) return false;
    setSaving(true);
    setMessage(null);
    try {
      const result = await saveEditorBuffer();
      if (result.success) return true;
      setMessage({ tone: 'error', text: saveErrorMessage(result.error) });
      return false;
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : 'Could not save the source file.',
      });
      return false;
    } finally {
      setSaving(false);
    }
  }, [entry, presentation.readOnly, saveEditorBuffer]);

  const saveOnly = useCallback(async () => {
    const saved = await saveBuffer();
    if (!saved) return;
    setNeedsRebuild(true);
    setMessage({ tone: 'success', text: 'Source saved. Rebuild to update the 3D model.' });
  }, [saveBuffer]);

  saveShortcutRef.current = () => void saveOnly();

  const migrateLegacySource = async () => {
    if (!presentation.legacy || migrating || runInProgress || rebuilding) return;
    if (connectionId) {
      setMessage({ tone: 'error', text: 'Legacy migration is available for local projects only.' });
      return;
    }
    const outcome = await openConfirm({
      title: 'Migrate legacy CAD source?',
      description: `Hardcore will use cadgen to rewrite and rename this source to ${migratedName ?? 'a plain .py file'}. The accepted STEP stays unchanged.`,
      confirmLabel: 'Migrate',
      variant: 'default',
    });
    if (!outcome.success) return;
    setMigrating(true);
    setMessage(null);
    try {
      const result = await (
        await getBrowserClient()
      ).migrateLegacyCadModel(
        { workspacePath: resource.workspacePath, filePath: sourcePath },
        { timeoutMs: 150_000 }
      );
      if (!result.success) {
        setMessage({ tone: 'error', text: result.error });
        return;
      }
      await onMigrated(result);
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : 'Could not migrate the legacy CAD source.',
      });
    } finally {
      setMigrating(false);
    }
  };

  const rebuildAndView = async () => {
    if (!entry || rebuilding || runInProgress) return;
    setMessage(null);
    const result = await rebuildSource({
      restoreSourceOnFailure: false,
      prepare: async () => {
        if (!entry.dirty) return { success: true };
        const saved = await saveBuffer();
        return saved
          ? { success: true }
          : { success: false, error: 'The source could not be saved before rebuilding.' };
      },
    });
    if (!result.success) {
      setNeedsRebuild(true);
      setMessage({ tone: 'error', text: result.error });
      return;
    }
    setNeedsRebuild(false);
    setMessage(null);
    resource.setWorkspaceMode('3d');
  };

  const blocked = saving || rebuilding || migrating || runInProgress;

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="@container flex min-h-12 shrink-0 items-center gap-3 border-b px-4">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-background-secondary text-foreground-muted">
          <Code2 className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div
            className="truncate text-xs font-medium text-foreground"
            title={sourcePath.split(/[\\/]/).at(-1)}
          >
            {sourcePath.split(/[\\/]/).at(-1)}
          </div>
          <div
            className="truncate text-micro text-foreground-tertiary-muted"
            title={presentation.subtitle}
          >
            {presentation.subtitle}
          </div>
        </div>
        <div className="shrink-0 @max-[680px]:hidden">
          {!presentation.readOnly && entry?.dirty ? (
            <Badge tone="warning" variant="soft">
              Unsaved
            </Badge>
          ) : needsRebuild ? (
            <Badge tone="warning" variant="soft">
              Rebuild needed
            </Badge>
          ) : null}
        </div>
        {presentation.legacy ? (
          <Button
            type="button"
            size="xs"
            disabled={blocked || loading || Boolean(connectionId)}
            onClick={() => void migrateLegacySource()}
          >
            {migrating ? (
              <Loader2 className="mr-1 size-3 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 size-3" />
            )}
            Migrate
          </Button>
        ) : (
          <>
            <div className="hidden shrink-0 items-center gap-1 @min-[561px]:flex">
              {entry?.dirty ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  disabled={blocked}
                  onClick={() => {
                    discard();
                    setMessage(null);
                  }}
                >
                  <RotateCcw className="mr-1 size-3" />
                  Discard
                </Button>
              ) : null}
              <Button
                type="button"
                variant="secondary"
                size="xs"
                disabled={blocked || !entry?.dirty}
                onClick={() => void saveOnly()}
              >
                {saving ? (
                  <Loader2 className="mr-1 size-3 animate-spin" />
                ) : (
                  <Save className="mr-1 size-3" />
                )}
                Save
              </Button>
            </div>
            <Button
              type="button"
              size="xs"
              disabled={blocked || loading}
              onClick={() => void rebuildAndView()}
            >
              {rebuilding || runInProgress ? (
                <Loader2 className="mr-1 size-3 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-1 size-3" />
              )}
              Rebuild & view
            </Button>
            <div className="hidden shrink-0 @max-[560px]:block">
              <DropdownMenu.Root>
                <DropdownMenu.Trigger
                  render={
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      icon
                      aria-label="More source actions"
                    >
                      <MoreHorizontal className="size-3.5" />
                    </Button>
                  }
                />
                <DropdownMenu.Content align="end">
                  {!presentation.readOnly && entry?.dirty ? (
                    <>
                      <DropdownMenu.Item disabled>Unsaved changes</DropdownMenu.Item>
                      <DropdownMenu.Separator />
                    </>
                  ) : needsRebuild ? (
                    <>
                      <DropdownMenu.Item disabled>Rebuild needed</DropdownMenu.Item>
                      <DropdownMenu.Separator />
                    </>
                  ) : null}
                  <DropdownMenu.Item
                    disabled={blocked || !entry?.dirty}
                    onClick={() => void saveOnly()}
                  >
                    <Save className="size-4" />
                    Save source
                  </DropdownMenu.Item>
                  {entry?.dirty ? (
                    <DropdownMenu.Item
                      disabled={blocked}
                      onClick={() => {
                        discard();
                        setMessage(null);
                      }}
                    >
                      <RotateCcw className="size-4" />
                      Discard changes
                    </DropdownMenu.Item>
                  ) : null}
                </DropdownMenu.Content>
              </DropdownMenu.Root>
            </div>
          </>
        )}
      </div>

      {presentation.legacy ? (
        <div className="bg-warning/5 flex items-start gap-2 border-b px-4 py-2 text-tiny text-foreground-muted">
          <AlertTriangle className="text-warning mt-0.5 size-3.5 shrink-0" />
          <span>
            This old .step.py/.stp.py generator is view-only. Migrate it explicitly to edit a plain
            Python model; Hardcore will keep the accepted STEP unchanged.
          </span>
        </div>
      ) : null}

      {message ? (
        <div
          className={`flex items-center gap-2 border-b px-4 py-2 text-tiny ${
            message.tone === 'error'
              ? 'border-destructive/30 bg-destructive/5 text-destructive'
              : 'bg-success/5 text-success'
          }`}
          role={message.tone === 'error' ? 'alert' : 'status'}
        >
          {message.tone === 'error' ? (
            <AlertTriangle className="size-3.5 shrink-0" />
          ) : (
            <CheckCircle2 className="size-3.5 shrink-0" />
          )}
          <span>{message.text}</span>
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1">
        <div ref={editorHostRef} className="absolute inset-0" />
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center gap-2 bg-background text-xs text-foreground-muted">
            <Loader2 className="size-3.5 animate-spin" />
            Loading source…
          </div>
        ) : entry && (entry.status.kind === 'error' || entry.status.kind === 'orphaned') ? (
          <div className="text-destructive absolute inset-0 flex items-center justify-center p-8 text-center text-sm">
            The generator source could not be opened.
          </div>
        ) : null}
      </div>
    </div>
  );
});

function saveErrorMessage(error: SaveFileError): string {
  switch (error.type) {
    case 'conflict':
      return 'The source changed on disk. Discard your buffer to reload it before editing again.';
    case 'no-etag':
    case 'not-open':
      return 'The source is not ready to save yet.';
    case 'write-failed':
      return error.message;
  }
}
