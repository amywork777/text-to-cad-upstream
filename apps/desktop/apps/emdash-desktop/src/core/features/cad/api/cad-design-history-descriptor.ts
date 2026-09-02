import { z } from 'zod';
import {
  parseCadSourceHistory,
  type CadDesignParameter,
  type CadSourceFeature,
  type CadSourceHistory,
} from './cad-source-history';

export const CAD_DESIGN_HISTORY_DESCRIPTOR_VERSION = 1 as const;

export type CadDesignHistoryFeatureKind =
  | 'builder'
  | 'sketch'
  | 'primitive'
  | 'operation'
  | 'assembly';

export type CadDesignSelectorKind =
  | 'body'
  | 'component'
  | 'face'
  | 'edge'
  | 'vertex'
  | 'sketch-entity';

/**
 * An exact reference emitted by cadgen or the viewer. The desktop adapter deliberately leaves this
 * empty when source parsing cannot prove a topology identity; labels and face order are not refs.
 */
export interface CadDesignSelectorRef {
  kind: CadDesignSelectorKind;
  ref: string;
}

export interface CadDesignSourceSpan {
  path: string;
  start: number;
  end: number;
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
}

export interface CadDesignSketchTransform {
  origin: [number, number, number];
  xAxis: [number, number, number];
  yAxis: [number, number, number];
  normal: [number, number, number];
}

export interface CadDesignSketchDescriptor {
  plane?: 'XY' | 'XZ' | 'YZ';
  transform?: CadDesignSketchTransform;
  dimensionIds: string[];
}

export interface CadDesignHistoryGroupDescriptor {
  id: string;
  label: string;
  functionName: string;
  dependencyIds: string[];
  featureIds: string[];
}

export interface CadDesignHistoryFeatureDescriptor {
  id: string;
  groupId: string;
  operation: string;
  label: string;
  kind: CadDesignHistoryFeatureKind;
  mode?: 'add' | 'subtract';
  source?: CadDesignSourceSpan;
  editability: {
    mode: 'read-only' | 'numeric-parameters';
    parameterIds: string[];
  };
  selectorRefs: CadDesignSelectorRef[];
  sketch?: CadDesignSketchDescriptor;
}

export interface CadDesignHistoryParameterDescriptor {
  id: string;
  symbol: string;
  label: string;
  description?: string;
  unit?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  source: CadDesignSourceSpan & { editable: true };
  featureIds: string[];
  origin?: CadDesignParameter['origin'];
}

const sourceSpanShape = {
  path: z.string().min(1),
  start: z.number().int().nonnegative(),
  end: z.number().int().nonnegative(),
  startLine: z.number().int().positive(),
  startColumn: z.number().int().nonnegative(),
  endLine: z.number().int().positive(),
  endColumn: z.number().int().nonnegative(),
};

const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/i, 'Expected a SHA-256 hex digest.');
const vector3Schema = z.tuple([z.number(), z.number(), z.number()]);

export const cadDesignSourceSpanSchema = z
  .strictObject(sourceSpanShape)
  .refine((span) => span.end >= span.start, { message: 'Source span end must follow start.' });

export const cadDesignSelectorRefSchema = z.strictObject({
  kind: z.enum(['body', 'component', 'face', 'edge', 'vertex', 'sketch-entity']),
  ref: z.string().min(1),
});

const cadDesignSketchTransformSchema = z.strictObject({
  origin: vector3Schema,
  xAxis: vector3Schema,
  yAxis: vector3Schema,
  normal: vector3Schema,
});

const cadDesignSketchDescriptorSchema = z.strictObject({
  plane: z.enum(['XY', 'XZ', 'YZ']).optional(),
  transform: cadDesignSketchTransformSchema.optional(),
  dimensionIds: z.array(z.string().min(1)),
});

const cadDesignHistoryGroupDescriptorSchema = z.strictObject({
  id: z.string().min(1),
  label: z.string(),
  functionName: z.string().min(1),
  dependencyIds: z.array(z.string().min(1)),
  featureIds: z.array(z.string().min(1)),
});

const cadDesignHistoryFeatureDescriptorSchema = z.strictObject({
  id: z.string().min(1),
  groupId: z.string().min(1),
  operation: z.string().min(1),
  label: z.string(),
  kind: z.enum(['builder', 'sketch', 'primitive', 'operation', 'assembly']),
  mode: z.enum(['add', 'subtract']).optional(),
  source: cadDesignSourceSpanSchema.optional(),
  editability: z.strictObject({
    mode: z.enum(['read-only', 'numeric-parameters']),
    parameterIds: z.array(z.string().min(1)),
  }),
  selectorRefs: z.array(cadDesignSelectorRefSchema),
  sketch: cadDesignSketchDescriptorSchema.optional(),
});

