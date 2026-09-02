import { describe, expect, it } from 'vitest';
import {
  cadDesignHistoryApi,
  cadDesignHistoryDescriptorSchema,
  createCadDesignHistoryDescriptor,
  parseCadDesignHistoryDescriptor,
} from './cad-design-history-descriptor';
import portableFixture from './fixtures/design-history-v1.json';

const SOURCE_HASH = 'a'.repeat(64);
const STEP_HASH = 'b'.repeat(64);
const PORTABLE_FIXTURE: unknown = portableFixture;

const SOURCE = `from cadgen import build123d as bd
from cadgen import step

@step()
def bracket(width: float = 40, height: float = 20):
    with bd.BuildPart() as part:
        with bd.BuildSketch(bd.Plane.XZ.offset(height)):
            bd.Rectangle(width, 12)
        bd.extrude(amount=height)
    return part.part
`;

function descriptor(source = SOURCE) {
  return createCadDesignHistoryDescriptor({
    source,
    sourcePath: 'src/bracket.py',
    sourceHash: SOURCE_HASH,
    stepPath: 'STEP/bracket.step',
    stepHash: STEP_HASH,
  });
}

describe('CAD design history descriptor', () => {
  it('binds a versioned payload to both source and canonical STEP hashes', () => {
    expect(descriptor()).toEqual(
      expect.objectContaining({
        type: 'designHistory',
        version: 1,
        identityScope: 'revision',
        binding: {
          hashAlgorithm: 'sha256',
          sourcePath: 'src/bracket.py',
          sourceHash: SOURCE_HASH,
          stepPath: 'STEP/bracket.step',
          stepHash: STEP_HASH,
        },
      })
    );
  });

  it('makes IDs deterministic but explicitly revision-local', () => {
    const first = descriptor();
    const second = descriptor();

    expect(first.identityScope).toBe('revision');
    expect(first.features.map((feature) => feature.id)).toEqual(
      second.features.map((feature) => feature.id)
    );
    expect(first.features.find((feature) => feature.operation === 'Rectangle')?.id).toBe(
      'feature:bracket:rectangle:1'
    );
  });

  it('does not collapse distinct authored helper names into the same stable ID', () => {
    const result = descriptor(`${SOURCE}
def _body():
    return bd.Box(1, 1, 1)

def body():
    return bd.Box(2, 2, 2)
`);

    expect(result.groups.map((group) => group.id)).toEqual(
      expect.arrayContaining(['group:_body', 'group:body'])
    );
  });

  it('carries exact source spans, numerical editability, and sketch placement', () => {
    const result = descriptor();
    const rectangle = result.features.find((feature) => feature.operation === 'Rectangle');
    const width = result.parameters.find((parameter) => parameter.symbol === 'width');

    expect(SOURCE.slice(rectangle?.source?.start, rectangle?.source?.end)).toBe(
      'Rectangle(width, 12)'
    );
    expect(rectangle).toEqual(
      expect.objectContaining({
        editability: {
          mode: 'numeric-parameters',
          parameterIds: expect.arrayContaining([width?.id]),
        },
        sketch: {
          plane: 'XZ',
          transform: {
            origin: [0, -20, 0],
            xAxis: [1, 0, 0],
            yAxis: [0, 0, 1],
            normal: [0, -1, 0],
          },
          dimensionIds: expect.arrayContaining([width?.id]),
        },
      })
    );
    expect(SOURCE.slice(width?.source.start, width?.source.end)).toBe('40');
    expect(width?.source.editable).toBe(true);
  });

  it('publishes right-handed principal-plane transforms with offsets along their normals', () => {
    const result = descriptor(`
def gen_step(offset: float = 12):
    with BuildPart() as part:
        with BuildSketch(Plane.XY.offset(offset)):
            Rectangle(10, 10)
        with BuildSketch(Plane.XZ.offset(offset)):
            Rectangle(10, 10)
        with BuildSketch(Plane.YZ.offset(offset)):
            Rectangle(10, 10)
    return part.part
`);
    const sketches = result.features
      .filter((feature) => feature.operation === 'Rectangle')
      .map((feature) => feature.sketch?.transform);

    expect(sketches).toEqual([
      {
        origin: [0, 0, 12],
        xAxis: [1, 0, 0],
        yAxis: [0, 1, 0],
        normal: [0, 0, 1],
      },
      {
        origin: [0, -12, 0],
        xAxis: [1, 0, 0],
        yAxis: [0, 0, 1],
        normal: [0, -1, 0],
      },
      {
        origin: [12, 0, 0],
        xAxis: [0, 1, 0],
        yAxis: [0, 0, 1],
        normal: [1, 0, 0],
      },
    ]);
  });

  it('passes through only exact selector refs supplied by cadgen or the viewer', () => {
    const parsed = descriptor();
    const featureId = parsed.features.find((feature) => feature.operation === 'Rectangle')?.id;
    const result = createCadDesignHistoryDescriptor({
      source: SOURCE,
      sourcePath: 'src/bracket.py',
      sourceHash: SOURCE_HASH,
      stepPath: 'STEP/bracket.step',
      stepHash: STEP_HASH,
      selectorRefsByFeatureId: {
        [featureId!]: [{ kind: 'face', ref: 'cadgen://bracket/face/top' }],
      },
    });

    expect(result.features.find((feature) => feature.id === featureId)?.selectorRefs).toEqual([
      { kind: 'face', ref: 'cadgen://bracket/face/top' },
    ]);
    expect(
      result.features.find((feature) => feature.operation === 'extrude')?.selectorRefs
    ).toEqual([]);
  });

  it('rejects descriptors that are not bound to an accepted artifact', () => {
    expect(() =>
      createCadDesignHistoryDescriptor({
        source: SOURCE,
        sourcePath: 'src/bracket.py',
        sourceHash: SOURCE_HASH,
        stepPath: 'STEP/bracket.step',
        stepHash: '',
      })
    ).toThrow('stepHash must not be empty');
  });

  it('exports a runtime-validated public API and survives a JSON round trip', () => {
    const original = descriptor();
    const parsedJson: unknown = JSON.parse(JSON.stringify(original));

    expect(cadDesignHistoryApi.version).toBe(1);
    expect(cadDesignHistoryApi.schema).toBe(cadDesignHistoryDescriptorSchema);
    expect(cadDesignHistoryApi.parse(parsedJson)).toEqual(original);
    expect(parseCadDesignHistoryDescriptor(parsedJson)).toEqual(original);
  });

  it('round-trips the portable viewer fixture without losing contract data', () => {
    const parsed = parseCadDesignHistoryDescriptor(PORTABLE_FIXTURE);

    expect(JSON.parse(JSON.stringify(parsed))).toEqual(PORTABLE_FIXTURE);
    expect(parsed.features[0]?.selectorRefs).toEqual([
      { kind: 'face', ref: 'cadgen://bracket/face/top' },
    ]);
  });

  it('rejects incompatible versions, malformed hashes, and dangling references', () => {
    const original = descriptor();

    expect(cadDesignHistoryDescriptorSchema.safeParse({ ...original, version: 2 }).success).toBe(
      false
    );
    expect(
      cadDesignHistoryDescriptorSchema.safeParse({
        ...original,
        binding: { ...original.binding, stepHash: 'not-a-sha256' },
      }).success
    ).toBe(false);
    expect(
      cadDesignHistoryDescriptorSchema.safeParse({
        ...original,
        groups: [{ ...original.groups[0], featureIds: ['feature:missing'] }],
      }).success
    ).toBe(false);
  });
});
