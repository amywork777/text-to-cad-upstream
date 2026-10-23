# Semantic PMI: data contract, AP242 export and downstream testing

cadgen's engine attaches manufacturing requirements (PMI: datums, dimensions and geometric
tolerances) to a part's own faces. It keeps them in the part's native document (the `.xbf`)
and writes them to STEP AP242 as **semantic** PMI: machine-readable entities linked to the
faces they control, not graphical callouts. This page is the contract that the 3D annotation
viewer and downstream readers (a DFM engine reading AP242) build on.

Status of each interface: **stable** means it is not changed without a deprecation;
**provisional** means it may still change in this PR's review.

| Interface | Status |
| --- | --- |
| `pmi.annotate`, `pmi.datum`, `pmi.diameter`, `pmi.distance`, `pmi.flatness`, `pmi.position`, `pmi.plus_minus` | stable (signatures and meaning) |
| `pmi.basic` (basic, theoretically exact distances) and the entries' `dimension.basic` | provisional (new in this branch; stable once reviewed) |
| `pmi.dimension`, `pmi.geometric` (generic forms; only the verified types are accepted) | stable |
| `structure["pmi"]` entry shape (below) | stable for the fields listed; new fields may be added |
| `status` values `ok` / `missing` / `ambiguous` / `invalid` | stable |
| `presentation` / `pmi.place(anchor, offset)` | **provisional** (frame and fields may change with the 3D viewer) |
| The cadgen JSON attribute's layout inside the xbf (`pmi.EXTRA_GUID`) | **provisional**, internal: read through `pmi.read`, never directly |
| Report of the AP242 reader (`cadgen/_internal/ap242_pmi_report.py`; `scripts/pmi/ap242_pmi_report.py` runs it) and the export check's `pmiVerification` | provisional (verification tools, not an API) |

## Fixture

| File | What it is |
| --- | --- |
| [`models/examples/src/pmi_plate.py`](../../models/examples/src/pmi_plate.py) | The example model. All tolerance values are **illustrative**. |
| [`pmi_plate.step`](pmi_plate.step) | The AP242 file the example exports (`cd models/examples/src && python pmi_plate.py`, then `../XBF/pmi_plate.step`). |
| [`pmi_plate.xbf`](pmi_plate.xbf) | Its native document. |
| [`pmi_plate.pmi.json`](pmi_plate.pmi.json) | `structure["pmi"]` as the viewer is served it. |
| [`pmi_plate.report.json`](pmi_plate.report.json) | What a reader with no OCCT in it finds in `pmi_plate.step`. |

The part is a 100 × 60 × 10 mm plate with a Ø10 mm through-hole at its centre. Its annotations,
with **illustrative** values:

| Id | Kind | On | Value |
| --- | --- | --- | --- |
| `A` | datum | bottom face (z = −5) | |
| `B` | datum | front face (y = −30) | |
| `C` | datum | left face (x = −50) | |
| `thickness` | linear distance, bottom → top | two parallel planes | 10 mm (measured) ±0.2 |
| `hole-diameter` | diameter | the hole's cylinder | Ø10 mm (measured) +0.1/0 |
| `top-flatness` | flatness | top face | 0.05 mm |
| `hole-position` | position, diametral zone | the hole's cylinder | Ø0.1 mm to A\|B\|C |
| `hole-from-B` | basic distance, B → the hole's axis | front plane, the hole's cylinder | 30 mm (measured), no tolerance |
| `hole-from-C` | basic distance, C → the hole's axis | left plane, the hole's cylinder | 50 mm (measured), no tolerance |

`tests/python/packages/cadgen/engine/test_pmi.py` (`FixtureTest`) checks that the committed
files are still what a fresh build makes.

## Authoring (Python, in the model)

```python
from cadgen.engine import pmi, step, xbf

@xbf(out="XBF/plate.xbf")
@step(out="plate.step")
def plate():
    body = bd.Box(100, 60, 10) - bd.Cylinder(5, 10)
    bottom = body.faces().sort_by(bd.Axis.Z)[0]
    front = body.faces().sort_by(bd.Axis.Y)[0]
    hole = body.faces().filter_by(bd.GeomType.CYLINDER)[0]
    return pmi.annotate(body,
        pmi.datum("A", bottom),
        pmi.datum("B", front),
        pmi.diameter("hole-diameter", hole, tolerance=pmi.plus_minus(0.1, 0)),
        pmi.position("hole-position", hole, 0.1, datums=["A", "B"],
                     presentation=pmi.place(anchor=(0, 0, 5), offset=(20, 20, 0))),
        pmi.basic("hole-from-B", front, hole))          # the true position: theoretically exact, measured
```

