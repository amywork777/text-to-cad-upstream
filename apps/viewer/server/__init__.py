"""CAD Viewer backend.

A stdlib-only Python HTTP server for the built React client in ``dist/``. It is
launched directly, from the directory it should serve (the cwd IS the served
directory) — there is nothing to pip install for the server itself:

    cd /absolute/dir && <python> <path to>/server/main.py

``cadgen`` is imported LAZILY, and only on the STEP-import path. Nothing in this
package may import it at module scope: viewing a directory of existing models
must keep working when cadgen is absent, and cadgen drags a ~300MB kernel that
someone who only wants to look at an ``.stl`` should never pay for.
"""
