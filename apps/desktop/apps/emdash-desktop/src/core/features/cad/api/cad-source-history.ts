export type CadSourceFeatureKind = 'builder' | 'sketch' | 'primitive' | 'operation' | 'assembly';

export interface CadSourceFeature {
  id: string;
  operation: string;
  label: string;
  kind: CadSourceFeatureKind;
  line: number;
  column?: number;
  span?: [number, number];
  mode?: 'add' | 'subtract';
  plane?: 'XY' | 'XZ' | 'YZ';
  sketchOrigin?: [number, number, number];
}

export interface CadSourceFeatureGroup {
  id: string;
  functionName: string;
  label: string;
  line: number;
  dependencies: string[];
  features: CadSourceFeature[];
}

export interface CadDesignParameter {
  id: string;
  symbol: string;
  label: string;
  description?: string;
  unit?: string;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  line: number;
  span: [number, number];
  groupIds: string[];
  featureIds: string[];
  origin?: 'declared' | 'function-parameter' | 'source-variable' | 'feature-literal';
}

export interface CadSourceHistory {
  groups: CadSourceFeatureGroup[];
  parameters: CadDesignParameter[];
  diagnostics: string[];
}

interface SourceFunction {
  name: string;
  line: number;
  startLineIndex: number;
  endLineIndex: number;
}

interface ParameterMarker {
  label?: unknown;
  description?: unknown;
  unit?: unknown;
  id?: unknown;
  min?: unknown;
  max?: unknown;
  step?: unknown;
}

const FEATURE_OPERATIONS = new Map<string, { kind: CadSourceFeatureKind; label: string }>([
  ['BuildPart', { kind: 'builder', label: 'Part builder' }],
  ['BuildSketch', { kind: 'builder', label: 'Sketch builder' }],
  ['BuildLine', { kind: 'builder', label: 'Path builder' }],
  ['Rectangle', { kind: 'sketch', label: 'Rectangle sketch' }],
  ['RectangleRounded', { kind: 'sketch', label: 'Rounded rectangle sketch' }],
  ['Circle', { kind: 'sketch', label: 'Circle sketch' }],
  ['Spline', { kind: 'sketch', label: 'Spline path' }],
  ['Box', { kind: 'primitive', label: 'Box' }],
  ['Cylinder', { kind: 'primitive', label: 'Cylinder' }],
  ['Sphere', { kind: 'primitive', label: 'Sphere' }],
  ['Hole', { kind: 'primitive', label: 'Hole' }],
  ['extrude', { kind: 'operation', label: 'Extrude' }],
  ['revolve', { kind: 'operation', label: 'Revolve' }],
  ['loft', { kind: 'operation', label: 'Loft' }],
  ['sweep', { kind: 'operation', label: 'Sweep' }],
  ['fillet', { kind: 'operation', label: 'Fillet' }],
  ['chamfer', { kind: 'operation', label: 'Chamfer' }],
  ['add', { kind: 'operation', label: 'Add shape' }],
  ['AssemblyHelper', { kind: 'assembly', label: 'Assembly' }],
]);