- **The code is the source.** The document is made from the model on every build (engine laws 2
  and 11), and there is no route for writing PMI into a document. A viewer's create, edit or
  move is a Quick Edit packet that writes these calls into the script.
- **Refs.** A ref is a build123d `Face` of the shape passed to `annotate` (numbered against it at
  once), or a ref in the engine's grammar: an element name (`f:pmi_plate.body_make_box1.5;M:pmi_plate.body`),
  the canonical `owner/element` ref a served document gives (`plate/f:…`), or an ordinal
  (`face 7`). Element names are the engine's persistent naming. Ordinals work but are fragile
  across edits.
- **Ids** are the author's: unique on a part and stable across rebuilds. A datum's id is its
  letter.
- **Nominals are measured**, never typed in: a cylinder's diameter, or the distance between two
  parallel planes.
- **Basic dimensions** (`pmi.basic`: ASME's basic, ISO's theoretically exact) are measured distances
  with no tolerance. They locate what a geometric tolerance controls, such as a position
  tolerance's true position. A basic dimension goes between two parallel planes, from a plane to
  a hole's axis parallel to it, or between two parallel axes. Anything else is `invalid`, for
  example an axis that crosses the plane. A tolerance on a basic dimension, or a basic diameter,
  is refused.
- **Tolerances are explicit.** `plus_minus(upper, lower=None)` takes signed deviations from the
  nominal; `lower` defaults to `-upper`. A dimension given no tolerance holds none.
- **Datum frames** are ordered, primary first, with three datums at most. A datum holds one
  place in every frame that names it, because XCAF holds one position per datum. Anything else
  is refused.
- **Part-level only.** `annotate` takes one part. An annotated assembly is refused.

## Where it is held: the native document (`.xbf`)

The source of truth inside the document is XCAF's own GD&T objects on the GD&T tool
(`XCAFDoc_DimTolTool`, label `0:1:4`):
- `XCAFDoc_Datum`, `XCAFDoc_Dimension` and `XCAFDoc_GeomTolerance`, each with its
  `XCAFDimTolObjects_*Object`, hold the kind, values and units. Units are the document's
  millimetres.
- Each is linked by XCAF graph nodes to the sub-shape label of the face it is on, under the
  part's label.

These are the objects the STEP writer translates and the STEP reader produces, so any OCCT-based
reader of the xbf (BinXCAF) sees the semantics.

Beside each object, one cadgen attribute holds what XCAF has no place for, as JSON: the id, the
label, each ref as written, the status and its problem, and the presentation. For an annotation
linked to no geometry it also holds the values, because XCAF only gives values meaning through
geometry. Nothing is held twice. The values are never in the JSON for a linked annotation.

A document without PMI holds nothing new. Its STEP is byte-identical to PR #568's. Its xbf
differs only in the build closure's engine digest, which records the engine's code and changes
with any engine edit. Its cache key is the same, so nothing is rebuilt (checked). A document
with PMI is still xbf/4. PR #568's
engine without this change opens it (checked) and leaves PMI out of its structure. Its STEP
export still writes the GD&T, but with OCCT's three defects unrepaired (see AP242 export). A
warm build of a document holding PMI converts the whole document instead of patching it.

## Read / query

- `pmi.read(path)` reads an `.xbf` or a `.step` and returns the entries below.
- `Loaded(path).structure()["pmi"]` is the same list. The viewer gets it on every version with no
  extra route, and a build's own structure (`build.held(...).structure`) is the same list
  (tested).
