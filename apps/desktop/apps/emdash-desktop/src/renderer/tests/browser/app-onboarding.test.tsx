import type { ReactNode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App, HAS_SEEN_ONBOARDING } from '@renderer/App';

const state = vi.hoisted(() => ({
  legacy: {
    data: { hasImportSources: false, portStatus: null as string | null },
    isLoading: false,
  },
  settled: vi.fn(),
}));

// Keep the real App routing and import shell; isolate unrelated workspace services.
vi.mock('@emdash/ui/react/primitives', () => ({
  Tooltip: { Provider: ({ children }: { children: ReactNode }) => children },
}));
vi.mock('@core/features/legacy-port/api/browser/useLegacyPort', () => ({
  useLegacyPortStatus: () => state.legacy,
}));
vi.mock('@core/features/workbench/browser/onboarding/import-step', () => ({
  ImportStep: ({ onComplete }: { onComplete: () => void }) => (
    <button onClick={onComplete}>Finish import</button>
  ),
}));
vi.mock('@core/features/github/api/browser/github-context-provider', () => ({
  GithubContextProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@core/features/terminals/browser/pty/pty-pool-provider', () => ({
  TerminalPoolProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@core/features/workbench/contributions/browser/layout-provider', () => ({
  WorkspaceLayoutContextProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@core/primitives/external-links/browser', () => ({
  ExternalLinkProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@renderer/lib/layout/provider', () => ({
  WorkspaceViewProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@renderer/lib/providers/theme-provider', () => ({
  ThemeProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@core/features/workbench/api/browser/open-external-link', () => ({
  confirmOpenExternalLink: vi.fn(),
}));
vi.mock('@core/features/workbench/browser/window-controls', () => ({
  FramelessTitlebarOverlay: () => <div>Window controls</div>,
}));
vi.mock('@core/services/hosts/browser/recovery-wakeups', () => ({
  HostRecoveryWakeups: () => null,
}));
vi.mock('@renderer/app/app-menu-events', () => ({ AppMenuEvents: () => null }));
vi.mock('@renderer/app/app-shutdown-lifecycle', () => ({ AppShutdownLifecycle: () => null }));
vi.mock('@renderer/lib/modal/modal-renderer', () => ({ ModalRenderer: () => null }));
vi.mock('@renderer/lib/boot/splash-gate', () => ({ reportAppQueriesSettled: state.settled }));
vi.mock('@renderer/app/welcome', () => ({ WelcomeScreen: () => <div>Welcome to Hardcore</div> }));
vi.mock('@renderer/app/workspace', () => ({ Workspace: () => <div>CAD workspace</div> }));

describe('App onboarding without a hosted account', () => {
  let host: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (
      globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.removeItem(HAS_SEEN_ONBOARDING);
    localStorage.removeItem('emdash:has-seen-onboarding:v1');
    state.legacy = { data: { hasImportSources: false, portStatus: null }, isLoading: false };
    state.settled.mockClear();
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    localStorage.removeItem(HAS_SEEN_ONBOARDING);
    localStorage.removeItem('emdash:has-seen-onboarding:v1');
  });

  const render = async () => act(async () => root.render(<App />));

  it('waits for import discovery, then welcomes a fresh user without sign-in', async () => {
    state.legacy.isLoading = true;
    await render();
    expect(host.textContent).toBe('Window controls');
    expect(state.settled).not.toHaveBeenCalled();
    state.legacy.isLoading = false;
    await render();
    expect(host.textContent).toContain('Welcome to Hardcore');
    expect(host.textContent).not.toContain('Sign in');
    expect(localStorage.getItem(HAS_SEEN_ONBOARDING)).toBe('true');
    expect(state.settled).toHaveBeenCalledTimes(1);
  });

  it('keeps import mounted through status refresh until the user completes it', async () => {
    state.legacy.data.hasImportSources = true;
    await render();
    expect(host.textContent).toContain('Finish import');
    expect(localStorage.getItem(HAS_SEEN_ONBOARDING)).toBeNull();
    state.legacy.data = { hasImportSources: false, portStatus: 'completed' };
    await render();
    expect(host.textContent).toContain('Finish import');
    await act(async () => host.querySelector('button')!.click());
    expect(host.textContent).toContain('Welcome to Hardcore');
    expect(localStorage.getItem(HAS_SEEN_ONBOARDING)).toBe('true');
  });

  it('opens the workspace for returning users with the legacy onboarding marker', async () => {
    localStorage.setItem('emdash:has-seen-onboarding:v1', 'true');
    await render();
    expect(host.textContent).toBe('CAD workspace');
    expect(localStorage.getItem(HAS_SEEN_ONBOARDING)).toBe('true');
  });
});
