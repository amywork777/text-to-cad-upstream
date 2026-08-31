# hypercar models

| Script          | Artifact           | Description                                    |
|-----------------|--------------------|------------------------------------------------|
| hypercar.py     | STEP/hypercar.step | Mid-engine hypercar, full assembly (13 systems) |

Build: `python src/hypercar.py`; unchanged models are no-ops. The build takes
~50 s cold.

## Layout

- `lib/` — the part builders, one module per system, plus `surfaces.py` (the
  one master body surface every panel is cut from), `palette.py` (colours,
  authored as sRGB hex) and `context.py` (the shared `group`/`style` helpers).
  Plain modules: no `@step` lives here.
- `hypercar.anim.js` — choreography (the showcase tour, the door loop, the
  explode loop). Declared by `animation=` on the decorator; its text is copied
  into `STEP/hypercar.step.json`.
- `../render/` — authored presentation config for beauty renders, kept at the
  project root because it is neither code nor an artifact:

  ```bash
  cadgen step snapshot STEP/hypercar.step tmp/beauty.png \
    --theme render/presentation_theme.json \
    --display render/presentation_display.json
  ```

## Assembly order

The order of `SYSTEMS` in `hypercar.py` IS the occurrence order, and
`hypercar.anim.js` targets those ids — do not reorder without updating it.

    o1.1 body   o1.2 glazing   o1.3 lighting   o1.4 chassis
    o1.5 suspension_front   o1.6 suspension_rear   o1.7 wheels   o1.8 brakes
    o1.9 powertrain   o1.10 interior   o1.11 aero   o1.12 hinge   o1.13 details

## Kinematics

The dihedral synchro-helix doors are typed mates on the decorator: one
`cylindrical` per door (62 deg of rotation coupled to 310 mm of travel about
the same tower axis) plus a `fastened` mate for each part that rides the door,
all geared by the `doors` coupling. Poses: `shut` (0) and `open` (1).

```bash
cadgen step snapshot STEP/hypercar.step tmp/open.png --kinematics open
```