const FUNCTION_RE = /^def\s+([A-Za-z_]\w*)\s*\(/;
const CALL_RE = /\b([A-Za-z_]\w*)\s*\(/g;
const PARAMETER_MARKER_RE = /^\s*#\s*@cad-parameter\s+(.+)\s*$/;
const NUMERIC_ASSIGNMENT_RE = /^\s*([A-Z][A-Z0-9_]*)\s*=\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:#.*)?$/;
const UPPER_ASSIGNMENT_RE = /^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.+?)\s*(?:#.*)?$/;
const UPPER_SYMBOL_RE = /\b[A-Z][A-Z0-9_]*\b/g;
const DIRECT_NUMBER_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const DIMENSION_SYMBOL_RE =
  /(?:^|_)(?:LENGTH|WIDTH|HEIGHT|RADIUS|DIAMETER|OD|ID|THICKNESS|CLEARANCE|FILLET|CHAMFER|SPACING|OFFSET|ANGLE|ARC|DISTANCE|DEPTH|SIZE|X|Y|Z)(?:_|$)/;
const NON_DESIGN_SYMBOL_RE = /(?:^|_)(?:COLOR|COUNT|INDEX|SAMPLE|STEP|MODE)(?:_|$)/;

const FEATURE_ARGUMENT_NAMES: Readonly<Record<string, readonly string[]>> = {
  Box: ['length', 'width', 'height'],
  Cylinder: ['radius', 'height'],
  Sphere: ['radius'],
  Hole: ['radius', 'depth'],
  Rectangle: ['width', 'height'],
  RectangleRounded: ['width', 'height', 'radius'],
  Circle: ['radius'],
  extrude: ['amount'],
  revolve: ['revolution_arc'],
};

export function parseCadSourceHistory(source: string): CadSourceHistory {
  const lines = source.split('\n');
  const lineOffsets = sourceLineOffsets(lines);
  const functions = collectFunctions(lines);
  const functionMap = new Map(functions.map((item) => [item.name, item]));
  const dependencies = new Map(
    functions.map((item) => [item.name, collectFunctionDependencies(lines, item, functionMap)])
  );
  const orderedFunctions = reachableFunctions(functionMap, dependencies);
  const rawGroups = orderedFunctions
    .map((item) => sourceFeatureGroup(lines, item, dependencies.get(item.name) ?? []))
    .filter((group) => group.features.length > 0);
  const groups = rawGroups.map((group) => ({
    ...group,
    features: group.features.map((feature): CadSourceFeature => {
      const range = featureCallRange(source, lineOffsets, feature);
      if (!range) return feature;
      const callSource = source.slice(range.start, range.end);
      const mode: NonNullable<CadSourceFeature['mode']> = /\bmode\s*=\s*Mode\.SUBTRACT\b/.test(
        callSource
      )
        ? 'subtract'
        : 'add';
      const planeMatch =
        feature.operation === 'BuildSketch'
          ? callSource.match(/\bPlane\.(XY|XZ|YZ)(?:\.offset\(([^)]+)\))?/)
          : null;
      const sketchOrigin = planeMatch
        ? resolveSketchOrigin(lines, feature, planeMatch[1] as 'XY' | 'XZ' | 'YZ', planeMatch[2])
        : null;
      return {
        ...feature,
        span: [range.start, range.end],
        mode,
        ...(planeMatch ? { plane: planeMatch[1] as NonNullable<CadSourceFeature['plane']> } : {}),
        ...(sketchOrigin ? { sketchOrigin } : {}),
      };
    }),
  }));
  const parsedParameters = collectParameters(source, lines, lineOffsets);
  const groupIds = new Set(groups.map((group) => group.id));
  const assignments = collectUpperAssignments(lines);
  const declaredParameters = parsedParameters.parameters.map((parameter) => ({
    ...parameter,
    origin: 'declared' as const,
    groupIds: orderedFunctions
      .filter(
        (item) =>
          groupIds.has(item.name) &&
          functionUsesSourceSymbol(lines, item, parameter.symbol, assignments)
      )
      .map((item) => item.name),
    featureIds: groups.flatMap((group) =>
      group.features
        .filter((feature) =>
          featureUsesSymbol(source, lines, lineOffsets, feature, parameter.symbol, assignments)
        )
        .map((feature) => feature.id)
    ),
  }));
  const functionParameters = collectFunctionDefaultParameters({
    source,
    lineOffsets,
    orderedFunctions,
    groups,
  });
  const inferredParameters = collectInferredSourceParameters({
    source,
    lines,
    lineOffsets,
    orderedFunctions,
    groups,
    assignments,
    declaredSymbols: new Set(
      [...declaredParameters, ...functionParameters].map((parameter) => parameter.symbol)
    ),
  });
  const featureLiteralParameters = collectFeatureLiteralParameters({
    source,
    lines,
    lineOffsets,
    groups,
  });
  const parameters = [
    ...declaredParameters,
    ...functionParameters,
    ...inferredParameters,
    ...featureLiteralParameters,
  ];

  return {
    groups,
    parameters,
    diagnostics: parsedParameters.diagnostics,
  };
}

function resolveSketchOrigin(
  lines: readonly string[],
  feature: CadSourceFeature,
  plane: 'XY' | 'XZ' | 'YZ',
  offsetExpression?: string
): [number, number, number] {
  const bindings = numericBindingsThroughLine(lines, feature.line);
  const offset = offsetExpression
    ? (evaluateNumericExpression(offsetExpression, bindings) ?? 0)
    : 0;
  const location = sketchLocationExpressions(lines, feature.line);
  const u = location ? (evaluateNumericExpression(location[0], bindings) ?? 0) : 0;
  const v = location ? (evaluateNumericExpression(location[1], bindings) ?? 0) : 0;
  // build123d's positive XZ plane normal points toward -Y, so a positive plane offset lowers Y.
  if (plane === 'XZ') return [u, -offset, v];
  if (plane === 'YZ') return [offset, u, v];
  return [u, v, offset];
}

function sketchLocationExpressions(
  lines: readonly string[],
  featureLine: number
): [string, string] | null {
  const startIndex = featureLine - 1;
  const featureIndent = lines[startIndex]?.match(/^\s*/)?.[0].length ?? 0;
  for (let index = startIndex + 1; index < lines.length; index += 1) {
    const line = lines[index] ?? '';
    if (!line.trim()) continue;
    const indent = line.match(/^\s*/)?.[0].length ?? 0;
    if (indent <= featureIndent) break;
    const match = line.match(
      /\bLocations\s*\(\s*(?:Pos\s*\()?\s*[([]?\s*([^,)\]]+)\s*,\s*([^,)\]]+)/
    );
    if (match) return [match[1].trim(), match[2].trim()];
  }
  return null;
}

function numericBindingsThroughLine(
  lines: readonly string[],
  lineNumber: number
): Map<string, number> {
  const bindings = new Map<string, number>();
  const end = Math.min(lineNumber, lines.length);
  for (let index = 0; index < end; index += 1) {
    const match = lines[index]?.match(/^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*(?:#.*)?$/);
    if (!match) continue;
    const value = evaluateNumericExpression(match[2], bindings);
    if (value !== null) bindings.set(match[1], value);
  }
  const sourcePrefix = lines.slice(0, end).join('\n');
  const functionPattern = /^\s*def\s+[A-Za-z_]\w*\s*\(([^)]*)\)\s*(?:->[^:]*)?:/gm;
  for (const functionMatch of sourcePrefix.matchAll(functionPattern)) {
    const argumentPattern =
      /(?:^|,)\s*([A-Za-z_]\w*)\s*(?::[^,=]+)?=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)/g;
    for (const argumentMatch of functionMatch[1].matchAll(argumentPattern)) {
      const value = Number(argumentMatch[2]);
      if (Number.isFinite(value)) bindings.set(argumentMatch[1], value);
    }
  }
  return bindings;
}

function evaluateNumericExpression(
  expression: string,
  bindings: ReadonlyMap<string, number>
): number | null {
  const tokens = expression.match(/\d+(?:\.\d*)?|\.\d+|[A-Za-z_]\w*|[()+\-*/]/g);
  if (!tokens || tokens.join('').replaceAll(' ', '') !== expression.replaceAll(/\s+/g, ''))
    return null;
  let index = 0;
  const primary = (): number | null => {
    const token = tokens[index++];
    if (!token) return null;
    if (token === '+' || token === '-') {
      const value = primary();
      return value === null ? null : token === '-' ? -value : value;
    }
    if (token === '(') {
      const value = additive();
      if (tokens[index++] !== ')') return null;
      return value;
    }
    if (/^(?:\d|\.)/.test(token)) {
      const value = Number(token);
      return Number.isFinite(value) ? value : null;
    }
    return bindings.get(token) ?? null;
  };
  const multiplicative = (): number | null => {
    let value = primary();
    while (value !== null && (tokens[index] === '*' || tokens[index] === '/')) {
      const operator = tokens[index++];
      const right = primary();
      if (right === null || (operator === '/' && right === 0)) return null;
      value = operator === '*' ? value * right : value / right;
    }
    return value;
  };
  const additive = (): number | null => {
    let value = multiplicative();
    while (value !== null && (tokens[index] === '+' || tokens[index] === '-')) {
      const operator = tokens[index++];
      const right = multiplicative();
      if (right === null) return null;
      value = operator === '+' ? value + right : value - right;
    }
    return value;
  };
  const value = additive();
  return value !== null && index === tokens.length && Number.isFinite(value) ? value : null;
}

export function applyCadParameterValues(
  source: string,
  values: Record<string, number>
): { source: string; appliedValues: Record<string, number> } {
  const history = parseCadSourceHistory(source);
  const parameterMap = new Map(history.parameters.map((parameter) => [parameter.id, parameter]));
  const edits: Array<{ span: [number, number]; value: string; id: string; number: number }> = [];

  for (const [id, rawValue] of Object.entries(values)) {
    const parameter = parameterMap.get(id);
    if (!parameter) throw new Error(`Unknown CAD design parameter: ${id}`);
    if (!Number.isFinite(rawValue)) throw new Error(`${parameter.label} must be a finite number.`);
    const value = normalizeParameterValue(parameter, rawValue);
    edits.push({
      span: parameter.span,
      value: formatParameterValue(parameter, value),
      id,
      number: value,
    });
  }

  edits.sort((left, right) => right.span[0] - left.span[0]);
  let nextSource = source;
  for (const edit of edits) {
    nextSource = `${nextSource.slice(0, edit.span[0])}${edit.value}${nextSource.slice(edit.span[1])}`;
  }
  return {
    source: nextSource,
    appliedValues: Object.fromEntries(edits.map((edit) => [edit.id, edit.number])),
  };
}

function sourceLineOffsets(lines: readonly string[]): number[] {
  const offsets: number[] = [];
  let offset = 0;
  for (const line of lines) {
    offsets.push(offset);
    offset += line.length + 1;
  }
  return offsets;
}

function collectFunctions(lines: readonly string[]): SourceFunction[] {
  const functions: SourceFunction[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const match = line.match(FUNCTION_RE);
    if (!match) continue;
    let endLineIndex = lines.length;
    for (let next = index + 1; next < lines.length; next += 1) {
      const candidate = lines[next];
      if (candidate && !/^\s/.test(candidate) && /^(?:def|class)\s+/.test(candidate)) {
        endLineIndex = next;
        break;
      }
    }
    functions.push({
      name: match[1],
      line: index + 1,
      startLineIndex: index,
      endLineIndex,
    });
  }
  return functions;
}

function collectFunctionDependencies(
  lines: readonly string[],
  item: SourceFunction,
  functionMap: ReadonlyMap<string, SourceFunction>
): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (let index = item.startLineIndex + 1; index < item.endLineIndex; index += 1) {
    for (const operation of callsInLine(lines[index])) {
      if (operation === item.name || !functionMap.has(operation) || seen.has(operation)) continue;
      seen.add(operation);
      result.push(operation);
    }
  }
  return result;
}

