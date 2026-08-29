---
name: dxf
description: Generate, regenerate, and validate 2D DXF drawings from Python ezdxf sources. Use for DXF files, `.py` generators, @dxf model scripts, 2D profiles, outlines, templates, gaskets, panels, flat patterns, laser/plasma/waterjet cut layouts, and 2D drawing exports of CAD geometry.
---

# DXF generation and validation

Provenance: maintained in [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad).
Use the installed local skill files as the runtime source of truth; the
repository link is only for provenance and release review.

## Setup

This skill's commands are thin entrypoints over the `cadgen` distribution, which
carries the Python build runtime and the JavaScript it executes. Install it once:

```bash
python -m pip install -r requirements.txt
```

Generation is pure Python (ezdxf). Only `cadgen dxf snapshot` additionally needs
**Node 20 or newer on `PATH`** — it meshes the flat pattern on demand through a
bundled Node one-shot; a missing `node` is reported at render time.

## Purpose

Create or modify 2D DXF drawings from natural-language requirements or from CAD geometry, generate validated drawing artifacts, and return checked outputs. A DXF drawing's source of truth is a dedicated Python generator file named `<name>.py` defining the `@dxf` model function; the CLI owns output paths.

The build product IS the `.dxf` file: **every run writes the sibling `<name>.dxf`**
(the same contract the model script has for STEP: source in, exchange file out; `-o`
or a `SOURCE=OUTPUT` pair renames it). There is no drawing package any more — the
CAD Viewer parses and meshes the `.dxf` itself, so the file you hand a cutting
service and the file the viewer renders are one and the same. The only thing kept
under `__cadgen__/models/<name>.py/` is a small output record that makes an
unchanged source a no-op. An unchanged source closure skips regeneration; `--force`
overrides.

## The three DXF workflows

Copy the full generator template for the applicable workflow from `references/generator-templates.md` when creating a new drawing.

1. **DXF generated from scratch** (standalone drafting — gaskets, panels, templates, cut layouts with no 3D model behind them): a `<name>.py` that builds an `ezdxf` document directly.

2. **DXF derived from a generated STEP part** (flat patterns / profiles of a `$cad` model): a drawing script beside the model script it projects, with its OWN stem (one model per file — `bracket_drawing.py` beside `bracket.py`). Model scripts are plain importable modules now; path-loading also works and records the closure the same way:

   ```python
   from pathlib import Path

   from cadgen import dxf
   from cadgen.sources import load_source_module

   _step = load_source_module(Path(__file__).with_name("bracket.py"))

   @dxf
   def drawing():
       return {"document": _step.build_dxf()}
   ```

   Keep the shared drawing logic (e.g. a `build_dxf()` helper that unfolds the part via `cadgen.flatten`) in the model script or a plain helper module; the drawing script is the entry point. The loaded model script and its imports are recorded in the drawing's source closure, so editing the 3D part automatically invalidates the cached drawing.

3. **DXF derived from an imported STEP** (a `.step`/`.stp` file with no Python source): a `<name>.py` that reads the STEP (e.g. `build123d.import_step`) and projects it with `cadgen.flatten`. Only Python sources are freshness inputs — like a `@step`-decorated model function that composes imported STEPs, the drawing does not auto-rebuild when the imported file changes; rerun with `--force` after replacing it.

One model per file: a source declaring both a `@step` and a `@dxf` model is rejected — a drawing gets its own script. The viewer catalog is artifacts-only: scripts never list; the `.dxf` the run writes is the entry the viewer renders.

## Use this skill when

Use this skill when the user asks for DXF files, 2D drawings, profiles, outlines, templates, gaskets, panels, flat patterns, or cut layouts for laser, plasma, waterjet, or CNC routing.

Use `$cad` for the 3D part or assembly a DXF derives from. Use `$sendcutsend` for SendCutSend-specific upload preflight.

## Defaults

Use these defaults unless the user specifies otherwise:

- Units: millimeters; set them explicitly on the document (`doc.units = ezdxf.units.MM`).
- Geometry lives in modelspace at 1:1 scale.
- Cut profiles are closed polylines or closed line/arc loops; open contours only for engraving or reference geometry (generation validation enforces this — see Validation).
- For CAD-backed parts, derive DXF cut contours from the actual STEP/solid topology with `cadgen.flatten`: select the real planar faces (`planar_faces`), project and union them (`union_projected_faces`), and emit clean closed contours (`add_shapely_geometry`). Use hand-drawn parametric outlines only when there is no reliable 3D topology to project.
- Apply kerf / tool-radius compensation with `cadgen.flatten.offset_geometry` / `offset_closed_points` when the cutting process requires it; do not hand-offset coordinates.
- Layers carry intent: keep cut geometry and bend/fold lines on separate layers, and include "bend" in bend-layer names so downstream tools classify them as bends rather than cuts.
- DXF layers are drawing structure, not STEP part/assembly structure.

## Tool

```bash
python <drawing>.py [flags]      # a @dxf model script writes its sibling .dxf
cadgen dxf snapshot --input <drawing> --output <file.png>   # render it
```