- The build report's `pmi` is `{"annotations": n, "problems": [{part, id, status, problem}],
  "unattached": [ids]}`. `unattached` lists ids passed to `annotate` on a shape that never
  reached the result, for example one a later operation replaced.

### `structure["pmi"]` entry

```jsonc
{
  "id": "hole-position",            // author's id; for a foreign STEP: datum letter, or "<kind>-<n>"
  "kind": "geometric_tolerance",    // "dimension" | "datum" | "geometric_tolerance" | "unsupported"
  "label": null,                    // author's optional text
  "status": "ok",                   // worst of its refs: "ok" | "missing" | "ambiguous" | "invalid"
  "problem": null,                  // why, when status is not ok
  "part": 0,                        // the structure's prototype index; null when linked to nothing
  "refs": [{
    "role": "feature",              // "feature" | "from" | "to"
    "ref": "plate/f:…",             // canonical (refs.py's Hit.ref) when resolved; else == written
    "written": "face 7",            // as the code wrote it (null for a foreign STEP)
    "status": "ok",
    "candidates": null,             // for "ambiguous": canonical refs of every face it names
    "problem": null
  }],
  "presentation": {"anchor": [-5, 0, 5], "offset": [-15, 15, 0]},   // PROVISIONAL; mm, part frame; null when never placed
  "xcaf_type": null,                // the XCAF type name, for kind "unsupported"

  // one of, by kind:
  "dimension": {"type": "diameter" | "distance",
                "basic": false,             // true: theoretically exact (pmi.basic), tolerance always null
                "nominal": {"value": 10.0, "unit": "mm", "source": "geometry"} | null,  // null when unlinked
                "tolerance": null | {"type": "plus_minus", "upper": 0.1, "lower": 0.0}},
  "datum": {"letter": "A"},
  "geometric_tolerance": {"characteristic": "flatness" | "position", "value": 0.1, "unit": "mm",
                          "zone": "diameter" | null, "modifier": null, "datums": ["A", "B", "C"]},
  "values": {...}                   // kind "unsupported": what XCAF holds
}
```

### References after a model edit

Every build resolves each ref against the part as it is built now:

| Status | When | Kept in the xbf | Exported to STEP |
| --- | --- | --- | --- |
| `ok` | The ref names one face the annotation can stand on. | Yes, linked to the face | Yes |
| `missing` | It names nothing: the face was deleted, or its making changed and it is named differently. The problem text gives the name's atom now, where one exists. | Yes, unlinked, with values | **Refused** |
| `ambiguous` | It names several faces; `candidates` lists them. | Yes, unlinked | **Refused** |
| `invalid` | It names a face the annotation cannot stand on: a diameter on a plane, non-parallel planes for a distance, a datum letter the part doesn't define, or an owner that isn't the annotated part. Or, for a ref written as text, it names another kind of face than it did on the model's last build (below). | Yes, unlinked | **Refused** |

"Refused" means `ExportRefused` names every such id. A decorator's STEP then fails the build
after the xbf is written, so nothing is silently discarded.

**A name that comes to name another kind of face is flagged.** Each ref written as text in code (an
element name, a canonical `owner/element` ref, or `face N`) is held to the kind of face it named:
a plane, or a cylinder. A later build where the same ref, with the same annotation id, role and
written text, names a face of another kind marks it `invalid`. The problem names both kinds:
"… named a cylinder face on the last build and names a plane face now". This catches a hole made a
square cut whose name passed to a flat side of the cut, which a basic dimension could otherwise
measure as a plane (44 in the viewer's v3 fixture). Only the kind is compared, so a name that passes
to another plane, or to another hole, isn't caught.

- **History.** The last build is the model's previous document in this process, or after a restart
  the model's xbf on disk. A model with no previous document isn't checked: its first build, or an
  in-memory model after a restart.
- **Clearing.** The flag stays on every build until the code writes that ref anew. Any other text is
  a fresh claim and is held to whatever its face is now: another spelling of the same face (with its
  owner, or as `face N`), a ref to another face, or a build123d `Face`. So an agent that swaps the
  code's own ref for the viewer's canonical spelling also resets the check, on purpose.
- **Selected Faces.** A ref given as a build123d `Face` is never held to a kind: it is whatever the
  code's own selection picks on each build.
- **Precedence.** The check runs only where the annotation could stand on the new face. Where it
  couldn't (a diameter on a plane), that existing reason is the one given.

## AP242 export

`@step`, `cadgen export X.xbf X.step` and the viewer's **Export** menu write the AP242 file (schema
`AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF`) through OCCT's `STEPCAFControl_Writer` in
GD&T mode:

| cadgen | AP242 entities |
| --- | --- |
| datum | `DATUM` (identification = letter), `DATUM_FEATURE`, `SHAPE_ASPECT_RELATIONSHIP` |
| diameter | `DIMENSIONAL_SIZE('diameter')`, `DIMENSIONAL_CHARACTERISTIC_REPRESENTATION` → `SHAPE_DIMENSION_REPRESENTATION` (nominal, `POSITIVE_LENGTH_MEASURE`) |
| distance | `DIMENSIONAL_LOCATION('linear distance')` between two `SHAPE_ASPECT`s |
| basic distance | the same `DIMENSIONAL_LOCATION`, with no tolerance, its `SHAPE_DIMENSION_REPRESENTATION` holding `DESCRIPTIVE_REPRESENTATION_ITEM('dimensional note','theoretical')`: CAx-IF PMI Recommended Practices 4.1, 5.3, Table 7 (a type 1 dimension modifier). To a hole, the distance is to its axis (5.1.1: by default a location dimension to a feature with a diameter is from its center). Written by OCCT from an XCAF dimension description, and read back into one |
| plus-minus tolerance | `PLUS_MINUS_TOLERANCE` → `TOLERANCE_VALUE(lower, upper)` as `LENGTH_MEASURE_WITH_UNIT` |
| flatness | `FLATNESS_TOLERANCE` |
| position | `( GEOMETRIC_TOLERANCE GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE POSITION_TOLERANCE )`, `DATUM_SYSTEM` of ordered `DATUM_REFERENCE_COMPARTMENT`s, `TOLERANCE_ZONE` with `TOLERANCE_ZONE_FORM('cylindrical or circular')` |
| face link | `SHAPE_ASPECT` ← `GEOMETRIC_ITEM_SPECIFIC_USAGE` → `ADVANCED_FACE` (named with the engine's element name) |
| units | every measure refers to `SI_UNIT(.MILLI.,.METRE.)` |

OCCT 7.9.3's writer gets three of these records wrong. The export repairs them in its text
pass (`export/step.py`, `_pmi_records`); without the repairs, each one shows in the reader
with no OCCT in it:
1. Tolerance bounds are written untyped, `MEASURE_WITH_UNIT(0.2,#u)`, though `measure_value` is
   a select that needs its type. They are rewritten to the CAx-IF form,
   `LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.2),#u)`.
2. Every diametral zone gets a `RUNOUT_ZONE_DEFINITION` with 2 attributes where the schema
   declares 3, plus an unreferenced 0° `RUNOUT_ZONE_ORIENTATION`, on a tolerance that is not a
   runout. Both are dropped; the zone and its form stay.
3. **In a document with no dimension, every tolerance magnitude refers to a bare
   `SI_UNIT($,.METRE.)` while its value stays in mm.** A flatness of 0.05 mm is written as
   0.05 m, and OCCT reads it back as 50 mm. The cause is `STEPCAFControl_Writer::GetUnit` with
   the GD&T context unset: the writer only sets that context while writing dimensions. Such
   measures are pointed at the file's mm unit. `UnitsTest` covers this.

OCCT also accepts the lower deviation as a magnitude that its writer negates, so passing a
signed lower writes a wrong bound. The engine converts in both directions.

These exports are refused while a document holds PMI, because each one rebuilds the document
from a view and would carry no PMI: a posed STEP, a partial STEP (`--part`), and an xbf written
from a STEP or with `--part`. GLB, STL and 3MF carry no PMI, as they carry no B-rep.

### Exporting from the viewer

**Export** in the viewer's top-right toolbar (#568's export panel) lists the format as
**STEP (AP242)** and says that it "includes the built model's PMI and checks it in the exported
STEP". The PMI is the built document's: Quick Edit requests not yet applied to the code are not in
it. A STEP that would drop PMI (a posed or partial export, or an annotation linked to no geometry)
is unavailable, with the reason the engine gives.

