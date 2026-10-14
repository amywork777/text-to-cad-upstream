# The job file

One JSON object, passed as `--job part.cam.json` (or inline: `--job '{...}'`). This page is the keys
every job shares; each operation adds its own keys, on its reference page. Every key is checked:
an unknown key or value is refused with a sentence naming the allowed ones, and nothing is written.

```json
{
  "name": "bracket",
  "machine": {"kind": "mill", "post": "grbl", "travel_mm": [300, 200, 80], "max_rpm": 24000},
  "material": "aluminum-6061",
  "stock": {"kind": "box", "margin_mm": [2, 2, 1]},
  "tools": [
    {"id": "T1", "type": "flat", "diameter_mm": 6, "flutes": 3, "flute_length_mm": 20, "stickout_mm": 30}
  ],
  "setups": [
    {"id": "top", "orientation": "+Z", "origin": "stock-top-center",
     "operations": [{"op": "face", "tool": "T1"}]}
  ]
}
```

| key | meaning |
| --- | --- |
| `name` | the job's name, for the posted files' headers |
| `machine` | the machine and its controller ([Machine](#machine)); required |
| `material` | a feeds-table name or an object ([Material](#material)); required |
| `stock` | what the part is cut from ([Stock](#stock)); required |
| `tools` | the tool list ([Tools](#tools)) |
| `setups` | one per way the part is held, in order ([Setups](#setups)); required |
| `tolerance_mm` | how closely paths follow the part (default 0.01) |
| `coolant` | `off`, `flood`, `mist` or `air` for every operation that names none |

## Machine

| key | meaning |
| --- | --- |
| `kind` | `mill` (3-axis), `mill4` (plus an A axis about X), `mill5` (two rotary axes), `router`, `lathe`, `laser`, `plasma`, `waterjet`, `wire_edm` |
| `post` | the controller's dialect ([posts.md](posts.md)); required, never guessed: a dialect read by the wrong controller moves the machine wrongly. Ask the user which controller runs the machine |
| `name` | the machine's name, for the headers |
| `travel_mm` | axis travel `[x, y, z]` (a lathe `[x, z]`, a laser, plasma or waterjet `[x, y]` or `[x, y, z]`); with it, the `travel` check runs |
| `max_rpm`, `max_feed_mm_min` | limits: speeds and feeds are clamped to them (the `limits` warning says where) |
| `rapid_mm_min` | rapid traverse rate, for the cycle time (default per kind) |
| `tool_change_s` | seconds per tool change, for the cycle time |
| `spindle_spinup_s` | seconds the spindle takes to reach speed (0 to 60): every post dwells that long after each spindle start, and the cycle time counts it (left out: GRBL waits 3 s, the others none) |
| `kinematics` | a `mill5`'s: `ac_trunnion` (A tilts the table about X, C turns it) or `bc_head` (B tilts the head, C turns the table) |
| `rotary_limits_deg` | rotary travel: `{"a": [-120, 30], "c": [-360, 360]}` |
| `diameter_mode` | a lathe's X words are diameters (default `true`) or radii |

The cutting machines take their process keys (power, amps, quality) on [cutting.md](cutting.md).

## Material

A name from the feeds table:

`aluminum-6061`, `aluminum-7075`, `steel-1018`, `stainless-304`, `tool-steel`, `titanium-6al4v`,
`brass`, `copper`, `delrin`, `acrylic`, `hdpe`, `nylon`, `mdf`, `hardwood`, `plywood`,
`carbon-fiber`, `foam`. `mild-steel` is `steel-1018` and `acetal` is `delrin`.

Or an object that names one and overrides some of its numbers, keeping the rest of its row
(`{"name": "aluminum-6061", "surface_m_min": 300}`), or describes another with `surface_m_min` (or
`sfm`, surface feet per minute) and `chipload_mm`: `chipload_mm` is per tooth for a 6 mm tool
(scaled with the diameter), or a chip load per tool diameter, `{"3": 0.02, "6": 0.04, "12": 0.06}`,
interpolated between the diameters given. Also `drill_mm_per_rev` and `stepdown_fraction` (of the
tool diameter). For a material not in the table, take the surface speed and chip load from the tool
maker's chart; never borrow a row that only sounds close.

The table's numbers are conservative starting points for carbide tools (from common tool makers'
charts), clamped to the machine's limits, thinned for light stepovers. They are not tuned for the
user's machine: say so. An operation's own `feed` (mm/min), `speed` (rpm) and `plunge_mm_min`
override them.

How the numbers are worked out:

- **Speed:** `rpm = 1000 x Vc / (pi x D)` from the material's surface speed `Vc` (m/min), lower for
  HSS tools, drills, reamers and taps; rounded to a whole 10 rpm and never above `max_rpm`.
- **Feed:** `feed = rpm x flutes x chip load`. The chip load grows with the diameter: in proportion
  below 1 mm, interpolated between 1, 3, 6, 10, 12 and 20 mm, held past 20 mm. A slot takes 0.75 of
  it, an engraving and a thread mill half.
- **Chip thinning:** at a stepover under half the diameter the chip is thinner than the feed per
  tooth, so the feed rises by `D / (2 x sqrt(D x ae - ae^2))`, at most 2 times. The plunge is never
  thinned: it is 0.3 of the un-thinned feed.
- **Hole makers** feed per revolution (a drill's from the material, a reamer twice it, a spot half).
- **A tap** feeds exactly `rpm x pitch`: anything else strips the thread or breaks the tap. Held to
  `max_feed_mm_min`, its spindle slows to a whole rpm instead.

For example a 6 mm 3-flute carbide end mill in 6061 at Vc 250: 13,260 rpm; at 0.04 mm a tooth,
1,591 mm/min; plunge 477 mm/min. On a 10,000 rpm router spindle it runs at 10,000 rpm and 1,200
mm/min.

## Stock

| `kind` | keys | meaning |
| --- | --- | --- |
| `box` | `margin_mm` or `size_mm` | a block round the part. `margin_mm` is one number (every side but the bottom), `[x, y]`, `[x, y, z]` (z on top only) or six numbers `[-x, +x, -y, +y, -z, +z]`; `size_mm` is `[x, y, z]`, centred on the part, flush with its bottom (any size that holds the part; smaller than the part on any axis is refused) |
| `cylinder` | `diameter_mm`, `length_mm`, `axis`, `margin_mm`, `face_stock_mm` | bar stock for a lathe or a 4th axis; `axis` `x`, `y` or `z` (default `z`); `margin_mm` is one number or `[radial, axial]`, the axial margin at both ends (on a lathe at the chuck end only: the face end is `face_stock_mm`); a stated `diameter_mm` takes no radial margin and a stated `length_mm` no axial one; `face_stock_mm` (default 1 on a lathe) stands the bar proud of the part's +axis end, centred on its turning axis ([turning.md](turning.md#the-bar)). The bar is measured on the exact part, so it is never thinner than the part |
| `sheet` | `thickness_mm`, `margin_mm` | a plate for cutting or routing. A `.dxf` part is cut from a sheet only, and needs `thickness_mm` (a drawing has no thickness of its own) |
| `from_step` | `path` | another STEP (a casting, a blank), relative to the job file or the part; it must hold the whole part, by volume, not only its bounding box |

The stock must suit the machine: a lathe turns a `cylinder`; a laser, plasma or waterjet cuts a
`sheet`; a wire EDM a `sheet` or a `box`; mills and routers take any.

## Tools

Every tool has an `id` (operations name it; no spaces round it) and a `type`. Milling tools share:
`number` (the posted T number; default the digits of the id), `name`, `diameter_mm`, `flutes`,
`flute_length_mm`, `stickout_mm`, `shank_diameter_mm`, `holder_diameter_mm`, `holder_length_mm`,
`material` (`carbide` or `hss`). Lathe tools take `id`, `type`, `number`, `name`, `diameter_mm` and
`material`; a beam or a wire only `id`, `type`, `number`, `name` and its own key. Give
`flute_length_mm`, `stickout_mm` and the holder whenever the user knows them: the `reach`,
`holder_collision` and `long_stickout` checks use them. A stickout given without a flute length
cuts the default flutes (3 diameters) back to it; a holder states both its diameter and its length;
a cutter under 3 mm sits on a 3 mm shank unless `shank_diameter_mm` says otherwise.

| `type` | its own keys | for |
| --- | --- | --- |
| `flat` | | flat end mill |
| `face_mill` | | face mill (4 teeth by default) |
| `ball` | | ball end mill |
| `bull` | `corner_radius_mm` | end mill with a corner radius |
| `vee` | `angle_deg`, `tip_diameter_mm` | V-bit for engraving and chamfers |
| `chamfer` | `angle_deg`, `tip_diameter_mm` | chamfer mill |
| `engraver` | `angle_deg`, `tip_diameter_mm` | engraving cutter |
| `drill` | `point_angle` | twist drill (default 118°) |
| `spot` | `angle_deg` | spot drill |
| `tap` | `pitch_mm` | tap |
| `reamer`, `boring` | | reamer, boring bar |
| `counterbore` | `pilot_diameter_mm` (less than the diameter) | counterbore with a pilot |
| `thread_mill` | `pitch_mm` | thread mill |
| `slot` | `width_mm` | slot or keyseat cutter |
| `turn` | `insert` (`C`, `D`, `V`, `W`), `nose_radius_mm`, `side` (`left`, `right`, `neutral`) | lathe turning tool |
| `groove` | `width_mm`, `nose_radius_mm`, `side` | lathe grooving tool |
| `thread` | `pitch_mm`, `side` | lathe threading tool |
| `partoff` | `width_mm` | part-off blade |
| `beam` | `kerf_mm` | laser, plasma or waterjet beam |
| `wire` | `diameter_mm` | EDM wire |

## Setups

A setup is one way the part is held. Each posts its own file, `<part>.<id><extension>`.

| key | meaning |
| --- | --- |
| `id` | short name (letters, digits, `-`, `_`); names the posted file |
| `name` | the plain name the Viewer shows (default from the orientation: "Top") |
| `orientation` | which way the tool looks at the part: `+Z` (from above, default), `-Z` (flipped), `+X`, `-X`, `+Y`, `-Y`; a planar face, `"#o1.f4"` ([below](#a-setup-on-a-face)); or a tilted 3+2 position `{"a_deg": 30, "c_deg": 90}` on a mill4/mill5 ([multi-axis.md](multi-axis.md)) |
| `origin` | where work zero is, on the stock or the part's bounding box: `stock-top-center` (default), `stock-top-corner`, `stock-center`, `stock-bottom-center`, `stock-bottom-corner`, `part-top-center`, `part-top-corner`, `part-center`, `part-bottom-center`, `part-bottom-corner` (a corner is the setup's -X -Y one; a lathe takes no corner); or a point in part coordinates, `[x, y, z]` or `{"xyz": [x, y, z]}` |
| `wcs` | the work offset posted: `G54`..`G59` (default G54, G55, ... by setup order) |
| `fixture` | what holds the stock, one or a list: keep-out boxes (clamps, a vise's jaws) `{"min_mm": [...], "max_mm": [...], "name": "clamp"}` in part coordinates, a `{"type": "vise"}` or a `{"type": "plate"}` ([below](#fixture)); the `fixture` check refuses any move into one |
| `clearance_mm` | height above the stock top for moves between features (default 5) |
| `retract_mm` | height above the material for moves within a feature (default 2); at most `clearance_mm` |
| `operations` | the operations, in cutting order |

### A setup on a face

`"orientation": "#o1.f4"` (on a `mill`, `router`, `mill4` or `mill5`) turns the part so that planar
face looks up at the tool: the tool comes down its outward normal, and the part is turned by the
smallest rotation that does it (a half turn about X for a face looking down -Z). The setup's
`origin` keywords then sit on the stock or part box in that turned frame, so `stock-top-center`
is over the highest stock point the tool sees. Its name is "Face #o1.f4 up", which the posted
file's header carries. An edge, a vertex or a face that is not flat (a cylinder) is refused: it
has no one normal to look down. On a mill4 or mill5 a face the rotary axes reach (within
`rotary_limits_deg`) is that rotary position, as `+Y` is; one they cannot reach (a face with an X
slope on a mill4) is a re-fixture by hand, as on a 3-axis mill.

### `fixture`

A box has no `type` (or `"type": "box"`): `min_mm`, `max_mm` (part coordinates) and an optional
`name`. A vise or a plate is built around the stock's box in the setup's frame (on a mill4 or
mill5 in a rotary position, in the part's own axes: it is bolted to the table and turns with the
part), then written as boxes in part coordinates, which the `fixture` check, the operations'
leads and plunges, and the Viewer use:

| `type` | keys (mm; default) | what is built |
| --- | --- | --- |
| `vise` | `jaws_along` (`x` or `y`; across the stock's narrower side, `y` on a tie), `jaw_height_mm` (40), `grip_mm`, `parallels_mm`, `jaw_width_mm` (150), `jaw_thickness_mm` (20), `parallel_width_mm` (6), `floor_thickness_mm` (10), `name` | Two jaws on the stock's sides along `jaws_along` (`x`: its -X and +X sides), `jaw_width_mm` wide about its centre, standing on the vise's floor; the stock on two parallels `parallels_mm` tall (none at 0), under its edges along the jaws. `grip_mm`, how far the jaws reach up the stock, is `jaw_height_mm - parallels_mm`: any two give the third, and three must agree within 0.01 mm. With fewer than two the grip is 10 (at most half the stock's height). A grip of 0 or less holds nothing and is refused. |
| `plate` | `thickness_mm` (12), `border_mm` (25), `name` | A plate under the stock, `border_mm` wider than it all round (a fixture plate, a spoilboard you must not cut). |

The boxes are named after the fixture's `name` (or its type): `vise -Y jaw`, `vise +Y jaw`,
`vise floor`, `vise -Y parallel`, `plate`. Every size the job did not state is listed in an
`assumed_fixture` note ([checks.md](checks.md)); say which were assumed when you report, and ask
for the real ones when the cut runs near them. A vise or plate is a mill's or a router's: a lathe
or a cutting machine refuses one, and a setup turned onto a sloping face refuses one (its boxes
would stand at an angle to the part's axes: give the jaws as boxes).

```json
"fixture": {"type": "vise", "jaws_along": "y", "jaw_height_mm": 40, "grip_mm": 8}
```

## Operations

Keys every operation takes:

| key | meaning |
| --- | --- |
| `op` | the operation ([the table in SKILL.md](../SKILL.md#choose-the-operation)) |
| `tool` | a tool `id` |
| `faces` | face selectors from `cadgen cam features` or the Viewer (`#o1.f15`), each once |
| `region` | instead of faces, a boundary in the setup's coordinates: `{"polygon": [[x, y], ...], "bottom_z": z}` |
| `feed`, `speed` | override the table's feed (mm/min) and spindle speed (rpm) |
| `stepdown_mm` | depth per pass |
| `stepover` | sideways step as a fraction of the tool diameter (0.4 = 40 %) |
| `stepover_mm` | sideways step in mm (instead of `stepover`) |
| `stock_to_leave_mm` | material left for a later finishing pass |
| `plunge_mm_min` | override the plunge feed (mm/min), on operations that plunge or ramp (the milling ones) |
| `clearance_mm`, `retract_mm` | this operation's own heights over the stock top, instead of the setup's; it ends at or above the setup's clearance. An operation's own key of that name (a drill's chip-break `retract_mm`) is its own |
| `coolant` | `off`, `flood`, `mist`, `air` |
| `name` | a name for the Viewer's row and the G-code comments |

What each operation adds is on its reference page. An operation refuses a shared key it does not
read, rather than ignore it: of `feed`, `speed`, `stepdown_mm`, `stepover`, `stepover_mm` and
`stock_to_leave_mm`,

| operations | read |
| --- | --- |
| `face`, `pocket`, `adaptive`, `slot`, `helix_bore`, `rough`, `waterline`, `rest`, `rotary` | all of them (`rest` of `parallel`: no `stepdown_mm`) |
| `contour`, `swarf` | `feed`, `speed`, `stepdown_mm`, `stock_to_leave_mm` |
| `parallel`, `scallop`, `surface_normal` | `feed`, `speed`, `stepover`, `stepover_mm`, `stock_to_leave_mm` |
| `pencil`, `turn_rough`, `turn_finish`, `turn_groove` | `feed`, `speed`, `stock_to_leave_mm` |
| `engrave`, `cut` | `feed`, `speed`, `stepdown_mm` (a beam's `cut`: `feed` only) |
| `drill`, `thread_mill`, `chamfer`, `turn_face`, `turn_drill`, `turn_partoff` | `feed`, `speed` (a tap: `speed` only) |
| `turn_thread` | `speed` (a thread feeds one pitch a turn) |
| `wire_edm` | `feed` |
