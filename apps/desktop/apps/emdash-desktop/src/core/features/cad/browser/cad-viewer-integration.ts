import type {
  CadDesignParameter,
  CadSourceFeature,
  CadSourceFeatureKind,
  CadSourceHistory,
} from '@core/features/cad/api/cad-source-history';

export interface CadDesignTreeControl {
  parameterId: string;
  label: string;
}

export interface CadDesignTreeNode {
  id: string;
  label: string;
  operation: string;
  kind: CadSourceFeatureKind;
  line: number;
  sourceFeatureIds: string[];
  geometryNames: string[];
  controls: CadDesignTreeControl[];
  children: CadDesignTreeNode[];
  sketchPlane?: 'XY' | 'XZ' | 'YZ';
  sketchOrigin?: [number, number, number];
}

export interface CadDesignTreeGroup {
  id: string;
  label: string;
  functionName: string;
  nodes: CadDesignTreeNode[];
}

function parameterSemanticName(parameter: CadDesignParameter): string {
  const dottedName = parameter.symbol.split('.').at(-1)?.toLowerCase() ?? '';
  if (dottedName !== parameter.symbol.toLowerCase()) return dottedName;
  const words = `${parameter.symbol} ${parameter.label}`.toLowerCase();
  for (const name of [
    'revolution_arc',
    'corner_radius',
    'diameter',
    'thickness',
    'length',
    'width',
    'height',
    'radius',
    'depth',
    'amount',
    'angle',
  ]) {
    if (words.includes(name.replace('_', ' ')) || words.includes(name)) return name;
  }
  return dottedName;
}

function designControlLabel(parameter: CadDesignParameter, role: 'sketch' | 'feature'): string {
  const name = parameterSemanticName(parameter);
  if (role === 'feature') {
    if (name === 'height' || name === 'amount' || name === 'thickness') return 'Depth';
    if (name === 'revolution_arc' || name === 'angle') return 'Angle';
  }
  if (name === 'corner_radius') return 'Corner radius';
  return (
    name
      .split('_')
      .filter(Boolean)
      .map((word) => `${word[0]?.toUpperCase() ?? ''}${word.slice(1)}`)
      .join(' ') || parameter.label
  );
}

function featureModeName(feature: CadSourceFeature): string {
  if (feature.operation === 'extrude') {
    return feature.mode === 'subtract' ? 'Cut-Extrude' : 'Boss-Extrude';
  }
  if (feature.operation === 'revolve') {
    return feature.mode === 'subtract' ? 'Cut-Revolve' : 'Revolve';
  }
  if (feature.operation === 'Box' || feature.operation === 'Cylinder') return 'Boss-Extrude';
  if (feature.operation === 'Sphere') return 'Revolve';
  if (feature.operation === 'Hole') return 'Hole';
  if (feature.operation === 'fillet') return 'Fillet';
  if (feature.operation === 'chamfer') return 'Chamfer';
  if (feature.operation === 'loft') return 'Loft';
  if (feature.operation === 'sweep') return 'Sweep';
  if (feature.operation === 'BuildLine') return '3D Sketch';
  return feature.label;
}

export function buildCadDesignTree(history: CadSourceHistory): CadDesignTreeGroup[] {
  const parametersByFeature = new Map<string, CadDesignParameter[]>();
  for (const parameter of history.parameters) {
    for (const featureId of parameter.featureIds) {
      const linked = parametersByFeature.get(featureId) ?? [];
      linked.push(parameter);
      parametersByFeature.set(featureId, linked);
    }
  }
  const counters = new Map<string, number>();
  let sketchCount = 0;
  const numberedLabel = (type: string) => {
    const count = (counters.get(type) ?? 0) + 1;
    counters.set(type, count);
    return `${type}${count}`;
  };
  const controlsFor = (
    featureIds: readonly string[],
    role: 'sketch' | 'feature',
    accept: (parameter: CadDesignParameter) => boolean = () => true
  ): CadDesignTreeControl[] => {
    const seen = new Set<string>();
    const controls: CadDesignTreeControl[] = [];
    for (const featureId of featureIds) {
      for (const parameter of parametersByFeature.get(featureId) ?? []) {
        if (seen.has(parameter.id) || !accept(parameter)) continue;
        seen.add(parameter.id);
        controls.push({
          parameterId: parameter.id,
          label: designControlLabel(parameter, role),
        });
      }
    }
    return controls;
  };
  const sketchNode = (
    id: string,
    line: number,
    sourceFeatures: readonly CadSourceFeature[],
    controls: CadDesignTreeControl[],
    geometryNames: string[],
    sketchPlane: CadDesignTreeNode['sketchPlane'] = 'XY',
    sketchOrigin: CadDesignTreeNode['sketchOrigin'] = [0, 0, 0]
  ): CadDesignTreeNode => {
    sketchCount += 1;
    return {
      id,
      label: `Sketch${sketchCount}`,
      operation: 'Sketch',
      kind: 'sketch',
      line,
      sourceFeatureIds: sourceFeatures.map((feature) => feature.id),
      geometryNames,
      controls,
      children: [],
      sketchPlane,
      sketchOrigin,
    };
  };

  return history.groups.map((group) => {
    const nodes: CadDesignTreeNode[] = [];
    for (let index = 0; index < group.features.length; index += 1) {
      const feature = group.features[index];
      if (feature.operation === 'BuildPart') continue;
      if (feature.operation === 'BuildSketch') {
        const entities: CadSourceFeature[] = [];
        let cursor = index + 1;
        while (cursor < group.features.length && group.features[cursor].kind === 'sketch') {
          entities.push(group.features[cursor]);
          cursor += 1;
        }
        const consumer = group.features[cursor];
        const sketchFeatureIds = [feature.id, ...entities.map((entity) => entity.id)];
        const sketch = sketchNode(
          `${feature.id}:design-sketch`,
          feature.line,
          [feature, ...entities],
          controlsFor(sketchFeatureIds, 'sketch'),
          entities.map((entity) => entity.operation),
          feature.plane ?? 'XY',
          feature.sketchOrigin ?? [0, 0, 0]
        );
        if (consumer && (consumer.operation === 'extrude' || consumer.operation === 'revolve')) {
          const type = featureModeName(consumer);
          nodes.push({
            id: consumer.id,
            label: numberedLabel(type),
            operation: consumer.operation,
            kind: 'operation',
            line: consumer.line,
            sourceFeatureIds: [consumer.id],
            geometryNames: [type, consumer.operation],
            controls: controlsFor([consumer.id], 'feature'),
            children: [sketch],
          });
          index = cursor;
        } else {
          nodes.push(sketch);
          index = cursor - 1;
        }
        continue;
      }

      if (
        feature.operation === 'Box' ||
        feature.operation === 'Cylinder' ||
        feature.operation === 'Sphere'
      ) {
        const linked = parametersByFeature.get(feature.id) ?? [];
        const sketchNames =
          feature.operation === 'Box'
            ? new Set(['length', 'width', 'radius', 'corner_radius'])
            : new Set(['radius', 'diameter']);
        const sketch = sketchNode(
          `${feature.id}:design-sketch`,
          feature.line,
          [feature],
          controlsFor([feature.id], 'sketch', (parameter) =>
            sketchNames.has(parameterSemanticName(parameter))
          ),
          [
            feature.operation === 'Box'
              ? 'Rectangle'
              : feature.operation === 'Sphere'
                ? 'Arc'
                : 'Circle',
          ]
        );
        const featureParameters = new Set(
          linked
            .filter((parameter) => !sketchNames.has(parameterSemanticName(parameter)))
            .map((parameter) => parameter.id)
        );
        const type = featureModeName(feature);
        nodes.push({
          id: feature.id,
          label: numberedLabel(type),
          operation: feature.operation,
          kind: 'operation',
          line: feature.line,
          sourceFeatureIds: [feature.id],
          geometryNames: [feature.operation, type],
          controls: controlsFor([feature.id], 'feature', (parameter) =>
            featureParameters.has(parameter.id)
          ),
          children: [sketch],
        });
        continue;
      }

      if (feature.kind === 'sketch') {
        nodes.push(
          sketchNode(
            `${feature.id}:design-sketch`,
            feature.line,
            [feature],
            controlsFor([feature.id], 'sketch'),
            [feature.operation]
          )
        );
        continue;
      }

      const type = featureModeName(feature);
      nodes.push({
        id: feature.id,
        label: numberedLabel(type),
        operation: feature.operation,
        kind: feature.kind,
        line: feature.line,
        sourceFeatureIds: [feature.id],
        geometryNames: [feature.operation, type],
        controls: controlsFor([feature.id], 'feature'),
        children: [],
      });
    }
    return {
      id: group.id,
      label: group.label,
      functionName: group.functionName,
      nodes,
    };
  });
}

export interface CadViewerHostTheme {
  background: string;
  panel: string;
  control: string;
  accent: string;
  border: string;
  foreground: string;
  mutedForeground: string;
  info: string;
  dark: boolean;
  scene: string;
  sceneGrid: string;
  radiusXs: string;
  radiusSm: string;
  radiusMd: string;
  radiusLg: string;
  radiusXl: string;
  radiusFull: string;
  textMicro: string;
  textTiny: string;
}

const INTEGRATION_STYLE_ID = 'hardcore-cad-viewer-integration';
const INTEGRATION_HEADER_ATTRIBUTE = 'data-hardcore-cad-viewer-header';

function themeValue(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  return styles.getPropertyValue(name).trim() || fallback;
}

export function readCadViewerHostTheme(
  root: HTMLElement = document.documentElement
): CadViewerHostTheme {
  const styles = getComputedStyle(root);
  const dark = root.classList.contains('emdark');
  return {
    background: themeValue(styles, '--em-background-secondary', dark ? '#181818' : '#f2f2f2'),
    panel: themeValue(styles, '--em-background', dark ? '#111111' : '#fcfcfc'),
    control: themeValue(styles, '--em-background', dark ? '#111111' : '#fcfcfc'),
    accent: themeValue(styles, '--em-background-secondary-2', dark ? '#282828' : '#dddddd'),
    border: themeValue(styles, '--em-border-subtle', dark ? '#333333' : '#d0d0d0'),
    foreground: themeValue(styles, '--em-foreground', dark ? '#e8e8e8' : '#222222'),
    mutedForeground: themeValue(styles, '--em-foreground-muted', dark ? '#b8b8b8' : '#626262'),
    info: themeValue(styles, '--em-foreground-info', dark ? '#73a7ff' : '#3b82f6'),
    dark,
    scene: themeValue(styles, '--hc-cad-scene', dark ? '#1a1e23' : '#eceff4'),
    sceneGrid: themeValue(styles, '--hc-cad-scene-grid', dark ? '#3b4554' : '#cbd3e2'),
    radiusXs: themeValue(styles, '--hc-radius-xs', '4px'),
    radiusSm: themeValue(styles, '--hc-radius-sm', '6px'),
    radiusMd: themeValue(styles, '--hc-radius-md', '8px'),
    radiusLg: themeValue(styles, '--hc-radius-lg', '10px'),
    radiusXl: themeValue(styles, '--hc-radius-xl', '14px'),
    radiusFull: themeValue(styles, '--hc-radius-full', '9999px'),
    textMicro: themeValue(styles, '--em-text-micro', '10px'),
    textTiny: themeValue(styles, '--em-text-tiny', '11px'),
  };
}

