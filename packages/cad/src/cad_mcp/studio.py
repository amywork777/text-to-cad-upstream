"""Studio's own (studio-base): the ``cad mcp`` Studio starts runs Studio's own engine.

Studio ships cad built from studio-base, pinned, in its own Python, with its own state folder and port. Since 0.11.12
``cad mcp`` hands the start to an installed global ``cad`` wherever there is one (``shim.start_server``): on a computer
with Jake's cad installed, Studio's plugin then ran the person's public cad, which has none of Studio's engine code and
updates past Studio's pin, registered in Studio's state folder, and offered Studio no CAD views. Studio's plugin sets
``CAD_STUDIO_ENGINE=1`` (``scripts/studio_cad_plugin.py`` in Studio), and its ``cad mcp`` then starts this release's
own server, as ``cad server start`` does, whatever cad is installed globally.
"""

from __future__ import annotations

import os

ENV = "CAD_STUDIO_ENGINE"


def own_engine() -> bool:
    """Whether this ``cad mcp`` is Studio's, which starts this release's own server, never a global cad's."""
    return os.environ.get(ENV, "").strip() == "1"
