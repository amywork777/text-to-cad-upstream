"""Studio's committed CAD assets (studio-base): the results viewer's fixtures, which
``tests/python/global/test_no_cad_assets_tracked.py`` allows beside its own list, kept out of Jake's
file. Each entry is that list's: (path, `*` standing for any run of characters but `/`; most bytes; why
it is committed)."""

from __future__ import annotations

KIB = 1024
TINY = 64 * KIB

STUDIO_ALLOWED: tuple[tuple[str, int, str], ...] = (
    ("packages/ui/src/renderers/glb/__tests__/ready.cam.glb", 64 * KIB,
     "a real `cad cam plan` result, ready to cut (the part, the stock and two tools' toolpaths), the CAM "
     "viewer's JS tests read; a JS test cannot run FreeCAD"),
    ("packages/ui/src/renderers/glb/__tests__/fix.cam.glb", 16 * KIB,
     "a real `cad cam plan` result refused by a reach check, the CAM viewer's JS tests read; a JS test cannot run "
     "FreeCAD"),
    ("packages/ui/src/renderers/glb/__tests__/plate.*.result.glb", TINY,
     "real `cad step plan` results as 0.11 writes them, one ready to cut and one a check refused (19-22 KB "
     "each), the CAM viewer's JS tests read beside their result.json; a JS test cannot run FreeCAD"),
    ("packages/ui/src/renderers/glb/__tests__/cantilever.result.glb", TINY,
     "a real `cad step solve` result (the deformed cantilever with its stress field, 51 KB) the results "
     "viewer's JS tests read beside its result.json; a JS test cannot run the solver"),
)
