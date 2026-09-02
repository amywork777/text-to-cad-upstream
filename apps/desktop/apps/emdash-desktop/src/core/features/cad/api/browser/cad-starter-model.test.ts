import { describe, expect, it } from 'vitest';
import { createStarterCadModel, slugifyModelName } from './cad-starter-model';

describe('CAD starter model', () => {
  it('creates a deterministic build123d generator for the named model', () => {
    const starter = createStarterCadModel('Mounting Plate v2');

    expect(starter.fileName).toBe('mounting-plate-v2.py');
    expect(starter.source).toContain('from cadgen import build123d as bd');
    expect(starter.source).toContain('@step()');
    expect(starter.source).toContain('def mounting_plate_v2(');
    expect(starter.source).toContain('part.label = "mounting_plate_v2"');
  });

  it('falls back to an untitled model for punctuation-only names', () => {
    expect(createStarterCadModel('---').fileName).toBe('untitled-model.py');
  });

  it('keeps the decorated function name valid for digit-leading model names', () => {
    expect(createStarterCadModel('3 Wheel Hub').source).toContain('def model_3_wheel_hub(');
  });

  it('normalizes repeated separators without leaking filesystem punctuation', () => {
    expect(slugifyModelName('  Left / Right Bracket  ')).toBe('left-right-bracket');
  });
});