const cadDesignHistoryParameterDescriptorSchema = z.strictObject({
  id: z.string().min(1),
  symbol: z.string().min(1),
  label: z.string(),
  description: z.string().optional(),
  unit: z.string().optional(),
  value: z.number().finite(),
  min: z.number().finite(),
  max: z.number().finite(),
  step: z.number().positive().finite(),
  source: z.strictObject({ ...sourceSpanShape, editable: z.literal(true) }),
  featureIds: z.array(z.string().min(1)),
  origin: z
    .enum(['declared', 'function-parameter', 'source-variable', 'feature-literal'])
    .optional(),
});

/** Runtime JSON boundary for viewer, sidecar, and host-process handoffs. */
export const cadDesignHistoryDescriptorSchema = z
  .strictObject({
    type: z.literal('designHistory'),
    version: z.literal(CAD_DESIGN_HISTORY_DESCRIPTOR_VERSION),
    identityScope: z.literal('revision'),
    binding: z.strictObject({
      hashAlgorithm: z.literal('sha256'),
      sourcePath: z.string().min(1),
      sourceHash: sha256Schema,
      stepPath: z.string().min(1),
      stepHash: sha256Schema,
    }),
    groups: z.array(cadDesignHistoryGroupDescriptorSchema),
    features: z.array(cadDesignHistoryFeatureDescriptorSchema),
    parameters: z.array(cadDesignHistoryParameterDescriptorSchema),
    diagnostics: z.array(z.string()),
  })
  .superRefine(validateDescriptorReferences);

/** Portable payload shared by Hardcore and a native Text-to-CAD viewer implementation. */
export type CadDesignHistoryDescriptorV1 = z.infer<typeof cadDesignHistoryDescriptorSchema>;
export type CadDesignHistoryDescriptor = CadDesignHistoryDescriptorV1;

export function parseCadDesignHistoryDescriptor(value: unknown): CadDesignHistoryDescriptorV1 {
  return cadDesignHistoryDescriptorSchema.parse(value);
}

export interface CreateCadDesignHistoryDescriptorInput {
  source: string;
  sourcePath: string;
  sourceHash: string;
  stepPath: string;
  stepHash: string;
  history?: CadSourceHistory;
  selectorRefsByFeatureId?: Readonly<Record<string, readonly CadDesignSelectorRef[]>>;
}

/**
 * Adapts the current source parser into the versioned native-viewer contract. Feature IDs are
 * deterministic only inside the sourceHash + stepHash revision to which this descriptor is bound.
 * They are not construction-history identities across rebuilds; a future authored cadgen descriptor
 * can introduce that stronger identity in a new contract version.
 */
