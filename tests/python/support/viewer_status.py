"""Query the artifact-status authority (``apps/viewer/server/artifact_status.py``).

Freshness verdicts have exactly one implementation and it lives in the Viewer,
so cadgen suites that need a verdict (portability, concurrency) ask it through
this shim rather than keeping a second implementation alive just for tests.

It runs in a SUBPROCESS on purpose. The viewer server is stdlib-only and keeps
cadgen a soft dependency; importing its modules into a cadgen test process
would put both on one ``sys.path`` and make an accidental coupling invisible.
The subprocess also means these callers do not have to care that the viewer
lives outside the package under test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VIEWER_APP_ROOT = _REPO_ROOT / "apps" / "viewer"

_SNIPPET = """
import json, sys
sys.path.insert(0, sys.argv[1])
from server.artifact_status import artifact_status
sys.stdout.write(json.dumps(artifact_status(sys.argv[2], sys.argv[3])))
"""


def viewer_artifact_status(file_ref: str | Path, root: str | Path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _SNIPPET, str(_VIEWER_APP_ROOT), str(file_ref), str(root)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"artifact_status failed: {proc.stderr[-400:]}")
    return json.loads(proc.stdout)
