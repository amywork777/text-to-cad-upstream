import type { TaskStore } from '@core/features/tasks/api/browser/stores/task-store';

/**
 * Project discussion may only borrow a live, non-archived chat's conversation store.
 * Archived chats have already released their scoped stores during teardown.
 */
export function projectDiscussionHostTasks<T extends TaskStore>(tasks: Iterable<T>): T[] {
  return Array.from(tasks)
    .filter(
      (task) =>
        task.state !== 'unregistered' &&
        task.data.type !== 'automation-run' &&
        !('archivedAt' in task.data && task.data.archivedAt)
    )
    .sort((left, right) => left.data.createdAt.localeCompare(right.data.createdAt));
}
