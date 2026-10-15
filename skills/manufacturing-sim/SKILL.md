---
name: manufacturing-sim
description: Simulate or estimate what happens to a part while it is made - casting (sand, investment and lost-wax jewellery, permanent mould, die), injection moulding, heat treatment and quenching, 3D printing, machining, sheet metal, welding, reflow soldering, forging and extrusion. Casting runs as a simulation of the metal freezing in its mould; the other processes get hand estimates, labelled as estimates. Use when the user asks whether a part will cast or fill, where shrinkage or porosity forms, how long it takes to freeze or cool, whether it will sink, warp or curl, spring back or crack when bent, chatter when machined, distort when welded, or how hot its parts get through a reflow oven.
license: MIT
---

# Manufacturing simulation: what happens to the part while it is made

Provenance: maintained in [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad).
Use the installed local skill files as the runtime source of truth; the repository link is only for
provenance and release review.

Use this skill for questions about a process rather than about the finished part in service: will
it cast soundly, will it fill, will it warp when printed or spring back when bent. It is a router,
the way `$fea` is for engineering questions: [Choose the process](#choose-the-process) maps the
user's question to a process and its reference page. A process cadgen simulates today runs as an
analysis of the same solver `$fea` uses (`cadgen fea solve` with the study's `analysis` naming the
process); every other process gets an honest hand estimate, labelled as one, from
[estimates.md](references/estimates.md) until its simulation is built.

Casting runs today: the metal poured into the mould, freezing from the pour until it is solid, with
where it freezes last (where shrinkage collects), whether the feeders reach it, the Niyama
porosity indicator and whether thin sections freeze before the mould fills. It is lite: the cavity
starts full (filling is not simulated), the mould is a heat transfer coefficient (not meshed), and
there is no shrinkage-driven flow, gas porosity or microstructure. Say so when you report.

## Choose the process

Match the user's question to a row first. Only a **Runs today** row runs in cadgen, and one whose status
says estimate runs hand formulas on the part, not a simulation.

| The user asks | `analysis` | Plain word | Status | Reference |
| --- | --- | --- | --- | --- |
| "Will it cast", "where will it shrink or be porous", "will this 1 mm frame fill", "how long until it is solid", "where do I put the riser or the sprue": sand, investment (lost-wax jewellery), permanent mould or die casting | `casting` | Casting | **Runs today** (lite: the cavity starts full, the mould is a heat transfer coefficient, no shrinkage flow or microstructure) | [casting.md](references/casting.md) |
| Injection moulding: "how long to cool", "will it sink", "will it warp", "will it fill" | none yet | Injection moulding | **Estimate** (cooling time and sink risk by hand; no flow, pack or warp simulation) | [estimates.md](references/estimates.md#injection-moulding) |
| Heat treatment and quenching: "will it distort", "how fast does the core cool", "how hard will it be" | none yet | Heat treatment | **Estimate** (the cooling runs today as `$fea`'s heat over time; no phase change, distortion or hardness) | [estimates.md](references/estimates.md#heat-treatment-and-quenching) |
| 3D printing (FDM, resin, SLS/MJF, metal powder bed): "will it warp or curl", "residual stress" | none yet | 3D printing | **Estimate** (thermal strain by hand; printability is `$dfam-check`'s) | [estimates.md](references/estimates.md#3d-printing) |
| CNC machining: "will this thin wall deflect under the cutter or the clamp", "which spindle speeds are chatter-free" | none yet | Machining | **Estimate** (the deflection and the natural frequency run today in `$fea` as `static` and `modal`; chatter by hand) | [estimates.md](references/estimates.md#cnc-machining) |
| Sheet metal bending: "how much will it spring back", "what overbend", "will it crack at this bend", the bend allowance | `sheet_metal` | Sheet metal | **Runs today** (estimate: per bend from the STEP by hand formulas, Gardiner's springback, the outer strain against the minimum R/t, DIN 6935's K-factor; no forming simulation; bend rules are `$dfm`'s) | [sheet_metal.md](references/sheet_metal.md) |
| Welding: "how much will it distort", "residual stress at the weld" | none yet | Welding | **Estimate** (shrinkage and angular distortion by hand) | [estimates.md](references/estimates.md#welding) |
| Reflow soldering of a board: "how hot do the parts get through the profile", "is the big connector above liquidus long enough" | none yet | Reflow | **Estimate** (the temperatures run today in `$fea` as heat over time with the oven's profile; no solder flow) | [estimates.md](references/estimates.md#reflow-soldering) |
| Forging, extrusion and deep drawing: "what press force", "will the die fill" | none yet | Forming | **Estimate** (slab-method forging load, extrusion pressure, deep-drawing force by hand; no die fill) | [estimates.md](references/estimates.md#forging-extrusion-and-deep-drawing) |

A test keeps this table's **Runs today** rows in step with what cadgen registers.

### When the process is an estimate

- Say "estimate" every time you quote one, and give its assumptions and its source with the
  number. Never pass an estimate off as a simulation, or a simulation of something else (a static
  stress, a temperature) off as the process's.
- Say plainly what is not in this version, in the user's words: "a warp simulation of a moulded
  part is not in this version".
- Where `$fea` honestly answers part of the question, offer it and say which part: a thin wall's
  deflection under a cutting force is `static`; a part's natural frequency for chatter is `modal`;
  a quench's or a reflow oven's temperatures over time are `thermal_transient`. Each estimate in
  [estimates.md](references/estimates.md) says how to set that study up.
- Geometry rules (draft, rib to wall ratios, bend reliefs, overhangs) are `$dfm`'s and
  `$dfam-check`'s: send the user there for a review rather than restating them.

## Say what the run did

- **Lite limits.** Every casting result carries its limits (the sidecar's `limits`, the GLB's
  `analysis.limits`). Quote them whenever you quote its numbers.
- **Instant fill.** The cavity starts full at the pour temperature. A thin section far from the gate
  freezes sooner in reality, because the metal cools as it flows to it: treat a `misrun_risk`
  warning as a real risk, and a section the run says fills in time as optimistic.
- **Feeders.** A named feeder is taken to stay liquid until the casting is solid (a riser sized for
  it). Whether it really does is a separate check: its own modulus should be about 1.2 times the
  section it feeds or more ([casting.md](references/casting.md#hand-checks)).
- **Estimated fill time.** Without `fill_time_s` the fill time is estimated from the mass; say it
  was estimated, and ask for the real one when the misrun answer depends on it.
- **Niyama.** It marks where porosity is likely, not how much, and some alloys have no published
  threshold: say which.
- **Adapted steps.** As in `$fea`: report every `adapted:` line and `fit_` finding.

## Setup

Run cadgen through [uv](https://docs.astral.sh/uv/). `cadgen fea faces` shares one installation
with the `$cad` skill and the CAD app's server; `cadgen fea solve` needs the `fea` extra, so it runs
from its own installation, made the first time it is needed (below):

- `cadgen` below means `uvx --no-config --managed-python --python 3.13 --from cadgen==0.7.21 cadgen`
- `python` below means `uvx --no-config --managed-python --python 3.13 --from cadgen==0.7.21 python`

Solving needs cadgen's opt-in `fea` extra (the mesher and the solver). The first time a study runs,
`cadgen fea solve` fails with "cadgen's fea extra is not installed"; that is a missing install, not
a modelling error. Run the same command with the extra in the requirement, and keep using that form
for `fea solve` from then on (the first run downloads the mesher and solver; later runs reuse them):

```bash
uvx --no-config --managed-python --python 3.13 --from "cadgen[fea]==0.7.21" cadgen fea solve part.step --study casting.json
```

Units: mm for geometry, °C for temperatures, s for times, W/(m² K) for a heat transfer coefficient.

## Workflow (casting)

1. **List the faces.** A casting study names faces only for its feeders: the gate, the riser and
   the sprue's contact with the part. Prefer faces the user selected in the Viewer
   (`part.step#o1.f12`); otherwise list them and match by description.

   ```bash
   cadgen fea faces part.step
   ```

2. **Write the study** as `casting.json` beside the part ([casting.md](references/casting.md)):

   ```json
   {"analysis": "casting", "alloy": "sterling-silver-925", "process": "investment",
    "feeders": [{"faces": ["#o1.f12"]}], "fill_time_s": 0.5}
   ```

   `alloy` and `process` are required; the process sets the mould's temperature, the pour's
   superheat and the mould's heat transfer coefficient, and `pour_temperature_C`,
   `mold_temperature_C` and `h_W_m2K` override them when the user knows theirs (a jeweller's flask
   temperature, a foundry's pour temperature). Leave `mesh` out on the first run.

3. **Solve.**

   ```bash
   cadgen fea solve part.step --study casting.json
   ```

   This writes `part.fea.glb` (coloured by the time to fully solid: the last to freeze is red) and
   `part.fea.json` (every number, the study, the mesh and timings) beside the part. Progress lines
   print to stderr; `--json` prints the result as one JSON line. A study with an unknown alloy, a
   pour below the liquidus or a mould above the solidus is refused with a message naming the field.

4. **Read the findings**, one line each after the numbers ([casting.md](references/casting.md#findings)).

5. **Report**, in this order: when it is fully solid and where it freezes last; every hot spot with
   its place (mm) and size; the thinnest section, when it is solid through, and the fill time (and
   whether it was estimated); the Niyama finding; the hand check against Chvorinov's rule; the
   limits. Then what would change the answer most: a feeder on the hot spot, a thicker thin
   section, a hotter pour or mould. Show the result GLB with `$cad` (its Show the model step),
   beside the STEP; the Time scrubber plays the temperature and the liquid fraction through the
   freezing.
