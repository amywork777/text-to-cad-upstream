# CAD kinematics and animation

Read this file when the user asks to articulate, pose, or animate a STEP
model, or when designing or reviewing mates, couplings, pose presets, posed
exports, or animation clips.

There are THREE systems with different lifecycles, deliberately independent:

- **Geometry parameters** are the model function's signature
  (`def bracket(width: float = 10.0)`). Changing one re-runs Python and
  rebuilds the artifact. They are not live in the viewer.
- **Kinematics** is typed mates declared as PURE DATA via `kinematics=` on
  the export decorators. It drives the viewer's pose sliders and bakes posed
  exports — no rebuild, no Python at render time. It lives in the model's
  sidecar (`<name>.step.cadgen.json`, written beside the artifact).
- **Animation** is choreography in a plain `.js` module declared via
  `@step(animation="<name>.anim.js")`, whose TEXT is copied into the same
  sidecar. It targets occurrences directly and knows nothing about mates.
  Editing kinematics or animation never re-keys a render package and never
  dirties an export.

## Kinematics: typed mates

One `kinematics=` dict, closed keys `mates` / `couplings` / `poses`, on any
of `@step`/`@stl`/`@glb`/`@threemf`. Each decorator's declaration stands
alone (share a module-level dict; there is no cross-decorator inheritance).

```python
import cadgen
from cadgen import step
from cadgen import build123d as bd

KINEMATICS = {
    "mates": [
        cadgen.revolute("elbow", parent="#upper_arm", child="#forearm",
                        axis="#forearm.pivot_bore", limits=(0, 150)),
        cadgen.slider("extend", parent="#rail", child="#carriage",
                      axis="#rail.f2", limits=(0, 80)),
        cadgen.cylindrical("lead", parent="#housing", child="#screw",
                           axis="#screw.f1",
                           limits={"turn": (0, 3600), "travel": (0, 40)}),
        cadgen.fastened("mount", parent="#carriage", child="#bracket"),
    ],
    "couplings": [cadgen.couple("curl", {"mcp": 50, "pip": 70, "dip": 40})],
    "poses": {"open": {"jaw": 40}, "closed": {"jaw": 0}},
}

@step(out="../STEP/arm.step", kinematics=KINEMATICS,
      animation="arm.anim.js")
def arm(): ...
```

- **Mate kinds**: `revolute` (degrees about an axis), `slider` (model units
  along it), `cylindrical` (sub-DOFs `<name>.turn` and `<name>.travel` about
  one axis), `fastened` (0-DOF rigid attachment — needed exactly when
  occurrences are SIBLINGS in the instance tree, like a pin that must orbit
  with its carrier; instance-tree children ride for free).
- **`parent`/`child`** are occurrence refs: `#`-prefixed labels (canonical —
  label parts with `cadgen.label_shape`) or occurrence ids. They must resolve
  at build or the build fails; `cadgen step inspect refs` lists both.
- **`axis`** is a selector ref (`axis="#forearm.pivot_bore"` — a cylindrical
  face or circular edge yields its axis, a planar face its center+normal) or
  literals (`origin=(x, y, z), direction=(x, y, z)`). Refs resolve ONCE at
  build into world numbers; the viewer does arithmetic, never topology.
- **ZERO IS THE ARTIFACT AS WRITTEN.** Every DOF's rest value is 0 — the
  placement the author built (or the baked pose, below). There is no
  `default=`; a presentation pose is a preset or a bake.
- **`couple(name, {dof: ratio})`** declares a virtual DOF gearing real ones
  linearly and ADDITIVELY (setting `curl=x` adds `50*x` degrees to `mcp`).
  Exact gear trains are ratio arithmetic, not code.
- **`poses`** are named `{dof: value}` presets — all that remains of "pose"
  as a concept.
- The mate graph is a TREE: one parent mate per occurrence, no cycles.
  Closed-loop linkages (four-bars) are out of scope by design — they need a
  solver; cadgen evaluates pure forward kinematics, identically in Python
  and the viewer, so a slider position and an exported bake agree to the bit.

## Export at pose

`pose=` (a preset name or `{dof: value}` dict) on the SAME decorator bakes
that artifact at the configuration:

```python
@step(out="gripper.step", kinematics=KINEMATICS, pose="closed")
@stl(out="gripper_open.stl", kinematics=KINEMATICS, pose="open")
@stl(out="gripper_closed.stl", kinematics=KINEMATICS, pose="closed")
```

The written artifact is its own q=0: a baked STEP's sidecar shifts limits and
re-zeroes presets to describe the file as written. Mesh bakes are transient —
stl/glb/3mf never have sidecars or animation. The mesh freshness ledger keys
on the pose, so posed and rest variants never satisfy each other's no-op
gates.

## Animation: the .anim.js contract

```js
// arm.anim.js — beside the model script; TEXT is copied into the sidecar.
export const clips = {
  demo: {
    label: "Demo",
    duration: 8,          // seconds
    loop: true,           // default
    update(t, m) {        // called every frame; t in seconds
      m.get("forearm").rotate([0, 0, 1], 120 * (t / 8), [0, 0, 25]);
      m.get("#o1.3.1,o1.3.2").translate([0, 0, 40 * Math.min(t / 2, 1)]);
      m.get("lid").opacity(t < 5 ? 1 : 1 - (t - 5) / 2);
    },
  },
};
```

- `m.get(target)` takes a LABEL (canonical) or occurrence-id refs
  (`"#o1.3.1"`, comma lists; each id covers its whole subtree). Unknown
  targets THROW — a typo never silently animates nothing.
- Handles: `.rotate(axis, degrees, origin=[0,0,0])`, `.translate(vec)`,
  `.opacity(0..1)`, `.visible(bool)`. Successive transform calls
  PREMULTIPLY: spin about a part's own center first, then orbit the origin,
  and the spin rides the orbit.
- Every frame starts from rest and `update(t)` rebuilds the state — a pure
  function of t, so scrub/loop/seek are free. No wall-clock, no state.
- Animation is deliberately Turing-complete and deliberately ignorant of
  mates: animating a jointed part re-describes the motion (a few lines of
  ratio math). That independence is what guarantees choreography edits can
  never invalidate builds.
- The declared file must exist (no convention discovery); a missing
  `animation=` target fails the build loudly.

## Reviewing motion

Snapshot renders stills; motion review is interactive in the viewer. For
still evidence of a configuration, render at DOF values:

```bash
cadgen step snapshot --input STEP/arm.step --output tmp/open.png --params '{"jaw": 40}'
```

Identify fixed pivots, link lengths, gear ratios, and joint limits BEFORE
declaring mates; pivot every rotation about its hinge bore or mate face —
never a bounding-box center. Convert visual concerns into `cadgen step
inspect measure` checks before calling them fixed.

## Migration from the retired pose framework

`cadgen.pose(params/features/joints/drivers/animations/module)` and the
`.params.js` sidecars are gone (hard cutover). The mapping: features+joints →
mates (axes by selector ref); ratio drivers → `couplings`; params that moved
geometry → mate DOFs; params that toggled styles/visibility → animation
clips or viewer display settings; keyframe animations and escape-hatch
modules → the `.anim.js` contract above.
