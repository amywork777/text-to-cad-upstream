import { expect, it } from 'vitest';
import { normalizeViewSettings } from '@text-to-cad/core/common/viewSettings.js';
import { NEUTRAL_CLIP, clipApplied, clipSummary } from '../../../../dist/renderers/kit/view-settings/ClipControls.js';

const BOUNDS = { min: [0, 0, 0], max: [10, 10, 10] };

it('the X puts back a clip the settings accept and that cuts nothing; a placed plane cuts its share', () => {
  expect(() => normalizeViewSettings({ clip: NEUTRAL_CLIP })).not.toThrow();
  expect(clipApplied({ clip: NEUTRAL_CLIP })).toBe(false);
  expect(clipApplied({})).toBe(false);
  // A plane at 3 on Y, the lower side kept: 70% of the box cut away.
  const cut = { clip: { enabled: true, axis: 'y', at: 3, invert: false } };
  expect([clipApplied(cut), clipSummary(cut, BOUNDS)]).toEqual([true, '70%']);
});
