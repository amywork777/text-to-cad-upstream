import { useEffect, useRef, type ReactNode } from 'react';
import { FileX } from 'lucide-react';
import type { CadEntry } from '@cad/core/client';
import { EmptyState } from '../file-viewer/navigation/index.js';
import { useI18n } from '../i18n/index.js';

// How long the screen waits before asking the engine again about a document it does not hold:
// soon at first (an engine starting up takes up its cache in a few seconds), then every 10 s.
export const RECHECK_MS = [1000, 2000, 4000, 8000, 10000];

/** A file that is not there (yet). When the catalog has it -- a build wrote it, or it was put back --
 * the view opens it, once for each version of it: `reload` is the host's. A document named by its
 * id, whose catalog row does not change, is asked of the engine again while the screen is up
 * (`recheck`, true once the engine knows it): an engine that restarted under the page takes up its
 * cache a moment later, and a build of the model writes it, and either opens it. `title` is the
 * host's translation of "File does not exist", else the surrounding language's. */
export function MissingCadFile({ file, entry, reload, recheck, action, title, description }: {
  file: string; entry: CadEntry | null; reload?: () => void; action?: ReactNode; title?: string;
  /** Whether the document can be opened now, asked again while the screen is up. */
  recheck?: () => Promise<boolean>;
  /** What to say in place of the file's path: why a document named by its id is not held. */
  description?: string;
}) {
  const { t } = useI18n();
  const reloaded = useRef('');
  useEffect(() => {
    // Reopen only once the catalog confirms a file at this very path: a stale entry or another
    // file's late reply cannot do it.
    const identity = entry?.file === file ? `${file}:${entry.hash || ''}:${entry.bytes || 0}` : '';
    if (identity && reload && reloaded.current !== identity) {
      reloaded.current = identity;
      reload();
    }
  }, [file, entry, reload]);
  useEffect(() => {
    if (!recheck || !reload) return undefined;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = (attempt: number) => {
      timer = setTimeout(() => {
        void recheck().catch(() => false).then(known => {
          if (stopped) return;
          if (known) reload();
          else ask(attempt + 1);
        });
      }, RECHECK_MS[Math.min(attempt, RECHECK_MS.length - 1)]);
    };
    ask(0);
    return () => { stopped = true; clearTimeout(timer); };
  }, [file, recheck, reload]);
  return <EmptyState icon={FileX} title={title ?? t("file.missing")} description={description ?? file} tone="warn" action={action} />;
}
