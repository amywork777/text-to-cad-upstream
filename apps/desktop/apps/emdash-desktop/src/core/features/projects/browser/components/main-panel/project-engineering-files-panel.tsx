import { encodeResourceUri } from '@emdash/core/primitives/path/api';
import {
  Badge,
  Button,
  Checkbox,
  Field,
  Input,
  Select,
  Textarea,
  toast,
} from '@emdash/ui/react/primitives';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowUpRight,
  Beaker,
  ChevronDown,
  FilePlus2,
  FileText,
  Loader2,
  MessageSquareText,
  Plus,
  Save,
  X,
} from 'lucide-react';
import { observer } from 'mobx-react-lite';
import { useEffect, useMemo, useRef, useState } from 'react';
import { getFilesClient } from '@core/features/files/api/browser/client';
import {
  addEngineeringDocument,
  EMPTY_ENGINEERING_WORKSPACE,
  engineeringDocumentKindSchema,
  loadEngineeringWorkspace,
  materialStatusSchema,
  saveEngineeringWorkspace,
  type EngineeringDocument,
  type EngineeringDocumentKind,
  type EngineeringWorkspace,
  type MaterialRecord,
  type MaterialStatus,
  type ProjectContextLocation,
} from '@core/features/projects/api/browser/project-context';
import { getTaskManagerStore } from '@core/features/tasks/api/browser/task-state/task-selectors';
import { resolveWorkspacePath } from '@core/features/workspaces/api/browser/workspace-path';
import { getHostClient } from '@core/primitives/desktop-host/browser/host-client';
import { hostFileRefFromNativePath } from '@core/primitives/desktop-runtime/api';
import type { Project } from '@core/primitives/projects/api';

const DOCUMENT_LABELS: Record<EngineeringDocumentKind, string> = {
  'material-datasheet': 'Material datasheet',
  requirements: 'Requirements / specification',
  calculation: 'Calculation',
  drawing: 'Drawing',
  bom: 'BOM / parts list',
  'assembly-instructions': 'Assembly instructions',
  'test-report': 'Test / inspection report',
  'supplier-quote': 'Supplier quote',
  reference: 'Reference',
};

const MATERIAL_STATUS_LABELS: Record<MaterialStatus, string> = {
  candidate: 'Candidate',
  approved: 'Approved',
  rejected: 'Rejected',
};

type MaterialDraft = Pick<
  MaterialRecord,
  'name' | 'grade' | 'supplier' | 'status' | 'datasheetDocumentId' | 'notes' | 'modelIds'
>;

const EMPTY_MATERIAL: MaterialDraft = {
  name: '',
  grade: '',
  supplier: '',
  status: 'candidate',
  datasheetDocumentId: null,
  notes: '',
  modelIds: [],
};

