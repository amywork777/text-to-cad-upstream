"""CAD Viewer backend.

A stdlib-only Python HTTP server for the built React client in ``dist/``. It is
launched directly — there is nothing to pip install for the server itself:

    <python> server/main.py --root /absolute/dir

``cadgen`` is imported LAZILY, and only on the STEP-import path. Nothing in this
package may import it at module scope: viewing a directory of existing models
must keep working when cadgen is absent, and cadgen drags a ~300MB kernel that
someone who only wants to look at an ``.stl`` should never pay for.
"""
