import assert from "node:assert/strict";
import test from "node:test";

import { pageFit, scrollPage } from "./pageView.js";

// Three A4 sheets one under another (595 × 842 points each, 24 apart), y up from the first top.
const SHEETS = [0, -(842 * 3 + 48), 595, 0];

test("a tall stack of sheets opens at its width with its first page's top in view", () => {
  const view = pageFit(SHEETS, 800, 600, { top: 40, margin: 16 });
  assert.equal(view.scale, (800 - 32) / 595);
  assert.equal(view.offsetY, 40 + 16);
  assert.equal(view.offsetX, 16);
});

test("a picture that fits opens whole", () => {
  const view = pageFit([0, -480, 640, 0], 800, 600, { margin: 16 });
  assert.equal(view.scale, Math.min((800 - 32) / 640, (600 - 32) / 480));
});

test("a landscape sheet opens whole however short the pane", () => {
  const sheet = [0, -297, 420, 0];
  const view = pageFit(sheet, 800, 200, { top: 40, margin: 16 });
  assert.equal(view.scale, (200 - 40 - 32) / 297);
});

test("scrolling moves a tall page and stops at its ends; a page that fits across does not move across", () => {
  const start = pageFit(SHEETS, 800, 600, { top: 40, margin: 16 });
  // Scrolling up past the top stays at the top; across, a page that fits stays put.
  assert.deepEqual(scrollPage(start, 50, 30, SHEETS, 800, 600, { top: 40, margin: 16 }), start);
  const down = scrollPage(start, 0, -400, SHEETS, 800, 600, { top: 40, margin: 16 });
  assert.equal(down.offsetY, start.offsetY - 400);
  // Far down, the bottom of the last page stops at the bottom of the pane.
  const end = scrollPage(start, 0, -1e9, SHEETS, 800, 600, { top: 40, margin: 16 });
  assert.equal(-SHEETS[1] * start.scale + end.offsetY, 600 - 16);
});

test("scrolling down a page zoomed past its side does not jump it across", () => {
  const start = pageFit(SHEETS, 800, 600, { top: 40, margin: 16 });
  const zoomed = { ...start, scale: start.scale * 3, offsetX: 200 };
  assert.equal(scrollPage(zoomed, 0, -100, SHEETS, 800, 600, { top: 40, margin: 16 }).offsetX, 200);
});
