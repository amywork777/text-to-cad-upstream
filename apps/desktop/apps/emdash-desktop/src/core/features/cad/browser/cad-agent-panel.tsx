import type { AgentProviderId } from '@emdash/plugins/agents/types';
import { Badge, Button, Textarea, Tooltip, toast } from '@emdash/ui/react/primitives';
import {
  CheckCircle2,
  Info,
  Loader2,
  PanelLeftClose,
  RotateCcw,
  Send,
  Square,
  X,
} from 'lucide-react';
import { observer } from 'mobx-react-lite';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getBrowserClient } from '@core/features/browser/api/browser/client';
import {
  buildCadAgentContext,
  cadConversationsForModel,
  cadModelContextKey,
  selectCadConversation,
} from '@core/features/cad/api/browser/cad-agent';
import { cadAnalysisRootPath } from '@core/features/cad/api/browser/cad-analysis';
import { shouldDismissCadConversationNotice } from '@core/features/cad/api/browser/cad-conversation-notice';
import {
  readLastCadConversationProvider,
  rememberCadConversationProvider,
} from '@core/features/cad/api/browser/cad-conversation-provider';
import {
  cadConversationTitleFromPrompt,
  isCadConversationPlaceholder,
  nextCadConversationPlaceholder,
} from '@core/features/cad/api/browser/cad-conversation-title';
import {
  preserveLastGoodModel,
  restoreLastGoodModel,
  shouldAutoRestoreCadBackup,
  shouldMarkCadRunInterrupted,
} from '@core/features/cad/api/browser/cad-last-good';
import {
  archiveCadModelConversation,
  beginCadValidation,
  cadEditAvailability,
  ensureCadModel,
  finishCadRun,
  finishCadValidation,
  reconcileCadModelConversations,
  reconcileCadArtifactFromDisk,
  recordCadConversationTurnDuration,
  registerCadModelConversation,
  removeCadModelConversation,
  restoreCadModelConversation,
  restoreCadRun,
  startCadRun,
  type CadModelIdentity,
} from '@core/features/cad/api/cad-model-state';
import { CAD_VALIDATION_WIRE_TIMEOUT_MS } from '@core/features/cad/api/cad-validation';
import {
  cadModelCatalogMemento,
  type CadModelConversationType,
  type CadModelRecord,
} from '@core/features/cad/contributions/mementos';
import {
  acquireIntegratedAgentSession,
  type IntegratedAgentAttachment,
  type IntegratedAgentSession,
} from '@core/features/conversations/api/browser/integrated-agent-session';
import { useEffectiveProvider } from '@core/features/conversations/api/browser/use-effective-provider';
import {
  engineeringWorkspaceAgentContext,
  loadEngineeringWorkspace,
  loadManufacturingProfile,
  loadProjectBrief,
  manufacturingProfileAgentContext,
  projectBriefAgentContext,
} from '@core/features/projects/api/browser/project-context';
import {
  getProjectSshConnectionId,
  getProjectStore,
  projectData,
} from '@core/features/projects/api/browser/stores/project-selectors';
import { getTaskStore } from '@core/features/tasks/api/browser/task-state/task-selectors';
import type { TaskTabContext } from '@core/features/workbench/api/browser/tabs/task-tab-context';
import {
  useConversations,
  useTaskComposition,
} from '@core/features/workbench/api/browser/task-composition-context';
import {
  relativeToWorkspace,
  resolveWorkspacePath,
} from '@core/features/workspaces/api/browser/workspace-path';
import { useMemento } from '@core/primitives/mementos/react/use-memento';
import type { CadTabResource } from '../api/browser/cad-tab-resource';
import { CadConversationSwitcher, type CadConversationOption } from './cad-conversation-switcher';
import { CadDesignHistory } from './cad-design-history';
import { cadOutputPath } from './cad-design-history-model';
import { CadExecutionContext } from './cad-execution-context';
import {
  cadDefaultSourcePath,
  cadModelSourcePath,
  isCadModelSourcePath,
} from './cad-model-files-model';
import { CadSessionModelSelector } from './cad-session-model-selector';
import { useCadRuntimeStatus } from './use-cad-runtime-status';

const DESIGN_SUGGESTIONS = [
  'Make this part lighter while preserving its mounting interfaces.',
  'Add dimensions and features for a manufacturable bolted connection.',
  'Check this part for manufacturability and fix the problems you find.',
] as const;

const DISCUSSION_SUGGESTIONS: Record<CadModelConversationType, readonly string[]> = {
  design: DESIGN_SUGGESTIONS,
  analysis: [
    'Review the current model and propose an analysis plan.',
    'Check whether the existing loads and constraints are complete.',
    'Summarize the analysis artifacts and identify missing evidence.',
  ],
  manufacturing: [
    'Review this model against the selected manufacturing process.',
    'Identify difficult features, tolerances, and likely setup risks.',
    'Draft questions to resolve with a supplier before release.',
  ],
  review: [
    'Review the current revision against the project brief.',
    'List unresolved engineering risks without changing the model.',
    'Summarize what changed and what should be checked next.',
  ],
  custom: [
    'Explain the current model and its associated engineering context.',
    'Compare design options without changing the geometry.',
    'Summarize the open decisions for this model.',
  ],
};

