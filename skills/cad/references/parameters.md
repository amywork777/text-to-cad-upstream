# CAD parameters and pose

Read this file when the user asks to parameterize or animate a STEP model, or
when designing or reviewing CAD source parameters, viewer pose controls, or
animation clips.

There are TWO parameter systems with different lifecycles:

- **Geometry parameters** are the model function's signature
  (`def bracket(width: float = 10.0)`). Changing one re-runs Python and
  rebuilds the artifact. They are not live in the viewer.
- **Pose parameters** are declared on the decorator via `pose=cadgen.pose(...)`
  and drive the viewer live — joints, explodes, visibility, styles, and
  animation clips — with no rebuild and no Python at render time. The pose
  block travels inside the render package's generated source sidecar
  (`<package>/source.json`, written by the build alongside the descriptor);
  there are NO loose sidecar files (`.params.js` is retired — see Migration
  below).

## Principle

Parameters are part of the model contract. A good parameter makes design
intent explicit, maps to named geometry or motion, stays inside a valid range,
and gives both users and LLMs enough context to predict what changing it will
do. Prefer parameter logic that preserves the mechanism's constraints over
logic that only looks plausible from one camera angle.

## Naming

Use snake_case semantic names: `wall_thickness`, `hinge_angle_deg`,
`gear_ratio`, `exploded_distance` — never `offset2` or `slider_a`. Encode
units in names only when otherwise ambiguous (`_deg`, `_mm`, `_sec`). Keep
pose parameter ids, feature ids, UI labels, and source constants aligned
enough that a control can be traced to geometry.

## Declaring pose

```python
from cadgen import pose, step
from cadgen import build123d as bd

@step(kind="assembly", pose=pose(
    params={
        "drive": {"type": "number", "label": "Drive", "default": 0,
                  "min": 0, "max": 360, "step": 1, "unit": "deg"},
        "ringVisible": {"type": "boolean", "label": "Ring gear", "default": True},
    },
    features={
        "sun": {"ref": "#o1.3.1", "label": "Sun gear"},
        "carrier": {"ref": "#o1.1.1", "label": "Carrier"},
        "ring": {"ref": "#o1.2.1", "label": "Ring gear"},
    },
    joints=[
        {"id": "sun_spin", "feature": "sun", "kind": "rotate",
         "axis": [0, 0, 1], "origin": [0, 0, 0]},
        {"id": "carrier_rot", "feature": "carrier", "kind": "rotate",
         "axis": [0, 0, 1], "origin": [0, 0, 0]},
    ],
    drivers=[
        {"kind": "joint", "joint": "sun_spin", "param": "drive"},
        {"kind": "ratio", "joint": "carrier_rot", "source": "sun_spin", "ratio": 24 / 84},
        {"kind": "visible", "target": "ring", "param": "ringVisible"},
    ],
    animations={
        "meshCycle": {"label": "Mesh cycle", "duration": 6, "loop": True,
                      "tracks": [{"param": "drive",
                                  "keys": [{"t": 0, "value": 0}, {"t": 1, "value": 360}]}]},
    },
))
def planetary(): ...
```

The block validates at decoration time — a typo fails the build with an error
naming the offender, never a silent no-op at render time. Because the pose is
Python data, BUILD IT WITH CODE: loops over wheel tables, explode-vector
dicts, and sampled sine keyframes compress what used to be hundreds of
hand-written sidecar lines (see `models/step/assemblies/mars_rover_concept.py`
for the full-vocabulary example).

## The vocabulary (closed)

- **features** bind names to occurrences: `ref` (a `#o...` token, may carry
  several comma-joined selectors), `names` (occurrence-label matching —
  survives renumbering; prefer it where labels exist), `selectors` (a list),
  plus optional `label`/`axis`/`origin`.
- **joints** form a tree: `{id, feature, kind: rotate|translate, axis,
  origin?, parent?}`. A child's parts inherit every ancestor transform.
  Several joints may share a feature — the last-declared owns the feature's
  chain; earlier ones are chain links (e.g. chassis heave→pitch→roll).
  Rotations are degrees, translations millimetres.