function reachableFunctions(
  functionMap: ReadonlyMap<string, SourceFunction>,
  dependencies: ReadonlyMap<string, readonly string[]>
): SourceFunction[] {
  const root = functionMap.get('gen_step');
  if (!root) return [...functionMap.values()];
  const ordered: SourceFunction[] = [];
  const visited = new Set<string>();
  const visit = (item: SourceFunction) => {
    if (visited.has(item.name)) return;
    visited.add(item.name);
    ordered.push(item);
    for (const name of dependencies.get(item.name) ?? []) {
      const dependency = functionMap.get(name);
      if (dependency) visit(dependency);
    }
  };
  visit(root);
  return ordered;
}

function sourceFeatureGroup(
  lines: readonly string[],
  item: SourceFunction,
  dependencies: string[]
): CadSourceFeatureGroup {
  const features: CadSourceFeature[] = [];
  for (let index = item.startLineIndex + 1; index < item.endLineIndex; index += 1) {
    const line = lines[index];
    const calls = callsWithColumns(line);
    for (const call of calls) {
      const operation = call.name;
      const definition = FEATURE_OPERATIONS.get(operation);
      if (!definition) continue;
      const assemblyAdd = operation === 'add' && /\w+\.add\s*\(/.test(line);
      if (operation === 'add' && !assemblyAdd) continue;
      const kind = assemblyAdd ? 'assembly' : definition.kind;
      const label = assemblyAdd ? 'Add component' : definition.label;
      features.push({
        id: `${item.name}:${index + 1}:${operation}:${features.length + 1}`,
        operation,
        label,
        kind,
        line: index + 1,
        column: call.column,
      });
    }
  }
  return {
    id: item.name,
    functionName: item.name,
    label: functionLabel(item.name),
    line: item.line,
    dependencies,
    features,
  };
}

function callsInLine(line: string): string[] {
  return callsWithColumns(line).map((call) => call.name);
}

function callsWithColumns(line: string): Array<{ name: string; column: number }> {
  const calls: Array<{ name: string; column: number }> = [];
  CALL_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CALL_RE.exec(line))) calls.push({ name: match[1], column: match.index });
  return calls;
}

