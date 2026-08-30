# cadgen

The CAD runtime behind [text-to-cad](https://github.com/earthtojake/text-to-cad):
STEP-first artifact generation on [build123d](https://github.com/gumyr/build123d) and
OCCT, and the command line that drives it. (The CAD Viewer is a separate standalone
app — [earthtojake/cad-viewer](https://github.com/earthtojake/cad-viewer) — bundled
by the cad-viewer skill, not by this package.)

```bash
pip install cadgen
python part.py  # a @step model script builds its STEP and render package
```

`cadgen` carries the JavaScript it executes as well as the Python. Mesh and drawing
builders run under Node and snapshots render in a headless browser — both ship inside
the wheel, so a single `pip install` is the whole runtime. Nothing is fetched at build
time and nothing is resolved relative to a checkout.

Two things it deliberately does not carry: **Node ≥ 20 on `PATH`** (needed only by the
DXF and mesh-export builders, resolved when they run, never at import), and a **browser**
for snapshots (`pip install 'cadgen[snapshot]'` then `python -m playwright install
chromium`). Plain STEP generation needs neither.

## Command line

Building is library-first: a model script declares one `@step` (or `@dxf`)
function and `python <model>.py` builds it — there is no `gen` verb. The CLI
covers everything downstream of a build:

| | |
|---|---|
| `step build` | make a model script's or an imported STEP/STP's derived state current |
| `stl build` / `3mf build` / `glb build` | write that model's mesh outputs, one door per format |
| `step inspect` / `step snapshot` | inspect selector references, render review images |
| `dxf snapshot` | render a DXF drawing |
| `snapshot` | render any supported input |
| `urdf validate` / `srdf validate` / `sdf validate` | validate robot descriptions |
| `cache` | inspect or garbage-collect the user-level caches |
| `daemon` / `daemon status` | opt-in warm process that holds OCP resident between builds |
| `doctor` | print installed cadgen and verify a skill's pin |

Dispatch is lazy: `cadgen --help` does not import the CAD stack.

Each command is also available as `python -m <module>`. The agent skills in
text-to-cad are instruction-only: they teach these same commands rather than
shipping entrypoints of their own.

## Python API

The supported surface is the root `cadgen` exports plus the top-level `cadgen.*` modules:

- **Format namespaces**: `cadgen.step`, `cadgen.stl`, `cadgen.threemf`, `cadgen.glb`.
  Each is one object: the declaration decorator (`@step`, `@stl`, ...) AND that
  format's verbs (`step.build(...)`, `stl.build(...)`), returning the typed
  results in `cadgen.results`. Every `cadgen <format> <verb>` command is that
  function with a parser derived from its signature, so the library call and the
  command cannot disagree.
- **Generator-script helpers**, all at the root: `AssemblyHelper`, `MateRelation`,
  `MateTarget`, `label_text`, `label_shape`, `target`, `report`, `track`, `srgb`,
  `compound_from_instances`, `ensure_step_topology_artifact`,
  `validate_step_topology_artifact`, and the STEP scene helpers `import_step`,
  `load_step_scene`, `located_shape`, `occurrence_selector_id`,
  `scene_occurrence_shape`. Resolved lazily, so `import cadgen` does not pay for OCP.
- **2D generators**: `cadgen.sources` (`load_source_module`) and `cadgen.flatten`
  (planar-face projection/unfold, contour emission, kerf offsetting) for `@dxf` drawings.
- **Build and inspection**: `cadgen.generation` (`generate_step_targets`,
  `generate_dxf_targets`, `targets_include_output_pairs`), `cadgen.catalog`,
  `cadgen.metadata`, `cadgen.analysis`, `cadgen.lookup`, `cadgen.cad_ref_syntax`,
  `cadgen.selector_types`, `cadgen.reporting`, `cadgen.cli_logging`, `cadgen.render`,
  `cadgen.step_topology_artifact`, `cadgen.step_targets`, `cadgen.step_export`,
  `cadgen.drawing_checks`, `cadgen.drawing_render`.
- **Asset resolution**: `cadgen.assets` (`node_builders_dir`, `browser_runtime_dir`)
  — where the packaged JavaScript lives, resolved at call time.

`cadgen.cli` holds the argument parsers and `cadgen.daemon` the warm build
process (the CAD Viewer's backend is pure Node, in the separate viewer app).
Everything under `cadgen._internal` is private
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
after changing anything under `packages/cadjs`:

```bash
scripts/bundle/bundle-skill.sh cadgen-runtime
```

`cadgen.assets` prefers a checkout's live `packages/cadjs/bin` over the packaged copy,
so builder JavaScript stays editable without rebundling.

To check the package the way a user receives it — installed, from a directory that is
not the repo — run `scripts/test/test-installed.sh`.
