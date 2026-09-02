import { Badge, Button, Field, Input, Select, Textarea, toast } from '@emdash/ui/react/primitives';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  ArrowUpRight,
  Beaker,
  ChevronDown,
  FilePlus2,
  FlaskConical,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react';
import { observer } from 'mobx-react-lite';
import { useMemo, useRef, useState } from 'react';
import { cadModelContextKey } from '@core/features/cad/api/browser/cad-agent';
import {
  addCadAnalysisFile,
  cadAnalysisFolderPath,
  cadAnalysisStatusSchema,
  cadAnalysisTypeSchema,
  createCadAnalysis,
  loadCadAnalyses,
  saveCadAnalysis,
  type CadAnalysisManifest,
  type CadAnalysisType,
} from '@core/features/cad/api/browser/cad-analysis';
import { cadModelCatalogMemento } from '@core/features/cad/contributions/mementos';
import {
  EMPTY_ENGINEERING_WORKSPACE,
  loadEngineeringWorkspace,
  saveEngineeringWorkspace,
  type EngineeringWorkspace,
  type ProjectContextLocation,
} from '@core/features/projects/api/browser/project-context';
import {
  getProjectStore,
  projectData,
} from '@core/features/projects/api/browser/stores/project-selectors';
import type { TaskTabContext } from '@core/features/workbench/api/browser/tabs/task-tab-context';
import {
  relativeToWorkspace,
  resolveWorkspacePath,
} from '@core/features/workspaces/api/browser/workspace-path';
import { getHostClient } from '@core/primitives/desktop-host/browser/host-client';
import { useMemento } from '@core/primitives/mementos/react/use-memento';
import type { CadTabResource } from '../api/browser/cad-tab-resource';

const TYPE_LABELS: Record<CadAnalysisType, string> = {
  'static-structural': 'Static structural',
  thermal: 'Thermal',
  modal: 'Modal',
  flow: 'Flow',
  other: 'Other',
};

const EMPTY_DRAFT = {
  name: '',
  type: 'static-structural' as CadAnalysisType,
  solver: '',
  objective: '',
  loads: '',
  constraints: '',
};

