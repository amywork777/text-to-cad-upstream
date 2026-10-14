---
name: cam
description: Turn a saved STEP part or DXF profile into toolpaths and G-code with cadgen, for CNC mills and routers (2.5D, 3D, indexed and 5-axis), lathes, laser, plasma and waterjet cutters and wire EDM. It plans the cuts, simulates the stock, checks for gouges, collisions and reach, estimates the cycle time and posts G-code for the named controller. Use when the user asks to machine, mill, turn, cut or engrave a part, for CAM, toolpaths, feeds and speeds, or G-code for a CNC machine.
license: MIT
---

# CAM: toolpaths and G-code from a saved part

Provenance: maintained in [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad).
Use the installed local skill files as the runtime source of truth; the repository link is only for
provenance and release review.

Use this skill to take a saved part to cutting instructions. You write a small job file (machine,
material, stock, tools, setups and their operations), `cadgen cam plan` plans every toolpath,
simulates the stock being cut, runs the checks, estimates the time and posts one G-code file per
setup. It also writes `<part>.cam.glb`, which the Viewer shows with the toolpaths, the simulated
stock, a Job panel with the verdict and a playback of the cut. This page is a router: [Choose the
operation](#choose-the-operation) maps what the user wants to an operation and its reference page;
[job-file.md](references/job-file.md) holds what every job shares, [checks.md](references/checks.md)
what the verdict and findings mean, [posts.md](references/posts.md) the controllers, and
[machining-practice.md](references/machining-practice.md) how a machinist would plan the part:
workholding, tool choice, operation order, cutting parameters, materials and proving the program.

Modelling the part is `$cad`; this skill only reads a saved `.step` (or a `.dxf` for cutting).
Reviewing whether a design CAN be machined well, before any toolpath, is `$dfm`. 3D printing is
`$gcode`.

## Choose the operation

The `op` key of each operation names it. Pick by what the user wants cut and on which machine.

| The user wants | `op` | Plain word | Status | Reference |
| --- | --- | --- | --- | --- |
| The top of the stock flattened | `face` | Face | **Runs today** | [milling-2d.md](references/milling-2d.md) |
| An outline cut around (or inside) a shape, cut out of a plate with tabs | `contour` | Profile | **Runs today** | milling-2d.md |
| A flat-floored pocket cleared, with or without islands | `pocket` | Pocket | **Runs today** | milling-2d.md |
| A big pocket or open area cleared fast with constant tool load | `adaptive` | Adaptive clear | **Runs today** (lite) | milling-2d.md |
| A slot or keyway | `slot` | Slot | **Runs today** | milling-2d.md |
| Edges chamfered or deburred | `chamfer` | Chamfer | **Runs today** | milling-2d.md |
| Text, a logo or a line engraved | `engrave` | Engrave | **Runs today** | milling-2d.md |
| A round hole too big for a drill, milled in a helix | `helix_bore` | Helix bore | **Runs today** | milling-2d.md |
| A thread milled in a hole or on a boss | `thread_mill` | Thread mill | **Runs today** | milling-2d.md |
| Holes drilled, pecked, tapped, reamed, bored or spotted | `drill` | Drill | **Runs today** | [drilling.md](references/drilling.md) |
| A curved or sculpted part roughed out | `rough` | 3D rough | **Runs today** | [milling-3d.md](references/milling-3d.md) |
| A curved surface finished smooth | `parallel` | Parallel finish | **Runs today** | milling-3d.md |
| Steep walls finished in levels | `waterline` | Waterline | **Runs today** | milling-3d.md |
| An even finish over mixed steep and shallow surfaces | `scallop` | Scallop | **Runs today** (lite) | milling-3d.md |
| Inside corners and creases cleaned up after finishing | `pencil` | Pencil | **Runs today** (lite) | milling-3d.md |
| Only the material a bigger tool left behind | `rest` | Rest machining | **Runs today** | milling-3d.md |
| A face at an angle reached by tilting the part (3+2), any operation above | a setup with a tilted `orientation` | Indexed | **Runs today** | [multi-axis.md](references/multi-axis.md) |
| A pattern or groove wrapped around a cylinder on a 4th axis | `rotary` | 4th-axis wrap | **Runs today** (lite) | multi-axis.md |
| A tilted or ruled wall cut with the side of the tool on a 5-axis | `swarf` | Swarf | **Runs today** (lite) | multi-axis.md |
| A sculpted surface finished with the tool tilted to it on a 5-axis | `surface_normal` | 5-axis finish | **Runs today** (lite) | multi-axis.md |
| The end of a bar faced on a lathe | `turn_face` | Face | **Runs today** | [turning.md](references/turning.md) |
| A turned part roughed, outside or bore | `turn_rough` | Rough turn | **Runs today** | turning.md |
| A turned profile finished, outside or bore | `turn_finish` | Finish turn | **Runs today** | turning.md |
| A groove on a lathe | `turn_groove` | Groove | **Runs today** | turning.md |
| A thread cut on a lathe | `turn_thread` | Thread | **Runs today** | turning.md |
| A centre hole or a hole on the spindle axis | `turn_drill` | Centre drill | **Runs today** | turning.md |
| The finished part cut off the bar | `turn_partoff` | Part off | **Runs today** | turning.md |
| A flat part cut out on a laser, plasma, waterjet or router | `cut` | Cut out | **Runs today** | [cutting.md](references/cutting.md) |
| A profile cut on a wire EDM | `wire_edm` | Wire cut | **Runs today** (lite) | [wire-edm.md](references/wire-edm.md) |

A lite operation carries plain-sentence limits in its result: quote them when you report it. A test
keeps this table in step with what cadgen builds.

## Setup

Run cadgen through [uv](https://docs.astral.sh/uv/), so this skill's commands share one
installation, and its warm build daemon, with the `$cad` skill and the CAD app's server:

- `cadgen` below means `uvx --no-config --managed-python --python 3.13 --from cadgen==0.7.21 cadgen`
- `python` below means `uvx --no-config --managed-python --python 3.13 --from cadgen==0.7.21 python`

Units are fixed: mm for lengths, mm/min for feed, rev/min for spindle speed, degrees for angles,
seconds for time.

## Workflow

1. **Read the part.** Every job names faces by the Viewer's selector.

   ```bash
   cadgen cam features part.step
   ```

   It prints the part's size, one line per face (`#o1.f15  flat floor at Z 17, facing +Z (a pocket
   floor 8 mm down, 1 island)`) and one line per hole (diameter, depth, through or blind, axis,
   position). For a `.dxf` it lists the closed profiles and holes. A face the user selected in the
   Viewer arrives as `part.step#o1.f15` and needs no lookup.

2. **Pick the machine, material and stock.** Use what the user said; otherwise ask once, in one
   message, for what [machining-practice.md](references/machining-practice.md#ask-before-you-plan)
   lists (the machine and controller, how the part is held, the tools they own, the material and
   temper, the critical features), and assume nothing about them silently. A material from the feeds
   table gives starting speeds and feeds ([job-file.md](references/job-file.md#material)); say they
   are starting points.

3. **Write the job** as `part.cam.json` beside the part ([job-file.md](references/job-file.md)):

   ```json
   {
     "machine": {"kind": "mill", "post": "grbl", "travel_mm": [300, 200, 80], "max_rpm": 24000},
     "material": "aluminum-6061",
     "stock": {"kind": "box", "margin_mm": [2, 2, 1]},
     "tools": [
       {"id": "T1", "type": "flat", "diameter_mm": 6, "flutes": 3, "flute_length_mm": 20, "stickout_mm": 30},
       {"id": "T2", "type": "drill", "diameter_mm": 5}
     ],
     "setups": [
       {"id": "top", "orientation": "+Z", "origin": "stock-top-center", "operations": [
         {"op": "face", "tool": "T1"},
         {"op": "pocket", "tool": "T1", "faces": ["#o1.f15"]},
         {"op": "drill", "tool": "T2", "faces": ["#o1.f7", "#o1.f8"], "cycle": "peck"}
       ]}
     ]
   }
   ```

   Plan it the way [machining-practice.md](references/machining-practice.md) says: hold the part
   low and give every vise jaw and clamp as a `fixture` box; the shortest tool that reaches and the
   largest that fits; face, rough with stock to leave, finish, then spot, drill and tap, then
   chamfer; climb milling; helix or ramp entries, never a straight plunge. One setup per way the
   part is held. Each operation's own keys are on its reference page.

4. **Plan.**

   ```bash
   cadgen cam plan part.step --job part.cam.json
   ```

   It writes `part.cam.glb` and, when no check found an error, one G-code file per setup
   (`part.top.nc`; the extension is the post's; a post that needs one file per tool names them
   `part.top.T1.nc`, `part.top.T2.nc`) beside the part, and prints one line per operation (tool, speed, feed, time), one
   `adapted:` line per step it took to fit a big part, then its findings. `--json` gives the same as
   one JSON object. Every plan first removes what the last plan of that part wrote there, so a job
   that cannot run leaves nothing (never the last run's G-code) and says, in one sentence, what to
   change.

5. **Read the verdict and fix the job.** "Ready to cut" means no check failed; "N to fix" lists the
   errors, and no G-code was written ("G-code not written: fix N errors first"): only the GLB, to
   show where they are. Fix each in the JOB (a shorter tool, a smaller stepdown, another setup, a different
   tool for a corner), never by changing the part unless the user asks. Re-plan until it is ready,
   then deal with warnings ([checks.md](references/checks.md)).

6. **Show it.** Show `part.cam.glb` with `$cad` (its Show the model step): the user sees the
   toolpaths, the cut stock, the Job panel and can play the cut.

## Report

Say, in the user's words:

- The verdict, the total time and the tool list, then each setup with its operations.
- Every warning, every lite limit an operation carries and every `adapted:` step, with its note.
- That speeds and feeds are starting points from a table, not tuned for their machine.
- Where the plan departs from [machining-practice.md](references/machining-practice.md) (a long
  stickout, a full-width slot, a straight plunge, a tool the user did not confirm they own), and
  why.
- **Always:** the G-code has not been run on a machine. Give the user the steps in
  [Proving the program](references/machining-practice.md#proving-the-program): check the post
  matches the controller, set the work offset and tool lengths, play the cut in the Viewer, dry-run
  it above the part, then cut single-block with the overrides down. The same warning opens every
  posted file.

Never send G-code to a machine from this skill.
