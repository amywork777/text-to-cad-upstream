import { Button } from '@emdash/ui/react/primitives';
import {
  ArrowUpRight,
  BadgeCheck,
  Box,
  FileCode2,
  FileImage,
  FileOutput,
  Files,
  PackageOpen,
  RefreshCw,
} from 'lucide-react';
import { observer } from 'mobx-react-lite';
import { useCallback, useEffect, useState } from 'react';
import { EditorFileTree } from '@core/features/editor/contributions/browser/editor-file-tree';
import { FileIcon } from '@core/features/editor/contributions/browser/file-icon';
import { openFile as openWorkbenchFile } from '@core/features/workbench/api/browser/open-file';
import {
  useTaskComposition,
  useWorkspace,
} from '@core/features/workbench/api/browser/task-composition-context';
import { relativeToWorkspace } from '@core/features/workspaces/api/browser/workspace-path';
import { hostFileRefFromNativePath } from '@core/primitives/desktop-runtime/api';
import type { CadTabResource } from '../api/browser/cad-tab-resource';
import {
  cadModelDirectory,
  type CadModelFile,
  type CadModelFileRole,
  isCadRelatedDirectory,
  selectCadModelFiles,
} from './cad-model-files-model';

const ROLE_LABELS: Record<CadModelFileRole, string> = {
  model: 'Model',
  source: 'Generator',
  drawing: 'Drawing',
  reference: 'Reference',
  analysis: 'Analysis',
  validation: 'Validation',
  export: 'Export',
};

export const CadModelFilesSidebar = observer(function CadModelFilesSidebar({
  resource,
}: {
  resource: CadTabResource;
}) {
  const workspace = useWorkspace();
  const taskView = useTaskComposition();
  const files = taskView.editorView.files;
  const [showAllFiles, setShowAllFiles] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    if (!files) return;
    setIsRefreshing(true);
    try {
      const directory = cadModelDirectory(resource.path) || workspace.path;
      await files.registerDir(directory, true);
      const refreshed = new Set<string>();
      for (let depth = 0; depth < 4; depth += 1) {
        const relatedDirectories = [...files.nodes.values()].filter(
          (node) =>
            node.type === 'directory' &&
            !refreshed.has(node.path) &&
            isCadRelatedDirectory(node.path, resource.path)
        );
        if (relatedDirectories.length === 0) break;
        relatedDirectories.forEach((node) => refreshed.add(node.path));
        await Promise.all(relatedDirectories.map((node) => files.registerDir(node.path, true)));
      }
    } finally {
      setIsRefreshing(false);
    }
  }, [files, resource.path, workspace.path]);

  useEffect(() => {
    setShowAllFiles(false);
    void refresh();
  }, [refresh]);

  const candidates = files ? [...files.nodes.values()] : [];
  if (!candidates.some((candidate) => candidate.path === resource.path)) {
    candidates.push({
      id: resource.path,
      path: resource.path,
      name: resource.path.split(/[\\/]/).pop() ?? resource.path,
      parentId: null,
      parentPath: null,
      depth: 0,
      type: 'file',
      childrenLoaded: false,
      isHidden: false,
    });
  }
  const modelFiles = selectCadModelFiles(candidates, resource.path);

  if (showAllFiles) {
    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
        <div className="flex h-12 shrink-0 items-center justify-between border-b px-5">
          <div>
            <div className="text-sm font-medium text-foreground">All project files</div>
            <div className="text-tiny text-foreground-muted">Browse the complete workspace</div>
          </div>
          <Button type="button" variant="ghost" size="xs" onClick={() => setShowAllFiles(false)}>
            Back to model files
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <EditorFileTree />
        </div>
      </div>
    );
  }

  const openFile = (file: CadModelFile) => {
    openWorkbenchFile(hostFileRefFromNativePath(file.path, workspace.sshConnectionId), {
      context: { projectId: taskView.projectId, taskId: taskView.taskId },
      preview: false,
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background-secondary/40">
      <div className="flex min-h-16 shrink-0 items-center justify-between gap-4 border-b bg-background px-6 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="bg-accent text-accent-foreground flex size-8 shrink-0 items-center justify-center rounded-lg">
            <Box className="size-4" />
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-foreground">Model files</div>
            <div className="truncate text-tiny text-foreground-muted">
              {resource.path.split(/[\\/]/).pop() ?? resource.path}
            </div>
          </div>
        </div>
        <button
          type="button"
          aria-label="Refresh model files"
          title="Refresh model files"
          className="flex size-7 items-center justify-center rounded-md text-foreground-muted hover:bg-background-secondary hover:text-foreground"
          onClick={() => void refresh()}
        >
          <RefreshCw className={`size-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto w-full max-w-3xl">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <h2 className="text-base font-medium text-foreground">Outputs for this model</h2>
              <p className="mt-1 max-w-xl text-xs leading-5 text-foreground-muted">
                Generated models, drawings, analyses, and exports stay together here.
              </p>
            </div>
            <span className="shrink-0 text-xs text-foreground-muted">
              {modelFiles.length} {modelFiles.length === 1 ? 'file' : 'files'}
            </span>
          </div>

          <div className="overflow-hidden rounded-xl border bg-background shadow-xs">
            {modelFiles.map((file, index) => (
              <button
                key={file.path}
                type="button"
                className={`group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-background-secondary ${index > 0 ? 'border-t' : ''}`}
                onClick={() => openFile(file)}
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background-secondary text-foreground-muted">
                  <RoleIcon role={file.role} name={file.name} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">
                    {file.name}
                  </span>
                  <span className="mt-0.5 block truncate text-tiny text-foreground-muted">
                    {ROLE_LABELS[file.role]} · {relativeToWorkspace(workspace.path, file.path)}
                  </span>
                </span>
                <ArrowUpRight className="size-3.5 shrink-0 text-foreground-tertiary-muted transition-colors group-hover:text-foreground" />
              </button>
            ))}
          </div>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-3"
            onClick={() => setShowAllFiles(true)}
          >
            <Files className="mr-2 size-3.5" />
            Browse all project files
          </Button>
        </div>
      </div>
    </div>
  );
});

function RoleIcon({ role, name }: { role: CadModelFileRole; name: string }) {
  if (role === 'model') return <Box className="size-3.5" />;
  if (role === 'source') return <FileCode2 className="size-3.5" />;
  if (role === 'drawing') return <FileOutput className="size-3.5" />;
  if (role === 'reference') return <FileImage className="size-3.5" />;
  if (role === 'analysis') return <FileOutput className="size-3.5" />;
  if (role === 'validation') return <BadgeCheck className="size-3.5" />;
  if (role === 'export') return <PackageOpen className="size-3.5" />;
  return <FileIcon filename={name} size={14} />;
}
