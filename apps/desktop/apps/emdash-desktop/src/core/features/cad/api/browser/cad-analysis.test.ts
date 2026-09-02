import { describe, expect, it } from 'vitest';
import {
  cadAnalysisFolderPath,
  cadAnalysisManifestSchema,
  cadAnalysisRootPath,
} from './cad-analysis';

describe('CAD analysis artifacts', () => {
  it('keeps every analysis bundle beside its logical model', () => {
    expect(cadAnalysisRootPath('models/bracket.step.py')).toBe('models/analyses/bracket');
    expect(cadAnalysisRootPath('models/bracket.stp.py')).toBe('models/analyses/bracket');
    expect(cadAnalysisRootPath('bracket.implicit.mjs')).toBe('analyses/bracket');
    expect(cadAnalysisFolderPath('models/bracket.step', 'run-1')).toBe(
      'models/analyses/bracket/run-1'
    );
    expect(() => cadAnalysisRootPath('../outside.step')).toThrow('inside the model workspace');
    expect(() => cadAnalysisRootPath('/tmp/outside.step')).toThrow('inside the model workspace');
  });

  it('records revision, material, setup, status, and ordinary files without claiming a run', () => {
    const manifest = cadAnalysisManifestSchema.parse({
      version: 1,
      id: 'run-1',
      name: 'Bracket proof load',
      type: 'static-structural',
      status: 'planned',
      model: {
        contextKey: 'cad-model:models/bracket',
        path: 'models/bracket.step',
        revisionId: 'revision-1',
        validatedAt: '2026-08-24T00:00:00.000Z',
      },
      materialId: 'material-1',
      solver: 'CalculiX',
      objective: 'Check proof load margin.',
      loads: '1 kN vertical load',
      constraints: 'Fixed mounting holes',
      notes: '',
      files: [
        {
          id: 'file-1',
          name: 'bracket.inp',
          role: 'input',
          relativePath: 'models/analyses/bracket/run-1/bracket.inp',
          addedAt: '2026-08-24T00:00:00.000Z',
        },
      ],
      createdAt: '2026-08-24T00:00:00.000Z',
      updatedAt: '2026-08-24T00:00:00.000Z',
    });

    expect(manifest.status).toBe('planned');
    expect(manifest.files[0]).toMatchObject({ role: 'input', name: 'bracket.inp' });
  });
});
