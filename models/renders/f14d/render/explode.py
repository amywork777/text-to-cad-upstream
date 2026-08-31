#!/usr/bin/env python3
"""RETIRED: the exploded-view teardown is choreography now, not a parameter.

This script drove the aircraft's `exploded` pose parameter -- sweeping it for a
GIF, or pinning it for stills -- back when `f14d.params.js` declared that
parameter.  Both surfaces are gone (design/pose-animation-split.md): kinematics
became typed mates, which the F-14D has none of because nothing about it
articulates, and the staged separation moved whole into `f14d.anim.js`, where it
is a pair of clips the CAD Viewer's Animation tab plays.  Snapshot is PNG-only;
there is no parameter sweep and no animation capture to drive from a CLI.

To see the teardown, open the aircraft in the Viewer and play `teardown`
(60 s, out and back) or `explodedHold` (24 s, out, hold, back).

The camera knowledge is worth keeping, because framing a teardown is not the
same problem as framing the built jet.  A three-quarter view from high and
forward is the one that works: the separation is mostly on Z (skin up, gear and
inlets down) with the nozzles drawing aft, so a camera well above the waterline
and off the bow sees the vertical stack without the wings hiding what drops out
from under them, while a level side view collapses the whole explode into one
line.  Zoom is TIGHTER than 1 crops in, and these values sit well below the
~3.2 that fills the frame with the assembled aircraft: the teardown roughly
doubles the bounding sphere (skin +5.2 m up, gear -2.3 m down, nozzles +4.4 m
aft), and framing is by bounding sphere, so a zoom that suits the built jet
throws the skin out of frame before it stops travelling.

    hi34   direction [-0.85, -0.55, 0.62]  up [0, 0, 1]  zoom 2.5
    fq     direction [-1, -0.62, 0.20]     up [0, 0, 1]  zoom 2.5
    side   direction [0, -1, 0]            up [0, 0, 1]  zoom 2.6

shot.py still renders the BUILT aircraft, and its theme/display JSON is what
keeps a teardown frame and a gauntlet frame lit and edged identically.
"""

from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write(
        "render/explode.py is retired: the `exploded` pose parameter and the GIF\n"
        "sweep it drove no longer exist. The teardown lives in f14d.anim.js and\n"
        "plays in the CAD Viewer's Animation tab (clips: teardown, explodedHold).\n"
        "See this file's docstring for the review cameras.\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
