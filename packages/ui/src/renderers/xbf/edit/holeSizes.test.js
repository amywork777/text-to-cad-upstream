import assert from "node:assert/strict";
import test from "node:test";

import { calloutValues, defaultStandard, holeCallout, holeFill, holeFits, holeSizeOptions } from "./holeSizes.js";

test("a standard screw fills its hole: its clearance at a fit, its tap drill, its head's counterbore or countersink", () => {
  const m3 = { standard: "iso", size: "M3", fit: "normal" };
  assert.deepEqual(holeFill({ ...m3, type: "simple" }, "mm"), { diameter: "3.4" });
  assert.deepEqual(holeFill({ ...m3, type: "simple", fit: "close" }, "mm"), { diameter: "3.2" });
  assert.deepEqual(holeFill({ ...m3, type: "tapped" }, "mm"), { diameter: "2.5" });
  assert.deepEqual(holeFill({ ...m3, type: "counterbore" }, "mm"), { diameter: "3.4", cbore_diameter: "6.5", cbore_depth: "3.3" });
  assert.deepEqual(holeFill({ ...m3, type: "countersink" }, "mm"), { diameter: "3.4", csk_diameter: "6.72", csk_angle: "90" });
  // An inch screw, in an inch part and in a millimetre one; an ISO screw in an inch part.
  assert.deepEqual(holeFill({ standard: "ansi", size: "#4-40", fit: "close", type: "simple" }, "in"), { diameter: ".116" });
  assert.deepEqual(holeFill({ standard: "ansi", size: "1/4-20", type: "tapped" }, "mm"), { diameter: "5.11" });
  assert.deepEqual(holeFill({ standard: "iso", size: "M3", fit: "normal", type: "simple" }, "in"), { diameter: ".1339" });
  assert.deepEqual(holeFill({ standard: "ansi", size: "#10-32", fit: "normal", type: "countersink" }, "in"),
    { diameter: ".221", csk_diameter: ".385", csk_angle: "82" });
  // Loose is ISO's alone: in inches it reads as Normal. A size the standard has not is Custom, filling nothing.
  assert.equal(holeFill({ standard: "ansi", size: "#6-32", fit: "loose", type: "simple" }, "in").diameter, ".1695");
  assert.deepEqual(holeFill({ standard: "iso", size: "", type: "simple" }, "mm"), {});
  assert.equal(defaultStandard("in"), "ansi");
  assert.deepEqual(holeFits("ansi").map(fit => fit.label), ["Close", "Normal"]);
  // A flat head is not made under M3: a countersink offers M3 up.
  assert.equal(holeSizeOptions("iso", "countersink")[0].value, "M3");
  assert.equal(holeSizeOptions("iso", "simple")[0].value, "M1.6");
});

test("a sized hole's callout is written as a drawing labels it, and read back to its size", () => {
  const tapped = { standard: "iso", size: "M3", fit: "normal", type: "tapped" };
  assert.equal(holeCallout(tapped), "M3x0.5 tapped hole");
  assert.equal(holeCallout({ standard: "ansi", size: "#4-40", fit: "close", type: "counterbore" }), "#4-40 socket head counterbore, close fit");
  assert.equal(holeCallout({ standard: "iso", size: "", type: "simple" }), "");
  assert.deepEqual(calloutValues("M3x0.5 tapped hole"), { standard: "iso", size: "M3", type: "tapped" });
  assert.deepEqual(calloutValues("1/4-20 clearance hole, normal fit"), { standard: "ansi", size: "1/4-20", type: "simple", fit: "normal" });
  assert.deepEqual(calloutValues("M7 clearance hole, normal fit"), {});
  assert.deepEqual(calloutValues("drilled by hand"), {});
});
