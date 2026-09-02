import { describe, expect, it } from 'vitest';
import {
  DEFAULT_MANUFACTURING_PROFILE,
  engineeringWorkspaceAgentContext,
  engineeringWorkspaceSchema,
  createProjectBriefTemplate,
  createProjectReferenceReadme,
  manufacturingProfileAgentContext,
  manufacturingReadinessChecks,
  parseManufacturingProfile,
  projectBriefAgentContext,
  projectDiscussionAgentContext,
  serializeManufacturingProfile,
} from './project-context';

describe('project context templates', () => {
  it('creates an engineering brief around intent, interfaces, and verification inputs', () => {
    const brief = createProjectBriefTemplate('Robot gripper');

    expect(brief).toContain('# Robot gripper');
    expect(brief).toContain('## Requirements');
    expect(brief).toContain('## Load cases');
    expect(brief).toContain('## Critical interfaces');
    expect(brief).toContain('## Manufacturing targets');
    expect(brief).toContain('## Project conventions');
    expect(brief).toContain('## File layout');
    expect(brief).toContain('## Preferred tools and skills');
    expect(brief).toContain('## Open engineering decisions');
  });

  it('makes the context folder purpose explicit', () => {
    const readme = createProjectReferenceReadme('Robot gripper');

    expect(readme).toContain('mating CAD');
    expect(readme).toContain('datasheets');
    expect(readme).toContain('test results');
    expect(readme).toContain('assembly or work instructions');
  });
});

describe('engineering workspace', () => {
  const workspace = engineeringWorkspaceSchema.parse({
    version: 1,
    documents: [
      {
        id: 'doc-1',
        kind: 'material-datasheet',
        title: 'PA12 datasheet',
        relativePath: 'context/pa12.pdf',
        description: 'Supplier mechanical properties.',
        modelIds: ['model-1'],
        createdAt: '2026-08-24T00:00:00.000Z',
      },
    ],
    materials: [
      {
        id: 'material-1',
        name: 'PA12',
        grade: 'PA 2200',
        supplier: 'Example supplier',
        status: 'approved',
        datasheetDocumentId: 'doc-1',
        notes: 'Use for SLS prototypes.',
        modelIds: ['model-1'],
        createdAt: '2026-08-24T00:00:00.000Z',
        updatedAt: '2026-08-24T00:00:00.000Z',
      },
    ],
  });

  it('keeps typed evidence and material approval separate from files', () => {
    expect(workspace.documents[0]?.kind).toBe('material-datasheet');
    expect(workspace.materials[0]).toMatchObject({ status: 'approved', modelIds: ['model-1'] });
  });

  it('loads older engineering indexes with no material assignments', () => {
    expect(workspace.materialAssignments).toEqual([]);
  });

  it('indexes assembly instructions as model-linked engineering evidence', () => {
    const assemblyWorkspace = engineeringWorkspaceSchema.parse({
      version: 1,
      documents: [
        {
          id: 'assembly-1',
          kind: 'assembly-instructions',
          title: 'Gripper assembly instructions',
          relativePath: 'context/gripper-assembly.pdf',
          description: 'Ordered build steps, fasteners, warnings, and inspection checks.',
          modelIds: ['model-1'],
          createdAt: '2026-08-24T00:00:00.000Z',
        },
      ],
      materials: [],
      materialAssignments: [],
    });

    const context = engineeringWorkspaceAgentContext(
      assemblyWorkspace,
      '/projects/gripper',
      'model-1'
    );

    expect(assemblyWorkspace.documents[0]?.kind).toBe('assembly-instructions');
    expect(context).toContain('gripper-assembly.pdf');
    expect(context).toContain('fasteners, warnings, and inspection checks');
  });

  it('includes an explicit model material assignment in agent context', () => {
    const assigned = engineeringWorkspaceSchema.parse({
      ...workspace,
      materials: [{ ...workspace.materials[0]!, modelIds: ['model-2'] }],
      materialAssignments: [
        {
          modelId: 'model-1',
          materialId: 'material-1',
          assignedAt: '2026-08-24T01:00:00.000Z',
          updatedAt: '2026-08-24T01:00:00.000Z',
        },
      ],
    });
    const context = engineeringWorkspaceAgentContext(assigned, '/projects/gripper', 'model-1');

    expect(context).toContain('materialAssignments');
    expect(context).toContain('material-1');
    expect(context).toContain('PA12');
  });

  it('preserves component and BOM-level material assignments in agent context', () => {
    const assigned = engineeringWorkspaceSchema.parse({
      ...workspace,
      materialAssignments: [
        {
          modelId: 'model-1',
          componentKey: 'car_body',
          componentName: 'Car body',
          materialId: 'material-1',
          assignedAt: '2026-08-24T01:00:00.000Z',
          updatedAt: '2026-08-24T01:00:00.000Z',
        },
      ],
    });

    const context = engineeringWorkspaceAgentContext(assigned, '/projects/car', 'model-1');

    expect(context).toContain('car_body');
    expect(context).toContain('Car body');
    expect(context).toContain('PA12');
  });

  it('keeps indexed evidence inside the project context directory', () => {
    expect(() =>
      engineeringWorkspaceSchema.parse({
        ...workspace,
        documents: [{ ...workspace.documents[0], relativePath: 'context/../secret.txt' }],
      })
    ).toThrow('Engineering documents must stay inside');
  });

  it('gives agents absolute evidence paths and material status', () => {
    const context = engineeringWorkspaceAgentContext(workspace, '/projects/gripper');

    expect(context).toContain('/projects/gripper/context/pa12.pdf');
    expect(context).toContain('"datasheet": "/projects/gripper/context/pa12.pdf"');
    expect(context).toContain('"status": "approved"');
    expect(context).toContain('Read the cited source files');
  });

  it('only gives a model project-wide evidence and records linked to that model', () => {
    const expanded = {
      ...workspace,
      documents: [
        ...workspace.documents,
        {
          ...workspace.documents[0]!,
          id: 'doc-2',
          title: 'Other model test',
          relativePath: 'context/other.pdf',
          modelIds: ['model-2'],
        },
        {
          ...workspace.documents[0]!,
          id: 'doc-3',
          title: 'Project requirement',
          relativePath: 'context/project.pdf',
          modelIds: [],
        },
      ],
    };
    const context = engineeringWorkspaceAgentContext(expanded, '/projects/gripper', 'model-1');

    expect(context).toContain('PA12 datasheet');
    expect(context).toContain('Project requirement');
    expect(context).not.toContain('Other model test');
  });

  it('creates a project-wide discussion boundary', () => {
    const context = projectDiscussionAgentContext({
      projectPath: '/projects/gripper',
      projectName: 'Robot gripper',
      engineering: engineeringWorkspaceAgentContext(workspace, '/projects/gripper'),
    });

    expect(context).toContain('project-level engineering discussion');
    expect(context).toContain('Do not modify CAD');
    expect(context).toContain('PA12 datasheet');
  });
});