export function cadViewerHostThemeSignature(theme: CadViewerHostTheme): string {
  return JSON.stringify(theme);
}

function integrationStyles(theme: CadViewerHostTheme): string {
  return `
header[${INTEGRATION_HEADER_ATTRIBUTE}],
header:has(button[aria-label="Toggle CAD Viewer"]) {
  display: none !important;
}

/* Hardcore owns these two chat-facing actions so they have one obvious home. */
button[aria-label="Draw"],
button[aria-label="Copy screenshot"],
button[aria-label="Copy Screenshot"],
button[title="Copy screenshot to clipboard"] {
  display: none !important;
}

/* Keep one radius scale for native viewer roles and Hardcore's injected
 * controls. The rules below restore the viewer's semantic rounded-* classes
 * because the currently shipped standalone CSS compiled them to zero. */
body {
  --radius: ${theme.radiusMd};
  --radius-xs: ${theme.radiusXs};
  --radius-sm: ${theme.radiusSm};
  --radius-md: ${theme.radiusMd};
  --radius-lg: ${theme.radiusLg};
  --radius-xl: ${theme.radiusXl};
  --radius-full: ${theme.radiusFull};
  --hardcore-text-micro: ${theme.textMicro};
  --hardcore-text-tiny: ${theme.textTiny};
  --cad-scene-backdrop: ${theme.scene};
  --hardcore-scene-grid: ${theme.sceneGrid};
  background-color: var(--cad-scene-backdrop);
}

/* The current standalone build compiled its semantic rounded-* utilities to
 * zero. Restore those existing roles in the embedded document instead of
 * enumerating viewer controls or changing its standalone presentation. */
.rounded-xs {
  border-radius: var(--radius-xs) !important;
}

.rounded-sm {
  border-radius: var(--radius-sm) !important;
}

.rounded-md {
  border-radius: var(--radius-md) !important;
}

.rounded-lg {
  border-radius: var(--radius-lg) !important;
}

.rounded-xl {
  border-radius: var(--radius-xl) !important;
}

.rounded-full {
  border-radius: var(--radius-full) !important;
}

:where([data-hardcore-feature-history-panel], [data-hardcore-sketch-edit-overlay]) {
  --hardcore-radius-sm: var(--radius-sm);
  --hardcore-radius-md: var(--radius-md);
  --hardcore-radius-lg: var(--radius-lg);
  --hardcore-transition: background-color 120ms, border-color 120ms, color 120ms,
    box-shadow 120ms;
}

[data-file-sheet-tab] {
  height: calc(2rem - 0.25rem) !important;
  margin: 0.125rem;
  border-right-color: transparent !important;
  border-radius: var(--radius-sm) !important;
}

[data-hardcore-feature-history-panel] {
  min-height: 0;
  flex: 1;
  overflow: auto;
  background: transparent;
}

[data-hardcore-feature-history-panel][hidden],
[data-hardcore-design-mode-view][hidden],
[data-file-sheet-tab-pane="top"][data-hardcore-model-tree-view="design"]
  [data-file-sheet-tab-panel="tree"] {
  display: none !important;
}

[data-hardcore-design-mode-switch] {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.1875rem;
  margin: 0.375rem 0.5rem;
  padding: 0.1875rem;
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-md);
  background: var(--ui-glass-control);
  -webkit-backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
  backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
}

[data-hardcore-design-mode] {
  min-width: 0;
  min-height: 1.75rem;
  border: 0;
  border-radius: var(--hardcore-radius-sm);
  background: transparent;
  padding: 0.25rem 0.375rem;
  color: var(--muted-foreground);
  font-size: 0.75rem;
  font-weight: 500;
  transition: var(--hardcore-transition);
}

[data-hardcore-design-mode]:hover {
  background: color-mix(in srgb, var(--accent) 58%, transparent);
  color: var(--foreground);
}

[data-hardcore-design-mode]:focus-visible,
[data-hardcore-edit-sketch]:focus-visible,
[data-hardcore-sketch-edit-actions] button:focus-visible,
[data-hardcore-apply-parameters]:focus-visible,
[data-hardcore-revert-parameters]:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--ring) 32%, transparent);
}

[data-hardcore-design-mode][aria-pressed="true"] {
  background: var(--secondary);
  color: var(--foreground);
}

[data-hardcore-design-mode-view="sliders"] {
  border-top: 1px solid color-mix(in srgb, var(--sidebar-border) 70%, transparent);
}

[data-hardcore-design-mode-view="sliders"] [data-hardcore-parameter-control] {
  padding: 0.5rem;
  border-bottom: 1px solid color-mix(in srgb, var(--sidebar-border) 70%, transparent);
}

[data-hardcore-edit-sketch] {
  width: calc(100% - 1rem);
  margin: 0.375rem 0.5rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-md);
  background: var(--secondary);
  padding: 0.3125rem 0.5rem;
  color: var(--foreground);
  font-size: 0.75rem;
  font-weight: 500;
  text-align: center;
  transition: var(--hardcore-transition);
}

[data-hardcore-edit-sketch]:hover {
  background: var(--accent);
}

[data-hardcore-sketch-edit-overlay] {
  position: fixed;
  z-index: 45;
  overflow: visible;
  pointer-events: none;
  color: var(--foreground);
}

[data-hardcore-sketch-edit-header] {
  position: absolute;
  z-index: 3;
  top: 0.75rem;
  left: 0.75rem;
  right: 9.5rem;
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.5rem;
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-lg);
  background: var(--ui-glass-popover);
  padding: 0.375rem 0.5rem;
  -webkit-backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
  backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
  box-shadow: var(--ui-shadow-soft);
  font-size: 0.8125rem;
  pointer-events: auto;
}

[data-hardcore-sketch-edit-header] strong {
  min-width: 0;
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

[data-hardcore-sketch-edit-header] span {
  flex-shrink: 0;
}

[data-hardcore-sketch-edit-actions] {
  position: absolute;
  z-index: 3;
  top: 0.75rem;
  right: 0.75rem;
  display: flex;
  gap: 0.375rem;
  pointer-events: auto;
}

[data-hardcore-sketch-edit-actions] button {
  min-width: 4rem;
  min-height: 1.75rem;
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-md);
  background: var(--ui-glass-control);
  padding: 0.375rem 0.625rem;
  color: var(--foreground);
  font-size: 0.75rem;
  font-weight: 500;
  transition: var(--hardcore-transition);
  -webkit-backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
  backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
}

[data-hardcore-sketch-edit-actions] button:hover {
  background: var(--accent);
}

[data-hardcore-sketch-confirm]:not(:disabled):hover {
  filter: brightness(0.94);
}

[data-hardcore-sketch-confirm] {
  border-color: color-mix(in srgb, var(--ring) 65%, var(--border)) !important;
  background: var(--primary) !important;
  color: var(--primary-foreground) !important;
}

[data-hardcore-sketch-confirm]:disabled {
  opacity: 0.55;
}

[data-hardcore-sketch-dimension] {
  position: absolute;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  transform: translate(-50%, -50%);
  border: 1px solid color-mix(in srgb, var(--ring) 45%, var(--border));
  border-radius: var(--hardcore-radius-sm);
  background: var(--ui-glass-control);
  padding: 0.1875rem 0.25rem;
  -webkit-backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
  backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
  box-shadow: var(--ui-shadow-soft);
  font-size: var(--hardcore-text-tiny);
  pointer-events: auto;
}

[data-hardcore-sketch-dimension] input {
  width: 3.75rem;
  border: 0;
  background: transparent;
  color: var(--foreground);
  font: inherit;
  font-variant-numeric: tabular-nums;
  outline: none;
  text-align: right;
}

[data-hardcore-sketch-dimension]:focus-within {
  border-color: var(--ring);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--ring) 28%, transparent);
}

[data-hardcore-sketch-help] {
  position: absolute;
  z-index: 2;
  bottom: 0.75rem;
  left: 50%;
  max-width: calc(100% - 1.5rem);
  transform: translateX(-50%);
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-sm);
  background: var(--ui-glass-control);
  padding: 0.25rem 0.625rem;
  color: var(--muted-foreground);
  font-size: var(--hardcore-text-tiny);
  text-align: center;
  white-space: normal;
  pointer-events: auto;
  -webkit-backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
  backdrop-filter: blur(var(--ui-glass-blur)) saturate(var(--ui-glass-saturation));
}

@media (max-width: 360px) {
  [data-hardcore-sketch-edit-header] {
    right: 8rem;
  }

  [data-hardcore-sketch-edit-header] span {
    display: none;
  }

  [data-hardcore-sketch-edit-actions] button {
    min-width: 3.25rem;
    padding-inline: 0.5rem;
  }
}

[data-hardcore-model-tree-view="design"] [data-file-sheet-tab="tree"],
[data-hardcore-model-tree-view="geometry"] [data-file-sheet-tab="features"] {
  border-bottom-color: transparent !important;
  background: transparent !important;
  color: var(--muted-foreground) !important;
}

[data-hardcore-model-tree-view="design"] [data-file-sheet-tab="features"],
[data-hardcore-model-tree-view="geometry"] [data-file-sheet-tab="tree"] {
  border-bottom-color: var(--primary) !important;
  background: color-mix(in srgb, var(--accent) 40%, transparent) !important;
  color: var(--foreground) !important;
}

[data-hardcore-feature-history-group] {
  position: relative;
}

[data-hardcore-feature-history-group] > summary {
  display: flex;
  align-items: center;
  cursor: pointer;
  list-style: none;
  min-height: 1.75rem;
  margin: 0.0625rem 0.25rem;
  border-radius: var(--hardcore-radius-sm);
  padding: 0.1875rem 0.375rem 0.1875rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  transition: var(--hardcore-transition);
}

[data-hardcore-feature-history-group] > summary::-webkit-details-marker {
  display: none;
}

[data-hardcore-feature-history-group] > summary::before {
  content: "";
  display: inline-block;
  width: 0;
  height: 0;
  margin-right: 0.4375rem;
  border-top: 0.25rem solid transparent;
  border-bottom: 0.25rem solid transparent;
  border-left: 0.3125rem solid var(--muted-foreground);
  transform-origin: center;
  transition: transform 120ms ease;
}

[data-hardcore-feature-history-group][open] > summary::before {
  transform: rotate(90deg);
}

[data-hardcore-feature-history-children] {
  position: relative;
  margin-left: 1rem;
  border-left: 1px solid color-mix(in srgb, var(--sidebar-border) 80%, transparent);
}

[data-hardcore-feature-history-root] {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.375rem;
  min-height: 2rem;
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid color-mix(in srgb, var(--sidebar-border) 70%, transparent);
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--sidebar-foreground);
}

[data-hardcore-feature-filter-wrap] {
  padding: 0.375rem 0.5rem;
  border-bottom: 1px solid color-mix(in srgb, var(--sidebar-border) 70%, transparent);
}

[data-hardcore-feature-filter] {
  width: 100%;
  height: 1.75rem;
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-sm);
  background: var(--secondary);
  padding: 0 0.4375rem;
  color: var(--foreground);
  font-size: 0.75rem;
  transition: var(--hardcore-transition);
  outline: none;
}

[data-hardcore-feature-filter]:focus {
  border-color: var(--ring);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--ring) 25%, transparent);
}

[data-hardcore-tree-icon] {
  display: inline-flex;
  width: 0.875rem;
  height: 0.875rem;
  flex: none;
  align-items: center;
  justify-content: center;
  font-family: var(--font-sans);
  font-size: var(--hardcore-text-tiny);
  font-weight: 700;
  line-height: 1;
}

[data-hardcore-tree-icon="model"] { color: var(--chart-2); }
[data-hardcore-tree-icon="group"] { color: var(--chart-4); }
[data-hardcore-tree-icon="builder"] { color: var(--chart-1); }
[data-hardcore-tree-icon="sketch"] { color: var(--chart-4); }
[data-hardcore-tree-icon="primitive"] { color: var(--primary); }
[data-hardcore-tree-icon="operation"] { color: var(--chart-3); }
[data-hardcore-tree-icon="assembly"] { color: var(--chart-5); }
[data-hardcore-tree-icon="parameter"] {
  color: var(--muted-foreground);
  font-size: var(--hardcore-text-tiny);
}

[data-hardcore-feature-history-row] {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.375rem;
  min-height: 1.75rem;
  width: calc(100% - 0.5rem);
  margin: 0.0625rem 0.25rem;
  border: 0;
  border-radius: var(--hardcore-radius-sm);
  background: transparent;
  padding: 0.1875rem 0.5rem 0.1875rem 0.625rem;
  font-size: 0.75rem;
  text-align: left;
  color: var(--sidebar-foreground);
  outline: none;
  transition: var(--hardcore-transition);
}

[data-hardcore-feature-history-row]:hover,
[data-hardcore-feature-history-group] > summary:hover {
  background: color-mix(in srgb, var(--accent) 58%, transparent);
}

[data-hardcore-feature-history-row][data-hardcore-selected="true"] {
  background: color-mix(in srgb, var(--ring) 22%, var(--accent));
  outline: 1px solid color-mix(in srgb, var(--ring) 42%, transparent);
  outline-offset: -1px;
}

[data-hardcore-feature-history-row]:focus-visible,
[data-hardcore-feature-history-group] > summary:focus-visible {
  box-shadow: inset 0 0 0 1px var(--ring);
}

[data-hardcore-feature-history-row][data-hardcore-selected="true"] +
  [data-hardcore-parameter-control],
[data-hardcore-feature-node][data-hardcore-selected="true"]
  [data-hardcore-parameter-control] {
  border-left-color: var(--ring);
}

[data-hardcore-feature-node] > summary {
  cursor: pointer;
  list-style: none;
}

[data-hardcore-feature-node] > summary::-webkit-details-marker {
  display: none;
}

[data-hardcore-feature-node] > summary::before {
  content: "";
  width: 0;
  height: 0;
  flex: none;
  border-top: 0.21875rem solid transparent;
  border-bottom: 0.21875rem solid transparent;
  border-left: 0.275rem solid var(--muted-foreground);
  transition: transform 120ms ease;
}

[data-hardcore-feature-node][open] > summary::before {
  transform: rotate(90deg);
}

[data-hardcore-feature-node-plain]::before {
  content: "";
  width: 0.275rem;
  flex: none;
}

[data-hardcore-editable-marker] {
  min-width: 2.25rem;
  flex: none;
  color: var(--muted-foreground);
  font-size: var(--hardcore-text-tiny);
  font-weight: 500;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

[data-hardcore-feature-history-empty] {
  padding: 1rem 0.75rem;
  color: var(--muted-foreground);
  font-size: 0.75rem;
  text-align: center;
}

[data-hardcore-parameter-control] {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 0.25rem;
  padding: 0.375rem 0.5rem 0.5rem 2.25rem;
  background: color-mix(in srgb, var(--accent) 24%, transparent);
}

[data-hardcore-parameter-control][data-hardcore-dirty="true"] {
  background: color-mix(in srgb, var(--ring) 15%, var(--accent));
}

[data-hardcore-feature-node] [data-hardcore-parameter-control],
[data-hardcore-feature-history-children] > [data-hardcore-parameter-control] {
  border-left: 1px solid color-mix(in srgb, var(--ring) 32%, var(--sidebar-border));
}

[data-hardcore-feature-history-panel] [data-hardcore-parameter-control] {
  padding-top: 0.25rem;
  padding-bottom: 0.25rem;
}

[data-hardcore-design-mode-view="features"] [data-hardcore-parameter-range] {
  display: none;
}

[data-hardcore-parameter-control] label {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.25rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.75rem;
  color: var(--sidebar-foreground);
}

[data-hardcore-parameter-origin] {
  flex: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  padding: 0 0.25rem;
  color: var(--muted-foreground);
  font-size: var(--hardcore-text-micro);
  font-weight: 500;
}

[data-hardcore-parameter-number] {
  width: 4.25rem;
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-sm);
  background: var(--secondary);
  padding: 0.1875rem 0.25rem;
  color: var(--foreground);
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
  outline: none;
  transition: var(--hardcore-transition);
}

[data-hardcore-parameter-number]:focus-visible {
  border-color: var(--ring);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--ring) 25%, transparent);
}

[data-hardcore-parameter-range] {
  grid-column: 1 / -1;
  width: 100%;
  accent-color: var(--foreground);
}

[data-hardcore-parameter-unit] {
  width: 1.5rem;
  font-size: var(--hardcore-text-tiny);
  color: var(--muted-foreground);
}

[data-hardcore-apply-parameters] {
  flex: none;
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-sm);
  background: var(--primary);
  padding: 0.1875rem 0.4375rem;
  color: var(--primary-foreground);
  font-size: var(--hardcore-text-tiny);
  font-weight: 500;
  transition: var(--hardcore-transition);
}

[data-hardcore-revert-parameters] {
  flex: none;
  border: 1px solid var(--border);
  border-radius: var(--hardcore-radius-sm);
  background: transparent;
  padding: 0.1875rem 0.4375rem;
  color: var(--foreground);
  font-size: var(--hardcore-text-tiny);
  font-weight: 500;
  transition: var(--hardcore-transition);
}

[data-hardcore-apply-parameters]:not(:disabled):hover,
[data-hardcore-revert-parameters]:not(:disabled):hover {
  border-color: var(--ring);
}

[data-hardcore-apply-parameters]:disabled,
[data-hardcore-revert-parameters]:disabled {
  cursor: default;
  background: var(--muted);
  color: var(--muted-foreground);
  opacity: 0.7;
}

`;
}

