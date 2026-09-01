# Converting an old generator source into a model script

A CAD model is a plain `.py` script that builds itself: one `@step` or `@dxf`
decorated function per file. Older corpora sometimes hold sources written to a
different shape — a magic `gen_step()`/`gen_dxf()` function, a `<name>.step.py`
or `<name>.dxf.py` filename. cadgen does not read those; converting one is a
hand edit, and this page is the recipe.

## Before / after

```python
# bracket.step.py (old source)           # bracket.py (a model script)
from build123d import Box                from cadgen import build123d as bd
                                         from cadgen import step
def gen_step():
    return Box(10, 10, 10)               @step()
                                         def bracket(width: float = 10.0):
                                             return bd.Box(width, 10, 10)
```

Four mechanical steps:

1. **Rename the file** to plain `.py` (`bracket.step.py` → `bracket.py`). The
   artifact defaults to the sibling `<stem>.step`, so the STEP path is unchanged.
2. **Name the function** after the file and decorate it: `@step()` (or `@dxf()`).
3. **Give every parameter a default** — the pipeline calls the function with no
   arguments. A `gen_step()` that took no arguments needs nothing here; promote
   module-level constants to defaulted parameters when you want them tunable.
4. **Rewrite `from build123d import X` to the lazy idiom**: `from cadgen import
   build123d as bd`, then `bd.X`. Same names, same objects on first touch, but a
   current model's re-run skips the ~2.5s kernel import.

Run it directly: `python bracket.py` (flags: `--force`, `--json`, `--verbose`,
`-o PATH`, `--mesh-tolerance`, `--mesh-angular-tolerance`, `--lock-timeout`).

## What has to move while you are in there

- **Everything the model needs is defined ABOVE the decorated function.**
  Decoration is what runs the build, so anything below it never executes.
- **One `@step` or `@dxf` model per file.** A source defining two must be split.
- **Declared options move into the decorator**: `out=` (output path, relative to
  the script), `kind=` (`"part"`/`"assembly"`, else inferred from the return),
  `mesh_tolerance=`, `mesh_angular_tolerance=`.
- **The return is geometry.** A `@step` returns a build123d `Shape`, or a
  `{"shape": ..., "stl": ..., "3mf": ..., "mesh_tolerance": ...,
  "mesh_angular_tolerance": ...}` envelope — those are the only fields. A `@dxf`
  returns build123d 2D geometry (a bare shape → the `CUT` layer, or
  `{"CUT": ..., "ENGRAVE": ...}`); the engine writes the DXF bytes.
- **Articulation is `kinematics=` on the decorator** (typed mates, couplings,
  pose presets) with choreography in a `<name>.anim.js` module named by
  `animation=`. See `references/kinematics.md`.
- **Mesh outputs are stacked decorators**: `@stl`, `@glb`, `@threemf` above or
  below `@step`. See `references/supported-exports.md`.
- **Composition imports the module and calls the function**
  (`import bracket; bracket.bracket()`), or wraps it with `cadgen.compose.memo`
  for the cached seam. Importing a model module never builds.

## Verify the conversion

Content addressing makes "same geometry" checkable: rebuild and compare the
package's component content hashes against the pre-conversion package.

```bash
python path/to/model.py --force
python - <<'EOF'
import json, pathlib
from cadgen.catalog import render_package_dir
d = json.loads((render_package_dir(pathlib.Path("path/to/model.step")) / "assembly.json").read_text())
print(sorted(e["contentHash"] for e in d["components"].values()))
EOF
```

Identical hash lists = identical geometry. (Written DXF bytes are pure drawing
content — no identity comments — so a rename changes nothing.)

Imported foreign STEP/STP files need no conversion and no build step: every door
makes what it needs on demand. `cadgen step build IN OUT` re-emits one as a new
document when you want cadgen's own bytes, or want to attach kinematics to it.