function functionLabel(name: string): string {
  if (name === 'gen_step') return 'Model assembly';
  return name
    .replace(/^_+/, '')
    .split('_')
    .filter(Boolean)
    .map((word) => `${word[0]?.toUpperCase() ?? ''}${word.slice(1)}`)
    .join(' ');
}

function identifierLabel(name: string): string {
  const acronyms = new Set(['ID', 'OD', 'X', 'Y', 'Z']);
  return name
    .replace(/^_+/, '')
    .split('_')
    .filter(Boolean)
    .map((word, index) => {
      if (acronyms.has(word.toUpperCase())) return word.toUpperCase();
      const lower = word.toLowerCase();
      return index === 0 ? `${lower[0]?.toUpperCase() ?? ''}${lower.slice(1)}` : lower;
    })
    .join(' ');
}

function collectParameters(
  source: string,
  lines: readonly string[],
  lineOffsets: readonly number[]
): { parameters: CadDesignParameter[]; diagnostics: string[] } {
  const parameters: CadDesignParameter[] = [];
  const diagnostics: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const markerMatch = lines[index].match(PARAMETER_MARKER_RE);
    if (!markerMatch) continue;
    let marker: ParameterMarker;
    try {
      marker = JSON.parse(markerMatch[1]) as ParameterMarker;
    } catch {
      diagnostics.push(`Line ${index + 1}: @cad-parameter must be followed by valid JSON.`);
      continue;
    }
    const assignmentIndex = nextNonEmptyLine(lines, index + 1);
    const assignment =
      assignmentIndex === -1 ? null : lines[assignmentIndex].match(NUMERIC_ASSIGNMENT_RE);
    if (!assignment) {
      diagnostics.push(
        `Line ${index + 1}: @cad-parameter must precede an uppercase numeric assignment.`
      );
      continue;
    }
    const symbol = assignment[1];
    const defaultValue = Number(assignment[2]);
    const min = Number(marker.min);
    const max = Number(marker.max);
    const step = Number(marker.step);
    if (
      ![min, max, step].every(Number.isFinite) ||
      min > defaultValue ||
      max < defaultValue ||
      step <= 0
    ) {
      diagnostics.push(
        `Line ${index + 1}: ${symbol} needs finite min/max/step values containing its default.`
      );
      continue;
    }
    const valueColumn = lines[assignmentIndex].indexOf(assignment[2]);
    const valueStart = lineOffsets[assignmentIndex] + valueColumn;
    parameters.push({
      id: stringValue(marker.id) || symbol.toLowerCase(),
      symbol,
      label: stringValue(marker.label) || functionLabel(symbol),
      ...(stringValue(marker.description) ? { description: stringValue(marker.description) } : {}),
      ...(stringValue(marker.unit) ? { unit: stringValue(marker.unit) } : {}),
      min,
      max,
      step,
      defaultValue,
      line: assignmentIndex + 1,
      span: [valueStart, valueStart + assignment[2].length],
      groupIds: [],
      featureIds: [],
    });
  }
  const duplicateIds = duplicateValues(parameters.map((parameter) => parameter.id));
  if (duplicateIds.length > 0) {
    diagnostics.push(`Duplicate CAD parameter ids: ${duplicateIds.join(', ')}.`);
    return {
      parameters: parameters.filter((parameter) => !duplicateIds.includes(parameter.id)),
      diagnostics,
    };
  }
  return { parameters, diagnostics };
}

