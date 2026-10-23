---
name: engineering-drawing
description: Make an engineering drawing of a part as a PDF - orthographic, section and detail views with hidden lines and centre lines, real dimensions, hole, slot and bolt-circle callouts read off the model, notes and an ISO title block on a zoned sheet, all projected from the part's geometry so the drawing follows the model. Use when the user asks for a drawing, a dimensioned sheet, shop or manufacturing drawings, a print, or "2D views of this part".
license: MIT
---

# Engineering drawing

Provenance: maintained in [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad).
Use the installed local skill files as the runtime source of truth.

An engineering drawing is a DOCUMENT derived from a part. `cadgen.eng_drawing`
projects views from the part's geometry, measures dimensions between points ON
it, reads hole sizes, depths and counts off its faces, draws centre lines on its
turned features, and lays the result out on an ISO sheet: a zoned border, a
title block with the projection symbol, numbered notes. Change the model, rerun
the drawing script, and every view and value moves with it.

**The output is one PDF**, a page per sheet. No DXF is written and there is no
CLI: the script is the interface. `$dxf` makes cut layouts and flat patterns,
which are toolpaths, not documents.

## Setup

Run cadgen through [uv](https://docs.astral.sh/uv/), so this skill's commands share
one installation, and its warm build daemon, with the CAD app's server:

- `cadgen` below means `uvx --no-config --managed-python --python 3.13 --from cadgen==0.7.26 cadgen`
- `python` below means `uvx --no-config --managed-python --python 3.13 --from cadgen==0.7.26 python`

The first run downloads that installation; later runs reuse it.

## Workflow

1. **Get the part.** `cadgen.read_step(Path(__file__).parent / "../STEP/part.step")`
   reads the artifact a `@step` model wrote (run `python <model>.py` first); a
   live build123d shape works too. The drawing documents geometry; it does not
   build it.
2. **Write `<name>_drawing.py`** beside the model, from
   [the template](references/sheet-api.md#template). Import the facts your
   dimensions reference (hole pitch, wall, step lengths) from the model module
   rather than retyping them, so moving a feature moves its dimension. If the
   model keeps them inside a function, read them from its source and say so in
   the handoff; `holes()` and `overall()` need none.
3. **Choose the views.** `sheet.three_views(part, iso=True)` returns top, front,
   right and an isometric, in the projection the sheet names. The sheet lays
   them out again when it renders, spacing each pair for the dimensions they
   end up carrying, so add annotation freely. Where hidden lines would be the
   only way to show something (walls, floors, a bore's depth, a keyway), cut
   that view: `front.section("A", through=(x, y, z))` draws SECTION A-A,
   hatched, with its cutting plane on the view that sees it edge-on. Where a
   feature is too small to dimension at the sheet's scale (a chamfer, a groove,
   a thin wall), `sheet.detail(front, (x, y, z), radius)` draws DETAIL B larger,
   in free paper near its parent, which gets the circle and the letter.
4. **Dimension what a maker needs**, in MODEL coordinates:
   - `view.overall()` for overall size; `overall(height=False)` where another
     dimension already states it (a turned part's height is its diameter).
   - `view.dim(p1, p2)` for feature sizes and positions. Leave `offset` unset:
     the dimension goes on the side of the view its points are on and the
     shortest sits nearest the view. Put the points at the END of the edges
     they measure, on the side the dimension will go: a point in the middle of
     an edge runs its extension line along that edge. Two points that differ
     in one direction measure that direction; pass `orientation=` otherwise.
     Diameters of turned features go on the profile with `text="%%c<>"`.
   - `view.holes()` calls out every hole and slot the view looks down;
     `view.hole(point)` and `view.slot(point)` call out one. Diameter, THRU or
     depth, counterbore, countersink, a slot's width and length, the `4×` count
     and a bolt circle's `EQ SP ON ⌀60` are **read off the part**: do not type
     them. Anything you do
     type is checked, and a value the part contradicts stops the script.
     Only `thread=` (which the geometry cannot carry) and `label=` are yours.
     A chamfered bore end is part of its hole: it is called out as `⌵`, with
     `BOTH ENDS` or `FAR SIDE` when the other end is opened out too.
   - `view.diameter(center)` / `view.radius(center)` measure the circle or arc
     there; pass `size=` only to pick one of several concentric ones.
   - `tol=`, `fit=` and `general_tolerance=` only from the design requirements
     or the user. Never invent a tolerance, material, finish or process note:
     a field you leave blank prints as an empty, captioned cell, which says the
     drawing does not state it.
5. **Run `python <name>_drawing.py` and read what it prints** before the PDF:
   - *"incomplete: …"*: a hole or slot not called out, an overall size or a
     turned diameter not dimensioned. Each line names the call that states it.
   - *"measures blank paper"*: a dimension's points miss the view. Usually the
     part was built from a corner and the script assumed it was centred.
   - *"annotation overlaps"*, *"views crowded"*, *"leader crosses the view"*:
     not enough paper where the annotation is. The message names the view and
     side asking most, and a larger sheet or smaller scale; moving that
     annotation to a view with room to spare often does instead.
   - *"was guessed"*: a dimension's points differ in both directions about
     equally; say which with `orientation=`.
   - *"separate solids"*: the part is in pieces, usually a cut that runs right
     through the model. Fix the model before drawing it.
   - A refusal (an exception, no PDF): a typed size the part contradicts, a
     hole called out where no hole is, views that run off the frame. The
     message says what the part has, or which scale fits.

   Set `MPLCONFIGDIR` to a writable directory when running unattended.
6. **Read the PDF** (render a page to PNG if you cannot view PDFs). Check that
   every feature a maker needs is located and sized exactly once, that no text
   sits on line work, that hidden lines and centre lines appear where they
   should, and that the section shows what it was cut for. Fix the script, rerun,
   and read it again.

Steps 3 and 5 stand on their own: a sheet of views with no dimensions is a
drawing too, and writes its PDF with a list of everything it leaves unstated.

## What the sheet contains

- Line work with meaning, each at its own weight: visible outline (0.5),
  hidden (dashed), centre lines (chain), section hatching (ANSI31), dimensions,
  notes. Centre marks on every hole seen end-on, a centre line down every
  turned feature seen from the side, down every slot and across its ends, and a
  bolt circle's pitch circle.
- Dimensions measured from the geometry, true size at any scale; values wider
  than their extension lines set beside them. Hole callouts in the standard
  symbols (⌀ ↧ ⌴ ⌵), drawn as line work so they print the same everywhere.
- An ISO 5457 zoned border, an ISO 7200-style title block (TITLE, DWG NO., REV,
  SHEET, MATERIAL, FINISH, SCALE, SIZE, DRAWN, DATE, UNITS and the ISO 5456-2
  projection symbol), numbered notes with the general tolerance as note 1, and
  a revision table when `revisions=` is given.
- PDF bytes that are a function of the content: an unchanged drawing rebuilds
  to an identical file.

## Limits to state in the handoff

- Every dimension without `tol=`/`fit=` is nominal, governed by the general
  tolerance if one is given. Say which requirements came from the user.
- Full sections and circular details only: no half, offset or broken-out
  sections, no auxiliary views. Say what a view does not show.
- Holes, slots, overall sizes and turned diameters are checked for
  completeness; chamfers, fillets and pockets are not, and are stated with
  `dim`, `radius`, a detail or a `note`. A bolt circle's clocking (where its
  first hole sits) is a `dim` or an `angle` you add.
- Millimetres only; one part per arrangement.
