# Supported exports

Read this file when the user requests STL, 3MF, or native GLB output files from CAD geometry. For a `.step` file, run the model script or `cadgen step build` (either writes the STEP output; see `step-generation.md`) — a mesh door writes mesh formats only. For 2D DXF output, use the `$dxf` skill: a drawing is its own `<name>.py` declaring one `@dxf` function — one model per file, so a drawing never shares a script with a `@step` model.

## Policy

STL, 3MF, and native GLB are mesh exports, not substitutes for STEP. Validate the primary CAD geometry first, then export the requested formats. Do not treat exported mesh renders as CAD validation; inspect and snapshot the primary model per the standard workflow.

Native GLB exports are ordinary glTF 2.0 binary files for external tools: Y-up, with one material per distinct part/face color. Do not confuse them with the CAD Viewer render artifact — the render package directory in the user-level store (`~/.cache/cadgen/packages/<stepHash>-v<N>/`: an `assembly.json` descriptor plus a `components/` dir of content-addressed exact-geometry components) — which the model script builds and a mesh door never writes.

## Declare the exports the model always has

A mesh output that belongs to the model belongs in the model. Stack `@stl`, `@glb` or `@threemf` on the `@step` function and every build produces them:

```python
from cadgen import build123d as bd
from cadgen import glb, step, stl


@step(out="STEP/bracket.step")
@stl(out="STL/bracket.stl")
@glb
def bracket():
    return bd.Box(40, 20, 6)
```

`python models/bracket.py` (or `cadgen step build models/bracket.py`) then writes the STEP **and** the declared meshes, and heals any of them that were deleted — no separate export step. Declare the same format more than once at distinct targets for draft/print variants:

```python
@stl(out="STL/bracket_draft.stl", mesh_tolerance=8e-3)
@stl(out="STL/bracket_print.stl", mesh_tolerance=4e-4)
```

## Tool

One door per format — `cadgen stl build`, `cadgen 3mf build`, `cadgen glb build` — each taking one model target (a `@step`-decorated model script or an imported STEP/STP file) and an optional output path:

```bash
cadgen stl build path/to/model.py                     # every declared @stl variant,
                                                      # or the sibling <name>.stl
cadgen stl build path/to/model.py meshes/model.stl    # one ad-hoc export
```

Omitting the output is the normal form: it produces exactly what the model declares. A relative output path resolves beside the model's STEP document (not beside the script), so pass an absolute path when that is not what you mean. Ask for several formats by running several doors — each writes only its own format:

```bash
cadgen stl build path/to/model.py
cadgen 3mf build path/to/model.py
cadgen glb build path/to/model.py
```

An output the model already has at the requested tolerances is reported `current` and not rewritten. `--force` re-exports it anyway; it never rebuilds the model itself (that is `cadgen step build`).

Pass an imported STEP/STP file directly only when no model script exists or the user explicitly identifies that file as the target; its part/assembly kind is inferred automatically:

```bash
cadgen stl build path/to/imported.step
```

A mesh door never writes a `.step` file. A generated model's STEP is the OUTPUT of `python <model>.py` or `cadgen step build <model>.py` (always written, assembled from the model's package); an imported model's STEP is already the file on disk.

## Mesh tolerance

Mesh exports tessellate each component's exact surfaces with the same watertight tessellator the CAD Viewer renders with, at the same default tolerances — an export matches what renders, boundary vertices lie on the exact STEP edge curves, and repeated exports are byte-identical.

Use these flags when the default mesh density is wrong for the part:

```bash
--mesh-tolerance FLOAT           # chord tolerance RELATIVE to each component's
                                 # bounding diagonal (default 1.5e-3)
--mesh-angular-tolerance FLOAT   # max normal spread across a triangle edge,
                                 # radians (default 0.35)
```

Either flag overrides what the declaration and the model set, for that run only. Use tighter tolerances for visual fidelity on curved parts; use looser tolerances for large simple geometry when file size matters. The linear tolerance is relative (scale-free), not an absolute deflection in millimetres.

## Workflow

1. Validate the model per the standard workflow (build, inspect, snapshot).
2. Declare the exports the model should always have; run the model script.
3. For anything ad hoc, run the format door for each requested format.
4. Report the exported files.

Example — the model declares its STL, and a one-off coarse GLB is requested beside it:

```bash
python models/bracket.py

cadgen glb build models/bracket.py meshes/bracket_preview.glb \
  --mesh-tolerance 5e-3 \
  --mesh-angular-tolerance 0.5

cadgen step inspect refs models/bracket.step --facts --planes --positioning
```

## Reporting

```text
Files:
- STEP: /absolute/project/models/bracket.step
- STL: /absolute/project/models/STL/bracket.stl
- GLB: /absolute/project/models/meshes/bracket_preview.glb

Validation:
- CAD geometry validated; STL/3MF/native GLB written as requested exports.
- Primary STEP/STP snapshot packet run/skipped and why.
```
