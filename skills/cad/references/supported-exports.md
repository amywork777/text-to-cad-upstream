# Supported exports

Read this file when the user requests STL, 3MF, or native GLB output files from CAD geometry. For a `.step` file, run the model script (it always writes the STEP output; see `step-generation.md`) — `cadgen step export` writes mesh formats only. For 2D DXF output, use the `$dxf` skill; DXF uses a separate the `@dxf` model function contract in a dedicated `<name>.py` drawing generator (never inside a `.py`).

## Policy

STL, 3MF, and native GLB are mesh exports, not substitutes for STEP. Validate the primary CAD geometry first, then export the requested formats. Do not treat exported mesh renders as CAD validation; inspect and snapshot the primary model per the standard workflow.

Native GLB exports are ordinary glTF 2.0 binary files for external tools: Y-up, with one material per distinct part/face color. Do not confuse them with the CAD Viewer render artifact — the render package directory in the user-level store (`~/.cache/cadgen/packages/<stepHash>-v<N>/`: an `assembly.json` descriptor plus a `components/` dir of content-addressed exact-geometry components) — which the model script builds and `cadgen step export` never writes.

## Tool

`cadgen step export` takes one model target — a `@step`-decorated model function Python source or an imported STEP/STP file — and one or more mesh format flags (`--stl`, `--3mf`, `--glb`). The model is built once per run (the generator runs once), so every requested format comes from identical geometry; exports can never be stale.

```bash
cadgen step export path/to/model.py --stl --3mf --glb
```

Each format flag takes an optional output path. Without a path, the file is written beside the model as `<name>.<ext>`. A relative path resolves beside the model; an absolute path is used as-is:

```bash
cadgen step export path/to/model.py \
  --stl meshes/model.stl \
  --3mf meshes/model.3mf \
  --glb meshes/model.glb
```

When a generator exists, export from the generator. Pass an imported STEP/STP file directly only when no generator exists or the user explicitly identifies that file as the target; its part/assembly kind is inferred automatically:

```bash
cadgen step export path/to/imported.step --stl --3mf
```

`cadgen step export` never writes a `.step` file. A generated model's STEP is the OUTPUT of `python <model>.py <name>.py` (always written, assembled from the model's package); an imported model's STEP is already the file on disk.

## Mesh tolerance

Mesh exports tessellate each component's exact surfaces with the same watertight tessellator the CAD Viewer renders with, at the same default tolerances — an export matches what renders, boundary vertices lie on the exact STEP edge curves, and repeated exports are byte-identical.

Use these flags when the default mesh density is wrong for the part:

```bash
--mesh-tolerance FLOAT           # chord tolerance RELATIVE to each component's
                                 # bounding diagonal (default 1.5e-3)
--mesh-angular-tolerance FLOAT   # max normal spread across a triangle edge,
                                 # radians (default 0.35)
```

Use tighter tolerances for visual fidelity on curved parts; use looser tolerances for large simple geometry when file size matters. The linear tolerance is relative (scale-free), not an absolute deflection in millimetres.

## Workflow

1. Validate the model per the standard workflow (generate, inspect, snapshot).
2. Run `cadgen step export` with the requested format flag(s).
3. Report the exported files.

Example — write the STEP during generation, then mesh exports from the same generator:

```bash
python models/bracket.py

cadgen step export models/bracket.py \
  --stl meshes/bracket.stl \
  --glb meshes/bracket.glb \
  --mesh-tolerance 5e-3 \
  --mesh-angular-tolerance 0.5

cadgen step inspect refs models/bracket.step --facts --planes --positioning
```

## Reporting

```text
Files:
- STEP: /absolute/project/models/bracket.step
- STL: /absolute/project/models/meshes/bracket.stl
- GLB: /absolute/project/models/meshes/bracket.glb

Validation:
- CAD geometry validated; STL/3MF/native GLB written as requested exports.
- Primary STEP/STP snapshot packet run/skipped and why.
```
