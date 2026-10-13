# Drilling: drill, peck, tap, ream, bore and spot holes

One operation, `drill`, cuts round holes along the setup's Z in canned cycles: spot them, drill or
peck them, tap, ream or bore them. Each is its own operation in the job, one tool each, usually in
that order. The posted file carries the controller's cycles (G81, G83, G84, ...) where the post has
them, and the same moves spelled out where it does not (GRBL has none).

Read the holes first: `cadgen cam features` lists each one with its diameter, depth, through or
blind, its axis and the face selectors of its wall.

```bash
cadgen cam features part.step
```

## A minimal job

Spot every hole, peck the 5 mm through holes, tap them M6:

```json
{
  "machine": {"kind": "mill", "post": "grbl", "travel_mm": [300, 200, 80], "max_rpm": 24000},
  "material": "aluminum-6061",
  "stock": {"kind": "box", "margin_mm": [2, 2, 1]},
  "tools": [
    {"id": "T1", "type": "spot", "diameter_mm": 6},
    {"id": "T2", "type": "drill", "diameter_mm": 5},
    {"id": "T3", "type": "tap", "diameter_mm": 6, "pitch_mm": 1}
  ],
  "setups": [
    {"id": "top", "orientation": "+Z", "origin": "stock-top-center", "operations": [
      {"op": "drill", "tool": "T1", "holes": "all"},
      {"op": "drill", "tool": "T2", "holes": {"diameter_mm": 5}, "cycle": "peck"},
      {"op": "drill", "tool": "T3", "holes": {"diameter_mm": 5}}
    ]}
  ]
}
```

```bash
cadgen cam plan part.step --job part.cam.json
```

## Which holes

Name them one way per operation:

