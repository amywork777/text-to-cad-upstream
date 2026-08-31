# Demo Models

Curated model fixtures and generator assets for text-to-cad workflows.

This tree is intended to be committed with Git LFS for large CAD, mesh, and
robot artifacts. Source generators and concise documentation remain normal
text files.

## Layout

```text
models/
├── examples/              demo parts and assemblies, as one cad-project
│   ├── src/               @step model scripts (+ lib/ helpers, .anim.js)
│   ├── STEP/              artifacts built by those scripts
│   ├── STL/ 3MF/ GLB/     the mesh exports a few of them declare
│   └── imported/          committed source STEPs (no script)
├── step/
│   └── mechanisms/        cad-project of imported, animated .step assemblies
├── renders/               concept packages, one cad-project each
│   ├── f1/ f14d/ hypercar/ moonwatch/ motorbike/ qdd_actuator/
│   ├── falcon_heavy/                                  (SpaceX reconstruction)
│   └── juno/ lyra/                                    (robot descriptions)
├── drawings/              2D DXF fixtures, as one cad-project
│   ├── src/               @dxf model scripts (+ lib/ helpers)
│   └── DXF/               drawings built by those scripts (+ imported/)
└── robots/                imported robot fixtures with URDF/SRDF
    └── elrobot/ lekiwi/ openarm/ so101/ tom/
```

**Where does a new model go?** If it is one self-contained model script, it
belongs in the `examples/` cad-project: the script in `examples/src/`, its
artifact declared into a format folder with `out=`. If it needs a folder of its
own — helper modules, per-link generators, research/provenance docs, a
`render/` config — it belongs in `renders/`. Robot fixtures imported from
elsewhere go in `robots/`.

Generated output (`.step`/`.stl`/`.3mf`/`.glb` exports and their `.step.json`
sidecars) is gitignored — never commit it; a fresh clone regenerates by running
the scripts.

## Directory Map

- [examples/](examples/src/README.md): the demo corpus as one cad-project —
  every part and assembly is a `@step` model script directly under
  `examples/src/` (shared helpers in `src/lib/`, `.anim.js` choreography beside
  the scripts they belong to), and every artifact lands in a root-level format
  folder. Two models (`planetary_gear_assembly`, `mars_rover_concept`) carry
  typed mates and animation clips; a handful declare STL/3MF/GLB exports so the
  mesh doors have fixtures. `examples/imported/import-smoke.step` is a
  committed SOURCE, not an output.
- `step/`:
  - [step/mechanisms/](step/mechanisms/README.md): a cad-project whose
    content is `imported/` — annotated mechanism STEPs, each with a
    new-format `.step.json` sidecar (kinematics + animation) and its
    authored `.kinematics.json` / `.anim.js` sources.
  - `models/renders/` and `models/robots/` (below) are the only other places
    STEP files belong — both keep STEP sources inside self-contained project
    folders.
- [renders/](renders/README.md): large concept renders and related
  experiments. Each is its OWN cad-project — `src/` for the model scripts and
  their shared `lib/`, format folders for the artifacts — rather than a flat
  folder of generators. All 9: the `f1`, `f14d`, `hypercar`, `moonwatch`,
  `motorbike` and `qdd_actuator` concept packages, the educational
  public-source `falcon_heavy` SpaceX reconstruction, and the `juno`/`lyra`
  robot description packages.
- [drawings/](drawings/src/README.md): small 2D DXF fixtures as one
  cad-project — `@dxf` model scripts in `src/`, their built drawings in `DXF/`
  (regenerate with `python models/drawings/src/<name>.py`; not committed), and
  imported permissively licensed `.dxf` files in `DXF/imported/` for tooling
  robustness tests.
- [robots/](robots/README.md): imported robot fixtures with URDF/SRDF — each
  keeps its own mix of STEP, mesh, and other file types alongside the robot
  description rather than splitting across the buckets above. (The authored
  juno/lyra robot description packages live in `renders/` with the other
  concept packages.)

The larger `mechbench/` and `mechbench2/` external datasets are intentionally
not included in this committed fixture tree.

## Git LFS Fetching

Repository LFS config excludes `models/**` from default LFS fetches so ordinary
checkout and publish jobs can avoid downloading every model blob. Fetch the
model artifacts explicitly when you need local bytes:

```bash
git lfs pull --include="models/**" --exclude=""
```

## Cleanup Policy

- Keep canonical sources (`*.py`, `*.urdf`, `*.srdf`, and docs)
  readable in normal Git.
- Keep durable generated fixtures (`*.step`, `*.stl`, `*.3mf`, `*.glb`, and
  `*.dxf`) in Git LFS.
- Do not commit supplementary media or sidecar metadata such as `*.png`,
  `*.mp4`, `*.gif`, or `*.json` unless a future workflow defines them as a
  required model artifact — a package's `render/` job/theme JSON configs
  (e.g. `renders/moonwatch/render/`) are the established exception.
- Do not commit local runtime debris such as `.DS_Store`, `__pycache__/`,
  `.cache/`, logs, or one-off timestamped review snapshots.
- Put temporary scratch artifacts under ignored local paths, not in this tree.
