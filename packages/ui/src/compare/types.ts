/** What Compare's view is handed: the two STEP files, by absolute path, and how to read them. */
export interface StepCompareProps {
  /** The earlier revision, by its absolute path. */
  before: string;
  /** The later revision, by its absolute path. */
  after: string;
  /** A file's own bytes, by its absolute path: the host's (`CadWorkspaceService.fileBytes`). */
  readFile(path: string, options: { signal: AbortSignal }): Promise<Uint8Array>;
  /** Before becomes after, and after before. */
  onSwap(): void;
  onClose(): void;
}
