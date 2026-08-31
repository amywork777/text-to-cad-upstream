# Demo Models

Curated model fixtures and generator assets for text-to-cad workflows.

This tree is intended to be committed with Git LFS for large CAD, mesh, and
robot artifacts. Source generators and concise documentation remain normal
text files.

## Layout

```text
models/
├── step/                  STEP generator sources, one flat file per model
│   ├── parts/             single-body generators (no `children=`)
│   ├── assemblies/        multi-part generators (+ optional .params.js sidecar)
│   └── mechanisms/        cad-project of imported, animated .step assemblies
├── renders/               folder-per-model concept packages and experiments
│   ├── f1/ hypercar/ moonwatch/ qdd_actuator/ raptor3/ starship-mechazilla/
│   ├── raptor2/ merlin1d/ falcon_heavy/ starship/     (SpaceX reconstructions)
│   └── juno/ lyra/                                    (robot descriptions)
├── mesh/                  exported meshes, by format
│   ├── stl/  3mf/  glb/
├── drawings/              2D DXF fixtures, as one cad-project
│   ├── src/               @dxf model scripts (+ lib/ helpers)
│   └── DXF/               drawings built by those scripts (+ imported/)
└── robots/                imported robot fixtures with URDF/SRDF
    └── elrobot/ lekiwi/ openarm/ so101/ tom/
```

**Where does a new model go?** If it is one self-contained `<name>.step.py`
file, it belongs in `step/parts/` (single body) or `step/assemblies/`
(multi-part). If it needs a folder of its own — helper modules, per-link
generators, research/provenance docs, a `render/` config — it belongs in
`renders/`. Robot fixtures imported from elsewhere go in `robots/`.

Generated output (`__cadgen__/`, `.step` exports) is written on demand beside
the sources and is gitignored — never commit it.

## Directory Map

- `step/`: STEP generator sources, split by shape:
  - [step/parts/](step/parts/README.md): single-body `<name>.step.py`
    generators — structured fixtures, compact build123d examples, and other
    standalone demo parts.
  - [step/assemblies/](step/assemblies/README.md): flat multi-part
    `<name>.step.py` generators — one-shot concepts and standalone demo
    assemblies, each a single file plus an optional `.params.js` sidecar.
  - [step/mechanisms/](step/mechanisms/README.md): a cad-project whose
    content is `imported/` — annotated mechanism STEPs, each with a
    new-format `.step.json` sidecar (kinematics + animation) and its
    authored `.kinematics.json` / `.anim.js` sources.
  - `models/renders/` and `models/robots/` (below) are the only other places
    STEP files belong — both keep STEP sources inside self-contained project
    folders.
- [renders/](renders/README.md): large concept renders and related
  experiments — every model that needs a folder of its own rather than a flat
  generator file. All 12: the educational public-source SpaceX reconstruction
  packages (`raptor2`, `merlin1d`, `falcon_heavy`, `starship`), the `f1`,
  `hypercar`, `moonwatch`, `qdd_actuator`, `raptor3` and `starship-mechazilla`
  concept packages, and the `juno`/`lyra` robot description packages.
- [mesh/](mesh/README.md): exported `stl/`, `3mf/`, and `glb/` mesh artifacts —
  durable exports from `step/parts/` and `step/assemblies/` kept as fixtures
  for testing export/render behavior, organized by format.
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
