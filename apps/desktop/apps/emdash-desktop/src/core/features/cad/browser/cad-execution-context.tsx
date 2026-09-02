import { Tooltip } from '@emdash/ui/react/primitives';
import { FolderGit2, GitBranch, Laptop, Server } from 'lucide-react';
import { observer } from 'mobx-react-lite';
import { getMachinesStore } from '@core/features/machines/contributions/app-stores';
import {
  getProjectStore,
  projectData,
} from '@core/features/projects/api/browser/stores/project-selectors';
import { useProjectWorkspaceOptions } from '@core/features/tasks/api/browser/create-task-modal/use-project-workspace-options';
import { getTaskStore } from '@core/features/tasks/api/browser/task-state/task-selectors';
import { basenameFromAnyPath } from '@core/primitives/path-name/api/path-name';

export type CadExecutionContextViewProps = {
  workspaceLabel: string;
  workspacePath: string | null;
  isWorktree: boolean;
  locationLabel: string;
  isRemote: boolean;
};

export function displayWorkspaceLabel(label: string): string {
  return label.replace(/^emdash\//, '');
}

export function CadExecutionContextView({
  workspaceLabel,
  workspacePath,
  isWorktree,
  locationLabel,
  isRemote,
}: CadExecutionContextViewProps) {
  const visibleWorkspaceLabel = displayWorkspaceLabel(workspaceLabel);
  const WorkspaceIcon = isWorktree ? GitBranch : FolderGit2;
  const LocationIcon = isRemote ? Server : Laptop;
  const workspaceKind = isWorktree ? 'Isolated worktree' : 'Project folder';

  return (
    <div
      className="flex max-w-36 min-w-0 items-center gap-1 text-micro text-foreground-muted"
      aria-label={`${workspaceKind}, ${visibleWorkspaceLabel}, runs on ${locationLabel}`}
    >
      <Tooltip.Root>
        <Tooltip.Trigger
          render={
            <span className="flex min-w-0 items-center gap-1" tabIndex={0}>
              <WorkspaceIcon className="size-3 shrink-0" />
              <span className="truncate">{visibleWorkspaceLabel}</span>
            </span>
          }
        />
        <Tooltip.Content>
          {workspaceKind}
          {workspacePath ? ` · ${workspacePath}` : ''}. This chat uses this workspace.
        </Tooltip.Content>
      </Tooltip.Root>
      <span aria-hidden="true">·</span>
      <Tooltip.Root>
        <Tooltip.Trigger
          render={
            <span className="flex min-w-0 items-center gap-1" tabIndex={0}>
              <LocationIcon className="size-3 shrink-0" />
              <span className="truncate">{locationLabel}</span>
            </span>
          }
        />
        <Tooltip.Content>Runs on {locationLabel}</Tooltip.Content>
      </Tooltip.Root>
    </div>
  );
}

export const CadExecutionContext = observer(function CadExecutionContext({
  projectId,
  taskId,
}: {
  projectId: string;
  taskId: string;
}) {
  const project = projectData(getProjectStore(projectId));
  const task = getTaskStore(projectId, taskId);
  const workspaceOptions = useProjectWorkspaceOptions(projectId).data;
  const workspace = workspaceOptions.find((option) => option.workspaceId === task?.workspaceId);
  const workspacePath = workspace?.path ?? task?.workspacePath ?? null;
  const isWorktree = workspace?.kind === 'worktree';
  const workspaceLabel =
    workspace?.branchName ||
    (workspacePath ? basenameFromAnyPath(workspacePath) : '') ||
    (isWorktree ? 'Worktree' : 'Project folder');
  const machine =
    project?.type === 'ssh'
      ? getMachinesStore().connections.find((candidate) => candidate.id === project.connectionId)
      : null;

  return (
    <CadExecutionContextView
      workspaceLabel={workspaceLabel}
      workspacePath={workspacePath}
      isWorktree={isWorktree}
      locationLabel={project?.type === 'ssh' ? (machine?.name ?? 'Remote machine') : 'This Mac'}
      isRemote={project?.type === 'ssh'}
    />
  );
});
