import { action, makeObservable, observable, runInAction } from 'mobx';
import { browserControlsRegistry } from '@core/features/browser/api/browser/browser-controls-registry';
import { browserSessionStore } from '@core/features/browser/api/browser/browser-session-store';
import { BrowserTabResource } from '@core/features/browser/api/browser/browser-tab-resource';
import { getBrowserClient } from '@core/features/browser/api/browser/client';
import type { EngineeringWorkspaceMode } from '@core/features/cad/api/browser/cad-engineering-object';
import type { CadSourceHistory } from '@core/features/cad/api/cad-source-history';
import type {
  TabEntry,
  TabHandle,
  TabResource,
} from '@core/primitives/workbench-shell/browser/tabs/core/tab-provider';
import type { CadState } from '../../browser/cad-tab-provider';
import {
  buildCadViewerConsumeParameterCommandScript,
  buildCadViewerConsumeReferenceCommandScript,
  buildCadViewerFeatureHistoryScript,
  buildCadViewerFeatureHistoryReadyScript,
  buildCadViewerIntegrationScript,
  buildCadViewerToolbarActionScript,
  cadViewerHostThemeSignature,
  readCadViewerHostTheme,
  type CadViewerParameterCommand,
  type CadViewerReferenceCommand,
} from '../../browser/cad-viewer-integration';

export type CadViewerStatus = 'starting' | 'ready' | 'error';

const VIEWER_FILE_SHEET_BUTTON =
  'button[aria-pressed][aria-label^="Expand "], button[aria-pressed][aria-label^="Collapse "]';
const STEP_RESOURCE_RE = /\.(?:step|stp)(?:\.py)?$/i;
const PYTHON_SOURCE_RE = /\.py$/i;

export function shouldSyncCadViewerFeatureHistory(path: string): boolean {
  return STEP_RESOURCE_RE.test(path) || PYTHON_SOURCE_RE.test(path);
}

const READ_VIEWER_TREE_STATE = `(() => {
  const button = document.querySelector(${JSON.stringify(VIEWER_FILE_SHEET_BUTTON)});
  if (!(button instanceof HTMLButtonElement)) return null;
  return button.getAttribute('aria-pressed') === 'true';
})()`;

function setViewerTreeStateScript(open: boolean): string {
  return `(() => {
    const selector = ${JSON.stringify(VIEWER_FILE_SHEET_BUTTON)};
    const button = document.querySelector(selector);
    if (!(button instanceof HTMLButtonElement)) return null;
    const current = button.getAttribute('aria-pressed') === 'true';
    if (current !== ${JSON.stringify(open)}) button.click();
    return new Promise((resolve) => requestAnimationFrame(() => {
      const nextButton = document.querySelector(selector);
      resolve(nextButton instanceof HTMLButtonElement
        ? nextButton.getAttribute('aria-pressed') === 'true'
        : null);
    }));
  })()`;
}

function asViewerParameterCommand(value: unknown): CadViewerParameterCommand | null {
  if (!value || typeof value !== 'object') return null;
  const command = value as Record<string, unknown>;
  if (typeof command.requestId !== 'string' || typeof command.sourceHash !== 'string') return null;
  if (!command.values || typeof command.values !== 'object') return null;
  const values = Object.entries(command.values as Record<string, unknown>);
  if (values.length === 0 || values.some(([, number]) => !Number.isFinite(number))) return null;
  return {
    requestId: command.requestId,
    sourceHash: command.sourceHash,
    values: Object.fromEntries(values) as Record<string, number>,
  };
}

function asViewerReferenceCommand(value: unknown): CadViewerReferenceCommand | null {
  if (!value || typeof value !== 'object') return null;
  const command = value as Record<string, unknown>;
  if (typeof command.requestId !== 'string' || typeof command.reference !== 'string') return null;
  const reference = command.reference.trim();
  return reference.includes('#') ? { requestId: command.requestId, reference } : null;
}

function geometryOnlyHistory(message: string): CadSourceHistory {
  return { groups: [], parameters: [], diagnostics: [message] };
}

function explainMissingParameters(history: CadSourceHistory): CadSourceHistory {
  if (history.parameters.length > 0) return history;
  return {
    ...history,
    diagnostics: [
      ...history.diagnostics,
      'No safely editable dimensions were found in the linked source. Ask the agent to expose a dimension to add it to Sliders.',
    ],
  };
}

