# Studio's views

Studio's own part of the viewer (studio-base, not Jake's text-to-cad): the FEA and CAM result
viewers, which the GLB renderer loads for a file `cad fea solve` or `cad cam plan` wrote, and CAD
mode's workspace over an engine document. [`settings-ui.md`](settings-ui.md) and
[`cad-renderer.md`](cad-renderer.md) are the viewer's contract; this page is what Studio adds to it,
kept apart so Jake's pages merge as he writes them.

## In the GLB renderer

- **An FEA result** (the `result.glb` a study's solve writes, `cad <type> solve --out DIR`) is drawn by its
  own surface over the same shell (`glb/FeaSurface.jsx`, in the FEA viewer's chunk, `glb/feaView.jsx`, which a
  plain GLB never fetches): the same tools, Select picking the result's faces, with Study (and an assembly's
  Parts) in the view's panel, the colour bar and the study's markers on the model. Its layout is the viewer's
  own, the same for every result: the file carries no view. See [An FEA result](#an-fea-result).
- **A CAM result** (`<stem>.cam.glb`, `cad cam plan`): a GLB whose scene says
  `generator: "cad cam"` and carries the job in its extras (`cam`, schema 1) loads
  the CAM viewer, its own chunk (`glb/camView.jsx`; a plain GLB never fetches it), before
  it is framed; should the chunk fail, the file is refused as one that failed to load, never
  drawn as a plain GLB that would hide its verdict. Its tools are a GLB's,
  less Explode (its nodes are the part, the stock and the toolpaths). It adds **Job**, a
  file sidebar section (`glb/CamJobPanel.jsx`, id `job`): the verdict first, its errors
  in plain words, then each setup and its operations (word, tool, time), the tools, and
  **Show**, a row with an eye for each thing the file draws beyond its surfaces (Toolpaths,
  Rapids, Tool, Stock, Part; the renderer's one slice of the file's view, `cam`).
  A row isolates its paths (the rest dimmed) until it is chosen again, and is Quick Edit's
  chip (`camChips`) beside the picked nodes: the part the job names (`document`), its faces
  as a selector or the whole part, and its sentence as the reference's `summary`. The
  file's LINES (`_CAM_T`, `_CAM_OP`, which GLTFLoader lowercases) are redrawn as
  screen-space lines, one per operation and kind (`glb/cam/lines.js`): feed moves in the
  operation's colour, rapids thin and dashed. They and the riding tool hang
  from a group of their own in the model group, placed where the scene's root is and never
  inside the scene, so Preview's sibling, Select's picks and Clip's caps never meet them;
  Clip cuts the part and the stock, not the paths. The file's routines gain **Simulate**
  (and one per setup), played from the Animation section in the tools view, which draws the
  paths up to the moment and rides a tool along them (`glb/cam/playback.js`,
  `glb/cam/tool.js`), a readout at the view's foot. Preview shows the part as the view had
  it, without the paths, and has no CAM routine.
- **State.** An FEA result keeps one renderer slice, `fea` (the field, the deformation, the load and
  the markers' gate), against its fields and scale; a CAM result one, `cam` (the Show rows and the
  hidden operations). Any other GLB keeps none (`cad-renderer.md`, the `renderer` row).
- **Tools.** A CAM result's strip is a GLB's without Explode.

## In the view's chrome

- **Quick Edit** stands under the notices where there are any: the host's (the CAD app's file
  handler's corner: Full size and its update), then the view's own about its file (a STEP brought in
  with no part script: *Imported STEP, no history* and **Edit as a part**). Quick Edit steps down
  under them at every width, so neither covers the other.
- **The view's panel** of a CAM result has one tab, **Job**: see [CAM results](#cam-results).
- **CAD mode's left dock.** The FeatureManager and PMI share one panel head instead of a stack panel's
  heading (`DOCK_PANEL_HEAD_CLASS`): 28px, 8px in, the words as written, its glyphs ending 8px from the
  right edge. The tracked-caps headings inside PMI sit a level below it, and every heading and row of
  the dock starts on the same 8px edge. The tree takes up to 75% of the column; PMI stays open and
  scrolls in the rest.

## An FEA result

A GLB that `cad fea solve` wrote is a result: a linear static stress study of a part or a bonded
assembly, its mesh carrying every field (von Mises stress and the displacement), the true
displacement, the study it was solved for, the checks cadgen judged and the source face of every
triangle (`glb/feaResult.js`). The viewer reads the study once there (`result.study`), never the
file's raw echo. Its layout is the viewer's: a file says what was solved and judged, not how to show it.

The FEA viewer is a chunk of its own (`glb/feaView.jsx`: its surface, `glb/FeaSurface.jsx`, Study, the
colour bar, the markers, `feaResult.js` and `fea/`), which `GlbRenderer` loads with one `import()` only once
the scene carries a mesh `cad fea solve` wrote (`generator` in its extras). A plain GLB
never fetches it; a result whose chunk fails to load says so in the load's alert, never drawn as a plain GLB. Its words are in `glb/fea/`: per check kind one row of `checkKinds.js` (stress and
displacement), per field one of `fields.js`, Study's setup in `setup.js`, What you see's controls in `controls.js`.

