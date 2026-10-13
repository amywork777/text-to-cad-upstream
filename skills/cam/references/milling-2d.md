# 2.5D milling

Flat floors, straight walls, holes and edges, cut in levels with the tool along Z: `face`, `contour`,
`pocket`, `adaptive`, `slot`, `chamfer`, `engrave`, `helix_bore` and `thread_mill`. Drilling is
[drilling.md](drilling.md); curved surfaces are [milling-3d.md](milling-3d.md). The keys every
operation shares (`tool`, `faces`, `region`, `feed`, `speed`, `stepdown_mm`, `stepover`,
`stepover_mm`, `stock_to_leave_mm`, `coolant`, `name`) are in [job-file.md](job-file.md#operations).

Read the part first: every face this page names comes from it.

```bash
cadgen cam features part.step
```

Coordinates in a `region`, a `path` or `holes` are the setup's work coordinates (WCS): with the
default origin `stock-top-center`, Z 0 is the top of the stock and the part is below it.

A minimal job: face the top, cut a slot, bore a hole, profile the outline out with tabs.

```json
{
  "machine": {"kind": "mill", "post": "grbl", "max_rpm": 24000},
  "material": "aluminum-6061",
  "stock": {"kind": "box", "margin_mm": [2, 2, 1]},
  "tools": [
    {"id": "T1", "type": "flat", "diameter_mm": 6, "flutes": 3, "flute_length_mm": 15, "stickout_mm": 30},
    {"id": "T2", "type": "flat", "diameter_mm": 4, "flutes": 3, "flute_length_mm": 14}
  ],
  "setups": [{"id": "top", "operations": [
    {"op": "face", "tool": "T1"},
    {"op": "slot", "tool": "T2", "faces": ["#o1.f14"]},
    {"op": "helix_bore", "tool": "T1", "faces": ["#o1.f8"]},
    {"op": "contour", "tool": "T1", "faces": ["#o1.f3"], "loops": "outer", "tabs": {"count": 4}}
  ]}]
}
```

```bash
cadgen cam plan part.step --job job.cam.json
```

## face: Face

Takes the top of the stock down flat to the part's top in parallel passes that start and end
outside the stock. Flat or bull tool. Stepover defaults to 0.7 of the diameter.

| key | meaning |
| --- | --- |
| `depth_mm` | how far below the stock top to face (default: down to the part's top plus the stock to leave) |
| `pattern` | `zigzag` (default) or `one_way` (every pass climb, the same way) |
| `angle_deg` | the passes' direction in the XY plane (0 runs along X) |
| `region` | face only inside this polygon (the tool's centre kept in it) |

## pocket: Pocket

Clears a pocket down to its floors by rings offset inward, innermost first, level by level. Name
its floor faces (naming the deepest floor of a stepped pocket clears the steps above it too) or a
`region` with `bottom_z`. Islands are walked round. Stepover defaults to 0.4 of the diameter.

| key | meaning |
| --- | --- |
| `entry` | `helix` (default), `ramp` or `plunge`: how each level is entered (a helix falls back to a ramp, then a plunge) |
| `ramp_angle_deg` | the entry's ramp angle (default 3) |
| `direction` | `climb` (default) or `conventional` |

## contour: Profile

Follows a shape's loops at the tool's radius, level by level from the stock top. A flat face square
to the tool names its outline and its holes; a wall (a plane standing square to XY, a cylinder or
cone along Z) names the whole loop it stands on, on its air side; or give a `region`.

| key | meaning |
| --- | --- |
| `side` | `outside` (the tool's edge on the loop, outside the shape), `inside` or `on` (the tool's centre on it). A face's default is `outside`; a floor below the part's top defaults to `inside` (its walls); a wall's side is its air side |
| `loops` | a face's `all` (default), `outer` (the outline only) or `inner` (its holes only) |
| `bottom_z` | how deep, WCS. Default: a wall's foot, a floor's height (inside), or whatever lies under the tool (a blind slot's floor), else the part's bottom (cut through) |
| `through_mm` | go this much below a cut through (default 0: nothing below the part is cut). Give 0.2 to 0.5 mm to break through cleanly when the part sits on parallels or a spoilboard, and add the support as a `fixture` box if it could be hit |
| `tabs` | `{"count": 4, "width_mm": 5, "height_mm": 1.5}`: bridges left on a cut through, evenly spaced (default width 5, height a third of the cut, at most 2 mm) |
| `lead_in_mm`, `lead_out_mm` | radius of a tangent quarter-arc lead onto and off the loop from the air side (default 0: none); the descent is then made at the lead's start |
| `finish_mm` | leave this much for the levels and take it off in one last full-depth pass |
| `entry` | `ramp` (default: zig-zag down along the loop itself) or `plunge` |
| `ramp_angle_deg` | the ramp's angle (default 3) |
| `direction` | `climb` (default) or `conventional` |

Holes are cut before the outline that holds them. A loop smaller than the tool is skipped and said.

## adaptive: Adaptive clear (lite)

Clears a pocket or an open area at a capped tool load. Name it like a pocket: floor `faces`, or a
`region` with `bottom_z`; an open side clears out to the stock's edge. Each level enters by a helix at
the region's most open point, then grows the cleared area outward one stepover at a time (each new
pass is the cleared area offset by the stepover, clipped to the region), so no point of a pass is
more than a stepover from material already cut; only the stretches that meet new material are cut.
Stepover defaults to 0.15 of the diameter (more than 0.5 is refused); step down to twice the
material's (deep and light), within the flutes. Flat or bull tool.

| key | meaning |
| --- | --- |
| `direction` | `climb` (default) or `conventional` |
| `ramp_angle_deg` | the helix entry's angle (default 3) |

Its limits, which its result carries (quote them): it is not a true medial-axis adaptive solver; a
pass round a small cleared area cuts up to about twice the stepover's worth per millimetre (the first
ring round an entry); a piece too narrow for a helix is ramped into along its outline at full width;
it does not use rest material from earlier operations.

## slot: Slot

Cuts a slot along its centreline, each level entered by a ramp along the centreline. Give one of: a
`path`, the slot's floor in `faces`, or its outline as a `region` (a straight stadium or rectangle:
its long axis is the centreline, its short side the width). A slot wider than the tool is widened in
loops round the centreline, a stepover (default 0.4 of the diameter) at a time; a tool wider than the
slot is refused. An open slot is cut back and forth.

| key | meaning |
| --- | --- |
| `path` | `{"points": [[x, y], ...], "bottom_z": z}`: the centreline, any shape (closed when its last point is its first) |
| `width_mm` | the slot's width (default: the tool's diameter for a path, the floor's or region's own width) |
| `entry` | `ramp` (default) or `plunge` |
| `ramp_angle_deg` | the ramp's angle (default 3) |
| `direction` | `climb` (default) or `conventional`, for the widening loops |

