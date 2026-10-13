import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPromptContext, formatPromptMessage } from '@text-to-cad/core/prompt';
import CamJobPanel, { camChoices } from '../../../dist/renderers/glb/CamJobPanel.js';
import { CAM_SHOWN, camDisplaySections, camPathKinds, camReferences, paintCam } from '../../../dist/renderers/glb/camView.js';
import { camOpColours } from '../../../dist/renderers/glb/cam/colours.js';
import { readCamJob } from '../../../dist/renderers/glb/cam/extras.js';
import { camSceneMeshes } from '../../../dist/renderers/glb/cam/playback.js';
import { camScene } from './__tests__/camFile';

beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const job = () => readCamJob(camScene())!;

it('leads with the verdict and its errors, then each setup with its operations: word, tool, time', () => {
  const onChoose = vi.fn();
  const { container } = render(<CamJobPanel active job={job()} colours={camOpColours(job())} chosen="" onChoose={onChoose} />);
  expect(screen.getByRole('region', { name: 'Job' })).toBeTruthy();
  const verdict = container.querySelector('[data-cam-verdict]')!;
  expect(verdict.getAttribute('data-cam-verdict')).toBe('fix');
  expect(verdict.querySelector('[data-cam-verdict-title]')!.textContent).toBe('1 to fix');
  expect(verdict.querySelector('[data-cam-verdict-caption]')!.textContent).toBe('2 warnings');
  // Errors alone, in plain words, under the verdict; warnings go to the agent.
  expect([...verdict.querySelectorAll('[data-cam-finding]')].map((row) => row.textContent)).toEqual(['Tool too long for this pocket']);
  const rows = [...container.querySelectorAll('[data-cam-row]')].map((row) => [row.getAttribute('data-cam-row'), row.textContent]);
  expect(rows).toEqual([['setup:top', 'Top2 operations · 2 min'], ['op:0', 'Face6 mm flat · 30 s'], ['op:1', 'Pocket4 mm ball · 1 min']]);
  expect(container.querySelectorAll('[data-cam-swatch]')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'Select Pocket' }));
  expect(onChoose).toHaveBeenLastCalledWith('op:1');
  fireEvent.click(screen.getByRole('button', { name: 'Select Tool too long for this pocket' }));
  expect(onChoose).toHaveBeenLastCalledWith('finding:0');
});

it('marks the row chosen, and keeps the panel mounted but hidden while Select is not the tool', () => {
  const { container, rerender } = render(<CamJobPanel active job={job()} colours={{}} chosen="op:0" onChoose={() => {}} />);
  expect(screen.getByRole('button', { name: 'Select Face' }).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByRole('button', { name: 'Select Pocket' }).getAttribute('aria-pressed')).toBe('false');
  rerender(<CamJobPanel active={false} job={job()} colours={{}} chosen="" onChoose={() => {}} />);
  expect(container.querySelector('[data-cam-verdict]')).toBeTruthy();
  expect(screen.queryByRole('region', { name: 'Job' })).toBeNull();
});

it('carries a row into Quick Edit: the part\'s faces with the operation\'s sentence, or the whole part', () => {
  const choices = camChoices(job());
  const pocket = camReferences('/work/part.step', choices.get('op:1'));
  expect(pocket).toEqual([{ resource: { kind: 'workspace-file', path: '/work/part.step' }, target: { kind: 'cad-selector', selectors: ['o1.f12', 'o1.f13'] },
    summary: 'Pocket #o1.f12 with T3 4 mm ball, 60 s' }]);
  const message = formatPromptMessage(createPromptContext([{ id: 'r', kind: 'reference', reference: pocket[0] }]));
  expect(message).toContain('Pocket #o1.f12 with T3 4 mm ball, 60 s · /work/part.step#o1.f12,o1.f13');
  expect(camReferences('/work/part.step', choices.get('op:0'))[0].target).toEqual({ kind: 'whole-resource' });
  expect(choices.get('setup:top')).toMatchObject({ ops: [0, 1], faces: ['#o1.f12', '#o1.f13'], summary: 'Top setup: Face, Pocket, 2 min' });
  expect(choices.get('finding:0')).toMatchObject({ ops: [1], summary: 'Tool too long for this pocket (Pocket #o1.f12 with T3 4 mm ball, 60 s)' });
  // A result with no part to name has no references; nothing chosen, none either.
  expect(camReferences('', choices.get('op:1'))).toEqual([]);
  expect(camReferences('/work/part.step', null)).toEqual([]);
});

it('paints a choice as its operations isolated, and a moment as the tool on the path', () => {
  const root = camScene();
  const parsed = readCamJob(root)!;
  const paths = { update: vi.fn(() => true), toolAt: vi.fn(() => ({ point: [1, 2, 3], op: 1, setup: 'top' })) };
  const tool = { show: vi.fn(), hide: vi.fn() };
  const shown = { toolpaths: true, rapids: false, stock: false, part: true };
  paintCam({ controller: { paths, tool }, meshes: camSceneMeshes(root), job: parsed, shown, isolate: new Set([1]), moment: null });
  expect(paths.update).toHaveBeenLastCalledWith({ toolpaths: true, rapids: false, isolate: new Set([1]), time: null, setup: null });
  expect(tool.hide).toHaveBeenCalled();
  expect(paintCam({ controller: { paths, tool }, meshes: camSceneMeshes(root), job: parsed, shown, isolate: null, moment: { t: 45, setup: null } })).toBe(true);
  expect(paths.toolAt).toHaveBeenLastCalledWith(45, null);
  expect(tool.show).toHaveBeenLastCalledWith({ point: [1, 2, 3], op: 1, setup: 'top' });
});

it('gates what Display shows of a result: toolpaths, rapids, stock and part, each only where the file has it', () => {
  const root = camScene();
  const onChange = vi.fn();
  const sections = camDisplaySections({ job: job(), meshes: camSceneMeshes(root), paths: camPathKinds(root), shown: CAM_SHOWN, onChange });
  expect(sections.map((section: any) => [section.id, section.title, section.enabled])).toEqual([
    ['cam-toolpaths', 'Toolpaths', true], ['cam-rapids', 'Rapids', true], ['cam-stock', 'Stock', false], ['cam-part', 'Part', true]]);
  sections[2].onEnabledChange(true);
  expect(onChange).toHaveBeenLastCalledWith({ stock: true });
  root.remove(...camSceneMeshes(root).stock.map((entry: any) => entry.object));
  expect(camDisplaySections({ job: job(), meshes: camSceneMeshes(root), paths: { feed: true, rapid: false }, shown: CAM_SHOWN, onChange })
    .map((section: any) => section.title)).toEqual(['Toolpaths', 'Part']);
});