export function createCadDesignHistoryDescriptor(
  input: CreateCadDesignHistoryDescriptorInput
): CadDesignHistoryDescriptorV1 {
  requireBindingValue('sourcePath', input.sourcePath);
  requireBindingValue('sourceHash', input.sourceHash);
  requireBindingValue('stepPath', input.stepPath);
  requireBindingValue('stepHash', input.stepHash);

  const history = input.history ?? parseCadSourceHistory(input.source);
  const groupIdMap = new Map(
    history.groups.map((group) => [group.id, `group:${stableSourceName(group.functionName)}`])
  );
  const featureIdMap = revisionFeatureIds(history);
  const parameterIdMap = revisionParameterIds(history.parameters, featureIdMap);
  const parametersByFeatureId = new Map<string, string[]>();
  for (const parameter of history.parameters) {
    const parameterId = parameterIdMap.get(parameter.id);
    if (!parameterId) continue;
    for (const legacyFeatureId of parameter.featureIds) {
      const featureId = featureIdMap.get(legacyFeatureId);
      if (!featureId) continue;
      const ids = parametersByFeatureId.get(featureId) ?? [];
      ids.push(parameterId);
      parametersByFeatureId.set(featureId, ids);
    }
  }

  const groups: CadDesignHistoryGroupDescriptor[] = history.groups.map((group) => ({
    id: groupIdMap.get(group.id)!,
    label: group.label,
    functionName: group.functionName,
    dependencyIds: group.dependencies.flatMap((dependency) => {
      const id = groupIdMap.get(dependency);
      return id ? [id] : [];
    }),
    featureIds: group.features.flatMap((feature) => {
      const id = featureIdMap.get(feature.id);
      return id ? [id] : [];
    }),
  }));

  const features = history.groups.flatMap((group) => {
    let activeSketch: CadSourceFeature | undefined;
    return group.features.map((feature) => {
      if (feature.operation === 'BuildSketch') activeSketch = feature;
      const id = featureIdMap.get(feature.id)!;
      const parameterIds = parametersByFeatureId.get(id) ?? [];
      const parsedSelectors =
        input.selectorRefsByFeatureId?.[feature.id] ?? input.selectorRefsByFeatureId?.[id] ?? [];
      const source = feature.span
        ? sourceSpan(input.source, input.sourcePath, feature.span)
        : undefined;
      const sketchSource = feature.kind === 'sketch' ? activeSketch : undefined;
      return {
        id,
        groupId: groupIdMap.get(group.id)!,
        operation: feature.operation,
        label: feature.label,
        kind: feature.kind,
        ...(feature.mode ? { mode: feature.mode } : {}),
        ...(source ? { source } : {}),
        editability: {
          mode: parameterIds.length > 0 ? ('numeric-parameters' as const) : ('read-only' as const),
          parameterIds,
        },
        selectorRefs: parsedSelectors.map((selector) => ({ ...selector })),
        ...(feature.kind === 'sketch'
          ? {
              sketch: {
                ...(sketchSource?.plane ? { plane: sketchSource.plane } : {}),
                ...(sketchSource?.plane
                  ? {
                      transform: principalPlaneTransform(
                        sketchSource.plane,
                        sketchSource.sketchOrigin ?? [0, 0, 0]
                      ),
                    }
                  : {}),
                dimensionIds: parameterIds,
              },
            }
          : {}),
      } satisfies CadDesignHistoryFeatureDescriptor;
    });
  });

  const parameters: CadDesignHistoryParameterDescriptor[] = history.parameters.map((parameter) => ({
    id: parameterIdMap.get(parameter.id)!,
    symbol: parameter.symbol,
    label: parameter.label,
    ...(parameter.description ? { description: parameter.description } : {}),
    ...(parameter.unit ? { unit: parameter.unit } : {}),
    value: parameter.defaultValue,
    min: parameter.min,
    max: parameter.max,
    step: parameter.step,
    source: {
      ...sourceSpan(input.source, input.sourcePath, parameter.span),
      editable: true,
    },
    featureIds: parameter.featureIds.flatMap((featureId) => {
      const id = featureIdMap.get(featureId);
      return id ? [id] : [];
    }),
    ...(parameter.origin ? { origin: parameter.origin } : {}),
  }));

  return parseCadDesignHistoryDescriptor({
    type: 'designHistory',
    version: CAD_DESIGN_HISTORY_DESCRIPTOR_VERSION,
    identityScope: 'revision',
    binding: {
      hashAlgorithm: 'sha256',
      sourcePath: input.sourcePath,
      sourceHash: input.sourceHash,
      stepPath: input.stepPath,
      stepHash: input.stepHash,
    },
    groups,
    features,
    parameters,
    diagnostics: [...history.diagnostics],
  });
}

/** Explicit portable surface for native viewer and host integrations. */
export const cadDesignHistoryApi = {
  version: CAD_DESIGN_HISTORY_DESCRIPTOR_VERSION,
  schema: cadDesignHistoryDescriptorSchema,
  parse: parseCadDesignHistoryDescriptor,
  create: createCadDesignHistoryDescriptor,
} as const;

function revisionFeatureIds(history: CadSourceHistory): Map<string, string> {
  const ids = new Map<string, string>();
  for (const group of history.groups) {
    const operationCounts = new Map<string, number>();
    for (const feature of group.features) {
      const operation = stableSegment(feature.operation);
      const ordinal = (operationCounts.get(operation) ?? 0) + 1;
      operationCounts.set(operation, ordinal);
      ids.set(
        feature.id,
        `feature:${stableSourceName(group.functionName)}:${operation}:${ordinal}`
      );
    }
  }
  return ids;
}

function revisionParameterIds(
  parameters: readonly CadDesignParameter[],
  featureIdMap: ReadonlyMap<string, string>
): Map<string, string> {
  const ids = new Map<string, string>();
  const used = new Set<string>();
  for (const parameter of parameters) {
    const linkedFeatureId = parameter.featureIds.flatMap((id) => {
      const mapped = featureIdMap.get(id);
      return mapped ? [mapped] : [];
    })[0];
    const base =
      parameter.origin === 'feature-literal' && linkedFeatureId
        ? `parameter:${linkedFeatureId.slice('feature:'.length)}:${stableSegment(parameter.symbol)}`
        : `parameter:${stableSegment(parameter.id)}`;
    let id = base;
    let suffix = 2;
    while (used.has(id)) id = `${base}:${suffix++}`;
    used.add(id);
    ids.set(parameter.id, id);
  }
  return ids;
}

function sourceSpan(
  source: string,
  path: string,
  span: readonly [number, number]
): CadDesignSourceSpan {
  const start = sourceLocation(source, span[0]);
  const end = sourceLocation(source, span[1]);
  return {
    path,
    start: span[0],
    end: span[1],
    startLine: start.line,
    startColumn: start.column,
    endLine: end.line,
    endColumn: end.column,
  };
}

