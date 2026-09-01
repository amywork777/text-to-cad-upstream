"""Tests for the Python backend.

These live OUTSIDE ``server/`` on purpose. The skill bundle rsyncs ``server/``
verbatim into ``skills/cad-viewer/scripts/viewer/server/`` and then compares the
trees with ``diff -qr``; keeping tests out of that directory means the copy
needs no test excludes and the ``--check`` diff has nothing extra to explain.

Run them from the app root::

    python -m unittest discover -s tests_server -t .
"""
