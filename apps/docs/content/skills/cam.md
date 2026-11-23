---
title: cam
description: The cam skill turns a saved part into 3-axis CNC toolpaths and G-code, planned and posted by your own FreeCAD and checked against the part. It never sends G-code to a machine.
---

The `cam` skill plans how a part is cut on a 3-axis CNC mill or router. Your agent writes a small job file (machine, material, stock, tools, and each setup's operations), and `cad step plan` has your own FreeCAD (1.1 or newer, run headless) plan the toolpaths and post them for the named controller.

## How it works

```bash
cad step plan part.step --job part.cam.json --out CAM
```

The plan reads a `.step`, `.stp` or `.xbf`, or a model the engine holds. It supports facing, profiling, pocketing, adaptive clearing and drilling, posted for GRBL, LinuxCNC, Mach3/Mach4, Fanuc, Centroid, UCCNC or Smoothieware. Every move is checked against the part for reach, gouges and rapids into the stock.

It writes into `CAM`: every number as JSON, a GLB of the part, the stock and the toolpaths that any viewer opens, and, when nothing is an error, the G-code.

## Limits

- It plans how a part is cut, not whether the design machines well, and it does not slice for a 3D printer.
- It needs FreeCAD installed (`CAD_FREECAD` names its `freecadcmd` where it is not found).
- It never sends G-code to a machine. Check the program on your controller before you run it.
