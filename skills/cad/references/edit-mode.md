# Edit mode

The CAD viewer edits a part by hand while its Python script stays the source. It runs the script,
shows a design tree with the part's named sizes (Equations) and its history (one feature
per operation the script performs, numbered as SolidWorks numbers them: Sketch1, Boss-Extrude1,
Fillet1), and draws the selected feature's dimensions on the model. The hand edit notes below use
the same names (Fillet2, Cut-Extrude2). When the engineer changes a value, the viewer rewrites that
one number in the script, keeping how it was written, and builds again every part that uses the
changed file.

Its toolbar's Features tab also has modeling commands, as SolidWorks names them: Extruded,
Revolved, Swept and Lofted Boss/Base (each switched to its Cut in its dialog), Hole Wizard and Rib;
Move Face, Fillet, Chamfer, Draft, Shell, Split, Delete Face and Delete/Keep Body; Pattern, Mirror
and Plane. Each acts on what the
engineer selects (edges or faces on the model, a sketch or a feature in the design tree) and
writes one line of build123d into the script, after the statement that makes the part's body, which
then reads back as a new feature of the history.

The engineer also sketches there, as in SolidWorks: Sketch on a plane or a flat face, draw lines,
rectangles, circles, arcs (Centerpoint, 3 Point, and Tangent Arc, written as a centerpoint arc and
`s.tangent(<curve>, arc)`), slots, polygons and points, add relations and Smart Dimensions, Exit Sketch, then
extrude or revolve it, as a boss or a cut. Each stroke is a line of `cadgen.sketch` code
([sketching.md](sketching.md)) in the part's script, written as it is drawn; see "Sketches drawn
by hand" below.

## Write the script so it edits well

- **Name the sizes that matter at the top of the file**, one per line, in the project's units:
  `LENGTH = 2.80`, `WALL = .060`. They become the Equations (with those the part's own
  script names at its top, used or not; Add expression writes one there). Use plain names, not abbreviations
  (`TRAY_HEIGHT`, not `TH`).
- **Put sizes several parts share in `sizes.py` beside the parts**, one per line with what it is
  for (`WALL = 2.0  # every outer wall`), and import them by name (`from sizes import WALL`). A
  part's imports resolve from its own folder, so the file sits in the same folder as the parts.
  Changing one there, in edit mode or in Studio's Sizes, builds again every part that imports it,
  so one number drives them all; a part's own sizes stay at the top of its script.
- **Build each feature from those names**, so a dimension on the model leads back to a size
  (`LENGTH - 2*WALL`), not to a number computed somewhere else.
- **One feature per line** in the function that designs the part (`outer = ...`,
  `cavity = ...`, `tray = outer - cavity`): each line is a feature of the history, with its
  variable's name beside it.
- **Keep the body in one name and return it** (`tray = ...`, then `return tray`), in build123d's
  algebra style. A command writes its line right after the last statement that makes the body,
  before `label` and `color` are set. A body returned outright (`return bd.Box(...)`) is first
  put in a name (`part = bd.Box(...)`); a part built in builder style (`with bd.BuildPart()`)
  takes no commands yet.
- **Give a part's PMI in its `return`** (`return annotate(part, ...)`, or a function of the part's
  own the return calls): a command's line then lands before it, so the annotations stand on the
  finished body and follow it ([PMI](pmi.md)), the general profile taking any face a command adds.
- **Profiles as `bd.Rectangle`, `bd.RectangleRounded`, `bd.Box` or `bd.Cylinder`, placed with `bd.Pos(...)`**, get
  dimensions drawn on the model. Other shapes still show their sizes in the history.