- **Its tools, Parts and Study.** A result has every GLB's tools, Select picking its faces rather than its
  nodes, then Annotate, Measure and Clip (which cuts it open in the field's colours; it has no X-ray). Study,
  and an assembly's Parts above it, are tabs of the view's panel (`glb/FeaStudyPanel.jsx`).
  - **Parts**, only for an assembly of six parts or more (`feaShowsParts`); under six, a face picked on
    the model names its part. One row per part, its material and "holds 1.5×" (or "yields"), the joints
    it is in under it ("↔ base", "bonded · 88 mm²"), the weakest part open.
  - **Study**, always in this order:
    - **The verdict** (`glb/FeaVerdict.jsx`, `feaVerdict`): a headline in the worst check's status tone
      ("Too weak", "Moves too much", "Fails 1 of 2 checks", "Passes all checks"), how much of this load
      the weakest check takes ("OK only to 0.8× this load", "OK up to 1.6× this load"), then each check,
      worst first, with a meter of how much of its limit it uses and its value against the limit. The
      checks are the file's (`extras.checks`); at a load of 0 it says **No load**.
    - **The setup**, as sentences under glyphs that match the markers: **Held at**, **Slides on** (a
      roller), **Pushed** (each load, its faces under it, shut) and **Made of**.
    - **What you see** (`feaControls` in `glb/fea/controls.js`, each row `glb/fea/controlRow.jsx`): a
      Field select (Stress, Displacement), a Deformation slider from 0 to four times the file's own
      exaggeration, opening at it, and a Load slider from 0.1× to 3× the solved load, opening at 1×;
      then the **Loads and fixtures** checkbox, on as the file opens, saying what it draws.
    - **Details**, shut: the mesh size and how it got there.

    A group shows only where the file records something for it. A file missing anything cadgen always
    writes (its fields, its `checks` or `study`, the safety factor, a check's numbers, status or margin), or
    with a check of a kind cadgen does not judge, does not read: the viewer says so in the load's alert over
    the model as the file colours it, and stands no default in for it.
- **Choosing.** A row of Study or Parts, a check in the verdict, or a face pressed under Select tints
  what it stands for (two thirds of the way to magenta, which no colour of the ramp is) and carries it
  into Quick Edit by the STEP the result was solved from, with what it is ("Fixed face 17", "Part
  'post'", "Tip sag fails: moves 0.62 mm, limit 0.5 mm (OK only to 0.8× this load)"). One face's chip
  has a card: what the study does to it and, in an assembly, its part.
- **A load other than the solved one** (the Load slider, k; the study is linear, so it scales exactly):
  the colour bar's range, every check's value and the displacement drawn are k times the solved ones,
  every "holds" is divided by k, and the verdict can change its word.
- **A colour bar** at bottom-centre (`glb/FeaColourBar.jsx`, `glb/feaChrome.js`): the field and its range,
  no controls. **Findings** stay in the file for the agent: the viewer raises no alert for them.
- **Loads and fixtures on the model** (`glb/feaMarkers.js`, one row of `MARKER_KINDS` per kind): arrows
  on each loaded face (one through the middle for a body load) labelled with the amount at the load shown,
  never on or inside the part (`glb/FeaLoadLabels.jsx`); grey cones into each fixed face, on a plate for a
  roller. They stand on the deformed shape, a faint ghost where the model hides them.
- **Its routine, the Load ramp** (`LOAD_RAMP` in `glb/feaView.jsx`, one of `useGlbAnimation`'s own clips),
  in the playbar under the model and Preview's: the load going on from none to the load chosen over two
  seconds. Preview frames once on the box the model is drawn in over the ramp (`glb/feaBounds.js`).
- **Framing.** The camera frames a result right of the view's panel and above the colour bar
  (`runtime.framingInset`, `framingInset` in `glb/feaChrome.js`, `insetLeft` and `insetBottom` in
  `kit/camera/viewportCameraFit.js`); Preview frames in the whole width.
- **The choices are the file's view**: one renderer slice (`fea`: the field, the deformation, the load
  and the markers' gate), written against the result's fields and scale, so a re-solved result opens at
  its own defaults.

## CAM results

A GLB written by `cad cam plan` carries its job in the scene's extras (`cam`). The GLB
renderer loads the CAM viewer (`renderers/glb/camView.jsx`, a chunk of its own that a plain
GLB never fetches) and draws the toolpaths, the tool, the stock box and the part. The plan is
3-axis milling and drilling (FreeCAD plans it, cad cam checks it): each setup's tool comes from
+Z or -Z. Its strip is a GLB's (Select, Pencil, Shapes, Measure, Clip), with no Explode: the part,
the stock and the paths mean nothing pulled apart. What there is to read of the job is
**Job**, a tab of the [view's panel](settings-ui.md#the-views-panel-and-the-tool-stack), there whatever tool
is in hand. The verdict is the status: Job has no findings card. Findings go to the agent,
through the GLB's extras and the CLI's JSON; the section shows only the errors, as rows under
the verdict.

- **Verdict.** First, in the theme's status tones: green "Ready to cut · 42 min · 3 tools",
  or red "2 to fix". Under it, what the job takes: its tool changes ("No tool changes",
  "1 tool change", "3 tool changes", counted from the operations in program order) and the
  controller its G-code is for
  ("grbl controller"); then, muted, whether G-code was written and how many warnings went to
  the agent; then each error in plain words, a row that chooses the operations it is about.
- **Setups and operations.** Each setup is a parent row (its name, how many operations, its
  time), its operations under it in the job's order: a swatch in the operation's own path
  colour, its plain word, its tool and its time. An operation row's eye floats over its right
  end as an assembly row's does, on hover and kept while it is on: **Hide** puts that
  operation's paths away (feed moves and rapids), **Reveal** brings them back. Any number can be
  hidden; hiding is not choosing.
- **Tools.** Under a muted **Tools** heading, each tool once, in the order the program first
  uses it: how the machine names it and what it is ("T1 6 mm flat"), then the spindle speed
  and feed its operations run it at ("12,000 rpm · 1,440 mm/min"), a range where they differ.
  Its hint adds the operations that use it.
- **Show.** Under a muted **Show** heading, a row for each thing the file draws beyond its
  surfaces, each only where the file has it, its words on hover and its eye as a layer's is
  (on hover, kept while it is put away): **Toolpaths** (each operation in its own colour),
  **Rapids** (moves between cuts, dashed), **Tool** (the tool on the path while Simulate
  plays), **Stock** (the see-through block the part is cut from; put away by default) and
  **Part**. These were Display's gates; Display is a mode and the grid, and a file's own
  drawing is its section's. The rows and the hidden operations are the file's view (the
  renderer's `cam` slice), kept with it as the camera and Display are.
- **Safety.** At the section's foot, always shown in small muted type, the sentence every
  result carries (`cam.safety`): what the plan is not, and what to check before cutting.
- **Choosing.** Every setup, operation, tool and error row is a choice: a press chooses it, a
  second press, Escape or its chip's X lets go. The choice isolates its operations (the rest
  of the paths dimmed, not hidden) and is Quick Edit's chip beside any picked nodes, named for
  its row ("Pocket", "Top setup", "T1 6 mm flat"), a face's glyph where it names faces (in
  the operation's colour, for an operation), else the part's; its card the row's sentence, the
  part and how many faces. What Quick Edit carries is the part the job was planned from, the
  faces the operations name (the whole part where they name none), and the row's sentence. A
  setup chooses its operations, a tool every operation that runs it, an error the operations
  it is about. A plain pick of a node lets go of the choice, as it does of a measurement.

**Simulate.** A result's routines are the file's, played from the playbar under the model:
**Simulate** plays the whole program, and a job with more than one setup adds **Simulate
<setup>** for each, showing that setup's paths alone. The program plays at one pace for every
routine, the whole job in at most 30 seconds; the paths are drawn up to the moment and the tool
rides them, standing along its setup's axis. With reduced motion (the system's `prefers-reduced-motion` or
the host's `reducedMotion`) nothing sweeps: a routine steps one operation a second, each drawn
whole with the tool at its end. While one plays, a small readout sits at the view's bottom
centre (above Quick Edit's sheet on a phone): the operation under way, the program's time over
its whole ("1:32 / 3:38") and how fast it plays ("12× speed", "Real time", or "One operation a
second"). It takes no pointer and is not read out as it changes. There is no Time row in Job:
the Animation section is the one way to move through the program. As every routine, Simulate
is one motion: playing it puts Clip back, and Clip set lets go of it. Preview draws the part
as the tools view had it, its stock as shown, with none of the job's drawing and no CAM
routine: the paths are the tools view's alone.