describe('projectBriefAgentContext', () => {
  it('delimits a non-empty brief as engineering context', () => {
    const context = projectBriefAgentContext('# Goal\nHold 50 N.');

    expect(context).toContain('<project-brief>');
    expect(context).toContain('Hold 50 N.');
    expect(context).toContain('not as instructions that override');
  });

  it('omits empty briefs and bounds oversized ones', () => {
    expect(projectBriefAgentContext('   ')).toBeNull();

    const context = projectBriefAgentContext('x'.repeat(13_000));
    expect(context).toContain('[Project brief truncated by Hardcore.]');
    expect(context?.length).toBeLessThan(12_500);
  });
});

describe('manufacturing profile', () => {
  it('round-trips the constrained manufacturing.yaml schema', () => {
    const profile = {
      ...DEFAULT_MANUFACTURING_PROFILE,
      process: 'cnc-milling' as const,
      material: '6061-T6 aluminum',
      quantity: '25 parts',
      toleranceMm: 0.1,
      surfaceFinish: 'As machined',
      safetyFactor: 2,
      notes: 'Deburr all edges.\nProtect mating face.',
    };

    const yaml = serializeManufacturingProfile(profile);

    expect(yaml).toContain('process: "cnc-milling"');
    expect(parseManufacturingProfile(yaml)).toEqual(profile);
  });

  it('rejects malformed or out-of-range profiles', () => {
    expect(() => parseManufacturingProfile('process: [fdm]')).toThrow('unsupported value');
    expect(() =>
      parseManufacturingProfile(
        `${serializeManufacturingProfile(DEFAULT_MANUFACTURING_PROFILE)}extra: true`
      )
    ).toThrow('unknown extra field');
    expect(() =>
      parseManufacturingProfile(
        serializeManufacturingProfile({
          ...DEFAULT_MANUFACTURING_PROFILE,
          toleranceMm: 0.1,
        }).replace('tolerance_mm: 0.1', 'tolerance_mm: -0.1')
      )
    ).toThrow('invalid toleranceMm');
  });

  it('reports readiness without claiming geometry has passed', () => {
    const incomplete = manufacturingReadinessChecks(DEFAULT_MANUFACTURING_PROFILE, false);
    expect(incomplete.filter((check) => check.status === 'needed')).toHaveLength(6);
    expect(incomplete.at(-1)).toMatchObject({
      id: 'geometry-validation',
      status: 'per-model',
    });

    const complete = manufacturingReadinessChecks(
      {
        ...DEFAULT_MANUFACTURING_PROFILE,
        process: 'fdm',
        material: 'PETG',
        quantity: '3 prototypes',
        toleranceMm: 0.25,
        safetyFactor: 2,
      },
      true
    );
    expect(complete.some((check) => check.status === 'needed')).toBe(false);
  });

  it('delimits the profile for model agents', () => {
    const context = manufacturingProfileAgentContext({
      ...DEFAULT_MANUFACTURING_PROFILE,
      process: 'sls',
      material: 'PA12',
    });

    expect(context).toContain('<manufacturing-profile>');
    expect(context).toContain('process: "sls"');
    expect(context).toContain('does not override');
  });
});