- **drivers** (every scalar obeys `value = offset + scale * f(param)`, where
  `f` is identity or a `window: [a, b]` normalization + `easing` — one of
  linear, smoothstep, sine, easeIn, easeOut, easeInOut):
  - `joint` — drive a joint from a param (`scale`, `offset`, `window`,
    `easing`). Windowed drivers are how STAGED sequences work: many drivers
    on one master param, each with its own window.
  - `ratio` — couple a joint to an earlier-declared joint (`ratio`,
    `offset`). Gears and differentials.
  - `translate` — move features along a `direction` vector (or `"radial"`:
    outward from the origin through each feature's center) by
    `distance * f(param)`. Explodes. Applied OUTSIDE the joint chains.
  - `visible` — a boolean/enum param controls target visibility (`value`
    matches an enum option; `invert` flips).
  - `style` — either a lerp (`style: {opacity: {from: 1, to: 0.2}, ...}`
    driven by a param) or `palettes` (enum/boolean param value → per-target
    style maps). Style props: `opacity`, `edgeOpacity`, `color`, `emissive`,
    `emissiveIntensity`.
  - `scale` — uniform scale between `from`/`to` about `origin`.
- **animations** are keyframe clips: `{label, duration, loop, tracks:
  [{param, keys: [{t, value, easing?}]}]}` with `t` in [0, 1] of the
  duration. Numbers lerp (easing belongs to the destination key);
  booleans/enums step-hold. Sample sinusoids densely from Python rather than
  approximating with a few keys. Clips play in the viewer's parameter panel;
  snapshot renders stills only.

Anything outside this vocabulary is an ERROR by design — computational
behavior belongs in the escape hatch, not in new driver kinds.

## The escape hatch

`pose(..., module="_pose/my_model_extras.js")` names a JS module beside the
model source; the build copies it content-addressed into the render package.
It receives the full runtime contract AFTER the declarative pass each frame:
`setup({THREE, modelGroup, cleanup})`, `update({params, features, effects,
time})`, `dispose(ctx)` — including procedural scene overlays and time-gated
effects. Use it sparingly: solvers, IK, overlays. Worked example:
`models/step/assemblies/_pose/planetary_orbit_guide.js`.

Known limitation: editing ONLY the hatch `.js` does not change the Python
source closure, so a current model will not rebuild — run the model with
`--force` after hatch-only edits.

## Imported STEP files

A foreign `.step` has no pose. To animate one, promote it to an authored
model: a minimal script that wraps the import and declares the pose —

```python
@step(pose=pose(...))
def vendor_arm():
    return cadgen.read_step("vendor_arm_v3.step")
```

## Validation

- Identify fixed pivots, moving pivots, link lengths, gear ratios, axes, and
  joint limits BEFORE declaring joints; pivot every rotation about its hinge,
  mate, or local frame — never a bounding-box center.
- Review the animations in the viewer (play each clip) and check for
  disconnected hinges, drifting pivots, collisions, and looping jumps;
  convert visual concerns into measurements before calling them fixed.
  For still evidence, snapshot key poses with `--params` values.
- Eyeballed keyframes that violate real link lengths, and interpolating
  between two valid poses through invalid intermediate geometry, are the two
  classic failures.

## Migration from `.params.js` sidecars (retired)

Sidecars no longer load anywhere: the viewer ignores them (the params panel
says so) and snapshot `--params-path` is a hard error. Worked examples:
`mars_rover_concept.py` (clean map: joints/ratios/windows/palettes/keyframe
clips), `f14d.py` (staged windows + the style fade), and
`planetary_gear_assembly.py` (ratio couplings + the escape hatch).

Remaining corpus-migration work (belongs to the deferred models/ migration
task):

- migrate the remaining sidecar models to `pose=` (the corpus audit's mapping
  table freezes the vocabulary assignments), deleting each `.params.js` with
  its model;
- the four heavy-compute models (juno, f1, gd01_mecha, lunar_mass_driver)
  keep their data cores declarative and move their solvers into hatch
  modules;
- delete the scanner's `legacyParamsSidecar` teaching detection once no
  sidecar remains, and add a corpus policy test that no `.params.js` exists
  under `models/`.
