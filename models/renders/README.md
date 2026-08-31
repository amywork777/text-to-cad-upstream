# Renders

Large concept renders and related experiments — every model that needs a
**folder of its own** rather than a single loose script.

**Each folder here is its own cad-project**, in the layout the `$cad-project`
skill defines: authored code in `src/` (one `@step` model per file, shared
modules in `src/lib/`, animation modules beside their script), raw artifacts in
format folders (`STEP/`, `3MF/`, ...), scratch in `tmp/`, and a `.gitignore`
that keeps the artifacts out of the repo. A fresh clone has no `STEP/` at all;
regenerate a project by running its scripts:

```bash
cd models/renders/<project>
ls src/*.py | xargs -n1 -P4 python     # unchanged models no-op
```

Each project's `src/README.md` is its model catalog — which script builds which
artifact — so start there rather than reading every file.

Single-file model scripts — parts and assemblies alike — live in the
[`../examples/`](../examples/src/README.md) cad-project instead.

## Concept packages

- [f1/](f1/src/README.md): open-wheel F1 car — a modular `lib/` build over one
  shared surface vocabulary, plus `f1_stage.appearance.json`, the authored
  presentation stage. Its DRS four-bar and rack-and-track-rod steering are
  CLOSED loops, so both solves live in `f1.anim.js` rather than in typed mates.
- [f14d/](f14d/src/README.md): Grumman F-14D Super Tomcat — one lofted airframe
  skin with ten systems grouped on top of it, a staged teardown in
  `f14d.anim.js`, and a `render/` suite of presentation configs and review
  tooling.
- [hypercar/](hypercar/src/README.md): mid-engine hypercar — modular `lib/`
  build with a `render/` presentation theme.
- [moonwatch/](moonwatch/README.md): chronograph wristwatch — shared finishing
  vocabulary, per-cluster helpers, eight entry models (`case`, `dial`,
  `movement_base`, `keyless_works`, `chrono_works`, `movement`, `bracelet`,
  `moonwatch` for the full watch) plus a `finishing_sampler` coupon, and a
  `render/` suite of presentation themes and job templates.
- [motorbike/](motorbike/README.md): retro step-through scooter — `lib/spec.py`
  is the hardpoint/palette source of truth and `lib/lib.py` the shared geometry
  vocabulary; 19 part models plus a 46-occurrence `motorbike` assembly with
  typed mates for steering, wheel spin, engine swing and the stand pivot.
- [qdd_actuator/](qdd_actuator/src/README.md): quasi-direct-drive actuator —
  one virtual `drive` DOF gears the rotor, carrier, both ball cages and the
  three planets through the 4.5:1 planetary reduction, with the exploded
  teardown in `qdd_actuator.anim.js`.

## SpaceX reconstruction package

> **Educational, non-functional public-source reconstruction. Not suitable
> for manufacture, propulsion, testing, or operational engineering.**

A museum/documentary-style CAD package reconstructed exclusively from public
sources; proprietary internals are deliberately excluded and hidden internals
appear only as simplified translucent placeholder volumes. Its
`PROVENANCE.md`, `DIMENSIONS.md`, and `RESEARCH.md` carry the source,
confidence, and dimension tables.

- [falcon_heavy/](falcon_heavy/README.md): Falcon Heavy full vehicle — three
  cores with 27 linked Merlin 1D instances, MVac-derivative second stage,
  cutaway and exploded views (~2,150 named parts each). The Merlin 1D library
  is VENDORED into `src/lib/merlin_common.py`; the standalone Merlin 1D
  package it came from no longer lives in this repo, so the vendored copy is
  the source of truth.

## Robot description packages

- [juno/](juno/README.md): Juno humanoid — a 27-DOF biped: one model per link
  emitting both a STEP part and the 3MF mesh the URDF references, plus the
  authored `juno.urdf` / `juno.srdf`.
- [lyra/](lyra/README.md): Lyra dexterous hand — a 16-DOF five-digit hand, the
  same shape: per-link models with 3MF exports, authored `lyra.urdf` /
  `lyra.srdf`, and named poses shared between the SRDF group states and the
  STEP's kinematics presets.

These two carry URDF/SRDF but live here rather than in `../robots/` because
they are authored concept packages, not the imported robot fixtures that
`../robots/` collects. Their `3MF/` meshes are GENERATED and no longer
committed — build the link models before loading either URDF.

## Kinematics, animation, and per-package `render/` folders

A project's articulation is split three ways (see the `$cad` skill's
`kinematics.md`): geometry parameters are the model function's signature,
typed mates are pure data under the `@step` decorator's `kinematics=`, and
choreography is a `.js` module named by `animation=`. The retired `.params.js`
sidecars are gone from every package here.

Some packages keep a `render/` subfolder holding presentation-theme JSON,
snapshot job templates, and review tooling. Those configs are authored and
committed; anything they generate goes to the project's `tmp/`.
