---
name: cad-project
description: Project structure for multi-part CAD work - src/ for model scripts and shared code, format folders (STEP/, DXF/, STL/) for raw outputs, naming, and commit policy for projects with several @step/@dxf model scripts and imported source files. Use when starting a CAD project with more than a couple of models, when asked how to organize CAD code and artifacts, or when growing a flat folder of models into a project.
---

# CAD project structure

Provenance: maintained in [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad).

This skill is pure convention: cadgen itself is deliberately unopinionated (a
model script's artifact defaults to its sibling; `write=` relocates it). Use
this structure for anything bigger than a couple of loose models; skip it for
one-off parts, where a flat folder is fine. Authoring the models themselves is
the `$cad` skill; drawings are `$dxf`.

## The layout: code in `src/`, raw outputs in format folders

Only OUTPUTS are organized by format. Code is not: a model script is not a
"STEP thing" — it is authored Python that happens to emit a STEP.

```
<project>/
  src/                    # AUTHORED code — the only thing you edit
    README.md             #   the model catalog (see below)
    plate.py              #   one @step/@dxf model per file
    plate_drawing.py
    lib/                  #   shared code (plain modules — never models)
      holes.py
  STEP/                   # raw outputs ONLY (+ their source sidecars)
    plate.step
    imported/             #   committed source files brought in from outside (see commit policy)
  DXF/  STL/  GLB/  3MF/  # other format folders: same shape, outputs + imported/
  tmp/                    # scratch: snapshots, debug renders (gitignored)
```

Two mechanical rules:

1. **Format folders hold only raw artifacts.** Never code, never notes. Each
   model script declares its own destination — cadgen has no layout knowledge:

   ```python
   from cadgen import build123d as bd
   from cadgen import step

   @step(write="../STEP/plate.step")
   def plate(width: float = 10.0):
       return bd.Box(width, 10, 10)
   ```

   `write=` resolves relative to the script, so the project relocates as a
   unit.
2. **`src/` holds ONLY runnable model scripts.** Every `.py` directly under
   `src/` is a model — run it to build it. Everything shared goes in
   `src/lib/`. So `ls src/*.py` IS the model catalog.

Because scripts sit directly in `src/`, imports need no setup: python puts the
script's own directory — `src/` — on `sys.path`, so shared code and sibling
models import directly, from any working directory:

```python
from lib import fasteners
from plate import WIDTH        # constants from another model; importing never builds
```

Build from anywhere: `python src/plate.py`. Build-if-missing and rebuild are
the same command — the freshness gate runs first, so unchanged models no-op.
Regenerate a whole project mechanically:

```bash
for f in src/*.py; do python "$f"; done
```

The CAD Viewer opened at the project root catalogs the format folders'
artifacts (scripts never appear); before anything is built, discovery is
`src/`, not the viewer.

## Naming

- Model script stem = artifact stem = a Python identifier (`plate.py` →
  `STEP/plate.step`). Industry/exchange names (part numbers, revisions,
  spaces) go on the ARTIFACT via `write=` ("../STEP/PN-10432_revB.step"),
  never into the stem — scripts must stay importable modules.
- A drawing gets its own stem: `plate_drawing.py` → `DXF/plate_drawing.dxf`
  (one model per file).
- Never distinguish files by case alone (macOS filesystems are usually
  case-insensitive).
- Files brought in from outside — vendor downloads, supplier files, anything
  used as a SOURCE, whether rendered directly or composed into generated
  models downstream — keep their upstream names and live in the format
  folder's `imported/` subfolder (`STEP/imported/`, `DXF/imported/`, ...).

## `src/README.md` — the model catalog

Every project ships a short catalog so an agent landing in the project knows
what builds what without reading every script:

```markdown
# <project> models

| Script           | Artifact              | Description                   |
|------------------|-----------------------|-------------------------------|
| plate.py         | STEP/plate.step       | Mounting plate, param `hole_d`|
| plate_drawing.py | DXF/plate_drawing.dxf | Plate flat pattern            |

Build: `python src/<script>` per row; unchanged models are no-ops.
Imported sources: STEP/imported/servo.step (committed, no script).
```

Keep it a table plus a few lines; update it whenever a model is added or
changed.

## Commit policy (a principle, not a layout)

Derived files are regenerable and typically ignored; authored files and
anything code cannot reproduce are committed:

1. **Authored** (`src/`): always committed.
2. **Generated** (the format folders): NOT committed by default — a fresh
   clone regenerates by running the scripts. Snapshots and other review
   renders are scratch, not artifacts: they go to `tmp/`, always ignored.
3. **Committed exceptions, made deliberately**: imported source files under
   any format folder's `imported/` (no code can regenerate them — a
   code-only checkout must never be missing INPUTS, only derived outputs)
   and pinned fixtures —
   anything asserted against byte-for-byte, since regeneration on a newer
   kernel can legally change bytes for identical geometry. Pin a loose file
   with its own negation line or `git add -f`.

```gitignore
/STEP/*
!/STEP/imported/
/DXF/*
!/DXF/imported/
/STL/*
!/STL/imported/
/GLB/*
!/GLB/imported/
/3MF/*
!/3MF/imported/
/tmp/
__pycache__/
```

Note the `*` forms: ignoring the directory itself (`/STEP/`) would make the
`imported/` negation dead — git never descends into an ignored directory.

## Scaffolding a new project

Copy `references/project-template.md` — the full tree with a working example
model, drawing, lib module, README, and .gitignore to create verbatim. Then
verify the loop end to end: `python src/<first-model>.py`, snapshot it, and
confirm the format folder gained the artifact. A living exemplar ships in
this repo at `models/projects/demo-plate/`.