export const ProjectEngineeringFilesPanel = observer(function ProjectEngineeringFilesPanel({
  project,
  view,
  onAskDocument,
}: {
  project: Project;
  view: 'documents' | 'materials';
  onAskDocument: (document: EngineeringDocument) => void;
}) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [documentKind, setDocumentKind] = useState<EngineeringDocumentKind>('reference');
  const [materialDraft, setMaterialDraft] = useState<MaterialDraft>(EMPTY_MATERIAL);
  const [editingMaterialId, setEditingMaterialId] = useState<string | null>(null);
  const [previewDocument, setPreviewDocument] = useState<EngineeringDocument | null>(null);
  const taskManager = getTaskManagerStore(project.id);
  const models = Array.from(taskManager?.tasks.values() ?? [])
    .filter((task) => task.state !== 'unregistered' && task.data.type !== 'automation-run')
    .map((task) => ({ id: task.data.id, name: task.data.name }))
    .sort((left, right) => left.name.localeCompare(right.name));
  const location = useProjectContextLocation(project);
  const queryKey = ['engineeringWorkspace', project.id] as const;
  const query = useQuery({
    queryKey,
    queryFn: async () => await loadEngineeringWorkspace(location),
  });
  const workspace = query.data?.workspace ?? EMPTY_ENGINEERING_WORKSPACE;

  const uploadDocument = useMutation({
    mutationFn: async (file: File) =>
      await addEngineeringDocument(location, workspace, file, documentKind),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKey, { exists: true, workspace: next });
      toast('Engineering document added');
    },
    onError: (error) => {
      toast.error('Could not add engineering document', {
        description: error instanceof Error ? error.message : String(error),
      });
    },
  });
  const saveWorkspace = useMutation({
    mutationFn: async (next: EngineeringWorkspace) => {
      await saveEngineeringWorkspace(location, next);
      return next;
    },
    onSuccess: (next) => {
      queryClient.setQueryData(queryKey, { exists: true, workspace: next });
      toast('Engineering workspace saved');
    },
    onError: (error) => {
      toast.error('Could not save engineering workspace', {
        description: error instanceof Error ? error.message : String(error),
      });
    },
  });

  const openDocument = async (document: EngineeringDocument) => {
    const path = resolveWorkspacePath(project.path, document.relativePath);
    const result = await (await getHostClient()).openPath({ path });
    if (!result.success) {
      toast.error('Could not open document', { description: result.error });
    }
  };

  const saveMaterial = () => {
    if (!materialDraft.name.trim()) return;
    const now = new Date().toISOString();
    const existing = workspace.materials.find((material) => material.id === editingMaterialId);
    const material: MaterialRecord = {
      id: existing?.id ?? crypto.randomUUID(),
      ...materialDraft,
      name: materialDraft.name.trim(),
      grade: materialDraft.grade.trim(),
      supplier: materialDraft.supplier.trim(),
      notes: materialDraft.notes.trim(),
      createdAt: existing?.createdAt ?? now,
      updatedAt: now,
    };
    const materials = existing
      ? workspace.materials.map((candidate) =>
          candidate.id === existing.id ? material : candidate
        )
      : [...workspace.materials, material];
    saveWorkspace.mutate({ ...workspace, materials });
    setEditingMaterialId(null);
    setMaterialDraft(EMPTY_MATERIAL);
  };

  const editMaterial = (material: MaterialRecord) => {
    setEditingMaterialId(material.id);
    setMaterialDraft({
      name: material.name,
      grade: material.grade,
      supplier: material.supplier,
      status: material.status,
      datasheetDocumentId: material.datasheetDocumentId,
      notes: material.notes,
      modelIds: material.modelIds,
    });
  };

  if (query.isPending) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-foreground-muted">
        <Loader2 className="size-4 animate-spin" />
        Loading engineering files…
      </div>
    );
  }

  return (
    <div className="relative flex min-h-0 flex-1 overflow-hidden rounded-lg border bg-background">
      {view === 'documents' ? (
        <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
          <div className="flex items-center justify-between gap-4 border-b px-5 py-4">
            <div>
              <div className="text-sm font-medium text-foreground">Engineering documents</div>
              <p className="mt-0.5 text-xs text-foreground-muted">
                Datasheets, requirements, drawings, BOMs, assembly instructions, and test evidence.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Select.Root
                value={documentKind}
                onValueChange={(value) =>
                  setDocumentKind(engineeringDocumentKindSchema.parse(value))
                }
              >
                <Select.Trigger appearance="input" className="w-44">
                  <Select.Value>{DOCUMENT_LABELS[documentKind]}</Select.Value>
                </Select.Trigger>
                <Select.Content align="end">
                  {engineeringDocumentKindSchema.options.map((kind) => (
                    <Select.Item key={kind} value={kind}>
                      {DOCUMENT_LABELS[kind]}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
              <Button
                type="button"
                size="sm"
                disabled={uploadDocument.isPending || query.isError || project.type === 'ssh'}
                onClick={() => fileInputRef.current?.click()}
              >
                {uploadDocument.isPending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <FilePlus2 className="size-3.5" />
                )}
                Add file
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                hidden
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = '';
                  if (file) uploadDocument.mutate(file);
                }}
              />
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-5">
            {query.isError ? (
              <div className="rounded-md border border-border-destructive/30 bg-background-destructive/5 p-3 text-xs text-foreground-destructive">
                {query.error instanceof Error
                  ? query.error.message
                  : 'Engineering files unavailable.'}
              </div>
            ) : workspace.documents.length === 0 ? (
              <EmptyDocuments />
            ) : (
              <div className="flex flex-col gap-2">
                {workspace.documents.map((document) => (
                  <DocumentCard
                    key={document.id}
                    document={document}
                    models={models}
                    onAsk={() => onAskDocument(document)}
                    onOpen={() => setPreviewDocument(document)}
                    onSave={(next) =>
                      saveWorkspace.mutate({
                        ...workspace,
                        documents: workspace.documents.map((candidate) =>
                          candidate.id === next.id ? next : candidate
                        ),
                      })
                    }
                  />
                ))}
              </div>
            )}
          </div>
          <div className="border-t px-5 py-3 text-tiny text-foreground-muted">
            Files live in <code>context/</code>; their types and model links live in{' '}
            <code>engineering.json</code>.
          </div>
        </section>
      ) : null}

      {view === 'materials' ? (
        <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-background-secondary">
          <div className="border-b bg-background px-5 py-4">
            <div className="flex items-center gap-2">
              <Beaker className="size-4 text-foreground-muted" />
              <div className="text-sm font-medium text-foreground">Materials</div>
              <Badge variant="soft" tone="neutral">
                {workspace.materials.length}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-foreground-muted">
              Track candidate and approved materials with their source datasheets.
            </p>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-5">
            {workspace.materials.length > 0 ? (
              <div className="mb-5 flex flex-col gap-2">
                {workspace.materials.map((material) => (
                  <button
                    key={material.id}
                    type="button"
                    className="flex items-center gap-3 rounded-lg border bg-background p-3 text-left hover:bg-background-secondary"
                    onClick={() => editMaterial(material)}
                  >
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-background-secondary">
                      <Beaker className="size-3.5 text-foreground-muted" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium text-foreground">
                        {material.name}
                        {material.grade ? ` · ${material.grade}` : ''}
                      </span>
                      <span className="mt-0.5 block text-tiny text-foreground-muted">
                        {MATERIAL_STATUS_LABELS[material.status]} ·{' '}
                        {material.modelIds.length === 0
                          ? 'All models'
                          : `${material.modelIds.length} linked`}
                      </span>
                    </span>
                    <ChevronDown className="size-3.5 -rotate-90 text-foreground-muted" />
                  </button>
                ))}
              </div>
            ) : null}

            <div className="rounded-lg border bg-background p-4">
              <div className="text-xs font-medium text-foreground">
                {editingMaterialId ? 'Edit material' : 'Add material'}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <Field.Root>
                  <Field.Label>Name or family</Field.Label>
                  <Input
                    value={materialDraft.name}
                    placeholder="e.g. Aluminum"
                    onChange={(event) =>
                      setMaterialDraft((current) => ({
                        ...current,
                        name: event.currentTarget.value,
                      }))
                    }
                  />
                </Field.Root>
                <Field.Root>
                  <Field.Label>Grade</Field.Label>
                  <Input
                    value={materialDraft.grade}
                    placeholder="e.g. 6061-T6"
                    onChange={(event) =>
                      setMaterialDraft((current) => ({
                        ...current,
                        grade: event.currentTarget.value,
                      }))
                    }
                  />
                </Field.Root>
                <Field.Root>
                  <Field.Label>Supplier</Field.Label>
                  <Input
                    value={materialDraft.supplier}
                    placeholder="Optional"
                    onChange={(event) =>
                      setMaterialDraft((current) => ({
                        ...current,
                        supplier: event.currentTarget.value,
                      }))
                    }
                  />
                </Field.Root>
                <Field.Root>
                  <Field.Label>Status</Field.Label>
                  <Select.Root
                    value={materialDraft.status}
                    onValueChange={(value) =>
                      setMaterialDraft((current) => ({
                        ...current,
                        status: materialStatusSchema.parse(value),
                      }))
                    }
                  >
                    <Select.Trigger appearance="input" className="w-full">
                      <Select.Value>{MATERIAL_STATUS_LABELS[materialDraft.status]}</Select.Value>
                    </Select.Trigger>
                    <Select.Content width="trigger">
                      {materialStatusSchema.options.map((status) => (
                        <Select.Item key={status} value={status}>
                          {MATERIAL_STATUS_LABELS[status]}
                        </Select.Item>
                      ))}
                    </Select.Content>
                  </Select.Root>
                </Field.Root>
                <Field.Root className="col-span-2">
                  <Field.Label>Source datasheet</Field.Label>
                  <Select.Root
                    value={materialDraft.datasheetDocumentId ?? 'none'}
                    onValueChange={(value) =>
                      setMaterialDraft((current) => ({
                        ...current,
                        datasheetDocumentId: value === 'none' ? null : value,
                      }))
                    }
                  >
                    <Select.Trigger appearance="input" className="w-full">
                      <Select.Value>
                        {workspace.documents.find(
                          (document) => document.id === materialDraft.datasheetDocumentId
                        )?.title ?? 'No datasheet linked'}
                      </Select.Value>
                    </Select.Trigger>
                    <Select.Content width="trigger">
                      <Select.Item value="none">No datasheet linked</Select.Item>
                      {workspace.documents
                        .filter((document) => document.kind === 'material-datasheet')
                        .map((document) => (
                          <Select.Item key={document.id} value={document.id}>
                            {document.title}
                          </Select.Item>
                        ))}
                    </Select.Content>
                  </Select.Root>
                </Field.Root>
                <Field.Root className="col-span-2">
                  <Field.Label>Engineering notes</Field.Label>
                  <Textarea
                    value={materialDraft.notes}
                    rows={3}
                    placeholder="Properties, temperature limits, process notes, assumptions…"
                    onChange={(event) =>
                      setMaterialDraft((current) => ({
                        ...current,
                        notes: event.currentTarget.value,
                      }))
                    }
                  />
                </Field.Root>
              </div>
              <ModelLinkPicker
                models={models}
                selected={materialDraft.modelIds}
                onChange={(modelIds) => setMaterialDraft((current) => ({ ...current, modelIds }))}
              />
              <div className="mt-4 flex justify-end gap-2">
                {editingMaterialId ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setEditingMaterialId(null);
                      setMaterialDraft(EMPTY_MATERIAL);
                    }}
                  >
                    Cancel
                  </Button>
                ) : null}
                <Button
                  type="button"
                  size="sm"
                  disabled={!materialDraft.name.trim() || saveWorkspace.isPending || query.isError}
                  onClick={saveMaterial}
                >
                  {saveWorkspace.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : editingMaterialId ? (
                    <Save className="size-3.5" />
                  ) : (
                    <Plus className="size-3.5" />
                  )}
                  {editingMaterialId ? 'Save material' : 'Add material'}
                </Button>
              </div>
            </div>
          </div>
        </section>
      ) : null}
      {previewDocument ? (
        <ProjectDocumentPreview
          project={project}
          document={previewDocument}
          onClose={() => setPreviewDocument(null)}
          onAsk={() => onAskDocument(previewDocument)}
          onOpenExternal={() => void openDocument(previewDocument)}
        />
      ) : null}
    </div>
  );
});