export const CadAgentPanel = observer(function CadAgentPanel({
  resource,
  task,
  onHide,
}: {
  resource: CadTabResource;
  task: TaskTabContext;
  onHide: () => void;
}) {
  const conversations = useConversations();
  const taskView = useTaskComposition();
  const connectionId = getProjectSshConnectionId(task.projectId);
  const [initialProvider] = useState(() =>
    readLastCadConversationProvider(window.localStorage, connectionId)
  );
  const { providerId, setProviderOverride, installedProviderIds, createDisabled } =
    useEffectiveProvider(connectionId, initialProvider);
  const [draft, setDraft] = useState('');
  const [creating, setCreating] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [contextNotice, setContextNotice] = useState<{
    conversationId: string;
    text: string;
  } | null>(null);
  const [session, setSession] = useState<IntegratedAgentSession | null>(null);
  const [captureAttachment, setCaptureAttachment] = useState<IntegratedAgentAttachment | null>(
    null
  );
  const [captureBusy, setCaptureBusy] = useState(false);
  const { status: cadRuntimeStatus, repair: repairCadRuntime } = useCadRuntimeStatus();
  const [runSession, setRunSession] = useState<IntegratedAgentSession | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const handledCaptureRequest = useRef(0);
  const captureBusyRef = useRef(false);
  const pendingComposerFocusId = useRef<string | null>(null);
  const wasWorking = useRef(false);
  const locallyStartedRunId = useRef<string | null>(null);
  const observedWorkingRunId = useRef<string | null>(null);
  const validatingRunIds = useRef(new Set<string>());
  const submittedMessageCounts = useRef(new Map<string, number>());
  const defaultConversationAttempted = useRef<string | null>(null);
  const reconciledArtifactKeys = useRef(new Set<string>());
  const [catalog, setCatalog] = useMemento(cadModelCatalogMemento);
  const relativePath = relativeToWorkspace(resource.workspacePath, resource.path);
  const contextKey = cadModelContextKey(relativePath);
  const modelRecord = catalog.models[contextKey];
  const modelPath = modelRecord?.modelPath ?? cadOutputPath(relativePath);
  const sourcePath =
    modelRecord?.sourcePath ?? (isCadSource(relativePath) ? relativePath : undefined);
  const validationTargetPath = sourcePath ?? modelPath;

  const identity: CadModelIdentity = useMemo(
    () => ({
      contextKey,
      modelPath,
      ...(sourcePath ? { sourcePath } : {}),
    }),
    [contextKey, modelPath, sourcePath]
  );
  const conversationData = Array.from(conversations.conversations.values(), (item) => item.data);
  const allModelConversations = cadConversationsForModel(conversationData, contextKey);
  const modelConversations = allModelConversations.filter(
    (conversation) => !modelRecord?.conversations[conversation.id]?.archivedAt
  );
  const selectedConversation = selectCadConversation(
    modelConversations,
    contextKey,
    conversations.activeAcpSessionIds,
    modelRecord?.activeConversationId
  );
  const selectedConversationId = selectedConversation?.id ?? null;
  const selectedConversationStore = selectedConversationId
    ? conversations.conversations.get(selectedConversationId)
    : undefined;
  const selectedConversationType = selectedConversationStore?.data.type;
  const selectedConversationSeen = selectedConversationStore?.seen;
  const modelRunInProgress =
    modelRecord?.run.status === 'generating' || modelRecord?.run.status === 'validating';
  const runConversationId = modelRunInProgress ? (modelRecord.run.conversationId ?? null) : null;
  const runConversation = runConversationId
    ? conversations.conversations.get(runConversationId)?.data
    : null;
  const runAgentStatus = runConversation?.agentStatus ?? null;
  const selectedThread = selectedConversationId
    ? modelRecord?.conversations[selectedConversationId]
    : undefined;
  const canEditGeometry = selectedConversationId !== null;
  const conversationOptions: CadConversationOption[] = modelConversations.map((conversation) => ({
    id: conversation.id,
    title: conversation.title,
    isActive: conversation.id === selectedConversationId,
  }));
  const activeConversationOption =
    conversationOptions.find((conversation) => conversation.isActive) ?? null;
  const deleteConversationDisabledReason =
    modelConversations.length <= 1 ? 'Keep at least one chat for this CAD context.' : null;
  const archiveConversationDisabledReason =
    modelConversations.length <= 1
      ? 'Keep at least one active chat for this CAD context.'
      : session?.isWorking
        ? 'Stop this chat before archiving it.'
        : modelRunInProgress && runConversationId === selectedConversationId
          ? 'Finish or stop this CAD revision before archiving its chat.'
          : null;

  useEffect(() => {
    if (!selectedConversationId || !selectedConversationType) return;
    const hasWorkbenchChat = taskView.paneLayout.groups.some(({ pane }) =>
      pane.resolvedTabs.some((tab) => tab.kind === 'acp-chat' || tab.kind === 'conversation')
    );
    if (hasWorkbenchChat) return;

    const cadGroup = taskView.paneLayout.groups.find(({ pane }) =>
      pane.resolvedTabs.some((tab) => tab.kind === 'cad')
    );
    if (!cadGroup) return;

    // Legacy Hardcore models created their first Design conversation from the
    // embedded CAD panel after pane hydration. Promote that same conversation
    // into the normal Codex-style chat pane as soon as it exists, preserving
    // its transcript while removing the duplicate CAD-local thread chrome.
    taskView.paneLayout.setActiveGroup(cadGroup.paneId);
    taskView.paneLayout.open(
      selectedConversationType === 'acp' ? 'acp-chat' : 'conversation',
      { conversationId: selectedConversationId },
      { preview: false, target: 'left' }
    );
  }, [selectedConversationId, selectedConversationType, taskView]);

  const recordTurnDuration = useCallback(
    (turnId: string, durationMs: number) => {
      if (!selectedConversationId) return;
      setCatalog((current) =>
        recordCadConversationTurnDuration(
          current,
          contextKey,
          selectedConversationId,
          turnId,
          durationMs,
          new Date().toISOString()
        )
      );
    },
    [contextKey, selectedConversationId, setCatalog]
  );

  useEffect(() => {
    setCatalog((current) => ensureCadModel(current, identity, new Date().toISOString()));
  }, [identity, setCatalog]);

  useEffect(() => {
    if (!modelRecord || modelRunInProgress) return;
    const reconciliationKey = `${contextKey}:${modelRecord.run.id ?? 'none'}:${modelRecord.run.status}:${modelRecord.revisionId ?? 'none'}`;
    if (reconciledArtifactKeys.current.has(reconciliationKey)) return;
    reconciledArtifactKeys.current.add(reconciliationKey);
    const validationPath = resolveWorkspacePath(resource.workspacePath, validationTargetPath);
    void (async () => {
      const result = await (
        await getBrowserClient()
      ).validateCadModel(
        {
          workspacePath: resource.workspacePath,
          filePath: validationPath,
        },
        { timeoutMs: CAD_VALIDATION_WIRE_TIMEOUT_MS }
      );
      if (!result.success) {
        // Provisioning may have completed after an initial validation attempt.
        // Let a later render retry instead of pinning the stale session state.
        reconciledArtifactKeys.current.delete(reconciliationKey);
        return;
      }
      const checkedAt = new Date().toISOString();
      setCatalog((current) =>
        reconcileCadArtifactFromDisk(current, contextKey, result.artifact, result.facts, checkedAt)
      );
      resource.refreshViewer();
    })().catch(() => {
      reconciledArtifactKeys.current.delete(reconciliationKey);
    });
  }, [contextKey, modelRecord, modelRunInProgress, resource, setCatalog, validationTargetPath]);

  const modelConversationIds = allModelConversations
    .map((conversation) => conversation.id)
    .join(':');
  useEffect(() => {
    const conversationIds = modelConversationIds ? modelConversationIds.split(':') : [];
    if (conversationIds.length === 0) return;
    setCatalog((current) =>
      reconcileCadModelConversations(current, contextKey, conversationIds, new Date().toISOString())
    );
  }, [contextKey, modelConversationIds, setCatalog]);

  useEffect(() => {
    if (
      !modelRecord ||
      modelConversations.length > 0 ||
      creating ||
      !providerId ||
      createDisabled ||
      defaultConversationAttempted.current === contextKey
    ) {
      return;
    }
    defaultConversationAttempted.current = contextKey;
    const conversationId = crypto.randomUUID();
    setCreating(true);
    void conversations
      .createConversation({
        id: conversationId,
        projectId: task.projectId,
        taskId: task.taskId,
        provider: providerId,
        title: 'Design',
        type: 'acp',
        contextKey,
      })
      .then(() => {
        const createdAt = new Date().toISOString();
        setCatalog((current) =>
          registerCadModelConversation(current, contextKey, {
            id: conversationId,
            type: 'design',
            createdAt,
          })
        );
      })
      .catch(() => {
        setCreateError('Could not create the Design conversation. Check the agent connection.');
      })
      .finally(() => setCreating(false));
  }, [
    contextKey,
    conversations,
    createDisabled,
    creating,
    modelConversations.length,
    modelRecord,
    providerId,
    setCatalog,
    task.projectId,
    task.taskId,
  ]);

  useEffect(() => {
    setSession(null);
    setCaptureAttachment(null);
    captureBusyRef.current = false;
    setCaptureBusy(false);
    if (!selectedConversationId) return;
    const acquired = acquireIntegratedAgentSession({
      conversationId: selectedConversationId,
      projectId: task.projectId,
      taskId: task.taskId,
    });
    setSession(acquired);
    return () => acquired.dispose();
  }, [selectedConversationId, task.projectId, task.taskId]);

  useEffect(() => {
    let cancelled = false;
    const consumeReference = async () => {
      const command = await resource.consumeViewerReferenceCommand();
      if (cancelled || !command) return;
      setDraft((current) => {
        if (current.includes(command.reference)) return current;
        const separator = current.length > 0 && !current.endsWith(' ') ? ' ' : '';
        return `${current}${separator}${command.reference} `;
      });
      window.requestAnimationFrame(() => composerRef.current?.focus());
    };
    void consumeReference();
    const timer = window.setInterval(() => void consumeReference(), 350);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [resource]);

  useEffect(() => {
    if (
      resource.captureRequest <= handledCaptureRequest.current ||
      !session ||
      captureBusyRef.current
    ) {
      return;
    }
    handledCaptureRequest.current = resource.captureRequest;
    let cancelled = false;
    setCreateError(null);
    captureBusyRef.current = true;
    setCaptureBusy(true);
    void (async () => {
      const result = await (
        await getBrowserClient()
      ).captureScreenshotForChat({ browserId: resource.browserId });
      if (!result.success) throw new Error(result.error ?? 'Could not capture the model.');
      const attachment = await session.uploadPng(
        pngBytesFromDataUrl(result.dataUrl),
        `cad-annotation-${Date.now()}.png`,
        result.dataUrl
      );
      if (!attachment) throw new Error('Could not attach the model screenshot.');
      if (cancelled) return;
      setCaptureAttachment(attachment);
      window.requestAnimationFrame(() => composerRef.current?.focus());
      toast('Screenshot copied and added to chat');
    })()
      .catch((error: unknown) => {
        if (!cancelled) {
          setCreateError(error instanceof Error ? error.message : 'Could not capture the model.');
        }
      })
      .finally(() => {
        captureBusyRef.current = false;
        if (!cancelled) setCaptureBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [resource, resource.captureRequest, session]);

  useEffect(() => {
    if (selectedConversationStore && !selectedConversationStore.seen) {
      selectedConversationStore.markSeen();
    }
  }, [selectedConversationSeen, selectedConversationStore]);

  useEffect(() => {
    const shouldFocusCreatedConversation =
      selectedConversation !== null &&
      isCadConversationPlaceholder(selectedConversation.title) &&
      (session?.messageCount ?? 0) === 0;
    if (
      !selectedConversationId ||
      (pendingComposerFocusId.current !== selectedConversationId && !shouldFocusCreatedConversation)
    ) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      composerRef.current?.focus();
      pendingComposerFocusId.current = null;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectedConversation, selectedConversationId, session?.messageCount]);

  useEffect(() => {
    if (
      shouldDismissCadConversationNotice({
        noticeConversationId: contextNotice?.conversationId ?? null,
        selectedConversationId,
        sessionConversationId: session?.conversationId ?? null,
        messageCount: session?.messageCount ?? 0,
      })
    ) {
      setContextNotice(null);
    }
  }, [contextNotice, selectedConversationId, session, session?.messageCount]);

  useEffect(() => {
    setRunSession(null);
    if (!runConversationId || runConversationId === selectedConversationId) return;
    const acquired = acquireIntegratedAgentSession({
      conversationId: runConversationId,
      projectId: task.projectId,
      taskId: task.taskId,
    });
    setRunSession(acquired);
    return () => acquired.dispose();
  }, [runConversationId, selectedConversationId, task.projectId, task.taskId]);

  const lifecycleSession =
    runConversationId && runConversationId === selectedConversationId ? session : runSession;

  const isWorking = lifecycleSession?.isWorking ?? false;
  useEffect(() => {
    if (isWorking) observedWorkingRunId.current = modelRecord?.run.id ?? null;
    if (wasWorking.current && !isWorking) resource.refreshViewer();
    wasWorking.current = isWorking;
  }, [isWorking, modelRecord?.run.id, resource]);

  useEffect(() => {
    const run = modelRecord?.run;
    if (
      !run?.id ||
      run.origin === 'source' ||
      !['generating', 'validating'].includes(run.status) ||
      creating ||
      lifecycleSession?.isLoading
    )
      return;
    const runId = run.id;
    const completedLocally = observedWorkingRunId.current === run.id;
    const restoredRun = locallyStartedRunId.current !== run.id;
    const messageCountBeforeSubmit = submittedMessageCounts.current.get(run.id);
    const completedNewTurn =
      messageCountBeforeSubmit !== undefined &&
      lifecycleSession !== null &&
      lifecycleSession.messageCount > messageCountBeforeSubmit;
    if (
      shouldMarkCadRunInterrupted({
        runStatus: run.status,
        runId,
        observedWorkingRunId: observedWorkingRunId.current,
        isWorking,
        lifecycleStatus: lifecycleSession?.status,
        agentStatus: runAgentStatus,
      })
    ) {
      setCatalog((current) =>
        finishCadRun(current, contextKey, 'interrupted', new Date().toISOString())
      );
      return;
    }
    if (
      run.status === 'generating' &&
      (lifecycleSession?.status === 'error' || runAgentStatus === 'error')
    ) {
      setCatalog((current) =>
        finishCadRun(current, contextKey, 'failed', new Date().toISOString())
      );
      return;
    }
    if (
      run.status === 'validating' ||
      ((lifecycleSession?.status === 'completed' || runAgentStatus === 'completed') &&
        (completedLocally || completedNewTurn || restoredRun))
    ) {
      if (validatingRunIds.current.has(run.id)) return;
      validatingRunIds.current.add(run.id);
      if (run.status === 'generating') {
        setCatalog((current) => beginCadValidation(current, contextKey));
      }
      const recoverySnapshot = modelRecord.lastGood;
      void (async () => {
        let result;
        try {
          const validationPath = resolveWorkspacePath(resource.workspacePath, validationTargetPath);
          result = await (
            await getBrowserClient()
          ).validateCadModel(
            {
              workspacePath: resource.workspacePath,
              filePath: validationPath,
            },
            { timeoutMs: CAD_VALIDATION_WIRE_TIMEOUT_MS }
          );
          if (
            !result.success &&
            shouldAutoRestoreCadBackup(runId, locallyStartedRunId.current) &&
            recoverySnapshot &&
            (recoverySnapshot.backupPath || recoverySnapshot.sourceBackupPath)
          ) {
            await restoreLastGoodModel({
              workspacePath: resource.workspacePath,
              snapshot: recoverySnapshot,
              sshConnectionId: connectionId,
            });
          }
        } catch (error) {
          result = {
            success: false as const,
            error: error instanceof Error ? error.message : 'CAD validation failed.',
          };
        }
        const checkedAt = new Date().toISOString();
        setCatalog((current) => finishCadValidation(current, contextKey, result, checkedAt));
        if (!result.success)
          setCreateError(`${result.error} The previous validated files were kept when available.`);
        resource.refreshViewer();
        validatingRunIds.current.delete(runId);
        submittedMessageCounts.current.delete(runId);
      })();
      return;
    }
    if (
      !lifecycleSession?.isWorking &&
      restoredRun &&
      runAgentStatus === 'idle' &&
      lifecycleSession?.status === 'idle'
    ) {
      setCatalog((current) =>
        finishCadRun(current, contextKey, 'interrupted', new Date().toISOString())
      );
    }
  }, [
    connectionId,
    contextKey,
    creating,
    isWorking,
    modelRecord?.lastGood,
    modelRecord?.run,
    resource,
    lifecycleSession,
    runAgentStatus,
    setCatalog,
    validationTargetPath,
  ]);

  const submit = async () => {
    const text = draft.trim() || (captureAttachment ? 'Review this annotated CAD screenshot.' : '');
    if (!text || creating || !session || !selectedConversationId || !selectedThread) return;
    setCreateError(null);
    setContextNotice(null);

    if (!session.canSubmit) {
      setCreateError('This conversation is still working. Wait for it to finish before sending.');
      return;
    }

    const availability = cadEditAvailability(catalog, contextKey, selectedConversationId);
    if (!availability.allowed) {
      setCreateError(
        availability.reason === 'run-in-progress'
          ? 'Another CAD revision is already generating or validating.'
          : 'The focused CAD artifact is no longer available.'
      );
      return;
    }

    const runId = crypto.randomUUID();
    const startedAt = new Date().toISOString();
    let projectContext: {
      brief: string | null;
      manufacturing: string | null;
      engineering: string | null;
      referencePath: string | null;
    } | null = null;
    const project = projectData(getProjectStore(task.projectId));
    const projectContextPromise = project
      ? Promise.all([
          loadProjectBrief({
            projectPath: project.path,
            projectName: project.name,
            ...(project.type === 'ssh' ? { sshConnectionId: project.connectionId } : {}),
          }).catch(() => null),
          loadManufacturingProfile({
            projectPath: project.path,
            projectName: project.name,
            ...(project.type === 'ssh' ? { sshConnectionId: project.connectionId } : {}),
          }).catch(() => null),
          loadEngineeringWorkspace({
            projectPath: project.path,
            projectName: project.name,
            ...(project.type === 'ssh' ? { sshConnectionId: project.connectionId } : {}),
          }).catch(() => null),
        ]).then(([brief, manufacturing, engineering]) => {
          if (!brief?.exists && !manufacturing?.exists && !engineering?.exists) return null;
          return {
            brief: brief?.exists ? projectBriefAgentContext(brief.content) : null,
            manufacturing: manufacturing?.exists
              ? manufacturingProfileAgentContext(manufacturing.profile)
              : null,
            engineering: engineering?.exists
              ? engineeringWorkspaceAgentContext(engineering.workspace, project.path, task.taskId)
              : null,
            referencePath:
              brief?.exists || engineering?.exists
                ? resolveWorkspacePath(project.path, 'context')
                : null,
          };
        })
      : Promise.resolve(null);
    try {
      projectContext = await projectContextPromise;
    } catch {
      setCreateError('Could not load the shared model and project context.');
      return;
    }

    const hiddenContext = buildCadAgentContext({
      relativePath,
      modelFiles: modelRecord?.artifacts.map((artifact) => artifact.path) ?? [modelPath],
      revisionId: modelRecord?.revisionId,
      modelHash: modelRecord?.modelHash,
      sourceHash: modelRecord?.sourceHash,
      conversationType: selectedThread.type,
      canEditGeometry,
      projectBrief: projectContext?.brief,
      projectReferencePath: projectContext?.referencePath,
      manufacturingProfile: projectContext?.manufacturing,
      engineeringWorkspace: projectContext?.engineering,
      analysisRootPath:
        selectedThread.type === 'analysis' ? cadAnalysisRootPath(relativePath) : null,
    });
    const catalogSourcePath = cadModelSourcePath(
      (modelRecord?.artifacts ?? []).map((artifact) => ({ path: artifact.path, type: 'file' })),
      relativePath
    );
    let preserved;
    try {
      preserved = await preserveLastGoodModel({
        workspacePath: resource.workspacePath,
        modelPath,
        sourcePath: sourcePath ?? catalogSourcePath ?? recoverySourcePath(relativePath),
        contextKey,
        runId,
        sshConnectionId: connectionId,
        recordedAt: startedAt,
      });
    } catch {
      setCreateError('Could not preserve the current model. Generation was not started.');
      return;
    }
    const lastGood = preserved;
    locallyStartedRunId.current = runId;
    observedWorkingRunId.current = null;
    submittedMessageCounts.current.set(runId, session.messageCount);
    const nextCatalog = startCadRun(catalog, identity, {
      id: runId,
      conversationId: selectedConversationId,
      prompt: text,
      startedAt,
      ...(lastGood ? { lastGood } : {}),
    });
    if (nextCatalog === catalog) {
      submittedMessageCounts.current.delete(runId);
      setCreateError(
        'Another CAD revision started before this request. Try again when it finishes.'
      );
      return;
    }
    setCatalog(nextCatalog);
    autoTitleConversationFromPrompt();
    session.submitPrompt(text, hiddenContext, captureAttachment ? [captureAttachment] : []);
    setDraft('');
    setCaptureAttachment(null);

    function autoTitleConversationFromPrompt() {
      if (!selectedConversation || !isCadConversationPlaceholder(selectedConversation.title)) {
        return;
      }
      const generatedTitle = cadConversationTitleFromPrompt(text);
      void conversations
        .renameConversation(selectedConversation.id, generatedTitle)
        .catch(() => {});
      void getTaskStore(task.projectId, task.taskId)?.rename(generatedTitle);
    }
  };

  const createModelConversation = async () => {
    if (!providerId || createDisabled) {
      throw new Error('Connect Codex or Claude before creating a conversation.');
    }
    const conversationId = crypto.randomUUID();
    const createdAt = new Date().toISOString();
    const title = nextCadConversationPlaceholder(
      allModelConversations.map((conversation) => conversation.title)
    );
    setCreating(true);
    setCreateError(null);
    try {
      await conversations.createConversation({
        id: conversationId,
        projectId: task.projectId,
        taskId: task.taskId,
        provider: providerId,
        title,
        type: 'acp',
        contextKey,
      });
      rememberCadConversationProvider(window.localStorage, providerId, connectionId);
      pendingComposerFocusId.current = conversationId;
      setCatalog((current) =>
        registerCadModelConversation(current, contextKey, {
          id: conversationId,
          type: 'custom',
          createdAt,
        })
      );
      setContextNotice({
        conversationId,
        text: 'This chat keeps its own messages and shares the latest model context.',
      });
    } catch (error) {
      setCreateError('Could not create a new chat. Check the agent connection.');
      throw error;
    } finally {
      setCreating(false);
    }
  };

  const switchConversationProvider = async (nextProviderId: AgentProviderId) => {
    if (!selectedConversationId || !session) {
      throw new Error('This chat is still connecting.');
    }
    if (nextProviderId === session.providerId) return;
    if (session.isWorking || modelRunInProgress) {
      throw new Error('Stop the current work before changing agents.');
    }

    const conversationId = crypto.randomUUID();
    const createdAt = new Date().toISOString();
    const previousProvider = session.providerId === 'codex' ? 'Codex' : 'Claude';
    const nextProvider = nextProviderId === 'codex' ? 'Codex' : 'Claude';
    const title = nextCadConversationPlaceholder(
      allModelConversations.map((conversation) => conversation.title)
    );
    setCreating(true);
    setCreateError(null);
    try {
      await conversations.createConversation({
        id: conversationId,
        projectId: task.projectId,
        taskId: task.taskId,
        provider: nextProviderId,
        title,
        type: 'acp',
        contextKey,
      });
      rememberCadConversationProvider(window.localStorage, nextProviderId, connectionId);
      setProviderOverride(nextProviderId);
      pendingComposerFocusId.current = conversationId;
      setCatalog((current) =>
        registerCadModelConversation(current, contextKey, {
          id: conversationId,
          type: selectedThread?.type ?? 'custom',
          createdAt,
        })
      );
      setContextNotice({
        conversationId,
        text: `Now using ${nextProvider}. Your ${previousProvider} messages are preserved in the previous chat.`,
      });
    } catch (error) {
      setCreateError(`Could not start a ${nextProvider} chat. Check that the agent is connected.`);
      throw error;
    } finally {
      setCreating(false);
    }
  };

  const renameModelConversation = async (title: string) => {
    if (!selectedConversationId) throw new Error('No conversation is selected.');
    await conversations.renameConversation(selectedConversationId, title);
  };

  const archiveModelConversation = async () => {
    if (!selectedConversationId) throw new Error('No conversation is selected.');
    if (archiveConversationDisabledReason) throw new Error(archiveConversationDisabledReason);
    const archivedAt = new Date().toISOString();
    const result = archiveCadModelConversation(
      catalog,
      contextKey,
      selectedConversationId,
      archivedAt
    );
    if (result.status === 'last-active-conversation') {
      throw new Error('Every model keeps at least one active chat.');
    }
    if (result.status === 'run-in-progress') {
      throw new Error('Finish or stop the current CAD revision before archiving this chat.');
    }
    if (result.status === 'missing') {
      throw new Error('This chat is no longer attached to the model.');
    }
    if (result.status !== 'archived') return;

    setCatalog(result.catalog);
    toast('Chat archived. Model files were not changed.', {
      action: {
        label: 'Undo',
        onClick: () =>
          setCatalog(
            (current) =>
              restoreCadModelConversation(
                current,
                contextKey,
                selectedConversationId,
                new Date().toISOString()
              ).catalog
          ),
      },
    });
  };

  const deleteModelConversation = async () => {
    if (!selectedConversationId) throw new Error('No conversation is selected.');
    const result = removeCadModelConversation(
      catalog,
      contextKey,
      selectedConversationId,
      new Date().toISOString()
    );
    if (result.status === 'last-conversation') {
      throw new Error('Every model must keep at least one chat.');
    }
    if (result.status === 'run-in-progress') {
      throw new Error('Finish or stop the current CAD revision before deleting this chat.');
    }
    if (result.status === 'missing')
      throw new Error('This chat is no longer attached to the model.');

    await conversations.deleteConversation(selectedConversationId);
    setCatalog(result.catalog);
  };

  const status = agentStatus(session, creating, canEditGeometry, modelRecord?.run.status);
  const validationSummary = passedValidationSummary(modelRecord?.run.validation);
  const lastGood = modelRecord?.lastGood;
  const recoveryMessage = recoveryText(
    modelRecord?.run.status,
    modelRecord?.run.validation?.status,
    Boolean(lastGood?.backupPath),
    Boolean(lastGood?.sourceBackupPath)
  );
  const restore = async () => {
    if (!lastGood || restoring) return;
    setRestoring(true);
    setCreateError(null);
    try {
      await restoreLastGoodModel({
        workspacePath: resource.workspacePath,
        snapshot: lastGood,
        sshConnectionId: connectionId,
      });
      setCatalog((current) => restoreCadRun(current, contextKey, new Date().toISOString()));
      resource.refreshViewer();
    } catch {
      setCreateError('Could not restore the previous model files.');
    } finally {
      setRestoring(false);
    }
  };
  const submitDisabled =
    (!draft.trim() && !captureAttachment) ||
    creating ||
    captureBusy ||
    !session ||
    !session.canSubmit ||
    modelRunInProgress;
  const showHeaderStatus =
    status.label !== 'Connecting' &&
    (status.loading || status.tone === 'warning' || status.tone === 'error');

  return (
    <aside className="flex h-full w-[clamp(300px,32vw,380px)] max-w-[44%] min-w-[300px] flex-col border-r bg-background">
      <div className="border-b px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-1">
          <div className="min-w-0 flex-1">
            <CadConversationSwitcher
              activeConversation={activeConversationOption}
              disabled={creating || !providerId || createDisabled}
              archiveDisabledReason={archiveConversationDisabledReason}
              deleteDisabledReason={deleteConversationDisabledReason}
              onCreate={createModelConversation}
              onRename={renameModelConversation}
              onArchive={archiveModelConversation}
              onDelete={deleteModelConversation}
            />
          </div>
          {showHeaderStatus ? (
            <Badge tone={status.tone} variant="soft">
              {status.loading ? <Loader2 className="mr-1 size-3 animate-spin" /> : null}
              {status.label}
            </Badge>
          ) : null}
          {validationSummary && !showHeaderStatus ? (
            <Tooltip.Root>
              <Tooltip.Trigger
                render={
                  <span
                    className="text-success inline-flex size-6 items-center justify-center"
                    role="status"
                    aria-label={`Model valid. ${validationSummary}`}
                    tabIndex={0}
                  />
                }
              >
                <CheckCircle2 className="size-3.5" />
              </Tooltip.Trigger>
              <Tooltip.Content>{validationSummary}</Tooltip.Content>
            </Tooltip.Root>
          ) : null}
          <Tooltip.Root>
            <Tooltip.Trigger
              render={
                <Button
                  type="button"
                  size="xs"
                  icon
                  variant="ghost"
                  aria-label="Hide chat"
                  onClick={onHide}
                >
                  <PanelLeftClose />
                </Button>
              }
            />
            <Tooltip.Content>Hide chat</Tooltip.Content>
          </Tooltip.Root>
        </div>
      </div>

      {contextNotice?.conversationId === selectedConversationId ? (
        <div className="bg-accent/40 flex items-start gap-2 border-b px-4 py-2 text-tiny leading-4 text-foreground-muted">
          <Info className="mt-0.5 size-3.5 shrink-0" />
          <span>{contextNotice.text}</span>
        </div>
      ) : null}

      {recoveryMessage ? (
        <div className="flex items-center gap-3 border-b bg-background-secondary px-4 py-2">
          <span className="min-w-0 flex-1 text-tiny leading-4 text-foreground-muted">
            {recoveryMessage}
          </span>
          {lastGood?.backupPath || lastGood?.sourceBackupPath ? (
            <Button
              type="button"
              variant="secondary"
              size="xs"
              disabled={restoring}
              onClick={() => void restore()}
            >
              {restoring ? (
                <Loader2 className="mr-1 size-3 animate-spin" />
              ) : (
                <RotateCcw className="mr-1 size-3" />
              )}
              Restore
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {session ? (
          session.isLoading && session.messageCount === 0 ? (
            <div className="flex h-full items-center justify-center gap-2 text-xs text-foreground-muted">
              <Loader2 className="size-3.5 animate-spin" />
              Loading this chat…
            </div>
          ) : session.messageCount === 0 ? (
            <CadConversationEmptyState
              type={selectedThread?.type ?? 'custom'}
              canEditGeometry={canEditGeometry}
              onSuggestion={setDraft}
            />
          ) : (
            <CadDesignHistory
              state={session.chatState}
              modelPath={modelPath}
              run={modelRecord?.run}
              persistedDurationsMs={selectedThread?.turnDurationsMs}
              onTurnDuration={recordTurnDuration}
            />
          )
        ) : (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-foreground-muted">
            <Loader2 className="size-3.5 animate-spin" />
            Preparing the chat…
          </div>
        )}

        {session?.error || createError ? (
          <div className="border-destructive/30 text-destructive absolute inset-x-3 bottom-3 rounded-md border bg-background p-2.5 text-xs shadow-sm">
            {session?.error ?? createError}
            {session?.error ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="mt-1"
                onClick={session.retry}
              >
                Retry connection
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      <form
        className="border-t bg-background p-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        {captureAttachment ? (
          <div className="mb-2 flex items-center gap-2 rounded-md border bg-background-secondary p-1.5">
            {captureAttachment.previewUrl ? (
              <img
                src={captureAttachment.previewUrl}
                alt="CAD screenshot ready to send"
                className="h-12 w-16 rounded border object-cover"
              />
            ) : null}
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium">Model screenshot</div>
              <div className="text-tiny text-foreground-muted">Ready to send with this message</div>
            </div>
            <Button
              type="button"
              size="xs"
              icon
              variant="ghost"
              aria-label="Remove model screenshot"
              onClick={() => setCaptureAttachment(null)}
            >
              <X />
            </Button>
          </div>
        ) : captureBusy ? (
          <div className="mb-2 flex items-center gap-2 text-tiny text-foreground-muted">
            <Loader2 className="size-3 animate-spin" />
            Capturing model…
          </div>
        ) : null}
        <label htmlFor={`cad-prompt-${resource.browserId}`} className="sr-only">
          Describe an engineering change or ask about this project
        </label>
        <Textarea
          ref={composerRef}
          id={`cad-prompt-${resource.browserId}`}
          value={draft}
          rows={3}
          placeholder="Ask about the project or describe a change…"
          className="min-h-20 resize-none text-sm"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="mt-2 flex min-w-0 items-center gap-2">
          {session ? (
            <CadSessionModelSelector
              providerId={session.providerId}
              modelId={session.modelId}
              modelLabel={session.modelLabel}
              options={session.modelOptions}
              providerOptions={(['claude', 'codex'] as const).filter(
                (candidate) =>
                  candidate === session.providerId || installedProviderIds.includes(candidate)
              )}
              cadRuntimeStatus={cadRuntimeStatus}
              disabled={creating || session.isLoading || session.isWorking}
              onProviderChange={switchConversationProvider}
              onChange={(modelId) => session.setModel(modelId)}
              onRepairCadRuntime={repairCadRuntime}
            />
          ) : null}
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            {session?.canCancel ? (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  session.stop();
                  if (selectedConversationId === runConversationId) {
                    setCatalog((current) =>
                      finishCadRun(current, contextKey, 'cancelled', new Date().toISOString())
                    );
                  }
                }}
              >
                <Square className="mr-1 size-3 fill-current" />
                Stop
              </Button>
            ) : null}
            <Button type="submit" size="sm" className="shrink-0" disabled={submitDisabled}>
              {creating ? (
                <Loader2 className="mr-1 size-3 animate-spin" />
              ) : (
                <Send className="mr-1 size-3" />
              )}
              {session?.isWorking ? 'Working' : 'Send'}
            </Button>
          </div>
        </div>
        <div className="mt-1.5 min-w-0 px-1">
          <CadExecutionContext projectId={task.projectId} taskId={task.taskId} />
        </div>
      </form>
    </aside>
  );
});

function CadConversationEmptyState({
  type,
  canEditGeometry,
  onSuggestion,
}: {
  type: CadModelConversationType;
  canEditGeometry: boolean;
  onSuggestion: (suggestion: string) => void;
}) {
  const suggestions = DISCUSSION_SUGGESTIONS[type];
  return (
    <div className="flex h-full flex-col justify-center gap-5 overflow-auto p-4">
      <div>
        <div className="text-sm font-medium text-foreground">
          {canEditGeometry ? 'What should change?' : 'Ask about this model'}
        </div>
        <p className="mt-1 text-xs leading-5 text-foreground-muted">
          {canEditGeometry
            ? 'This conversation can revise the model. Every message receives the latest files, revision, and project engineering context.'
            : 'This chat receives the latest model and project context. Allow edits when you want it to change geometry.'}
        </p>
      </div>
      <div className="flex flex-col gap-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            className="rounded-lg border bg-background-secondary px-3 py-2.5 text-left text-xs leading-4 text-foreground-muted transition-colors hover:border-foreground/20 hover:bg-background-tertiary hover:text-foreground"
            onClick={() => onSuggestion(suggestion)}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

function agentStatus(
  session: IntegratedAgentSession | null,
  creating: boolean,
  canEditGeometry: boolean,
  durableStatus?: string
): { label: string; tone: 'neutral' | 'success' | 'warning' | 'error'; loading: boolean } {
  if (creating || session?.isLoading)
    return { label: 'Connecting', tone: 'neutral', loading: true };
  if (session?.error) return { label: 'Offline', tone: 'error', loading: false };
  if (session?.isWorking)
    return {
      label: canEditGeometry ? 'Working' : 'Thinking',
      tone: 'warning',
      loading: true,
    };
  if (durableStatus === 'generating')
    return { label: 'Checking files', tone: 'warning', loading: true };
  if (durableStatus === 'validating')
    return { label: 'Validating model', tone: 'warning', loading: true };
  if (durableStatus === 'completed')
    return { label: 'Model valid', tone: 'success', loading: false };
  if (durableStatus === 'interrupted')
    return { label: 'Interrupted', tone: 'warning', loading: false };
  if (durableStatus === 'cancelled') return { label: 'Stopped', tone: 'neutral', loading: false };
  if (durableStatus === 'failed') return { label: 'Failed', tone: 'error', loading: false };
  if (durableStatus === 'restored') return { label: 'Restored', tone: 'success', loading: false };
  return { label: 'Ready', tone: 'neutral', loading: false };
}

function recoveryText(
  status: string | undefined,
  validationStatus: string | undefined,
  preservedModel: boolean,
  preservedSource: boolean
): string | null {
  if (!['failed', 'cancelled', 'interrupted'].includes(status ?? '')) return null;
  const suffix = preservedModel
    ? preservedSource
      ? ' The previous model and generator are preserved.'
      : ' The previous model is preserved.'
    : preservedSource
      ? ' The previous generator is preserved.'
      : '';
  if (status === 'failed' && validationStatus === 'failed')
    return `Geometry validation failed.${suffix}`;
  if (status === 'interrupted') return `The previous generation was interrupted.${suffix}`;
  if (status === 'cancelled') return `Generation stopped.${suffix}`;
  return `The last generation failed.${suffix}`;
}

function isCadSource(path: string): boolean {
  return isCadModelSourcePath(path);
}

function recoverySourcePath(path: string): string | undefined {
  return cadDefaultSourcePath(path) ?? undefined;
}

function pngBytesFromDataUrl(dataUrl: string): Uint8Array {
  const encoded = dataUrl.split(',', 2)[1] ?? '';
  const binary = window.atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function passedValidationSummary(
  validation: CadModelRecord['run']['validation'] | undefined
): string | null {
  if (validation?.status !== 'passed') return null;
  const details = [];
  if (validation.facts?.size) {
    details.push(
      `${validation.facts.size.map((value) => Number(value.toFixed(2))).join(' × ')} mm`
    );
  }
  if (validation.facts?.faceCount !== undefined) {
    details.push(`${validation.facts.faceCount} faces`);
  }
  return details.length > 0 ? `Geometry validated · ${details.join(' · ')}` : 'Geometry validated';
}