**The check.** After writing the file, the export worker reads that exact STEP with the AP242 reader
(`cadgen/_internal/pmi_verification.py`, which uses no OCCT). It compares the file's annotations one
to one with the model's served PMI:
- values and units, both deviations' units included;
- datum letters and the frame's order, and the tolerance zone's form;
- the named face each annotation is on;
- for each dimension, whether it is basic: its `'theoretical'` note.

The result travels with the export job, with the SHA-256 of the bytes it checked, and the panel
shows it: "9/9 PMI annotations verified in STEP", or what failed. Several things make the check
incomplete, and it never reports success when they happen:
- an annotation missing from the file, or an extra one;
- a model with no PMI;
- a reader problem, or a schema that isn't AP242;
- a face name that appears more than once across the geometry;
- a repeated datum letter;
- an unsupported modifier.

It checks the supported semantic PMI. It does not check graphical callouts or whether the
requirements are complete for manufacturing, and the panel says that compatibility with a
factory's importer is untested.

**Reviewing before export.** The PMI section can filter to the selected geometry: **For
selection**, with **Show all PMI** to return to the whole list.
- A toleranced dimension shows its **Current limits** (nominal plus each signed deviation), from
  the saved document.
- A position lists its datum references in order, and each one lights that datum's face.
- A datum lists the tolerances that use it, under **Used by**.

