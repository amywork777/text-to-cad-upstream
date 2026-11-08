/**
 * The generators an FEA result GLB names in its mesh's extras: `cad solve`, as text-to-cad 0.11's
 * `cad <type> solve --out DIR` writes `result.glb`, and `cadgen fea`, as the 0.10 Studio line wrote
 * a `.fea.glb` that a project may still hold. Kept apart from the reader so the renderer can tell a
 * result without loading the FEA viewer's chunk.
 */
const FEA_GENERATORS = new Set(["cad solve", "cadgen fea"]);

/** Whether a mesh's extras `generator` is an FEA result's. */
export function isFeaGenerator(generator) {
  return FEA_GENERATORS.has(generator);
}

/**
 * Whether a loaded scene carries an FEA result: a mesh a solve wrote. Its generator alone says so; what
 * else the result holds is `feaResult.js`'s to read, and one that does not read is the load's alert, never a plain GLB.
 */
export function carriesFeaResult(root) {
  let found = false;
  root?.traverse?.((object) => {
    if (!found && object?.isMesh && object.geometry && isFeaGenerator(object.userData?.generator)) found = true;
  });
  return found;
}
