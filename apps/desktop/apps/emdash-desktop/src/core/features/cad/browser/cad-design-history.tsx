import type { ChatState, TranscriptTurn } from '@emdash/chat-ui';
import { Markdown } from '@emdash/ui/react/components';
import {
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  FileBox,
  Loader2,
  TerminalSquare,
  Wrench,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createEffect, createRoot } from 'solid-js';
import type { CadModelRecord } from '@core/features/cad/contributions/mementos';
import {
  summarizeCadTurns,
  formatWorkedDuration,
  type CadActivity,
  type CadArtifact,
  type CadTurnSummary,
} from './cad-design-history-model';

/**
 * CAD-oriented presentation of an ACP transcript.
 *
 * The interaction pattern is adapted from Open Design's Apache-2.0 Studio:
 * conclusions and generated files remain primary, while thinking and tool calls
 * live in one compact per-turn execution disclosure. Hardcore remains the runtime
 * and source of truth; this component only changes the product presentation.
 */

interface TranscriptSnapshot {
  turns: readonly TranscriptTurn[];
  activeTurnId: string | null;
}

export function CadDesignHistory({
  state,
  modelPath,
  run,
  persistedDurationsMs,
  onTurnDuration,
}: {
  state: ChatState;
  modelPath: string;
  run?: CadModelRecord['run'];
  persistedDurationsMs?: Readonly<Record<string, number>>;
  onTurnDuration?: (turnId: string, durationMs: number) => void;
}) {
  const snapshot = useTranscriptSnapshot(state);
  const summaries = useMemo(
    () => summarizeCadTurns(snapshot.turns, snapshot.activeTurnId, modelPath, persistedDurationsMs),
    [modelPath, persistedDurationsMs, snapshot]
  );
  const scrollerRef = useRef<HTMLDivElement>(null);
  const followTailRef = useRef(true);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller && followTailRef.current) scroller.scrollTop = scroller.scrollHeight;
  }, [summaries]);

  useEffect(() => {
    if (!onTurnDuration) return;
    for (const turn of summaries) {
      if (turn.state !== 'working' && turn.durationMs !== undefined && turn.durationMs >= 1_000) {
        onTurnDuration(turn.id, turn.durationMs);
      }
    }
  }, [onTurnDuration, summaries]);

  return (
    <div
      ref={scrollerRef}
      className="h-full overflow-y-auto px-4 py-4"
      onScroll={(event) => {
        const target = event.currentTarget;
        followTailRef.current = target.scrollHeight - target.scrollTop - target.clientHeight < 80;
      }}
    >
      <div className="mx-auto flex w-full max-w-xl flex-col gap-5">
        {summaries.map((turn, index) => (
          <DesignTurn
            key={turn.id}
            turn={turn}
            compact={index < summaries.length - 1}
            run={index === summaries.length - 1 ? run : undefined}
          />
        ))}
      </div>
    </div>
  );
}

function DesignTurn({
  turn,
  compact,
  run,
}: {
  turn: CadTurnSummary;
  compact: boolean;
  run?: CadModelRecord['run'];
}) {
  if (compact) {
    return (
      <details className="group overflow-hidden rounded-lg border bg-background-secondary">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs text-foreground-muted hover:bg-background-tertiary [&::-webkit-details-marker]:hidden">
          {activityStatus(turn.state).icon}
          <span className="min-w-0 flex-1 truncate text-foreground">{revisionLabel(turn)}</span>
          <ChevronDown className="size-3.5 shrink-0 transition-transform group-open:rotate-180" />
        </summary>
        <div className="flex flex-col gap-2.5 border-t px-3 py-3">
          {hasWorkDetails(turn) ? <TaskActivityDisclosure turn={turn} /> : null}
          {turn.assistantText ? (
            <div className="text-sm leading-6 text-foreground">
              <Markdown content={turn.assistantText} variant="compact" />
            </div>
          ) : null}
          {turn.artifacts.length > 0 ? <ArtifactSummary artifacts={turn.artifacts} /> : null}
        </div>
      </details>
    );
  }

  return (
    <article className="flex flex-col gap-3" data-turn-state={turn.state}>
      <div className="flex items-center gap-2 text-xs text-foreground-muted">
        {activityStatus(turn.state, run).icon}
        <span className="font-medium text-foreground">Latest revision</span>
        <span>{activityStatus(turn.state, run).label}</span>
      </div>
      {turn.userText ? (
        <div className="ml-8 rounded-xl border bg-background-secondary px-3 py-2.5 text-sm text-foreground">
          <Markdown content={turn.userText} variant="compact" />
        </div>
      ) : null}

      <div className="flex flex-col gap-2.5">
        {hasWorkDetails(turn) ? <TaskActivityDisclosure turn={turn} /> : null}

        {turn.assistantText ? (
          <div className="text-sm leading-6 text-foreground">
            <Markdown content={turn.assistantText} variant="compact" />
          </div>
        ) : null}

        {turn.artifacts.length > 0 ? <ArtifactSummary artifacts={turn.artifacts} /> : null}
      </div>
    </article>
  );
}

