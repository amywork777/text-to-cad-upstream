import { Badge, Button, Textarea } from '@emdash/ui/react/primitives';
import { Loader2, MessageSquareText, Plus, Send, Square } from 'lucide-react';
import { observer } from 'mobx-react-lite';
import { useEffect, useMemo, useState } from 'react';
import { selectContextConversation } from '@core/features/cad/api/browser/cad-agent';
import { ChatTranscript } from '@core/features/conversations/api/browser/chat/chat-transcript';
import {
  acquireIntegratedAgentSession,
  type IntegratedAgentSession,
} from '@core/features/conversations/api/browser/integrated-agent-session';
import { useEffectiveProvider } from '@core/features/conversations/api/browser/use-effective-provider';
import { conversationManagerStoreToken } from '@core/features/conversations/contributions/browser/task-stores';
import {
  engineeringWorkspaceAgentContext,
  loadEngineeringWorkspace,
  loadManufacturingProfile,
  loadProjectBrief,
  manufacturingProfileAgentContext,
  projectBriefAgentContext,
  projectDiscussionAgentContext,
  type ProjectContextLocation,
} from '@core/features/projects/api/browser/project-context';
import { getTaskManagerStore } from '@core/features/tasks/api/browser/task-state/task-selectors';
import { newChatDraftView } from '@core/features/workbench/contributions/views';
import { useNavigate } from '@core/primitives/navigation/browser/navigation-hooks';
import type { Project } from '@core/primitives/projects/api';
import { projectDiscussionHostTasks } from './project-discussion-hosts';

