# demo-plate models

| script           | artifact              | what it is                     |
|------------------|-----------------------|--------------------------------|
| plate.py         | STEP/plate.step       | mounting plate, param `hole_d` |
| plate_drawing.py | DXF/plate_drawing.dxf | plate flat pattern             |

Build everything: run each script (`python src/plate.py`,
`python src/plate_drawing.py`); unchanged models are no-ops. Shared
geometry lives in `src/lib/`. This project is the living exemplar for the
`cad-project` skill.