function revisionLabel(turn: CadTurnSummary): string {
  return (
    turn.userText
      .split('\n')
      .map((line) => line.replace(/^\s*[-#>*]+\s*/, '').trim())
      .find(Boolean) ?? 'Previous revision'
  );
}

function TaskActivityDisclosure({ turn }: { turn: CadTurnSummary }) {
  const running = turn.state === 'working';
  const [open, setOpen] = useState(running);
  const userToggledRef = useRef(false);

  useEffect(() => {
    if (!userToggledRef.current) setOpen(running);
  }, [running]);

  const status = activityStatus(turn.state);
  const completed = turn.state === 'completed';
  const completedLabel = formatWorkedDuration(turn.durationMs);
  const detailCount = [
    turn.activities.length > 0
      ? `${turn.activities.length} agent ${turn.activities.length === 1 ? 'step' : 'steps'}`
      : null,
    turn.thinkingTokens > 0 ? `~${turn.thinkingTokens.toLocaleString()} thinking tokens` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="overflow-hidden rounded-lg border bg-background-secondary">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-foreground-muted transition-colors hover:bg-background-tertiary"
        aria-expanded={open}
        onClick={() => {
          userToggledRef.current = true;
          setOpen((value) => !value);
        }}
      >
        {completed ? null : status.icon}
        <span className="font-medium text-foreground">
          {completed ? completedLabel : status.label}
        </span>
        <span className="min-w-0 flex-1 truncate">
          {running ? turn.activities.at(-1)?.title : detailCount}
        </span>
        <ChevronDown
          className={`size-3.5 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open ? (
        <div className="flex flex-col gap-1 border-t px-2 py-2">
          {turn.thinkingTokens > 0 ? (
            <div className="flex items-center gap-2 rounded-md px-2 py-1.5 text-tiny text-foreground-muted">
              <Wrench className="size-3 shrink-0" />
              <span className="text-foreground">Reasoning</span>
              <span>~{turn.thinkingTokens.toLocaleString()} tokens</span>
            </div>
          ) : null}
          {turn.activities.map((activity) => (
            <div
              key={activity.id}
              className="flex items-start gap-2 rounded-md px-2 py-1.5 text-tiny text-foreground-muted"
            >
              {activityIcon(activity)}
              <div className="min-w-0 flex-1">
                <div className="truncate text-foreground">{activity.title}</div>
                {activity.detail ? (
                  <code className="mt-0.5 block max-h-10 overflow-hidden font-mono text-micro leading-4 break-all text-foreground-tertiary-muted">
                    {activity.detail}
                  </code>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function hasWorkDetails(turn: CadTurnSummary): boolean {
  return turn.activities.length > 0 || turn.thinkingTokens > 0;
}

function ArtifactSummary({ artifacts }: { artifacts: CadArtifact[] }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-background-secondary">
      <div className="flex items-center gap-2 border-b px-3 py-2 text-micro font-semibold tracking-wider text-foreground-muted uppercase">
        <FileBox className="size-3.5" />
        Design outputs
      </div>
      <div className="flex flex-col py-1">
        {artifacts.map((artifact) => (
          <div
            key={`${artifact.operation}:${artifact.path}`}
            className="flex items-center gap-2 px-3 py-1.5"
          >
            <span className="rounded border px-1.5 py-0.5 text-[9px] text-foreground-muted uppercase">
              {artifact.operation === 'model' ? 'model' : artifact.operation}
            </span>
            <code className="min-w-0 flex-1 truncate font-mono text-tiny text-foreground">
              {artifact.path}
            </code>
          </div>
        ))}
      </div>
    </div>
  );
}

function useTranscriptSnapshot(state: ChatState): TranscriptSnapshot {
  const [snapshot, setSnapshot] = useState<TranscriptSnapshot>(() => readTranscript(state));

  useEffect(() => {
    setSnapshot(readTranscript(state));
    return createRoot((dispose) => {
      createEffect(() => {
        const next = readTranscript(state);
        setSnapshot(next);
      });
      return dispose;
    });
  }, [state]);

  return snapshot;
}

function readTranscript(state: ChatState): TranscriptSnapshot {
  const committed = state.transcript.state.committedTurns;
  const active = state.transcript.state.activeTurnSnapshot;
  return {
    turns: active ? [...committed, active] : committed,
    activeTurnId: active?.id ?? null,
  };
}

function activityStatus(
  state: CadTurnSummary['state'],
  run?: CadModelRecord['run']
): { label: string; icon: React.ReactNode } {
  if (state === 'working') {
    return {
      label: 'Working',
      icon: <Loader2 className="text-warning size-3.5 shrink-0 animate-spin" />,
    };
  }
  if (state === 'error') {
    return {
      label: 'Needs attention',
      icon: <CircleAlert className="text-destructive size-3.5 shrink-0" />,
    };
  }
  if (state === 'stopped') {
    return {
      label: 'Stopped',
      icon: <CircleAlert className="size-3.5 shrink-0 text-foreground-muted" />,
    };
  }
  if (run?.status === 'validating') {
    return {
      label: 'Validating geometry',
      icon: <Loader2 className="text-warning size-3.5 shrink-0 animate-spin" />,
    };
  }
  if (run?.validation?.status === 'failed') {
    return {
      label: 'Validation failed',
      icon: <CircleAlert className="text-destructive size-3.5 shrink-0" />,
    };
  }
  if (run?.validation?.status === 'passed') {
    return {
      label: 'Geometry validated',
      icon: <CheckCircle2 className="text-success size-3.5 shrink-0" />,
    };
  }
  return {
    label: 'Completed',
    icon: <CheckCircle2 className="text-success size-3.5 shrink-0" />,
  };
}

function activityIcon(activity: CadActivity) {
  if (activity.status === 'running') {
    return <Loader2 className="text-warning mt-0.5 size-3 shrink-0 animate-spin" />;
  }
  if (activity.status === 'error') {
    return <CircleAlert className="text-destructive mt-0.5 size-3 shrink-0" />;
  }
  if (/execute|command|terminal/i.test(activity.title)) {
    return <TerminalSquare className="mt-0.5 size-3 shrink-0" />;
  }
  return <Wrench className="mt-0.5 size-3 shrink-0" />;
}