function viewerThemePayload(theme: CadViewerHostTheme): object {
  const background = {
    type: 'solid',
    solidColor: theme.scene,
    linearStart: theme.scene,
    linearEnd: theme.scene,
    radialInner: theme.scene,
    radialOuter: theme.scene,
  };
  const floor = {
    color: theme.scene,
    gridCenterColor: theme.sceneGrid,
    gridCellColor: theme.sceneGrid,
    grid: {
      centerColor: theme.sceneGrid,
      cellColor: theme.sceneGrid,
    },
    axis: { color: theme.sceneGrid },
  };
  return {
    version: 12,
    themeId: 'custom',
    custom: {
      colorMode: theme.dark ? 'dark' : 'light',
      background,
      floor,
      modeColors: {
        light: { background, floor },
        dark: { background, floor },
      },
    },
  };
}

export function buildCadViewerIntegrationScript(theme: CadViewerHostTheme): string {
  const styleText = integrationStyles(theme);
  const themePayload = JSON.stringify(viewerThemePayload(theme));
  const viewerColorMode = theme.dark ? 'dark' : 'light';
  return `(() => {
    const styleId = ${JSON.stringify(INTEGRATION_STYLE_ID)};
    let style = document.getElementById(styleId);
    if (!(style instanceof HTMLStyleElement)) {
      style = document.createElement('style');
      style.id = styleId;
      document.head.appendChild(style);
    }
    style.textContent = ${JSON.stringify(styleText)};

    // Keep viewer chrome native, but let the host's single design-system file
    // supply scene, grid, and radius tokens for the embedded presentation.
    const viewerColorMode = ${JSON.stringify(viewerColorMode)};
    document.documentElement.classList.toggle('dark', viewerColorMode === 'dark');
    document.documentElement.dataset.theme = viewerColorMode;
    document.documentElement.style.colorScheme = viewerColorMode;

    const publishSelectedReference = () => {
      const copyButton = [...document.querySelectorAll('button')].find((candidate) => {
        if (candidate.tagName !== 'BUTTON' || candidate.disabled) return false;
        const label = [candidate.textContent, candidate.getAttribute('aria-label')]
          .filter(Boolean)
          .join(' ')
          .trim();
        return /^Copy(?:\\s+reference|\\s+.+#\\S+)$/i.test(label);
      });
      if (!copyButton || copyButton.tagName !== 'BUTTON') return;
      const copyLabel = [copyButton.textContent, copyButton.getAttribute('aria-label')]
        .filter(Boolean)
        .join(' ')
        .trim();
      const selectedRow = document.querySelector('[role="row"][aria-selected="true"]');
      const selectedDescription = selectedRow
        ? [
            selectedRow.getAttribute('aria-label'),
            selectedRow.getAttribute('aria-description'),
            selectedRow.getAttribute('title'),
            selectedRow.textContent,
          ]
            .filter(Boolean)
            .join(' ')
        : '';
      let nearbyDescription = '';
      let nearbyElement = copyButton.parentElement;
      for (let depth = 0; depth < 6 && nearbyElement; depth += 1) {
        nearbyDescription += ' ' + (nearbyElement.textContent || '');
        nearbyElement = nearbyElement.parentElement;
      }
      const selectedIdentifier = selectedDescription.match(
        /\\b(o\\d+(?:\\.\\d+)+(?:\\.[a-z]\\d+)?)(?=Copy|[^\\w.]|$)/i
      )?.[1];
      const selectedReference =
        selectedDescription.match(/(?:Ref:\\s*)?(#[\\w.-]+)/)?.[1] ||
        (selectedIdentifier ? '#' + selectedIdentifier : undefined) ||
        (() => {
          const identifier = nearbyDescription.match(
            /\\b(o\\d+(?:\\.\\d+)+(?:\\.[a-z]\\d+)?)(?=Copy|[^\\w.]|$)/i
          )?.[1];
          return identifier ? '#' + identifier : undefined;
        })();
      const reference = /#\\S+/.test(copyLabel)
        ? copyLabel.replace(/^Copy\\s+/, '')
        : selectedReference;
      if (!reference || window.__hardcoreLastCadReference === reference) return;
      window.__hardcoreLastCadReference = reference;
      copyButton.click();
      window.__hardcoreCadReferenceCommand = {
        requestId: window.crypto?.randomUUID?.() || String(Date.now()),
        reference,
      };
    };
    const syncViewerChrome = () => {
      const viewerToggle = document.querySelector('button[aria-label="Toggle CAD Viewer"]');
      const viewerHeader = viewerToggle?.closest('header');
      if (
        viewerHeader instanceof HTMLElement &&
        !viewerHeader.hasAttribute(${JSON.stringify(INTEGRATION_HEADER_ATTRIBUTE)})
      ) {
        viewerHeader.setAttribute(${JSON.stringify(INTEGRATION_HEADER_ATTRIBUTE)}, '');
      }
      publishSelectedReference();
    };
    syncViewerChrome();
    if (!window.__hardcoreCadViewerIntegrationObserver) {
      const observer = new window.MutationObserver(syncViewerChrome);
      observer.observe(document.documentElement, {
        attributes: true,
        childList: true,
        characterData: true,
        subtree: true,
      });
      window.__hardcoreCadViewerIntegrationObserver = observer;
    }

    const storageKey = 'cad-viewer:theme';
    const previousTheme = window.localStorage.getItem(storageKey);
    const nextTheme = ${JSON.stringify(themePayload)};
    if (previousTheme !== nextTheme) {
      window.localStorage.setItem(storageKey, nextTheme);
      window.dispatchEvent(new StorageEvent('storage', {
        key: storageKey,
        oldValue: previousTheme,
        newValue: nextTheme,
        storageArea: window.localStorage
      }));
    }
    return true;
  })()`;
}

