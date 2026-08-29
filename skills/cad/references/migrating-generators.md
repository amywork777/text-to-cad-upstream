# Migrating legacy generators to model scripts

Read this when a build fails with "legacy generator" or "retired .step.py/.dxf.py
naming". The magic-name `gen_step()`/`gen_dxf()` contract and the double-suffix
naming are retired with NO backwards compatibility: a model is now a plain `.py`
script that builds itself.

## Before / after

```python
# bracket.step.py (retired)              # bracket.py
from build123d import Box                from cadgen import build123d as bd
                                         from cadgen import step
def gen_step():
    return Box(10, 10, 10)               @step()
                                         def bracket(width: float = 10.0):
                                             return bd.Box(width, 10, 10)
```

Run it directly: `python bracket.py` (flags: `--force`, `--json`, `--verbose`,
`-o PATH`, `--mesh-tolerance`, `--mesh-angular-tolerance`, `--lock-timeout`).
Drawings are the same shape with `@dxf` and the unchanged gen_dxf return
contract (an ezdxf document, bare or in a `{"document": ...}` envelope).

## The codemod

Mechanical migration, one file at a time:

```bash
python -m cadgen.migrate path/to/model.step.py     # add --no-rename to keep the filename
```

It renames `gen_step` to a function named after the file, decorates it, rewrites
`from build123d import X` imports to the lazy `bd.` idiom, and renames the file
to plain `.py`. Files it cannot transform safely are reported and left
untouched — migrate those by hand using the shape above.

## Verify the migration

Content addressing makes "same geometry" checkable: rebuild and compare the
package's component content hashes against the pre-migration package.

```bash
python path/to/model.py --force
python - <<'EOF'
import json, pathlib
from cadgen.catalog import render_package_dir
d = json.loads((render_package_dir(pathlib.Path("path/to/model.step")) / "assembly.json").read_text())
print(sorted(e["contentHash"] for e in d["components"].values()))
EOF
```

Identical hash lists = identical geometry. (Written DXF bytes are pure
drawing content — no identity comments — so a rename changes nothing.)

## What changed underneath

- Everything the model needs must be defined ABOVE the decorated function
  (decoration-time execution); importing the module never builds; calling the
  function returns the shape (composition: `import bracket; bracket.bracket()`,
  or `cadgen.compose.child_entry` for the cached seam).
- One `@step` or `@dxf` model per file.
- Declared options move into the decorator: `write=` (output path, relative to
  the script), `kind=` ("part"/"assembly", else inferred from the return),
  `mesh_tolerance=`, `mesh_angular_tolerance=`. Envelope returns
  (`{"shape": ..., "params": ..., "stl": ..., "3mf": ...}`) keep working.
- The render package records artifact→source provenance, so nothing depends on
  filenames pairing up any more; the viewer catalogs artifacts only.
- `scripts/gen` and `cadgen step gen`/`cadgen dxf gen` are gone. Imported
  foreign STEP/STP files use `cadgen import`.
