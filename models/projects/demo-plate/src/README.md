# demo-plate models

| script               | artifact              | what it is                     |
|----------------------|-----------------------|--------------------------------|
| STEP/plate.py        | STEP/plate.step       | mounting plate, param `hole_d` |
| DXF/plate_drawing.py | DXF/plate_drawing.dxf | plate flat pattern             |

Build everything: run each mirrored script (`python src/STEP/plate.py`,
`python src/DXF/plate_drawing.py`); unchanged models are no-ops. Shared
geometry lives in `src/lib/`. This project is the living exemplar for the
`cad-project` skill; bigger projects may delegate this catalog to per-folder
READMEs (`src/STEP/README.md`, ...).
