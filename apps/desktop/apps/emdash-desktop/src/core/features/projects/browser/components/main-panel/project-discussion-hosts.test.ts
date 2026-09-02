import { describe, expect, it } from 'vitest';
import type { TaskStore } from '@core/features/tasks/api/browser/stores/task-store';
import { projectDiscussionHostTasks } from './project-discussion-hosts';

function task({
  id,
  state = 'provisioned',
  type = 'task',
  archivedAt,
  createdAt,
}: {
  id: string;
  state?: TaskStore['state'];
  type?: 'task' | 'automation-run';
  archivedAt?: string;
  createdAt: string;
}): TaskStore {
  return {
    state,
    data: { id, type, archivedAt, createdAt },
  } as unknown as TaskStore;
}

describe('projectDiscussionHostTasks', () => {
  it('never returns an archived chat after its scoped conversation store is released', () => {
    const archived = task({
      id: 'archived',
      archivedAt: '2026-08-28T12:00:00.000Z',
      createdAt: '2026-08-28T10:00:00.000Z',
    });
    const active = task({ id: 'active', createdAt: '2026-08-28T11:00:00.000Z' });

    expect(projectDiscussionHostTasks([archived, active])).toEqual([active]);
    expect(projectDiscussionHostTasks([archived])).toEqual([]);
  });

  it('keeps eligible chats in creation order and excludes unfinished and automation tasks', () => {
    const newer = task({ id: 'newer', createdAt: '2026-08-28T12:00:00.000Z' });
    const older = task({ id: 'older', createdAt: '2026-08-28T10:00:00.000Z' });
    const unfinished = task({
      id: 'unfinished',
      state: 'unregistered',
      createdAt: '2026-08-28T09:00:00.000Z',
    });
    const automation = task({
      id: 'automation',
      type: 'automation-run',
      createdAt: '2026-08-28T08:00:00.000Z',
    });

    expect(projectDiscussionHostTasks([newer, automation, unfinished, older])).toEqual([
      older,
      newer,
    ]);
  });
});
