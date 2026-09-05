import { Tooltip } from '@emdash/ui/react/primitives';
import { QueryClientProvider } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { GithubContextProvider } from '@core/features/github/api/browser/github-context-provider';
import { useLegacyPortStatus } from '@core/features/legacy-port/api/browser/useLegacyPort';
import { TerminalPoolProvider } from '@core/features/terminals/browser/pty/pty-pool-provider';
import { confirmOpenExternalLink } from '@core/features/workbench/api/browser/open-external-link';
import { Onboarding } from '@core/features/workbench/browser/onboarding/onboarding';
import { FramelessTitlebarOverlay } from '@core/features/workbench/browser/window-controls';
import { WorkspaceLayoutContextProvider } from '@core/features/workbench/contributions/browser/layout-provider';
import { ExternalLinkProvider } from '@core/primitives/external-links/browser';
import { queryClient } from '@core/primitives/query/browser/query-client';
import { HostRecoveryWakeups } from '@core/services/hosts/browser/recovery-wakeups';
import { reportAppQueriesSettled } from '@renderer/lib/boot/splash-gate';
import { AppMenuEvents } from './app/app-menu-events';
import { AppShutdownLifecycle } from './app/app-shutdown-lifecycle';
import { WelcomeScreen } from './app/welcome';
import { Workspace } from './app/workspace';
import { WorkspaceViewProvider } from './lib/layout/provider';
import { ModalRenderer } from './lib/modal/modal-renderer';
import { ThemeProvider } from './lib/providers/theme-provider';

export const HAS_SEEN_ONBOARDING = 'hardcore:has-seen-onboarding:v1';
const LEGACY_HAS_SEEN_ONBOARDING = 'emdash:has-seen-onboarding:v1';

function hasSeenOnboarding(): boolean {
  const seen =
    localStorage.getItem(HAS_SEEN_ONBOARDING) ?? localStorage.getItem(LEGACY_HAS_SEEN_ONBOARDING);
  if (seen === 'true') localStorage.setItem(HAS_SEEN_ONBOARDING, 'true');
  return seen === 'true';
}

type AppView = 'onboarding' | 'welcome' | 'workspace';

function AppContent() {
  const [view, setView] = useState<AppView>(() =>
    hasSeenOnboarding() ? 'workspace' : 'onboarding'
  );

  const { data: legacyStatus, isLoading } = useLegacyPortStatus();

  const queriesReported = useRef(false);
  useEffect(() => {
    if (isLoading || queriesReported.current) return;
    queriesReported.current = true;
    reportAppQueriesSettled();
  }, [isLoading]);

  // Freeze the import decision so a status refresh cannot unmount an import in progress.
  const [needsImport, setNeedsImport] = useState<boolean | null>(null);
  useEffect(() => {
    if (!isLoading && view === 'onboarding' && needsImport === null) {
      const shouldImport = Boolean(legacyStatus?.hasImportSources && !legacyStatus.portStatus);
      setNeedsImport(shouldImport);
      if (!shouldImport) {
        localStorage.setItem(HAS_SEEN_ONBOARDING, 'true');
        setView('welcome');
      }
    }
  }, [view, isLoading, needsImport, legacyStatus]);

  const handleOnboardingComplete = () => {
    localStorage.setItem(HAS_SEEN_ONBOARDING, 'true');
    setView('welcome');
  };

  const handleOpenSettingsFromMenu = useCallback(() => {
    if (view === 'onboarding' && needsImport) return false;
    setView('workspace');
    return true;
  }, [view, needsImport]);

  const renderContent = () => {
    // Linux runs frameless (`frame: false`), so every branch — including the
    // pre-resolution loading window — must mount the overlay to keep window
    // controls and a drag region available.
    if (isLoading || (view === 'onboarding' && needsImport === null)) {
      return <FramelessTitlebarOverlay />;
    }
    if (view === 'onboarding' && needsImport) {
      return (
        <>
          <Onboarding onComplete={handleOnboardingComplete} />
          <FramelessTitlebarOverlay />
        </>
      );
    }
    // The welcome splash is an opaque full-screen overlay, so the Workspace
    // would be fully hidden behind it; render it standalone to avoid mounting a
    // second, hidden WindowControls (the Workspace Titlebar's) underneath.
    if (view === 'welcome') {
      return (
        <>
          <WelcomeScreen onGetStarted={() => window.location.reload()} />
          <FramelessTitlebarOverlay />
        </>
      );
    }
    return <Workspace />;
  };

  return (
    <Tooltip.Provider delay={300}>
      <WorkspaceLayoutContextProvider>
        <TerminalPoolProvider>
          <GithubContextProvider>
            <WorkspaceViewProvider>
              <AppMenuEvents onOpenSettings={handleOpenSettingsFromMenu} />
              <ExternalLinkProvider openExternalLink={confirmOpenExternalLink}>
                <ThemeProvider>
                  <ModalRenderer />
                  <AppShutdownLifecycle />
                  <HostRecoveryWakeups />
                  {renderContent()}
                </ThemeProvider>
              </ExternalLinkProvider>
            </WorkspaceViewProvider>
          </GithubContextProvider>
        </TerminalPoolProvider>
      </WorkspaceLayoutContextProvider>
    </Tooltip.Provider>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