export const ProjectDiscussionPanel = observer(function ProjectDiscussionPanel({
  project,
  draftSeed,
  onDraftSeedConsumed,
}: {
  project: Project;
  draftSeed?: string;
  onDraftSeedConsumed?: () => void;
}) {
  const { navigate } = useNavigate();
  const taskManager = getTaskManagerStore(project.id);
  const contextKey = `engineering-project:${project.id}`;
  const candidateTasks = projectDiscussionHostTasks(taskManager?.tasks.values() ?? []);
  const existingOwner = candidateTasks
    .map((task) => {
      const manager = task.get(conversationManagerStoreToken);
      const conversation = selectContextConversation(
        Array.from(manager.conversations.values(), (item) => item.data),
        contextKey,
        manager.activeAcpSessionIds
      );
      return conversation ? { task, manager, conversation } : null;
    })
    .find((owner) => owner !== null);
  const fallbackTask = candidateTasks[0];
  const hostTask = existingOwner?.task ?? fallbackTask;
  const conversations = existingOwner?.manager ?? hostTask?.get(conversationManagerStoreToken);
  const selectedConversation =
    existingOwner?.conversation ??
    (conversations
      ? selectContextConversation(
          Array.from(conversations.conversations.values(), (item) => item.data),
          contextKey,
          conversations.activeAcpSessionIds
        )
      : null);
  const selectedConversationId = selectedConversation?.id ?? null;
  const hostTaskId = hostTask?.data.id ?? null;
  const [session, setSession] = useState<IntegratedAgentSession | null>(null);
  const [draft, setDraft] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const connectionId = project.type === 'ssh' ? project.connectionId : undefined;
  const { providerId, createDisabled } = useEffectiveProvider(connectionId);
  const location: ProjectContextLocation = useMemo(
    () => ({
      projectPath: project.path,
      projectName: project.name,
      ...(connectionId ? { sshConnectionId: connectionId } : {}),
    }),
    [connectionId, project.name, project.path]
  );

  useEffect(() => {
    if (!draftSeed) return;
    setDraft(draftSeed);
    onDraftSeedConsumed?.();
  }, [draftSeed, onDraftSeedConsumed]);

  useEffect(() => {
    setSession(null);
    if (!selectedConversationId || !hostTaskId) return;
    const acquired = acquireIntegratedAgentSession({
      conversationId: selectedConversationId,
      projectId: project.id,
      taskId: hostTaskId,
    });
    setSession(acquired);
    return () => acquired.dispose();
  }, [hostTaskId, project.id, selectedConversationId]);

  const submit = async () => {
    const text = draft.trim();
    if (!text || creating || !hostTask || !conversations || !taskManager) return;
    setError(null);
    setCreating(true);
    try {
      if (hostTask.state !== 'provisioned') {
        await taskManager.provisionTask(hostTask.data.id);
        const readyTask = taskManager.tasks.get(hostTask.data.id);
        if (readyTask?.state !== 'provisioned') {
          throw new Error(
            readyTask?.errorMessage ?? 'The project discussion workspace is not ready.'
          );
        }
      }
      const [brief, manufacturing, engineering] = await Promise.all([
        loadProjectBrief(location).catch(() => null),
        loadManufacturingProfile(location).catch(() => null),
        loadEngineeringWorkspace(location).catch(() => null),
      ]);
      const hiddenContext = projectDiscussionAgentContext({
        projectPath: project.path,
        projectName: project.name,
        brief: brief?.exists ? projectBriefAgentContext(brief.content) : null,
        manufacturing: manufacturing?.exists
          ? manufacturingProfileAgentContext(manufacturing.profile)
          : null,
        engineering: engineering?.exists
          ? engineeringWorkspaceAgentContext(engineering.workspace, project.path)
          : null,
      });

      if (session) {
        if (!session.canSubmit) throw new Error('The project discussion is not ready to send.');
        session.submitPrompt(text, hiddenContext);
      } else {
        if (selectedConversation || !providerId || createDisabled) {
          throw new Error('Connect Claude or Codex before starting the project discussion.');
        }
        await conversations.createConversation({
          id: crypto.randomUUID(),
          projectId: project.id,
          taskId: hostTask.data.id,
          provider: providerId,
          title: `Engineering · ${project.name}`,
          type: 'acp',
          contextKey,
          initialQueue: [{ text, hiddenContext }],
        });
      }
      setDraft('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setCreating(false);
    }
  };

  if (!hostTask) {
    return (
      <div className="flex h-full flex-col items-center justify-center rounded-lg border bg-background p-8 text-center">
        <span className="flex size-11 items-center justify-center rounded-xl border bg-background-secondary">
          <MessageSquareText className="size-5 text-foreground-muted" />
        </span>
        <h3 className="mt-4 text-sm font-medium text-foreground">Start a chat in this project</h3>
        <p className="mt-1 max-w-md text-xs leading-5 text-foreground-muted">
          Every chat can work with the entire project folder, including its CAD models, drawings,
          assemblies, and supporting documents.
        </p>
        <Button className="mt-4" onClick={() => navigate(newChatDraftView(project.id))}>
          <Plus className="size-3.5" />
          Start first chat
        </Button>
      </div>
    );
  }

  const status = discussionStatus(session, creating);
  const submitDisabled =
    !draft.trim() ||
    creating ||
    (session ? !session.canSubmit : Boolean(selectedConversation) || !providerId || createDisabled);

  return (
    <section
      aria-label="Project assistant"
      className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border bg-background"
    >
      <div className="flex items-center gap-3 border-b px-5 py-4">
        <span className="flex size-8 items-center justify-center rounded-lg bg-background-secondary text-foreground-muted">
          <MessageSquareText className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-micro font-medium tracking-wide text-foreground-muted uppercase">
            Project chat
          </div>
          <div className="truncate text-sm font-medium text-foreground">{project.name}</div>
        </div>
        <Badge tone={status.tone} variant="soft">
          {status.loading ? <Loader2 className="mr-1 size-3 animate-spin" /> : null}
          {status.label}
        </Badge>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {session ? (
          session.isLoading && session.messageCount === 0 ? (
            <div className="flex h-full items-center justify-center gap-2 text-xs text-foreground-muted">
              <Loader2 className="size-3.5 animate-spin" />
              Loading project discussion…
            </div>
          ) : (
            <ChatTranscript
              context={session.chatContext}
              state={session.chatState}
              stickToBottom
              pinUserMessages
              style={{ position: 'absolute', inset: 0 }}
            />
          )
        ) : (
          <DiscussionEmptyState onSuggestion={setDraft} />
        )}
        {session?.error || error ? (
          <div className="absolute inset-x-4 bottom-4 rounded-md border border-border-destructive/30 bg-background p-3 text-xs text-foreground-destructive shadow-sm">
            {session?.error ?? error}
          </div>
        ) : null}
      </div>

      <form
        className="border-t p-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label htmlFor={`project-prompt-${project.id}`} className="sr-only">
          Ask about this project
        </label>
        <Textarea
          id={`project-prompt-${project.id}`}
          value={draft}
          rows={3}
          className="min-h-24 resize-none text-sm"
          placeholder="Ask about requirements, materials, calculations, suppliers, or testing…"
          onChange={(event) => setDraft(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="mt-2 flex items-center gap-2">
          {session?.canCancel ? (
            <Button type="button" variant="secondary" size="sm" onClick={session.stop}>
              <Square className="size-3 fill-current" />
              Stop
            </Button>
          ) : (
            <span className="text-micro text-foreground-tertiary-muted">
              Scope: entire project · ⌘ ↵ to send
            </span>
          )}
          <Button type="submit" size="sm" className="ml-auto" disabled={submitDisabled}>
            {creating ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Send className="size-3.5" />
            )}
            {session?.isWorking ? 'Queue question' : 'Ask project'}
          </Button>
        </div>
      </form>
    </section>
  );
});

function DiscussionEmptyState({ onSuggestion }: { onSuggestion: (value: string) => void }) {
  const suggestions = [
    'Compare our candidate materials and identify what evidence is still missing.',
    'Review the project requirements for contradictions or unverified assumptions.',
    'What should we test before releasing the next CAD revision?',
  ];
  return (
    <div className="flex h-full flex-col items-center justify-center p-8 text-center">
      <MessageSquareText className="size-6 text-foreground-muted" />
      <div className="mt-3 text-sm font-medium text-foreground">Discuss the whole project</div>
      <p className="mt-1 max-w-md text-xs leading-5 text-foreground-muted">
        Ask questions that span models. Hardcore supplies shared engineering evidence and keeps this
        discussion separate from geometry revisions.
      </p>
      <div className="mt-5 flex w-full max-w-lg flex-col gap-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            className="rounded-lg border bg-background-secondary px-3 py-2 text-left text-xs text-foreground-muted hover:text-foreground"
            onClick={() => onSuggestion(suggestion)}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

function discussionStatus(
  session: IntegratedAgentSession | null,
  creating: boolean
): { label: string; tone: 'neutral' | 'success' | 'warning' | 'error'; loading: boolean } {
  if (creating || session?.isLoading)
    return { label: 'Connecting', tone: 'neutral', loading: true };
  if (session?.error) return { label: 'Offline', tone: 'error', loading: false };
  if (session?.isWorking) return { label: 'Thinking', tone: 'warning', loading: true };
  if (session?.status === 'completed') return { label: 'Ready', tone: 'success', loading: false };
  return { label: 'Ready', tone: 'neutral', loading: false };
}
