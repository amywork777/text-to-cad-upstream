// Studio (studio-base): the ribbon icons a renderer hands the model tools (`useModelTools`'s `icons`), which CAD
// mode's ribbon wears (`ribbonIcon`, `xbf/edit/EditRibbon.jsx`).
import React, { useSyncExternalStore } from 'react';
import { createViewSettingsStore } from '../../../../../dist/renderers/kit/view-settings/viewSettingsStore.js';
import { cleanup, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useModelTools } from '../../../../../dist/renderers/kit/tools/model-effects/ModelTools.js';

beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// The strip's tiles, as FloatingToolBar draws a tool with a `tile`.
function Strip({ store, icons = null }: { store: ReturnType<typeof createViewSettingsStore>; icons?: Record<string, React.ReactNode> | null }) {
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const tools = useModelTools({ view: snapshot.scene.view, features: { settings: ['exploded', 'clip'] }, store,
    mesh: { bounds: { min: [0, 0, 0], max: [10, 10, 10] } }, disabled: false, icons });
  return <><div data-testid="model">model</div>{tools.tools.map(tool => <React.Fragment key={tool.id}>{tool.tile}</React.Fragment>)}</>;
}

it('keeps the kit\'s glyphs on its tiles, and hands the icons a renderer gives it to the ribbon', () => {
  const store = createViewSettingsStore();
  const icons = { exploded: <svg data-testid="cad-exploded" />, clip: <svg data-testid="cad-section" /> };
  const { rerender } = render(<Strip store={store} />);
  const glyph = (name: string) => screen.getByRole('button', { name, exact: true }).querySelector('[data-testid]')?.getAttribute('data-testid') ?? 'kit';
  expect([glyph('Explode'), glyph('Clip')]).toEqual(['kit', 'kit']);
  // The strip keeps plain glyphs; CAD mode's ribbon wears the renderer's (`ribbonIcon`, `EditRibbon.jsx`).
  rerender(<Strip store={store} icons={icons} />);
  expect([glyph('Explode'), glyph('Clip')]).toEqual(['kit', 'kit']);
  const ribbonIcons = (handed: typeof icons | null) => renderHook(() => useModelTools({ view: store.getSnapshot().scene.view, features: { settings: ['exploded', 'clip'] },
    store, mesh: { bounds: { min: [0, 0, 0], max: [10, 10, 10] } }, disabled: false, icons: handed }))
    .result.current.tools.map((tool: { ribbonIcon: React.ReactElement | null }) => tool.ribbonIcon?.props['data-testid'] ?? null);
  expect(ribbonIcons(icons)).toEqual(['cad-exploded', 'cad-section']);
  expect(ribbonIcons(null)).toEqual([null, null]);
});
