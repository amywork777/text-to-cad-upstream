import { useEffect } from "react";
import { requestSceneFrame } from "../../kit/viewport/sceneFrames.js";
import { DRAFT_CLASSES, DRAFT_ORDER } from "./editMode.js";

/**
 * Draft Analysis shaded on the model: the server's triangles (`check.positions`, each with its
 * class) as one mesh in the model's group, so it turns with the part and hides behind it as the
 * part's own faces do, drawn a little in front of them so it is never lost in them.
 *
 * @param {{ viewport: { runtimeRef: object, viewerReadyTick: number }, check: object | null }} props
 */
export default function DraftAnalysisLayer({ viewport, check }) {
  useEffect(() => {
    const runtime = viewport.runtimeRef?.current;
    if (!runtime?.THREE || !runtime.modelGroup || !check?.positions?.length) return undefined;
    const { THREE, modelGroup } = runtime;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(check.positions, 3));
    const colors = new Float32Array(check.positions.length);
    check.classes.forEach((kind, index) => {
      const rgb = DRAFT_CLASSES[DRAFT_ORDER[kind]].rgb;
      for (let corner = 0; corner < 3; corner += 1) colors.set(rgb, index * 9 + corner * 3);
    });
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const material = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.82, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = "draft-analysis";
    mesh.renderOrder = 3;
    modelGroup.add(mesh);
    requestSceneFrame(runtime, false);
    return () => {
      modelGroup.remove(mesh);
      geometry.dispose();
      material.dispose();
      requestSceneFrame(runtime, false);
    };
  }, [viewport.runtimeRef, viewport.viewerReadyTick, check]);
  return null;
}
