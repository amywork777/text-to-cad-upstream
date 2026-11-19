// The scene's API for a renderer's own way of showing a pick (Studio's CAD workspace, `xbf/edit/` in @cad/ui): the colour a
// pick is drawn in (`setHighlightColor`) and a part's face count (`faceCount`), on the fixture `xbf.test.js` reads.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as THREE from "three";

import { loadXbfDocument } from "./xbfDocument.js";
import { createXbfScene } from "./xbfScene.js";

const FIXTURE = path.join(path.dirname(fileURLToPath(import.meta.url)), "__fixtures__", "bracket");
const STRUCTURE = JSON.parse(fs.readFileSync(path.join(FIXTURE, "structure.json"), "utf8"));
const ENGINE_LOOK = JSON.parse(fs.readFileSync(path.join(path.dirname(FIXTURE), "look.json"), "utf8"));
const ENGINE_ENVIRONMENT = new Uint8Array([...new TextEncoder().encode("#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n"),
  255, 255, 255, 128]).buffer;
const URL_BASE = "http://127.0.0.1:9/api/v1/documents/xbf/abc123";
const [PLATE, PEG] = STRUCTURE.prototypes;

/** An engine that answers the fixture through its API (`xbf.test.js`'s): its structure, every part and its look. */
function engine() {
  const base = "http://127.0.0.1:9";
  const fetch = async (url) => {
    if (url === `${base}/api/v1/look`) return new Response(JSON.stringify(ENGINE_LOOK));
    if (url === `${base}/api/v1/look/environment`) return new Response(ENGINE_ENVIRONMENT);
    if (url.startsWith(`${base}/api/v1/documents/abc123/version`)) return new Response(JSON.stringify({ version: STRUCTURE.version }));
    if (!url.startsWith(`${URL_BASE}/`)) return new Response(JSON.stringify({ error: "not found" }), { status: 404 });
    const rest = url.slice(URL_BASE.length).replace(/\?tessellation=[^&]*$/, "");
    if (rest === "/structure") return new Response(JSON.stringify(STRUCTURE));
    const part = /^\/parts\/([^/]+)$/.exec(rest);
    if (part) {
      const file = fs.readFileSync(path.join(FIXTURE, `${part[1]}.xbm`));
      return new Response(file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength));
    }
    return new Response(JSON.stringify({ error: "not found" }), { status: 404 });
  };
  return { fetch };
}

test("a renderer's own pick colour: a part's tint and edges, a face's fill and outline and an edge drawn in it, null the viewer's again", async () => {
  // As CAD mode's workspace draws a pick in its orange, and Simple view's ai layout keeps the viewer's own colour.
  const document = await loadXbfDocument(URL_BASE, { fetch: engine().fetch });
  const scene = createXbfScene(THREE, document);
  const [plate, peg] = scene.object3D.children.map(carrier => carrier.children[0]);
  const colours = () => ({
    part: [...plate.children.filter(child => child.type === "LineSegments"), ...plate.children[0].children].map(each => each.material.color.getHexString()),
    elements: ["selected face", "selected edge"].flatMap(name => peg.getObjectByName(name).children.map(child => child.material.color.getHexString())),
  });
  scene.setHighlight({ hovered: [], selected: ["i0"] });
  scene.setElementHighlight({ hovered: null, selected: ["i1/face/1", "i1/edge/1"] });
  const own = colours();
  assert.ok([...own.part, ...own.elements].every(colour => colour !== "ff9a2e"));
  scene.setHighlightColor("#ff9a2e");
  const workspace = colours();
  assert.deepEqual([workspace.part.length, workspace.elements.length], [own.part.length, 3]);
  assert.ok([...workspace.part, ...workspace.elements].every(colour => colour === "ff9a2e"), JSON.stringify(workspace));
  // What the pointer rests on wears it too.
  scene.setHighlight({ hovered: ["i0"], selected: [] });
  assert.ok(plate.children.filter(child => child.type === "LineSegments").every(line => line.material.color.getHexString() === "ff9a2e"));
  scene.setHighlightColor(null);
  scene.setHighlight({ hovered: [], selected: ["i0"] });
  assert.deepEqual(colours(), own);
  scene.dispose();
  document.release();
});

test("a part's faces are counted as its buffer has them, a face left unmeshed among them", async () => {
  const document = await loadXbfDocument(URL_BASE, { fetch: engine().fetch });
  const scene = createXbfScene(THREE, document);
  assert.equal(scene.faceCount(0), document.parts.get(PLATE.key).mesh.faces.length / 3);
  assert.equal(scene.faceCount(1), document.parts.get(PEG.key).mesh.faces.length / 3);
  assert.ok(scene.faceCount(0) > 0);
  assert.equal(scene.faceCount(99), 0);
  scene.dispose();
  document.release();
});
