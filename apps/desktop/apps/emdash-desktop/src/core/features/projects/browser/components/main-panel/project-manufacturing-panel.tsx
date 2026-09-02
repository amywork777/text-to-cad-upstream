import { Badge, Button, Field, Input, Select, Textarea, toast } from '@emdash/ui/react/primitives';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, CircleDashed, Loader2, Save, ScanLine } from 'lucide-react';
import { useMemo, useState } from 'react';
import {
  DEFAULT_MANUFACTURING_PROFILE,
  loadManufacturingProfile,
  loadProjectBrief,
  manufacturingProcessSchema,
  manufacturingReadinessChecks,
  saveManufacturingProfile,
  type ManufacturingProcess,
  type ManufacturingProfile,
  type ManufacturingReadinessCheck,
  type ProjectContextLocation,
} from '@core/features/projects/api/browser/project-context';
import type { Project } from '@core/primitives/projects/api';

const PROCESS_LABELS: Record<ManufacturingProcess, string> = {
  undecided: 'Undecided',
  fdm: 'FDM printing',
  sla: 'SLA printing',
  sls: 'SLS printing',
  'cnc-milling': 'CNC milling',
  'sheet-metal': 'Sheet metal',
  'injection-molding': 'Injection molding',
  other: 'Other',
};

