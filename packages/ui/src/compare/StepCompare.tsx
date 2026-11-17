import { useEffect, useState } from 'react';
import { ArrowLeftRight, ArrowRight, GitCompareArrows, X } from 'lucide-react';
import { StepDiff } from '@draftwright/specify-ui';
import '@draftwright/specify-ui/style.css';
import './stepCompare.css';
import { Button } from '../primitives/button.jsx';
import { TooltipHint } from '../primitives/tooltip.jsx';
import { Spinner } from '../primitives/spinner.js';
import { useI18n } from '../i18n/index.js';
import { baseName } from '../cad-viewer/catalog.js';
import type { StepCompareProps } from './types.js';

type Files = { before: { name: string; bytes: Uint8Array }; after: { name: string; bytes: Uint8Array } };

/**
 * Two revisions of a STEP compared by Specify (`@draftwright/specify-ui`'s `StepDiff`, its engine in
 * a worker of its own): the later part with its faces coloured by what changed, the earlier one's
 * gone or moved faces over it in translucent red, the report of what changed feature by feature
 * beside it, and the PMI that changed; an assembly lists its parts first. Above it, the bar names the
 * two files, swaps them and closes the comparison (Escape too). The files are read whole by the host
 * (`readFile`) and compared in the page: nothing is uploaded. It changes nothing.
 */
export function StepCompare({ before, after, readFile, onSwap, onClose }: StepCompareProps) {
  const { t } = useI18n();
  const [files, setFiles] = useState<Files | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setFiles(null); setError('');
    Promise.all([readFile(before, { signal: controller.signal }), readFile(after, { signal: controller.signal })]).then(([old, next]) => {
      if (!controller.signal.aborted) setFiles({ before: { name: baseName(before), bytes: old }, after: { name: baseName(after), bytes: next } });
    }, (failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
    });
    return () => controller.abort();
  }, [before, after, readFile]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return <section aria-label={t('compare.title')} className="flex min-h-0 flex-1 flex-col" data-step-compare="">
    <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-border px-2 text-xs">
      <GitCompareArrows className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      <h2 className="sr-only">{t('compare.title')}</h2>
      <span className="shrink-0 text-muted-foreground">{t('compare.before')}</span>
      <span className="min-w-0 truncate" data-compare-before="">{baseName(before)}</span>
      <ArrowRight className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="shrink-0 text-muted-foreground">{t('compare.after')}</span>
      <span className="min-w-0 truncate" data-compare-after="">{baseName(after)}</span>
      <TooltipHint content={t('compare.swap')}>
        <Button type="button" variant="ghost" size="icon-xs" className="text-muted-foreground" aria-label={t('compare.swap')} onClick={onSwap}>
          <ArrowLeftRight className="size-3.5" aria-hidden="true" />
        </Button>
      </TooltipHint>
      <span className="flex-1" />
      <span className="hidden shrink-0 text-tiny text-muted-foreground sm:inline">{t('compare.credit')}</span>
      <TooltipHint content={t('compare.close')}>
        <Button type="button" variant="ghost" size="icon-xs" className="text-muted-foreground" aria-label={t('compare.close')} onClick={onClose}>
          <X className="size-3.5" aria-hidden="true" />
        </Button>
      </TooltipHint>
    </div>
    {error ? <p role="alert" className="p-4 text-xs text-destructive">{t('compare.failed', { reason: error })}</p>
      : files ? <div className="diff-page cad-step-diff"><StepDiff before={files.before} after={files.after} /></div>
        : <p role="status" className="flex flex-1 items-center justify-center gap-2 text-xs text-muted-foreground"><Spinner className="size-3.5" />{t('compare.reading')}</p>}
  </section>;
}