## chamfer: Chamfer

Breaks the top edges of a face's loops (or a wall's top edge, or a `region`'s outline at its
`bottom_z`) with a `vee`, `chamfer`, `engraver` or `spot` tool, in one pass on the air side. The
depth comes from the tool's angle: a cone of half angle a cuts `width / tan(a)` deep (a 90° vee: as
deep as wide). The modelled part has sharp edges there, so the gouge check does not judge a chamfer.

| key | meaning |
| --- | --- |
| `width_mm` | the chamfer's width across the top face (required) |
| `tip_offset_mm` | put the tip this much lower so the cone, not the point, cuts (default 0.2 for a sharp tip, 0 for a flat tip) |
| `loops` | a face's `all` (default), `outer` or `inner` |
| `direction` | `climb` (default) or `conventional` |

A width the cone cannot reach (wider than its radius less the tip offset) is refused.

## engrave: Engrave

Follows curves at a shallow depth with the tool's centre on them: a DXF's lines, arcs, circles,
ellipses, polylines and splines (open or closed; blocks are expanded; text, dimensions and hatches are
skipped and counted: explode text to curves; any other entity is refused, naming its handle),
the edges of flat faces, or a `region`'s outline. Vee, engraver or chamfer tool. Nearest curve first;
plunges at each start. The modelled part has no engraving, so the gouge check does not judge it.

