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
  nominal is the engine's, measured on the geometry (`source: "geometry"`); its tolerance is what
  the code supplied (`pmi.plus_minus(upper, lower)`), and none where it supplied none. The viewer
  never fills a tolerance in, not even a default.
- A **datum**: its letter.
- A **geometric tolerance** (`flatness`, `position`): its value, a diameter zone, the datums it
  refers to.
- Anything else the document holds (a STEP's profile tolerance, an angle) is an entry the viewer
  does not draw: listed, saying so (`unsupported`, with its XCAF type), never dropped.

`pmiCallout` says each as a drawing writes it: the nominal at the tolerance's number of places,
`±0.2` where it is the same both ways and the two deviations stacked where it is not, true minus
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
values say why — the engine's own words where it gives them. A reference that resolved is named as
a pick's chip names it ("plate · face 7"), its canonical ref its copy.

## Drawing it

`@text-to-cad/core/lib/xbf/xbfPmiLayout.js` makes each annotation's construction in the scene's
coordinates from the elements its references name (`elementGeometry`): the point on its feature
a leader starts from (a flat face's own node nearest its middle, so never in a hole; a hole's rim),
where its label stands, and a distance's dimension and extension lines, square between its faces.
`presentation` (`pmi.place(anchor, offset)`: the anchor on the feature and the label's offset from
it, in millimetres in its part's frame, `part` the structure's prototype; drawn where that part's
first occurrence stands, `pmiPresentationToScene`, and written back in its frame) is where the code
placed it; one the code never placed stands out from its feature, each of a
feature's turned from the last. A placement says where a callout is drawn and nothing else.

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
(`xbfViewSlices.js`'s `pmi` slice, by the annotations' own ids, kept across a rebuild), never the
document.

Where the document is an `.xbf` (made from code), what the person changes is asked for, never
written (`xbf/pmi/useXbfPmi.jsx`), each a chip in Quick Edit (its `requests`) that carries one
paragraph of what to do to the model's `pmi.annotate(...)` call and the call itself
(`pmiChangeRequest`):

- **Move**: a drag of the picked label, on the plane facing the view through where it stood. It
  stands where it was let go, ringed, until the change goes; the request sets only `presentation`.
  **Pin placement** writes an annotation the code never placed where it is drawn now.
- **Edit**: a dimension's tolerance (`±0.1`, `+0.1/-0.05`, or nothing for none), a geometric
  tolerance's value and a position's datums, committed as the section's fields are. The label
  keeps saying what the document says until the code does.
- **New**: from a face's menu ("Add datum", "Add flatness"... whatever it and the faces picked with
  it can carry, which picks them and opens the PMI section on the form), or the section's New, of
  the faces Select has picked: one of the supported subset — a datum or a flatness on
  one flat face, a distance between two parallel ones, a diameter or a position on a round one —
  with a fresh id, its references the faces' canonical refs, and its values given (a geometric
  tolerance's value required; a dimension's tolerance only if given). A kind the pick cannot make
  is off in the menu, saying what it needs.

The call names its references as this build resolves them (canonical refs, which name the same
elements however the code wrote them) and asks the agent to keep the code's own. A STEP is not made
from code here: its PMI, where the engine serves any, is read alone.

## Known limits

- No leader routing: labels the code placed can cover each other, and a leader can cross the
  model.
- Not drawn under Explode or a pose; not drawn in Preview or in snapshots.
- Only the supported subset is drawn and made: distance, diameter, datum, flatness, position.
- A moved label returns to the document's placement if its change is dropped or sent before the
  code has it.
- The section's strings are English, as the engine document's other sections are.
