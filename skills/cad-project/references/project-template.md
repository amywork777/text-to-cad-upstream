# Project scaffold template

Create these files verbatim (rename `demo`/`plate` to the real project/part),
then run `python src/plate.py` from the project root to verify the loop.
A built copy of this exact project lives at `models/projects/demo-plate/`.

## `src/plate.py`

```python
"""Demo part: a mounting plate with corner holes."""

from __future__ import annotations

from cadgen import build123d as bd
from cadgen import step

from lib import holes

WIDTH = 60.0
DEPTH = 40.0
THICKNESS = 4.0


@step(write="../STEP/plate.step")
def plate(hole_d: float = 4.5):
    body = bd.Box(WIDTH, DEPTH, THICKNESS)
    return holes.corner_holes(body, WIDTH, DEPTH, THICKNESS, hole_d)
```

## `src/plate_drawing.py`

```python
"""Demo drawing: the plate's flat pattern (outline + corner holes)."""

from __future__ import annotations

import ezdxf

from cadgen import dxf

from lib import holes
from plate import DEPTH, WIDTH  # importing a model never builds it


@dxf(write="../DXF/plate_drawing.dxf")
def plate_drawing(hole_d: float = 4.5):
    document = ezdxf.new()
    space = document.modelspace()
    half_w, half_d = WIDTH / 2, DEPTH / 2
    space.add_lwpolyline(
        [(-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d)],
        close=True,
    )
    for x, y in holes.corner_hole_centers(WIDTH, DEPTH):
        space.add_circle((x, y), hole_d / 2)
    return document
```

## `src/lib/holes.py`

```python
"""Shared hole helpers (plain module: no @step here)."""

from __future__ import annotations

from cadgen import build123d as bd

INSET = 6.0


def corner_hole_centers(width: float, depth: float):
    """The four corner-hole centers, shared by the part and its drawing."""
    return [
        (sx * (width / 2 - INSET), sy * (depth / 2 - INSET))
        for sx in (-1, 1)
        for sy in (-1, 1)
    ]


def corner_holes(body, width: float, depth: float, thickness: float, hole_d: float):
    for x, y in corner_hole_centers(width, depth):
        body -= bd.Pos(x, y, 0) * bd.Cylinder(hole_d / 2, thickness * 2)
    return body
```

## `src/README.md`

```markdown
# demo models

| Script           | Artifact              | Description                    |
|------------------|-----------------------|--------------------------------|
| plate.py         | STEP/plate.step       | Mounting plate, param `hole_d` |
| plate_drawing.py | DXF/plate_drawing.dxf | Plate flat pattern             |

Build everything: run each script (`python src/plate.py`,
`python src/plate_drawing.py`); unchanged models are no-ops.
```

## `.gitignore`

```gitignore
/STEP/*
!/STEP/imported/
/DXF/*
!/DXF/imported/
/STL/*
!/STL/imported/
/GLB/*
!/GLB/imported/
/3MF/*
!/3MF/imported/
/tmp/
__pycache__/
```

The `*` forms matter: ignoring the directory itself (`/STEP/`) would make the
`imported/` negation dead — git never descends into an ignored directory. Pin any
other file deliberately with its own negation line or `git add -f`.

## Verify

```bash
python src/plate.py                      # builds STEP/plate.step + its package
python src/plate.py                      # "current" — the no-op gate works
python src/plate_drawing.py              # builds DXF/plate_drawing.dxf
cadgen step snapshot --input STEP/plate.step --output tmp/plate.png
```
