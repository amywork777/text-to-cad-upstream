import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ComponentType, type ReactNode } from 'react';
import type { FileSource } from '../file-viewer/types.js';
import { DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '../primitives/dropdown-menu.jsx';
import { Spinner } from '../primitives/spinner.js';
import { useI18n } from '../i18n/index.js';
import { baseName, normalizePath } from '../cad-viewer/catalog.js';
import type { StepCompareProps } from './types.js';

/** A STEP file, by its name: the files Compare offers and compares. */
export const STEP_FILE = /\.(?:step|stp)$/i;

/**
 * Where a host's Compare view comes from: `@cad/ui/compare`, imported by the host
 * (`() => import('@cad/ui/compare')`). The view brings Specify's engine, a WebAssembly module of
 * about 16 MB, so a host that cannot serve it (the CAD app, one HTML page in a host's sandbox) passes
 * none and the viewer offers no Compare; one that can loads it only when a comparison is opened.
 */
export type StepCompareLoader = () => Promise<{ StepCompare: ComponentType<StepCompareProps> }>;

/** The folder a file is in. */
const folderOf = (path: string) => path.slice(0, Math.max(path.lastIndexOf('/'), 0)) || '/';

/**
 * The other STEP files in the folder of the STEP on screen, by name, read once each time the submenu
 * opens: a revision is usually saved beside the file it revises (`bracket.step`, `bracket-rev-b.step`).
 */
function useFolderSteps(files: FileSource, file: string) {
  const [state, setState] = useState<{ file: string; steps: readonly string[] | null; error: string }>({ file, steps: null, error: '' });
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), [file]);
  const read = useCallback(() => {
    if (!files.list) return;
    controller.current?.abort();
    const asked = new AbortController();
    controller.current = asked;
    // A list already read stays while it is read again (an opening that hovers twice reads twice).
    setState(current => (current.file === file ? current : { file, steps: null, error: '' }));
    files.list(folderOf(file), { signal: asked.signal }).then(entries => {
      if (asked.signal.aborted) return;
      const steps = entries.filter(entry => entry.kind !== 'directory' && STEP_FILE.test(entry.name) && normalizePath(entry.path) !== file)
        .map(entry => normalizePath(entry.path))
        .sort((a, b) => baseName(a).localeCompare(baseName(b), undefined, { numeric: true }));
      setState({ file, steps, error: '' });
    }, (error: unknown) => {
      if (!asked.signal.aborted) setState({ file, steps: [], error: error instanceof Error ? error.message : String(error) });
    });
  }, [files, file]);
  return { steps: state.file === file ? state.steps : null, error: state.file === file ? state.error : '', read };
}

/**
 * Compare, for a STEP on screen: `menu`, the file menu's Compare with, a submenu of the other STEP
 * files in its folder, and `overlay`, the comparison of the one picked (before) with the file on
 * screen (after), drawn over the view under the navbar until it is closed. Specify compares them
 * (`@draftwright/specify-ui`'s STEP diff): what changed feature by feature, coloured on the part, and
 * the PMI that changed. Both are there only where the host can hand a file's bytes (`readFile`) and
 * load the view (`load`), and only for a STEP; a file opened next closes the comparison.
 */
export function CompareControls({ file, files, readFile, load, children }: {
  /** The file on screen, by its absolute path (`''`: none). */
  file: string;
  files: FileSource;
  readFile?: StepCompareProps['readFile'];
  load?: StepCompareLoader;
  children(slots: { menu: ReactNode; overlay: ReactNode }): ReactNode;
}) {
  const { t } = useI18n();
  const path = normalizePath(file);
  const enabled = Boolean(readFile && load && files.list && STEP_FILE.test(path));
  const { steps, error, read } = useFolderSteps(files, path);
  const [pair, setPair] = useState<{ before: string; after: string } | null>(null);
  // Another file on screen closes the comparison: it was of the one before.
  useEffect(() => { setPair(null); }, [path]);
  const View = useMemo(() => (load ? lazy(() => load().then(module => ({ default: module.StepCompare }))) : null), [load]);

  const label = t('compare.with');
  const menu = enabled ? <DropdownMenuSub onOpenChange={(open: boolean) => { if (open) read(); }}>
    <DropdownMenuSubTrigger data-compare-menu="">{label}</DropdownMenuSubTrigger>
    <DropdownMenuSubContent aria-label={label}>
      {steps === null ? <DropdownMenuItem disabled><Spinner className="size-3" />{t('compare.listing')}</DropdownMenuItem>
        : steps.length ? steps.map(step => <DropdownMenuItem key={step} data-compare-file={step} onSelect={() => setPair({ before: step, after: path })}>
          <span className="truncate">{baseName(step)}</span>
        </DropdownMenuItem>)
          : <DropdownMenuItem disabled>{error || t('compare.none')}</DropdownMenuItem>}
    </DropdownMenuSubContent>
  </DropdownMenuSub> : null;
  const overlay = enabled && pair && View && readFile ? <div className="absolute inset-0 z-40 flex min-h-0 flex-col bg-background" data-compare-overlay="">
    <Suspense fallback={<p role="status" className="flex flex-1 items-center justify-center gap-2 text-xs text-muted-foreground"><Spinner className="size-3.5" />{t('compare.reading')}</p>}>
      <View before={pair.before} after={pair.after} readFile={readFile}
        onSwap={() => setPair(current => current && { before: current.after, after: current.before })}
        onClose={() => setPair(null)} />
    </Suspense>
  </div> : null;
  return children({ menu, overlay });
}