- A unit constant named in the file (`INCH = 25.4`; build123d's own is `bd.IN`, 25.4) is fine: lengths
  show in the project's units, and the commands write theirs by that name (`.03*INCH`).
- **Bring a STEP in as its own line**, `part = read_step(Path(__file__).parent / "bracket.step")`
  (`from cadgen import read_step`; `read_xbf` of an xbf converted from it once reads faster), and
  model on that name. It is one feature, the imported body (NX's Body, SolidWorks' Imported1),
  with no history under it, as other CAD tools hold one. Change its faces with direct editing
  (`from cadgen.direct import offset_faces, delete_faces`): `part = offset_faces(part, <faces>,
  distance=2)` moves faces along their normals (negative pushes in), `part = delete_faces(part,
  <faces>)` takes a hole, round or boss out and heals the solid. Edit mode writes and reopens both
  (Move Face, Delete Face) on any body.
- **Keep a project's scripts inside its folder**: the folder of its git repository, or the one its
  Studio project lists. Edit mode reads only those files, so an assembly placing parts from a
  folder outside it shows nothing, and says so.

## What the commands write

- **Faces and edges by where they are, never by number**: build123d's own selectors, the
  cheapest chain that picks exactly what was selected, run before it is written. Fillet on the
  top face's outer edges writes
  `tray = bd.fillet(tray.faces().sort_by(bd.Axis.Z)[-1].outer_wire().edges(), radius=.03*INCH)`.
  A face selected for a fillet or a chamfer stands for its edges.
- **Hole**: a cylinder cut into the selected flat face, from its centre or moved along the two
  axes in its plane (all three on a slanted face, the place kept on its plane), where the face is
  clicked: `tray -= bd.Pos(1.37*INCH, 0) * bd.Plane(<face>) * bd.Cylinder(.03/2*INCH,
  .1*INCH, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MAX))`; through all, its depth is
  `tray.bounding_box().diagonal`. A counterbore or a countersink is added to the cylinder, both
  from the face down: `(bd.Cylinder(d/2, depth, align=...) + bd.Cylinder(cbore/2, cbore_depth,
  align=...))`, or `+ bd.Cone(d/2, csk/2, height, align=...)` with its height worked out from
  the angle (`(csk - d)/2 / tan(angle/2)`). Its panel is Hole Wizard's: a standard (ISO, ANSI
  Inch), a screw size and a fit fill the sizes (ISO 273 clearances; inch close and free fits; tap
  drills; a socket head's counterbore, a flat head's countersink), and a hole of a standard size
  keeps its callout in a comment on its line, as a drawing labels it:
  `tray -= ... * bd.Cylinder(2.5/2, ...)  # M3x0.5 tapped hole`. A Straight Tap is drilled at its
  tap drill; its thread is the callout's.
  Each click on the face after the first adds a hole there, as Hole Wizard's Positions do: one
  feature drills the same hole at each place, `tray -= [bd.Pos(*at) * bd.Plane(<face>) *
  bd.Cylinder(...) for at in ((5, 0), (-5, 0), (0, 2.5))]`, each `at` its offsets from the
  face's centre. That centre is the face's centre of mass, `bd.Plane(<face>)`'s origin: on a rim
  it is over the opening, so a hole in a rim always has its offsets, and one left at the centre
  is refused.
- **Chamfer**: `bd.chamfer(<edges>, length=1)`; Distance distance writes `length=1, length2=.5`
  (Flip direction swaps them), Angle distance `length=1, angle=30`. build123d measures an angle
  chamfer's length along each edge's first face; flipped, the distance runs along the other, written
  `length=1 * bd.tan(bd.radians(30)), length2=1`, which reopens as Angle distance, flipped.
- **Shell**: `bd.offset(body, amount=-thickness, openings=<faces>)`; Shell outward is a positive amount.
- **Split** cuts the body into bodies by an origin or reference plane, or a flat face's plane:
  `part = bd.split(part, bisect_by=bd.Plane.YZ, keep=bd.Keep.BOTH)` (`bd.Keep.TOP`/`bd.Keep.BOTTOM`
  keeps one side). **Delete/Keep Body** then takes a body out by a face picked on it:
  `part -= part.solids().sort_by(bd.Axis.X)[-1]  # Delete Body`, or keeps it alone
  (`part = bd.Part() + part.solids().sort_by(bd.Axis.X)[0]  # Keep Body`); a body is named by its place
  along the axis the bodies are most spread along.