export interface CadViewerParameterCommand {
  requestId: string;
  sourceHash: string;
  values: Record<string, number>;
}

export interface CadViewerReferenceCommand {
  requestId: string;
  reference: string;
}

export function buildCadViewerConsumeReferenceCommandScript(): string {
  return `(() => {
    const command = window.__hardcoreCadReferenceCommand;
    if (command) {
      delete window.__hardcoreCadReferenceCommand;
      window.__hardcoreLastConsumedCadReference = command.reference;
      return command;
    }
    const selectedRow = document.querySelector('[role="row"][aria-selected="true"]');
    const copyButton = [...document.querySelectorAll('button')].find((candidate) => {
      if (candidate.tagName !== 'BUTTON' || candidate.disabled) return false;
      const label = [candidate.textContent, candidate.getAttribute('aria-label')]
        .filter(Boolean)
        .join(' ')
        .trim();
      return /^Copy(?:\\s+reference|\\s+.+#\\S+)$/i.test(label);
    });
    const selectedDescription = [
      selectedRow?.getAttribute('aria-label'),
      selectedRow?.getAttribute('aria-description'),
      selectedRow?.getAttribute('title'),
      selectedRow?.textContent,
    ]
      .filter(Boolean)
      .join(' ');
    const copyLabel = [copyButton?.textContent, copyButton?.getAttribute('aria-label')]
      .filter(Boolean)
      .join(' ')
      .trim();
    let nearbyDescription = '';
    let nearbyElement = copyButton?.parentElement;
    for (let depth = 0; depth < 6 && nearbyElement; depth += 1) {
      nearbyDescription += ' ' + (nearbyElement.textContent || '');
      nearbyElement = nearbyElement.parentElement;
    }
    const explicitReference =
      selectedDescription.match(/(?:Ref:\\s*)?(#[\\w.-]+)/)?.[1] ||
      copyLabel.match(/^Copy\\s+(.+#\\S+)/i)?.[1];
    const identifier = (selectedDescription + ' ' + nearbyDescription).match(
      /\\b(o\\d+(?:\\.\\d+)+(?:\\.[a-z]\\d+)?)(?=Copy|[^\\w.]|$)/i
    )?.[1];
    const reference = explicitReference || (identifier ? '#' + identifier : null);
    if (!reference || window.__hardcoreLastConsumedCadReference === reference) return null;
    window.__hardcoreLastCadReference = reference;
    window.__hardcoreLastConsumedCadReference = reference;
    copyButton?.click();
    return {
      requestId: window.crypto?.randomUUID?.() || String(Date.now()),
      reference,
    };
  })()`;
}

export function buildCadViewerToolbarActionScript(label: 'Draw' | 'Copy screenshot'): string {
  return `(() => {
    const button = document.querySelector('button[aria-label=${JSON.stringify(label)}]');
    if (!button || button.tagName !== 'BUTTON' || button.disabled) return false;
    button.click();
    return true;
  })()`;
}

export function buildCadViewerConsumeParameterCommandScript(): string {
  return `(() => {
    const command = window.__hardcoreCadParameterCommand;
    if (!command) return null;
    delete window.__hardcoreCadParameterCommand;
    const handledKey = 'hardcore:cad-parameter-command:' + command.requestId;
    try {
      if (window.sessionStorage.getItem(handledKey) === 'handled') return null;
      window.sessionStorage.setItem(handledKey, 'handled');
    } catch {}
    return command;
  })()`;
}

export function buildCadViewerFeatureHistoryReadyScript(signature: string): string {
  return `(() => {
    const panel = document.querySelector('[data-hardcore-feature-history-panel]');
    return panel instanceof HTMLElement &&
      panel.getAttribute('data-hardcore-feature-history-signature') === ${JSON.stringify(signature)};
  })()`;
}

