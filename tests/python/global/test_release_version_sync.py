"""The release version stamp has to survive the development symlink layout.

`scripts/release/sync-version.mjs` names several paths that are the SAME FILE here: the
mirrored `viewer/packages/...` and `skills/.../packages/...` entries are symlinks to the
canonical package. Each target reads its file before any write happens, so two targets
stamping one file means the last write wins -- and a mirror declaring fewer fields than the
canonical target silently reverts the field only the canonical one knows about.

That is not hypothetical: adding the implicitjs version to `packages/cadjs/package-lock.json`
without adding it to that file's two symlinked mirrors made the 0.4.10 release fail its own
version gate, after the bump and before anything was published.
"""

from __future__ import annotations

import json

import subprocess
import unittest
from pathlib import Path

from tests.python.support.paths import repo_path

SYNC_SCRIPT = repo_path("scripts", "release", "sync-version.mjs")


def _node(script: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr.strip()}")
    return result.stdout


class VersionSyncMirrorTests(unittest.TestCase):
    def test_targets_naming_one_file_are_merged_into_one_write(self) -> None:
        """Two targets on the same real file become one target holding both field sets."""
        if not repo_path("viewer", "packages", "cadjs").is_symlink():
            self.skipTest("not in the development symlink layout")
        # The script resolves target paths against the repo root, so the pair below has to be
        # real repo paths: the canonical lockfile and the mirror that symlinks to it.
        script = (
            "const { mergeTargetsByRealPath } = await import(%s);\n"
            "const merged = mergeTargetsByRealPath([\n"
            '  { path: "packages/cadjs/package-lock.json",'
            ' fields: [["version"], ["packages", "../implicitjs", "version"]] },\n'
            '  { path: "viewer/packages/cadjs/package-lock.json", fields: [["version"]], required: false },\n'
            "]);\n"
            "console.log(JSON.stringify({ count: merged.length, fields: merged[0].fields,"
            " treatedAsRequired: merged[0].required !== false }));"
            % json.dumps(SYNC_SCRIPT.as_uri())
        )
        payload = json.loads(_node(script))
        self.assertEqual(1, payload["count"], "a symlinked mirror must not get its own write")
        self.assertIn(
            ["packages", "../implicitjs", "version"],
            payload["fields"],
            "the merged target must keep the field only the canonical target declared",
        )
        self.assertTrue(payload["treatedAsRequired"], "a required target keeps the file required")

    def test_every_cadjs_lockfile_target_stamps_the_same_fields(self) -> None:
        """The shape of the bug that broke 0.4.10, asserted generically.

        That release shipped a stale version because one copy of cadjs's lockfile
        declared a field the others did not, so a mirror kept an old stamp. The specific
        field then was implicitjs's version; implicitjs has since folded into cadjs and
        skills no longer vendor lockfiles, so naming it would assert a world that no
        longer exists. The property that actually guards the bug is that every target
        naming a cadjs lockfile declares the SAME fields — which stays meaningful, and
        starts biting again, the moment a second copy reappears.
        """
        targets = json.loads(
            _node(
                "const { jsonTargets } = await import(%s);\n"
                "console.log(JSON.stringify(jsonTargets));" % json.dumps(SYNC_SCRIPT.as_uri())
            )
        )
        lockfiles = [t for t in targets if t["path"].endswith("cadjs/package-lock.json")]
        self.assertTrue(lockfiles, "the canonical cadjs lockfile is no longer a sync target")
        canonical = next(
            (t for t in lockfiles if t["path"] == "packages/cadjs/package-lock.json"), lockfiles[0]
        )
        expected = [list(field) for field in canonical["fields"]]
        for target in lockfiles:
            with self.subTest(path=target["path"]):
                self.assertEqual(
                    [list(field) for field in target["fields"]],
                    expected,
                    f"{target['path']} stamps different fields than the canonical lockfile, "
                    "which is how a mirror ships a stale version",
                )
