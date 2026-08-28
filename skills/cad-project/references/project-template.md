# Project scaffold template

Create these files verbatim (rename `demo`/`plate` to the real project/part),
then run `python src/STEP/plate.py` from the project root to verify the loop.
A built copy of this exact project lives at `models/projects/demo-plate/`.

## `src/STEP/plate.py`

```python
"""Demo part: a mounting plate with corner holes."""

from __future__ import annotations

import sys
from pathlib import Path

# src/ on sys.path so mirrored scripts share src/lib (python puts THIS
# folder on the path, not the project's src/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cadgen import build123d as bd
from cadgen import step

from lib import holes  # noqa: E402

WIDTH = 60.0
DEPTH = 40.0
THICKNESS = 4.0


@step(write="../../STEP/plate.step")
def plate(hole_d: float = 4.5):
    body = bd.Box(WIDTH, DEPTH, THICKNESS)
    return holes.corner_holes(body, WIDTH, DEPTH, THICKNESS, hole_d)
```

## `src/DXF/plate_drawing.py`

```python
"""Demo drawing: the plate's flat pattern (outline + corner holes)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ezdxf

from cadgen import dxf

from lib import holes  # noqa: E402
from STEP.plate import DEPTH, WIDTH  # noqa: E402  (import never builds)


@dxf(write="../../DXF/plate_drawing.dxf")
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

## `src/lib/__init__.py`

Empty file.

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

| script               | artifact              | what it is                     |
|----------------------|-----------------------|--------------------------------|
| STEP/plate.py        | STEP/plate.step       | mounting plate, param `hole_d` |
| DXF/plate_drawing.py | DXF/plate_drawing.dxf | plate flat pattern             |

Build everything: run each mirrored script (`python src/STEP/plate.py`,
`python src/DXF/plate_drawing.py`); unchanged models are no-ops.
```

## `.gitignore`

```gitignore
/STEP/
/DXF/
/STL/
/GLB/
/3MF/
/PNG/
/GIF/
```

Commit a vendor import or pinned fixture deliberately with a negation pattern
(`!/STEP/vendor/`) or `git add -f STEP/<file>` when it arrives.

## Verify

```bash
python src/STEP/plate.py                 # builds STEP/plate.step + its package
python src/STEP/plate.py                 # "current" — the no-op gate works
python src/DXF/plate_drawing.py          # builds DXF/plate_drawing.dxf
python <cad-skill>/scripts/snapshot --input STEP/plate.step --output PNG/plate.png
```
