# PMI: datums, dimensions and tolerances

Read this file when the user asks for datums, toleranced dimensions, basic dimensions,
flatness or position (GD&T, PMI, model-based definition), or for a STEP a supplier or
an inspection tool can read requirements from.

A part's requirements are written in its model, on the faces they control, and the
document keeps them:

- **`pmi.annotate(part, *annotations)`** gives one part its annotations and returns
  the part.
- **Datums** name the faces the others are measured from: `pmi.datum("A", face)`.
- **Dimensions** are measured on the geometry, never typed: `pmi.diameter`,
  `pmi.distance`, and `pmi.basic` for a theoretically exact one.
- **Geometric tolerances**: `pmi.flatness` and `pmi.position`.

The `.xbf` keeps them as the kernel's own GD&T, linked to their faces, and a STEP
export writes them as AP242 semantic PMI: requirements a program reads off the faces,
not drawn callouts. A GLB, STL or 3MF carries none. The viewer draws each one on the
model and lists it in its PMI section, and `cadgen snapshot` draws them as the viewer
does.

## Annotate a part

```python
from cadgen.engine import pmi, step, xbf
import build123d as bd


@xbf(out="../XBF/plate.xbf")
@step(out="../STEP/plate.step")
def plate():
    body = bd.Box(100, 60, 10) - bd.Cylinder(5, 10)
    body.label = "plate"
    bottom, top = body.faces().sort_by(bd.Axis.Z)[0], body.faces().sort_by(bd.Axis.Z)[-1]
    front, left = body.faces().sort_by(bd.Axis.Y)[0], body.faces().sort_by(bd.Axis.X)[0]
    hole = body.faces().filter_by(bd.GeomType.CYLINDER)[0]
    # The tolerance values are examples: take the user's, or ask for them.
    return pmi.annotate(
        body,
        pmi.datum("A", bottom),
        pmi.datum("B", front),
        pmi.datum("C", left),
        pmi.distance("thickness", bottom, top, tolerance=pmi.plus_minus(0.2)),
        pmi.diameter("hole-diameter", hole, tolerance=pmi.plus_minus(0.1, 0)),
        pmi.flatness("top-flatness", top, 0.05),
        pmi.position("hole-position", hole, 0.1, datums=["A", "B", "C"]),
        pmi.basic("hole-from-B", front, hole),   # the hole's true position: 30 from B
        pmi.basic("hole-from-C", left, hole),    # and 50 from C
    )
```

- **Annotate the shape that is returned**, after its last boolean: a `Face` given as a
  ref is numbered against that shape when `annotate` is called. Annotations given to
  a shape a later operation replaces are reported as `unattached`.
- **One part at a time.** In an assembly, annotate each part before it goes into the
  compound; a part placed twice carries its PMI once. An annotated assembly is refused.
- **Ids are yours**: unique on the part and kept across edits. A datum's id is its
  letter. The build report, the viewer and the STEP check name annotations by id.
- **A ref** is a build123d `Face` of the annotated shape, or a ref in the engine's
  grammar: an element name, a canonical `owner/element` ref, or `face N`
  ([references](inspection-and-validation.md#references)). A selection the code makes
  again on every build, or an element name, follows the face through edits; `face N`
  does not.
- **Nominals are measured**: a cylinder's diameter, or a distance between two parallel
  planes, from a plane to a hole's axis parallel to it, or between two parallel axes.
- **Tolerances are explicit.** `pmi.plus_minus(upper, lower=None)` takes signed
  deviations, `lower` defaulting to `-upper`. A dimension given no `tolerance=` holds
  none: nothing is assumed.
- **A basic dimension** (`pmi.basic`) has no tolerance: it locates what a geometric
  tolerance controls, such as a position's true position. A tolerance on one, or a
  basic diameter, is refused.
- **A datum frame** is ordered, primary first, three datums at most, and a datum holds
  one place in every frame that names it.
- **Anything else is refused** (`PMIUnsupported`), never approximated: other
  characteristics and dimension types, limits and fits, material modifiers, reference
  dimensions, and assembly-level PMI.
- **`presentation=pmi.place(anchor, offset)`** says where a callout's label is drawn,
  in millimetres in the part's frame. It is not a requirement, and no export writes
  it. Dragging a label in the viewer asks for this change.

## After an edit

Every build resolves each ref again. One that still names its face follows it, its
nominal measured anew and its tolerance as written. Otherwise its status says why:

- `missing`: it names no face (the face was removed, or is made another way);
- `ambiguous`: it names several faces;
- `invalid`: it names a face the annotation cannot stand on (a diameter on a plane).

Such an annotation stays in the `.xbf` with its values, linked to nothing, and is
listed in the build report's `pmi` (`{"annotations", "problems"}`, with `unattached`
where any are). A STEP is refused rather than written without it, naming each one.
Fix the ref in the code, or remove the annotation.

A ref written as text that names a face of another kind than on the last build (a
hole's name that passed to a flat side of the cut that replaced it) is measured as it
is now, and the build warns of it once, on that build: `warning: pmi: ...` in its log
and `warnings` in its report's `pmi`. Read the warning, and point the ref at the face
meant: the next build of the same code no longer says it.

## Read and check

```python
from cadgen.engine import pmi

for entry in pmi.read("XBF/plate.xbf"):   # or a .step
    print(entry["id"], entry["kind"], entry["status"], entry["problem"])
```

Each entry has `id`, `kind` (`datum`, `dimension`, `geometric_tolerance`), `status`
(`ok`, `missing`, `ambiguous`, `invalid`), `problem`, `refs` (each with its canonical
ref and status), and one of `datum`, `dimension` or `geometric_tolerance` holding its
values. PMI read from another system's STEP that this does not model whole (another
characteristic, limits, a fit, modifiers, a link to an edge or a point) is listed as
`kind: "unsupported"` with its `xcaf_type` and a `reason`, never dropped, and a
nominal the file holds says `"source": "file"`.

## Export

`@step`, `cadgen export XBF/plate.xbf STEP/plate.step` and the viewer's Export
(**STEP (AP242)**) write the PMI. While a document holds PMI the code made, the
exports that would rebuild it without its PMI are refused: a posed STEP, and a STEP
or `.xbf` of one part (`--part`).

A vendor's STEP converts as ever (`cadgen export vendor/motor.step vendor/motor.xbf`):
the `.xbf` keeps the file's GD&T as read, and an export of either writes it. What an
export of a vendor's document cannot carry whole (a posed or partial one carries no
PMI) is said in its log, `warning: pmi: ...`, never refused.

The viewer's Export reads each STEP it writes back with a reader of its own, without
the kernel, and matches every annotation to the file: values, units, datum order,
zone, faces and a basic dimension's mark. The export's status says how many matched,
with the file's SHA-256. It checks the file, not a supplier's importer.

A STEP carries no annotation ids, and no drawn callouts.

## Review

`cadgen snapshot` draws a document's PMI as the viewer shows it, a broken one in red
or amber at the place the code gave it; `pmi=off` draws the model alone
([snapshots](snapshot-review.md)). In the viewer, picking a callout or its row lights
its faces and shows its values: a toleranced dimension's limits, a tolerance's datums
in order, and what uses each datum.
