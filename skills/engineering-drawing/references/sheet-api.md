# `cadgen.eng_drawing` reference

```python
from cadgen.eng_drawing import eng_drawing, Sheet
```

## Template

```python
from pathlib import Path

import cadgen
from cadgen.eng_drawing import Sheet, eng_drawing
# The facts the dimensions reference come from the model, not from this file.
from enclosure import FLOOR, HOLES, L, H, W


@eng_drawing(out="../PDF/enclosure_drawing.pdf")
def enclosure_drawing():
    part = cadgen.read_step(Path(__file__).parent / "../STEP/enclosure.step")
    sheet = Sheet("A3", title="ENCLOSURE", part_number="ENC-001", material="ABS",
                  revision="A", general_tolerance="ISO 2768-m",
                  notes=["BREAK SHARP EDGES."])
    top, front, right, iso = sheet.three_views(part, iso=True)
    front.section("A", through=(0, HOLES[0][1], 0))   # walls, floor and bores in section
    top.overall()
    top.dim((HOLES[0][0], HOLES[0][1], H), (HOLES[1][0], HOLES[0][1], H))   # hole pitch
    top.holes()                                       # every hole, sizes read off the part
    front.overall(width=False)                        # the width is the top view's
    front.dim((L / 2, HOLES[0][1], 0), (L / 2, HOLES[0][1], FLOOR))
    return sheet          # or [sheet_one, sheet_two] for a multi-sheet drawing


if __name__ == "__main__":
    enclosure_drawing()
```

A turned part states its diameters on the profile and cuts the view that shows
what hidden lines cannot, here a keyway's depth:

```python
from shaft import KEY_DEPTH, KEY_END, KEY_START, KEY_WIDTH, LENGTH, STEP_DIAMETER, STEP_LENGTH


@eng_drawing(out="../PDF/shaft_drawing.pdf")
def shaft_drawing():
    part = cadgen.read_step(Path(__file__).parent / "../STEP/shaft.step")   # axis along X
    sheet = Sheet("A3", title="SHAFT", part_number="SH-001", general_tolerance="ISO 2768-m")
    top, front, right, iso = sheet.three_views(part, iso=True)
    middle, r = (KEY_START + KEY_END) / 2, STEP_DIAMETER / 2
    right.section("A", through=(middle, 0, 0))            # the end view, cut through the keyway
    front.overall(height=False)                           # the height is the diameter
    front.dim((STEP_LENGTH / 2, 0, -r), (STEP_LENGTH / 2, 0, r), text="%%c<>")
    front.dim((0, 0, -r), (STEP_LENGTH, 0, -r))
    top.dim((KEY_START, KEY_WIDTH / 2, r), (KEY_END, KEY_WIDTH / 2, r))
    right.dim((middle, 0, -r), (middle, 0, r - KEY_DEPTH))   # what is left under the keyway
    return sheet
```

## `@eng_drawing(out="<path>.pdf")`

Declares the drawing. The function returns a `Sheet` or a list of them. Calling
it renders one PDF at `out`, a page per sheet, prints what it noticed and what
the drawing leaves unstated, and returns `[path]`.

`out` is required and must name a `.pdf`; a relative path resolves against the
script. Both are checked when the module is imported. There is no CLI verb: a
`Sheet` is composed in Python and no argument list carries that.

## `Sheet(size="A3", scale=1.0, title=..., part_number="", material="", finish="", revision="A", author="", date="", units="mm", projection="THIRD ANGLE", notes=(), ink="mono", text_height=3.5, general_tolerance="", revisions=())`

- `size`: `A4`, `A3`, `A2`, `A1`, `A0`, landscape, with an ISO 5457 zone grid.
- `scale`: 1 = 1:1, 0.5 = 1:2, 2 = 2:1. Values stay true size at any scale.
- `title`, `part_number` (DWG NO.), `material`, `finish`, `revision`, `author`
  (DRAWN), `date`: title block cells. A field left empty prints as an empty,
  captioned cell. Nothing is stamped from the clock. The drawing function's
  name prints small under the title, so a print leads back to its script.
- `units`: `"mm"`, the unit every value is measured in; anything else is refused.
- `projection`: `"THIRD ANGLE"` or `"FIRST ANGLE"`. It sets the arrangement
  `three_views` makes and the projection symbol the title block draws.
- `general_tolerance="ISO 2768-m"`: note 1, "TOLERANCES PER ISO 2768-m UNLESS
  OTHERWISE SPECIFIED." `notes=` takes a LIST; a bare string is refused.
- `revisions=[("A", "2026-09-01", "INITIAL RELEASE"), ...]`: a revision table.
- `ink`: `"mono"` (default) or `"color"` (per-layer colours, for review).

### `sheet.three_views(shape, gap=None, iso=False)`

