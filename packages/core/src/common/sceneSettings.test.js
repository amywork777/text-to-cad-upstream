import assert from "node:assert/strict";
import test from "node:test";

import {
  SCENE_QUALITY,
  resolveDisplayMaterialSettings,
  resolveRenderQuality,
  resolveSceneSurfaceLook,
  resolveViewSceneSettings
} from "./sceneSettings.js";
import { PHOTOGRAPHIC_STUDIO_MATERIAL_SETTINGS, PREVIEW_PART_FINISHES } from "./photographicStudioRig.js";
import { DARK_CANVAS_EXPOSURE } from "../lib/viewer/sceneRig.js";

test("normal CAD stays an orthographic responsive inspection scene", () => {
  const light = resolveViewSceneSettings({ appearance: "light" });
  const dark = resolveViewSceneSettings({ appearance: "dark" });

  assert.equal(light.render.enabled, false);
  assert.equal(light.render.configuration, null);
  assert.equal(light.camera.projection, "orthographic");
  assert.equal(light.display.mode, "shaded_edges");
  assert.equal(light.theme.materials.overrideSourceColors, false);
  assert.equal(light.materialOverrides, null);
  assert.equal(dark.materialOverrides, null);
  assert.equal(light.quality.id, SCENE_QUALITY.INTERACTIVE);
  assert.equal(light.theme.background.solidColor, "#f0f4f9");
  assert.equal(dark.theme.background.solidColor, "#36393f");
  assert.deepEqual(dark.theme.materials, light.theme.materials);
  // The same rig on both canvases, the dark one a step brighter (`DARK_CANVAS_EXPOSURE`).
  assert.deepEqual(
    { ...dark.theme.lighting, toneMappingExposure: light.theme.lighting.toneMappingExposure },
    light.theme.lighting
  );
  assert.equal(dark.theme.lighting.toneMappingExposure, light.theme.lighting.toneMappingExposure * DARK_CANVAS_EXPOSURE);
  assert.deepEqual(dark.theme.environment, light.theme.environment);
});

test("Render quality maps to the existing bounded scene-quality ladder", () => {
  assert.equal(resolveRenderQuality("preview").id, SCENE_QUALITY.STANDARD);
  assert.equal(resolveRenderQuality("final").id, SCENE_QUALITY.HIGH);
  assert.equal(resolveRenderQuality().id, SCENE_QUALITY.HIGH);
  assert.throws(() => resolveRenderQuality("high"), /Unknown render quality/);
});

test("the studio's finish is a constant of the rig, with no colour grading", () => {
  assert.equal(PHOTOGRAPHIC_STUDIO_MATERIAL_SETTINGS.overrideSourceColors, false);
  for (const channel of ["saturation", "contrast", "brightness"]) {
    assert.equal(Object.hasOwn(PHOTOGRAPHIC_STUDIO_MATERIAL_SETTINGS, channel), false);
  }
});

test("a Preview finish replaces every authored one over the parts' own colours; As modelled keeps the file's", () => {
  const lookOf = (previewSettings, preview = true) => {
    const scene = resolveViewSceneSettings({ preview, previewSettings });
    return resolveSceneSurfaceLook({ themeSettings: scene.theme, displaySettings: scene.display,
      renderMode: scene.render.enabled, renderConfiguration: scene.render.configuration });
  };
  const modelled = lookOf({});
  assert.equal(modelled.authored, true);
  assert.equal(Object.hasOwn(modelled, "finishes"), false);
  const machined = lookOf({ parts: { finish: "machined" } });
  assert.deepEqual([machined.authored, machined.finishes], [false, false]);
  for (const [channel, value] of Object.entries(PREVIEW_PART_FINISHES.machined)) assert.equal(machined.materialSettings[channel], value, channel);
  assert.equal(machined.materialSettings.overrideSourceColors, false, "each part keeps its colour");
  const rubberBlue = lookOf({ parts: { finish: "rubber", colorMode: "single", color: "#1f3a93" } });
  assert.deepEqual([rubberBlue.materialSettings.roughness, rubberBlue.materialSettings.defaultColor, rubberBlue.materialSettings.overrideSourceColors],
    [PREVIEW_PART_FINISHES.rubber.roughness, "#1f3a93", true]);
  assert.equal(lookOf({ parts: { finish: "machined" } }, false).authored, false, "outside Preview the theme's finish, never Preview's");
  assert.notEqual(lookOf({ parts: { finish: "machined" } }, false).materialSettings.metalness, 1);
});

test("part-color policy stays display-owned and preserves its editable palette", () => {
  const byPart = resolveViewSceneSettings({ display: { mode: "parts" } });
  assert.equal(byPart.theme.materials.overrideSourceColors, true);
  assert.equal(byPart.theme.materials.cycleColors, true);
  assert.deepEqual(byPart.theme.materials.fillColors, byPart.view.surfaces.colors);

  assert.deepEqual(resolveDisplayMaterialSettings(
    { defaultColor: "#ffffff", overrideSourceColors: false },
    { mode: "single", color: "#123456" }
  ), {
    defaultColor: "#123456",
    fillColors: ["#123456"],
    cycleColors: false,
    overrideSourceColors: true
  });
  assert.deepEqual(resolveDisplayMaterialSettings({}, { mode: "by_part", colors: ["#112233", "#abcdef"] }), {
    defaultColor: "#112233",
    fillColors: ["#112233", "#abcdef"],
    cycleColors: true,
    overrideSourceColors: true
  });
});
