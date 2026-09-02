import { describe, expect, it } from 'vitest';
import { createPackagedCadSmokePlan, verifyCadRuntimeLock } from './verify-packaged-cad.ts';

describe('packaged CAD smoke plan', () => {
  it('provisions and runs from the packaged CAD source on Unix', () => {
    const plan = createPackagedCadSmokePlan(
      '/release/resources/hardcore-cad',
      '/tmp/smoke',
      'linux'
    );
    expect(plan.setupScript).toBe('/release/resources/hardcore-cad/tooling/scripts/setup-cad.mjs');
    expect(plan.constraints).toBe(
      '/release/resources/hardcore-cad/tooling/cad-runtime-constraints.txt'
    );
    expect(plan.bundledCadgenSource).toBe(
      '/release/resources/hardcore-cad/vendor/text-to-cad/packages/cadgen'
    );
    expect(plan.installedCadgenSource).toBe(
      '/tmp/smoke/runtime/plugins/text-to-cad/packages/cadgen'
    );
    expect(plan.python).toBe('/tmp/smoke/runtime/venv/bin/python');
    expect(plan.viewerPython).toBe(
      '/tmp/smoke/runtime/plugins/text-to-cad/skills/cad-viewer/scripts/viewer/.venv/bin/python'
    );
    expect(plan.viewerLauncher).toBe(
      '/tmp/smoke/runtime/plugins/text-to-cad/skills/cad-viewer/scripts/viewer/server/main.mjs'
    );
    expect(plan.artifact).toBe('/tmp/smoke/workspace/packaged-smoke.step');
    expect(plan.parallelArtifact).toBe(
      '/tmp/smoke/parallel-workspace/packaged-parallel-smoke.step'
    );
  });

  it('accepts only installed packages that match the packaged dependency lock', () => {
    expect(() =>
      verifyCadRuntimeLock(
        [
          'build123d==0.11.1',
          'cadquery-ocp==7.9.3.1.1',
          'colorama==0.4.6',
          'ezdxf==1.4.4',
          'shapely==2.1.2',
          'pip==25.2',
        ].join('\n'),
        [
          'build123d==0.11.1',
          'cadgen @ file:///bundle/cadgen',
          'cadquery-ocp==7.9.3.1.1',
          'colorama==0.4.6',
          'ezdxf==1.4.4',
          'pip==25.2',
          'shapely==2.1.2',
        ].join('\n')
      )
    ).not.toThrow();
  });

  it('rejects drift and newly installed unpinned dependencies', () => {
    const constraints = [
      'build123d==0.11.1',
      'cadquery-ocp==7.9.3.1.1',
      'ezdxf==1.4.4',
      'shapely==2.1.2',
    ].join('\n');
    expect(() =>
      verifyCadRuntimeLock(
        constraints,
        [
          'build123d==0.12.0',
          'cadquery-ocp==7.9.3.1.1',
          'ezdxf==1.4.4',
          'new-transitive==1.0.0',
          'shapely==2.1.2',
        ].join('\n')
      )
    ).toThrow(/dependency lock mismatch.*build123d.*new-transitive/s);
  });

  it('uses the packaged Windows virtual-environment launcher', () => {
    const plan = createPackagedCadSmokePlan('C:\\release\\hardcore-cad', 'C:\\smoke', 'win32');
    expect(plan.python).toBe('C:\\smoke\\runtime\\venv\\Scripts\\python.exe');
    expect(plan.viewerPython).toBe(
      'C:\\smoke\\runtime\\plugins\\text-to-cad\\skills\\cad-viewer\\scripts\\viewer\\.venv\\Scripts\\python.exe'
    );
    expect(plan.viewerLauncher).toBe(
      'C:\\smoke\\runtime\\plugins\\text-to-cad\\skills\\cad-viewer\\scripts\\viewer\\server\\main.mjs'
    );
    expect(plan.setupScript).toBe('C:\\release\\hardcore-cad\\tooling\\scripts\\setup-cad.mjs');
  });
});
