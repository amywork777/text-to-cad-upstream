# demo-plate models

| Script           | Artifact              | Description                    |
|------------------|-----------------------|--------------------------------|
| plate.py         | STEP/plate.step       | Mounting plate, param `hole_d` |
| plate_drawing.py | DXF/plate_drawing.dxf | Plate flat pattern             |

Build everything: run each script (`python src/plate.py`,
`python src/plate_drawing.py`); unchanged models are no-ops. Shared
geometry lives in `src/lib/`. This project is the living exemplar for the
`cad-project` skill.
