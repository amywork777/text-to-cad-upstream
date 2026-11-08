import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import SketchPanel from '../../../../dist/renderers/xbf/edit/SketchPanel.js';

afterEach(cleanup);

const line = (id: string, extra = {}) => ({ id, kind: 'line', start: `${id}.start`, end: `${id}.end`, construction: false, ...extra });

// Sketch1 holds one line; the plate's top face is picked on the model.
function edit(settings: Record<string, unknown>) {
  const before = { curves: [line('Line1')], points: [], relations: [], dimensions: [], status: 'Under defined', dof: 4 };
  const after = { ...before, curves: [line('Line1'), ...['Line2', 'Line3', 'Line4', 'Line5'].map(id => line(id, { construction: true, converted: true }))] };
  return {
    status: 'ready', saving: false, state: { units: 'mm' }, sketch: { name: 'Sketch1', plane: 'Top', state: before },
    sketchTool: 'convert', sketchStep: 0, sketchSelection: [], construction: false,
    sketchSettings: { convertConstruction: false, convertOffset: '', convertReverse: false, ...settings },
    sketchOp: vi.fn(async (op: { kind: string }) => (op.kind === 'convert' ? { ok: true, sketch: { state: after } } : { ok: true })),
    setSketchTool: vi.fn(), setSketchSettings: vi.fn(), exitSketch: vi.fn(), cancelSketch: vi.fn(), selectInSketch: vi.fn(),
  };
}

const TOP = { selectorType: 'face', displaySelector: 'f9', pickData: { surfaceType: 'plane', center: [0, 0, -2.5], area: 800 } };

it("model edges offset into the sketch come in dashed and the offset is drawn from the curves they made", async () => {
  const user = userEvent.setup();
  const offset = edit({ convertOffset: '2', convertReverse: true });
  render(<SketchPanel edit={offset as never} references={[TOP]} />);
  // An offset holds on construction: the box is ticked and cannot be cleared while an offset is typed.
  const construction = screen.getByRole('checkbox', { name: 'For construction' });
  expect(construction.getAttribute('aria-checked')).toBe('true');
  expect(construction.hasAttribute('disabled')).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Convert' }));
  expect(offset.sketchOp.mock.calls.map(call => call[0])).toEqual([
    { kind: 'convert', items: [{ selector: 'f9', type: 'plane', center: [0, 0, -2.5], size: 800 }], construction: true },
    { kind: 'offset', items: ['Line2', 'Line3', 'Line4', 'Line5'], distance: '2', reverse: true, construction: false },
  ]);
  expect(offset.setSketchTool).toHaveBeenCalledWith(null);
  cleanup();
  // Without an offset, Convert brings the edges in as they are.
  const plain = edit({});
  render(<SketchPanel edit={plain as never} references={[TOP]} />);
  await user.click(screen.getByRole('button', { name: 'Convert' }));
  expect(plain.sketchOp.mock.calls.map(call => call[0])).toEqual([
    { kind: 'convert', items: [{ selector: 'f9', type: 'plane', center: [0, 0, -2.5], size: 800 }] },
  ]);
});
