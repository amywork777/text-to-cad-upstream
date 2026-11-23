/**
 * Studio (studio-base): whether the host's agent is changing the project the view shows (`studio/working` in
 * the host context: `{ working: true }` while a turn runs, anything else when none does). The view says so over
 * the model in plain words (`kit/shell/StudioWorkingNote.jsx`) and, on the first rebuild after, lights the
 * bodies that changed once (`renderers/xbf/useChangedBodies.js`). One per page, as a page is one view.
 */
let working = false;
// Counts the turns the view has heard start: a rebuild after a turn began flashes what changed, once.
let turns = 0;
const listeners = new Set<() => void>();

/** What the host's context says: a turn runs only for `{ working: true }`. */
function read(value: unknown): boolean {
  return typeof value === 'object' && value !== null && (value as Record<string, unknown>).working === true;
}

export const workingHost = {
  /** Whether a turn runs now. */
  get: (): boolean => working,
  /** How many turns have started since the page opened. */
  turns: (): number => turns,
  /** The host's context says whether a turn runs. */
  set(next: unknown): void {
    const value = read(next);
    if (value === working) return;
    working = value;
    if (value) turns += 1;
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