An imported `.dxf` needs no build step at all — the CAD Viewer renders it
directly — so there is no build command here.

Use the active project Python interpreter; treat `python` as an interpreter placeholder, and use `--help` for the full interface. Target paths resolve from the command's current working directory; run from the workspace that owns the artifacts with cwd-relative target paths. Keep a drawing generator in the same directory as the geometry it derives from, named `<name>.py`.

A DXF target is a Python source defining:

```python
@dxf
def drawing():
    ...
    return {"document": document}  # or a bare ezdxf document
```

Every run writes the target's sibling `<name>.dxf` (byte-deterministic: an
unchanged drawing produces an identical file). Flags:

- `-o`/`--output PATH` — write to a custom path instead; only with one plain generated Python target.
- `SOURCE.py=OUTPUT.dxf` positional pairs — per-target custom output paths.
- `--force` — regenerate even when the recorded output is current (an unchanged source closure is otherwise skipped).
- `--validate` — validate existing `.dxf` FILES with the generation-time drawing checks instead of generating.

Do not put output paths in the the `@dxf` model function return value.

`cadgen dxf snapshot` renders a drawing's 3D flat pattern to a PNG still or an orbit GIF:

```bash
cadgen dxf snapshot --input path/to/imported.dxf --output review.png
cadgen dxf snapshot --input path/to/source.py --output turntable.gif --mode orbit
```

For a generator it makes the sibling `.dxf` current first (the ordinary gen no-op
gate), then meshes the flat pattern on demand through the bundled Node one-shot and
renders it through the shared snapshot CLI (`cadgen.snapshot_cli`) and the same
headless browser runtime every rendering skill uses — so geometry and materials
render identically to the CAD Viewer; the default `snapshot` theme differs from the
viewport only by dropping the grid, origin axis and shadows.

Flags: `--mode view|orbit|list`, `--camera`, `--theme`, `--size-profile`,
`--width`/`--height`, `--job`, `--force`, `--json`. Theme settings live under one
`--theme`, mirroring the viewer's Theme tab; the default theme is `snapshot`, Workbench
Light without the ground grid, origin axis or shadows. There is no `--display`, and no
selector, parameter, section or exploded options: a drawing carries no CAD topology, and
display settings are CAD topology settings.

No CLI inspects an existing `.dxf`. For entity/layer checks use `ezdxf` directly,
and `--validate` for the drawing checks; review geometry visually with `$cad-viewer`.

## Workflow

1. Convert the request into a short brief: outline dimensions, holes and slots, layers, units, output path, and validation targets.
2. Pick the workflow: standalone drafting, projection of a generated STEP (create and validate the STEP geometry with `$cad` first), or projection of an imported STEP (declare it in `sources`).
3. Write or edit the `<name>.py` source with meaningful dimensions as named parameters, reusing the STEP source's geometry helpers instead of duplicating formulas.
4. Run each drawing script directly (`python <drawing>.py`); do not sweep directories.

```bash
python path/to/source.py
python path/to/source.py -o path/to/output.dxf
python path/to/a.py=out/a.dxf path/to/b.py=out/b.dxf
```

5. Validate the generated DXF deterministically, then hand off and report.

## Viewer integration

The CAD Viewer catalogs `.dxf` files only (artifacts, never scripts) and is a static visualization tool: it renders the `.dxf` that exists on disk (parsing and meshing it itself — 2D line work for dimensioned drawings, a fold-able 3D flat pattern for cut layouts) and never runs a script. A drawing with no `.dxf` yet simply does not appear until its script has been run; regenerating after edits is likewise the script's job. There is no in-viewer export. An imported `.dxf` renders directly with no artifact management.

## Validation

Validation happens IN generation, not after: every the `@dxf` model function build runs the drawing checks on the in-memory document before the package or any export is written, and a build with error findings fails. The checks: cut-layer profiles must close (polylines, circles, or chained line/arc loops), zero-length/degenerate entities are rejected, exact duplicate geometry (double-cut risk) is rejected, explicitly unitless documents are rejected, and an empty modelspace is rejected. Open geometry is allowed only on bend/engrave/reference-intent layers (matched by name).

The same checks run post-hoc on any existing `.dxf` file:

```bash
python --validate path/to/file.dxf
```

Beyond the built-in checks, verify requested dimensions with targeted `ezdxf` reads (entity counts by layer, drawing extents, every dimension the user specified) against the generated sibling `.dxf` (or the custom output path when one was requested), and review geometry visually in the CAD Viewer:

```python
import ezdxf

doc = ezdxf.readfile("path/to/source.dxf")
msp = doc.modelspace()
profiles = [e for e in msp.query("LWPOLYLINE") if e.closed]
holes = msp.query('CIRCLE[layer=="0"]')
```

Report only checks that actually ran.

## Handoff

After creating or modifying DXF drawings, you must ALWAYS hand the explicit `.py` file path(s) to `$cad-viewer` when that skill is installed and include its live viewer link(s) in the final response. If `$cad-viewer` is unavailable or startup fails, report that and rely on `ezdxf` checks instead of silently omitting the handoff.

Final responses should include generated files, returned viewer links, validation actually run, and assumptions.
