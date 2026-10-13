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
| `post` | the controller's dialect ([posts.md](posts.md)); left out, the kind's default (`grbl` for a mill, router or laser, `linuxcnc` for a mill4, mill5 or lathe) |
| `name` | the machine's name, for the headers |
| `travel_mm` | axis travel `[x, y, z]` (a lathe `[x, z]`); with it, the `travel` check runs |
| `max_rpm`, `max_feed_mm_min` | limits: speeds and feeds are clamped to them (the `limits` warning says where) |
| `rapid_mm_min` | rapid traverse rate, for the cycle time (default per kind) |
| `tool_change_s` | seconds per tool change, for the cycle time |
| `kinematics` | a `mill5`'s: `ac_trunnion` (A tilts the table about X, C turns it) or `bc_head` (B tilts the head, C turns the table) |
| `rotary_limits_deg` | rotary travel: `{"a": [-120, 30], "c": [-360, 360]}` |
| `diameter_mode` | a lathe's X words are diameters (default `true`) or radii |

The cutting machines take their process keys (power, amps, quality) on [cutting.md](cutting.md).

## Material

A name from the feeds table:

`aluminum-6061`, `aluminum-7075`, `steel-1018`, `stainless-304`, `tool-steel`, `titanium-6al4v`,
`brass`, `copper`, `delrin`, `acrylic`, `hdpe`, `nylon`, `mdf`, `hardwood`, `plywood`,
`carbon-fiber`, `foam`.

Or an object that names one and overrides it, or describes another:
`{"name": "aluminum-6061", "chipload_mm": 0.03}`, with `surface_m_min` (or `sfm`, surface feet per
minute), `chipload_mm` (per tooth, for a 6 mm tool; scaled with diameter), `drill_mm_per_rev`,
`stepdown_fraction` (of the tool diameter).

The table's numbers are conservative starting points for carbide tools (from common tool makers'
charts), clamped to the machine's limits, thinned for light stepovers. They are not tuned for the
user's machine: say so. An operation's own `feed` (mm/min) and `speed` (rpm) override them.

## Stock

| `kind` | keys | meaning |
| --- | --- | --- |
| `box` | `margin_mm` or `size_mm` | a block round the part. `margin_mm` is one number (every side but the bottom), `[x, y]`, `[x, y, z]` (z on top only) or six numbers `[-x, +x, -y, +y, -z, +z]`; `size_mm` is `[x, y, z]`, centred on the part, flush with its bottom |
| `cylinder` | `diameter_mm`, `length_mm`, `axis`, `margin_mm` | bar stock for a lathe or a 4th axis; `axis` `x`, `y` or `z` (default `z`) |
| `sheet` | `thickness_mm`, `margin_mm` | a plate for cutting or routing |
| `from_step` | `path` | another STEP (a casting, a blank), relative to the job file or the part |

## Tools

Every tool has an `id` (operations name it) and a `type`. Shared keys: `number` (the posted T number;
default the digits of the id), `name`, `diameter_mm`, `flutes`, `flute_length_mm`, `stickout_mm`,
`shank_diameter_mm`, `holder_diameter_mm`, `holder_length_mm`, `material` (`carbide` or `hss`).
Give `flute_length_mm`, `stickout_mm` and the holder whenever the user knows them: the `reach` and
`holder_collision` checks use them.

| `type` | its own keys | for |
| --- | --- | --- |
| `flat` | | flat end mill |
| `ball` | | ball end mill |
| `bull` | `corner_radius_mm` | end mill with a corner radius |
| `vee` | `angle_deg`, `tip_diameter_mm` | V-bit for engraving and chamfers |
| `chamfer` | `angle_deg`, `tip_diameter_mm` | chamfer mill |
| `engraver` | `angle_deg`, `tip_diameter_mm` | engraving cutter |
| `drill` | `point_angle` | twist drill (default 118°) |
| `spot` | `angle_deg` | spot drill |
| `tap` | `pitch_mm` | tap |
| `reamer`, `boring` | | reamer, boring bar |
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
| `orientation` | which way the tool looks at the part: `+Z` (from above, default), `-Z` (flipped), `+X`, `-X`, `+Y`, `-Y`; or a tilted 3+2 position `{"a_deg": 30, "c_deg": 90}` on a mill4/mill5 ([multi-axis.md](multi-axis.md)) |
| `origin` | where work zero is: `stock-top-center` (default), `stock-top-corner`, `part-top-center`, or `{"xyz": [x, y, z]}` in part coordinates |
| `wcs` | the work offset posted: `G54`..`G59` (default G54, G55, ... by setup order) |
| `fixture` | keep-out boxes (vise jaws, clamps) `{"min_mm": [...], "max_mm": [...], "name": "vise"}` in part coordinates; the `fixture` check refuses any move into one |
| `clearance_mm` | height above the stock top for moves between features (default 5) |
| `retract_mm` | height above the material for moves within a feature (default 2) |
| `operations` | the operations, in cutting order |

## Operations

Keys every operation takes:

| key | meaning |
| --- | --- |
| `op` | the operation ([the table in SKILL.md](../SKILL.md#choose-the-operation)) |
| `tool` | a tool `id` |
| `faces` | face selectors from `cadgen cam features` or the Viewer (`#o1.f15`) |
| `region` | instead of faces, a boundary in the setup's coordinates: `{"polygon": [[x, y], ...], "bottom_z": z}` |
| `feed`, `speed` | override the table's feed (mm/min) and spindle speed (rpm) |
| `stepdown_mm` | depth per pass |
| `stepover` | sideways step as a fraction of the tool diameter (0.4 = 40 %) |
| `stepover_mm` | sideways step in mm (instead of `stepover`) |
| `stock_to_leave_mm` | material left for a later finishing pass |
| `coolant` | `off`, `flood`, `mist`, `air` |
| `name` | a name for the Viewer's row and the G-code comments |

What each operation adds is on its reference page.
