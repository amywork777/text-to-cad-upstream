import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { BufferAttribute, BufferGeometry, Group, LineBasicMaterial, LineSegments, Mesh } from 'three';

/**
 * The extras `cadgen cam plan` writes on the scene (spec §10, schema 1): one setup, a face and a pocket, one error.
 * cadgen's own words, kept as the file carries them (`camExtras.json`); a fresh copy each call.
 */
export const camExtras = () => JSON.parse(readFileSync(join(__dirname, 'camExtras.json'), 'utf8'));

/** A LINES node as GLTFLoader builds one: positions, then `_cam_t` and `_cam_op` lowercased, and the node's extras. */
export function camLines(points: number[][], times: number[], ops: number[] | null, extras: Record<string, unknown>, { upper = false } = {}) {
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(new Float32Array(points.flat()), 3));
  geometry.setAttribute(upper ? '_CAM_T' : '_cam_t', new BufferAttribute(new Float32Array(times), 1));
  if (ops) geometry.setAttribute(upper ? '_CAM_OP' : '_cam_op', new BufferAttribute(new Float32Array(ops), 1));
  const line = new LineSegments(geometry, new LineBasicMaterial());
  Object.assign(line.userData, extras);
  return line;
}

const triangle = () => {
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(new Float32Array([0, 0, 0, 10, 0, 0, 0, 10, 0]), 3));
  return geometry;
};

/**
 * A scene as `cadgen cam plan` writes one, in mm: the part, the stock after the job, the top setup's feed moves
 * (three segments, written out of time order: the face's two, then the pocket's one) and its rapids (one).
 */
export function camScene({ extras = camExtras() as Record<string, unknown> | null, generator = 'cadgen cam' } = {}) {
  const root = new Group();
  if (generator) root.userData.generator = generator;
  if (extras) root.userData.cam = extras;
  const part = new Mesh(triangle());
  part.name = 'part';
  const stock = new Mesh(triangle());
  stock.userData.kind = 'stock';
  root.add(part, stock);
  root.add(camLines(
    [[0, 0, 0], [10, 0, 0], [5, 5, -2], [5, 9, -2], [10, 0, 0], [10, 10, 0]],
    [0, 10, 40, 80, 10, 20],
    [0, 0, 1, 1, 0, 0],
    { generator, setup: 'top', kind: 'feed' },
  ));
  root.add(camLines([[10, 10, 0], [5, 5, 5]], [20, 30], [1, 1], { generator, setup: 'top', kind: 'rapid' }));
  return root;
}
