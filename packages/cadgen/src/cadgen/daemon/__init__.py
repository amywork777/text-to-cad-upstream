"""Opt-in warm-process daemon for the CAD build CLIs.

Holds OCP, build123d and the parser modules resident so repeated builds skip the import
cost. Off unless ``CADGEN_WARM=1``; the daemon sets ``CADGEN_DAEMON_CHILD`` in the process
it serves from so a tool invoked through it cannot recurse back into the client.
"""

from cadgen.daemon.server import main

__all__ = ["main"]