function sourceLocation(source: string, offset: number): { line: number; column: number } {
  const before = source.slice(0, offset);
  const lines = before.split('\n');
  return { line: lines.length, column: lines.at(-1)?.length ?? 0 };
}

function principalPlaneTransform(
  plane: 'XY' | 'XZ' | 'YZ',
  origin: [number, number, number]
): CadDesignSketchTransform {
  if (plane === 'XZ') {
    return {
      origin: [...origin],
      xAxis: [1, 0, 0],
      yAxis: [0, 0, 1],
      normal: [0, -1, 0],
    };
  }
  if (plane === 'YZ') {
    return {
      origin: [...origin],
      xAxis: [0, 1, 0],
      yAxis: [0, 0, 1],
      normal: [1, 0, 0],
    };
  }
  return {
    origin: [...origin],
    xAxis: [1, 0, 0],
    yAxis: [0, 1, 0],
    normal: [0, 0, 1],
  };
}

function stableSegment(value: string): string {
  const segment = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return segment || 'unnamed';
}

function stableSourceName(value: string): string {
  return encodeURIComponent(value.trim()) || 'unnamed';
}

function validateDescriptorReferences(
  descriptor: {
    groups: Array<{ id: string; dependencyIds: string[]; featureIds: string[] }>;
    features: Array<{
      id: string;
      groupId: string;
      editability: { mode: 'read-only' | 'numeric-parameters'; parameterIds: string[] };
      sketch?: { dimensionIds: string[] };
    }>;
    parameters: Array<{
      id: string;
      min: number;
      max: number;
      value: number;
      source: { start: number; end: number };
      featureIds: string[];
    }>;
  },
  context: z.RefinementCtx
): void {
  const groupIds = uniqueIds(descriptor.groups, 'groups', context);
  const featureIds = uniqueIds(descriptor.features, 'features', context);
  const parameterIds = uniqueIds(descriptor.parameters, 'parameters', context);

  descriptor.groups.forEach((group, index) => {
    validateReferences(group.dependencyIds, groupIds, ['groups', index, 'dependencyIds'], context);
    validateReferences(group.featureIds, featureIds, ['groups', index, 'featureIds'], context);
  });
  descriptor.features.forEach((feature, index) => {
    validateReferences([feature.groupId], groupIds, ['features', index, 'groupId'], context);
    validateReferences(
      feature.editability.parameterIds,
      parameterIds,
      ['features', index, 'editability', 'parameterIds'],
      context
    );
    validateReferences(
      feature.sketch?.dimensionIds ?? [],
      parameterIds,
      ['features', index, 'sketch', 'dimensionIds'],
      context
    );
    if (
      (feature.editability.mode === 'numeric-parameters') !==
      feature.editability.parameterIds.length > 0
    ) {
      context.addIssue({
        code: 'custom',
        message: 'Feature editability must agree with its parameter references.',
        path: ['features', index, 'editability'],
      });
    }
  });
  descriptor.parameters.forEach((parameter, index) => {
    validateReferences(
      parameter.featureIds,
      featureIds,
      ['parameters', index, 'featureIds'],
      context
    );
    if (parameter.source.end < parameter.source.start) {
      context.addIssue({
        code: 'custom',
        message: 'Source span end must follow start.',
        path: ['parameters', index, 'source', 'end'],
      });
    }
    if (parameter.min > parameter.value || parameter.max < parameter.value) {
      context.addIssue({
        code: 'custom',
        message: 'Parameter range must contain its current value.',
        path: ['parameters', index],
      });
    }
  });
}

function uniqueIds(
  values: ReadonlyArray<{ id: string }>,
  collection: 'groups' | 'features' | 'parameters',
  context: z.RefinementCtx
): Set<string> {
  const ids = new Set<string>();
  values.forEach((value, index) => {
    if (ids.has(value.id)) {
      context.addIssue({
        code: 'custom',
        message: `Duplicate ${collection} id: ${value.id}`,
        path: [collection, index, 'id'],
      });
    }
    ids.add(value.id);
  });
  return ids;
}

function validateReferences(
  references: readonly string[],
  knownIds: ReadonlySet<string>,
  path: Array<string | number>,
  context: z.RefinementCtx
): void {
  references.forEach((reference, index) => {
    if (knownIds.has(reference)) return;
    context.addIssue({
      code: 'custom',
      message: `Unknown descriptor reference: ${reference}`,
      path: [...path, index],
    });
  });
}

function requireBindingValue(name: string, value: string): void {
  if (!value.trim()) throw new Error(`CAD design history ${name} must not be empty.`);
}
