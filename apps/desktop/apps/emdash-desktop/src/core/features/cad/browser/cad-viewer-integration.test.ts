import { JSDOM } from 'jsdom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseCadSourceHistory } from '../api/cad-source-history';
import {
  buildCadDesignTree,
  buildCadViewerConsumeParameterCommandScript,
  buildCadViewerConsumeReferenceCommandScript,
  buildCadViewerFeatureHistoryScript,
  buildCadViewerFeatureHistoryReadyScript,
  buildCadViewerIntegrationScript,
  buildCadViewerToolbarActionScript,
  cadViewerHostThemeSignature,
  readCadViewerHostTheme,
  type CadViewerHostTheme,
} from './cad-viewer-integration';

const theme: CadViewerHostTheme = {
  background: '#f2f2f2',
  panel: '#fcfcfc',
  control: '#fcfcfc',
  accent: '#dddddd',
  border: '#d0d0d0',
  foreground: '#222222',
  mutedForeground: '#626262',
  info: '#3b82f6',
  dark: false,
  scene: '#f2f2f2',
  sceneGrid: '#d5d5d5',
  radiusXs: '4px',
  radiusSm: '6px',
  radiusMd: '8px',
  radiusLg: '10px',
  radiusXl: '14px',
  radiusFull: '9999px',
  textMicro: '10px',
  textTiny: '11px',
};

afterEach(() => vi.unstubAllGlobals());

