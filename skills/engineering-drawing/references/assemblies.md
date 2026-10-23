# Assembly drawings

```python
from cadgen.eng_drawing import eng_drawing, parts_list, assembly_sheets
```

An assembly is a drawing set: a general arrangement keyed to a parts list,
then a sheet per part, each one refined like any sheet:

```python
@eng_drawing(out="../PDF/rig_drawing.pdf")
def rig_drawing():
    parts = parts_list(cadgen.read_scene(Path(__file__).parent / "../STEP/rig.step"))
    parts.merge("eye:upper", "eye:lower")                                # one part, named twice
    parts.set("base_plate", material="6061-T6", part_number="RIG-101")   # stated, never guessed
    sheets = assembly_sheets(parts, title="RIG", part_number="RIG-100", general_tolerance="ISO 2768-m")
    top, front, right, iso = sheets.part("base_plate").views
    front.section("A")
    return sheets
```

## `parts_list(source)`

`source` is a scene from `cadgen.read_scene(path)` or a live build123d
`Compound` made with `children=`. Returns a `PartsList`: one `Item` per
distinct part, numbered in the order the assembly first holds them.
Occurrences are one part when they have the same name, the same colour and the
same geometry (a shared STEP prototype, one shape object, or an exact
translated copy). Anything less stays apart: a saved STEP shares one prototype
between any parts of identical geometry (a steel spacer and a brass one), a
label's detail often names a finish (`piston_rod:chrome`), and mirror images
have identical volumes. `parts.twins` lists the item pairs that share a shape
under different names, and the script prints them.

- `parts[3]`, `parts["coil_spring"]`: an item by number, label or the label's
  name before the colon; an unknown or ambiguous key is refused with the list.
- `parts.set(key, description=..., part_number=..., material=...)`: what the
  model cannot carry; chains. Nothing else is accepted. It may follow
  `assembly_sheets`: each part's sheet reads its item when it renders.
- `parts.merge(*keys, description=None)`: list items as one part, after
  checking their geometry is the same; a different shape is refused. The first
  keeps its place, later items are numbered again, and the description is the
  label segments they share unless given. Merge before drawing from the list.
- `item.number`, `.description` (the label read out: `piston_rod:chrome` is
  `PISTON ROD, CHROME`), `.quantity`, `.part_number`, `.material`, `.labels`,
  `.refs` (occurrence refs, `#o1.2`), `.shape` (one occurrence in its own
  frame), `.occurrences` (each placed in the assembly), `.prototypes` (the STEP
  prototypes they share).
- `parts.assembly`: the whole assembly, placed, for the GA's views.

## `assembly_sheets(parts, title=..., part_number="", revision="A", size="A3", author="", date="", projection="THIRD ANGLE", ink="mono", notes=(), general_tolerance="", revisions=())`

Returns the set as a list of `Sheet`s: the general arrangement (front view, the
one of top and right showing more, an isometric; no hidden lines; overall
sizes; balloons; the parts list, continued on further sheets past 16
items on A3), then one sheet per item. A GA that does not fit `size` beside its
parts list at 1:50 or larger is refused, naming a larger size. A part's sheet
draws `item.shape` in three views and an isometric on a sheet that chooses its
own size and scale (`Sheet(size=None, scale=None)`), states its overall sizes,
calls out the holes and slots each view looks down, and is titled with the
item's description over `ITEM n (QTY q) OF <title>`. Every sheet carries the drawing number, revision, author
and date; `notes` and `revisions` go on the GA, `general_tolerance` on the part
sheets. `sheets.part(key)` is an item's sheet; `sheets.parts` the list.

## `sheet.parts_list(parts, first=1, last=None)`

Draws `parts` as the parts list, standing on the title block and as wide as it
(ISO 7573, ASME Y14.34): ITEM, QTY, DESCRIPTION, PART NO., MATERIAL, the header
against the block and item 1 above it. `first`/`last` draw a run of a list too
long for one sheet; one that does not fit is refused, naming where to split it,
and each run of a split list says on which sheet it continues. The views and
any detail keep clear of it; a hand-placed view over it, or a note running
under it, is refused.

## `view.balloons(parts)`

Balloon every item of `parts` the view shows, on a view of `parts.assembly`.
Each leader ends in a dot on a point of the part the view sees. The balloons
stand in a column each side of a tall view (rows above and below a wide one),
may run the frame's height clear of other views, the title block and the parts
list, keep their leaders uncrossed and off dimension text, and stand outside
any hole callouts. An item already ballooned in an earlier view of the sheet is
skipped, so balloon the views in order of preference. A column the paper cannot
hold is refused, naming a larger sheet or scale. Not on a section or a detail.

## What the script prints

| Line | Means |
| --- | --- |
| `incomplete: item 4 (CORE) has no balloon ...` | no ballooned view shows that part; balloon a view from a side where it shows |
| `incomplete: the parts list leaves out items 18, 19 ...` | draw the rest with `parts_list(parts, first=18)` on another sheet |
| `note ... runs under the parts list` / `view is drawn over the parts list` | shorten the note, move the view |
| `note: items 1 and 10 (... and ...) are the same shape under different names ...` | `parts.merge(1, 10)` lists them as one part, if they are one |
| `front.balloons(): 9 balloons do not fit on the right of the front view on A3 ...` | a larger `size=`, or balloon some items on another view (a refusal) |
| `the general arrangement does not fit A3 beside its parts list ...` | give `assembly_sheets()` a larger `size=` (a refusal) |