## What was verified, and how

Each claim below is backed by an automated test in `test_pmi.py` unless marked otherwise.

- **Native document.** Values, units, datum letters and order, and each annotation's faces are
  read back from the saved xbf and checked against the document's own geometry: plane
  origin/normal and cylinder radius by face ordinal. The build's served structure equals the
  file's. A warm rebuild writes the same bytes. Editing the thickness and radius re-measures both
  nominals and keeps the tolerances. Editing only a tolerance rewrites it. Removing the
  annotations from the code removes them from the document.
- **Basic dimensions** (`BasicTest`).
  - The xbf holds `hole-from-B` 30 and `hole-from-C` 50: measured, `basic`, no tolerance, on the
    datum planes and the hole that the position tolerance names.
  - The STEP has both as `DIMENSIONAL_LOCATION` with the `'theoretical'` note and no
    `PLUS_MINUS_TOLERANCE`, read by the reader with no OCCT in it and by OCCT's reader.
  - Moving the hole re-measures them (35, 60).
  - An axis-to-axis basic between two holes measures 40. One whose axis crosses its plane is
    `invalid`.
  - A tolerance on a basic dimension, and a basic diameter, are refused.
  - Outside the suite, the `steputils` parse and the EXPRESS attribute-count check of the refreshed
    fixture found nothing malformed.
- **Broken references.** A name-based ref whose face is deleted goes `missing`: it is kept in the
  xbf with its tolerance and reported in the build report, and the STEP is refused. A diameter
  on a plane is `invalid`. A name that names two faces is `ambiguous`; this one is a unit test,
  because a natural model does not produce duplicate names. A shape replaced after annotation is
  listed as `unattached`.
- **OCCT round trip.** Reading the STEP with OCCT's XCAF reader in GD&T mode gives the same kinds,
  values and face refs as the xbf, by element name. This is OCCT reading its own writer, so it
  does **not** establish interoperability by itself.
- **Reader with no OCCT.** `cadgen/_internal/ap242_pmi_report.py` (standard library only; `scripts/pmi/ap242_pmi_report.py` runs it) parses Part 21 with its own
  tokenizer and walks AP242's PMI entities to recover each one's values, units, datum frame
  order, zone form, and the named `ADVANCED_FACE` and surface (plane or cylinder radius). The
  test asserts every value against the model. Outside the automated suite, during this PR:
  - The same report was produced with the third-party `steputils` 0.1 Part 21 parser
    (`--parser steputils`), with identical output.
  - With `--schema` pointed at the AP242 MIM long-form EXPRESS from the stepcode project
    (`data/ap242/242_mim_lf.exp`, ISO TC184/SC4/WG12 N11521), every PMI entity's explicit
    attribute count matched its declaration.

  That schema check is what found the malformed `RUNOUT_ZONE_DEFINITION`. The unit check found
  the metre unit.
- **Not verified.** No commercial CAD system, NIST's STEP File Analyzer or CAx-IF test-suite
  validator has read these files. The checks above are a reader written for this PR plus a
  generic third-party parser; they are not a certified AP242 validator. Foreign STEP files in
  inch or metre units are not tested: OCCT converts GD&T values into the document's mm on
  reading, but this PR does not test it. ifcopenshell 0.8's EXPRESS loader could not load the
  AP242 long form, so it is not used.

## Downstream testing (DFM engine)