export function buildCadViewerFeatureHistoryScript(
  history: CadSourceHistory,
  sourceHash: string
): string {
  const payload = JSON.stringify({
    groups: history.groups,
    designGroups: buildCadDesignTree(history),
    parameters: history.parameters,
    diagnostics: history.diagnostics,
    sourceHash,
  });
  return `(() => {
    window.__hardcoreCloseSketchEditor?.();
    document.querySelector('[data-hardcore-sketch-edit-overlay]')?.remove();
    for (const canvas of document.querySelectorAll('canvas[data-hardcore-sketch-dimmed]')) {
      if (!(canvas instanceof HTMLCanvasElement)) continue;
      canvas.style.opacity = canvas.getAttribute('data-hardcore-previous-opacity') || '';
      canvas.removeAttribute('data-hardcore-previous-opacity');
      canvas.removeAttribute('data-hardcore-sketch-dimmed');
    }
    const pane = document.querySelector('[data-file-sheet-tab-pane="top"]');
    const treeTab = pane?.querySelector('button[data-file-sheet-tab="tree"]');
    const treePanel = pane?.querySelector('[data-file-sheet-tab-panel="tree"]');
    const tabList = treeTab?.closest('[role="tablist"]');
    if (!(pane instanceof HTMLElement) || !(treeTab instanceof HTMLButtonElement) ||
        !(treePanel instanceof HTMLElement) || !(tabList instanceof HTMLElement)) return false;

    const data = ${payload};
    const featureCount = data.designGroups.reduce((count, group) => count + group.nodes.length, 0);
    treeTab.replaceChildren();
    const geometryLabel = document.createElement('span');
    geometryLabel.className = 'min-w-0 truncate';
    geometryLabel.textContent = 'Geometry';
    treeTab.appendChild(geometryLabel);
    treeTab.setAttribute('aria-label', 'Geometry topology');
    treeTab.title = 'Raw STEP bodies, faces, and edges';

    let tabWrap = pane.querySelector('[data-hardcore-feature-history-tab-wrap]');
    let featureTab = pane.querySelector('button[data-file-sheet-tab="features"]');
    if (!(tabWrap instanceof HTMLElement) || !(featureTab instanceof HTMLButtonElement)) {
      tabWrap = document.createElement('span');
      tabWrap.setAttribute('data-hardcore-feature-history-tab-wrap', '');
      tabWrap.className = 'relative flex items-stretch';
      featureTab = document.createElement('button');
      featureTab.type = 'button';
      featureTab.setAttribute('role', 'tab');
      featureTab.setAttribute('aria-selected', 'false');
      featureTab.setAttribute('data-file-sheet-tab', 'features');
      featureTab.className = treeTab.className;
      tabWrap.appendChild(featureTab);
      tabList.appendChild(tabWrap);
    }
    const treeTabWrap = treeTab.parentElement;
    if (treeTabWrap?.parentElement === tabList && tabWrap.nextElementSibling !== treeTabWrap) {
      tabList.insertBefore(tabWrap, treeTabWrap);
    }
    featureTab.replaceChildren();
    featureTab.setAttribute('aria-label', 'Design build sequence');
    featureTab.title = 'Source-backed construction steps';
    const tabLabel = document.createElement('span');
    tabLabel.className = 'min-w-0 truncate';
    tabLabel.textContent = 'Design';
    const tabCount = document.createElement('span');
    tabCount.className = 'text-[10px] tabular-nums text-muted-foreground';
    tabCount.textContent = String(featureCount);
    featureTab.append(tabLabel, tabCount);

    pane.querySelector('[data-hardcore-parameters-tab-wrap]')?.remove();

    let panel = pane.querySelector('[data-hardcore-feature-history-panel]');
    if (!(panel instanceof HTMLElement)) {
      panel = document.createElement('div');
      panel.setAttribute('data-hardcore-feature-history-panel', '');
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-label', 'Design build sequence');
      panel.tabIndex = 0;
      treePanel.insertAdjacentElement('afterend', panel);
    }
    const hadFeatureTree = panel.hasAttribute('data-hardcore-feature-tree-ready');
    const previouslyOpenGroups = new Set(
      [...panel.querySelectorAll('[data-hardcore-feature-history-group][open]')]
        .map((item) => item.getAttribute('data-hardcore-feature-history-group'))
        .filter(Boolean)
    );
    const previouslyOpenFeatures = new Set(
      [...panel.querySelectorAll('[data-hardcore-feature-node][open]')]
        .map((item) => item.getAttribute('data-hardcore-feature-node'))
        .filter(Boolean)
    );
    const previouslySelectedFeature = panel
      .querySelector('[data-hardcore-feature-history-row][data-hardcore-selected="true"]')
      ?.getAttribute('data-hardcore-feature-id');
    panel.replaceChildren();
    panel.setAttribute('data-hardcore-feature-tree-ready', '');
    panel.setAttribute('data-hardcore-feature-history-signature', data.sourceHash);

    pane.querySelector('[data-hardcore-parameters-panel]')?.remove();

    const drafts = new Map(data.parameters.map((parameter) => [parameter.id, parameter.defaultValue]));
    const parametersById = new Map(data.parameters.map((parameter) => [parameter.id, parameter]));
    const controls = new Map();
    const applyButtons = [];
    const revertButtons = [];
    const statusNotes = [];
    let activeSketchEditor = null;
    let refreshActiveSketchEditor = () => {};
    let controlIndex = 0;
    const parameterGroupIds = (parameter) => Array.isArray(parameter.groupIds) ? parameter.groupIds : [];
    const parameterFeatureIds = (parameter) => Array.isArray(parameter.featureIds) ? parameter.featureIds : [];
    const changedValues = () => Object.fromEntries(
      data.parameters
        .filter((parameter) => drafts.get(parameter.id) !== parameter.defaultValue)
        .map((parameter) => [parameter.id, drafts.get(parameter.id)])
    );
    const updateApplyState = () => {
      const count = Object.keys(changedValues()).length;
      for (const applyButton of applyButtons) {
        applyButton.disabled = count === 0;
        applyButton.textContent = count === 0 ? 'Apply' : 'Apply ' + count;
      }
      for (const revertButton of revertButtons) revertButton.disabled = count === 0;
      for (const statusNote of statusNotes) {
        statusNote.textContent = count === 0
          ? featureCount + ' features · ' + data.parameters.length + ' editable dimensions'
          : count + ' change' + (count === 1 ? '' : 's') + ' pending';
      }
      for (const parameter of data.parameters) {
        const dirty = drafts.get(parameter.id) !== parameter.defaultValue;
        for (const control of controls.get(parameter.id) ?? []) {
          control.element.setAttribute('data-hardcore-dirty', dirty ? 'true' : 'false');
        }
      }
    };
    const setDraft = (parameter, rawValue) => {
      if (!Number.isFinite(rawValue)) return;
      const value = Math.min(parameter.max, Math.max(parameter.min, rawValue));
      drafts.set(parameter.id, value);
      for (const control of controls.get(parameter.id) ?? []) {
        control.number.value = String(value);
        control.range.value = String(value);
      }
      updateApplyState();
      refreshActiveSketchEditor();
    };
    const setDraftFromNumberInput = (parameter, input, commit = false) => {
      if (input.value.trim() === '') {
        if (commit) input.value = String(drafts.get(parameter.id));
        return;
      }
      const rawValue = Number(input.value);
      if (!Number.isFinite(rawValue)) {
        if (commit) input.value = String(drafts.get(parameter.id));
        return;
      }
      if (!commit && (rawValue < parameter.min || rawValue > parameter.max)) return;
      setDraft(parameter, rawValue);
    };
    const appendParameterControl = (parent, parameter, labelOverride) => {
      const control = document.createElement('div');
      control.setAttribute('data-hardcore-parameter-control', parameter.id);
      const label = document.createElement('label');
      const inputId = 'hardcore-parameter-' + parameter.id + '-' + (++controlIndex);
      label.htmlFor = inputId;
      label.appendChild(document.createTextNode(labelOverride || parameter.label));
      if (parameter.origin && parameter.origin !== 'declared') {
        const origin = document.createElement('span');
        origin.setAttribute('data-hardcore-parameter-origin', parameter.origin);
        origin.textContent = parameter.origin === 'function-parameter' ? 'Model' : 'Auto';
        origin.title = parameter.origin === 'function-parameter'
          ? 'Authored geometry parameter on the @step model function'
          : parameter.origin === 'feature-literal'
            ? 'Direct editable value from this feature call'
            : 'Dimension-like source variable used by the model';
        label.appendChild(origin);
      }
      label.title = parameter.description || parameter.symbol;
      const number = document.createElement('input');
      number.id = inputId;
      number.type = 'number';
      number.min = String(parameter.min);
      number.max = String(parameter.max);
      number.step = String(parameter.step);
      number.value = String(parameter.defaultValue);
      number.setAttribute('data-hardcore-parameter-number', '');
      number.setAttribute('aria-label', parameter.label);
      const unit = document.createElement('span');
      unit.setAttribute('data-hardcore-parameter-unit', '');
      unit.textContent = parameter.unit || '';
      const range = document.createElement('input');
      range.type = 'range';
      range.min = String(parameter.min);
      range.max = String(parameter.max);
      range.step = String(parameter.step);
      range.value = String(parameter.defaultValue);
      range.setAttribute('data-hardcore-parameter-range', '');
      range.setAttribute('aria-label', parameter.label + ' slider');
      number.addEventListener('input', () => setDraftFromNumberInput(parameter, number));
      number.addEventListener('change', () => setDraftFromNumberInput(parameter, number, true));
      range.addEventListener('input', () => setDraft(parameter, Number(range.value)));
      number.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        applyButtons.find((button) => !button.disabled)?.click();
      });
      control.append(label, number, unit, range);
      parent.appendChild(control);
      const parameterControls = controls.get(parameter.id) ?? [];
      parameterControls.push({ element: control, number, range });
      controls.set(parameter.id, parameterControls);
    };

    const resetDrafts = () => {
      for (const parameter of data.parameters) {
        drafts.set(parameter.id, parameter.defaultValue);
        for (const control of controls.get(parameter.id) ?? []) {
          control.number.disabled = false;
          control.range.disabled = false;
          control.number.value = String(parameter.defaultValue);
          control.range.value = String(parameter.defaultValue);
        }
      }
      updateApplyState();
      refreshActiveSketchEditor();
    };

    const appendPanelHeader = (parent, title, note) => {
      const header = document.createElement('div');
      header.style.display = 'flex';
      header.style.alignItems = 'center';
      header.style.gap = '0.5rem';
      header.style.padding = '0.5rem';
      header.style.borderBottom = '1px solid color-mix(in srgb, var(--sidebar-border) 70%, transparent)';
      const copy = document.createElement('div');
      copy.style.minWidth = '0';
      copy.style.flex = '1';
      const heading = document.createElement('div');
      heading.style.fontSize = '0.6875rem';
      heading.style.fontWeight = '500';
      heading.textContent = title;
      const description = document.createElement('div');
      description.style.marginTop = '0.125rem';
      description.style.fontSize = '0.625rem';
      description.style.color = 'var(--muted-foreground)';
      description.textContent = note;
      statusNotes.push(description);
      copy.append(heading, description);
      header.appendChild(copy);
      if (data.parameters.length > 0) {
        const actions = document.createElement('div');
        actions.style.display = 'flex';
        actions.style.alignItems = 'center';
        actions.style.gap = '0.25rem';
        const revertButton = document.createElement('button');
        revertButton.type = 'button';
        revertButton.disabled = true;
        revertButton.setAttribute('data-hardcore-revert-parameters', '');
        revertButton.textContent = 'Revert';
        revertButton.title = 'Discard pending parameter changes';
        revertButton.addEventListener('click', resetDrafts);
        revertButtons.push(revertButton);
        const applyButton = document.createElement('button');
        applyButton.type = 'button';
        applyButton.disabled = true;
        applyButton.setAttribute('data-hardcore-apply-parameters', '');
        applyButton.textContent = 'Apply';
        applyButton.addEventListener('click', () => {
          const values = changedValues();
          if (Object.keys(values).length === 0) return;
          const requestId = globalThis.crypto?.randomUUID?.() ?? String(Date.now());
          window.__hardcoreCadParameterCommand = {
            requestId,
            sourceHash: data.sourceHash,
            values,
          };
          for (const button of applyButtons) {
            button.disabled = true;
            button.textContent = 'Applying…';
          }
          for (const parameterControls of controls.values()) {
            for (const control of parameterControls) {
              control.number.disabled = true;
              control.range.disabled = true;
            }
          }
          if (activeSketchEditor) {
            for (const control of activeSketchEditor.overlay.querySelectorAll('input, button')) {
              control.disabled = true;
            }
            const confirm = activeSketchEditor.overlay.querySelector('[data-hardcore-sketch-confirm]');
            if (confirm instanceof HTMLButtonElement) confirm.textContent = 'Applying…';
          }
        });
        applyButtons.push(applyButton);
        actions.append(revertButton, applyButton);
        header.appendChild(actions);
      }
      parent.appendChild(header);
    };

    appendPanelHeader(
      panel,
      'Design',
      featureCount + ' features · ' + data.parameters.length + ' editable dimensions'
    );

    const designModeStorageKey = 'hardcore:design-mode';
    const designModeSwitch = document.createElement('div');
    designModeSwitch.setAttribute('data-hardcore-design-mode-switch', '');
    designModeSwitch.setAttribute('role', 'group');
    designModeSwitch.setAttribute('aria-label', 'Design view');
    const featuresModeButton = document.createElement('button');
    featuresModeButton.type = 'button';
    featuresModeButton.setAttribute('data-hardcore-design-mode', 'features');
    featuresModeButton.textContent = 'Features';
    featuresModeButton.title = 'Edit dimensions in the construction tree';
    const slidersModeButton = document.createElement('button');
    slidersModeButton.type = 'button';
    slidersModeButton.setAttribute('data-hardcore-design-mode', 'sliders');
    slidersModeButton.textContent = 'Sliders';
    slidersModeButton.title = data.parameters.length > 0
      ? 'Adjust all editable dimensions'
      : 'No editable dimensions are exposed for this model';
    slidersModeButton.disabled = data.parameters.length === 0;
    designModeSwitch.append(featuresModeButton, slidersModeButton);
    panel.appendChild(designModeSwitch);

    const featureContent = document.createElement('div');
    featureContent.setAttribute('data-hardcore-design-mode-view', 'features');
    const slidersContent = document.createElement('div');
    slidersContent.setAttribute('data-hardcore-design-mode-view', 'sliders');
    panel.append(featureContent, slidersContent);

    const activateDesignMode = (mode) => {
      const nextMode = mode === 'sliders' && data.parameters.length > 0 ? 'sliders' : 'features';
      featuresModeButton.setAttribute('aria-pressed', nextMode === 'features' ? 'true' : 'false');
      slidersModeButton.setAttribute('aria-pressed', nextMode === 'sliders' ? 'true' : 'false');
      featureContent.hidden = nextMode !== 'features';
      slidersContent.hidden = nextMode !== 'sliders';
      try {
        window.sessionStorage.setItem(designModeStorageKey, nextMode);
      } catch {}
    };
    featuresModeButton.addEventListener('click', () => activateDesignMode('features'));
    slidersModeButton.addEventListener('click', () => activateDesignMode('sliders'));

    const sketchViewportCanvas = () => [...document.querySelectorAll('canvas')]
      .map((canvas) => ({ canvas, rect: canvas.getBoundingClientRect() }))
      .filter(({ rect }) => rect.width > 240 && rect.height > 180)
      .sort((left, right) => (right.rect.width * right.rect.height) - (left.rect.width * left.rect.height))[0]
      ?.canvas ?? null;
    const resolveViewerRuntime = (canvas) => {
      let element = canvas;
      while (element) {
        const fiberKey = Object.keys(element).find((key) => key.startsWith('__reactFiber$'));
        let fiber = fiberKey ? element[fiberKey] : null;
        while (fiber) {
          let hook = fiber.memoizedState;
          while (hook) {
            const candidate = hook.memoizedState?.current;
            if (candidate?.THREE && candidate?.scene && candidate?.camera &&
                candidate?.modelGroup && candidate?.requestRender) return candidate;
            hook = hook.next;
          }
          fiber = fiber.return;
        }
        element = element.parentElement;
      }
      return null;
    };
    const createViewerBridge = () => {
      const provided = window.__hardcoreCadViewerBridge;
      if (provided?.canvas && provided?.renderSketch && provided?.project &&
          provided?.setGhosted && provided?.dispose) return provided;
      const canvas = sketchViewportCanvas();
      if (!(canvas instanceof HTMLCanvasElement)) return null;
      const runtime = resolveViewerRuntime(canvas);
      if (!runtime) return null;
      const THREE = runtime.THREE;
      let sketchGroup = null;
      const materialStates = new Map();
      const disposeObject = (object) => {
        object?.traverse?.((child) => {
          child.geometry?.dispose?.();
          const materials = Array.isArray(child.material) ? child.material : [child.material];
          for (const material of materials) material?.dispose?.();
        });
      };
      const clearSketch = () => {
        if (!sketchGroup) return;
        runtime.scene.remove(sketchGroup);
        disposeObject(sketchGroup);
        sketchGroup = null;
      };
      const setGhosted = (ghosted) => {
        runtime.modelGroup.traverse((object) => {
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          for (const material of materials) {
            if (!material) continue;
            if (ghosted && !materialStates.has(material)) {
              materialStates.set(material, {
                transparent: material.transparent,
                opacity: material.opacity,
                depthWrite: material.depthWrite,
              });
              material.transparent = true;
              material.opacity = 0.22;
              material.depthWrite = false;
              material.needsUpdate = true;
            } else if (!ghosted && materialStates.has(material)) {
              const previous = materialStates.get(material);
              material.transparent = previous.transparent;
              material.opacity = previous.opacity;
              material.depthWrite = previous.depthWrite;
              material.needsUpdate = true;
            }
          }
        });
        if (!ghosted) materialStates.clear();
        runtime.requestRender();
      };
      const renderSketch = (spec) => {
        clearSketch();
        runtime.modelGroup.updateMatrixWorld(true);
        sketchGroup = new THREE.Group();
        sketchGroup.name = 'HardcoreSketchEdit';
        sketchGroup.matrix.copy(runtime.modelGroup.matrixWorld);
        sketchGroup.matrixAutoUpdate = false;
        const grid = new THREE.GridHelper(
          Math.max(spec.extent * 1.5, 10),
          20,
          0x64748b,
          0x94a3b8
        );
        grid.position.set(...spec.origin);
        if (spec.plane === 'XY') grid.rotation.x = Math.PI / 2;
        if (spec.plane === 'YZ') grid.rotation.z = Math.PI / 2;
        const gridMaterials = Array.isArray(grid.material) ? grid.material : [grid.material];
        for (const material of gridMaterials) {
          material.transparent = true;
          material.opacity = 0.28;
          material.depthWrite = false;
        }
        grid.renderOrder = 900;
        sketchGroup.add(grid);
        if (spec.segments.length > 0) {
          const points = spec.segments.flatMap((segment) => segment)
            .map((point) => new THREE.Vector3(...point));
          const geometry = new THREE.BufferGeometry().setFromPoints(points);
          const material = new THREE.LineBasicMaterial({
            color: 0x2563eb,
            transparent: true,
            opacity: 0.98,
            depthTest: false,
            depthWrite: false,
          });
          const lines = new THREE.LineSegments(geometry, material);
          lines.renderOrder = 1000;
          sketchGroup.add(lines);
        }
        runtime.scene.add(sketchGroup);
        runtime.requestRender();
      };
      const project = (point) => {
        runtime.modelGroup.updateMatrixWorld(true);
        runtime.camera.updateMatrixWorld?.(true);
        const projected = new THREE.Vector3(...point)
          .applyMatrix4(runtime.modelGroup.matrixWorld)
          .project(runtime.camera);
        const rect = canvas.getBoundingClientRect();
        return {
          x: ((projected.x + 1) / 2) * rect.width,
          y: ((1 - projected.y) / 2) * rect.height,
          visible: projected.z >= -1 && projected.z <= 1,
        };
      };
      return {
        canvas,
        renderSketch,
        project,
        setGhosted,
        dispose: () => {
          clearSketch();
          setGhosted(false);
          runtime.requestRender();
        },
      };
    };
    const closeSketchEditor = ({ revert = false } = {}) => {
      if (!activeSketchEditor) return;
      const editor = activeSketchEditor;
      activeSketchEditor = null;
      refreshActiveSketchEditor = () => {};
      window.removeEventListener('resize', editor.align);
      window.removeEventListener('keydown', editor.keydown, true);
      if (editor.animationFrame !== null) window.cancelAnimationFrame?.(editor.animationFrame);
      editor.bridge.dispose();
      editor.overlay.remove();
      if (revert) resetDrafts();
    };
    window.__hardcoreCloseSketchEditor = () => closeSketchEditor();
    const openSketchEditor = (designNode) => {
      if (designNode.kind !== 'sketch' || designNode.controls.length === 0) return;
      closeSketchEditor();
      const bridge = createViewerBridge();
      if (!bridge) return;
      const canvas = bridge.canvas;
      const viewLabel = designNode.sketchPlane === 'XZ'
        ? 'Jump to front view'
        : designNode.sketchPlane === 'YZ'
          ? 'Jump to right view'
          : 'Jump to top view';
      const viewButton = document.querySelector('[role="button"][aria-label="' + viewLabel + '"]');
      if (viewButton instanceof Element) {
        viewButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      }

      const overlay = document.createElement('div');
      overlay.setAttribute('data-hardcore-sketch-edit-overlay', '');
      overlay.setAttribute('data-hardcore-on-model', '');
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-label', 'Editing ' + designNode.label);
      const header = document.createElement('div');
      header.setAttribute('data-hardcore-sketch-edit-header', '');
      const heading = document.createElement('strong');
      heading.textContent = 'Editing ' + designNode.label;
      const plane = document.createElement('span');
      plane.style.color = 'var(--muted-foreground)';
      plane.textContent = (designNode.sketchPlane || 'XY') + ' plane';
      header.append(heading, plane);
      const actions = document.createElement('div');
      actions.setAttribute('data-hardcore-sketch-edit-actions', '');
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.textContent = 'Cancel';
      cancel.setAttribute('data-hardcore-sketch-cancel', '');
      const confirm = document.createElement('button');
      confirm.type = 'button';
      confirm.textContent = 'Done';
      confirm.setAttribute('data-hardcore-sketch-confirm', '');
      actions.append(cancel, confirm);

      const help = document.createElement('div');
      help.setAttribute('data-hardcore-sketch-help', '');
      help.textContent = 'The blue sketch is attached to the model · Esc cancels';
      overlay.append(header, actions, help);
      document.body.appendChild(overlay);

      const dimensionInputs = new Map();
      for (const control of designNode.controls) {
        const parameter = parametersById.get(control.parameterId);
        if (!parameter) continue;
        const dimension = document.createElement('label');
        dimension.setAttribute('data-hardcore-sketch-dimension', control.parameterId);
        const label = document.createElement('span');
        label.textContent = control.label;
        const input = document.createElement('input');
        input.type = 'number';
        input.min = String(parameter.min);
        input.max = String(parameter.max);
        input.step = String(parameter.step);
        input.value = String(drafts.get(parameter.id));
        input.setAttribute('aria-label', control.label + ' sketch dimension');
        const unit = document.createElement('span');
        unit.textContent = parameter.unit || '';
        input.addEventListener('input', () => setDraftFromNumberInput(parameter, input));
        input.addEventListener('change', () => setDraftFromNumberInput(parameter, input, true));
        input.addEventListener('keydown', (event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            closeSketchEditor({ revert: true });
          }
        });
        dimension.append(label, input, unit);
        overlay.appendChild(dimension);
        dimensionInputs.set(control.parameterId, { wrapper: dimension, input, control, parameter });
      }

      const align = () => {
        const rect = canvas.getBoundingClientRect();
        const treeRect = pane.getBoundingClientRect();
        const visibleWidth = treeRect.left > rect.left && treeRect.left < rect.right
          ? treeRect.left - rect.left
          : rect.width;
        overlay.style.left = rect.left + 'px';
        overlay.style.top = rect.top + 'px';
        overlay.style.width = visibleWidth + 'px';
        overlay.style.height = rect.height + 'px';
      };
      const valueFor = (...labels) => {
        const match = [...dimensionInputs.values()].find(({ control }) =>
          labels.includes(control.label.toLowerCase())
        );
        return match ? Number(drafts.get(match.parameter.id)) : null;
      };
      const origin = designNode.sketchOrigin || [0, 0, 0];
      const mapSketchPoint = (u, v) => designNode.sketchPlane === 'XZ'
        ? [origin[0] + u, origin[1], origin[2] + v]
        : designNode.sketchPlane === 'YZ'
          ? [origin[0], origin[1] + u, origin[2] + v]
          : [origin[0] + u, origin[1] + v, origin[2]];
      const sketchGeometry = () => {
        const hasRectangle = designNode.geometryNames.some((name) => /rectangle|box/i.test(name));
        const hasRoundedRectangle = designNode.geometryNames.some((name) =>
          /rectanglerounded/i.test(name)
        );
        const hasCircle = designNode.geometryNames.some((name) => /circle|cylinder|arc/i.test(name));
        const explicitLength = valueFor('length');
        const horizontal = explicitLength ?? valueFor('width') ?? 40;
        const vertical = explicitLength !== null
          ? (valueFor('width', 'height') ?? horizontal)
          : (valueFor('height') ?? horizontal);
        const diameter = valueFor('diameter');
        const radius = valueFor('radius') ?? (diameter === null ? null : diameter / 2) ??
          Math.min(horizontal, vertical) / 4;
        const segments = [];
        if (hasRectangle) {
          const corners = hasRoundedRectangle
            ? (() => {
                const cornerRadius = Math.min(radius, horizontal / 2, vertical / 2);
                const points = [];
                for (const [centerU, centerV, startAngle] of [
                  [horizontal / 2 - cornerRadius, vertical / 2 - cornerRadius, 0],
                  [-horizontal / 2 + cornerRadius, vertical / 2 - cornerRadius, Math.PI / 2],
                  [-horizontal / 2 + cornerRadius, -vertical / 2 + cornerRadius, Math.PI],
                  [horizontal / 2 - cornerRadius, -vertical / 2 + cornerRadius, Math.PI * 1.5],
                ]) {
                  for (let step = 0; step <= 8; step += 1) {
                    const angle = startAngle + (step / 8) * (Math.PI / 2);
                    points.push([
                      centerU + Math.cos(angle) * cornerRadius,
                      centerV + Math.sin(angle) * cornerRadius,
                    ]);
                  }
                }
                return points;
              })()
            : [
                [-horizontal / 2, -vertical / 2],
                [horizontal / 2, -vertical / 2],
                [horizontal / 2, vertical / 2],
                [-horizontal / 2, vertical / 2],
              ];
          for (let index = 0; index < corners.length; index += 1) {
            segments.push([
              mapSketchPoint(...corners[index]),
              mapSketchPoint(...corners[(index + 1) % corners.length]),
            ]);
          }
        }
        if (hasCircle) {
          const segmentCount = 48;
          for (let index = 0; index < segmentCount; index += 1) {
            const start = (index / segmentCount) * Math.PI * 2;
            const end = ((index + 1) / segmentCount) * Math.PI * 2;
            segments.push([
              mapSketchPoint(Math.cos(start) * radius, Math.sin(start) * radius),
              mapSketchPoint(Math.cos(end) * radius, Math.sin(end) * radius),
            ]);
          }
        }
        return {
          segments,
          horizontal,
          vertical,
          radius,
          extent: Math.max(horizontal, vertical, radius * 2, 10),
        };
      };
      const projectDimensions = (geometry) => {
        let radialIndex = 0;
        let placementIndex = 0;
        for (const { wrapper, input, control, parameter } of dimensionInputs.values()) {
          input.value = String(drafts.get(parameter.id));
          const label = control.label.toLowerCase();
          let anchor;
          let screenOffsetY = 0;
          if (label === 'length' || (label === 'width' && valueFor('length') === null)) {
            anchor = mapSketchPoint(0, geometry.vertical / 2 + geometry.extent * 0.08);
          } else if (label === 'width' || label === 'height') {
            anchor = mapSketchPoint(
              geometry.horizontal / 2 + geometry.extent * 0.08,
              0
            );
          } else if (/radius|diameter/.test(label)) {
            const angle = Math.PI / 4 + radialIndex * 0.35;
            anchor = mapSketchPoint(
              Math.cos(angle) * geometry.radius,
              Math.sin(angle) * geometry.radius
            );
            radialIndex += 1;
          } else {
            anchor = origin;
            placementIndex += 1;
            screenOffsetY = -72 * placementIndex;
          }
          const projected = bridge.project(anchor);
          wrapper.hidden = !projected || projected.visible === false;
          if (!projected) continue;
          const overlayWidth = Number.parseFloat(overlay.style.width) ||
            canvas.getBoundingClientRect().width;
          const overlayHeight = Number.parseFloat(overlay.style.height) ||
            canvas.getBoundingClientRect().height;
          wrapper.style.left = Math.max(72, Math.min(overlayWidth - 72, projected.x)) + 'px';
          wrapper.style.top = Math.max(
            52,
            Math.min(overlayHeight - 52, projected.y + screenOffsetY)
          ) + 'px';
        }
      };
      let currentGeometry = null;
      const refresh = () => {
        if (!activeSketchEditor || activeSketchEditor.overlay !== overlay) return;
        currentGeometry = sketchGeometry();
        bridge.renderSketch({
          plane: designNode.sketchPlane || 'XY',
          origin,
          extent: currentGeometry.extent,
          segments: currentGeometry.segments,
        });
        projectDimensions(currentGeometry);
        const pending = Object.keys(changedValues()).length;
        confirm.textContent = pending > 0 ? 'Apply' : 'Done';
      };
      const keydown = (event) => {
        if (event.key !== 'Escape') return;
        event.preventDefault();
        closeSketchEditor({ revert: true });
      };
      cancel.addEventListener('click', () => closeSketchEditor({ revert: true }));
      confirm.addEventListener('click', () => {
        const apply = applyButtons.find((button) => !button.disabled);
        if (apply) apply.click();
        else closeSketchEditor();
      });
      bridge.setGhosted(true);
      activeSketchEditor = {
        overlay,
        canvas,
        bridge,
        align,
        keydown,
        animationFrame: null,
      };
      refreshActiveSketchEditor = refresh;
      window.addEventListener('resize', align);
      window.addEventListener('keydown', keydown, true);
      align();
      refresh();
      if (window.requestAnimationFrame) {
        const followCamera = () => {
          if (!activeSketchEditor || activeSketchEditor.overlay !== overlay) return;
          align();
          if (currentGeometry) projectDimensions(currentGeometry);
          activeSketchEditor.animationFrame = window.requestAnimationFrame(followCamera);
        };
        activeSketchEditor.animationFrame = window.requestAnimationFrame(followCamera);
      }
      dimensionInputs.values().next().value?.input.focus();
    };

    const iconText = {
      model: '▧',
      group: '▰',
      builder: '⌗',
      sketch: '⌁',
      primitive: '⬡',
      operation: '▰',
      assembly: '▦',
      parameter: 'ƒx',
    };
    const createTreeIcon = (kind, title) => {
      const icon = document.createElement('span');
      icon.setAttribute('data-hardcore-tree-icon', kind);
      icon.setAttribute('aria-hidden', 'true');
      icon.title = title;
      icon.textContent = iconText[kind] || '•';
      return icon;
    };
    const requestedFile = new URLSearchParams(window.location.search).get('file');
    const pathName = requestedFile || window.location.pathname.split('/').filter(Boolean).at(-1) || 'Model';
    const modelName = pathName
      .split('/').at(-1)
      .replace(/\\.(?:step|stp)(?:\\.py)?$/i, '')
      .replace(/\\.py$/i, '') || 'Model';
    const isAssembly = data.groups.some((group) =>
      group.features.some((feature) => feature.kind === 'assembly')
    );
    const root = document.createElement('div');
    root.setAttribute('data-hardcore-feature-history-root', '');
    root.appendChild(createTreeIcon('model', isAssembly ? 'Assembly model' : 'Part model'));
    const rootLabel = document.createElement('span');
    rootLabel.style.minWidth = '0';
    rootLabel.style.flex = '1';
    rootLabel.style.overflow = 'hidden';
    rootLabel.style.textOverflow = 'ellipsis';
    rootLabel.style.whiteSpace = 'nowrap';
    rootLabel.textContent = modelName;
    const rootType = document.createElement('span');
    rootType.style.color = 'var(--muted-foreground)';
    rootType.style.fontSize = '0.5625rem';
    rootType.style.fontWeight = '500';
    rootType.textContent = isAssembly ? 'Assembly' : 'Part';
    root.append(rootLabel, rootType);
    featureContent.appendChild(root);

    const filterWrap = document.createElement('div');
    filterWrap.setAttribute('data-hardcore-feature-filter-wrap', '');
    const filterInput = document.createElement('input');
    filterInput.type = 'search';
    filterInput.placeholder = 'Filter features';
    filterInput.setAttribute('aria-label', 'Filter feature tree');
    filterInput.setAttribute('data-hardcore-feature-filter', '');
    filterWrap.appendChild(filterInput);
    featureContent.appendChild(filterWrap);

    const ungroupedParameters = data.parameters.filter(
      (parameter) => parameterGroupIds(parameter).length === 0
    );
    if (ungroupedParameters.length > 0) {
      const looseParameters = document.createElement('details');
      looseParameters.open = hadFeatureTree
        ? previouslyOpenGroups.has('__model_parameters__')
        : false;
      looseParameters.setAttribute('data-hardcore-feature-history-group', '__model_parameters__');
      looseParameters.setAttribute('data-hardcore-search-text', 'model parameters');
      const looseSummary = document.createElement('summary');
      looseSummary.appendChild(createTreeIcon('parameter', 'Model parameters'));
      const looseLabel = document.createElement('span');
      looseLabel.style.minWidth = '0';
      looseLabel.style.flex = '1';
      looseLabel.textContent = 'Model Parameters';
      const looseCount = document.createElement('span');
      looseCount.setAttribute('data-hardcore-editable-marker', '');
      looseCount.textContent = 'Edit ' + ungroupedParameters.length;
      looseSummary.append(looseLabel, looseCount);
      looseParameters.appendChild(looseSummary);
      const looseChildren = document.createElement('div');
      looseChildren.setAttribute('data-hardcore-feature-history-children', '');
      for (const parameter of ungroupedParameters) appendParameterControl(looseChildren, parameter);
      looseParameters.appendChild(looseChildren);
      featureContent.appendChild(looseParameters);
    }

    const selectableRows = [];
    const normalizeName = (value) => value.toLowerCase().replace(/[^a-z0-9]+/g, '');
    const selectMatchingGeometry = (names) => {
      const normalizedNames = names.map(normalizeName).filter((name) => name.length > 2);
      if (normalizedNames.length === 0) return false;
      const candidate = [...treePanel.querySelectorAll('[role="treeitem"]')].find((item) => {
        const label = normalizeName(item.getAttribute('aria-label') || item.textContent || '');
        return normalizedNames.some(
          (name) => label === name || label.endsWith(name) || label.includes(name)
        );
      });
      if (!(candidate instanceof HTMLElement)) return false;
      candidate.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
      return true;
    };
    const selectFeature = (row, node, designNode) => {
      for (const candidate of selectableRows) {
        candidate.setAttribute('data-hardcore-selected', candidate === row ? 'true' : 'false');
        const candidateNode = candidate.closest('[data-hardcore-feature-node]');
        if (candidateNode instanceof HTMLElement) {
          candidateNode.setAttribute(
            'data-hardcore-selected',
            candidate === row ? 'true' : 'false'
          );
        }
      }
      if (node instanceof window.HTMLDetailsElement) node.open = true;
      const linked = selectMatchingGeometry([
        designNode.label,
        designNode.operation,
        ...designNode.geometryNames,
      ]);
      row.setAttribute('data-hardcore-geometry-linked', linked ? 'true' : 'false');
      const firstInput = node.querySelector('[data-hardcore-parameter-number]');
      if (firstInput instanceof window.HTMLInputElement) firstInput.focus();
    };
    const nodeSourceFeatureIds = (node) => [
      ...node.sourceFeatureIds,
      ...node.children.flatMap(nodeSourceFeatureIds),
    ];
    const appendDesignNode = (parent, designNode) => {
      const nodeControls = designNode.controls
        .map((control) => ({ ...control, parameter: parametersById.get(control.parameterId) }))
        .filter((control) => control.parameter);
      const hasDetails = nodeControls.length > 0 || designNode.children.length > 0;
      const featureNode = hasDetails ? document.createElement('details') : document.createElement('div');
      if (hasDetails) {
        featureNode.open = hadFeatureTree
          ? previouslyOpenFeatures.has(designNode.id)
          : designNode.children.length > 0;
        featureNode.setAttribute('data-hardcore-feature-node', designNode.id);
      }
      const row = hasDetails ? document.createElement('summary') : document.createElement('button');
      if (row instanceof HTMLButtonElement) row.type = 'button';
      row.setAttribute('data-hardcore-feature-history-row', '');
      row.setAttribute('data-hardcore-feature-id', designNode.id);
      if (!hasDetails) row.setAttribute('data-hardcore-feature-node-plain', '');
      row.setAttribute('role', 'treeitem');
      row.setAttribute('aria-label', designNode.label + ', source line ' + designNode.line);
      row.setAttribute(
        'data-hardcore-search-text',
        (designNode.label + ' ' + designNode.operation + ' ' + designNode.geometryNames.join(' ')).toLowerCase()
      );
      row.title = designNode.operation + ', source line ' + designNode.line;
      row.appendChild(createTreeIcon(designNode.kind, designNode.operation));
      const name = document.createElement('span');
      name.style.minWidth = '0';
      name.style.flex = '1';
      name.style.overflow = 'hidden';
      name.style.textOverflow = 'ellipsis';
      name.style.whiteSpace = 'nowrap';
      name.textContent = designNode.label;
      row.appendChild(name);
      if (nodeControls.length > 0) {
        const editable = document.createElement('span');
        editable.setAttribute('data-hardcore-editable-marker', '');
        editable.textContent = 'Edit ' + nodeControls.length;
        editable.title = nodeControls.length + ' editable dimension' + (nodeControls.length === 1 ? '' : 's');
        row.appendChild(editable);
        row.title += ' · click to edit ' + nodeControls.length + ' dimension' +
          (nodeControls.length === 1 ? '' : 's');
      }
      selectableRows.push(row);
      row.setAttribute(
        'data-hardcore-selected',
        previouslySelectedFeature === designNode.id ? 'true' : 'false'
      );
      if (previouslySelectedFeature === designNode.id && featureNode instanceof HTMLElement) {
        featureNode.setAttribute('data-hardcore-selected', 'true');
      }
      row.addEventListener('click', (event) => {
        if (row.tagName === 'SUMMARY') event.preventDefault();
        selectFeature(row, featureNode, designNode);
      });
      if (designNode.kind === 'sketch' && nodeControls.length > 0) {
        row.title += ' · double-click to edit the sketch in the viewport';
        row.addEventListener('dblclick', (event) => {
          event.preventDefault();
          event.stopPropagation();
          openSketchEditor(designNode);
        });
      }
      featureNode.appendChild(row);
      for (const control of nodeControls) {
        appendParameterControl(featureNode, control.parameter, control.label);
      }
      if (designNode.kind === 'sketch' && nodeControls.length > 0) {
        const editSketch = document.createElement('button');
        editSketch.type = 'button';
        editSketch.setAttribute('data-hardcore-edit-sketch', '');
        editSketch.textContent = 'Edit sketch in viewport';
        editSketch.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          openSketchEditor(designNode);
        });
        featureNode.appendChild(editSketch);
      }
      if (designNode.children.length > 0) {
        const nested = document.createElement('div');
        nested.setAttribute('data-hardcore-feature-history-children', '');
        for (const child of designNode.children) appendDesignNode(nested, child);
        featureNode.appendChild(nested);
      }
      parent.appendChild(featureNode);
    };
    for (const group of data.designGroups) {
      const groupParameters = data.parameters.filter((parameter) =>
        parameterGroupIds(parameter).includes(group.id)
      );
      const details = document.createElement('details');
      details.open = hadFeatureTree ? previouslyOpenGroups.has(group.id) : true;
      details.setAttribute('data-hardcore-feature-history-group', group.id);
      details.setAttribute(
        'data-hardcore-search-text',
        (group.label + ' ' + group.functionName + ' ' + group.nodes.map((node) => node.label + ' ' + node.operation + ' ' + node.children.map((child) => child.label).join(' ')).join(' ')).toLowerCase()
      );
      const summary = document.createElement('summary');
      summary.setAttribute('aria-label', group.label + ' features');
      summary.appendChild(createTreeIcon('group', 'Construction group'));
      const summaryRow = document.createElement('span');
      summaryRow.style.display = 'flex';
      summaryRow.style.minWidth = '0';
      summaryRow.style.flex = '1';
      summaryRow.style.alignItems = 'center';
      summaryRow.style.gap = '0.375rem';
      const label = document.createElement('span');
      label.style.minWidth = '0';
      label.style.flex = '1';
      label.style.overflow = 'hidden';
      label.style.textOverflow = 'ellipsis';
      label.style.whiteSpace = 'nowrap';
      label.textContent = group.label;
      summaryRow.appendChild(label);
      const count = document.createElement('span');
      count.setAttribute('data-hardcore-editable-marker', '');
      count.textContent = String(group.nodes.length);
      summaryRow.appendChild(count);
      summary.appendChild(summaryRow);
      details.appendChild(summary);
      const children = document.createElement('div');
      children.setAttribute('data-hardcore-feature-history-children', '');
      const groupFeatureIds = new Set(group.nodes.flatMap(nodeSourceFeatureIds));
      const groupOnlyParameters = groupParameters.filter(
        (parameter) => !parameterFeatureIds(parameter).some((featureId) => groupFeatureIds.has(featureId))
      );
      if (groupOnlyParameters.length > 0) {
        const parameterFolder = document.createElement('details');
        parameterFolder.open = hadFeatureTree
          ? previouslyOpenFeatures.has(group.id + ':parameters')
          : false;
        parameterFolder.setAttribute('data-hardcore-feature-node', group.id + ':parameters');
        const parameterSummary = document.createElement('summary');
        parameterSummary.setAttribute('data-hardcore-feature-history-row', '');
        parameterSummary.appendChild(createTreeIcon('parameter', 'Group parameters'));
        const parameterLabel = document.createElement('span');
        parameterLabel.style.minWidth = '0';
        parameterLabel.style.flex = '1';
        parameterLabel.textContent = 'Parameters';
        const parameterCount = document.createElement('span');
        parameterCount.setAttribute('data-hardcore-editable-marker', '');
        parameterCount.textContent = 'Edit ' + groupOnlyParameters.length;
        parameterSummary.append(parameterLabel, parameterCount);
        parameterFolder.appendChild(parameterSummary);
        for (const parameter of groupOnlyParameters) appendParameterControl(parameterFolder, parameter);
        children.appendChild(parameterFolder);
      }
      for (const node of group.nodes) appendDesignNode(children, node);
      details.appendChild(children);
      featureContent.appendChild(details);
    }

    for (const parameter of data.parameters) appendParameterControl(slidersContent, parameter);

    updateApplyState();

    const emptyFilterResult = document.createElement('div');
    emptyFilterResult.hidden = true;
    emptyFilterResult.setAttribute('data-hardcore-feature-history-empty', '');
    emptyFilterResult.textContent = 'No matching features';
    featureContent.appendChild(emptyFilterResult);
    filterInput.addEventListener('input', () => {
      const query = filterInput.value.trim().toLowerCase();
      let visibleCount = 0;
      for (const groupElement of panel.querySelectorAll('[data-hardcore-feature-history-group]')) {
        if (!(groupElement instanceof HTMLElement)) continue;
        const groupText = groupElement.getAttribute('data-hardcore-search-text') || '';
        const matchesGroup = !query || groupText.includes(query);
        groupElement.hidden = !matchesGroup;
        if (matchesGroup) {
          visibleCount += 1;
          if (query && groupElement.tagName === 'DETAILS') groupElement.open = true;
          for (const row of groupElement.querySelectorAll('[data-hardcore-feature-history-row]')) {
            if (!(row instanceof HTMLElement)) continue;
            const rowText = row.getAttribute('data-hardcore-search-text');
            if (!rowText) continue;
            const rowContainer = row.closest('[data-hardcore-feature-node]') || row;
            if (rowContainer instanceof HTMLElement) {
              rowContainer.hidden = !!query && !rowText.includes(query);
            }
          }
        }
      }
      emptyFilterResult.hidden = visibleCount > 0;
    });

    for (const diagnostic of data.diagnostics) {
      const warning = document.createElement('div');
      warning.setAttribute('data-hardcore-feature-history-diagnostic', '');
      warning.style.padding = '0.5rem';
      warning.style.fontSize = '0.625rem';
      warning.style.color = 'var(--muted-foreground)';
      warning.textContent = diagnostic;
      featureContent.appendChild(warning);
    }

    let activeDesignMode = 'features';
    try {
      const storedDesignMode = window.sessionStorage.getItem(designModeStorageKey);
      if (storedDesignMode === 'features' || storedDesignMode === 'sliders') {
        activeDesignMode = storedDesignMode;
      }
    } catch {}
    activateDesignMode(activeDesignMode);

    const activeStorageKey = 'hardcore:model-tree-view';
    const activate = (view) => {
      const nextView = view === 'geometry' ? 'geometry' : 'design';
      pane.setAttribute('data-hardcore-model-tree-view', nextView);
      featureTab.setAttribute('aria-selected', nextView === 'design' ? 'true' : 'false');
      treeTab.setAttribute('aria-selected', nextView === 'geometry' ? 'true' : 'false');
      panel.hidden = nextView !== 'design';
      try {
        window.sessionStorage.setItem(activeStorageKey, nextView);
      } catch {}
    };
    pane.__hardcoreFeatureHistoryActivate = activate;
    if (!pane.hasAttribute('data-hardcore-feature-history-bound')) {
      pane.setAttribute('data-hardcore-feature-history-bound', '');
      pane.addEventListener('click', (event) => {
        const target = event.target instanceof Element
          ? event.target.closest('button[data-file-sheet-tab]')
          : null;
        if (target?.getAttribute('data-file-sheet-tab') === 'features') {
          pane.__hardcoreFeatureHistoryActivate?.('design');
        }
        if (target?.getAttribute('data-file-sheet-tab') === 'tree') {
          pane.__hardcoreFeatureHistoryActivate?.('geometry');
        }
      });
    }
    let activeView = 'design';
    try {
      const storedView = window.sessionStorage.getItem(activeStorageKey);
      if (storedView === 'design' || storedView === 'geometry') {
        activeView = storedView;
      }
    } catch {}
    activate(activeView);
    return true;
  })()`;
}