Returns `(top, front, right)`, or four views with `iso=True`. When the sheet
renders, the views are laid out again with each gap sized to the dimensions and
callouts the facing views carry; `gap=` fixes it instead. The isometric takes
the larger free region at the sheet's scale or the largest standard scale that
fits; its label states its scale when that differs from the sheet's. A label or
scale you set on it yourself is kept.

### `sheet.view(shape, name, at=(x, y), label=None, hidden=True, centre_marks=True, scale=None)`

One view, centred on `at` (sheet mm from the bottom-left corner), for a custom
layout. `name` is `top`, `bottom`, `front`, `back`, `left`, `right` or `iso`.

A view whose geometry runs off the frame is refused, naming a scale that fits.

## `View`

Points are MODEL coordinates (3-tuples; a 2-tuple means z = 0); offsets are
sheet millimetres.

- `view.overall(width=True, height=True)`: overall width above and height left
  of the view, each on the outermost row of its side.
- `view.dim(p1, p2, offset=None, text=None, orientation=None, tol=None, fit=None)`:
  a linear dimension, measured. Unplaced, it goes on the side of the view its
  points are on, the shortest nearest the view. `offset` places the line that
  far from the farther point (its sign picks the side). `orientation` unset
  measures the direction the points differ more in, and the script says when
  that was close to a guess. A point on a hole's centre runs its extension line
  as a centre line. `text` overrides the
  value; `"<>"` inserts the measurement, `"%%c<>"` prefixes ⌀ (a diameter on a
  profile). `tol=0.1` prints ±0.1, `tol=(0.05, 0.02)` +0.05/-0.02, `fit="H7"`
  appends a fit class. `orientation` is `"h"`, `"v"` or None.
- `view.holes(angle=45)`: one callout per kind of hole the view looks down
  (`4× ⌀5.5 THRU`, `⌀28 THRU`), placed on the hole nearest the view's edge. A
  blind or counterbored hole that opens on the far side belongs to the
  opposite view.
- `view.hole(point, diameter=None, depth=None, thru=None, cbore=None, csk=None, thread=None, count=None, angle=45, tol=None, fit=None, label=None)`:
  one callout on the hole whose axis passes through `point`, in a view looking
  down that axis. Every size and the count come from the part; a value given is
  checked and a contradiction is refused, naming what the part has. `thread`
  (`"M6x1 - 6H"`) replaces the diameter; `label` is appended (`"EQ SP ON %%c60"`).
  A through hole opened out at both ends reads `BOTH ENDS` or `FAR SIDE ...`.
  Pieces of one bore separated by air (a clevis's arms, a cross hole) are one
  hole; a groove or a pocket with material inside is not a hole.
- `view.diameter(center, size=None, angle=45, text=None)` and
  `view.radius(center, size=None, ...)`: the circle or arc centred there,
  measured; `size` (a diameter, or a radius) picks one of several.
- `view.section(letter="A", through=None)`: draw the view as a full section
  through `through` (default: the part's middle), square to the line of sight.
  Cut faces are hatched, hidden lines are left out, the view is labelled
  `SECTION A-A`, and the cutting plane is drawn on a view of the same part
  that sees it edge-on. Letters I, O and Q are refused.
- `view.angle(vertex, p1, p2, offset=14)`: the angle at `vertex` between the
  legs toward `p1` and `p2`.
- `view.note(text, at, offset=(10, 10))`: a leader from a model point to text.

## What the script prints

| Line | Means |
| --- | --- |
| `incomplete: 4× ⌀5.5 THRU is not called out. top.hole(...) states it ...` | the part has holes the sheet does not call out |
| `incomplete: the overall size along Z (8) is not dimensioned. front.overall() ...` | an overall extent is not stated in any view |
| `incomplete: the turned diameter ⌀30 is not dimensioned ...` | a shaft step or boss has no diameter |
| `front dim 2: ... measures blank paper` | a dimension's points miss the view |
| `annotation overlaps: '120' is printed over 'TOP' ...` | two pieces of text collide |
| `views crowded: ... Sheet("A2") or Sheet(scale=0.5) gives them room` | the views' annotation needs more paper |
| `SECTION A-A has no view on this sheet that sees its cutting plane ...` | add the view that shows the plane |
| `front dim 0: ... which one it measures was guessed ...` | pass `orientation=` |
| `the part in the top view is 2 separate solids ...` | the model is in pieces |

## Layers

| Layer | Linetype | Weight | Holds |
| --- | --- | --- | --- |
| SHEET | continuous | 0.35 | frame, zone marks |
| TITLE | continuous | 0.25 | title block, projection symbol |
| VISIBLE | continuous | 0.50 | visible edges |
| HIDDEN | DASHED | 0.25 | hidden edges |
| CENTER | CENTER | 0.18 | centre marks and centre lines, cutting planes |
| DIM | continuous | 0.18 | dimensions, callouts |
| NOTES | continuous | 0.25 | notes, view labels, leaders |
| HATCH | continuous | 0.18 | section hatching |

They exist inside the ezdxf document the page is rendered from; the PDF carries
their weights and dash patterns, not the layer names.