- **Plane** (Reference Geometry) is a line of its own, offset from an origin plane or a flat face
  of the body: `plane1 = bd.Plane.XY.offset(10)`, `plane2 = bd.Plane(<face>).offset(-.25*INCH)`
  (a face's plane faces out of the part; a minus flips it). Two parallel faces picked make a Mid
  Plane, kept midway: `plane3 = bd.Plane(<a>).offset(bd.Plane(<a>).z_dir.dot(<b>.center() - <a>.center()) / 2)`;
  an edge a plane normal to it at its start (or end):
  `plane4 = bd.Plane(origin=<edge>.position_at(0), z_dir=<edge>.tangent_at(0)).offset(0)`. The tree lists it as Plane1, and a
  sketch goes on it by its name: `sketch4 = Sketch("Sketch4", plane=plane1)`, as do a mirror
  (`about=plane1`), a draft's neutral plane (`bd.draft(<faces>, plane1, 2)`) and another plane
  (`plane2 = plane1.offset(5)`), each written after the plane's own line. A line that only
  offsets a plane reads as a Plane; one that offsets a plane to place something reads as what it
  places. At angle turns it about its own X or Y axis through its origin, by the right hand:
  `plane3 = bd.Plane.XZ.offset(0).rotated((30, 0, 0))`, `.rotated((0, 30, 0))` about its Y.
- **Draft** tilts the faces picked by an angle about where they meet the neutral plane, a flat
  face of the part or an origin plane, so the part narrows along the plane's normal, its direction
  of pull: `tray = bd.draft(<faces>, -bd.Plane(<face>), 1)` (a face's own normal points out of the
  part, so its plane is turned to pull into it), or `bd.Plane.XY` for the Top Plane (`XZ` Front,
  `YZ` Right). A minus before the plane turns the pull. It takes flat, round and conical faces.
- **Mirror and Pattern** copy the feature picked in the history, or the whole body. A feature's
  tool written inline is named where it is made, so the copy follows it:
  `plate -= (hole1 := bd.Pos(...) * bd.Cylinder(...))`, then
  `plate -= bd.mirror(hole1, about=bd.Plane.YZ)` or
  `plate -= [loc * hole1 for loc in bd.GridLocations(-.4*INCH, 0, 3, 1, align=(bd.Align.MIN, bd.Align.CENTER)).locations[1:]]`
  (a circular pattern uses `bd.PolarLocations(0, count)`, about the Z axis). Up Z, each copy is
  placed by its own `Pos`: `plate -= [bd.Pos(0, 0, .3*INCH * i) * hole1 for i in range(1, 3)]`.
  About a round face's axis or a straight edge picked on the model:
  `hub -= [hole1.rotate(<face>.axis_of_rotation, i * 360 / 6) for i in range(1, 6)]`
  (`bd.Axis(<edge>)` for an edge). An Angle short of 360 spreads them from the first to the last:
  `i * 90 / (4 - 1)`, or `bd.PolarLocations(0, 4, angular_range=90, endpoint=True)`; a negative angle
  is Reverse direction.
- **Extruded Boss/Base and Extruded Cut** make a solid of the sketch picked on the model or in the design tree:
  `part += bd.extrude(sketch2.face(), amount=5)`, or `part -= bd.extrude(...)` for a cut (a negative
  amount goes the other way along the sketch's normal; Mid Plane is `both=True` with half the
  depth; a cut Through All is `amount=-part.bounding_box().diagonal`; Up To Next is
  `until=bd.Until.NEXT, target=part` with no amount; Up To Surface and Up To Vertex are
  `amount=sketch2.depth_to(<face>)`, or `depth_to(<edge>.start_point())` for the end of an edge,
  so the extrude follows what it ends on; a draft is `taper=` in degrees, drawn in, or out when
  negative). A cut starts toward the part. The line goes after the sketch's own lines.
  Direction 2 goes the other way too, as a second extrude of the same profile added to the
  first: `part += bd.extrude(sketch2.face(), amount=6) + bd.extrude(sketch2.face(), amount=-4)`, Blind
  or (for a cut) Through All, with its own `taper=`; not with Mid Plane. With Up To Surface or Up To
  Vertex it goes the other side of the sketch's plane from what Direction 1 ends on. It reads back
  as one feature with Direction 2 on.
- **Revolved Boss/Base and Revolved Cut** turn the selected sketch about one of its lines (its
  centerline, usually): `part += bd.revolve(sketch2.face(), axis=sketch2.axis(line1),
  revolution_arc=360)`, or `part -= bd.revolve(...)` for a cut; Reverse direction is a negative
  angle. Mid Plane and Direction 2 turn the profile back first and revolve the whole angle:
  `bd.revolve(sketch2.face().rotate(sketch2.axis(line1), -45), axis=sketch2.axis(line1),
  revolution_arc=90)` is 90° Mid Plane; a turn back other than half is Direction 2's angle.
- **Thin Feature** (an extrude's option) makes the outline a wall rather than filling it:
  `part += bd.extrude(sketch2.thin(1.5), amount=20)`, `side="outside"` or `side="mid"` for the wall
  outside the outline or astride it.
- **Swept Boss/Base and Swept Cut** run a profile sketch along a path sketch:
  `part += bd.sweep(sketch1.face(), path=sketch2.path(), transition=bd.Transition.RIGHT)`, or `-=` for a
  cut. Its line goes after the later of the two sketches.
- **Lofted Boss/Base and Lofted Cut** join profile sketches, usually on offset planes, in order:
  `part += bd.loft([sketch1.face(), sketch3.face()])`.
- **Rib** grows a sketch's straight lines to the body, parallel to the sketch:
  `part += sketch4.rib(2, part)`, `flip=True` for the other side of the line.
- Sizes are written in the project's units, as the file writes them (`.03*INCH` in an inch part).
- A line that does not run, or does not make the feature on what was selected, is not written.
- **Delete** (the key, or a feature's menu in the design tree) takes a feature's lines out of the
  script; the sketch it was made from stays. A line that changes the body in place goes whole
  (`part += ...`, `tray = bd.fillet(tray...)`); a boolean that starts a name keeps the name as the
  body it was made from (`tray = outer - cavity` becomes `tray = outer`, and `cavity`'s line goes);
  a loop goes whole when every line in it is the feature's. A feature whose name later features
  still use asks first, as SolidWorks' Confirm Delete: it names those child features and, on
  Delete All, takes them out with it in one change. A line no feature makes that still uses it
  (the `return`, a sketch) refuses it. A sketch of its own goes with its lines.
- **Reorder**: a feature dragged to another place in the design tree moves its lines (with the
  sketch it was made from, when that sketch is its alone) to just above the feature it is dropped
  on. It does not go above a line that makes a name it reads, below one that reads a name it makes,
  or past a line that reads a body one of them changes in place (a hole and a fillet on the part
  swap; a fillet on the post does not go past the post's join).
- **Edit Feature** (a feature's menu, or a double-click on it) reopens the command that wrote the
  feature's line, with its values, and writes that same line again in its place. What the line
  acts on stays as written (its edges, faces, the feature it copies, its sketch) unless the
  engineer picks others: a fillet's, chamfer's, shell's, draft's or hole's panel rolls the part back to
  just before the feature, and edges or faces picked there are written as selectors on the body
  as it was at that line (`outer = bd.fillet(outer.faces().sort_by(bd.Axis.Z)[-1].edges(), radius=2)`).
  A value left as it was keeps how it was written (`radius=WALL` stays `radius=WALL`). A line
  written in the commands' form opens this way even when you wrote it.
- **An assembly places its parts; a part is modeled on its own.** In an assembly the design tree
  lists its parts (Daisy tray<1>), and Open Part (double-click, or the part's menu) opens the part's
  own model in the view, where its features, sketches and commands are. The toolbar's modeling
  commands are off in an assembly, as in SolidWorks.
- **Compare** (the Inspect tab's Analyze group, as SolidWorks' Compare Geometry) lists the versions of
  the part edit mode read this session, newest first (each a change the agent or a hand edit made,
  named by the files that changed after it); one picked draws the material the part has gained
  since it in amber and what it has lost in red, with their volumes. It writes nothing; edit mode
  keeps the last 12 versions while the viewer runs.
- **New Sheet** (the Drafting tab's Sheet group, in a part) writes `<name>_drawing.py` beside the
  part from the engineering drawing skill's template: it calls the part's model (`part().shape`, so
  the drawing follows the part), puts top, front and right views in third angle and an isometric on an A3 sheet, each with its overall size, and is run
  at once to write `<name>_drawing.pdf` beside it. Its **Drawing** panel then sets the sheet as
  `Sheet(...)` takes it (size, `scale=0.5` for 1:2, the title block's `title`, `part_number`,
  `material`, `revision`, `author`) and whether `three_views(part, iso=True)` draws the isometric,
  and draws the PDF again. **Edit Sheet** opens the sheet itself in the view, as a SolidWorks
  drawing is worked on: dragging a view writes `three_views(..., offset=(x, y))` (the top, front
  and right views move together, the isometric by its own `iso_offset=`) or a hand-placed view's
  `at=`, kept inside the sheet's frame, a hand-placed view lining up with the others' centres; a
  dimension picked and deleted takes its call off (`top.overall()`, or one call of a chain); Smart
  Dimension picks two points of a view (corners and circles' centres, or a straight edge's two
  ends) and a third pick places it, written `view.dim(p1, p2, offset=...)` in model coordinates, and
  a circle seen round gives `view.diameter(...)` (an arc `view.radius(...)`). Each change draws the
  PDF again, and the sheet has its own Undo and Redo. Notes, hole callouts and other views are the
  agent's, in the same script.
- **Insert Components** (the Assembly tab, beside Mate) lists the project's part scripts and adds
  the one picked: `from cap import cap` in the assembly's script (with a `sys.path.insert` for its
  folder when no part is imported from there yet) and `cap().shape` at the end of the `children`
  it returns, where the part is made, for mates to place. A part already in the assembly is not
  inserted again (the design tree lists each part's model once); ask for another instance in code.
- **Mate** (the Assemble tab's Mate) places an assembly's part by a face or an edge picked on
  the part that stays and one on the part that moves to it, as SolidWorks' Standard Mates do. It
  adds a constraint from `cadgen.mates` to the moved part's `mate` call, on what was picked (found
  again by selector each run): `mate(pin_part, Coincident(<pin face>, <base face>),
  Concentric(<pin face>, <base hole>))`, the parts named before the `return Compound(children=[...])`
  that lists them. `mate` solves a part's mates together each run and moves it the least it can, so
  what they leave free stays where the part was and it follows the parts it is mated to; a part's
  call comes after the calls of the parts it is mated to. Coincident puts two flat faces face to
  face (`flip=True` the same way), Distance a gap apart (`Distance(a, b, 5)`), Concentric two round
  faces on one axis and two circular edges centre on centre, as a pin seats in a hole; Parallel,
  Perpendicular and Angle (`Angle(a, b, 30)`) line faces or edges up. Mates that cannot all hold
  are refused, naming them. The design tree lists them under Mates (Coincident1 (base, pin)), and a
  mate's Delete takes it out of its call.
- **Rename** (a row's menu, or F2) names a feature as the engineer calls it: the name is the
  comment at the end of the feature's line (`part -= ...  # Cable notch`), which the design tree
  shows after the feature's number (Extrude (2) "Cable notch") and Edit Feature keeps; a sketch's is its own
  (`Sketch("Cable notch", ...)`). A hole of a standard size is named by its callout until renamed.
  No two features share a name, and nothing is built.
- **Appearance** (the Inspect tab's Display group, or the part's menu in the design tree) colors the part with
  the hex picked: written where its body takes its color, `tray.color = "#B7A1D7"` (an alpha kept
  as the hex's last byte, `"#B7A1D7CC"`), or just before it is returned; the part is built again,
  as its document carries the color.
- **Mass Properties** (the Inspect tab's Measure group, or the part's menu in the design tree) weighs the part as
  it is, at the rollback bar when it is up: its volume, surface area, center of mass (marked on
  the model) and overall size, worked out from its solids, and its mass in a material of cadgen's
  table, the project brief's own as it opens. It writes nothing.
- **Draft Analysis** (the Inspect tab's Analyze group) shades the part by its draft against a direction of pull (an
  origin plane's normal, reversed or not): green where a face leans with the pull by at least the
  draft angle, red where it leans away, yellow where a wall stands too near the pull for a mold to
  release it, with each color's area. Use it before adding Draft. It writes nothing.
- **The rollback bar** under the features in the design tree (dragged up, or a feature's Rollback) shows
  the part as it was above the bar, the features below it greyed. While it is up, commands act on
  the body there and write their line right above the feature below the bar (a new sketch goes
  there too), so a feature can be put in early in the history. Nothing below the bar changes. Make
  Current Feature on the last feature brings the part back.
- **The timeline** along the bottom of the workspace lists the same features as icons, in the same
  order, each with the sketch it was made from just before it (a sketch nothing uses yet is an icon
  of its own). A click selects one and a double-click edits it (Edit Feature, or Edit Sketch on
  a sketch). The rollback bar's marker stands after the last feature the part still has: dragged
  back, it rolls the part back to there, as Rollback does, a feature and its sketch
  going together. It is put away while the drawing's sheet is up.
- **Command search** (S, anywhere in the workspace but a text field) is a box under the toolbar that
  runs any button of the toolbar by name, on whichever tab: type "fillet" and Fillet is the
  first result, "pocket" or "cut" Extruded Cut, "mate" Mate. The SolidWorks name for a command is
  found first, then the words other tools have for it (NX's and Fusion's: "edge blend", "press pull"); Enter runs the first result (the arrow keys move the choice), Escape
  puts the box away. It runs a result as its button does, and lists what the toolbar has and no
  more: a button the toolbar shows dimmed is dimmed in it, with the toolbar's reason, and while a
  sketch is open it is the sketch's tools and the features made of it. In AI mode (Studio's AI | CAD
  switch on AI), S is left alone.
- **Suppress** takes a feature out of the part but keeps its lines, as comments under a line that
  says what they are; Unsuppress puts them back exactly. A boolean that starts a name keeps the
  name meanwhile, on a line of its own:

  ```python
      # Suppressed (Cut-Extrude, 2 lines):
      # cavity = bd.Pos(0, 0, 2) * bd.Box(36, 16, 10)
      # tray = outer - cavity
      tray = outer  # Cut-Extrude suppressed
  ```

  The design tree shows the feature greyed where its lines are, with its sketch under it. Leave
  such a block as it is. If you must change a suppressed line, keep it commented and keep the count
  on the first line right, or Unsuppress cannot put it back. Its child features are suppressed
  with it (one made between its lines ends inside its block); Unsuppress puts back only it, its
  children staying suppressed, as SolidWorks leaves them.

## Sketches drawn by hand

- A new sketch is a line before the part is returned: `sketch2 = Sketch("Sketch2", plane="Top")`
  (on a face of the body: `plane=part.faces().sort_by(bd.Axis.Z)[-1]`; in an inch part, `unit=INCH`).
- Each stroke, relation and dimension is one more line at the end of the sketch's own lines,
  the entities named as the sketch names them where the name is free (`line1, line2, line3, line4
  = sketch2.rectangle(sketch2.origin, (30, 20))`, `sketch2.length(line1, 30)`). A point drawn on
  another sketch's point shares it (`line5 = sketch2.line(line4.end, ...)`); one drawn on a curve
  is held to it (`sketch2.coincident(...)`); a line drawn level or plumb gets `horizontal` or
  `vertical`.
- After each change the drawn coordinates are written where the sketch solved them, so the lines
  read as the sketch stands: a dimension of 30 turns `(14.32, 8.8)` into `(30, 8.8)`. The first size
  dimension of a sketch of two or more curves that nothing sizes yet scales the whole sketch about
  its origin instead, as SolidWorks' "Scale sketch on first dimension" does: a 30 on a line drawn 20
  long multiplies every drawn number of the sketch by 1.5, so it keeps its shape.
- Dragging solves as it goes (nothing written until the drag ends); a circle dragged by its edge
  takes a new radius. A dimension of what the sketch already sets comes in driven
  (`sketch2.length(line3, 30, driven=True)`), and the Driven box toggles one.
- Deleting an entity takes out its line and the relations and dimensions on it; a curve drawn
  from one of its points keeps the point where it was. A corner rectangle's line is deleted on its
  own: the rectangle is written as its four lines first.
- Move, Rotate and Scale Entities rewrite the drawn numbers of the selection's points (and, scaled,
  its circles' radii), as a drag does; Copy Entities writes new `point`s and the curves on them,
  joined as the originals are and held to nothing.
- 3 Point Corner Rectangle writes its four lines with `perpendicular` at its first corner and two
  `parallel`s, so it can stand at any angle; Perimeter Circle writes a `circle` about the center its
  three clicks give; Centerpoint Straight Slot writes a `slot` with its ends' centers either side
  of the clicked center.
- Spline writes `spline1 = sketch2.spline(line1.end, (25, 8), (10, 15))` through each point
  clicked, `closed=True` when its first point was clicked again; a double-click or Enter ends it.
- The sketch tools write lines too. Sketch Fillet writes `sketch2.fillet(line2, line3, 2)`, Sketch
  Chamfer `sketch2.chamfer(line2, line3, 2)`.
  Offset Entities draws the offset curves where they fall and holds them with
  `sketch2.offset_entities([line9, ...], [line1, ...], 2)`; its Construction geometry boxes write
  `construction=True` on the picked curves (Base geometry) or on the offset (Offset geometry).
  Mirror Entities draws the mirrored
  curves, shares the points on the centerline, and holds the rest with `sketch2.symmetric(...)`
  (and `sketch2.equal(...)` for an arc or circle). Trim Entities moves an end back to where
  another curve crosses (`sketch2.coincident(line1.end, line2)` keeps it there), splits a line
  or an arc in two (kept in line: `parallel` and `coincident`, or `equal` for an arc; a split
  line's length becomes the distance between its far ends), or makes a circle an arc; a
  rectangle is written as its four lines first. A curve nothing crosses is deleted. Extend
  Entities runs a line's free end on to the first curve ahead, or an arc's round its circle the way
  it turns, and keeps it there with the same `coincident`; a joined end is left alone. Linear and Circular Sketch Pattern write one line
  for all their copies, `pattern1 = sketch2.linear_pattern([circle1], 0, 10, 4)` or
  `sketch2.circular_pattern([circle1], sketch2.origin, 6, 360)`; deleting a copy or the pattern's
  dimension deletes the pattern. Convert
  Entities writes `converted1 = sketch2.convert(<edges>)`, the edges picked on the model (a face
  stands for its edges) by where they are on the body made before the sketch; deleting one of
  them takes that edge out of the line, and they are not trimmed. For construction adds
  `construction=True`; an Offset typed in Convert brings the edges in that way and offsets the
  curves they made at once, as Offset Entities does from model edges. Intersection Curve writes
  `converted2 = sketch2.convert(sketch2.intersection(part))`, where the body made before the
  sketch crosses its plane; deleting one of its curves deletes the line. Smart Dimension takes a
  model edge the same way: the edge comes in as `convertedN = sketch2.convert(<edge>,
  construction=True)` and the dimension is to `convertedN[0]`.
- Keep this shape when you change a sketch the engineer drew: its block of lines after the
  `Sketch(...)` line, entities assigned to names, so the engineer can open it again with Edit
  Sketch. Change sizes by their numbers or names, as in any sketch.

## Hand edits

- A hand edit is an ordinary edit to the script. The engineer's next message carries a note of
  each one ("In edit mode I changed Length (LENGTH) from 2.80 to 3.00 (parts/sizes.py, line 8).",
  "In edit mode I added Fillet2, radius 0.03 in, 1 edge (parts/housing_geometry.py, line 37).",
  "In edit mode I deleted Fillet1 (parts/housing_geometry.py, line 31).", "In edit mode I changed
  Fillet2 to radius 0.05 in, 1 edge (...)." for Edit Feature, "In edit mode I suppressed Fillet1:
  its lines are comments now (...).").
  A sketch is told once, when the engineer leaves it ("In edit mode I drew Sketch2 on the Top
  Plane (parts/plate.py, line 13): drew 4 lines and a circle, added 5 dimensions.").
- A command's line is the engineer's: keep it, and keep its selector unless a change you make
  moves what it selects (then say so, and propose the new selector).
- Read the script again before you change it, and keep their values unless they ask.
- Do not rebuild or recheck because they edited something: the viewer already rebuilt the parts
  that use the file.
- When a check fails, propose the change (which size, to what, and why) and wait for a go.