1. Read `docs/pmi/pmi_plate.step` with your AP242 reader. You should find, in mm:
   - `DATUM` A, B and C on the bottom, front and left planar faces;
   - a `DIMENSIONAL_LOCATION` 10 with `TOLERANCE_VALUE(-0.2, 0.2)` between the bottom and top
     faces;
   - a `DIMENSIONAL_SIZE` 'diameter' 10 with `(0, 0.1)` on the cylindrical face of radius 5;
   - a `FLATNESS_TOLERANCE` 0.05 on the top face;
   - a `POSITION_TOLERANCE` 0.1 with a diametral zone and the datum system A, B, C, in that
     order, on the hole;
   - two basic `DIMENSIONAL_LOCATION`s with no tolerance, each carrying
     `DESCRIPTIVE_REPRESENTATION_ITEM('dimensional note','theoretical')`: 30 from the front plane (B)
     to the hole, and 50 from the left plane (C) to the hole.

   [`pmi_plate.report.json`](pmi_plate.report.json) lists the record numbers and face names.
2. Compare with our reader:
   ```bash
   python3 packages/cadgen/src/cadgen/_internal/ap242_pmi_report.py docs/pmi/pmi_plate.step
   ```
   The reader is one standard-library file, so it runs without cadgen installed. With cadgen,
   `python -m cadgen._internal.ap242_pmi_report` is the same.
   Add `--parser steputils` once `pip install steputils` is done, and
   `--schema path/to/242_mim_lf.exp` to check attribute counts.
3. Make your own: edit `models/examples/src/pmi_plate.py` and run it from `models/examples/src`
   with a cadgen checkout's environment (`python pmi_plate.py`). The STEP lands in
   `models/examples/XBF/pmi_plate.step`. Print what the engine thinks it wrote:
   ```bash
   python -c "import json; from cadgen.engine import pmi; print(json.dumps(pmi.read('../XBF/pmi_plate.step'), indent=1))"
   ```
4. If your reader disagrees with the report, the report's `problems` list is the first place to
   look.

## Limitations (explicit)

- **Scope.** Datums on plane or cylinder faces; diameter and linear-distance dimensions with
  plus-minus tolerances; basic distances (plane to plane, plane to axis, axis to axis); flatness; position with up to 3 ordered datums and a diametral zone
  (`diameter_zone=False` writes a plain zone, not covered by a test). Everything else is refused by name with `PMIUnsupported` and never approximated:
  - other characteristics (perpendicularity, profile, runout and the rest);
  - radius and angle dimensions;
  - limits and fits, general tolerances;
  - material condition modifiers (Ⓜ/Ⓛ) and datum modifiers;
  - a basic dimension other than a distance (a basic diameter or angle), and reference (auxiliary) dimensions;
  - datum targets, composite frames and all-around;
  - assembly-level PMI.
- **Basic dimensions are separate annotations.** As in AP242, nothing links a basic dimension to
  the tolerance it locates. A reader pairs them through their shared faces: the hole and the
  frame's datums.
- **No identifiers in the STEP.** OCCT writes every `SHAPE_ASPECT`, `DATUM` name and tolerance
  name empty, ignoring XCAF's semantic name. The author's ids live in the xbf only. In a STEP an
  annotation is identified by its entity, values and face (the face carries the engine's element
  name).
- **No graphical PMI.** Presentation (`pmi.place`) is stored but never exported. This PR writes no
  `DRAUGHTING_CALLOUT` and no polyline or tessellated presentation.
- **One position per datum.** A datum must hold the same place in every frame that names it
  (XCAF's model); a different place is refused.
- **Exports that rebuild the document are refused:** posed or partial STEP, and xbf written
  from STEP or `--part`.
- **Whole conversion.** A warm build of a document holding PMI converts it whole instead of
  patching. The cost is the conversion; the bytes are the same.
- **Repairs depend on OCCT 7.9.3's output.** The three repairs target exact record forms that
  this OCCT version writes. A different OCCT may write them differently; the independent reader
  test would catch that.
- **OCCT's reader drops datums no tolerance names.** Its XCAF reader finds datums only through
  the tolerances that name them. Reading a STEP back with `pmi.read`, a datum that no tolerance
  names is missing, though the `DATUM` is in the file. The reader with no OCCT in it finds it
  (`AssemblyTest`).
- **OCCT's writer silently drops some tolerances.** A perpendicularity with no datum is one
  example. Perpendicularity isn't exposed, but this is noted for whoever adds characteristics.
