import { Badge, Button, Input } from '@emdash/ui/react/primitives';
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { getBrowserClient } from '@core/features/browser/api/browser/client';
import type {
  CadDesignParameter,
  CadSourceHistory,
} from '@core/features/cad/api/cad-source-history';
import type { TaskTabContext } from '@core/features/workbench/api/browser/tabs/task-tab-context';
import type { CadTabResource } from '../api/browser/cad-tab-resource';
import { useCadSourceRebuild } from './use-cad-source-rebuild';

interface HistorySnapshot {
  sourceHash: string;
  history: CadSourceHistory;
}

export function CadParametersPanel({
  resource,
  task,
  sourcePath,
}: {
  resource: CadTabResource;
  task: TaskTabContext;
  sourcePath: string;
}) {
  const [snapshot, setSnapshot] = useState<HistorySnapshot | null>(null);
  const [drafts, setDrafts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);
  const { rebuildSource, rebuilding, runInProgress } = useCadSourceRebuild({
    resource,
    task,
    sourcePath,
  });

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setMessage(null);
    try {
      const result = await (
        await getBrowserClient()
      ).readCadModelHistory({
        workspacePath: resource.workspacePath,
        filePath: sourcePath,
      });
      if (!result.success) {
        setSnapshot(null);
        setMessage({ tone: 'error', text: result.error });
        return;
      }
      setSnapshot(result);
      setDrafts(
        Object.fromEntries(
          result.history.parameters.map((parameter) => [parameter.id, parameter.defaultValue])
        )
      );
    } catch (error) {
      setSnapshot(null);
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : 'Could not load model history.',
      });
    } finally {
      setLoading(false);
    }
  }, [resource.workspacePath, sourcePath]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const changedValues = useMemo(() => {
    if (!snapshot) return {};
    return Object.fromEntries(
      snapshot.history.parameters
        .filter((parameter) => drafts[parameter.id] !== parameter.defaultValue)
        .map((parameter) => [parameter.id, drafts[parameter.id]])
    );
  }, [drafts, snapshot]);
  const hasChanges = Object.keys(changedValues).length > 0;
  const busy = loading || rebuilding || runInProgress;

  const applyAndView = async () => {
    if (!snapshot || !hasChanges || busy) return;
    setMessage(null);
    const result = await rebuildSource({
      restoreSourceOnFailure: true,
      prepare: async () => {
        const applied = await (
          await getBrowserClient()
        ).applyCadModelParameters({
          workspacePath: resource.workspacePath,
          filePath: sourcePath,
          expectedSourceHash: snapshot.sourceHash,
          values: changedValues,
        });
        return applied.success ? { success: true } : { success: false, error: applied.error };
      },
    });
    if (!result.success) {
      await loadHistory();
      setMessage({ tone: 'error', text: result.error });
      return;
    }
    resource.setWorkspaceMode('3d');
  };

  return (
    <CadParametersContent
      snapshot={snapshot}
      drafts={drafts}
      loading={loading}
      busy={busy}
      message={message}
      onDraftChange={(id, value) => setDrafts((current) => ({ ...current, [id]: value }))}
      onRefresh={() => void loadHistory()}
      onApply={() => void applyAndView()}
      onOpenSource={() => resource.setWorkspaceMode('source')}
    />
  );
}

export function CadParametersContent({
  snapshot,
  drafts,
  loading,
  busy,
  message,
  onDraftChange,
  onRefresh,
  onApply,
  onOpenSource,
}: {
  snapshot: HistorySnapshot | null;
  drafts: Record<string, number>;
  loading: boolean;
  busy: boolean;
  message: { tone: 'success' | 'error'; text: string } | null;
  onDraftChange: (id: string, value: number) => void;
  onRefresh: () => void;
  onApply: () => void;
  onOpenSource: () => void;
}) {
  const history = snapshot?.history;
  const hasParameterChanges =
    history?.parameters.some((parameter) => drafts[parameter.id] !== parameter.defaultValue) ??
    false;

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex min-h-12 shrink-0 items-center gap-3 border-b px-4">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-background-secondary text-foreground-muted">
          <SlidersHorizontal className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium text-foreground">Design parameters</div>
          <div className="text-micro text-foreground-tertiary-muted">
            Source-backed · {snapshot ? snapshot.sourceHash.slice(0, 8) : 'loading'}
          </div>
        </div>
        <Button type="button" size="xs" disabled={busy || !hasParameterChanges} onClick={onApply}>
          {busy ? (
            <Loader2 className="mr-1 size-3 animate-spin" />
          ) : (
            <CheckCircle2 className="mr-1 size-3" />
          )}
          Apply &amp; view
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="px-1.5"
          aria-label="Refresh design parameters"
          disabled={busy}
          onClick={onRefresh}
        >
          <RefreshCw className="size-3.5" />
        </Button>
      </div>

      {message ? (
        <div
          className={`flex items-center gap-2 border-b px-4 py-2 text-tiny ${
            message.tone === 'error'
              ? 'border-destructive/30 bg-destructive/5 text-destructive'
              : 'bg-success/5 text-success'
          }`}
          role={message.tone === 'error' ? 'alert' : 'status'}
        >
          {message.tone === 'error' ? (
            <AlertTriangle className="size-3.5 shrink-0" />
          ) : (
            <CheckCircle2 className="size-3.5 shrink-0" />
          )}
          {message.text}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-foreground-muted">
            <Loader2 className="size-3.5 animate-spin" />
            Reading model source…
          </div>
        ) : (
          <ParameterHistory
            parameters={history?.parameters ?? []}
            drafts={drafts}
            busy={busy}
            onDraftChange={onDraftChange}
            onOpenSource={onOpenSource}
          />
        )}
      </div>
    </div>
  );
}

