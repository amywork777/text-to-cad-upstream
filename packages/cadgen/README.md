# cadgen

The CAD runtime behind [text-to-cad](https://github.com/earthtojake/text-to-cad):
STEP-first artifact generation on [build123d](https://github.com/gumyr/build123d) and
OCCT, the command line that drives it, and the CAD Viewer that shows you the result.

```bash
pip install cadgen
cadgen viewer                 # browse and inspect CAD in a local directory
cadgen step gen part.step.py  # build a STEP and its render package
```

`cadgen` carries the JavaScript it executes as well as the Python. Mesh and drawing
builders run under Node, snapshots render in a headless browser, and the Viewer is a
built SPA — all three ship inside the wheel, so a single `pip install` is the whole
runtime. Nothing is fetched at build time and nothing is resolved relative to a checkout.

Two things it deliberately does not carry: **Node ≥ 20 on `PATH`** (needed only by the
DXF and implicit builders, resolved when they run, never at import), and a **browser**
for snapshots (`pip install 'cadgen[snapshot]'` then `python -m playwright install
chromium`). Plain STEP generation needs neither.

## Command line

`cadgen <command>`, or the equivalent `python -m cadgen.<module>`:

| | |
|---|---|
| `step gen` / `artifact` / `export` / `inspect` / `snapshot` | build STEP targets from `.step.py` generators, build their GLB/topology artifacts, export to exchange files, inspect selector references, render |
| `dxf gen` / `artifact` / `snapshot` | the same for `.dxf.py` drawing generators |
| `implicit gen` / `export` / `snapshot` | implicit CAD models |
| `snapshot` | render any supported input |
| `viewer` | serve the CAD Viewer over a local directory |
| `daemon` | opt-in warm process that holds OCP resident between builds |

Dispatch is lazy: `cadgen --help` does not import the CAD stack.

The agent skills in text-to-cad are thin entrypoints over these same parsers, which is
why a skill command and its `cadgen` equivalent take identical arguments and print
identical output.

## Python API

The supported surface is the root `cadgen` exports plus the top-level `cadgen.*` modules:

- **Generator-script helpers**: root exports (`AssemblyHelper`, `MateRelation`,
  `MateTarget`, `label_text`, `label_shape`, `target`, `ensure_step_glb_artifact`,
  `validate_step_glb_artifact`), `cadgen.assembly`, and `cadgen.step_scene`
  (`import_step`, `load_step_scene`, `located_shape`, `occurrence_selector_id`,
  `scene_occurrence_shape`).
- **2D generators**: `cadgen.sources` (`load_source_module`) and `cadgen.flatten`
  (planar-face projection/unfold, contour emission, kerf offsetting) for `.dxf.py`.
- **Build and inspection**: `cadgen.generation` (`generate_step_targets`,
  `generate_dxf_targets`, `targets_include_output_pairs`), `cadgen.catalog`,
  `cadgen.metadata`, `cadgen.analysis`, `cadgen.lookup`, `cadgen.cad_ref_syntax`,
  `cadgen.selector_types`, `cadgen.reporting`, `cadgen.cli_logging`, `cadgen.render`,
  `cadgen.step_artifacts`, `cadgen.step_targets`, `cadgen.step_export`,
  `cadgen.drawing_checks`, `cadgen.drawing_render`.
- **Asset resolution**: `cadgen.assets` (`node_builders_dir`, `browser_runtime_dir`,
  `viewer_dist_dir`) — where the packaged JavaScript lives, resolved at call time.

`cadgen.cli` holds the argument parsers, `cadgen.viewer` the Viewer backend, and
`cadgen.daemon` the warm build process. Everything under `cadgen._internal` is private
implementation — the STEP scene, generation, GLB/topology and export engines — with no
import stability between releases. `cadgen.generation` and `cadgen.step_scene` are thin
facades over those engines that re-export only the supported names.

## Versioning

Released to PyPI by the repository's `Release` workflow. The package version always
matches the plugin release version, and published skills pin the exact release
(`cadgen==0.4.7`), so a skill and the runtime under it are never a version apart.

## Local development

From a text-to-cad checkout:

```bash
./.venv/bin/python -m pip install -e packages/cadgen
```

Source edits under `packages/cadgen/src/cadgen` take effect immediately. The packaged
JavaScript is generated rather than committed in full, so build it once — and again
after changing anything under `packages/cadjs`, `packages/implicitjs`, or `viewer/`:

```bash
scripts/bundle/bundle-skill.sh cadgen-runtime
```

`cadgen.assets` prefers a checkout's live `packages/cadjs/bin` over the packaged copy,
so builder JavaScript stays editable without rebundling. The Viewer client is the
exception: it is a Vite build, gitignored, and only present once bundled.

To check the package the way a user receives it — installed, from a directory that is
not the repo — run `scripts/test/test-installed.sh`.