export function ProjectManufacturingPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ManufacturingProfile | null>(null);
  const sshConnectionId = project.type === 'ssh' ? project.connectionId : undefined;
  const location: ProjectContextLocation = useMemo(
    () => ({
      projectPath: project.path,
      projectName: project.name,
      ...(sshConnectionId ? { sshConnectionId } : {}),
    }),
    [project.name, project.path, sshConnectionId]
  );
  const profileQueryKey = ['manufacturingProfile', project.id] as const;
  const briefQueryKey = ['projectBrief', project.id] as const;
  const profileQuery = useQuery({
    queryKey: profileQueryKey,
    queryFn: async () => await loadManufacturingProfile(location),
  });
  const briefQuery = useQuery({
    queryKey: briefQueryKey,
    queryFn: async () => await loadProjectBrief(location),
  });
  const profile = draft ?? profileQuery.data?.profile ?? DEFAULT_MANUFACTURING_PROFILE;
  const checks = manufacturingReadinessChecks(profile, briefQuery.data?.exists === true);
  const neededCount = checks.filter((check) => check.status === 'needed').length;
  const saveProfile = useMutation({
    mutationFn: async (value: ManufacturingProfile) =>
      await saveManufacturingProfile(location, value),
    onSuccess: (_, value) => {
      queryClient.setQueryData(profileQueryKey, { exists: true, profile: value });
      setDraft(null);
      toast('Manufacturing profile saved');
    },
    onError: (error) => {
      toast.error('Could not save manufacturing profile', {
        description: error instanceof Error ? error.message : String(error),
      });
    },
  });

  const update = (patch: Partial<ManufacturingProfile>) => {
    setDraft((current) => ({ ...(current ?? profile), ...patch }));
  };
  const status = profileStatus({
    loading: profileQuery.isPending,
    failed: profileQuery.isError,
    saving: saveProfile.isPending,
    dirty: draft !== null,
    exists: profileQuery.data?.exists === true,
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto rounded-lg border border-border bg-background-secondary">
      <div className="flex shrink-0 flex-col border-b border-border">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <div className="text-sm font-medium text-foreground">Manufacturing profile</div>
            <p className="mt-0.5 text-xs text-foreground-muted">
              Shared process constraints for every model agent.
            </p>
          </div>
          <Badge tone={status.tone} variant="soft">
            {status.loading ? <Loader2 className="mr-1 size-3 animate-spin" /> : null}
            {status.label}
          </Badge>
        </div>

        {profileQuery.isError ? (
          <div className="border-b border-border-destructive/30 bg-background-destructive/5 px-4 py-2 text-xs text-foreground-destructive">
            {profileQuery.error instanceof Error
              ? profileQuery.error.message
              : 'The manufacturing profile could not be loaded.'}
          </div>
        ) : null}

        <div className="bg-background p-5">
          <div className="grid grid-cols-2 gap-x-4 gap-y-5">
            <Field.Root>
              <Field.Label>Process</Field.Label>
              <Select.Root
                value={profile.process}
                onValueChange={(value) =>
                  update({ process: manufacturingProcessSchema.parse(value) })
                }
              >
                <Select.Trigger appearance="input" className="w-full">
                  <Select.Value>{PROCESS_LABELS[profile.process]}</Select.Value>
                </Select.Trigger>
                <Select.Content align="start" width="trigger">
                  {manufacturingProcessSchema.options.map((process) => (
                    <Select.Item key={process} value={process}>
                      {PROCESS_LABELS[process]}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </Field.Root>

            <Field.Root>
              <Field.Label>Material</Field.Label>
              <Input
                value={profile.material}
                placeholder="e.g. 6061-T6 aluminum"
                onChange={(event) => update({ material: event.currentTarget.value })}
              />
            </Field.Root>

            <Field.Root>
              <Field.Label>Quantity</Field.Label>
              <Input
                value={profile.quantity}
                placeholder="e.g. 3 prototypes"
                onChange={(event) => update({ quantity: event.currentTarget.value })}
              />
            </Field.Root>

            <Field.Root>
              <Field.Label>General tolerance (mm)</Field.Label>
              <Input
                type="number"
                min="0.001"
                max="100"
                step="0.001"
                value={profile.toleranceMm ?? ''}
                placeholder="e.g. 0.1"
                onChange={(event) =>
                  update({ toleranceMm: optionalNumber(event.currentTarget.value) })
                }
              />
            </Field.Root>

            <Field.Root>
              <Field.Label>Safety factor</Field.Label>
              <Input
                type="number"
                min="1"
                max="100"
                step="0.1"
                value={profile.safetyFactor ?? ''}
                placeholder="e.g. 2"
                onChange={(event) =>
                  update({ safetyFactor: optionalNumber(event.currentTarget.value) })
                }
              />
            </Field.Root>

            <Field.Root>
              <Field.Label>Surface finish</Field.Label>
              <Input
                value={profile.surfaceFinish}
                placeholder="Optional"
                onChange={(event) => update({ surfaceFinish: event.currentTarget.value })}
              />
            </Field.Root>

            <Field.Root className="col-span-2">
              <Field.Label>Manufacturing notes</Field.Label>
              <Textarea
                value={profile.notes}
                rows={4}
                placeholder="Tool access, support restrictions, grain direction, post-processing…"
                onChange={(event) => update({ notes: event.currentTarget.value })}
              />
            </Field.Root>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
          <span className="text-xs text-foreground-muted">
            Saved as <code>manufacturing.yaml</code> in the project folder.
          </span>
          <Button
            type="button"
            size="sm"
            disabled={
              saveProfile.isPending ||
              profileQuery.isPending ||
              profileQuery.isError ||
              (draft === null && profileQuery.data?.exists === true)
            }
            onClick={() => saveProfile.mutate(profile)}
          >
            {saveProfile.isPending ? (
              <Loader2 className="mr-1 size-3 animate-spin" />
            ) : (
              <Save className="mr-1 size-3" />
            )}
            Save profile
          </Button>
        </div>
      </div>

      <ManufacturingChecks checks={checks} neededCount={neededCount} />
    </div>
  );
}

function ManufacturingChecks({
  checks,
  neededCount,
}: {
  checks: ManufacturingReadinessCheck[];
  neededCount: number;
}) {
  return (
    <aside aria-label="Manufacturing checks" className="shrink-0 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-foreground">Checks</h3>
          <p className="mt-1 text-xs leading-5 text-foreground-muted">
            Inputs required before process-aware model validation.
          </p>
        </div>
        <Badge tone={neededCount === 0 ? 'success' : 'warning'} variant="soft">
          {neededCount === 0 ? 'Profile ready' : `${neededCount} needed`}
        </Badge>
      </div>

      <div className="mt-5 overflow-hidden rounded-lg border border-border bg-background">
        {checks.map((check, index) => (
          <div
            key={check.id}
            className={`flex items-start gap-3 px-3 py-3 ${index > 0 ? 'border-t border-border' : ''}`}
          >
            <CheckIcon status={check.status} />
            <div className="min-w-0 flex-1">
              <div className="text-xs font-medium text-foreground">{check.label}</div>
              <div className="mt-0.5 text-tiny leading-4 text-foreground-muted">{check.detail}</div>
            </div>
          </div>
        ))}
      </div>

      <p className="mt-4 text-tiny leading-4 text-foreground-passive">
        Hardcore does not infer a geometry pass from agent completion. Each model revision must
        produce its own inspect and validation evidence.
      </p>
    </aside>
  );
}

function CheckIcon({ status }: { status: ManufacturingReadinessCheck['status'] }) {
  if (status === 'ready') {
    return <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-foreground-success" />;
  }
  if (status === 'per-model') {
    return <ScanLine className="mt-0.5 size-4 shrink-0 text-foreground-muted" />;
  }
  return <CircleDashed className="mt-0.5 size-4 shrink-0 text-foreground-warning" />;
}

function optionalNumber(value: string): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function profileStatus({
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