export class CadTabResource implements TabResource {
  status: CadViewerStatus = 'starting';
  error: string | null = null;
  chatOpen: boolean;
  workspaceMode: EngineeringWorkspaceMode;
  drawingCreating = false;
  captureRequest = 0;
  viewerTreeOpen: boolean | null = null;
  private readonly browserResource: BrowserTabResource;
  private requestId = 0;
  private disposed = false;
  private viewerIntegrationSignature = '';
  private viewerFeatureHistorySignature = '';
  private viewerFeatureHistorySourcePath: string | null | undefined;
  private viewerFeatureHistorySyncing = false;

  constructor(
    private readonly entry: TabEntry<CadState>,
    handle: TabHandle
  ) {
    this.chatOpen = entry.state.chatOpen !== false;
    this.workspaceMode = entry.state.workspaceMode ?? '3d';
    makeObservable(this, {
      status: observable,
      error: observable,
      chatOpen: observable,
      workspaceMode: observable,
      drawingCreating: observable,
      captureRequest: observable,
      viewerTreeOpen: observable,
      retry: action.bound,
      setChatOpen: action.bound,
      setWorkspaceMode: action.bound,
      setDrawingCreating: action.bound,
      requestCaptureForChat: action.bound,
    });
    this.browserResource = new BrowserTabResource(entry, handle);
    void this.start();
  }

  get browserId(): string {
    return this.entry.state.browserId;
  }

  get path(): string {
    return this.entry.state.path;
  }

  get workspacePath(): string {
    return this.entry.state.workspacePath;
  }

  refreshViewer = (): void => {
    this.viewerFeatureHistorySignature = '';
    this.viewerFeatureHistorySourcePath = undefined;
    browserControlsRegistry.get(this.browserId)?.adapter?.reloadIgnoringCache();
  };

  setChatOpen(open: boolean): void {
    this.chatOpen = open;
    this.entry.state.chatOpen = open;
  }

  setWorkspaceMode(mode: EngineeringWorkspaceMode): void {
    this.workspaceMode = mode;
    this.entry.state.workspaceMode = mode;
  }

  setDrawingCreating(creating: boolean): void {
    this.drawingCreating = creating;
  }

  requestCaptureForChat(): void {
    this.setChatOpen(true);
    const revealDelay = this.workspaceMode === '3d' ? 0 : 450;
    this.setWorkspaceMode('3d');
    window.setTimeout(() => {
      if (this.disposed) return;
      runInAction(() => {
        this.captureRequest += 1;
      });
    }, revealDelay);
  }