describe('CAD viewer integration', () => {
  it('reads the active Hardcore palette and polarity', () => {
    const dom = new JSDOM('<html class="emdark"><body></body></html>');
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('getComputedStyle', () => ({
      getPropertyValue: (name: string) =>
        ({
          '--em-background': '#121212',
          '--hc-cad-scene': '#101820',
          '--hc-cad-scene-grid': '#456789',
          '--hc-radius-md': '12px',
          '--em-text-micro': '9px',
          '--em-text-tiny': '10px',
        })[name] ?? '',
    }));

    const result = readCadViewerHostTheme(dom.window.document.documentElement);

    expect(result.dark).toBe(true);
    expect(result.panel).toBe('#121212');
    expect(result.scene).toBe('#101820');
    expect(result.sceneGrid).toBe('#456789');
    expect(result.radiusMd).toBe('12px');
    expect(result.textMicro).toBe('9px');
    expect(result.textTiny).toBe('10px');
    expect(cadViewerHostThemeSignature(result)).toContain('"dark":true');
    dom.window.close();
  });

  it('injects one integration style and one shared radius contract without repainting the viewer', () => {
    const dom = new JSDOM(
      '<html><head></head><body><header><button aria-label="Toggle CAD Viewer"></button></header></body></html>',
      { url: 'http://127.0.0.1:3245/models' }
    );
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLStyleElement', dom.window.HTMLStyleElement);
    vi.stubGlobal('StorageEvent', dom.window.StorageEvent);
    dom.window.localStorage.setItem(
      'cad-viewer:theme',
      JSON.stringify({ version: 12, themeId: 'custom', custom: { name: 'Saved custom theme' } })
    );

    dom.window.eval(buildCadViewerIntegrationScript(theme));
    dom.window.eval(buildCadViewerIntegrationScript(theme));

    const styles = dom.window.document.querySelectorAll('#hardcore-cad-viewer-integration');
    expect(styles).toHaveLength(1);
    expect(styles[0]?.textContent).not.toContain(':root {');
    expect(styles[0]?.textContent).not.toContain('--ui-glass-blur: 0px');
    expect(styles[0]?.textContent).toContain('--radius-md: 8px');
    expect(styles[0]?.textContent).toContain('--cad-scene-backdrop: #f2f2f2');
    expect(styles[0]?.textContent).toContain('--hardcore-scene-grid: #d5d5d5');
    expect(styles[0]?.textContent).toContain('--hardcore-text-micro: 10px');
    expect(styles[0]?.textContent).toContain('--hardcore-text-tiny: 11px');
    expect(styles[0]?.textContent).toContain('--hardcore-radius-md: var(--radius-md)');
    expect(styles[0]?.textContent).toContain(
      '.rounded-sm {\n  border-radius: var(--radius-sm) !important'
    );
    expect(styles[0]?.textContent).toContain(
      '.rounded-xs {\n  border-radius: var(--radius-xs) !important'
    );
    expect(styles[0]?.textContent).toContain(
      '.rounded-md {\n  border-radius: var(--radius-md) !important'
    );
    expect(styles[0]?.textContent).toContain(
      '.rounded-lg {\n  border-radius: var(--radius-lg) !important'
    );
    expect(styles[0]?.textContent).toContain(
      '.rounded-full {\n  border-radius: var(--radius-full) !important'
    );
    expect(styles[0]?.textContent).toContain('border-radius: var(--radius-sm) !important');
    expect(styles[0]?.textContent).toContain('border-radius: var(--hardcore-radius-sm)');
    expect(styles[0]?.textContent).toContain('border-radius: var(--radius-xs)');
    expect(styles[0]?.textContent).not.toContain('var(--hardcore-radius-xs)');
    expect(styles[0]?.textContent).toContain('font-size: var(--hardcore-text-micro)');
    expect(styles[0]?.textContent).toContain('font-size: var(--hardcore-text-tiny)');
    expect(styles[0]?.textContent).toContain('[data-hardcore-feature-history-row]:focus-visible');
    expect(styles[0]?.textContent).toContain('[data-hardcore-sketch-dimension]:focus-within');
    expect(styles[0]?.textContent).toContain(
      '[data-hardcore-apply-parameters]:not(:disabled):hover'
    );
    expect(styles[0]?.textContent).not.toContain('border-radius: 0');
    expect(styles[0]?.textContent).not.toContain('text-transform: uppercase');
    expect(styles[0]?.textContent).toContain('button[title="Copy screenshot to clipboard"]');
    expect(
      dom.window.document.querySelector('header')?.hasAttribute('data-hardcore-cad-viewer-header')
    ).toBe(true);
    expect(JSON.parse(dom.window.localStorage.getItem('cad-viewer:theme') ?? '{}')).toMatchObject({
      version: 12,
      themeId: 'custom',
      custom: {
        colorMode: 'light',
        background: { solidColor: '#f2f2f2' },
        floor: { gridCellColor: '#d5d5d5' },
      },
    });
    expect(dom.window.document.documentElement.classList.contains('dark')).toBe(false);
    dom.window.close();
  });

  it('supplies the host dark scene and grid colors to the viewer theme', () => {
    const dom = new JSDOM('<html><head></head><body></body></html>', {
      url: 'http://127.0.0.1:3245/models',
    });
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLStyleElement', dom.window.HTMLStyleElement);
    vi.stubGlobal('StorageEvent', dom.window.StorageEvent);

    dom.window.eval(
      buildCadViewerIntegrationScript({
        ...theme,
        dark: true,
        scene: '#101820',
        sceneGrid: '#456789',
      })
    );

    expect(dom.window.document.documentElement.classList.contains('dark')).toBe(true);
    expect(JSON.parse(dom.window.localStorage.getItem('cad-viewer:theme') ?? '{}')).toMatchObject({
      version: 12,
      themeId: 'custom',
      custom: {
        colorMode: 'dark',
        background: { solidColor: '#101820' },
        floor: { gridCellColor: '#456789' },
      },
    });
    dom.window.close();
  });

  it('hides viewer navigation that mounts after the integration runs', async () => {
    const dom = new JSDOM('<html><head></head><body></body></html>', {
      url: 'http://127.0.0.1:3245/models',
    });
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLStyleElement', dom.window.HTMLStyleElement);
    vi.stubGlobal('MutationObserver', dom.window.MutationObserver);
    vi.stubGlobal('StorageEvent', dom.window.StorageEvent);

    dom.window.eval(buildCadViewerIntegrationScript(theme));
    const viewerHeader = dom.window.document.createElement('header');
    const viewerToggle = dom.window.document.createElement('button');
    viewerToggle.setAttribute('aria-label', 'Toggle CAD Viewer');
    viewerHeader.appendChild(viewerToggle);
    dom.window.document.body.appendChild(viewerHeader);
    await new Promise((resolve) => dom.window.setTimeout(resolve, 0));

    expect(viewerHeader.hasAttribute('data-hardcore-cad-viewer-header')).toBe(true);
    dom.window.close();
  });

  it('copies a newly selected canonical reference and exposes it to the desktop chat', async () => {
    const dom = new JSDOM('<html><head></head><body></body></html>', {
      url: 'http://127.0.0.1:3245/models',
    });
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLStyleElement', dom.window.HTMLStyleElement);
    vi.stubGlobal('MutationObserver', dom.window.MutationObserver);
    vi.stubGlobal('StorageEvent', dom.window.StorageEvent);
    dom.window.eval(buildCadViewerIntegrationScript(theme));

    const copy = dom.window.document.createElement('button');
    copy.textContent = 'Copy bracket#f12';
    const onCopy = vi.fn();
    copy.addEventListener('click', onCopy);
    dom.window.document.body.appendChild(copy);
    await new Promise((resolve) => dom.window.setTimeout(resolve, 0));

    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(dom.window.eval(buildCadViewerConsumeReferenceCommandScript())).toMatchObject({
      reference: 'bracket#f12',
    });
    expect(dom.window.eval(buildCadViewerConsumeReferenceCommandScript())).toBeNull();
    dom.window.close();
  });

  it('reads a canonical reference from the selected topology row in the current viewer', async () => {
    const dom = new JSDOM(
      '<html><head></head><body><div role="row" aria-selected="true" aria-label="Face: Face f5 Ref: #o1.1.f5"></div><button>Copy reference</button></body></html>',
      { url: 'http://127.0.0.1:3245/models' }
    );
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLStyleElement', dom.window.HTMLStyleElement);
    vi.stubGlobal('MutationObserver', dom.window.MutationObserver);
    vi.stubGlobal('StorageEvent', dom.window.StorageEvent);
    const copy = dom.window.document.querySelector('button');
    const onCopy = vi.fn();
    copy?.addEventListener('click', onCopy);

    dom.window.eval(buildCadViewerIntegrationScript(theme));

    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(dom.window.eval(buildCadViewerConsumeReferenceCommandScript())).toMatchObject({
      reference: '#o1.1.f5',
    });
    dom.window.close();
  });

  it('copies an icon-only component reference from the current viewer markup', async () => {
    const dom = new JSDOM(
      '<html><head></head><body><div role="row" aria-selected="true" aria-label="Component passenger_cabin o1.2"></div><section><strong>passenger_cabin Component</strong><span>o1.2</span><button aria-label="Copy reference"></button></section></body></html>',
      { url: 'http://127.0.0.1:3245/models' }
    );
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLStyleElement', dom.window.HTMLStyleElement);
    vi.stubGlobal('MutationObserver', dom.window.MutationObserver);
    vi.stubGlobal('StorageEvent', dom.window.StorageEvent);
    const copy = dom.window.document.querySelector('button');
    const onCopy = vi.fn();
    copy?.addEventListener('click', onCopy);

    dom.window.eval(buildCadViewerIntegrationScript(theme));

    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(dom.window.eval(buildCadViewerConsumeReferenceCommandScript())).toMatchObject({
      reference: '#o1.2',
    });
    expect(dom.window.eval(buildCadViewerConsumeReferenceCommandScript())).toBeNull();
    dom.window.close();
  });

  it('falls back to the current viewer reference card when row metadata is unavailable', async () => {
    const dom = new JSDOM(
      '<html><head></head><body><section><div><strong>Planar Face o1.1.f4</strong><button>Copy reference</button></div></section></body></html>',
      { url: 'http://127.0.0.1:3245/models' }
    );
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLStyleElement', dom.window.HTMLStyleElement);
    vi.stubGlobal('MutationObserver', dom.window.MutationObserver);
    vi.stubGlobal('StorageEvent', dom.window.StorageEvent);
    const copy = dom.window.document.querySelector('button');
    const onCopy = vi.fn();
    copy?.addEventListener('click', onCopy);

    dom.window.eval(buildCadViewerIntegrationScript(theme));

    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(dom.window.eval(buildCadViewerConsumeReferenceCommandScript())).toMatchObject({
      reference: '#o1.1.f4',
    });
    dom.window.close();
  });

  it('can poll the current viewer selection without relying on the initial integration observer', () => {
    const dom = new JSDOM(
      '<html><body><div role="row" aria-selected="true" aria-label="Face f6 Ref: #o1.1.f6"></div><button aria-label="Copy reference"></button></body></html>',
      { url: 'http://127.0.0.1:3245/models' }
    );
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);

    expect(dom.window.eval(buildCadViewerConsumeReferenceCommandScript())).toMatchObject({
      reference: '#o1.1.f6',
    });
    expect(dom.window.eval(buildCadViewerConsumeReferenceCommandScript())).toBeNull();
    dom.window.close();
  });

  it('routes shell annotation actions to the existing viewer tool', () => {
    const dom = new JSDOM('<html><body><button aria-label="Draw"></button></body></html>');
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    const draw = dom.window.document.querySelector('button');
    const onDraw = vi.fn();
    draw?.addEventListener('click', onDraw);

    expect(dom.window.eval(buildCadViewerToolbarActionScript('Draw'))).toBe(true);
    expect(onDraw).toHaveBeenCalledTimes(1);
    expect(dom.window.eval(buildCadViewerToolbarActionScript('Copy screenshot'))).toBe(false);
    dom.window.close();
  });

  it('derives SolidWorks-style sketch consumers from authored and primitive construction', () => {
    const history = parseCadSourceHistory(`
def gen_step():
    with BuildPart() as part:
        with BuildSketch():
            Rectangle(24, 16)
            Circle(3, mode=Mode.SUBTRACT)
        extrude(amount=6)
        with BuildSketch(Plane.XZ):
            Circle(5)
        revolve(axis=Axis.Z, revolution_arc=180, mode=Mode.SUBTRACT)
        Box(40, 30, 8)
    return part.part
`);

    const tree = buildCadDesignTree(history);

    expect(tree[0]?.nodes.map((node) => node.label)).toEqual([
      'Boss-Extrude1',
      'Cut-Revolve1',
      'Boss-Extrude2',
    ]);
    expect(tree[0]?.nodes.map((node) => node.children[0]?.label)).toEqual([
      'Sketch1',
      'Sketch2',
      'Sketch3',
    ]);
    expect(tree[0]?.nodes[0]?.children[0]?.geometryNames).toEqual(['Rectangle', 'Circle']);
    expect(tree[0]?.nodes[0]?.controls.map((control) => control.label)).toEqual(['Depth']);
    expect(tree[0]?.nodes[0]?.children[0]?.controls.map((control) => control.label)).toEqual([
      'Width',
      'Height',
      'Radius',
    ]);
    expect(tree[0]?.nodes[1]?.controls.map((control) => control.label)).toEqual(['Angle']);
    expect(tree[0]?.nodes[1]?.children[0]?.sketchPlane).toBe('XZ');
    expect(tree[0]?.nodes[2]?.controls.map((control) => control.label)).toEqual(['Depth']);
    expect(tree[0]?.nodes[2]?.children[0]?.controls.map((control) => control.label)).toEqual([
      'Length',
      'Width',
    ]);
  });

  it('adds source feature history beside the native topology tree without replacing it', () => {
    const dom = new JSDOM(
      `<html><body>
        <section data-file-sheet-tab-pane="top">
          <div role="tablist">
            <span><button role="tab" aria-selected="true" data-file-sheet-tab="tree">Tree</button></span>
          </div>
          <div data-file-sheet-tab-panel="tree">
            Native topology
            <div role="treeitem" aria-label="Component Box1">Box1</div>
          </div>
        </section>
        <canvas aria-label="CAD viewport"></canvas>
      </body></html>`,
      { url: 'http://127.0.0.1:3245/model.step.py' }
    );
    const script = buildCadViewerFeatureHistoryScript(
      {
        diagnostics: [],
        parameters: [
          {
            id: 'width',
            symbol: 'Box.length',
            label: 'Box length',
            unit: 'mm',
            min: 10,
            max: 30,
            step: 1,
            defaultValue: 20,
            line: 4,
            span: [100, 102],
            groupIds: ['gen_step'],
            featureIds: ['gen_step:22:Box:2'],
            origin: 'source-variable',
          },
        ],
        groups: [
          {
            id: 'gen_step',
            functionName: 'gen_step',
            label: 'Model assembly',
            line: 20,
            dependencies: ['_body'],
            features: [
              {
                id: 'gen_step:21:AssemblyHelper:1',
                operation: 'AssemblyHelper',
                label: 'Assembly',
                kind: 'assembly',
                line: 21,
              },
              {
                id: 'gen_step:22:Box:2',
                operation: 'Box',
                label: 'Box',
                kind: 'primitive',
                line: 22,
              },
            ],
          },
        ],
      },
      'source-hash'
    );
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLButtonElement', dom.window.HTMLButtonElement);
    vi.stubGlobal('HTMLCanvasElement', dom.window.HTMLCanvasElement);
    vi.stubGlobal('Element', dom.window.Element);
    const canvas = dom.window.document.querySelector('canvas');
    vi.spyOn(canvas!, 'getBoundingClientRect').mockReturnValue({
      x: 120,
      y: 80,
      left: 120,
      top: 80,
      right: 840,
      bottom: 560,
      width: 720,
      height: 480,
      toJSON: () => ({}),
    });
    const viewerBridge = {
      canvas,
      renderSketch: vi.fn(),
      project: vi.fn(() => ({ x: 360, y: 240, visible: true })),
      setGhosted: vi.fn(),
      dispose: vi.fn(),
    };
    Object.assign(dom.window, { __hardcoreCadViewerBridge: viewerBridge });

    expect(dom.window.eval(script)).toBe(true);
    expect(dom.window.eval(script)).toBe(true);
    expect(dom.window.eval(buildCadViewerFeatureHistoryReadyScript('source-hash'))).toBe(true);
    vi.clearAllMocks();
    expect(dom.window.document.querySelectorAll('[data-file-sheet-tab="features"]')).toHaveLength(
      1
    );
    expect(dom.window.document.querySelector('[data-file-sheet-tab="tree"]')?.textContent).toBe(
      'Geometry'
    );
    expect(dom.window.document.querySelector('[data-file-sheet-tab="features"]')?.textContent).toBe(
      'Design2'
    );
    expect(
      [...dom.window.document.querySelectorAll('[data-file-sheet-tab]')].map(
        (tab) => tab.textContent
      )
    ).toEqual(['Design2', 'Geometry']);
    expect(
      dom.window.document.querySelector('[data-hardcore-feature-history-panel]')?.textContent
    ).toContain('Model assembly');
    expect(
      dom.window.document.querySelector('[data-hardcore-feature-history-root]')?.textContent
    ).toContain('modelAssembly');
    expect(dom.window.document.querySelector('[data-hardcore-feature-filter]')).not.toBeNull();
    expect(
      dom.window.document.querySelector('[data-hardcore-feature-history-row]')?.textContent
    ).toContain('Assembly1');
    expect(
      dom.window.document
        .querySelector('[data-hardcore-feature-history-row]')
        ?.getAttribute('data-hardcore-selected')
    ).toBe('false');
    expect(
      dom.window.document.querySelectorAll('[data-hardcore-tree-icon]').length
    ).toBeGreaterThan(2);
    const featureRows = [
      ...dom.window.document.querySelectorAll<HTMLElement>(
        '[data-hardcore-feature-history-row][data-hardcore-feature-id]'
      ),
    ];
    const matchingGeometry = dom.window.document.querySelector<HTMLElement>(
      '[aria-label="Component Box1"]'
    );
    matchingGeometry?.addEventListener('click', () => {
      matchingGeometry.setAttribute('data-test-selected', 'true');
    });
    featureRows[1]?.click();
    expect(featureRows[0]?.getAttribute('data-hardcore-selected')).toBe('false');
    expect(featureRows[1]?.getAttribute('data-hardcore-selected')).toBe('true');
    expect(matchingGeometry?.getAttribute('data-test-selected')).toBe('true');
    expect(featureRows[1]?.getAttribute('data-hardcore-geometry-linked')).toBe('true');
    const featureFilter = dom.window.document.querySelector<HTMLInputElement>(
      '[data-hardcore-feature-filter]'
    );
    if (featureFilter) {
      featureFilter.value = 'box';
      featureFilter.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    }
    expect(featureRows[0]?.hasAttribute('hidden')).toBe(true);
    expect(featureRows[1]?.hasAttribute('hidden')).toBe(false);
    expect(
      dom.window.document.querySelector('[data-file-sheet-tab-panel="tree"]')?.textContent
    ).toContain('Native topology');

    const featureTab = dom.window.document.querySelector<HTMLButtonElement>(
      'button[data-file-sheet-tab="features"]'
    );
    const treeTab = dom.window.document.querySelector<HTMLButtonElement>(
      'button[data-file-sheet-tab="tree"]'
    );
    const featurePanel = dom.window.document.querySelector<HTMLElement>(
      '[data-hardcore-feature-history-panel]'
    );
    expect(featureTab?.getAttribute('aria-selected')).toBe('true');
    expect(featurePanel?.hidden).toBe(false);
    expect(dom.window.document.querySelector('[data-hardcore-parameters-panel]')).toBeNull();
    expect(dom.window.sessionStorage.getItem('hardcore:model-tree-view')).toBe('design');
    const featuresMode = featurePanel?.querySelector<HTMLButtonElement>(
      '[data-hardcore-design-mode="features"]'
    );
    const slidersMode = featurePanel?.querySelector<HTMLButtonElement>(
      '[data-hardcore-design-mode="sliders"]'
    );
    const featureContent = featurePanel?.querySelector<HTMLElement>(
      '[data-hardcore-design-mode-view="features"]'
    );
    const slidersContent = featurePanel?.querySelector<HTMLElement>(
      '[data-hardcore-design-mode-view="sliders"]'
    );
    expect(featuresMode?.getAttribute('aria-pressed')).toBe('true');
    expect(slidersMode?.getAttribute('aria-pressed')).toBe('false');
    expect(featureContent?.hidden).toBe(false);
    expect(slidersContent?.hidden).toBe(true);
    expect(dom.window.document.querySelector('details')?.open).toBe(true);
    expect(featureRows[1]?.textContent).toContain('Boss-Extrude1');
    expect(featureRows[2]?.textContent).toContain('Sketch1');
    featureRows[2]?.click();
    const selectedFeature = featureRows[2]?.closest<HTMLDetailsElement>(
      '[data-hardcore-feature-node]'
    );
    expect(selectedFeature?.open).toBe(true);
    const numbers = [
      ...dom.window.document.querySelectorAll<HTMLInputElement>('[data-hardcore-parameter-number]'),
    ];
    expect(numbers).toHaveLength(2);
    expect(dom.window.document.activeElement).toBe(numbers[0]);
    const editSketch = featurePanel?.querySelector<HTMLButtonElement>(
      '[data-hardcore-edit-sketch]'
    );
    expect(editSketch?.textContent).toBe('Edit sketch in viewport');
    editSketch?.click();
    const sketchOverlay = dom.window.document.querySelector<HTMLElement>(
      '[data-hardcore-sketch-edit-overlay]'
    );
    expect(sketchOverlay?.getAttribute('aria-label')).toBe('Editing Sketch1');
    expect(sketchOverlay?.textContent).toContain('XY plane');
    expect(sketchOverlay?.hasAttribute('data-hardcore-on-model')).toBe(true);
    expect(sketchOverlay?.querySelector('svg')).toBeNull();
    expect(sketchOverlay?.style.left).toBe('120px');
    expect(sketchOverlay?.style.width).toBe('720px');
    expect(viewerBridge.setGhosted).toHaveBeenCalledWith(true);
    expect(viewerBridge.renderSketch).toHaveBeenCalledWith(
      expect.objectContaining({
        plane: 'XY',
        origin: [0, 0, 0],
        segments: expect.any(Array),
      })
    );
    const sketchLength = sketchOverlay?.querySelector<HTMLInputElement>(
      '[aria-label="Length sketch dimension"]'
    );
    expect(sketchLength?.value).toBe('20');
    if (sketchLength) {
      sketchLength.value = '';
      sketchLength.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
      expect(sketchLength.value).toBe('');
      expect(numbers[0]?.value).toBe('20');
      sketchLength.value = '24';
      sketchLength.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    }
    expect(
      numbers[0]?.closest('[data-hardcore-parameter-control]')?.getAttribute('data-hardcore-dirty')
    ).toBe('true');
    expect(numbers[1]?.value).toBe('24');
    expect(featurePanel?.textContent).toContain('1 change pending');
    sketchOverlay?.querySelector<HTMLButtonElement>('[data-hardcore-sketch-cancel]')?.click();
    expect(dom.window.document.querySelector('[data-hardcore-sketch-edit-overlay]')).toBeNull();
    expect(viewerBridge.dispose).toHaveBeenCalled();
    expect(numbers[0]?.value).toBe('20');
    expect(numbers[1]?.value).toBe('20');
    expect(dom.window.eval(buildCadViewerConsumeParameterCommandScript())).toBeNull();
    const revert = featurePanel?.querySelector<HTMLButtonElement>(
      '[data-hardcore-revert-parameters]'
    );
    expect(revert?.disabled).toBe(true);
    slidersMode?.click();
    expect(featuresMode?.getAttribute('aria-pressed')).toBe('false');
    expect(slidersMode?.getAttribute('aria-pressed')).toBe('true');
    expect(featureContent?.hidden).toBe(true);
    expect(slidersContent?.hidden).toBe(false);
    expect(dom.window.sessionStorage.getItem('hardcore:design-mode')).toBe('sliders');
    if (numbers[1]) {
      numbers[1].value = '25';
      numbers[1].dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    }
    editSketch?.click();
    const confirmOverlay = dom.window.document.querySelector<HTMLElement>(
      '[data-hardcore-sketch-edit-overlay]'
    );
    expect(
      confirmOverlay?.querySelector<HTMLInputElement>('[aria-label="Length sketch dimension"]')
        ?.value
    ).toBe('25');
    confirmOverlay?.querySelector<HTMLButtonElement>('[data-hardcore-sketch-confirm]')?.click();
    const apply = featurePanel?.querySelector<HTMLButtonElement>(
      '[data-hardcore-apply-parameters]'
    );
    expect(apply?.disabled).toBe(true);
    expect(
      [
        ...dom.window.document.querySelectorAll<HTMLButtonElement>(
          '[data-hardcore-apply-parameters]'
        ),
      ].map((button) => ({ disabled: button.disabled, text: button.textContent }))
    ).toEqual([{ disabled: true, text: 'Applying…' }]);
    const command = dom.window.eval(buildCadViewerConsumeParameterCommandScript());
    expect(command).toMatchObject({
      sourceHash: 'source-hash',
      values: { width: 25 },
    });
    dom.window.eval(`window.__hardcoreCadParameterCommand = ${JSON.stringify(command)}`);
    expect(dom.window.eval(buildCadViewerConsumeParameterCommandScript())).toBeNull();
    treeTab?.click();
    expect(treeTab?.getAttribute('aria-selected')).toBe('true');
    expect(featurePanel?.hidden).toBe(true);
    expect(dom.window.sessionStorage.getItem('hardcore:model-tree-view')).toBe('geometry');
    featurePanel?.remove();
    expect(dom.window.eval(buildCadViewerFeatureHistoryReadyScript('source-hash'))).toBe(false);
    dom.window.close();
  });

  it('keeps Design discoverable for imported STEP without inventing editable history', () => {
    const dom = new JSDOM(
      `<html><body>
        <section data-file-sheet-tab-pane="top">
          <div role="tablist">
            <span><button role="tab" aria-selected="true" data-file-sheet-tab="tree">Tree</button></span>
          </div>
          <div data-file-sheet-tab-panel="tree">Native STEP topology</div>
        </section>
      </body></html>`,
      { url: 'http://127.0.0.1:3245/imported.step' }
    );
    const script = buildCadViewerFeatureHistoryScript(
      {
        groups: [],
        parameters: [],
        diagnostics: [
          'This imported STEP has geometry but no linked editable construction source.',
        ],
      },
      'geometry-only:imported.step'
    );
    vi.stubGlobal('window', dom.window);
    vi.stubGlobal('document', dom.window.document);
    vi.stubGlobal('HTMLElement', dom.window.HTMLElement);
    vi.stubGlobal('HTMLButtonElement', dom.window.HTMLButtonElement);
    vi.stubGlobal('HTMLCanvasElement', dom.window.HTMLCanvasElement);
    vi.stubGlobal('Element', dom.window.Element);

    expect(dom.window.eval(script)).toBe(true);
    expect(
      dom.window.document.querySelector<HTMLButtonElement>('button[data-file-sheet-tab="features"]')
        ?.textContent
    ).toContain('Design');
    expect(
      dom.window.document.querySelector<HTMLButtonElement>('[data-hardcore-design-mode="sliders"]')
    ).toMatchObject({
      disabled: true,
      title: 'No editable dimensions are exposed for this model',
    });
    expect(
      dom.window.document.querySelector('[data-hardcore-feature-history-diagnostic]')?.textContent
    ).toContain('no linked editable construction source');
    expect(
      dom.window.document.querySelector('[data-file-sheet-tab-panel="tree"]')?.textContent
    ).toContain('Native STEP topology');
    dom.window.close();
  });
});