| key | meaning |
| --- | --- |
| `faces` | the hole walls (`#o1.f7`; either half of a split hole names the hole). Each must run along the setup's Z (a through hole either way); one that does not is refused with the setup, or the `orientation`, that would reach it |
| `holes` | `"all"`: every hole this setup reaches (holes along other axes are left, and the note counts them); or `{"diameter_mm": 5, "tolerance_mm": 0.05}`: those of one size |
| `points` | `[[x, y], ...]` in the setup's WCS (mm from its origin), with `depth_mm`. A point where the model has no hole is drilled anyway and said once as a `no_hole_in_model` warning |
| `top_z` | with `points` only: the holes' top in WCS. Left out, the part's top at each point (else the stock's top) |

A hole along X or Y needs its own setup (`"orientation": "+X"`); a hole at an angle needs a tilted
one ([multi-axis.md](multi-axis.md)).

## The cycle

`cycle` picks what the tool does in each hole. Left out, the tool decides: a drill or flat end mill
`drill` (or `peck` when the deepest hole is three diameters or more), a spot or chamfer tool `spot`,
a tap `tap`, a reamer `ream`, a boring bar `bore`.

| `cycle` | posted as | tools | what it does |
| --- | --- | --- | --- |
| `drill` | G81 | drill, flat, spot | feed to depth, rapid out |
| `dwell` | G82 | drill, flat, spot | feed to depth, wait `dwell_s` (default 0.5 s), rapid out: flat-bottomed counterbores, clean spot faces |
| `peck` | G83 | drill, flat | pecks of `peck_mm` (default one diameter) from the R plane, back to R after each to clear chips, then down to 0.5 mm over the last depth |
| `chipbreak` | G73 | drill, flat | pecks of `peck_mm` (default half a diameter), backing off `retract_mm` (default 0.2) after each to break the chip |
| `tap` | G84, G74 for a left-hand tap | tap | feed at exactly rpm x the tap's pitch, reverse the spindle at the bottom, feed out |
| `ream` | G85 | reamer | feed in, feed out |
| `bore` | G85, G89, G86 or G76 by `bore_mode` | boring | see below |
| `spot` | G81, or G82 with `dwell_s` | spot, drill, chamfer | a short cone to start the drill true: as wide as the hole (no wider than the tool), or `depth_mm` deep |

`bore_mode`: `feed` (G85, feed out; the default), `dwell` (G89, wait `dwell_s`, feed out), `stop`
(G86, spindle stop, rapid out), `fine` (G76, oriented spindle stop, shift `shift_mm`, default 0.1,
off the wall, rapid out).

A left-hand tap says so on the tool: `{"id": "T3", "type": "tap", "diameter_mm": 6, "pitch_mm": 1,
"hand": "left"}`; the spindle runs backwards into the hole.

## How deep

| key | meaning |
| --- | --- |
| `breakthrough_mm` | a through hole: how far the full diameter goes past the exit (default 1). The tip goes the point's length further (5 mm drill, 118°: 1.5 mm) |
| `depth_to` | a blind hole: `tip` stops the drill's tip on the floor (a flat floor keeps a ring of material at its edge); `shoulder` stops its full diameter there. The default is `shoulder` when the model draws a drill point below the floor, else `tip` |
| `depth_mm` | how deep below each hole's top, overriding the above (to the tip, or the shoulder with `depth_to`). Required with `points` (except for a spot) |

A tap's depth is set by the hole: it stops one pitch above a blind hole's floor, and runs three
pitches of lead past a through hole's exit plus `breakthrough_mm`. `depth_to` does not apply to it;
`depth_mm` does.

## Moving between holes

Each hole starts at its R plane: the setup's `retract_mm` (default 2) over the hole's top, or over
the stock for holes on the part's top face. The tool waits over the first hole at the initial level,
`retract_mm` over the stock.

| key | meaning |
| --- | --- |
| `return_to` | `auto` (the default): back to R between holes (G99) when every straight move between them at R clears the part, else to the initial level (G98); `r_plane` or `initial` force one |
| `order` | `shortest` (the default): nearest hole first, then improved by 2-opt; `given`: in the order named |

Holes with one depth and one R plane in a row are one canned cycle; between cycles the tool climbs
to the initial level before it moves across. Past 3000 holes the order is nearest-first only, and
the note says so.

## Feeds

From the material table as for any operation ([job-file.md](job-file.md#material)): drills by feed
per revolution, spots slower, reamers at half speed, taps at a fifth with the feed locked to rpm x
pitch. `speed` overrides the rpm; `feed` overrides the feed, except on a tap, which is refused (set
`speed`; the feed follows it).

## What it checks

As findings in the result (`check` `drill`, warnings), besides the shared checks
([checks.md](checks.md)):

| `type` | meaning |
| --- | --- |
| `hole_size` | the tool is more than `size_tolerance_mm` (default 0.05) off the hole's diameter: oversize cuts the part, undersize leaves the hole small. A drill one pitch under a hole drawn at its thread size says it is the tap drill |
| `tap_thread` | the tap's pitch is not a standard one for its size (M6: 1 or 0.75), or the hole is not drawn for it: an M6x1 tap wants a Ø5 hole (the tap drill) or a Ø6 one (drawn at the thread size) |
| `no_hole_in_model` | a point drills where the model is solid |

`reach` (an error) compares how deep the tool goes below the material beside it with its
`flute_length_mm` (a drill's default is ten diameters, a spot drill's one). The `gouge` check (an
error) judges the tool's whole body up its flutes, not just its point: a drill bigger than its hole is a
gouge as well as a `hole_size` warning. A tap is judged as its core (the thread's minor diameter,
`d - 1.2269 P`, for an M6x1 4.77 mm), since its thread form cuts the wall on purpose: a tap run into
material past its hole is a gouge. Point holes in solid material are not judged (said above).

Holes along one axis line are split where material stands between them: two blind holes drilled
from either side of a web are two holes, each blind, never one through hole.

## Reading the result

Each drill operation's row reads `Peck drill 4 holes with T2 5 mm drill, 20 s`, with its rpm and
feed. Its note (a `warning:` line) says what was left out: holes along another axis, a post without
a tapping or fine-boring cycle. On GRBL a tap is posted as feed in, `M4`, feed out, `M3`: it needs a
reversible spindle and a floating tap holder, and the note says so. A fine bore on a post without
G76 is posted without the oriented shift, so the bar can mark the wall on its way out.

## Limits

- Holes run along the setup's Z only; there is no cross-hole or angled-hole drilling within a setup.
- On a controller's own G73 the back-off distance is the controller's setting, not `retract_mm`
  (the expanded moves use `retract_mm`).
- Counterbores and countersinks are not recognised as such: a counterbore reads as a larger blind
  hole (drill it with a flat end mill and `dwell`, or pocket it) and a countersink as a cone.
