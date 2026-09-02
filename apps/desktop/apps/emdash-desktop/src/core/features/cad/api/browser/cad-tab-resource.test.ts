import { describe, expect, it } from 'vitest';
import { shouldSyncCadViewerFeatureHistory } from './cad-tab-resource';

describe('shouldSyncCadViewerFeatureHistory', () => {
  it('keeps Feature and Sliders injection enabled for cadgen 0.5 plain Python tabs', () => {
    expect(shouldSyncCadViewerFeatureHistory('models/bracket.py')).toBe(true);
    expect(shouldSyncCadViewerFeatureHistory('models/bracket.PY')).toBe(true);
  });

  it('continues to support canonical STEP tabs and rejects unrelated artifacts', () => {
    expect(shouldSyncCadViewerFeatureHistory('models/bracket.step')).toBe(true);
    expect(shouldSyncCadViewerFeatureHistory('models/bracket.stp')).toBe(true);
    expect(shouldSyncCadViewerFeatureHistory('models/bracket.step.py')).toBe(true);
    expect(shouldSyncCadViewerFeatureHistory('models/bracket.stl')).toBe(false);
  });
});