function DocumentCard({
  document,
  models,
  onAsk,
  onOpen,
  onSave,
}: {
  document: EngineeringDocument;
  models: { id: string; name: string }[];
  onAsk: () => void;
  onOpen: () => void;
  onSave: (document: EngineeringDocument) => void;
}) {
  const [draft, setDraft] = useState(document);
  return (
    <details className="group overflow-hidden rounded-lg border bg-background-secondary">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-background">
          <FileText className="size-3.5 text-foreground-muted" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-medium text-foreground">
            {document.title}
          </span>
          <span className="mt-0.5 block truncate text-tiny text-foreground-muted">
            {DOCUMENT_LABELS[document.kind]} · {document.relativePath}
          </span>
        </span>
        <Badge variant="soft" tone="neutral">
          {document.modelIds.length === 0 ? 'All models' : `${document.modelIds.length} linked`}
        </Badge>
        <ChevronDown className="size-3.5 text-foreground-muted transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t bg-background p-4">
        <Field.Root>
          <Field.Label>Description</Field.Label>
          <Textarea
            rows={2}
            value={draft.description}
            placeholder="What evidence does this file contain?"
            onChange={(event) => setDraft({ ...draft, description: event.currentTarget.value })}
          />
        </Field.Root>
        <ModelLinkPicker
          models={models}
          selected={draft.modelIds}
          onChange={(modelIds) => setDraft({ ...draft, modelIds })}
        />
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onOpen}>
            <ArrowUpRight className="size-3.5" />
            Open
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={onAsk}>
            <MessageSquareText className="size-3.5" />
            Ask about file
          </Button>
          <Button type="button" size="sm" onClick={() => onSave(draft)}>
            <Save className="size-3.5" />
            Save details
          </Button>
        </div>
      </div>
    </details>
  );
}

