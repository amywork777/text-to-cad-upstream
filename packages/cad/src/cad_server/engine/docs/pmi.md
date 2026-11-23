# PMI

A page of [the engine's documentation](../README.md). A name in bold in parentheses, such as (**Kinematics**), is another page or a named paragraph of one: the index says which.

A part's manufacturing requirements, on its own faces (`pmi.py`): datums, measured dimensions
with explicit tolerances, basic dimensions and geometric tolerances, a general profile for every
face nothing else controls, numbered notes and named views -- a model-based definition, authored
in the model and kept in its document. The functions that author them are `cad.build123d`'s, beside
the mechanism's (the root and `cad.engine` hold none of them): AP242's semantic PMI, which a STEP
carries with each annotation's placement (AP242's presentation of it), and the notes and named
views around it, which the xbf keeps and a STEP does not. Those that write an AP242 entity are named after it; those that write no entity of their
own keep plain names: `limits` (a dimension's 'lower limit' and 'upper limit' values),
`general_profile`, `note` and `view` (with `camera` and `section`), and `place`. `pmi.read` returns them as the structure's
`pmi`, the contract a viewer and a downstream reader build on, served with each part's views
(`pmi_views`) and coverage (`pmi_coverage`):

```python
from cad.build123d import (annotate, datum, dimensional_location, dimensional_size, flatness_tolerance, general_profile,
                          limits, note, place, plus_minus_tolerance, position_tolerance, section,
                          surface_profile_tolerance, view)
from my_project.notes import NOTES  # the project's notes by name, its own module: text-to-cad ships none

# bottom, top, front, left: the plate's faces; hole: its bore, on the origin. Values illustrative.
return annotate(body,
    datum("A", bottom), datum("B", front), datum("C", left),
    dimensional_location("thickness", bottom, top, tolerance=plus_minus_tolerance(0.2)),
    dimensional_size("hole", hole, tolerance=limits(10.0, 10.05)),   # its least and greatest size
    flatness_tolerance("top-flat", top, 0.05),
    position_tolerance("hole-pos", hole, 0.1, datums=["A", "B", "C"]),
    dimensional_location("hole-from-B", front, hole, basic=True),  # the true position: basic, no tolerance
    dimensional_location("hole-from-C", left, hole, basic=True),
    surface_profile_tolerance("B-and-C", [front, left], 0.1, datums=["A"]),  # one requirement on both faces
    general_profile("general", 0.5, datums=["A", "B", "C"]),       # Note 1: every face left over
    note("edges", NOTES["edges"]),                                 # a general note: Note 2
    note("mask", NOTES["primer-mask"], faces=[hole], annotations=["hole"]),  # a flag note
    view("A-A", camera="front", shows=["hole", "hole-pos", "mask"],
         section=section("y", 0, invert=True),  # keeps y > 0: its cut faces the front
         place={"hole": place((5, 0, 0), (15, 0, 10))}),
    view("iso", camera="iso"))                                     # shows everything
```

- **Authoring.** `annotate` takes one part (an annotated assembly is refused: annotate its
  parts) and returns it; a `Face` given as a ref is numbered against it at once (a face of another
  shape is refused, by its annotation's id), so annotations
  given to a shape a later operation replaces never reach the result, so the build fails, naming
  them (`pmi.unattached`): no file would carry them. Its body's run, and a @memo function's that
  annotated, keeps the annotations it gave (`memo.annotated`), so a replay of it gives them again
  and fails as its run did, or passes with the same PMI. Each annotation is a dict as its function
  makes it, its keys closed (law 16): `annotate` refuses one of another kind, a key beyond its
  function's or one missing, naming the set, and checks a tolerance and a presentation again as
  `plus_minus_tolerance`, `limits` and `place` check theirs. Ids are the author's, unique on a part, a note's with the rest; a datum's id
  is its letter, and a datum holds one place in every frame that names it (XCAF holds one
  position per datum). A ref is a `Face` or a ref of the grammar (**References**). A nominal is
  measured from the geometry: a cylinder's diameter, or a distance between parallel planes, from
  a plane to a hole's axis, or between parallel axes. A tolerance is held only where the code
  gives one: `plus_minus_tolerance(upper, lower=None)`, signed deviations, or `limits(lower,
  upper)`, the least and the greatest size, absolute (`limits(10.0, 10.05)` is 10.00–10.05). A
  basic dimension (`dimensional_location(..., basic=True)`) has none, and a tolerance on one is
  refused; a diameter is never basic. `presentation=place(anchor, offset)` (millimetres, the
  part's frame) is where a viewer draws the callout, never a requirement. A STEP draws it there:
  its text point, an annotation plane through it, and a leader from the anchor (a callout named by
  the id), which OCCT reads back as the same place; one with no offset has no leader to draw and is
  written without one.
- **Surface profiles.** `surface_profile_tolerance(id, refs, value, datums=())` is one
  requirement on a face or on a list of faces, of any kind, to up to three datums or none; its
  zone is a width about the true profile (no diametral one), and a profile on no face is refused.
  The general profile (`general_profile(id, value, datums=())`, one per part: a second is refused by
  name) is ASME Y14.5's "unless otherwise noted, all surfaces": a surface profile of every face of
  the part that nothing else controls, the code naming none of them. A face is otherwise
  controlled when it has a size or location requirement of its own
  (`pmi.otherwise_controlled(entries)`, over structure entries): a ref of a plus-minus or limits
  dimension, or the feature of a position or of a profile not general (a basic dimension locates
  that feature, and leaves the datum it starts from to it). A form control alone (flatness) and a
  datum leave a face to it, but the datum features it names are controlled on their own and left
  out of it: no face is profiled relative to itself. It is not XCAF's `All_Over` modifier, which
  in ASME means every surface beside any other requirement.
- **General tolerances.** `general_tolerance(id, standard)` states ISO 2768's general
  tolerances, as a drawing does: `"ISO 2768-m"` (part 1's class, f, m, c or v, for every size
  nothing else tolerances), or `"ISO 2768-mK"` with part 2's class (H, K or L) for general
  geometrical tolerances; another standard is refused by name (`PMIUnsupported`). It is a general
  note ("General tolerances ISO 2768-mK", numbered as any note is, its `note` block's
  `general_tolerance` the standard) that covers every face nothing else does, datum features too,
  and the one note a STEP carries: the CAx-IF PMI practice's `'default tolerances'` property of
  the part's `PRODUCT_DEFINITION_SHAPE`, its `'tolerance class'` the standard, which the export
  check matches as any requirement. One per part.
- **Notes.** `note(id, text, faces=(), annotations=())` says what to do in the code's words:
  a general note where it names no face and no annotation, a flag note on its faces (of any
  kind) and on the annotations of the same `annotate` call it names by id (an id no annotation of
  the call has, or a note's, is refused by name, as is an empty text). Notes are numbered per
  part: the general profile is Note 1 where the part has one, then each note in the order the
  code gives them. The text is the code's: a project keeps its notes in a module of its own
  (text-to-cad ships no note text).
- **Views.** `view(name, camera=..., shows=None, section=None, place=None, label=None)` is a
  named view of the part, given among its annotations, seen orthographically down `camera` (as a
  still draws it; a viewer keeps the person's projection): a preset's name (`iso`, `front`,
  `back`, `left`, `right`, `top`, `bottom`: `cad <type> snapshot --camera`'s, one table,
  `render/presets.py`) or `camera(direction, up)`, whose `direction` means what a preset's
  does, the way from the part toward the eye (`front` is `(0, -1, 0)`), both made unit vectors
  (an `up` along the direction is refused). Where it has one, it is cut by
  `section=section(axis, at, invert=False)`, the viewer's Clip: one plane across `x`, `y` or
  `z` at `at`, keeping the lower side, `invert` the upper (a front view, its eye toward -y, sees
  its cut where it keeps the far side, y above `at`: `invert=True`). It shows the ids of the same
  call `shows` names, annotations and notes (None: every one, as an iso view does), and draws
  each id it `place`s (`{id: place(...)}`) there in that view, as its own presentation says
  elsewhere. All in the part's frame. A view's name is unique among its part's views; an id the
  call does not have, and a placement of one the view does not show, are refused by name. A view
  is no annotation: the report counts none and a note names none. `cad <type> snapshot --view NAME`
  draws it as the viewer applies it (**The viewer and the snapshot**).
- **Resolution.** Each build resolves every ref against the part as built: `ok`, `missing` (it
  names no face; the problem gives the name's atom now, where there is one), `ambiguous`
  (several: `candidates` lists them) or `invalid` (a face the annotation cannot stand on: a
  diameter on a plane, a flatness on a cylinder, a datum on neither, a face a profile names
  twice). A geometric tolerance whose frame names a datum that is not `ok` takes the worst such
  datum's status, its problem naming the datum (`datum A is missing: ...`): it is measured from
  nothing the part has, so it covers no face. An annotation that is not `ok` is kept in the
  document with its values, linked to no geometry, and a STEP export refuses to drop it, naming
  each one. A general profile's faces are
  resolved with the rest: every face of the part as built that the part's other `ok` annotations
  leave, but the datum features it names, from this build's annotations and geometry alone. It
  has no ref to break, so it is `ok` (`invalid` where its frame names a datum the part lacks, then
  covering nothing); one that covers no face is `ok`, linked to nothing, and no STEP refuses it. A
  note's faces resolve as any ref does: one whose face an edit removed keeps its number and its
  text and is `missing` (a note with no face is `ok`); the build reports it, and no STEP refuses
  it. A build resolves against its own geometry alone and reads nothing of an earlier one (law 5:
  a declared xbf is never a source): a ref written as text names whatever face holds that name
  now, measured as it now is. The build report's `pmi` is `{"annotations", "problems"}`, with
  `"coverage"` where there is any, each logged.
- **Suggestions.** What a part's requirements leave unsaid is asked, each with the answer a
  standard gives (`pmi.suggestions(entries, faces, material=)`, pure; served in `pmi_coverage`
  and logged by the build as `pmi: PART: ask: QUESTION Suggest ANSWER (WHY)`), never applied: the
  part's material where it has none; datum A on its largest flat face where it has no datum; a
  general requirement (`general_tolerance("general", "ISO 2768-mK")`) where faces are uncovered and
  none is given; and each hole no size is on (faces going all the way round an axis, so a slot's
  round end is none), by its diameter, from the tables in `pmi.py`: an ISO
  273 clearance hole (its series' H class, ISO 286, and a position by the floating-fastener formula,
  hole less fastener), a coarse thread's tap drill (a thread note, 6H, and a position by the
  fixed-fastener formula, half the mating medium clearance hole less the fastener), else a bore
  (H7). Each is `{"kind", "faces", "question", "answer", "why"}`, its answer the call that says it
  on the face's canonical ref; the agent asks them in the chat (the viewer lists none).
- **Coverage.** Every face of a part is to have a requirement, most of them through its general
  profile, and what is not is said (`pmi.coverage(entries, faces)`, pure, of one part's
  structure entries and the canonical refs of all its faces). A face is covered by an `ok`
  toleranced dimension (plus-minus or limits) or geometric tolerance whose refs name it, the
  general profile by the faces it covers, and every face by a general tolerance (ISO 2768); another system's annotation listed `unsupported` covers
  its faces as any does, but a datum or a basic dimension. A basic dimension covers nothing: it is
  no requirement, but locates the feature a position or a profile controls, which covers it. A
  datum and a note cover nothing, and the datum features a general profile names are left out of
  it: such a face (a datum a basic dimension starts from too) is uncovered until it has a control
  of its own (datum A's flatness). The conflicts, each `{"kind", "ids", "problem"}`, in this
  order: `unused_datum`, a datum no tolerance's frame names; `unlinked_note`, a flag note every
  face and annotation of which is broken (one link that holds keeps it linked; a general note has
  none to break); `apart`, two toleranced dimensions of one type on the same faces whose zones do not meet; and
  `form_over_profile`, a flatness wider than a surface profile on its face, its own or the
  general one. It is derived where the document is served, never held: the structure's
  `pmi_coverage` is `[{"part", "uncovered": [refs, sorted], "conflicts": [...]}]`, one per part
  carrying PMI (a part given views alone carries none), served wherever `pmi` is;
  the build report's `coverage` is the same of each part with something to say, by its name,
  each logged as `warning: pmi: PART: N faces have no requirement: REF, ...` and `warning: pmi:
  PART: IDS: PROBLEM`. It warns: it never fails a build.
- **The document** holds what the code says and what this build's geometry resolves, and
  nothing of a previous build: the same code and closure make the same xbf whatever was built
  before. The values, units, kinds and face links are XCAF's `XCAFDimTolObjects` on the GD&T
  tool, linked to the faces' sub-shape labels (the STEP writer's input); beside each, a
  `TDF_Reference` to its part's shape label and one engine attribute (JSON, schema
  `cadgen.pmi/1`) holding what XCAF has no place for: the id, the label, the kind, the refs as
  the code wrote them, the presentation, and a general profile's flag (`"general": true`, its
  faces linked in XCAF, none written in the refs); an unlinked annotation's values too, since
  XCAF gives values meaning only through geometry. The id and the kind are also XCAF's (the
  object's semantic name and its type). No status and no problem are held: they are derived
  where the document is served (`pmi.records_of_document`), from the refs as written, the
  document's names and geometry and each kind's faces, as the build derives them, a general
  profile's faces with them (kinematics derives its loop where it serves its block). A note is an
  XCAF comment in the notes tool (`XCAFDoc_NotesTool`), by one fixed user (`cadgen`) with no
  timestamp, so the same code makes the same bytes, with the same reference and engine attribute
  beside it (the id, label, presentation, refs and the ids it names as written; its text is
  XCAF's). A general note is attached to its part's shape label; a flag note, where it is `ok`,
  to each of its faces (`AddNoteToSubshape`, the sub-shape index the face's ordinal in its part's
  face map), and to the GD&T label of each annotation it names. A view is an XCAF view in the views tool (`XCAFDoc_ViewTool`):
  parallel, its view direction the served direction reversed (XCAF's is the one looked along),
  its up, its eye the part's box centre moved toward the eye by the box's diagonal, its window
  that diagonal and its zoom 1; linked to its part's shape label and the GD&T labels it shows,
  its section an XCAF clipping plane (`XCAFDoc_ClippingPlaneTool`) named for the view, its normal
  into the half the Clip keeps, capped; beside it the same reference and a engine attribute
  (`kind` `view`, the name, label, camera as written, shows, section and placements), which the
  structure is served from. The notes a view shows are that attribute's alone: OCCT's `SetView`
  files a view's notes under its clipping-plane link. A document without PMI holds nothing new.
  A document holding PMI is converted whole on a warm build (GD&T labels link the sub-shape
  labels a patch remakes).
- **An entry** of `pmi.read` (an xbf or a STEP): `id`, `kind` (`datum`, `dimension`,
  `geometric_tolerance`, `note`, or `unsupported`), `label`, `status`, `problem`, `part` (the
  structure's prototype index, linked or
  not), `refs` (each `role`, the canonical `ref` when resolved, `written`, `status`,
  `candidates`, `problem`), `presentation`, `xcaf_type`, and one of `datum` (`letter`),
  `dimension` (`type` `diameter` or `distance`, `basic`, `nominal` `{value, unit, source}`,
  `tolerance`: `{type: "plus_minus", upper, lower}`, `{type: "limits", lower, upper}` or null),
  `geometric_tolerance` (`characteristic` `flatness`, `position` or `surface_profile`, `value`,
  `unit`, `zone`, `datums` in order, and `general`, false for a tolerance on the faces the code
  names, true for the part's general profile) or `note` (`number`, `text`, `general`: it names no
  face and no annotation, and the `annotations` it names; its `xcaf_type`
  `XCAFDoc_NoteComment`). A surface profile's `refs` are its faces, each of role `feature`; a
  general profile's are the faces it covers this build, in the part's order, each `written` null
  and `status` `ok`, and none where it covers none; a note's are its faces, each of role
  `feature`. A nominal's `source` is `geometry`, measured, where the code made the annotation,
  and `file` where another system did. XCAF holds limits in place of a nominal (its value is then
  their midpoint): a nominal of the code's beside limits is measured where the document is read,
  and a dimension read from a file with limits has none (`nominal` is null): the file states
  limits, and the midpoint XCAF rebuilds is no fact of it. Beside `pmi`, the structure's
  `pmi_views` lists each part's views, by part, in the code's order:
  `{"part", "name", "label", "camera": {"preset", "direction", "up", "projection":
  "orthographic"}, "section": {"axis", "at", "invert"} or null, "shows": [ids] or null (every
  one), "place": {id: {"anchor", "offset"}}}`, the camera's direction and up unit vectors, the
  direction from the part toward the eye (a preset's from the stills' table, `preset` its name;
  null for `camera`'s), and all of it in the part's frame, which a viewer places through the
  part's placement (empty where none); served wherever `pmi` is, as `pmi_coverage` is
  (**Coverage**, read by the agent: the viewer lists none of it).
- **A document another system wrote** (a vendor's STEP, or an xbf converted from one) lists its
  GD&T as XCAF reads it, and never blocks a conversion or an export. What this does not hold
  whole is `unsupported`, with its `xcaf_type`, its values and a `reason`: another
  characteristic or dimension type, a fit, a qualifier, modifiers, limits beside any of these or
  on a basic dimension (XCAF holds limits or deviations, never both), a zone modifier, a maximum
  value, a surface profile's diametral zone, a datum target or modified datum, a note other than
  a basic one's, and a link to an edge or a point (kept, its refs spelled as the grammar spells
  an edge or a vertex, never drawn). A note or a view another system wrote is not read. It is
  listed, never read as less than it says (law 13: left out with a word, never patched). An xbf
  of such a STEP copies its GD&T as read (`pmi.copy`), each object linked to the same elements.

Verified, and nothing else written: datums on planes and cylinders; diameter and linear-distance
dimensions with plus-minus tolerances or limits; basic distances, marked 'theoretical' as AP242
marks them (CAx-IF PMI Recommended Practices 5.3, a dimensional note on the dimension's
representation); flatness; position with an ordered datum frame of up to three and a diametral
zone; a surface profile on one face or several, of any kind, with a frame of up to three datums
or none; a part's general profile, on the faces nothing else controls; and, in the xbf alone,
general and flag notes and a part's named views. Every other characteristic,
dimension type, tolerance form (fits, modifiers), a basic diameter or angle, and assembly-level
PMI is refused by name (`PMIUnsupported`), never approximated.

**The STEP.** A STEP of a document holding PMI -- `export.translate`'s, whether `cad <type> export`
asks for it or a decorator declares it -- carries it as AP242's semantic PMI: `DATUM` and
`DATUM_FEATURE`; `DIMENSIONAL_SIZE('diameter')` and `DIMENSIONAL_LOCATION('linear distance')`
with their `SHAPE_DIMENSION_REPRESENTATION` and `PLUS_MINUS_TOLERANCE`, or, given limits, the
representation's `'lower limit'` and `'upper limit'` items (CAx-IF's) and no tolerance, its
nominal value their midpoint (XCAF holds the limits alone); `FLATNESS_TOLERANCE`;
`POSITION_TOLERANCE` with its `DATUM_SYSTEM` of ordered compartments and a
`TOLERANCE_ZONE_FORM('cylindrical or circular')`; `SURFACE_PROFILE_TOLERANCE`, with its
`DATUM_SYSTEM` where it names datums (then the complex entity of
`GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE`); each on its `ADVANCED_FACE` (named with the
element's name) through a `GEOMETRIC_ITEM_SPECIFIC_USAGE` of its `SHAPE_ASPECT` -- a tolerance
on several faces on a `COMPOSITE_SHAPE_ASPECT` that a `SHAPE_ASPECT_RELATIONSHIP` per face
relates to that face's aspect -- every measure in millimetres. A general profile is a
`SURFACE_PROFILE_TOLERANCE` on exactly the faces it covers, so a reader gets an explicit face set
(the file says nothing of "general"); one that covers no face is written as nothing. A STEP
carries no annotation id (the writer leaves every name empty), no graphical PMI, no note and no
view (OCCT's writer writes neither): **notes and views stay in the document** and
its xbf, and no STEP is refused for one. No export poses a document or takes a part out of it (law 22): a posed
file and a part's own file are models of their own. An xbf that `export.translate` writes of a
document this engine made and holds (`cad model export ID out.xbf`, the viewer's XBF of a held model)
is that document's own bytes, the ones its declared `@xbf` holds, and carries its PMI whole
(`export/tree.py`); only a document held without its XCAF document is made again from its view,
which carries none. Every export that would not carry the PMI the
code made whole is refused by name (`pmi.refuse_dropped`, in `export.translate`: a STEP held to
the GD&T, an xbf made again to the notes and the views as well, a part given views alone
included, each named, a STEP's by each annotation's id and the ref
that holds no geometry: `a STEP would drop PMI linked to no geometry: ID (ref 'REF': WHY). Fix the
refs in the model, or remove the annotations`); one of a document another system wrote is
written, and what it leaves out is said (`pmi.dropped`: `warning: pmi: FILE: ID is not carried
whole: WHY` in the export's log). OCCT's writer gets four PMI records wrong, and the STEP export
puts them right (`export/step.py`, `_pmi_records`; found and checked by the AP242 reader below):
a plus-minus tolerance's bounds untyped (`MEASURE_WITH_UNIT(0.2,#u)`); a two-attribute
`RUNOUT_ZONE_DEFINITION` beside every diametral zone; in a document with no dimension, every
tolerance magnitude in a bare metre while its value is millimetres; and a `DATUM_SYSTEM` per
tolerance, where each frame is written once. OCCT's own reader finds a
datum only through a tolerance that names it.

**The check in the written file.** Every STEP written of a document that holds PMI a STEP
carries is checked in the file (`pmi.checked`): a build's declared one, `cad
<type> export`'s and `<type>.export()`'s (the worker's `export`), and the viewer's, which offers STEP as it
offers every format of the document's kind, nothing inspected first (**Viewer exports**), one the
PMI refuses (above) failing with its reason. After writing the file the engine reads it back with
`cad.engine.export.ap242` -- a Part 21 reader of AP242's PMI entities with no OCCT in it -- and matches
every entry but the notes, which it neither expects nor counts (nor the views, which are no
entries), to one record of the file by face name, kind, values, units, datum order, zone and a
basic dimension's note (`ap242.check`), each part to its own product's records alone: the reader
gives each record the product it, its faces and every datum its frame names are of (its shape
aspects' `of_shape`, the faces' representation's product), and a part is its product by its name,
so face names and datum letters need be unique only within a part. Each face is held to the
document's own face of that name too (`pmi.step_surfaces`, in the part's frame, where the STEP
writes it): a plane by its normal (either sense) and its offset, a cylinder by its radius and its
axis, within a millionth of the part's size and 1e-9 of parallel, so a right name on the wrong
surface matches nothing (a face of another kind, a profile's, by its name); a limit dimension by
its two limits, in its nominal's unit (millimetres where it has none, as a file's has not), the
file's nominal value their midpoint; a tolerance on several faces by the same faces, in any order;
a general profile that covers no face by no record, none being left over. The result,
`{"matched", "total", "problems", "sha256"}` (the digest of the bytes checked), is the file's
`pmiVerification`: on the build report's `files` row, the export's answer, and the viewer's export
job. Every file is checked staged, before it lands (`export.translate`'s `check`), whoever asked
for it: for a document the code made, a check that finds any problem refuses the file (`FILE not
written: the PMI in the STEP written does not match the model's document, or could not be checked
against it (M of N matched): ...`), so no file is written and one there keeps its bytes (law 17),
a build's other declared files, its xbf too, with it (`atomic_replace.together`):
a record that does not match, and a check that could not be made alike -- a file the reader cannot
read, an entity it does not read, a schema other than AP242, a face name a part's geometry holds
twice, a datum letter a part's records repeat, two products of one name. Nothing is guessed. The
viewer's refusal is its export job's error, the person's toast. OCCT's writer writes one `DATUM`
of a letter per file, the frames of every part on it: two parts defining the same letter verify
neither, and the check says so (`Datum A is defined on 2 parts: ...`). A STEP of a document another
system wrote is checked of what it carries (each annotation `ok`; the rest are said as left out),
and refused alike where every face those are on carries a name -- a STEP this engine wrote, read
back, and its xbf -- so a round trip carries all it read or writes nothing. OCCT's STEP reader
gives each frame that names a datum a label of its own; a document read lists each datum once (by
its letter and the faces it is on). One whose faces carry no names (`face 7`) verifies nothing: it
is written, and what the check found is warned of in the log, `warning: pmi: FILE: the PMI in the
written file is not verified (M of N matched): ...`.
