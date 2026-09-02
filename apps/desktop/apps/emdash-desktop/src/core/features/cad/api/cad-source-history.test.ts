import { describe, expect, it } from 'vitest';
import { applyCadParameterValues, parseCadSourceHistory } from './cad-source-history';

const SOURCE = `from build123d import *

# @cad-parameter {"label":"Overall length","min":3000,"max":5000,"step":50,"unit":"mm"}
OVERALL_LENGTH = 4200.0

def _body():
    with BuildPart() as body:
        with BuildSketch():
            RectangleRounded(OVERALL_LENGTH, 1800, 80)
        extrude(amount=400)
        fillet(body.edges(), 20)
    return body.part

def _wheel():
    with BuildPart() as wheel:
        Cylinder(radius=340, height=220)
    return wheel.part

def gen_step():
    asm = AssemblyHelper("car")
    asm.add(_body(), "body")
    asm.add(_wheel(), "wheel")
    return asm.build()
`;

describe('CAD source history', () => {
  it('follows model helpers instead of stopping at the first BuildPart', () => {
    const history = parseCadSourceHistory(SOURCE);

    expect(history.groups.map((group) => group.functionName)).toEqual([
      'gen_step',
      '_body',
      '_wheel',
    ]);
    expect(history.groups[1].features.map((feature) => feature.operation)).toEqual([
      'BuildPart',
      'BuildSketch',
      'RectangleRounded',
      'extrude',
      'fillet',
    ]);
    expect(history.groups[2].features.at(-1)?.operation).toBe('Cylinder');
  });

  it('preserves additive and subtractive construction intent for sketches and consumers', () => {
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
    return part.part
`);
    const features = history.groups[0]?.features ?? [];

    expect(features.find((feature) => feature.operation === 'Rectangle')?.mode).toBe('add');
    expect(features.find((feature) => feature.operation === 'Circle')?.mode).toBe('subtract');
    expect(features.find((feature) => feature.operation === 'extrude')?.mode).toBe('add');
    expect(features.find((feature) => feature.operation === 'revolve')?.mode).toBe('subtract');
  });

  it('resolves authored sketch planes and locations into model coordinates', () => {
    const history = parseCadSourceHistory(`
GROUND_CLEARANCE = 160
BASE_FRONT = 900
BASE_REAR = -1100

def gen_step():
    base_cx = (BASE_FRONT + BASE_REAR) / 2
    with BuildPart() as part:
        with BuildSketch(Plane.XY.offset(GROUND_CLEARANCE)):
            with Locations((base_cx, 25)):
                RectangleRounded(4200, 1800, 200)
        extrude(amount=400)
    return part.part
`);

    const sketch = history.groups[0]?.features.find(
      (feature) => feature.operation === 'BuildSketch'
    );
    expect(sketch?.plane).toBe('XY');
    expect(sketch?.sketchOrigin).toEqual([-100, 25, 160]);
  });

  it('applies principal-plane offsets along each plane normal', () => {
    const history = parseCadSourceHistory(`
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
    const sketches = history.groups[0]?.features.filter(
      (feature) => feature.operation === 'BuildSketch'
    );

    expect(sketches?.map((feature) => [feature.plane, feature.sketchOrigin])).toEqual([
      ['XY', [0, 0, 12]],
      ['XZ', [0, -12, 0]],
      ['YZ', [12, 0, 0]],
    ]);
  });

  it('keeps explicitly declared design parameters as the trusted tier', () => {
    const history = parseCadSourceHistory(`${SOURCE}\nUNDECLARED_NUMBER = 12\n`);

    expect(history.parameters.filter((parameter) => parameter.origin === 'declared')).toEqual([
      expect.objectContaining({
        id: 'overall_length',
        symbol: 'OVERALL_LENGTH',
        label: 'Overall length',
        unit: 'mm',
        min: 3000,
        max: 5000,
        step: 50,
        defaultValue: 4200,
        groupIds: ['_body'],
        featureIds: [expect.stringContaining('RectangleRounded')],
        origin: 'declared',
      }),
    ]);
    expect(history.parameters).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ symbol: 'UNDECLARED_NUMBER' })])
    );
  });

  it('exposes direct feature literals and dimension-like source variables automatically', () => {
    const source = `
OVERALL_HEIGHT = 100
ROOF_Z = OVERALL_HEIGHT
SAMPLE_STEP = 2

def gen_step():
    with BuildPart() as part:
        Box(
            20,
            10,
            ROOF_Z,
        )
        fillet(part.edges(), 2)
    return part.part
`;
    const history = parseCadSourceHistory(source);

    expect(history.parameters).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          symbol: 'OVERALL_HEIGHT',
          defaultValue: 100,
          origin: 'source-variable',
          featureIds: [expect.stringContaining(':Box:')],
        }),
        expect.objectContaining({
          symbol: 'Box.length',
          defaultValue: 20,
          origin: 'feature-literal',
        }),
        expect.objectContaining({
          symbol: 'Box.width',
          defaultValue: 10,
          origin: 'feature-literal',
        }),
        expect.objectContaining({
          symbol: 'fillet.radius',
          defaultValue: 2,
          origin: 'feature-literal',
        }),
      ])
    );
    expect(history.parameters).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ symbol: 'SAMPLE_STEP' })])
    );

    const height = history.parameters.find((parameter) => parameter.symbol === 'OVERALL_HEIGHT');
    const length = history.parameters.find((parameter) => parameter.symbol === 'Box.length');
    expect(height).toBeDefined();
    expect(length).toBeDefined();
    const result = applyCadParameterValues(source, {
      [height!.id]: 150,
      [length!.id]: 25,
    });
    expect(result.source).toContain('OVERALL_HEIGHT = 150');
    expect(result.source).toContain('            25,');
  });

  it('exposes cadgen 0.5 model-function defaults as editable geometry parameters', () => {
    const source = `from cadgen import build123d as bd
from cadgen import step

@step()
def bracket(
    width: float = 40.0,
    height=20,
    hole_radius: float = 3.5,
    label: str = "mount",
):
    body = bd.Box(width, 10, height)
    hole = bd.Cylinder(hole_radius, height)
    return body - hole
`;
    const history = parseCadSourceHistory(source);

    expect(history.parameters).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'parameter_bracket_width',
          symbol: 'width',
          defaultValue: 40,
          groupIds: ['bracket'],
          featureIds: [expect.stringContaining(':Box:')],
          origin: 'function-parameter',
        }),
        expect.objectContaining({
          id: 'parameter_bracket_height',
          symbol: 'height',
          defaultValue: 20,
          featureIds: expect.arrayContaining([
            expect.stringContaining(':Box:'),
            expect.stringContaining(':Cylinder:'),
          ]),
          origin: 'function-parameter',
        }),
        expect.objectContaining({
          id: 'parameter_bracket_hole_radius',
          symbol: 'hole_radius',
          defaultValue: 3.5,
          featureIds: [expect.stringContaining(':Cylinder:')],
          origin: 'function-parameter',
        }),
      ])
    );
    expect(history.parameters).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ symbol: 'label' })])
    );

    const result = applyCadParameterValues(source, {
      parameter_bracket_width: 55,
      parameter_bracket_hole_radius: 4.2,
    });
    expect(result.source).toContain('width: float = 55,');
    expect(result.source).toContain('hole_radius: float = 4.2,');
  });

  it('surgically applies and snaps a bounded parameter value', () => {
    const result = applyCadParameterValues(SOURCE, { overall_length: 4324 });

    expect(result.appliedValues).toEqual({ overall_length: 4300 });
    expect(result.source).toContain('OVERALL_LENGTH = 4300');
    expect(result.source.replace('OVERALL_LENGTH = 4300', 'OVERALL_LENGTH = 4200.0')).toBe(SOURCE);
  });

  it('reports malformed declarations without exposing unsafe controls', () => {
    const history = parseCadSourceHistory(`
# @cad-parameter {"label":"Bad","min":0}
VALUE = 4
`);

    expect(history.parameters).toEqual([]);
    expect(history.diagnostics[0]).toContain('finite min/max/step');
  });
});