function ProjectDocumentPreview({
  project,
  document,
  onClose,
  onAsk,
  onOpenExternal,
}: {
  project: Project;
  document: EngineeringDocument;
  onClose: () => void;
  onAsk: () => void;
  onOpenExternal: () => void;
}) {
  const [preview, setPreview] = useState<
    | { status: 'loading' }
    | { status: 'error'; message: string }
    | { status: 'ready'; url: string; mimeType: string; text: string | null }
  >({ status: 'loading' });
  const sshConnectionId = project.type === 'ssh' ? project.connectionId : undefined;

  useEffect(() => {
    let disposed = false;
    let objectUrl: string | null = null;
    void (async () => {
      const path = resolveWorkspacePath(project.path, document.relativePath);
      const result = await (
        await getFilesClient()
      ).fs.readBytes({
        uri: encodeResourceUri(hostFileRefFromNativePath(path, sshConnectionId)),
      });
      if (disposed) return;
      if (!result.success) {
        setPreview({ status: 'error', message: 'The document could not be loaded.' });
        return;
      }
      const bytes = await result.data.bytes();
      if (disposed) return;
      const buffer = new ArrayBuffer(bytes.byteLength);
      new Uint8Array(buffer).set(bytes);
      const mimeType = result.data.meta.mimeType || mimeTypeForPath(document.relativePath);
      const blob = new Blob([buffer], { type: mimeType });
      objectUrl = URL.createObjectURL(blob);
      const text = isTextDocument(mimeType, document.relativePath)
        ? new TextDecoder().decode(buffer)
        : null;
      setPreview({ status: 'ready', url: objectUrl, mimeType, text });
    })().catch((error) => {
      if (!disposed) {
        setPreview({
          status: 'error',
          message: error instanceof Error ? error.message : String(error),
        });
      }
    });
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document.relativePath, project.path, sshConnectionId]);

  return (
    <div className="absolute inset-0 z-20 flex min-h-0 flex-col bg-background">
      <div className="flex items-center gap-3 border-b px-5 py-3">
        <span className="flex size-8 items-center justify-center rounded-md border bg-background-secondary">
          <FileText className="size-3.5 text-foreground-muted" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">{document.title}</div>
          <div className="truncate text-tiny text-foreground-muted">{document.relativePath}</div>
        </div>
        <Badge variant="soft" tone="neutral">
          {DOCUMENT_LABELS[document.kind]}
        </Badge>
        <Button type="button" variant="secondary" size="sm" onClick={onAsk}>
          <MessageSquareText className="size-3.5" />
          Ask about file
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onOpenExternal}>
          <ArrowUpRight className="size-3.5" />
          Open externally
        </Button>
        <Button type="button" variant="ghost" size="xs" icon aria-label="Close" onClick={onClose}>
          <X className="size-3.5" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 bg-background-secondary p-4">
        {preview.status === 'loading' ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-foreground-muted">
            <Loader2 className="size-4 animate-spin" /> Loading document…
          </div>
        ) : preview.status === 'error' ? (
          <div className="flex h-full items-center justify-center text-sm text-foreground-destructive">
            {preview.message}
          </div>
        ) : preview.mimeType === 'application/pdf' || document.relativePath.endsWith('.pdf') ? (
          <iframe
            title={document.title}
            src={preview.url}
            className="h-full w-full rounded-lg border bg-white"
          />
        ) : preview.mimeType.startsWith('image/') ? (
          <div className="flex h-full items-center justify-center overflow-auto rounded-lg border bg-background p-4">
            <img
              src={preview.url}
              alt={document.title}
              className="max-h-full max-w-full object-contain"
            />
          </div>
        ) : preview.text !== null ? (
          <pre className="h-full overflow-auto rounded-lg border bg-background p-5 font-mono text-xs leading-5 whitespace-pre-wrap text-foreground">
            {preview.text}
          </pre>
        ) : (
          <div className="flex h-full flex-col items-center justify-center rounded-lg border bg-background text-center">
            <FileText className="size-7 text-foreground-muted" />
            <div className="mt-3 text-sm font-medium text-foreground">Preview not available</div>
            <p className="mt-1 max-w-sm text-xs text-foreground-muted">
              This file is still indexed for Claude and Codex. Open it in its native application to
              inspect it directly.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function mimeTypeForPath(path: string): string {
  const lower = path.toLowerCase();
  if (lower.endsWith('.pdf')) return 'application/pdf';
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.svg')) return 'image/svg+xml';
  if (lower.endsWith('.json')) return 'application/json';
  if (lower.endsWith('.csv')) return 'text/csv';
  if (lower.endsWith('.md')) return 'text/markdown';
  return 'application/octet-stream';
}

function isTextDocument(mimeType: string, path: string): boolean {
  return (
    mimeType.startsWith('text/') ||
    mimeType === 'application/json' ||
    /\.(md|txt|csv|tsv|json|yaml|yml)$/i.test(path)
  );
}

function ModelLinkPicker({
  models,
  selected,
  onChange,
}: {
  models: { id: string; name: string }[];
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  return (
    <div className="mt-4">
      <div className="text-tiny font-medium text-foreground">Applies to models</div>
      <p className="mt-0.5 text-micro text-foreground-muted">
        No selection means this evidence applies project-wide.
      </p>
      {models.length === 0 ? (
        <div className="mt-2 text-tiny text-foreground-passive">No CAD models yet.</div>
      ) : (
        <div className="mt-2 flex flex-wrap gap-2">
          {models.map((model) => {
            const checked = selected.includes(model.id);
            return (
              <label
                key={model.id}
                className="flex cursor-pointer items-center gap-2 rounded-md border bg-background px-2.5 py-1.5 text-tiny text-foreground-muted"
              >
                <Checkbox
                  checked={checked}
                  onCheckedChange={(value) =>
                    onChange(
                      value
                        ? [...selected, model.id]
                        : selected.filter((modelId) => modelId !== model.id)
                    )
                  }
                />
                {model.name}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

function EmptyDocuments() {
  return (
    <div className="flex h-full min-h-64 flex-col items-center justify-center rounded-lg border border-dashed bg-background-secondary p-8 text-center">
      <FilePlus2 className="size-6 text-foreground-muted" />
      <div className="mt-3 text-sm font-medium text-foreground">Add engineering evidence</div>
      <p className="mt-1 max-w-sm text-xs leading-5 text-foreground-muted">
        Choose a document type, then add a PDF, spreadsheet, drawing, image, or other project file.
      </p>
    </div>
  );
}

function useProjectContextLocation(project: Project): ProjectContextLocation {
  const sshConnectionId = project.type === 'ssh' ? project.connectionId : undefined;
  return useMemo(
    () => ({
      projectPath: project.path,
      projectName: project.name,
      ...(sshConnectionId ? { sshConnectionId } : {}),
    }),
    [project.name, project.path, sshConnectionId]
  );
}
