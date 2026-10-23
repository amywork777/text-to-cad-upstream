import assert from 'node:assert/strict';
import test from 'node:test';
import { dimensionLimits, featureRequirements, datumRelationships } from './pmiReview.js';

const datum = { id: 'A', part: 0, kind: 'datum', datum: { letter: 'A' }, status: 'ok', supported: true,
  featureIds: ['i0/face/1'], refs: [{ ref: 'bracket/f:base', status: 'ok' }] };
const diameter = { id: 'bore', part: 0, kind: 'dimension', status: 'ok', supported: true,
  dimension: { type: 'diameter', nominal: 10, unit: 'mm', tolerance: { lower: 0, upper: .05 } },
  featureIds: ['i0/face/2'], refs: [{ ref: 'bracket/f:bore', status: 'ok' }] };
const position = { id: 'position', part: 0, kind: 'geometric_tolerance', status: 'ok', supported: true,
  tolerance: { characteristic: 'position', value: .1, unit: 'mm', zone: 'diameter', datums: ['A'] },
  featureIds: ['i0/face/2'], refs: [{ ref: 'bracket/f:bore', status: 'ok' }] };
const entries = [datum, diameter, position];
test('size limits preserve signed deviations and never invent an unspecified tolerance', () => {
  assert.deepEqual(dimensionLimits(diameter), { lower: 10, upper: 10.05, unit: 'mm' });
  assert.deepEqual(dimensionLimits({ ...diameter, dimension: { ...diameter.dimension, tolerance: { lower: -.2, upper: .1 } } }), { lower: 9.8, upper: 10.1, unit: 'mm' });
  assert.equal(dimensionLimits({ ...diameter, dimension: { ...diameter.dimension, tolerance: null } }), null);
  assert.equal(dimensionLimits({ ...diameter, status: 'missing' }), null);
});
test('a face reveals every attached requirement, and datum links stay on the same part', () => {
  assert.deepEqual(featureRequirements(entries, ['i0/face/2']).map(e => e.id), ['bore', 'position']);
  assert.deepEqual(featureRequirements(entries, ['i0/face/99']), []);
  const foreign = { ...datum, id: 'other-A', part: 1 };
  assert.deepEqual(datumRelationships(position, [foreign, ...entries]).map(r => [r.role, r.entry?.id]), [['Primary', 'A']]);
});
