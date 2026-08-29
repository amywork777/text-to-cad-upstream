---
name: cad-project
description: Opinionated project structure for multi-part CAD work - mirrored src layout, naming, shared code, and commit policy for projects with several @step/@dxf model scripts, format folders (STEP/, DXF/, STL/), and vendor imports. Use when starting a CAD project with more than a couple of models, when asked how to organize CAD code and artifacts, or when growing a flat folder of models into a project.
---

# CAD project structure

Provenance: maintained in [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad).

This skill is pure convention: cadgen itself is deliberately unopinionated (a
model script's artifact defaults to its sibling; `write=` relocates it). Use
this structure for anything bigger than a couple of loose models; skip it for
one-off parts, where a flat folder is fine. Authoring the models themselves is
the `$cad` skill; drawings are `$dxf`.

## The layout: src/ mirrors the output tree

```
<project>/
  src/                    # AUTHORED code — the only thing you edit
    README.md             #   the model catalog (required; see below)
    STEP/                 #   MIRRORED: src/STEP/<stem>.py -> STEP/<stem>.step
      bracket.py          #     one @step model per file
      arm.py
      _pose/              #     pose escape-hatch JS modules (declared via @step(pose=...))
    DXF/                  #   src/DXF/<stem>.py -> DXF/<stem>.dxf
      arm_drawing.py
    lib/                  #   ALL shared code (plain modules — never models)
      fasteners.py
  STEP/                   # PRIMARY artifacts (+ their source sidecars)
    bracket.step
    arm.step
    vendor_servo.step     #   imported vendor STEPs can live here too (committed);
  DXF/                    #   how a format folder organizes itself internally is
  STL/  GLB/  3MF/        #   project-dependent — only the top level is prescribed
  PNG/  GIF/              # snapshots / animations
```

Two mechanical rules:

1. **The mirror.** Code and artifact share the same relative path with the
   extension swapped: `src/STEP/bracket.py` generates `STEP/bracket.step`,
   `src/DXF/arm_drawing.py` generates `DXF/arm_drawing.dxf`. Mapping needs no
   table lookup — same path, other tree.
2. **Mirrored dirs hold ONLY generator scripts.** Every `.py` under
   `src/STEP/`, `src/DXF/`, ... is a runnable model — run it to build it.
   Everything shared goes in `src/lib/`. So `ls src/STEP/` IS the STEP model
   catalog (and with no artifacts checked out, `src/` is the whole catalog);
   `grep -rln "@step\|@dxf" src/` is the programmatic form.

Model scripts declare the routing themselves (cadgen has no layout knowledge):

```python
from cadgen import build123d as bd
from cadgen import step

@step(write="../../STEP/bracket.step")
def bracket(width: float = 10.0):
    return bd.Box(width, 10, 10)
```

`write=` resolves relative to the script, so the project relocates as a unit.
Build from anywhere: `python src/STEP/bracket.py`. Build-if-missing and
rebuild are the same command — the freshness gate runs first, so unchanged
models no-op in ~0.2s. Regenerate a whole project mechanically:

```bash
for f in src/STEP/*.py src/DXF/*.py; do python "$f"; done
```

The render package lives in the user-level store keyed by the artifact's
content hash, so the CAD Viewer resolves it from any project root, and
artifact→source provenance is recorded in the model-side sidecar
(`bracket.step.source.json`), never in the STEP file itself.

## Shared code: `src/lib/`

All helpers live in `src/lib/` as plain modules. Model scripts import them
with the one-line path shim (module-level, above the decorated function —
python puts the SCRIPT'S directory on `sys.path`, not `src/`):

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/

from lib import fasteners  # noqa: E402
```

The same shim lets models import each other's constants across mirrored dirs
(`from STEP.plate import WIDTH` inside a drawing) — importing a model module
never builds it. Running a `lib/` module directly defines things and exits 0:
that silence is correct, not a failed build — only mirrored-dir scripts build.

Cross-model geometry composition uses `cadgen.compose.child_entry` exactly as
the `$cad` skill documents:

```python
from cadgen.compose import child_entry
_ARM = child_entry(Path(__file__).with_name("arm.py"))
```

## Naming

- Model script stem = artifact stem = a Python identifier (`bracket.py` →
  `STEP/bracket.step`). Industry/exchange names (part numbers, revisions,
  spaces) go on the ARTIFACT via `write=` ("../../STEP/PN-10432_revB.step"),
  never into the stem — scripts must stay importable modules.
- A drawing gets its own stem: `arm_drawing.py` → `DXF/arm_drawing.dxf` (one
  model per file is a hard rule).
- Never distinguish files by case alone (macOS filesystems are usually
  case-insensitive).
- Vendor/imported STEPs keep their upstream names and get render packages via
  `cadgen import STEP/vendor_servo.step` ($cad).

## `src/README.md` — the model catalog (required)

Every project ships a short catalog so an agent landing in the project knows
what builds what without reading every script:

```markdown
# <project> models

| script               | artifact              | what it is                    |
|----------------------|-----------------------|-------------------------------|
| STEP/bracket.py      | STEP/bracket.step     | mounting bracket, param width |
| STEP/arm.py          | STEP/arm.step         | 2-link arm assembly           |
| DXF/arm_drawing.py   | DXF/arm_drawing.dxf   | arm flat pattern              |

Build: `python src/<path>.py` per row; unchanged models are no-ops.
Vendor imports: STEP/vendor_servo.step (committed, no script).
```

Keep it a table plus a few lines; update it whenever a model is added or
changed. Bigger projects may delegate to per-directory READMEs
(`src/STEP/README.md`, ...) forming a markdown tree — the root README then
lists the directories.

## Commit policy (a principle, not a layout)

Derived files are regenerable and typically ignored; authored files and
anything code cannot reproduce are committed:

1. **Authored** (`src/`): always committed.
2. **Generated** (the format folders): NOT committed by default —
   a fresh clone regenerates by running the scripts, and the shared
   content-addressed caches make that cheap (repeat runs near-instant).

   ```gitignore
   /STEP/*  /DXF/*  /STL/*  /GLB/*  /3MF/*  /PNG/*  /GIF/*
   !/STEP/vendor/
   ```

3. **Committed exceptions, made deliberately** (negation patterns or
   `git add -f`): vendor/imported files (no code can regenerate them — a
   code-only checkout must never be missing INPUTS, only derived outputs)
   and pinned fixtures — anything asserted against byte-for-byte, since
   regeneration on a newer kernel can legally change bytes for identical
   geometry.

## Safety properties this structure preserves

- Running any script is idempotent and locked: repeat runs no-op, concurrent
  runs of one model queue rather than race.
- The viewer opened at the project root catalogs the format folders'
  artifacts; scripts never appear (artifacts-only catalog). With no artifacts
  built yet the viewer shows an empty catalog — discovery in that state is
  `src/`, not the viewer.
- Deleting a format folder loses nothing authored — rerun the scripts.
- Moving/renaming the whole project breaks nothing: `write=` paths are
  script-relative and package provenance is folder-relative.

## Scaffolding a new project

Copy `references/project-template.md` — the full tree with a working example
model, drawing, lib module, README, and .gitignore to create verbatim. Then
verify the loop end to end: `python src/STEP/<first-model>.py`, snapshot it,
and confirm `STEP/` gained the artifact and its package. A living exemplar
ships in this repo at `models/projects/demo-plate/`.
