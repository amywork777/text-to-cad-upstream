# drawings models

Small 2D DXF fixtures for exercising the `dxf` skill tooling, organized as one
`$cad-project`: authored sources here in `src/`, raw outputs in `DXF/`, and
committed source files that no code regenerates in `DXF/imported/`. Everything
is intentionally simple so failures point at the tooling, not the fixture.

| Script                     | Artifact                        | Description                                                              |
|----------------------------|---------------------------------|--------------------------------------------------------------------------|
| `angled_tab.py`            | `DXF/angled_tab.dxf`            | Plate with a corner gusset tab on a **45° bend line**                     |
| `clamp_plate.py`           | `DXF/clamp_plate.dxf`           | Cut profile projected from 3D topology (`lib/clamp_plate_profile.py`)     |
| `gasket_plate.py`          | `DXF/gasket_plate.dxf`          | Rounded gasket, bolt holes, centre cutout, engraved crosshair             |
| `l_bracket_flat.py`        | `DXF/l_bracket_flat.dxf`        | Sheet-metal flat pattern with a single bend line                          |
| `label_plate.py`           | `DXF/label_plate.dxf`           | Laser-cut label: engraved text outlines + an open score line              |
| `multi_bend_test_panel.py` | `DXF/multi_bend_test_panel.dxf` | **Four bends in three orientations** on one blank                         |
| `u_channel_bracket.py`     | `DXF/u_channel_bracket.dxf`     | U-channel flat pattern with **two parallel** bend lines                   |

Build: `python src/<script>` per row; unchanged models are no-ops, `--force`
rebuilds anyway. Together these cover the skill's standalone-drafting and
topology-projection workflows. Written DXF bytes are a pure function of the
returned geometry, so a rebuild that changes them is a real change to report,
not noise.

Shared code lives in `src/lib/` and is never a model:

- `lib/clamp_plate_profile.py` — the clamp plate as a build123d solid. It is a
  plain helper, not a `@step` model: this project emits drawings only, so the
  profile is projected from live geometry rather than read back from a STEP
  artifact this project wrote (which the `$dxf` skill forbids — the freshness
  gate could never say "current").

## Why each bend fixture exists

- `l_bracket_flat.py` — the ordinary case: one bend, edge to edge.
- `u_channel_bracket.py` — **two parallel** bends, so the web stays flat and
  both flanges fold the same way. Covers bend ordering and a segment bounded by
  a bend on both sides, which the single-bend L-bracket cannot exercise.
- `angled_tab.py` — arbitrary bend-line ORIENTATION. Every other bend fixture's
  lines are vertical, so a fold that only handles constant-X axes renders this
  one wrong.
- `multi_bend_test_panel.py` — the fold model itself: five faces, four hinges, a
  tree. Two parallel verticals, a horizontal tab fold whose line is a *chord*
  (it spans only the tab, and the same infinite line continues along the
  panel's bottom edge where no bend runs), and a 45° corner fold. This is the
  one that fails when a fold cuts by its infinite line instead of its own
  segment.

## `DXF/imported/` — committed inputs

Raw DXF files no script regenerates, committed via Git LFS and never rebuilt.
They cover R12 (AC1009) and R2013+ (AC1027) flavors and a spread of entity
types.

**Every file here encloses at least one closed area**, except the dimensioned
drawings noted below. That is the selection rule, and it exists because the
viewer renders a DXF by extruding its closed cut contours into a 3D flat
pattern — a drawing with no area has nothing to extrude and nothing to show.

Several of these deliberately mix closed cut profiles with open annotation
(dimension extension lines, stray arcs), because real drawings do — layer
intent is what separates the two, not the entity type.

From [skymakerolof/dxf](https://github.com/skymakerolof/dxf) (`test/resources`,
MIT):

- `alu_extrusion_profile.dxf` — an aluminium extrusion cross-section: nine
  nested closed LWPOLYLINE chambers, two HATCH regions, and seven DIMENSION
  annotations across several layers and colors. The most realistic engineering
  part in the set. Upstream name: `alu-profile.dxf`.
- `plate_four_holes.dxf` — an OpenSCAD 2D export: a plate outline with four
  circular holes, written as 452 individual LINE segments that chain into
  closed loops with no dangling ends. Exercises the contour walk hard, since
  not one entity is closed on its own. Upstream name: `openscad_export.dxf`.
- `square_and_circle.dxf` — a square outline with an inscribed circle on
  separate colored layers; the circle is tangent to the square, a useful
  near-degenerate case for contour resolution. Upstream name:
  `squareandcircle.dxf`.
- `block_square_in_circle.dxf` — a circle plus an INSERT whose block holds a
  closed square, and a second standalone circle. Small, and the simplest file
  here that requires block expansion. Upstream name: `accumulatortest.dxf`.
- `circles_ellipses_arcs.dxf` — two closed ELLIPSE entities and a CIRCLE
  alongside two open ARCs. Closed-area ellipse coverage with open geometry
  mixed in. Upstream name: `circlesellipsesarcs.dxf`.

From [gdsestimating/dxf-parser](https://github.com/gdsestimating/dxf-parser)
(`test/data`, MIT):

- `laser_text_outlines.dxf` — the word "LaserWeb" as twelve legacy POLYLINE
  letter outlines, including the counters inside `a`, `e` and `b`. Closed by
  coincident first/last vertices rather than the closed flag, so it also covers
  that distinction. A genuine laser-cut profile. Upstream name: `polylines.dxf`.
- `overlapping_ellipses.dxf` — two full closed ELLIPSE entities that overlap.
  Minimal ellipse coverage. Upstream name: `ellipse.dxf`.

From [mozman/ezdxf](https://github.com/mozman/ezdxf) (`examples_dxf`, MIT):

- `nested_hole_shapes.dxf` — eight shapes with nested holes: rectangles inside
  rectangles, notched profiles, and pentagons, as sixteen closed LWPOLYLINE
  boundaries with ten HATCH fills. The best coverage of holes and nesting
  depth. Upstream name: `hatches_1.dxf`.

Authored in-repo (committed because no script here can rebuild them):

- `bracket_inches.dxf` — a small bracket profile authored with `$INSUNITS = 1`
  (inches). The units fixture: the parser scales every coordinate to
  millimetres, and a drawing baked before that support existed came out 25.4×
  too small. Its LWPOLYLINEs omit the `AcDbPolyline` subclass marker, so
  ezdxf's strict reader refuses it while cadgen's own parser accepts it — which
  is itself the point of keeping it.
- `cabinet_panel_drawing.dxf` — a workshop DRAWING rather than a cut layout
  (issue #246): plan view, front elevation, a section, eleven DIMENSION
  entities, ISO 128 `CENTER`/`HIDDEN` linetypes, a non-plotting CONSTRUCTION
  layer, and a TEXT title block. It is committed rather than generated because
  **`@dxf` cannot express any of that**: the contract is build123d geometry in,
  entities out, with no dimensions, linetypes, plot flags or TEXT entities. So
  a validator must not demand closed cut profiles here (`drawing_checks`
  classifies it as a dimensioned drawing and skips closure), and the Viewer
  must render it as lines rather than extruding a prism out of contours that
  enclose nothing. This is also the folder's only remaining DXF `TEXT` entity
  fixture. Its retired ezdxf generator is in git history at
  `models/drawings/dxf/cabinet_panel_drawing.dxf.py`.

Validate any file here post-hoc with the drawing checks (there is no
`--validate` flag; a clean drawing reports no findings):

```python
from cadgen.drawing_checks import validate_dxf_file

print([finding.render() for finding in validate_dxf_file("DXF/gasket_plate.dxf")])
```