  toggleViewerAnnotation = async (): Promise<boolean> => {
    const revealDelay = this.workspaceMode === '3d' ? 0 : 450;
    this.setWorkspaceMode('3d');
    if (revealDelay > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, revealDelay));
    }
    const adapter = browserControlsRegistry.get(this.browserId)?.adapter;
    if (!adapter) return false;
    try {
      return (await adapter.executeJavaScript(buildCadViewerToolbarActionScript('Draw'))) === true;
    } catch {
      return false;
    }
  };

  syncViewerTreeState = (): void => {
    const adapter = browserControlsRegistry.get(this.browserId)?.adapter;
    if (!adapter) return;
    void adapter
      .executeJavaScript(READ_VIEWER_TREE_STATE)
      .then((open) => {
        if (this.disposed || typeof open !== 'boolean') return;
        runInAction(() => {
          this.viewerTreeOpen = open;
        });
      })
      .catch(() => {});
  };

  setViewerTreeOpen = (open: boolean): void => {
    const adapter = browserControlsRegistry.get(this.browserId)?.adapter;
    if (!adapter) return;
    void adapter
      .executeJavaScript(setViewerTreeStateScript(open))
      .then((nextOpen) => {
        if (this.disposed || typeof nextOpen !== 'boolean') return;
        runInAction(() => {
          this.viewerTreeOpen = nextOpen;
        });
      })
      .catch(() => {});
  };

  syncViewerIntegration = (force = false): void => {
    const adapter = browserControlsRegistry.get(this.browserId)?.adapter;
    if (!adapter) return;
    const theme = readCadViewerHostTheme();
    const signature = cadViewerHostThemeSignature(theme);
    if (!force && signature === this.viewerIntegrationSignature) return;
    this.viewerIntegrationSignature = signature;
    void adapter.executeJavaScript(buildCadViewerIntegrationScript(theme)).catch(() => {
      if (this.viewerIntegrationSignature === signature) this.viewerIntegrationSignature = '';
    });
  };

  syncViewerFeatureHistory = async (
    force = false,
    sourcePath: string | null = PYTHON_SOURCE_RE.test(this.path) ? this.path : null
  ): Promise<void> => {
    if (!shouldSyncCadViewerFeatureHistory(this.path)) return;
    const historySourcePath = sourcePath && PYTHON_SOURCE_RE.test(sourcePath) ? sourcePath : null;
    if (this.viewerFeatureHistorySyncing) return;
    const adapter = browserControlsRegistry.get(this.browserId)?.adapter;
    if (!adapter) return;
    this.viewerFeatureHistorySyncing = true;
    const requestId = this.requestId;
    try {
      if (
        !force &&
        this.viewerFeatureHistorySourcePath === historySourcePath &&
        this.viewerFeatureHistorySignature
      ) {
        const ready = await adapter.executeJavaScript(
          buildCadViewerFeatureHistoryReadyScript(this.viewerFeatureHistorySignature)
        );
        if (ready === true) return;
      }
      let history: CadSourceHistory;
      let signature: string;
      if (historySourcePath) {
        const result = await (
          await getBrowserClient()
        ).readCadModelHistory({
          workspacePath: this.workspacePath,
          filePath: historySourcePath,
        });
        if (this.disposed || requestId !== this.requestId) return;
        if (result.success) {
          history = explainMissingParameters(result.history);
          signature = result.sourceHash;
        } else {
          history = geometryOnlyHistory(
            'The linked design source could not be read. Geometry still shows the exact STEP topology.'
          );
          signature = `source-unavailable:${historySourcePath}:${result.error}`;
        }
      } else {
        history = geometryOnlyHistory(
          'This imported STEP has geometry but no linked editable construction source. Ask the agent to expose dimensions; Geometry remains the exact STEP topology.'
        );
        signature = `geometry-only:${this.path}`;
      }
      const injected = await adapter.executeJavaScript(
        buildCadViewerFeatureHistoryScript(history, signature)
      );
      if (this.disposed || requestId !== this.requestId || injected !== true) return;
      this.viewerFeatureHistorySourcePath = historySourcePath;
      this.viewerFeatureHistorySignature = signature;
    } catch {
      // The viewer panel can mount after DOM ready; the workspace sync retries until it exists.
    } finally {
      this.viewerFeatureHistorySyncing = false;
    }
  };

  consumeViewerParameterCommand = async (): Promise<CadViewerParameterCommand | null> => {
    const adapter = browserControlsRegistry.get(this.browserId)?.adapter;
    if (!adapter) return null;
    try {
      return asViewerParameterCommand(
        await adapter.executeJavaScript(buildCadViewerConsumeParameterCommandScript())
      );
    } catch {
      return null;
    }
  };

  consumeViewerReferenceCommand = async (): Promise<CadViewerReferenceCommand | null> => {
    const adapter = browserControlsRegistry.get(this.browserId)?.adapter;
    if (!adapter) return null;
    try {
      return asViewerReferenceCommand(
        await adapter.executeJavaScript(buildCadViewerConsumeReferenceCommandScript())
      );
    } catch {
      return null;
    }
  };

  handleViewerDomReady = (): void => {
    this.viewerIntegrationSignature = '';
    this.viewerFeatureHistorySignature = '';
    this.syncViewerIntegration(true);
    this.syncViewerTreeState();
    void this.syncViewerFeatureHistory(true);
  };

  retry(): void {
    this.status = 'starting';
    this.error = null;
    void this.start();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.requestId += 1;
    this.browserResource.dispose();
  }

  private async start(): Promise<void> {
    const requestId = ++this.requestId;
    const result = await getBrowserClient().then((client) =>
      client.ensureCadViewer({
        workspacePath: this.entry.state.workspacePath,
        filePath: this.entry.state.path,
      })
    );
    if (this.disposed || requestId !== this.requestId) return;
    if (!result.success) {
      runInAction(() => {
        this.status = 'error';
        this.error = result.error;
      });
      return;
    }
    browserSessionStore.updateSession(this.browserId, {
      currentUrl: result.url,
      isLoading: true,
      loadError: null,
    });
    runInAction(() => {
      this.status = 'ready';
      this.error = null;
      this.viewerTreeOpen = null;
    });
    this.viewerIntegrationSignature = '';
  }
}
