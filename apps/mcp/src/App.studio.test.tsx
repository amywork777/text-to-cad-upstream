// Studio's side of the host bridge (`host/studioHost.ts`), through the page as a Studio window shows it:
// the `studio/*` host-context keys and methods. The harness is App.test.tsx's.
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { CadViewerProps } from '@cad/ui/cad-viewer';
import { editLayoutHost, focusHost, gridHost, selectHost, workingHost } from '@cad/ui/tab-store';
import App from './App';
import type { HostContext } from './host/bridge';
import type { Launch } from './host/server';

// The page as a checkout builds it: its Vite config names the build (vite.config.mjs, build.test.ts).
vi.hoisted(() => { Object.assign(globalThis, { __CAD_BUILD__: 'b80844940' }); });

// The shared CAD viewer, reduced to what this page hands it: what it draws for each prompt
// destination and each page is its own suite's (packages/ui); what this page hands it is this one's.
const viewer = vi.hoisted(() => ({ props: null as CadViewerProps | null, mounts: 0 }));
vi.mock('@cad/ui/cad-viewer', async original => {
  const { useEffect } = await import('react');
  return {
    ...await original<object>(),
    // What the host hands the navbar, and its notice (the file handler's corner), drawn as the real viewer would.
    CadViewer: (props: CadViewerProps) => { viewer.props = props; useEffect(() => { viewer.mounts += 1; }, []); return <>{props.update ?? null}{props.fullSize ?? null}{props.notice ?? null}</>; },
  };
});

