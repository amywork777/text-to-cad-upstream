"""Query the artifact-status authority (apps/viewer/server/artifactStatus.mjs) from Python tests.

Freshness verdicts have exactly one implementation, and it is JS; Python suites
that need a verdict (portability, concurrency) ask it through this shim instead
of keeping a second Python implementation alive just for tests.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STATUS_MODULE = _REPO_ROOT / "apps" / "viewer" / "server" / "artifactStatus.mjs"

_SNIPPET = """
import { pathToFileURL } from "node:url";
const { artifactStatus } = await import(pathToFileURL(process.argv[1]).href);
process.stdout.write(JSON.stringify(artifactStatus(process.argv[2], process.argv[3])));
"""


def js_artifact_status(file_ref: str | Path, root: str | Path) -> dict:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", _SNIPPET,
         str(_STATUS_MODULE), str(file_ref), str(root)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"artifactStatus failed: {proc.stderr[-400:]}")
    return json.loads(proc.stdout)
