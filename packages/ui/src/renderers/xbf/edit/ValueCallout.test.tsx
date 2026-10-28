import { cleanup, render } from '@testing-library/react';
import * as THREE from 'three';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ValueCallout from '../../../../dist/renderers/xbf/edit/ValueCallout.js';

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(performance.now()), 0));
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function viewport() {
  const host = document.createElement('div');
  Object.defineProperty(host, 'clientWidth', { value: 800 });
  Object.defineProperty(host, 'clientHeight', { value: 600 });
  document.body.append(host);
  const camera = new THREE.PerspectiveCamera(45, 800 / 600, 1, 1000);
  camera.position.set(0, -80, 60);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  camera.updateProjectionMatrix();
  return { runtimeRef: { current: { THREE, camera, modelGroup: new THREE.Group() } }, hostRef: { current: host }, viewerReadyTick: 1 };
}

it("stands beside what it sizes on the model, and sets the value typed there", async () => {
  const onCommit = vi.fn();
  const { container } = render(<ValueCallout viewport={viewport()} callout={{ at: [0, 0, 0], label: 'Radius', unit: 'mm', text: '1', onCommit }} />);
  const box = container.querySelector<HTMLElement>('[data-cad-callout]')!;
  await vi.waitFor(() => expect(box.style.visibility).toBe('visible'));
  const input = box.querySelector('input')!;
  input.focus();
  input.value = '2.5';
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await vi.waitFor(() => expect(onCommit).toHaveBeenCalledWith('2.5'));
});
