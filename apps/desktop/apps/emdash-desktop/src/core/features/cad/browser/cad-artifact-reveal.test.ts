import { describe, expect, it } from 'vitest';
import { planCadArtifactReveal } from './cad-artifact-reveal';

describe('planCadArtifactReveal', () => {
  it('opens the first STEP when no CAD tab is open and announces the rest', () => {
    expect(
      planCadArtifactReveal({
        newPaths: ['exports/plate.glb', 'models/plate.step', 'models/plate.step'],
        hasOpenCadTab: false,
      })
    ).toEqual({ open: 'models/plate.step', announce: ['exports/plate.glb'] });
  });

  it('falls back to the first artifact when nothing is a STEP', () => {
    expect(
      planCadArtifactReveal({ newPaths: ['exports/plate.stl'], hasOpenCadTab: false })
    ).toEqual({ open: 'exports/plate.stl', announce: [] });
  });

  it('never replaces an open viewer, it announces instead', () => {
    expect(
      planCadArtifactReveal({
        newPaths: ['models/bracket.step', 'models/lid.step'],
        hasOpenCadTab: true,
      })
    ).toEqual({ open: null, announce: ['models/bracket.step', 'models/lid.step'] });
  });

  it('does nothing without new artifacts', () => {
    expect(planCadArtifactReveal({ newPaths: [], hasOpenCadTab: false })).toEqual({
      open: null,
      announce: [],
    });
  });
});