interface FunctionParameterInput {
  source: string;
  lineOffsets: readonly number[];
  orderedFunctions: readonly SourceFunction[];
  groups: readonly CadSourceFeatureGroup[];
}

/**
 * cadgen 0.5 makes a plain @step function's default arguments the authored
 * geometry-parameter contract. Keep their exact numeric spans so the desktop
 * can offer the same safe, bounded edit path it previously offered for
 * uppercase constants in legacy .step.py generators.
 */
function collectFunctionDefaultParameters(input: FunctionParameterInput): CadDesignParameter[] {
  const groups = new Map(input.groups.map((group) => [group.functionName, group]));
  const parameters: CadDesignParameter[] = [];
  for (const item of input.orderedFunctions) {
    const group = groups.get(item.name);
    if (!group) continue;
    const ranges = functionArgumentRanges(input.source, input.lineOffsets, item);
    for (const range of ranges) {
      const match = range.text.match(
        /^([A-Za-z_]\w*)\s*(?::[\s\S]*?)?\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$/
      );
      if (!match) continue;
      const symbol = match[1];
      const rawValue = match[2];
      const defaultValue = Number(rawValue);
      if (!Number.isFinite(defaultValue)) continue;
      const bounds = inferredParameterBounds(symbol, defaultValue);
      const relativeValueStart = range.text.lastIndexOf(rawValue);
      const valueStart = range.start + relativeValueStart;
      const featureIds = group.features
        .filter((feature) =>
          featureUsesIdentifier(input.source, input.lineOffsets, feature, symbol)
        )
        .map((feature) => feature.id);
      parameters.push({
        id: `parameter_${slugId(item.name)}_${slugId(symbol)}`,
        symbol,
        label: identifierLabel(symbol),
        description: 'Geometry parameter declared on the model function.',
        unit: bounds.unit,
        min: bounds.min,
        max: bounds.max,
        step: bounds.step,
        defaultValue,
        line: item.line,
        span: [valueStart, valueStart + rawValue.length],
        groupIds: [group.id],
        featureIds,
        origin: 'function-parameter',
      });
    }
  }
  return parameters;
}