| key | meaning |
| --- | --- |
| `dxf` | the drawing's path, relative to the job file (else the part), or absolute |
| `origin_mm` | where the DXF's origin goes, `[x, y]` WCS (default `[0, 0]`) |
| `depth_mm` | how deep below the surface (default 0.2); deeper than the step down is cut in passes |
| `surface_z` | the surface's height, WCS (default: the named face's, else the part's top) |

The line's width at the surface is `tip diameter + 2 x depth x tan(half angle)` (in its note).

## helix_bore: Helix bore

Mills round holes by helical interpolation, posted as G2/G3 arcs with Z: the tool circles the
hole's exact centre at the hole's radius less its own, from the top of the material down at a pitch
per turn, then one flat circle at the bottom. A hole wider than twice the tool is bored inside out, a
stepover (default 0.4 of the diameter) wider each circle, so no core is left. Name hole walls in
`faces` (any face of a hole names the hole; it must open toward the tool) or list `holes`. A tool not
smaller than the hole is refused. Climb is counter-clockwise (G3).

| key | meaning |
| --- | --- |
| `holes` | `[{"center": [x, y], "diameter_mm": d, "bottom_z": z, "top_z": z}]`, WCS (`top_z` defaults to the part's top) |
| `pitch_mm` | depth per turn (default the step down, or less to keep the ramp at `ramp_angle_deg`) |
| `ramp_angle_deg` | the helix's ramp angle when no pitch is given (default 3) |
| `through_mm` | go this much below a through hole's bottom (default 0; 0.2 to 0.5 mm breaks through cleanly) |
| `direction` | `climb` (default) or `conventional` |

## thread_mill: Thread mill

Mills a thread by helical interpolation with a `thread_mill` tool: inside a tap-sized hole (name its
wall) or on a round boss (name its outside). It steps in on a tangent half circle, follows a helix of
one pitch per turn over the thread's length, and steps out the same way. An internal thread is cut to
its major diameter, an external one to the ISO minor diameter (`major - 1.22687 x pitch`). The
modelled hole is the tap drill, so the gouge check does not judge a thread. Drill the hole first.

| key | meaning |
| --- | --- |
| `thread` | `internal` or `external` (default: a hole's or a boss's) |
| `pitch_mm` | the thread's pitch (default the tool's) |
| `major_diameter_mm` | the nominal size. A hole's default is the tap drill plus the pitch, snapped to 0.5 mm (Ø5 at 1 mm is M6, Ø6.8 at 1.25 is M8); a boss's, its diameter |
| `depth_mm` | the thread's length from the top (default: through and bosses their whole length, blind holes their depth less two pitches) |
| `hand` | `right` (default) or `left` |
| `form` | `single` (default: a single-point tool, the helix covers the whole length) or `multi` (a tool whose `flute_length_mm` of teeth covers the thread: one turn plus a turn per pitch the thread is longer; only the tool's own pitch) |
| `passes` | radial passes splitting the thread's depth (default 1, 2 from a 1.5 mm pitch) |
| `direction` | `climb` (default: a right-hand internal thread runs counter-clockwise from the bottom up, an external one clockwise from the top down) or `conventional` |

The feed is the table's at the cutting edge, scaled to the tool's centre (slower in a hole, faster
round a boss).

## Reading the results

Each operation's row says its tool, spindle speed, feed and time; its `facts` give `levels`,
`passes`, `entries` (how levels were entered: `helix`, `ramp`, `lead`, `air`), `plunges`, and the
floor or bottom it reached. A `note` becomes a warning line: loops too small for the tool, tabs a loop
was too short for, a chamfer's or an engraving's width and depth, a thread's size. Inside corners the
tool's radius cannot reach come back as the `corner_radius` warning ([checks.md](checks.md)): finish
them with a smaller tool. Chamfer, engrave and thread mill cut into the modelled part on purpose and
are not judged by `gouge`; every other operation here is, so a gouge from them means a wrong face or
`bottom_z`.
