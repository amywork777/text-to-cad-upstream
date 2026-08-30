---
name: cad-project
description: Opinionated project structure for multi-part CAD work - src/ for model scripts and shared code, format folders (STEP/, DXF/, STL/) for raw outputs, naming, and commit policy for projects with several @step/@dxf model scripts and vendor imports. Use when starting a CAD project with more than a couple of models, when asked how to organize CAD code and artifacts, or when growing a flat folder of models into a project.
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
    README.md             #   the model catalog (required; see below)
    plate.py              #   one @step/@dxf model per file
    plate_drawing.py
    lib/                  #   ALL shared code (plain modules — never models)
      holes.py
    pose/                 #   pose escape-hatch JS modules, declared via
                          #   @step(pose=...) ($cad documents posing)
  STEP/                   # raw outputs ONLY (+ their source sidecars)
    plate.step
    vendor/               #   committed vendor/imported STEPs (see commit policy)
  DXF/  STL/  GLB/  3MF/  # other format folders, outputs only
  tmp/                    # scratch: snapshots, animations, debug renders (gitignored)
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
2. **`src/` top level holds ONLY runnable model scripts.** Every `.py`
   directly under `src/` is a model — run it to build it. Everything shared
   goes in `src/lib/`. So `ls src/*.py` IS the model catalog (and with no
   artifacts checked out, `src/` is the whole project);
   `grep -rln "@step\|@dxf" src/` is the programmatic form.

Because scripts sit directly in `src/`, no `sys.path` shim is needed: python
puts the script's own directory — `src/` — on `sys.path`, so shared code and
sibling models import directly, from any working directory:

```python
from lib import fasteners
from plate import WIDTH        # constants from another model; importing never builds
```

Running a `lib/` module directly defines things and exits 0: that silence is
correct, not a failed build — only top-level `src/` scripts build. Prefer a
flat `src/`; if a big project must nest model scripts in subfolders, each
nested script needs the one-line path shim back
(`sys.path.insert(0, str(Path(__file__).resolve().parents[1]))`) so `lib`
still resolves.

Build from anywhere: `python src/plate.py`. Build-if-missing and rebuild are
the same command — the freshness gate runs first, so unchanged models no-op in
well under a second. Regenerate a whole project mechanically:

```bash
for f in src/*.py; do python "$f"; done
```

The render package lives in the user-level store keyed by the artifact's
content hash, so the CAD Viewer resolves it from any project root, and
artifact→source provenance is recorded in the model-side sidecar
(`plate.step.source.json`), never in the STEP file itself.

Cross-model geometry composition uses `cadgen.compose.child_entry` exactly as
the `$cad` skill documents:

```python
from cadgen.compose import child_entry
_ARM = child_entry(Path(__file__).with_name("arm.py"))
```

## Naming

- Model script stem = artifact stem = a Python identifier (`plate.py` →
  `STEP/plate.step`). Industry/exchange names (part numbers, revisions,
  spaces) go on the ARTIFACT via `write=` ("../STEP/PN-10432_revB.step"),
  never into the stem — scripts must stay importable modules.
- A drawing gets its own stem: `plate_drawing.py` → `DXF/plate_drawing.dxf`
  (one model per file is a hard rule).
- Never distinguish files by case alone (macOS filesystems are usually
  case-insensitive).
- Vendor/imported STEPs keep their upstream names, live in `STEP/vendor/`,
  and get render packages via `cadgen import STEP/vendor/servo.step` ($cad).

## `src/README.md` — the model catalog (required)

Every project ships a short catalog so an agent landing in the project knows
what builds what without reading every script:

```markdown
# <project> models

| script           | artifact              | what it is                    |
|------------------|-----------------------|-------------------------------|
| plate.py         | STEP/plate.step       | mounting plate, param `hole_d`|
| arm.py           | STEP/arm.step         | 2-link arm assembly           |
| plate_drawing.py | DXF/plate_drawing.dxf | plate flat pattern            |

Build: `python src/<script>` per row; unchanged models are no-ops.
Vendor imports: STEP/vendor/servo.step (committed, no script).
```

Keep it a table plus a few lines; update it whenever a model is added or
changed.

## Commit policy (a principle, not a layout)

Derived files are regenerable and typically ignored; authored files and
anything code cannot reproduce are committed:

1. **Authored** (`src/`): always committed.
2. **Generated** (the format folders): NOT committed by default —
   a fresh clone regenerates by running the scripts, and the shared
   content-addressed caches make that cheap (repeat runs near-instant).
   Snapshots, animations, and other review renders are scratch, not
   artifacts: they go to `tmp/`, which is always ignored wholesale.
3. **Committed exceptions, made deliberately**: vendor/imported files under
   `STEP/vendor/` (no code can regenerate them — a code-only checkout must
   never be missing INPUTS, only derived outputs) and pinned fixtures —
   anything asserted against byte-for-byte, since regeneration on a newer
   kernel can legally change bytes for identical geometry. Pin a loose file
   with its own negation line or `git add -f`.

```gitignore
/STEP/*
!/STEP/vendor/
/DXF/*
/STL/*
/GLB/*
/3MF/*
/tmp/
__pycache__/
```

Note the `*` forms: ignoring the directory itself (`/STEP/`) would make the
vendor negation dead — git never descends into an ignored directory.

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
verify the loop end to end: `python src/<first-model>.py`, snapshot it, and
confirm the format folder gained the artifact and its package. A living
exemplar ships in this repo at `models/projects/demo-plate/`.
