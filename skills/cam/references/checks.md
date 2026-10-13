# The verdict and the checks

Every `cadgen cam plan` runs every check that applies to its job and gives one verdict:

- **Ready to cut** (`verdict.status` `ready`): no check found an error. Warnings may remain.
- **N to fix** (`fix`): N errors. The G-code is still written, so the user can look at it, but
  do not call it ready: change the job and plan again.

The headline is what the Viewer's Job panel shows first: "Ready to cut · 42 min · 3 tools".

Each finding is one object in the result's `findings` (and one line of the CLI's output):
`check` (the check below), `severity` (`error`, `warning` or `info`), `type` (the particular kind,
such as `reach_flutes`), `summary` (one plain sentence), `description` and `items` (where: the
setup, the operation's index, the point `at` in part mm, and the numbers).

| check | level | what it means | usual fix in the job |
| --- | --- | --- | --- |
| `gouge` | error | a cutting move goes into the part beyond the tolerance | a smaller tool or stepover, `stock_to_leave_mm` on the roughing, a tighter `tolerance_mm` |
| `holder_collision` | error | the holder or shank, above the flutes, touches the stock or the part | a longer `stickout_mm`, a slimmer holder, a shallower operation from another setup |
| `reach` | error | the cut is deeper than the flutes or the stickout | a longer tool, or cut it from another side |
| `rapid_into_stock` | error | a rapid move passes through uncut stock | raise `clearance_mm`, reorder operations |
| `travel` | error | a move leaves the machine's travel (`machine.travel_mm`, `rotary_limits_deg`) | move `origin`, another setup |
| `fixture` | error | a move enters a fixture keep-out box | change the region, move the part in the vise, another setup |
| `machine` | error | an operation needs an axis or a process the machine does not have | another machine kind, or another operation |
| `corner_radius` | warning | an inside corner is tighter than the tool's radius, so material stays in it | a smaller tool for those corners (`rest` or a second pocket), or accept the radius |
| `material_left` | warning | stock is left above the part after every operation, beyond `stock_to_leave_mm` | add a finishing or rest operation where it says |
| `limits` | warning | a feed or speed was clamped to `max_feed_mm_min` or `max_rpm` | none needed; report it |

## Adapted steps

A part too big for the time and memory target is never refused: the run coarsens the stock grid,
loosens the sampling or keeps fewer simulation frames, and says each step in an `adapted:` line
(and `adapted` in the result) with what it cost. Report every one; the toolpaths themselves keep
the job's tolerance, only the simulation and checks are coarser.

## What the checks do not cover

The checks know the part, the stock, the tools and the boxes you gave. They do not know the
user's real vise, clamps, tool lengths, work offsets, machine kinematics beyond the job, or whether
the stock is held well enough for the cut. Say so, and say that the program must be air-cut or run
single-block first.
