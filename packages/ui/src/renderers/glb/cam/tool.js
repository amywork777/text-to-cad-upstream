/**
 * The tool that rides a CAM result's path while it plays: a plain cutter (a cylinder, or a ball on a
 * cylinder for a ball end mill) under a wider holder, its tip on the path and its shank along the setup's
 * axis. Sized in mm from the operation's tool (its diameter, `toolDiameterMm`; 6 mm when the file does not
 * say), so it reads at the scale of the part, and built once per tool, swapped as the program changes tools.
 */

const DEFAULT_RADIUS_MM = 3;
const COLOURS = Object.freeze({ cutter: "#a1a1aa", holder: "#52525b" });
// A setup's orientation as the job writes it: the axis the tool comes in along, from the part's side.
const AXES = Object.freeze({ "+Z": [0, 0, 1], "-Z": [0, 0, -1], "+X": [1, 0, 0], "-X": [-1, 0, 0], "+Y": [0, 1, 0], "-Y": [0, -1, 0] });

/** The axis a setup's tool stands along, in CAD space: its orientation's, else +Z (a 3+2 tilt is drawn upright). */
export const setupAxis = (setup) => AXES[String(setup?.orientation || "").toUpperCase()] || AXES["+Z"];

/**
 * @param {typeof import("three")} THREE
 * @param {import("three").Object3D} root  Where the paths are drawn (`createCamPaths`), the tool beside them.
 * @param {object} job  `readCamJob`.
 * @param {{ mmPerUnit: number, direction(vector: number[]): import("three").Vector3 }} frame  `cadFrame`.
 */
export function createCamTool(THREE, root, job, frame) {
  const group = new THREE.Group();
  group.name = "cam-tool";
  group.visible = false;
  group.userData.camDrawn = true;
  group.raycast = () => {};
  root.add(group);
  const unit = 1 / (frame.mmPerUnit || 1);
  const materials = {
    cutter: new THREE.MeshStandardMaterial({ color: COLOURS.cutter, metalness: 0.6, roughness: 0.35 }),
    holder: new THREE.MeshStandardMaterial({ color: COLOURS.holder, metalness: 0.4, roughness: 0.5 }),
  };
  const built = new Map();
  const up = new THREE.Vector3(0, 1, 0);
  const setups = new Map(job.setups.map((setup) => [setup.id, setup]));

  // One tool, its tip at the origin and its shank up +Y: the cutter (a ball end's sphere at its tip), then the holder.
  const build = (op) => {
    const radius = (op?.toolDiameterMm > 0 ? op.toolDiameterMm / 2 : DEFAULT_RADIUS_MM);
    const ball = op?.toolType === "ball";
    const key = `${radius}:${ball}`;
    if (built.has(key)) return built.get(key);
    const tool = new THREE.Group();
    const flute = Math.max(radius * 6, 6);
    const cutter = new THREE.CylinderGeometry(radius, radius, flute - (ball ? radius : 0), 24);
    cutter.translate(0, (ball ? radius : 0) + (flute - (ball ? radius : 0)) / 2, 0);
    tool.add(new THREE.Mesh(cutter, materials.cutter));
    if (ball) tool.add(new THREE.Mesh(new THREE.SphereGeometry(radius, 24, 12).translate(0, radius, 0), materials.cutter));
    const holderRadius = Math.max(radius * 2, radius + 4);
    const holderHeight = Math.max(holderRadius * 2.5, 16);
    tool.add(new THREE.Mesh(new THREE.CylinderGeometry(holderRadius, holderRadius, holderHeight, 32).translate(0, flute + holderHeight / 2, 0), materials.holder));
    tool.scale.setScalar(unit);
    tool.traverse((object) => { object.raycast = () => {}; object.userData.camDrawn = true; });
    built.set(key, tool);
    return tool;
  };

  let shown = null;
  return {
    object3D: group,
    /** Stands the tool of the operation at `place.op` with its tip on `place.point` (the root's frame), or hides it. */
    show(place) {
      if (!place) { group.visible = false; return; }
      const op = job.operations.find((entry) => entry.index === place.op) || null;
      const tool = build(op);
      if (shown !== tool) {
        if (shown) group.remove(shown);
        group.add(tool);
        shown = tool;
      }
      const axis = frame.direction(setupAxis(setups.get(place.setup || op?.setup)));
      group.quaternion.setFromUnitVectors(up, axis);
      group.position.fromArray(place.point);
      group.visible = true;
    },
    hide() { group.visible = false; },
    dispose() {
      group.removeFromParent();
      for (const tool of built.values()) tool.traverse((object) => object.geometry?.dispose());
      built.clear();
      materials.cutter.dispose();
      materials.holder.dispose();
    },
  };
}