export const CadAnalysisPanel = observer(function CadAnalysisPanel({
  resource,
  task,
}: {
  resource: CadTabResource;
  task: TaskTabContext;
}) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [attachmentTarget, setAttachmentTarget] = useState<CadAnalysisManifest | null>(null);
  const [componentKey, setComponentKey] = useState('');
  const [componentMaterialId, setComponentMaterialId] = useState('');
  const [catalog] = useMemento(cadModelCatalogMemento);
  const project = projectData(getProjectStore(task.projectId));
  const modelPath = relativeToWorkspace(resource.workspacePath, resource.path);
  const contextKey = cadModelContextKey(modelPath);
  const modelRecord = catalog.models[contextKey];
  const analysisOptions = useMemo(
    () => ({
      workspacePath: resource.workspacePath,
      modelPath,
      ...(project?.type === 'ssh' ? { sshConnectionId: project.connectionId } : {}),
    }),
    [modelPath, project, resource.workspacePath]
  );
  const projectLocation: ProjectContextLocation | null = project
    ? {
        projectPath: project.path,
        projectName: project.name,
        ...(project.type === 'ssh' ? { sshConnectionId: project.connectionId } : {}),
      }
    : null;
  const engineeringKey = ['engineeringWorkspace', task.projectId] as const;
  const analysisKey = ['cadAnalyses', resource.workspacePath, modelPath] as const;
  const engineering = useQuery({
    queryKey: engineeringKey,
    enabled: projectLocation !== null,
    queryFn: async () => await loadEngineeringWorkspace(projectLocation!),
  });
  const analyses = useQuery({
    queryKey: analysisKey,
    queryFn: async () => await loadCadAnalyses(analysisOptions),
  });
  const workspace = engineering.data?.workspace ?? EMPTY_ENGINEERING_WORKSPACE;
  const assignment = workspace.materialAssignments.find(
    (candidate) => candidate.modelId === task.taskId && !candidate.componentKey
  );
  const componentAssignments = workspace.materialAssignments.filter(
    (candidate) => candidate.modelId === task.taskId && candidate.componentKey
  );

  const saveMaterial = useMutation({
    mutationFn: async (materialId: string | null) => {
      if (!projectLocation) throw new Error('Project context is unavailable.');
      const now = new Date().toISOString();
      const existing = workspace.materialAssignments.find(
        (candidate) => candidate.modelId === task.taskId && !candidate.componentKey
      );
      const materialAssignments = materialId
        ? [
            ...workspace.materialAssignments.filter(
              (candidate) => candidate.modelId !== task.taskId || candidate.componentKey
            ),
            {
              modelId: task.taskId,
              materialId,
              assignedAt: existing?.assignedAt ?? now,
              updatedAt: now,
            },
          ]
        : workspace.materialAssignments.filter(
            (candidate) => candidate.modelId !== task.taskId || candidate.componentKey
          );
      const next: EngineeringWorkspace = { ...workspace, materialAssignments };
      await saveEngineeringWorkspace(projectLocation, next);
      return next;
    },
    onSuccess: (next) => {
      queryClient.setQueryData(engineeringKey, { exists: true, workspace: next });
      toast('Model material updated');
    },
    onError: showError('Could not update model material'),
  });

  const saveComponentMaterial = useMutation({
    mutationFn: async (input: { componentKey: string; materialId: string | null }) => {
      if (!projectLocation) throw new Error('Project context is unavailable.');
      const normalizedKey = input.componentKey.trim();
      const now = new Date().toISOString();
      const existing = workspace.materialAssignments.find(
        (candidate) => candidate.modelId === task.taskId && candidate.componentKey === normalizedKey
      );
      const retained = workspace.materialAssignments.filter(
        (candidate) => candidate.modelId !== task.taskId || candidate.componentKey !== normalizedKey
      );
      const materialAssignments = input.materialId
        ? [
            ...retained,
            {
              modelId: task.taskId,
              componentKey: normalizedKey,
              componentName: normalizedKey,
              materialId: input.materialId,
              assignedAt: existing?.assignedAt ?? now,
              updatedAt: now,
            },
          ]
        : retained;
      const next: EngineeringWorkspace = { ...workspace, materialAssignments };
      await saveEngineeringWorkspace(projectLocation, next);
      return next;
    },
    onSuccess: (next) => {
      queryClient.setQueryData(engineeringKey, { exists: true, workspace: next });
      setComponentKey('');
      setComponentMaterialId('');
      toast('Component material updated');
    },
    onError: showError('Could not update component material'),
  });

  const createAnalysis = useMutation({
    mutationFn: async () =>
      await createCadAnalysis({
        ...analysisOptions,
        contextKey,
        revisionId: modelRecord?.revisionId ?? null,
        validatedAt: modelRecord?.run.validation?.checkedAt ?? null,
        materialId: assignment?.materialId ?? null,
        ...draft,
      }),
    onSuccess: (created) => {
      queryClient.setQueryData<CadAnalysisManifest[]>(analysisKey, (current = []) => [
        created,
        ...current,
      ]);
      setDraft(EMPTY_DRAFT);
      toast('Analysis setup created');
    },
    onError: showError('Could not create analysis'),
  });

  const updateAnalysis = useMutation({
    mutationFn: async (manifest: CadAnalysisManifest) =>
      await saveCadAnalysis(analysisOptions, manifest),
    onSuccess: (saved) => {
      queryClient.setQueryData<CadAnalysisManifest[]>(analysisKey, (current = []) =>
        current.map((candidate) => (candidate.id === saved.id ? saved : candidate))
      );
      toast('Analysis updated');
    },
    onError: showError('Could not update analysis'),
  });

  const attachFile = useMutation({
    mutationFn: async ({ manifest, file }: { manifest: CadAnalysisManifest; file: File }) =>
      await addCadAnalysisFile(analysisOptions, manifest, file),
    onSuccess: (saved) => {
      queryClient.setQueryData<CadAnalysisManifest[]>(analysisKey, (current = []) =>
        current.map((candidate) => (candidate.id === saved.id ? saved : candidate))
      );
      toast('Analysis file attached');
    },
    onError: showError('Could not attach analysis file'),
  });

  const openFolder = async (manifest: CadAnalysisManifest) => {
    const path = resolveWorkspacePath(
      resource.workspacePath,
      cadAnalysisFolderPath(modelPath, manifest.id)
    );
    const opened = await (await getHostClient()).openPath({ path });
    if (!opened.success)
      toast.error('Could not open analysis folder', { description: opened.error });
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background-secondary/40">
      <div className="flex min-h-16 shrink-0 items-center justify-between gap-4 border-b bg-background px-6 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="bg-accent text-accent-foreground flex size-8 shrink-0 items-center justify-center rounded-lg">
            <Activity className="size-4" />
          </span>
          <div>
            <div className="text-sm font-medium text-foreground">Model analysis</div>
            <div className="text-tiny text-foreground-muted">
              Set up and retain evidence for this model revision
            </div>
          </div>
        </div>
        <Badge
          variant="soft"
          tone={modelRecord?.run.validation?.status === 'passed' ? 'success' : 'warning'}
        >
          {modelRecord?.run.validation?.status === 'passed'
            ? 'Validated revision'
            : 'Unvalidated revision'}
        </Badge>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
          <section className="rounded-xl border bg-background p-5 shadow-xs">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Beaker className="size-4 text-foreground-muted" /> Model material
                </div>
                <p className="mt-1 text-xs text-foreground-muted">
                  Assigned from Project home. Analyses snapshot this choice when they are created.
                </p>
              </div>
              <Select.Root
                value={assignment?.materialId ?? 'none'}
                disabled={engineering.isPending || saveMaterial.isPending}
                onValueChange={(value) => saveMaterial.mutate(value === 'none' ? null : value)}
              >
                <Select.Trigger appearance="input" className="w-64">
                  <Select.Value>
                    {workspace.materials.find((material) => material.id === assignment?.materialId)
                      ?.name ?? 'No material assigned'}
                  </Select.Value>
                </Select.Trigger>
                <Select.Content width="trigger">
                  <Select.Item value="none">No material assigned</Select.Item>
                  {workspace.materials
                    .filter((material) => material.status !== 'rejected')
                    .map((material) => (
                      <Select.Item key={material.id} value={material.id}>
                        {material.name}
                        {material.grade ? ` · ${material.grade}` : ''} ({material.status})
                      </Select.Item>
                    ))}
                </Select.Content>
              </Select.Root>
            </div>
            <div className="mt-5 border-t pt-4">
              <div className="text-xs font-medium text-foreground">Component / BOM materials</div>
              <p className="mt-1 text-tiny text-foreground-muted">
                Assign different materials to named parts, viewer occurrence refs, or BOM item IDs.
              </p>
              {componentAssignments.length > 0 ? (
                <div className="mt-3 flex flex-col gap-2">
                  {componentAssignments.map((component) => (
                    <div
                      key={component.componentKey}
                      className="flex items-center gap-3 rounded-lg border bg-background-secondary px-3 py-2"
                    >
                      <code className="min-w-0 flex-1 truncate text-xs">
                        {component.componentName ?? component.componentKey}
                      </code>
                      <span className="text-xs text-foreground-muted">
                        {workspace.materials.find(
                          (material) => material.id === component.materialId
                        )?.name ?? 'Missing material'}
                      </span>
                      <Button
                        type="button"
                        icon
                        size="xs"
                        variant="ghost"
                        aria-label={`Remove material from ${component.componentKey}`}
                        disabled={saveComponentMaterial.isPending}
                        onClick={() =>
                          saveComponentMaterial.mutate({
                            componentKey: component.componentKey!,
                            materialId: null,
                          })
                        }
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="mt-3 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-2">
                <Input
                  value={componentKey}
                  placeholder="Part name, #occurrence, or BOM ID"
                  onChange={(event) => setComponentKey(event.currentTarget.value)}
                />
                <Select.Root
                  value={componentMaterialId}
                  onValueChange={(value) => setComponentMaterialId(value ?? '')}
                >
                  <Select.Trigger appearance="input" className="w-full">
                    <Select.Value>
                      {workspace.materials.find((material) => material.id === componentMaterialId)
                        ?.name ?? 'Choose material'}
                    </Select.Value>
                  </Select.Trigger>
                  <Select.Content width="trigger">
                    {workspace.materials
                      .filter((material) => material.status !== 'rejected')
                      .map((material) => (
                        <Select.Item key={material.id} value={material.id}>
                          {material.name}
                          {material.grade ? ` · ${material.grade}` : ''}
                        </Select.Item>
                      ))}
                  </Select.Content>
                </Select.Root>
                <Button
                  type="button"
                  size="sm"
                  disabled={
                    !componentKey.trim() || !componentMaterialId || saveComponentMaterial.isPending
                  }
                  onClick={() =>
                    saveComponentMaterial.mutate({
                      componentKey,
                      materialId: componentMaterialId,
                    })
                  }
                >
                  <Plus className="size-3.5" /> Assign
                </Button>
              </div>
            </div>
          </section>

          <section className="rounded-xl border bg-background p-5 shadow-xs">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <FlaskConical className="size-4 text-foreground-muted" /> New analysis
            </div>
            <p className="mt-1 text-xs text-foreground-muted">
              This creates a standard <code>analysis.json</code> manifest. It does not claim a
              solver has run.
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <Field.Root>
                <Field.Label>Name</Field.Label>
                <Input
                  value={draft.name}
                  placeholder="Bracket load case"
                  onChange={(event) => setDraft({ ...draft, name: event.currentTarget.value })}
                />
              </Field.Root>
              <Field.Root>
                <Field.Label>Analysis type</Field.Label>
                <Select.Root
                  value={draft.type}
                  onValueChange={(value) =>
                    setDraft({ ...draft, type: cadAnalysisTypeSchema.parse(value) })
                  }
                >
                  <Select.Trigger appearance="input" className="w-full">
                    <Select.Value>{TYPE_LABELS[draft.type]}</Select.Value>
                  </Select.Trigger>
                  <Select.Content width="trigger">
                    {cadAnalysisTypeSchema.options.map((type) => (
                      <Select.Item key={type} value={type}>
                        {TYPE_LABELS[type]}
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </Field.Root>
              <Field.Root className="col-span-2">
                <Field.Label>Solver</Field.Label>
                <Input
                  value={draft.solver}
                  placeholder="e.g. CalculiX, ANSYS, Abaqus, OpenFOAM"
                  onChange={(event) => setDraft({ ...draft, solver: event.currentTarget.value })}
                />
              </Field.Root>
              <Field.Root className="col-span-2">
                <Field.Label>Objective</Field.Label>
                <Input
                  value={draft.objective}
                  placeholder="What question should this analysis answer?"
                  onChange={(event) => setDraft({ ...draft, objective: event.currentTarget.value })}
                />
              </Field.Root>
              <Field.Root>
                <Field.Label>Loads</Field.Label>
                <Textarea
                  rows={3}
                  value={draft.loads}
                  placeholder="Forces, pressures, temperatures, duty cycle…"
                  onChange={(event) => setDraft({ ...draft, loads: event.currentTarget.value })}
                />
              </Field.Root>
              <Field.Root>
                <Field.Label>Constraints</Field.Label>
                <Textarea
                  rows={3}
                  value={draft.constraints}
                  placeholder="Fixed faces, contacts, thermal boundaries…"
                  onChange={(event) =>
                    setDraft({ ...draft, constraints: event.currentTarget.value })
                  }
                />
              </Field.Root>
            </div>
            <div className="mt-4 flex justify-end">
              <Button
                type="button"
                size="sm"
                disabled={!draft.name.trim() || createAnalysis.isPending}
                onClick={() => createAnalysis.mutate()}
              >
                {createAnalysis.isPending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Plus className="size-3.5" />
                )}
                Create setup
              </Button>
            </div>
          </section>

          <section>
            <div className="mb-3 flex items-end justify-between gap-4">
              <div>
                <h2 className="text-sm font-medium text-foreground">Analysis history</h2>
                <p className="mt-1 text-xs text-foreground-muted">
                  Inputs and results remain ordinary files inside each analysis folder.
                </p>
              </div>
              <span className="text-xs text-foreground-muted">
                {analyses.data?.length ?? 0} runs
              </span>
            </div>
            {analyses.isPending ? (
              <div className="flex items-center justify-center gap-2 rounded-xl border bg-background p-8 text-sm text-foreground-muted">
                <Loader2 className="size-4 animate-spin" /> Loading analyses…
              </div>
            ) : analyses.isError ? (
              <div className="border-destructive/30 bg-destructive/5 text-destructive rounded-xl border p-4 text-xs">
                {analyses.error instanceof Error ? analyses.error.message : 'Analyses unavailable.'}
              </div>
            ) : analyses.data?.length ? (
              <div className="flex flex-col gap-2">
                {analyses.data.map((manifest) => (
                  <details key={manifest.id} className="group rounded-xl border bg-background">
                    <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
                      <span className="flex size-9 items-center justify-center rounded-lg border bg-background-secondary">
                        <Activity className="size-4 text-foreground-muted" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-foreground">
                          {manifest.name}
                        </span>
                        <span className="mt-0.5 block text-tiny text-foreground-muted">
                          {TYPE_LABELS[manifest.type]} · {manifest.solver || 'Solver undecided'} ·{' '}
                          {manifest.files.length} files
                        </span>
                      </span>
                      <Badge variant="soft" tone={statusTone(manifest.status)}>
                        {manifest.status}
                      </Badge>
                      <ChevronDown className="size-3.5 text-foreground-muted transition-transform group-open:rotate-180" />
                    </summary>
                    <div className="border-t p-4">
                      <div className="grid grid-cols-2 gap-4 text-xs">
                        <AnalysisDetail label="Objective" value={manifest.objective} />
                        <AnalysisDetail
                          label="Revision"
                          value={manifest.model.revisionId ?? 'Not recorded'}
                        />
                        <AnalysisDetail label="Loads" value={manifest.loads} />
                        <AnalysisDetail label="Constraints" value={manifest.constraints} />
                      </div>
                      {manifest.files.length ? (
                        <div className="mt-4 flex flex-wrap gap-2">
                          {manifest.files.map((file) => (
                            <Badge key={file.id} variant="soft" tone="neutral">
                              {file.role} · {file.name}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                      <div className="mt-4 flex items-center justify-end gap-2">
                        <Select.Root
                          value={manifest.status}
                          disabled={updateAnalysis.isPending}
                          onValueChange={(value) =>
                            updateAnalysis.mutate({
                              ...manifest,
                              status: cadAnalysisStatusSchema.parse(value),
                            })
                          }
                        >
                          <Select.Trigger appearance="input" className="w-36">
                            <Select.Value>{manifest.status}</Select.Value>
                          </Select.Trigger>
                          <Select.Content width="trigger">
                            {cadAnalysisStatusSchema.options.map((status) => (
                              <Select.Item key={status} value={status}>
                                {status}
                              </Select.Item>
                            ))}
                          </Select.Content>
                        </Select.Root>
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          disabled={attachFile.isPending}
                          onClick={() => {
                            setAttachmentTarget(manifest);
                            inputRef.current?.click();
                          }}
                        >
                          <FilePlus2 className="size-3.5" /> Attach solver file
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => void openFolder(manifest)}
                        >
                          <ArrowUpRight className="size-3.5" /> Open folder
                        </Button>
                      </div>
                    </div>
                  </details>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed bg-background p-8 text-center">
                <FlaskConical className="mx-auto size-7 text-foreground-muted" />
                <div className="mt-3 text-sm font-medium text-foreground">No analyses yet</div>
                <p className="mt-1 text-xs text-foreground-muted">
                  Create a setup only when the model has a question that needs analysis.
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        hidden
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = '';
          if (file && attachmentTarget) attachFile.mutate({ manifest: attachmentTarget, file });
          setAttachmentTarget(null);
        }}
      />
    </div>
  );
});

function AnalysisDetail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-micro font-medium tracking-wide text-foreground-muted uppercase">
        {label}
      </div>
      <div className="mt-1 whitespace-pre-wrap text-foreground">{value || 'Not defined'}</div>
    </div>
  );
}

function statusTone(status: CadAnalysisManifest['status']) {
  if (status === 'completed') return 'success' as const;
  if (status === 'failed') return 'error' as const;
  if (status === 'running') return 'warning' as const;
  return 'neutral' as const;
}

function showError(title: string) {
  return (error: Error) =>
    toast.error(title, { description: error instanceof Error ? error.message : String(error) });
}
