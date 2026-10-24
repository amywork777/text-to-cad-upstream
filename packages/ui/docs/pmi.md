# PMI

An engine document's PMI — its product and manufacturing information: dimensions with their
tolerances, datum features and geometric tolerances (GD&T) — in the CAD viewer: read from the
document, drawn on the model, picked, hidden, and asked for. It is the document's own, not the
person's: ink (Pencil and Shapes, [annotation](annotation.md)) is a note on a view and goes with a
prompt; PMI is what the part is made to, and goes with the part.

The document is made from code. A model declares its PMI with `cadgen.engine.pmi`
(`pmi.annotate(body, pmi.datum("A", ...), pmi.distance(...), pmi.flatness(...), ...)`), the
engine writes it into the document's XCAF GD&T attributes, which its AP242 export reads, and the
served structure carries it (`structure.pmi`, absent where there is none). So the viewer writes
nothing: a change asked for in the viewer is the call the model's code should make, which Quick
Edit hands the agent, and the change reaches the view as the engine's next version.

## What is said, and where it comes from

`@text-to-cad/core/lib/xbf/xbfPmi.js` reads `structure.pmi` (`readXbfPmi`), entry by entry, each
field read as it is or as nothing, never guessed:

- A **dimension** (`distance` between two parallel flat faces, `diameter` of a round one): its
  nominal is the engine's, measured on the geometry (`source: "geometry"`), or as another system's
  file gives it (`source: "file"`, said so in its values); its tolerance is what
  the code supplied (`pmi.plus_minus(upper, lower)`), and none where it supplied none. The viewer
  never fills a tolerance in, not even a default. A **basic** dimension (`pmi.basic`,
  `dimension.basic`: theoretically exact, as a position tolerance's true position is located) is a
  distance between flat faces and holes, a hole by its axis; it holds no tolerance at all, and its
  number is drawn boxed, as a drawing draws it.
- A **datum**: its letter.
- A **geometric tolerance** (`flatness`, `position`): its value, a diameter zone, the datums it
  refers to.
- Anything else the document holds (a STEP's profile tolerance, an angle) is an entry the viewer
  does not draw: listed, saying why (`unsupported`: the engine's `reason` where it gives one, else
  the viewer's own, with its XCAF type), never dropped. Whether it is drawn is the viewer's to say;
  `cadgen snapshot` reads it by the same rule.

An id is the author's and unique on its part (a datum's is its letter), so an annotation is known
by its part (`part`, the structure's prototype) and its id together (`key`, `pmiKey`: `0:thickness`),
and two parts may each have a datum A.

`pmiCallout` says each as a drawing writes it: the nominal at its tolerance's places or at what it
needs (up to four), whichever is more (`pmiDimensionPlaces`: `⌀6.35 ±0.1`, `25.40 ±0.05`,
`3.175 basic`), `±0.2` where it is the same both ways and the two deviations stacked where it is not, true minus
signs; a datum's letter in its box; a frame's cells — its characteristic, `⌀` and its value, each
datum. The characteristic and `⌀` glyphs are drawn (`xbf/pmi/pmiGlyphs.jsx`), not typed: most UI
fonts lack them.

## References and their state

Each reference is the engine's ref grammar (`cadgen.engine.refs`): `refs[].ref` canonical where it
resolved, `refs[].written` as the code wrote it, and a status — `ok`, `missing` (it names nothing
in this build), `ambiguous` (it names several, its `candidates` listed) or `invalid` (it names a
face the annotation cannot stand on: a diameter on a flat face, say). A dimension whose reference
broke has no nominal, there being nothing to measure: it says `?`. The engine resolves
them on every build; the page finds the same element (`xbf/pmi/pmiRefs.js`) by spelling each
candidate's canonical ref as the tree does and keeping exact matches, and finds none for a ref
that is not `ok`. An annotation whose reference broke is drawn where its code placed it, its
leader ending in an open ring where the code anchored it (there is no face to point at), its box
and leader dashed in the status colour (missing and invalid red, ambiguous amber), and its row and
values say why — the engine's own words where it gives them. It is still its part's (`part`),
linked to no geometry, so it keeps its key, its pick and its eye across the rebuild that broke it.
What the build that served the document warned of (`warnings`: a ref that names another kind of
face than on the last build, measured as it now is) is said on its row and in its values, in the
warning colour; a file holds none, so it is said on the build that changed it and not after. A
reference that resolved is named as a pick's chip names it ("plate · face 7"), its canonical ref
its copy.

## Drawing it

`@text-to-cad/core/lib/xbf/xbfPmiLayout.js` makes each annotation's construction in the scene's
coordinates from the elements its references name (`elementGeometry`): the point on its feature
a leader starts from (a flat face's own node nearest its middle, so never in a hole; a hole's rim),
where its label stands, and a distance's dimension and extension lines: along what it measures (the
first flat face's normal; between two holes, square to both), each extension line from its end's
plane, or from a hole's centre line.
`presentation` (`pmi.place(anchor, offset)`: the anchor on the feature and the label's offset from
it, in millimetres in its part's frame, `part` the structure's prototype; drawn where the part
stands, `pmiPresentationToScene`, and written back in its frame) is where the code
placed it; one the code never placed stands out from its feature, each of a
feature's turned from the last. A placement says where a callout is drawn and nothing else.
`pmiConstructions` is that loop over a document, the one the viewer draws and cadgen's stills are
held to (`__fixtures__/pmi_plate/constructions.json`).

A repeated part's occurrences carry the same faces (`xbf/pmi/pmiRefs.js`): an annotation of the
part is about those faces on every occurrence, so a pick of any of them finds it, and it is drawn
once, at the first occurrence that is shown — not hidden, and in the isolation where one is set
(`pmiDrawnAt`). Where no occurrence of its part is shown it is not drawn, and stays listed; one
whose reference broke is drawn where its code placed it, in its part's frame. One of no part
(another system's, linked to nothing) is in the scene's frame.

`xbf/pmi/PmiOverlay.jsx` draws them over the viewport, as the joint handles are drawn: the labels
are DOM at the UI's size whatever the zoom, laid out again on every frame the camera or the view's
size moved, and the leaders (an arrow at the feature, a datum's filled triangle) and dimension
lines (arrows inside, or outside where the line is short) on a canvas under them. A distance's
words stand beside its line, out from the part. Labels the code did not place are set apart on
screen where two would cover one another (`separateLabels.js`). A leader or extension line whose
start the model hides from the camera (a datum on the bottom, seen from above) is drawn faint,
its marker hollow (`pmiHidden.js`: a ray through the point, its first surface nearer by more than
a thousandth of the model); the labels themselves are always on top, to be read. They are drawn on the model as
built: while Explode or a pose moves the parts they are not drawn, and the section says so.

## Picking, hiding, and asking

Under Select a label is a control. A click picks its annotation, and its features are lit as a
pick of them is (the renderer's element highlight); its row in the section opens its values. A
double-click looks at its feature (`lookAt`). Escape lets it go, and a press on the model does.
Under any other tool the labels take no pointer.

The section's eyes hide one annotation, or all of them; what is hidden is the file's view
(`xbfViewSlices.js`'s `pmi` slice, by each annotation's key, kept across a rebuild of the same
parts), never the document. Turned off, PMI is off in a prompt's views too (`display.pmi` false).

Where the document is an `.xbf` (made from code), what the person changes is asked for, never
written (`xbf/pmi/useXbfPmi.jsx`), each a chip in Quick Edit (its `requests`) that carries one
paragraph of what to do to its part's `pmi.annotate(...)` call, the annotation by its author's id
and the part by its name, and the call itself (`pmiChangeRequest`), what it does not change as the
document says it (a label, a position's zone, round or not):

- **Move**: a drag of the picked label, on the plane facing the view through where it stood. It
  stands where it was let go, ringed, until the change goes; the request sets only `presentation`.
  **Pin placement** writes an annotation the code never placed where it is drawn now.
- **Edit**: a dimension's tolerance (`±0.1`, `+0.1/-0.05`, or nothing for none), a geometric
  tolerance's value and a position's datums, committed as the section's fields are. The label
  keeps saying what the document says until the code does.
- **New**: from a face's menu ("Add datum", "Add flatness"... whatever it and the faces picked with
  it can carry, which picks them and opens the PMI section on the form), or the section's New, of
  the faces Select has picked: one of the supported subset — a datum on one flat or round face, a
  flatness on one flat face, a distance between two parallel ones, a basic dimension between two
  of flat faces and holes, all parallel, a diameter or a position on a round one —
  with an id and a letter its part has none of, its references the faces' canonical refs, its
  datums its part's, and its values given (a geometric tolerance's value required; a dimension's
  tolerance only if given). A kind the pick cannot make is off in the menu, saying what it needs.
  Until it is built it is called by its id ("Add flatness"), a datum by its letter ("Add datum B").

The call names its references as this build resolves them (canonical refs, which name the same
elements however the code wrote them) and asks the agent to keep the code's own. A STEP is not made
from code here: its PMI, where the engine serves any, is read alone.

## Reviewing requirements and the export

The PMI section follows the selected annotation's faces, or the selected geometry when
no annotation is picked. It lists every attached requirement, including hidden callouts.
**Show all PMI** restores the whole list; **For selection** returns to the filter. A selection
with no attached PMI says so without implying that it needs no requirements. A dimension
with explicit tolerances also shows **Current limits** (nominal plus each signed deviation, at
the places its nominal is written at), from the saved document, never a guessed tolerance or an unapplied Quick Edit.

A position tolerance lists its datum references in primary, secondary and tertiary order.
These buttons highlight the datum's geometry without changing its assignment or adding a
Quick Edit. Selecting a datum lists the tolerances that use it under **Used by**. Both
directions resolve within the annotation's part.

**Export** in the top-right toolbar offers **STEP (AP242)**, written from the built document
with all its semantic PMI; a Quick Edit request not yet built is not in it. Where the document
carries PMI, the menu says so under the format. The export service pins the revision on screen,
holds the job and its file, and never runs the model's code. A STEP of a pose or of one part, and
an XBF made again from the document, would drop the PMI, so they are unavailable; the menu says why
for each row the PMI decided (`pmi` with a `reason`), STEP and XBF alike.

Once the STEP is written, the worker reads that same file back on its own and compares its
supported annotations with the document's, one to one: values, units, datum order, tolerance-zone
form and the faces each is on, by name. The result and the file's SHA-256 go with the export job,
and stay with it when another model opens: the check is part of the export, with no endpoint or
export of its own. The browser's save writes that file; a save that fails never says Saved.

Missing or extra annotations, no PMI, a parser problem or a schema other than AP242 fail the
check. Both signed deviations' units are checked. Face names are looked for across all the
geometry, faces with no annotation included. An ambiguous name, two source refs that collide, a
datum letter used twice, an unsupported modifier or missing uniqueness metadata leave the check
incomplete, and its result says so; the file stays, to inspect.

The check does not establish a complete manufacturing definition, nor that a factory's importer
reads the file: the result says that is untested. Graphical callouts and the author's annotation
ids are not exported; basic dimensions are, marked theoretical, and are checked as any other
dimension is. What interoperability is tested with is the exported STEP itself.

## Known limits

- No leader routing: labels the code placed can cover each other, and a leader can cross the
  model.
- Not drawn under Explode or a pose, or in Preview. `cadgen snapshot` draws it as this does, on the
  parts as made (the engine README's snapshot section); a label moved here and not yet in the code
  is drawn where the document places it.
- Only the supported subset is drawn and made: distance (basic or not), diameter, datum, flatness,
  position.
- A moved label returns to the document's placement if its change is dropped or sent before the
  code has it.
- The section's strings are English, as the engine document's other sections are.
