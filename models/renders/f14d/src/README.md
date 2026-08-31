# f14d models

| Script   | Artifact         | Description                                        |
|----------|------------------|----------------------------------------------------|
| f14d.py  | STEP/f14d.step   | Grumman F-14D Super Tomcat, whole aircraft, clean   |

Build: `python src/f14d.py`; unchanged models are no-op. It is a long build
(the airframe skin's structural cuts dominate), so let it run.

`f14d.anim.js` is not a model — it is the choreography module `f14d.py`
declares with `animation=`, and the CAD Viewer's Animation tab is its only
consumer (clips: `teardown`, `explodedHold`). It sits beside its script.

`lib/` is the shared part library: one module per aircraft system, each
exporting `build()`. Nothing in `lib/` is runnable — `f14d.py` composes them,
and the SYSTEMS list in that file IS the occurrence order (`o1.1` airframe
through `o1.10` details). Read its docstring before adding or removing a
system: a new group renumbers every occurrence after it and `f14d.anim.js`
must be renumbered in the same commit.

Project tooling lives outside `src/` because it is not model code:

- `../validate.py` — bilateral-symmetry check plus `inspect validate` and
  `inspect interfere`.
- `../render/` — review-render helpers (`shot.py`, `gauntlet.py`, `part.py`,
  `ab.py`, `subrefs.py`) and the committed presentation theme/display JSON.
  `subrefs.py` regenerates the act-2 occurrence-id lists in `f14d.anim.js`.
  All of them write to `../tmp/`.
