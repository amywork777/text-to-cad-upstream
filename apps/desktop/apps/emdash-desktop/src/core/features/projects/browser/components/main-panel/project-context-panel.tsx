import { Badge, Button, Textarea, ToggleGroup, toast } from '@emdash/ui/react/primitives';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Beaker, ClipboardList, Factory, FileText, FolderOpen, Loader2, Save } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import {
  createProjectBriefTemplate,
  ensureProjectReferenceDirectory,
  loadProjectBrief,
  saveProjectBrief,
  type ProjectContextLocation,
} from '@core/features/projects/api/browser/project-context';
import { getHostClient } from '@core/primitives/desktop-host/browser/host-client';
import type { Project } from '@core/primitives/projects/api';
import { ProjectDiscussionPanel } from './project-discussion-panel';
import { ProjectEngineeringFilesPanel } from './project-engineering-files-panel';
import { ProjectManufacturingPanel } from './project-manufacturing-panel';

type ProjectContextMode = 'documents' | 'materials' | 'brief' | 'manufacturing';

export function ProjectContextPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<ProjectContextMode>('documents');
  const [discussionDraft, setDiscussionDraft] = useState<string | undefined>();
  const [draft, setDraft] = useState<string | null>(null);
  const [openingReferences, setOpeningReferences] = useState(false);
  const sshConnectionId = project.type === 'ssh' ? project.connectionId : undefined;
  const location: ProjectContextLocation = useMemo(
    () => ({
      projectPath: project.path,
      projectName: project.name,
      ...(sshConnectionId ? { sshConnectionId } : {}),
    }),
    [project.name, project.path, sshConnectionId]
  );
  const queryKey = ['projectBrief', project.id] as const;
  const brief = useQuery({
    queryKey,
    queryFn: async () => await loadProjectBrief(location),
  });
  const visibleContent = draft ?? brief.data?.content ?? createProjectBriefTemplate(project.name);
  const saveBrief = useMutation({
    mutationFn: async (content: string) => await saveProjectBrief(location, content),
    onSuccess: (_, content) => {
      queryClient.setQueryData(queryKey, { exists: true, content });
      setDraft(null);
      toast('Project context saved');
    },
    onError: (error) => {
      toast.error('Could not save project context', {
        description: error instanceof Error ? error.message : String(error),
      });
    },
  });

  const openReferences = async () => {
    if (openingReferences || project.type === 'ssh') return;
    setOpeningReferences(true);
    try {
      const directory = await ensureProjectReferenceDirectory(location);
      const opened = await (await getHostClient()).openPath({ path: directory });
      if (!opened.success) throw new Error(opened.error);
    } catch (error) {
      toast.error('Could not open project references', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setOpeningReferences(false);
    }
  };
  const clearDiscussionDraft = useCallback(() => setDiscussionDraft(undefined), []);

  const status = contextStatus({
    loading: brief.isPending,
    failed: brief.isError,
    saving: saveBrief.isPending,
    dirty: draft !== null,
    exists: brief.data?.exists === true,
  });

  return (
    <section aria-label="Project home workspace" className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex shrink-0 items-center justify-between gap-4">
        <ToggleGroup.Root
          multiple={false}
          value={[mode]}
          onValueChange={([value]) => {
            if (value) setMode(value as ProjectContextMode);
          }}
        >
          <ToggleGroup.Item value="documents" className="gap-1.5 text-xs">
            <FileText className="size-3.5" />
            Documents
          </ToggleGroup.Item>
          <ToggleGroup.Item value="materials" className="gap-1.5 text-xs">
            <Beaker className="size-3.5" />
            Materials
          </ToggleGroup.Item>
          <ToggleGroup.Item value="brief" className="gap-1.5 text-xs">
            <ClipboardList className="size-3.5" />
            Brief
          </ToggleGroup.Item>
          <ToggleGroup.Item value="manufacturing" className="gap-1.5 text-xs">
            <Factory className="size-3.5" />
            Manufacturing
          </ToggleGroup.Item>
        </ToggleGroup.Root>
        <span className="text-tiny text-foreground-muted">
          Project workspace · shared across models
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(20rem,24rem)] gap-3">
        <div className="relative min-h-0 min-w-0">
          <div
            className={`${mode === 'documents' || mode === 'materials' ? 'flex' : 'hidden'} absolute inset-0`}
            inert={mode === 'documents' || mode === 'materials' ? undefined : true}
          >
            <ProjectEngineeringFilesPanel
              project={project}
              view={mode === 'materials' ? 'materials' : 'documents'}
              onAskDocument={(document) =>
                setDiscussionDraft(
                  `Regarding the ${document.kind.replaceAll('-', ' ')} “${document.title}” at ${document.relativePath}: `
                )
              }
            />
          </div>

          <div
            className={`${mode === 'brief' ? 'flex' : 'hidden'} absolute inset-0 min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-background`}
            inert={mode === 'brief' ? undefined : true}
          >
            <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div>
                <div className="text-sm font-medium text-foreground">Engineering brief</div>
                <p className="mt-0.5 text-xs text-foreground-muted">
                  Requirements and decisions supplied to every model agent.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={openingReferences || project.type === 'ssh'}
                  onClick={() => void openReferences()}
                >
                  {openingReferences ? (
                    <Loader2 className="size-3 animate-spin" />
                  ) : (
                    <FolderOpen className="size-3" />
                  )}
                  Context folder
                </Button>
                <Badge tone={status.tone} variant="soft">
                  {status.loading ? <Loader2 className="mr-1 size-3 animate-spin" /> : null}
                  {status.label}
                </Badge>
              </div>
            </div>
            {brief.isError ? (
              <div className="border-destructive/30 bg-destructive/5 text-destructive border-b px-4 py-2 text-xs">
                {brief.error instanceof Error
                  ? brief.error.message
                  : 'The brief could not be loaded.'}
              </div>
            ) : null}
            <Textarea
              aria-label="Project engineering brief"
              value={visibleContent}
              className="min-h-0 flex-1 resize-none rounded-none border-0 bg-background p-4 font-mono text-xs leading-5 shadow-none focus-visible:ring-0"
              onChange={(event) => setDraft(event.target.value)}
            />
            <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
              <span className="text-tiny text-foreground-muted">
                <code>project.md</code> · references stay as ordinary files in <code>context/</code>
              </span>
              <Button
                type="button"
                size="sm"
                disabled={
                  saveBrief.isPending ||
                  brief.isPending ||
                  brief.isError ||
                  (draft === null && brief.data?.exists === true)
                }
                onClick={() => saveBrief.mutate(visibleContent)}
              >
                {saveBrief.isPending ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <Save className="size-3" />
                )}
                Save brief
              </Button>
            </div>
          </div>

          <div
            className={`${mode === 'manufacturing' ? 'flex' : 'hidden'} absolute inset-0 min-h-0`}
            inert={mode === 'manufacturing' ? undefined : true}
          >
            <ProjectManufacturingPanel project={project} />
          </div>
        </div>

        <ProjectDiscussionPanel
          project={project}
          draftSeed={discussionDraft}
          onDraftSeedConsumed={clearDiscussionDraft}
        />
      </div>
    </section>
  );
}

function contextStatus({
  loading,
  failed,
  saving,
  dirty,
  exists,
}: {
  loading: boolean;
  failed: boolean;
  saving: boolean;
  dirty: boolean;
  exists: boolean;
}): {
  label: string;
  tone: 'neutral' | 'success' | 'warning' | 'error';
  loading: boolean;
} {
  if (loading) return { label: 'Loading', tone: 'neutral', loading: true };
  if (failed) return { label: 'Unavailable', tone: 'error', loading: false };
  if (saving) return { label: 'Saving', tone: 'neutral', loading: true };
  if (dirty) return { label: 'Unsaved', tone: 'warning', loading: false };
  if (exists) return { label: 'Saved locally', tone: 'success', loading: false };
  return { label: 'Not created', tone: 'neutral', loading: false };
}