function functionArgumentRanges(
  source: string,
  lineOffsets: readonly number[],
  item: SourceFunction
): ArgumentRange[] {
  const start = lineOffsets[item.startLineIndex] ?? 0;
  const open = source.indexOf('(', start);
  if (open === -1) return [];
  let depth = 1;
  let quote = '';
  let escaped = false;
  for (let index = open + 1; index < source.length; index += 1) {
    const char = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === '(' || char === '[' || char === '{') depth += 1;
    if (char === ')' || char === ']' || char === '}') depth -= 1;
    if (depth === 0) return splitTopLevelArguments(source, open + 1, index);
  }
  return [];
}

interface InferredParameterInput {
  source: string;
  lines: readonly string[];
  lineOffsets: readonly number[];
  orderedFunctions: readonly SourceFunction[];
  groups: readonly CadSourceFeatureGroup[];
  assignments: ReadonlyMap<string, string>;
  declaredSymbols: ReadonlySet<string>;
}

function collectInferredSourceParameters(input: InferredParameterInput): CadDesignParameter[] {
  const groupIds = new Set(input.groups.map((group) => group.id));
  const sourceSymbols = upperSymbols(input.source);
  const parameters: CadDesignParameter[] = [];
  for (let index = 0; index < input.lines.length; index += 1) {
    const assignment = input.lines[index].match(NUMERIC_ASSIGNMENT_RE);
    if (!assignment) continue;
    const symbol = assignment[1];
    if (
      input.declaredSymbols.has(symbol) ||
      !DIMENSION_SYMBOL_RE.test(symbol) ||
      NON_DESIGN_SYMBOL_RE.test(symbol)
    ) {
      continue;
    }
    let linkedGroupIds = input.orderedFunctions
      .filter(
        (item) =>
          groupIds.has(item.name) &&
          functionUsesSourceSymbol(input.lines, item, symbol, input.assignments)
      )
      .map((item) => item.name);
    if (linkedGroupIds.length === 0) {
      const usedOutsideAssignment =
        sourceSymbols.filter((candidate) => candidate === symbol).length > 1;
      const modelGroup = input.groups.find((group) => group.functionName === 'gen_step');
      if (!usedOutsideAssignment || !modelGroup) continue;
      linkedGroupIds = [modelGroup.id];
    }
    const linkedFeatureIds = input.groups.flatMap((group) =>
      group.features
        .filter((feature) =>
          featureUsesSymbol(
            input.source,
            input.lines,
            input.lineOffsets,
            feature,
            symbol,
            input.assignments
          )
        )
        .map((feature) => feature.id)
    );
    const defaultValue = Number(assignment[2]);
    const bounds = inferredParameterBounds(symbol, defaultValue);
    const valueColumn = input.lines[index].indexOf(assignment[2]);
    const valueStart = input.lineOffsets[index] + valueColumn;
    parameters.push({
      id: `source_${symbol.toLowerCase()}`,
      symbol,
      label: identifierLabel(symbol),
      description: 'Automatically exposed from a dimension-like source variable used by the model.',
      unit: bounds.unit,
      min: bounds.min,
      max: bounds.max,
      step: bounds.step,
      defaultValue,
      line: index + 1,
      span: [valueStart, valueStart + assignment[2].length],
      groupIds: linkedGroupIds,
      featureIds: linkedFeatureIds,
      origin: 'source-variable',
    });
  }
  return parameters;
}

interface FeatureLiteralParameterInput {
  source: string;
  lines: readonly string[];
  lineOffsets: readonly number[];
  groups: readonly CadSourceFeatureGroup[];
}

