import { defineContract, eventStream, procedure } from '@emdash/wire/rpc';
import { z } from 'zod';
import type { CadSourceHistory } from '@core/features/cad/api/cad-source-history';
import type {
  BrowserDataClearKind,
  BrowserEvent,
  BrowsingDataKind,
} from '@core/primitives/browser/api';

type BrowserActionResult = { success: boolean; error?: string };

export type CadValidationResult =
  | {
      success: true;
      artifact: {
        revisionId: string;
        modelPath: string;
        modelHash: string;
        sourcePath?: string;
        sourceHash?: string;
      };
      facts: {
        occurrenceCount?: number;
        faceCount?: number;
        size?: [number, number, number];
      };
      validation: Record<string, unknown>;
    }
  | { success: false; error: string };

export type CadSourceHistoryResult =
  | { success: true; sourceHash: string; history: CadSourceHistory }
  | { success: false; error: string };

export type CadParameterApplyResult =
  | { success: true; sourceHash: string; appliedValues: Record<string, number> }
  | { success: false; error: string; conflict?: boolean };

export type CadDrawingResult =
  | {
      success: true;
      revisionId: string;
      drawing: {
        svgPath: string;
        pdfPath: string;
        dxfPath: string;
        manifestPath: string;
      };
    }
  | { success: false; error: string };

export type CadMigrationResult =
  | {
      success: true;
      sourcePath: string;
      modelPath: string;
      openPath: string;
    }
  | { success: false; error: string };

export type CadRuntimeStatus = {
  state: 'idle' | 'installing' | 'ready' | 'error';
  packageName: 'cad@text-to-cad';
  message: string;
  updatedAt: string | null;
};

export const browserDomain = 'browser' as const;

export const browserContract = defineContract({
  registerSession: procedure({
    input: z.object({ browserId: z.string(), partition: z.string() }),
    output: z.custom<BrowserActionResult>(),
  }),
  unregisterSession: procedure({
    input: z.object({ browserId: z.string() }),
    output: z.custom<BrowserActionResult>(),
  }),
  releaseWebContents: procedure({
    input: z.object({ browserId: z.string() }),
    output: z.custom<BrowserActionResult>(),
  }),
  bindWebContents: procedure({
    input: z.object({ browserId: z.string(), webContentsId: z.number() }),
    output: z.custom<BrowserActionResult>(),
  }),
  setActiveBrowser: procedure({
    input: z.object({ browserId: z.string().nullable() }),
    output: z.custom<BrowserActionResult>(),
  }),
  getActiveBrowser: procedure({
    input: z.void(),
    output: z.object({ browserId: z.string().nullable() }),
  }),
  ensureCadViewer: procedure({
    input: z.object({ workspacePath: z.string(), filePath: z.string() }),
    output: z.custom<{ success: true; url: string } | { success: false; error: string }>(),
  }),
  getCadRuntimeStatus: procedure({
    input: z.void(),
    output: z.custom<CadRuntimeStatus>(),
  }),
  repairCadRuntime: procedure({
    input: z.void(),
    output: z.custom<CadRuntimeStatus>(),
  }),
  validateCadModel: procedure({
    input: z.object({
      workspacePath: z.string(),
      filePath: z.string(),
      sourcePath: z.string().optional(),
    }),
    output: z.custom<CadValidationResult>(),
  }),
  rebuildCadModel: procedure({
    input: z.object({ workspacePath: z.string(), filePath: z.string() }),
    output: z.custom<CadValidationResult>(),
  }),
  readCadModelHistory: procedure({
    input: z.object({ workspacePath: z.string(), filePath: z.string() }),
    output: z.custom<CadSourceHistoryResult>(),
  }),
  applyCadModelParameters: procedure({
    input: z.object({
      workspacePath: z.string(),
      filePath: z.string(),
      expectedSourceHash: z.string(),
      values: z.record(z.string(), z.number()),
    }),
    output: z.custom<CadParameterApplyResult>(),
  }),
  migrateLegacyCadModel: procedure({
    input: z.object({ workspacePath: z.string(), filePath: z.string() }),
    output: z.custom<CadMigrationResult>(),
  }),
  createCadDrawing: procedure({
    input: z.object({ workspacePath: z.string(), filePath: z.string() }),
    output: z.custom<CadDrawingResult>(),
  }),
  openDevTools: procedure({
    input: z.object({ browserId: z.string() }),
    output: z.custom<BrowserActionResult>(),
  }),
  captureScreenshot: procedure({
    input: z.object({ browserId: z.string() }),
    output: z.custom<BrowserActionResult>(),
  }),
  captureScreenshotForChat: procedure({
    input: z.object({ browserId: z.string() }),
    output: z.custom<BrowserScreenshotResult>(),
  }),
  clearData: procedure({
    input: z.object({ browserId: z.string(), kind: z.custom<BrowserDataClearKind>() }),
    output: z.custom<BrowserActionResult>(),
  }),
  clearProfileStorage: procedure({
    input: z.object({ profileId: z.string() }),
    output: z.custom<BrowserActionResult>(),
  }),
  clearBrowsingData: procedure({
    input: z.object({ kind: z.custom<BrowsingDataKind>() }),
    output: z.custom<BrowserActionResult>(),
  }),
  events: eventStream({ key: z.void(), event: z.custom<BrowserEvent>() }),
});
export type BrowserScreenshotResult =
  | { success: true; dataUrl: string }
  | { success: false; error?: string };
