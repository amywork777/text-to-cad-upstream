import { toast } from '@emdash/ui/react/primitives';
import { reaction } from 'mobx';
import { useEffect } from 'react';
import { getBrowserClient } from '@core/features/browser/api/browser/client';
import type { ConversationManagerStore } from '@core/features/conversations/api/browser/conversation-manager';
import { openFile } from '@core/features/workbench/api/browser/open-file';
import { resolveWorkspacePath } from '@core/features/workspaces/api/browser/workspace-path';
import { hostFileRefFromNativePath } from '@core/primitives/desktop-runtime/api';

/** Let the writer finish (cadgen renames its output into place) before reading it. */
export const CAD_ARTIFACT_REVEAL_SETTLE_MS = 750;
/** Scan from a little before the turn started: clocks and watchers are not exact. */
const TURN_START_SLACK_MS = 2_000;

export type CadArtifactRevealPlan = { open: string | null; announce: string[] };

/**
 * Decide what to do with model artifacts that appeared during a turn. With no
 * CAD tab open, the first model (a STEP when there is one) opens in the
 * artifact pane. Every other new artifact is announced with an Open action so
 * a viewer the user is reviewing is never hijacked mid-turn.
 */
export function planCadArtifactReveal(input: {
  newPaths: readonly string[];
  hasOpenCadTab: boolean;
}): CadArtifactRevealPlan {
  const paths = [...new Set(input.newPaths)];
  if (paths.length === 0) return { open: null, announce: [] };
  if (input.hasOpenCadTab) return { open: null, announce: paths };
  const preferred = paths.find((path) => /\.(?:step|stp)$/i.test(path)) ?? paths[0]!;
  return { open: preferred, announce: paths.filter((path) => path !== preferred) };
}

type RevealTask = {
  projectId: string;
  taskId: string;
  workspace?: { path: string; sshConnectionId?: string } | null;
  paneLayout: {
    groups: ReadonlyArray<{ pane: { resolvedTabs: ReadonlyArray<{ kind: string }> } }>;
  };
};

/**
 * Reveal models written by any agent in the task. Every conversation is
 * watched; when its agent stops working, the workspace is scanned for model
 * artifacts newer than that turn. Subagents write into the same workspace, so
 * their models surface the same way. Artifacts the catalog already tracks
 * (the focused model a run just rebuilt) are left to the run lifecycle.
 */
export function useCadArtifactReveal(
  task: RevealTask,
  conversations: ConversationManagerStore,
  isTrackedArtifact: (relativePath: string) => boolean
): void {
  const workspacePath = task.workspace?.path;
  const connectionId = task.workspace?.sshConnectionId;
  const { projectId, taskId, paneLayout } = task;

  useEffect(() => {
    // The CAD Viewer serves local directories only; remote workspaces have no viewer to reveal into.
    if (!workspacePath || connectionId) return;
    const turnStartedAt = new Map<string, number>();
    const revealed = new Set<string>();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const open = (relativePath: string) =>
      openFile(hostFileRefFromNativePath(resolveWorkspacePath(workspacePath, relativePath)), {
        context: { projectId, taskId },
        target: 'artifact',
      });

    const reveal = async (sinceMs: number) => {
      const result = await (await getBrowserClient()).listCadArtifacts({ workspacePath, sinceMs });
      if (disposed || !result.success) return;
      const fresh = result.artifacts
        .map(({ path }) => path)
        .filter((path) => !revealed.has(path) && !isTrackedArtifact(path));
      for (const path of fresh) revealed.add(path);
      if (fresh.length === 0) return;
      const hasOpenCadTab = paneLayout.groups.some(({ pane }) =>
        pane.resolvedTabs.some((tab) => tab.kind === 'cad')
      );
      const plan = planCadArtifactReveal({ newPaths: fresh, hasOpenCadTab });
      if (plan.open) open(plan.open);
      for (const path of plan.announce) {
        toast.info(`New CAD artifact: ${path.split('/').pop() ?? path}`, {
          description: path,
          duration: 10_000,
          action: { label: 'Open', onClick: () => open(path) },
        });
      }
    };

    const dispose = reaction(
      () =>
        [...conversations.conversations.entries()].map(
          ([id, store]) => [id, store.status] as const
        ),
      (statuses, previous) => {
        const before = new Map(previous ?? []);
        for (const [id, status] of statuses) {
          const was = before.get(id);
          if (status === 'working' && was !== 'working') turnStartedAt.set(id, Date.now());
          if (was === 'working' && status !== 'working') {
            const since = (turnStartedAt.get(id) ?? Date.now()) - TURN_START_SLACK_MS;
            turnStartedAt.delete(id);
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => {
              timer = null;
              void reveal(since);
            }, CAD_ARTIFACT_REVEAL_SETTLE_MS);
          }
        }
      }
    );

    return () => {
      disposed = true;
      dispose();
      if (timer) clearTimeout(timer);
    };
  }, [
    connectionId,
    conversations,
    isTrackedArtifact,
    paneLayout,
    projectId,
    taskId,
    workspacePath,
  ]);
}