// The toasts a view says (the real viewer's Toaster draws them): what this page asks it to say.
vi.mock('sonner', async original => ({ ...await original<object>(), toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

beforeEach(() => vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); viewer.props = null; viewer.mounts = 0; });

const POLICY = 'https://www.texttocad.dev/privacy-policy';
type Answer = (body: any, url: URL) => unknown;
/** An answer with a status of its own (a route answers 200 otherwise). */
class Status { constructor(readonly status: number, readonly body: unknown) {} }

/**
 * A host frame and CAD's server, as the page reaches them: its sync, and the viewer's routes over
 * `cad_http`, answered here as the viewer answers them (`answers`, by path; a route without one, as
 * what the viewer reads for itself, never answers). `asked(path)` is what the page sent each: its
 * JSON body, or null for a read.
 */
function host(initial: HostContext, hostCapabilities: Record<string, unknown> = {}) {
  const listeners = new Set<(context: HostContext) => void>();
  let context = initial;
  const bridge = {
    get hostContext() { return context; }, hostCapabilities,
    notify: vi.fn(), request: vi.fn(async () => ({})), callTool: vi.fn(),
    onToolResult: () => () => {}, onTeardown: () => () => {},
    onHostContext(listener: (next: HostContext) => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    change(next: HostContext) { context = { ...context, ...next }; for (const listener of [...listeners]) listener(context); },
  };
  const answers: Record<string, Answer> = {
    // The person's settings: read (no body), or changed (`{telemetry}`, `{language}`, `{updates}`).
    '/api/v1/settings': body => ({ language: { locale: body?.language?.locale ?? null },
      telemetry: { share: Boolean(body?.telemetry?.share), policy: POLICY },
      updates: body?.updates ? { automatic: body.updates.automatic, reason: 'choice' } : { automatic: true, reason: 'default' } }),
    '/api/v1/server': () => ({ notice: null }),
    '/api/v1/documents': () => ({ documents: [] }),
    '/api/v1/local/reveal': () => null,
  };
  const requests: { path: string; body: any }[] = [];
  const server = {
    sync: () => new Promise(() => {}), reply: vi.fn(async () => ({})),
    http: vi.fn(async ({ url, body }: { url: string; body: string }) => {
      const target = new URL(url);
      const path = target.pathname;
      const sent = body ? JSON.parse(atob(body)) : null;
      requests.push({ path, body: sent });
      if (!answers[path]) return new Promise(() => {});
      const value = await answers[path](sent, target);
      if (value instanceof Status) return { status: value.status, headers: { 'content-type': 'application/json' }, body: btoa(JSON.stringify(value.body)) };
      return value === null ? { status: 204, headers: {}, body: '' }
        : { status: 200, headers: { 'content-type': 'application/json' }, body: btoa(JSON.stringify(value)) };
    }),
    answers,
    asked: (path: string) => requests.filter(request => request.path === path).map(request => request.body),
    /** The settings' reads (one, for the language, the consent, What's new and automatic updates), and the telemetry answers sent. */
    telemetry: () => requests.filter(request => request.path === '/api/v1/settings' && !request.body?.language && !request.body?.whats_new)
      .map(request => request.body && request.body.telemetry),
  };
  return { bridge, server };
}
// The home, as the server launches it: the library, with Open on a computer that has a chooser.
const home: Launch = { protocol: 9, page: 'home', model: null, pick: true };

it("a host that opens files beside the thread (Studio) moves between them itself: every view of it is bare (its tab names the file and holds its menu; the strip holds Display, Preview and the panel), with no home, Back or Forward, and opens another file in the host", async () => {
  const { bridge, server } = host({ displayMode: 'fullscreen' }, { openFiles: {} });
  const { container } = render(<App bridge={bridge as any} server={server as any} launch={{ protocol: 7, page: 'viewer', model: '/work/a.step' }} />);
  expect([viewer.props!.chrome, viewer.props!.history, viewer.props!.library]).toEqual(['bare', undefined, undefined]);
  // Its chat is a column beside the view, not a composer over it: the cube keeps the top-right, as SolidWorks has it.
  const frame = container.firstElementChild as HTMLElement;
  expect([frame.style.getPropertyValue('--cad-viewport-corner-left'), frame.style.getPropertyValue('--cad-host-bottom-inset')]).toEqual(['', '']);
  // The cube a chrome inset in from the right edge, and the strip and Quick Edit centred on the model's area past a panel.
  expect([frame.style.getPropertyValue('--cad-viewport-corner-right'), frame.hasAttribute('data-cad-centre-on-model')]).toEqual(['8px', true]);
  // A part opened from its assembly opens in a tab of the host's own.
  act(() => viewer.props!.openElsewhere!('/work/b.step'));
  expect(bridge.request).toHaveBeenCalledWith('studio/open-file', { path: '/work/b.step' });
  // A part opened as its STEP and shown by its built document asks for the swap in its own tab.
  act(() => viewer.props!.openElsewhere!('/work/doc', { replace: true }));
  expect(bridge.request).toHaveBeenCalledWith('studio/open-file', { path: '/work/doc', replace: true });
});

it('a host that lays the workspace out hears what the part on screen allows as it changes, until the view goes; a host that does not, nothing', () => {
  const said = (notify: ReturnType<typeof vi.fn>) => notify.mock.calls
    .filter(([method]) => method === 'studio/notifications/edit-state').map(([, params]) => params);
  try {
    const studio = host({ displayMode: 'fullscreen', 'studio/editLayout': 'manual' }, { studioEditState: {} });
    const { unmount } = render(<App bridge={studio.bridge as any} server={studio.server as any} launch={home} />);
    // The STEP view says what its part allows (`editLayoutHost`): a part script, then a command open, then the part gone.
    const builds = editLayoutHost.builds();
    act(() => editLayoutHost.reportEditState({ editable: true, busy: false }));
    act(() => editLayoutHost.reportEditState({ editable: true, busy: true }));
    // A build CAD mode saw end, for Studio to list the part anew.
    act(() => editLayoutHost.reportBuilt());
    act(() => editLayoutHost.reportEditState(null));
    expect(said(studio.bridge.notify)).toEqual([{ editable: false, busy: false, builds }, { editable: true, busy: false, builds },
      { editable: true, busy: true, builds }, { editable: true, busy: true, builds: builds + 1 }, { editable: false, busy: false, builds: builds + 1 }]);
    // A view closed says nothing more.
    unmount();
    act(() => editLayoutHost.reportEditState({ editable: true, busy: true }));
    expect(said(studio.bridge.notify)).toHaveLength(5);

    const plain = host({ displayMode: 'fullscreen' });
    render(<App bridge={plain.bridge as any} server={plain.server as any} launch={home} />);
    act(() => editLayoutHost.reportEditState({ editable: true, busy: false }));
    expect(said(plain.bridge.notify)).toEqual([]);
  } finally {
    editLayoutHost.reportEditState(null);
    editLayoutHost.set(false);
  }
});

it('a host that switches the layout at the view\'s ask hears it as studio/request/edit-layout, until the view goes; a host that does not is never asked', () => {
  const asked = (request: ReturnType<typeof vi.fn>) => request.mock.calls
    .filter(([method]) => method === 'studio/request/edit-layout').map(([, params]) => params);
  try {
    const studio = host({ displayMode: 'fullscreen', 'studio/editLayout': 'ai' }, { studioEditLayout: {} });
    const { unmount } = render(<App bridge={studio.bridge as any} server={studio.server as any} launch={home} />);
    expect(editLayoutHost.request('manual')).toBe(true);
    expect(asked(studio.bridge.request)).toEqual([{ layout: 'manual' }]);
    unmount();
    expect(editLayoutHost.request('ai')).toBe(false);

    const plain = host({ displayMode: 'fullscreen', 'studio/editLayout': 'ai' });
    render(<App bridge={plain.bridge as any} server={plain.server as any} launch={home} />);
    expect(editLayoutHost.request('manual')).toBe(false);
    expect(asked(plain.bridge.request)).toEqual([]);
  } finally {
    editLayoutHost.set(false);
  }
});

it('a host that opens a part at a line of its script hands the part on screen the place, and hears when it is taken and whether a feature was there; a host that does not, nothing', () => {
  const taken = (notify: ReturnType<typeof vi.fn>) => notify.mock.calls
    .filter(([method]) => method === 'studio/notifications/focus-taken').map(([, params]) => params);
  try {
    const studio = host({ displayMode: 'fullscreen', 'studio/focus': { path: 'parts/bracket.py', line: 12, nonce: 3 } }, { studioFocus: {} });
    const { unmount } = render(<App bridge={studio.bridge as any} server={studio.server as any} launch={home} />);
    expect(focusHost.get()).toEqual({ path: 'parts/bracket.py', line: 12, nonce: 3 });
    // The STEP view takes it (`focusHost`), no feature holding the line, for the host to open the script there; the host lets it go.
    act(() => focusHost.take(3, false));
    expect(taken(studio.bridge.notify)).toEqual([{ nonce: 3, found: false }]);
    act(() => studio.bridge.change({ 'studio/focus': null }));
    expect(focusHost.get()).toBeNull();
    // A view closed says nothing more.
    unmount();
    act(() => focusHost.take(4, true));
    expect(taken(studio.bridge.notify)).toHaveLength(1);

    const plain = host({ displayMode: 'fullscreen' });
    render(<App bridge={plain.bridge as any} server={plain.server as any} launch={home} />);
    act(() => focusHost.take(5, true));
    expect(taken(plain.bridge.notify)).toEqual([]);
  } finally {
    focusHost.set(null);
  }
});

it("a host whose agent is working says so to the view, and a host that asks for a message's picks again hears what the part on screen found; a host that does not, nothing", () => {
  const taken = (notify: ReturnType<typeof vi.fn>) => notify.mock.calls
    .filter(([method]) => method === 'studio/notifications/select-taken').map(([, params]) => params);
  try {
    const studio = host({ displayMode: 'fullscreen', 'studio/working': { working: true },
      'studio/select': { references: ['91fe49be#part/face 1', 'part.step#arm'], nonce: 7 } }, { studioSelect: {} });
    const { unmount } = render(<App bridge={studio.bridge as any} server={studio.server as any} launch={home} />);
    expect([workingHost.get(), selectHost.get()]).toEqual([true, { references: ['91fe49be#part/face 1', 'part.step#arm'], nonce: 7 }]);
    // The part on screen selects one, the other no longer in it.
    act(() => selectHost.take(7, 1, 1));
    expect(taken(studio.bridge.notify)).toEqual([{ nonce: 7, found: 1, missing: 1 }]);
    act(() => studio.bridge.change({ 'studio/working': { working: false }, 'studio/select': null }));
    expect([workingHost.get(), selectHost.get()]).toEqual([false, null]);
    unmount();
    act(() => selectHost.take(8, 1, 0));
    expect(taken(studio.bridge.notify)).toHaveLength(1);

    const plain = host({ displayMode: 'fullscreen' });
    render(<App bridge={plain.bridge as any} server={plain.server as any} launch={home} />);
    act(() => selectHost.take(9, 1, 0));
    expect(taken(plain.bridge.notify)).toEqual([]);
  } finally {
    selectHost.set(null);
    workingHost.set(null);
  }
});

it("a host that sets Show grid's default hands it to every 3D view, as it changes; a host that does not leaves it off", () => {
  try {
    const studio = host({ displayMode: 'fullscreen', 'studio/gridDefault': true });
    const { unmount } = render(<App bridge={studio.bridge as any} server={studio.server as any} launch={home} />);
    expect(gridHost.get()).toBe(true);
    act(() => studio.bridge.change({ 'studio/gridDefault': false }));
    expect(gridHost.get()).toBe(false);
    unmount();

    const plain = host({ displayMode: 'fullscreen' });
    render(<App bridge={plain.bridge as any} server={plain.server as any} launch={home} />);
    expect(gridHost.get()).toBe(false);
  } finally {
    gridHost.set(null);
  }
});
