// Studio's side of the host bridge (studio-base, not Jake's text-to-cad): what a Studio window asks
// of a CAD view and hears from it, over the `studio/*` methods and host-context keys. Jake's files
// call it from one place each: `App.tsx` (`useStudioHost`) and `ModelView.tsx` (`useStudioFiles`).
import { useEffect, useMemo } from 'react';
import { editLayoutHost, focusHost, type TabStore } from '@cad/ui/tab-store';
import type { Bridge, HostContext } from './bridge';

/** The view's bridging of Studio's workspace: its layout, what the part on screen allows, and a script line to select. */
export function useStudioHost(bridge: Bridge, context: HostContext, tabStore: TabStore): void {
  // A host that lays its workspace out (Studio's Simple view, `studio/editLayout`) sets how a part
  // script's model opens, and the navbar leaves the switch to it.
  const hostLayout = (context as Record<string, unknown>)['studio/editLayout'];
  useEffect(() => {
    if (hostLayout !== 'ai' && hostLayout !== 'manual') return;
    editLayoutHost.set(true);
    tabStore.settings.update({ editLayout: hostLayout });
  }, [hostLayout, tabStore]);
  // Its switch shows and holds as the navbar's would: the host that asks for it (`studioEditState`)
  // hears what the part on screen allows, now and at each change (`editLayoutHost`), and how many
  // builds CAD mode saw end, to list the parts they built.
  useEffect(() => {
    if (!bridge.hostCapabilities.studioEditState) return undefined;
    const send = () => bridge.notify('studio/notifications/edit-state', { ...editLayoutHost.editState(), builds: editLayoutHost.builds() });
    send();
    return editLayoutHost.subscribeEditState(send);
  }, [bridge]);
  // The part on screen asks the host that takes it (`studioEditLayout`) for a layout: a double-click on a face laid out
  // for the AI steps into CAD, one on empty space in CAD goes back. The layout comes back in the host context, above.
  useEffect(() => {
    if (!bridge.hostCapabilities.studioEditLayout) return undefined;
    return editLayoutHost.setRequester(layout => bridge.request('studio/request/edit-layout', { layout }));
  }, [bridge]);
  // A host that opens a part at a line of its script (Studio's References, `studio/focus`) has the part on screen select
  // the feature there (`focusHost`), and the host that asks to (`studioFocus`) hears when the view has taken it, and
  // whether a feature held the line.
  const hostFocus = (context as Record<string, unknown>)['studio/focus'];
  useEffect(() => { focusHost.set(hostFocus); }, [hostFocus]);
  useEffect(() => {
    if (!bridge.hostCapabilities.studioFocus) return undefined;
    return focusHost.subscribeTaken(({ nonce, found }) => bridge.notify('studio/notifications/focus-taken', { nonce, found }));
  }, [bridge]);
}

/**
 * A host that opens files beside the thread itself (`openFiles`: Studio). Its file list and tabs are how a
 * person moves between files, and its tab names the file, so every view of it is bare, as Codex's file
 * handler's is (`ownNavigation`), with the agent's shows still shown; and it opens another file in a tab of
 * its own, from any of its views (`openElsewhere`): a part opened from its assembly.
 */
export function useStudioFiles(bridge: Bridge): { ownNavigation: boolean; openElsewhere: ((path: string) => void) | undefined } {
  const ownNavigation = Boolean(bridge.hostCapabilities.openFiles);
  const openElsewhere = useMemo(() => (ownNavigation
    ? (path: string) => void bridge.request('studio/open-file', { path }).catch(() => {}) : undefined), [ownNavigation, bridge]);
  return { ownNavigation, openElsewhere };
}
