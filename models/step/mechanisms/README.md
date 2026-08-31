# Mechanism STEP demos

Mechanism assemblies inspired by the YouTube channel
[thang010146](https://www.youtube.com/@thang010146/videos). Original mechanism
design, animation, and downloadable source files are credited to
`thang010146`.

There is no `src/` here: nothing in this folder is generated from a model
script. `mechanisms/` is a STEP format folder holding one thing — imported
source documents and the annotations that ride with them — so the whole
project is `imported/`, flat, and committed (cad-project commit policy: no
code can regenerate an imported source, so a code-only checkout must never be
missing it).

Every mechanism kept here is a CLOSED-LOOP linkage. cadgen's mates evaluate
pure forward kinematics over a tree, so each model splits its motion the same
way:

- **Kinematics** (`<name>.kinematics.json`, baked into the sidecar) declares
  the real joints, any exactly-linear gearing as a `couplings` entry, and named
  `poses` — each pose is the loop SOLVED at one configuration, so every preset
  is geometrically consistent even though no solver runs at view time.
- **Animation** (`<name>.anim.js`, whose text is copied into the sidecar)
  carries the reference loop: the branch switching, rolling contacts and
  slider-crank arithmetic a mate tree cannot express.

Zero is the artifact as written — every model's rest state is its imported
placement.

## Contents

| Mechanism | Document | Kinematics DOFs / poses | Clip | Source |
|---|---|---|---|---|
| 180° flip mechanism | `imported/180_degree_flip_mechanism.step` | `crank`, `coupler`, `rocker`; poses `rest`, `quarter`, `over_center`, `three_quarter`, `flipped` | `flip` (5 s) | [Video](https://www.youtube.com/watch?v=IGexfslM_5Y), [STEP archive](https://www.mediafire.com/file/pcjk004x96r6ibu/180FlipMechanismSTEP.zip/file) |
| Adjustable height table 2 | `imported/adjustable_height_table_2.step` | `hoist`, `rise`, `descend`, four roller sliders, `actuator_rod`, `actuator_slider`, coupling `scissor`; poses `collapsed`, `mid`, `raised` | `lift` (8 s) | [Video](https://www.youtube.com/watch?v=c30g2UszMws), [STEP archive](https://www.mediafire.com/file/ulf0n6zbbp1veo4/TableAdjustHeight2STEP.zip/file) |
| Robot gripper, gear-rack drive | `imported/gear_rack_gripper.step` | `left_pinion`, `right_pinion`, `left_jaw`, `right_jaw`, `piston`, two conrods, coupling `grip`; poses `closed`, `half_open`, `open` | `drive` (6 s) | [Video](https://www.youtube.com/watch?v=CP5q6YxyeQ8), user upload `RobotGripperGearRackSTEP.zip` |

Each mechanism ships four files in `imported/`:

| File | What it is |
|---|---|
| `<name>.step` | the document, re-emitted in cadgen's dialect by `cadgen step build` |
| `<name>.step.json` | its sidecar: the resolved kinematics block + the copied clip text |
| `<name>.kinematics.json` | the kinematics SPACE as authored (the `--kinematics` input) |
| `<name>.anim.js` | the choreography module as authored (the `--animation` input) |

The two authored files are kept beside the document so the annotation stays
editable and reviewable; the sidecar is what every tool actually reads.

## Reviewing

```bash
cadgen step inspect refs imported/gear_rack_gripper.step --facts
cadgen step snapshot imported/gear_rack_gripper.step tmp/open.png --kinematics open
```

Motion review is interactive: open the CAD Viewer on `models/` and pick the
mechanism, then scrub its clip or drag the pose sliders.

## Re-annotating

`cadgen step build` writes a NEW document, so refreshing an annotation means
building to a scratch path and copying only the sidecar back:

```bash
cadgen step build imported/gear_rack_gripper.step tmp/gear_rack_gripper.step \
  --kinematics imported/gear_rack_gripper.kinematics.json \
  --animation imported/gear_rack_gripper.anim.js
cp tmp/gear_rack_gripper.step.json imported/gear_rack_gripper.step.json
```

Copy the sidecar only. Never replace the committed `.step` with the scratch
one: a round trip through OCCT re-reads and re-prints every decimal, so the
re-emit of a re-emit differs in the last digit of near-zero direction
components. The geometry is identical; the bytes are not, and these documents
are LFS-tracked.

Only `generatedAt` and `sourceHash` change when the declaration itself is
unchanged — `sourceHash` becomes the imported document's own hash, which is
now the annotation's true input.

Extracted source archives, Inventor files, SDF working files, videos, and
intermediate generation scripts are intentionally omitted from this fixture
bundle.
