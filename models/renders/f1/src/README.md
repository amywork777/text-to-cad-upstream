# f1 models

| Script  | Artifact       | Description                                       |
|---------|----------------|---------------------------------------------------|
| f1.py   | STEP/f1.step   | F1 concept car — 28 top-level occurrences         |

Build: `python src/f1.py`; unchanged models are no-op.

`lib/` holds the part builders. Read the two contracts first: `lib/spec.py` is
the coordinate system, package dimensions, suspension hardpoints, the DRS
four-bar and the material palette; `lib/surfaces.py` is the shared surface
vocabulary (airfoil family, blade family, body lofts) every part module builds
from, so the car has ONE surface language.

OCCURRENCE ORDER IS FROZEN — `f1.anim.js` addresses children as `#o1.N` in the
order `assemble()` adds them. The table lives in `f1.py`'s docstring; do not
reorder, insert or remove a child without updating both in the same change.

No `kinematics=`: both of this car's mechanisms are CLOSED LOOPS (the DRS is a
planar four-bar, the steering solves each wheel against a fixed-length track
rod), and typed mates evaluate pure forward kinematics on a TREE. Both solves
live in `f1.anim.js`, which is where the teardown belongs anyway. Clips:
`showcase` (the loop-closed timeline: car opens, engine stands alone, engine
opens, both reassemble), `drs`, `steering`, `teardown`, `engine`.

`../f1_stage.appearance.json` is the presentation stage (authored config, not
an artifact) — a cool key from high front-left, a hot rim from behind-right,
and a dark specular floor. Its `_comment` records why the materials are satin
rather than piano-black; read it before retuning.
