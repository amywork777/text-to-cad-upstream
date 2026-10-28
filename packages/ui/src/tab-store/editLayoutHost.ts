/**
 * Whether the host lays out a part script's model itself. Studio's bar switches Simple view for
 * every view and sends the layout in its host context (`studio/editLayout`); the app that hosts the
 * viewer takes that layout, and the view shows no switch of its own (`xbf/edit/useXbfCadMode.jsx`). One
 * per page, as a page is one view.
 *
 * The host's switch shows and holds as the navbar's would, so the part on screen reports what the
 * navbar's switch hangs on (`editState`): whether its file has a part script, the two layouts
 * (`editable`), and whether a command, sketch or pick is open or a change is being saved, which
 * holds the layout until it is finished or cancelled (`busy`). No part on screen, nothing of either.
 * It counts too the builds the part saw end (`builds`, a CAD-mode change's or a part opened as its STEP built first), so
 * the host lists its parts anew (Studio's `modelsChanged`); the count only grows.
 *
 * The part on screen asks the other way too (`request`): a double-click on a face laid out for the AI
 * asks for the CAD layout, one on empty space in CAD for the AI's (`xbf/edit/editLayout.js`'s
 * `doubleClickLayout`). The app that hosts the viewer says how to ask its host (`setRequester`) where
 * the host takes the ask (Studio's `studio/request/edit-layout`); the layout then comes back in the
 * host context as ever.
 */
export interface EditState {
  readonly editable: boolean;
  readonly busy: boolean;
}

export type EditLayout = 'manual' | 'ai';

const NONE: EditState = Object.freeze({ editable: false, busy: false });

let hosted = false;
const listeners = new Set<() => void>();
let editState: EditState = NONE;
let builds = 0;
const editListeners = new Set<() => void>();
let requester: ((layout: EditLayout) => unknown) | null = null;

export const editLayoutHost = {
  get: (): boolean => hosted,
  set(next: boolean): void {
    if (hosted === next) return;
    hosted = next;
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  /** What the part on screen allows, as it last said. */
  editState: (): EditState => editState,
  /** The part on screen says what it allows; null as it leaves the screen. */
  reportEditState(next: EditState | null): void {
    const { editable, busy } = next ?? NONE;
    if (editState.editable === editable && editState.busy === busy) return;
    editState = Object.freeze({ editable, busy });
    for (const listener of editListeners) listener();
  },
  /** How many builds the parts on this page saw end, since it loaded. */
  builds: (): number => builds,
  /** A build the part on screen saw end: its listeners hear of it, as of a change of what it allows. */
  reportBuilt(): void {
    builds += 1;
    for (const listener of editListeners) listener();
  },
  subscribeEditState(listener: () => void): () => void {
    editListeners.add(listener);
    return () => {
      editListeners.delete(listener);
    };
  },
  /**
   * How to ask the host for a layout, while it takes the ask: the host's answer, a promise that
   * fails where it refuses. The returned function takes it back.
   */
  setRequester(next: (layout: EditLayout) => unknown): () => void {
    requester = next;
    return () => {
      if (requester === next) requester = null;
    };
  },
  /**
   * Asks the host for a layout: true when a host that takes the ask was asked, false where none
   * does. `refused` hears that the host said no (a command open in it) or could not be reached.
   */
  request(layout: EditLayout, { refused }: { readonly refused?: () => void } = {}): boolean {
    if (requester === null) return false;
    Promise.resolve(requester(layout)).catch(() => refused?.());
    return true;
  },
};
