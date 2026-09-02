import { useCallback, useEffect, useState } from 'react';
import type { CadRuntimeStatus } from '@core/features/browser/api';
import { getBrowserClient } from '@core/features/browser/api/browser/client';

const INITIAL_STATUS: CadRuntimeStatus = {
  state: 'idle',
  packageName: 'cad@text-to-cad',
  message: 'CAD setup requires Python 3.11 or newer and will verify it before installing.',
  updatedAt: null,
};

export function useCadRuntimeStatus() {
  const [status, setStatus] = useState<CadRuntimeStatus>(INITIAL_STATUS);

  const ensureStatus = useCallback(async () => {
    const client = await getBrowserClient();
    const current = await client.getCadRuntimeStatus(undefined);
    return current.state === 'idle' ? client.repairCadRuntime(undefined) : current;
  }, []);

  const repair = useCallback(async () => {
    setStatus((current) => ({
      ...current,
      state: 'installing',
      message: 'Preparing the built-in CAD skills…',
    }));
    const client = await getBrowserClient();
    setStatus(await client.repairCadRuntime(undefined));
  }, []);

  useEffect(() => {
    let disposed = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const next = await ensureStatus();
        if (disposed) return;
        setStatus(next);
        if (next.state === 'idle' || next.state === 'installing') {
          timeout = setTimeout(() => void poll(), 1_000);
        }
      } catch {
        if (!disposed) timeout = setTimeout(() => void poll(), 2_000);
      }
    };

    void poll();
    return () => {
      disposed = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [ensureStatus]);

  return { status, repair };
}
