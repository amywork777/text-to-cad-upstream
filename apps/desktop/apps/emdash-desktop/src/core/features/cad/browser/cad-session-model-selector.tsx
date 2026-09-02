import type { AgentProviderId } from '@emdash/plugins/agents/types';
import { Button, Popover } from '@emdash/ui/react/primitives';
import {
  Check,
  ChevronDown,
  Code2,
  Loader2,
  RefreshCw,
  Sparkles,
  TriangleAlert,
} from 'lucide-react';
import { useState } from 'react';
import type { CadRuntimeStatus } from '@core/features/browser/api';

export interface CadSessionModelOption {
  id: string;
  name: string;
  description?: string;
}

const PROVIDER_LABELS = {
  claude: 'Claude',
  codex: 'Codex',
} as const;

export function CadSessionModelSelector({
  providerId,
  modelId,
  modelLabel,
  options,
  providerOptions,
  cadRuntimeStatus,
  disabled,
  onProviderChange,
  onChange,
  onRepairCadRuntime,
}: {
  providerId: string | null;
  modelId: string | null;
  modelLabel: string | null;
  options: ReadonlyArray<CadSessionModelOption>;
  providerOptions: readonly AgentProviderId[];
  cadRuntimeStatus?: CadRuntimeStatus;
  disabled: boolean;
  onProviderChange: (providerId: AgentProviderId) => Promise<void>;
  onChange: (modelId: string) => void;
  onRepairCadRuntime?: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [switchingProvider, setSwitchingProvider] = useState<AgentProviderId | null>(null);
  const [error, setError] = useState<string | null>(null);
  const providerLabel =
    providerId === 'claude'
      ? PROVIDER_LABELS.claude
      : providerId === 'codex'
        ? PROVIDER_LABELS.codex
        : 'AI';
  const effectiveModelId = modelId ?? options[0]?.id ?? null;
  const selected = options.find((option) => option.id === effectiveModelId);
  const selectedLabel = selected?.name ?? modelLabel ?? effectiveModelId ?? 'Default';
  const compactSelectedLabel = selectedLabel.replace(/\s*\(recommended\)$/i, '');

  const selectProvider = async (nextProviderId: AgentProviderId) => {
    if (nextProviderId === providerId || switchingProvider) return;
    setSwitchingProvider(nextProviderId);
    setError(null);
    try {
      await onProviderChange(nextProviderId);
      setOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not change agents.');
    } finally {
      setSwitchingProvider(null);
    }
  };

  return (
    <Popover.Root
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) setError(null);
      }}
    >
      <Popover.Trigger
        render={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 max-w-48 min-w-0 justify-start gap-1 px-1.5 text-tiny font-normal text-foreground-muted hover:text-foreground"
            disabled={disabled}
            aria-label="Choose agent and model"
            title={`${providerLabel} · ${selectedLabel}`}
          >
            <span className="shrink-0">{providerLabel}</span>
            <span className="text-foreground-tertiary-muted">·</span>
            <span className="min-w-0 truncate">
              {options.length === 0 && disabled ? 'Loading…' : compactSelectedLabel}
            </span>
            <ChevronDown className="size-3 shrink-0" />
          </Button>
        }
      />
      <Popover.Content align="start" side="top" className="w-64 p-1">
        {providerOptions.map((candidate) => {
          const label =
            candidate === 'claude'
              ? PROVIDER_LABELS.claude
              : candidate === 'codex'
                ? PROVIDER_LABELS.codex
                : candidate;
          const isCurrent = candidate === providerId;
          const isSwitching = candidate === switchingProvider;
          return (
            <button
              key={candidate}
              type="button"
              className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-xs hover:bg-background-secondary disabled:opacity-60"
              disabled={Boolean(switchingProvider)}
              aria-label={isCurrent ? `${label}, current agent` : `Continue with ${label}`}
              onClick={() => void selectProvider(candidate)}
            >
              {candidate === 'codex' ? (
                <Code2 className="size-3.5 shrink-0 text-foreground-muted" />
              ) : (
                <Sparkles className="size-3.5 shrink-0 text-foreground-muted" />
              )}
              <span className="min-w-0 flex-1 font-medium text-foreground">{label}</span>
              {!isCurrent && !isSwitching ? (
                <span className="text-micro text-foreground-muted">New chat</span>
              ) : null}
              {isSwitching ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : isCurrent ? (
                <Check className="size-3.5" />
              ) : null}
            </button>
          );
        })}
        <div className="my-1 border-t" />
        <div className="max-h-56 overflow-y-auto">
          {options.length > 0 ? (
            options.map((option) => {
              const isSelected = option.id === effectiveModelId;
              return (
                <button
                  key={option.id}
                  type="button"
                  className="flex min-h-8 w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-background-secondary"
                  onClick={() => {
                    onChange(option.id);
                    setOpen(false);
                  }}
                >
                  <span className="min-w-0 flex-1 truncate text-foreground">{option.name}</span>
                  {isSelected ? <Check className="size-3.5 shrink-0" /> : null}
                </button>
              );
            })
          ) : (
            <p className="px-2 py-2 text-micro text-foreground-muted">Loading models…</p>
          )}
        </div>
        {error ? <p className="text-destructive border-t px-2 py-2 text-micro">{error}</p> : null}
        {cadRuntimeStatus ? (
          <div className="mt-1 flex min-w-0 items-center gap-2 border-t px-2 pt-2 text-micro text-foreground-muted">
            {cadRuntimeStatus.state === 'ready' ? (
              <Check className="text-success size-3 shrink-0" />
            ) : cadRuntimeStatus.state === 'error' ? (
              <TriangleAlert className="text-warning size-3 shrink-0" />
            ) : (
              <Loader2 className="size-3 shrink-0 animate-spin" />
            )}
            <span className="min-w-0 flex-1 truncate" title={cadRuntimeStatus.message}>
              {cadRuntimeStatus.state === 'ready'
                ? 'CAD skills ready'
                : cadRuntimeStatus.state === 'error'
                  ? 'CAD skills need attention'
                  : 'Preparing CAD skills…'}
            </span>
            {cadRuntimeStatus.state === 'error' && onRepairCadRuntime ? (
              <Button
                type="button"
                variant="ghost"
                size="xs"
                className="h-6 px-1.5 text-micro"
                onClick={() => void onRepairCadRuntime()}
              >
                <RefreshCw className="mr-1 size-3" />
                Retry
              </Button>
            ) : null}
          </div>
        ) : null}
      </Popover.Content>
    </Popover.Root>
  );
}