function collectFeatureLiteralParameters(
  input: FeatureLiteralParameterInput
): CadDesignParameter[] {
  const parameters: CadDesignParameter[] = [];
  for (const group of input.groups) {
    for (const feature of group.features) {
      const range = featureCallRange(input.source, input.lineOffsets, feature);
      if (!range) continue;
      const args = splitTopLevelArguments(input.source, range.argumentsStart, range.argumentsEnd);
      const selectorNames =
        feature.operation === 'fillet'
          ? ['radius']
          : feature.operation === 'chamfer'
            ? ['length']
            : null;
      let numericPositionIndex = 0;
      for (let argumentIndex = 0; argumentIndex < args.length; argumentIndex += 1) {
        const arg = args[argumentIndex];
        const keyword = topLevelKeyword(arg.text);
        if (keyword?.name === 'mode' || keyword?.name === 'align') continue;
        const valueRange = keyword
          ? trimRange(input.source, arg.start + keyword.valueStart, arg.end)
          : trimRange(input.source, arg.start, arg.end);
        const rawValue = input.source.slice(valueRange.start, valueRange.end);
        if (!DIRECT_NUMBER_RE.test(rawValue)) continue;
        let name = keyword?.name;
        if (!name && selectorNames) {
          name = selectorNames[numericPositionIndex];
          numericPositionIndex += 1;
        } else if (!name) {
          name = FEATURE_ARGUMENT_NAMES[feature.operation]?.[argumentIndex];
        }
        if (!name) continue;
        const defaultValue = Number(rawValue);
        const bounds = inferredParameterBounds(name, defaultValue);
        parameters.push({
          id: `feature_${slugId(feature.id)}_${slugId(name)}`,
          symbol: `${feature.operation}.${name}`,
          label: `${feature.label} ${identifierLabel(name).toLowerCase()}`,
          description: `Direct ${name} value on this ${feature.label.toLowerCase()} operation.`,
          unit: bounds.unit,
          min: bounds.min,
          max: bounds.max,
          step: bounds.step,
          defaultValue,
          line: feature.line,
          span: [valueRange.start, valueRange.end],
          groupIds: [group.id],
          featureIds: [feature.id],
          origin: 'feature-literal',
        });
      }
    }
  }
  return parameters;
}

function collectUpperAssignments(lines: readonly string[]): Map<string, string> {
  const assignments = new Map<string, string>();
  for (const line of lines) {
    const match = line.match(UPPER_ASSIGNMENT_RE);
    if (!match) continue;
    assignments.set(match[1], match[2].split('#')[0].trim());
  }
  return assignments;
}

function functionUsesSourceSymbol(
  lines: readonly string[],
  item: SourceFunction,
  symbol: string,
  assignments: ReadonlyMap<string, string>
): boolean {
  for (let index = item.startLineIndex + 1; index < item.endLineIndex; index += 1) {
    if (lineUsesSourceSymbol(lines[index], symbol, assignments)) return true;
  }
  return false;
}

function featureUsesSymbol(
  source: string,
  lines: readonly string[],
  lineOffsets: readonly number[],
  feature: CadSourceFeature,
  symbol: string,
  assignments: ReadonlyMap<string, string>
): boolean {
  const range = featureCallRange(source, lineOffsets, feature);
  const text = range ? source.slice(range.start, range.end) : (lines[feature.line - 1] ?? '');
  return lineUsesSourceSymbol(text, symbol, assignments);
}

function featureUsesIdentifier(
  source: string,
  lineOffsets: readonly number[],
  feature: CadSourceFeature,
  identifier: string
): boolean {
  const range = featureCallRange(source, lineOffsets, feature);
  if (!range) return false;
  return textUsesIdentifier(source.slice(range.start, range.end), identifier);
}

function lineUsesSourceSymbol(
  text: string,
  symbol: string,
  assignments: ReadonlyMap<string, string>
): boolean {
  if (textUsesIdentifier(text, symbol)) return true;
  const pending = upperSymbols(text);
  const visited = new Set<string>();
  while (pending.length > 0) {
    const candidate = pending.pop();
    if (!candidate || visited.has(candidate)) continue;
    if (candidate === symbol) return true;
    visited.add(candidate);
    const expression = assignments.get(candidate);
    if (expression) pending.push(...upperSymbols(expression));
  }
  return false;
}

function textUsesIdentifier(text: string, identifier: string): boolean {
  const escaped = identifier.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`\\b${escaped}\\b`).test(text);
}

function upperSymbols(text: string): string[] {
  UPPER_SYMBOL_RE.lastIndex = 0;
  return [...text.matchAll(UPPER_SYMBOL_RE)].map((match) => match[0]);
}

interface CallRange {
  start: number;
  end: number;
  argumentsStart: number;
  argumentsEnd: number;
}

