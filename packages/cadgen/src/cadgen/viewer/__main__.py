"""``python -m cadgen.viewer`` — start the CAD Viewer.

The launcher, not the server: it picks the port, validates that this interpreter can
actually build artifacts, prints the URL (and the ``--json`` line agents parse), then
spawns ``cadgen.viewer.server`` and waits on it. Same behaviour the packaged skill runtime
used to get from ``npm run start``, minus the Node shim in between.
"""

from __future__ import annotations

import sys

from cadgen.viewer.start_viewer import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
