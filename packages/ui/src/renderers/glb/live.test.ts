import { expect, it } from 'vitest';
import { GLB_DECLINED_LIVE_COMMANDS, GLB_RESULT_LIVE } from '../../../dist/renderers/glb/tools.js';
import { HOST_LIVE_COMMANDS } from '../../../dist/renderers/kit/shell/liveBinding.js';

it("a result's view answers every host command, carrying it out or saying why not", () => {
  // A plain GLB clears its own selection and declines the rest; a result's view declines each.
  const plain = new Set(['clearSelection', ...Object.keys(GLB_DECLINED_LIVE_COMMANDS)]);
  for (const name of HOST_LIVE_COMMANDS) {
    expect(plain.has(name)).toBe(true);
    expect(typeof GLB_RESULT_LIVE.declined[name]).toBe('string');
  }
});