function featureCallRange(
  source: string,
  lineOffsets: readonly number[],
  feature: CadSourceFeature
): CallRange | null {
  const start = (lineOffsets[feature.line - 1] ?? 0) + (feature.column ?? 0);
  const open = source.indexOf('(', start + feature.operation.length);
  if (open === -1) return null;
  let depth = 1;
  let quote = '';
  let escaped = false;
  let comment = false;
  for (let index = open + 1; index < source.length; index += 1) {
    const char = source[index];
    if (comment) {
      if (char === '\n') comment = false;
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
      continue;
    }
    if (char === '#' && depth > 0) {
      comment = true;
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === '(' || char === '[' || char === '{') depth += 1;
    if (char === ')' || char === ']' || char === '}') depth -= 1;
    if (depth === 0) {
      return { start, end: index + 1, argumentsStart: open + 1, argumentsEnd: index };
    }
  }
  return null;
}

interface ArgumentRange {
  text: string;
  start: number;
  end: number;
}

function splitTopLevelArguments(source: string, start: number, end: number): ArgumentRange[] {
  const ranges: ArgumentRange[] = [];
  let rangeStart = start;
  let depth = 0;
  let quote = '';
  let escaped = false;
  for (let index = start; index <= end; index += 1) {
    const char = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === '(' || char === '[' || char === '{') depth += 1;
    if (char === ')' || char === ']' || char === '}') depth -= 1;
    if ((char === ',' && depth === 0) || index === end) {
      const rangeEnd = index === end ? end : index;
      const trimmed = trimRange(source, rangeStart, rangeEnd);
      if (trimmed.end > trimmed.start) {
        ranges.push({
          text: source.slice(trimmed.start, trimmed.end),
          start: trimmed.start,
          end: trimmed.end,
        });
      }
      rangeStart = index + 1;
    }
  }
  return ranges;
}

function trimRange(source: string, start: number, end: number): { start: number; end: number } {
  while (start < end && /\s/.test(source[start])) start += 1;
  while (end > start && /\s/.test(source[end - 1])) end -= 1;
  return { start, end };
}

function topLevelKeyword(text: string): { name: string; valueStart: number } | null {
  const match = text.match(/^([A-Za-z_]\w*)\s*=\s*/);
  return match ? { name: match[1], valueStart: match[0].length } : null;
}

function inferredParameterBounds(
  symbol: string,
  value: number
): { min: number; max: number; step: number; unit: string } {
  const angular = /(?:^|_)(?:ANGLE|ARC)(?:_|$)|revolution_arc/i.test(symbol);
  const magnitude = Math.abs(value);
  const step = angular ? 1 : niceParameterStep(magnitude);
  if (angular) return { min: 0, max: 360, step, unit: '°' };
  if (value > 0) {
    return {
      min: Math.max(step, snapParameterBound(value * 0.25, step, 'down')),
      max: Math.max(value, snapParameterBound(value * 2.5, step, 'up')),
      step,
      unit: 'mm',
    };
  }
  const reach = Math.max(magnitude, step * 10);
  return {
    min: snapParameterBound(value - reach, step, 'down'),
    max: snapParameterBound(value + reach, step, 'up'),
    step,
    unit: 'mm',
  };
}

function niceParameterStep(magnitude: number): number {
  if (magnitude >= 1000) return 10;
  if (magnitude >= 100) return 5;
  if (magnitude >= 10) return 1;
  if (magnitude >= 1) return 0.1;
  return 0.01;
}

function snapParameterBound(value: number, step: number, direction: 'up' | 'down'): number {
  const scaled = value / step;
  const rounded = direction === 'up' ? Math.ceil(scaled) : Math.floor(scaled);
  return Number((rounded * step).toFixed(Math.min(8, decimalPlaces(step))));
}

function slugId(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function nextNonEmptyLine(lines: readonly string[], start: number): number {
  for (let index = start; index < lines.length; index += 1) {
    if (lines[index].trim()) return index;
  }
  return -1;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function duplicateValues(values: readonly string[]): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  }
  return [...duplicates];
}

function normalizeParameterValue(parameter: CadDesignParameter, rawValue: number): number {
  const clamped = Math.min(Math.max(rawValue, parameter.min), parameter.max);
  const steps = Math.round((clamped - parameter.min) / parameter.step);
  return Math.min(parameter.max, parameter.min + steps * parameter.step);
}

function formatParameterValue(parameter: CadDesignParameter, value: number): string {
  const precision = Math.min(
    8,
    Math.max(decimalPlaces(parameter.step), decimalPlaces(parameter.defaultValue))
  );
  const fixed = value.toFixed(precision);
  return fixed.includes('.') ? fixed.replace(/0+$/, '').replace(/\.$/, '') : fixed;
}

function decimalPlaces(value: number): number {
  const text = String(value);
  if (text.includes('e-')) return Number(text.split('e-')[1]) || 0;
  return text.includes('.') ? text.length - text.indexOf('.') - 1 : 0;
}