function ParameterHistory({
  parameters,
  drafts,
  busy,
  onDraftChange,
  onOpenSource,
}: {
  parameters: readonly CadDesignParameter[];
  drafts: Record<string, number>;
  busy: boolean;
  onDraftChange: (id: string, value: number) => void;
  onOpenSource: () => void;
}) {
  if (parameters.length === 0) {
    return (
      <div className="mx-auto flex h-full max-w-lg flex-col items-center justify-center p-8 text-center">
        <SlidersHorizontal className="size-7 text-foreground-tertiary-muted" />
        <h2 className="mt-3 text-sm font-medium">No design parameters exposed</h2>
        <p className="mt-1 text-xs text-foreground-muted">
          Hardcore automatically exposes recognized feature dimensions and dimension-like source
          variables. For a custom control, declare a bounded
          <code className="mx-1 rounded bg-background-secondary px-1">@cad-parameter</code>
          above an uppercase numeric constant.
        </p>
        <Button type="button" variant="secondary" size="xs" className="mt-3" onClick={onOpenSource}>
          Open Source
        </Button>
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-3xl space-y-3 p-5">
      {parameters.map((parameter) => {
        const value = drafts[parameter.id] ?? parameter.defaultValue;
        const changed = value !== parameter.defaultValue;
        return (
          <section key={parameter.id} className="rounded-lg border bg-background-secondary/30 p-3">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <label htmlFor={`cad-parameter-${parameter.id}`} className="text-xs font-medium">
                    {parameter.label}
                  </label>
                  {parameter.origin && parameter.origin !== 'declared' ? (
                    <Badge tone="neutral" variant="soft">
                      {parameter.origin === 'function-parameter' ? 'Model' : 'Auto'}
                    </Badge>
                  ) : null}
                  {changed ? (
                    <Badge tone="warning" variant="soft">
                      Changed
                    </Badge>
                  ) : null}
                </div>
                {parameter.description ? (
                  <p className="mt-0.5 text-tiny text-foreground-muted">
                    {parameter.description}
                  </p>
                ) : null}
                <code className="mt-1 block text-micro text-foreground-tertiary-muted">
                  {parameter.symbol} · line {parameter.line}
                </code>
              </div>
              <div className="flex items-center gap-1.5">
                <Input
                  id={`cad-parameter-${parameter.id}`}
                  type="number"
                  className="h-7 w-24 text-right text-xs tabular-nums"
                  min={parameter.min}
                  max={parameter.max}
                  step={parameter.step}
                  value={value}
                  disabled={busy}
                  onChange={(event) => {
                    const nextValue = Number(event.currentTarget.value);
                    if (Number.isFinite(nextValue)) onDraftChange(parameter.id, nextValue);
                  }}
                />
                {parameter.unit ? (
                  <span className="w-8 text-micro text-foreground-muted">{parameter.unit}</span>
                ) : null}
              </div>
            </div>
            <div className="mt-3 flex items-center gap-3">
              <span className="w-12 text-right text-micro text-foreground-tertiary-muted tabular-nums">
                {parameter.min}
              </span>
              <input
                type="range"
                className="h-1 min-w-0 flex-1 cursor-pointer accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
                min={parameter.min}
                max={parameter.max}
                step={parameter.step}
                value={value}
                disabled={busy}
                aria-label={`${parameter.label} slider`}
                onChange={(event) => onDraftChange(parameter.id, Number(event.currentTarget.value))}
              />
              <span className="w-12 text-micro text-foreground-tertiary-muted tabular-nums">
                {parameter.max}
              </span>
              {changed ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  disabled={busy}
                  onClick={() => onDraftChange(parameter.id, parameter.defaultValue)}
                >
                  Reset
                </Button>
              ) : (
                <span className="w-12" />
              )}
            </div>
          </section>
        );
      })}
      <p className="text-micro text-foreground-tertiary-muted">
        Apply updates the Python source, rebuilds the canonical STEP, validates geometry, and
        creates a new model revision. Invalid geometry restores the previous source and model.
      </p>
    </div>
  );
}
