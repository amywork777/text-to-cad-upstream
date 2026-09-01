"""``server/store_paths.py`` must agree with cadgen, key for key.

The viewer keeps a LOCAL stdlib copy of the store layout rather than importing
cadgen's, because importing it would make cadgen a hard dependency of merely
viewing (see the module docstring there). The cost of that choice is a
duplication, and this is what pays it: both implementations are asked the same
questions over a matrix of environment states and paths, and their answers must
match exactly.

This replaces the grep-of-JS-source tests that policed the old mirror
(``test_cache_root_sync.py``'s scan of ``tessCache.mjs`` for three literals, and
``test_render_contract_sync.py``'s scan of ``packageContract.mjs``). It is
strictly stronger — a grep cannot tell you the two agree, only that a string is
present — and it is not the tautology trap of asserting a constant equals
itself, because the two implementations remain genuinely independent code.

cadgen is queried in a SUBPROCESS on purpose. Importing it here would put
``cadgen`` in ``sys.modules`` for the whole run and silently defeat
``test_module_boundaries``'s check that importing the server package does not
pull the kernel in.

Where it runs: anywhere cadgen is importable. Where it MUST run: set
``VIEWER_REQUIRE_CADGEN_PARITY=1`` and an absent cadgen fails instead of
skipping — that is how the workbench developing both sides keeps a guard that
was traded for a set of literal pins from quietly never executing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from server import store_paths  # noqa: E402

# Every question asked of both sides, in one place so neither can drift.
_PROBE = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    from cadgen import catalog
    from cadgen._internal import cache_paths, cache_schema, source_sidecar

    paths = json.loads(sys.argv[1])
    out = {
        "__cadgen__": catalog.__file__,
        "CACHE_SCHEMA_VERSION": cache_schema.CACHE_SCHEMA_VERSION,
        "SOURCE_SIDECAR_SUFFIX": source_sidecar.SOURCE_SIDECAR_SUFFIX,
        "SOURCE_SIDECAR_SCHEMA_VERSION": source_sidecar.SOURCE_SIDECAR_SCHEMA_VERSION,
        "packages_dir": str(cache_paths.packages_dir()),
        "locks_dir": str(cache_paths.locks_dir()),
        "records_dir": str(cache_paths.records_dir()),
        "package_dir_for_hash": str(catalog.package_dir_for_hash("f" * 64)),
        "per_path": {},
    }
    for probe in paths:
        out["per_path"][probe] = {
            "artifact_path_key": catalog.artifact_path_key(Path(probe)),
            "render_package_dir": str(catalog.render_package_dir(Path(probe))),
            "coordination_scope": str(catalog.coordination_scope(Path(probe))),
            "provenance_record": str(source_sidecar._provenance_record_path(Path(probe))),
            "source_sidecar_path": str(source_sidecar.source_sidecar_path(Path(probe))),
            "artifact_file_hash": catalog.artifact_file_hash(Path(probe)),
        }
    sys.stdout.write(json.dumps(out))
    """
)


def _viewer_answers(paths) -> dict:
    return {
        "CACHE_SCHEMA_VERSION": store_paths.CACHE_SCHEMA_VERSION,
        "SOURCE_SIDECAR_SUFFIX": store_paths.SOURCE_SIDECAR_SUFFIX,
        "SOURCE_SIDECAR_SCHEMA_VERSION": store_paths.SOURCE_SIDECAR_SCHEMA_VERSION,
        "packages_dir": store_paths.store_packages_dir(),
        "locks_dir": store_paths.store_locks_dir(),
        "records_dir": store_paths.store_records_dir(),
        "package_dir_for_hash": store_paths.package_dir_for_hash("f" * 64),
        "per_path": {
            probe: {
                "artifact_path_key": store_paths.artifact_path_key(probe),
                "render_package_dir": store_paths.render_package_dir(probe),
                "coordination_scope": store_paths.coordination_scope(probe),
                "provenance_record": store_paths.source_provenance_record_path(probe),
                "source_sidecar_path": store_paths.source_sidecar_path(probe),
                "artifact_file_hash": store_paths.artifact_file_hash(probe),
            }
            for probe in paths
        },
    }


def _cadgen_is_importable() -> bool:
    return (
        subprocess.run(
            [sys.executable, "-c", "import cadgen.catalog"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


# The one environment where this guard is REQUIRED rather than opportunistic.
#
# Skipping is right where cadgen is legitimately absent — the app ships alone,
# and its own CI installs no CAD kernel to check against. But a guard that only
# ever skips is a deleted guard, and this one replaced a set of literal pins
# that used to run on every change. So the workbench that develops both sides
# sets VIEWER_REQUIRE_CADGEN_PARITY=1, and there an unimportable cadgen is a
# FAILURE naming what to install rather than a quiet skip.
_PARITY_REQUIRED = os.environ.get("VIEWER_REQUIRE_CADGEN_PARITY", "").strip() not in ("", "0")


class AgreesWithCadgen(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if _cadgen_is_importable():
            return
        reason = (
            f"cadgen is not importable by {sys.executable}. This equality guard is the only "
            "thing comparing the viewer's store-key derivations against cadgen's; the server "
            "itself keeps working without cadgen, which is why it is skippable at all."
        )
        if _PARITY_REQUIRED:
            raise AssertionError(
                f"VIEWER_REQUIRE_CADGEN_PARITY is set, but {reason} Install cadgen into this "
                "interpreter, or put its source on PYTHONPATH — a skip here means a "
                "cross-language store-key mirror went unchecked."
            )
        raise unittest.SkipTest(reason)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name

        # A real file, a file under a symlinked ancestor, a missing file, and a
        # missing file under a symlinked ancestor — the last is where the JS
        # implementation used to disagree with cadgen.
        os.makedirs(os.path.join(self.base, "real", "sub"))
        Path(self.base, "real", "sub", "part.step").write_text("body\n", encoding="utf-8")
        os.symlink(os.path.join(self.base, "real"), os.path.join(self.base, "alias"))
        self.probes = [
            os.path.join(self.base, "real", "sub", "part.step"),
            os.path.join(self.base, "alias", "sub", "part.step"),
            os.path.join(self.base, "real", "sub", "gone.step"),
            os.path.join(self.base, "alias", "sub", "gone.step"),
            os.path.join(self.base, "real", "sub", "UPPER.STP"),
        ]

    def _compare(self, env_overrides: dict) -> None:
        env = dict(os.environ)
        for key in ("CADGEN_CACHE_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA"):
            env.pop(key, None)
        env.update({k: v for k, v in env_overrides.items() if v is not None})

        completed = subprocess.run(
            [sys.executable, "-c", _PROBE, json.dumps(self.probes)],
            capture_output=True,
            env=env,
            check=True,
            text=True,
        )
        cadgen_answers = json.loads(completed.stdout)
        cadgen_source = cadgen_answers.pop("__cadgen__")

        previous = {key: os.environ.get(key) for key in ("CADGEN_CACHE_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA")}
        try:
            for key in previous:
                os.environ.pop(key, None)
            for key, value in env_overrides.items():
                if value is not None:
                    os.environ[key] = value
            viewer_answers = _viewer_answers(self.probes)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        provenance = (
            f"the cadgen this interpreter imports is {cadgen_source}. If that is the wrong "
            "checkout, put the right packages/cadgen/src on PYTHONPATH; if it is the right "
            "one, the divergence is real and the viewer reads the wrong store tier."
        )
        # Checked first and on its own: a schema-version skew renames EVERY
        # package directory, so letting it through here buries one cause under
        # an 8000-character diff.
        self.assertEqual(
            viewer_answers["CACHE_SCHEMA_VERSION"],
            cadgen_answers["CACHE_SCHEMA_VERSION"],
            f"cache schema version skew — {provenance}",
        )
        self.assertEqual(viewer_answers, cadgen_answers, provenance)

    def test_the_explicit_override_wins_and_is_used_verbatim(self):
        self._compare({"CADGEN_CACHE_DIR": os.path.join(self.base, "explicit")})

    def test_the_override_beats_xdg(self):
        self._compare(
            {
                "CADGEN_CACHE_DIR": os.path.join(self.base, "explicit"),
                "XDG_CACHE_HOME": os.path.join(self.base, "xdg"),
            }
        )

    def test_a_whitespace_only_override_is_ignored(self):
        self._compare({"CADGEN_CACHE_DIR": "   ", "XDG_CACHE_HOME": os.path.join(self.base, "xdg")})

    @unittest.skipIf(os.name == "nt", "XDG_CACHE_HOME is never consulted on Windows")
    def test_xdg_cache_home_gets_the_cadgen_suffix(self):
        self._compare({"XDG_CACHE_HOME": os.path.join(self.base, "xdg")})

    @unittest.skipIf(os.name == "nt", "LOCALAPPDATA is never consulted on POSIX")
    def test_localappdata_is_ignored_on_posix(self):
        self._compare({"LOCALAPPDATA": os.path.join(self.base, "local")})

    @unittest.skipUnless(os.name == "nt", "Windows-only branch")
    def test_localappdata_gets_the_cadgen_suffix_on_windows(self):
        self._compare({"LOCALAPPDATA": os.path.join(self.base, "local")})

    def test_the_home_fallback(self):
        self._compare({})


class ReadPerCall(unittest.TestCase):
    def test_the_cache_root_is_never_memoised(self):
        # The suites set CADGEN_CACHE_DIR after the app is constructed and
        # expect the very next call to observe it. A module-level constant
        # would pass every other test in this file and fail this one.
        previous = os.environ.get("CADGEN_CACHE_DIR")
        try:
            os.environ["CADGEN_CACHE_DIR"] = "/tmp/first"
            self.assertEqual(store_paths.store_packages_dir(), os.path.join("/tmp/first", "packages"))
            os.environ["CADGEN_CACHE_DIR"] = "/tmp/second"
            self.assertEqual(store_paths.store_packages_dir(), os.path.join("/tmp/second", "packages"))
        finally:
            if previous is None:
                os.environ.pop("CADGEN_CACHE_DIR", None)
            else:
                os.environ["CADGEN_CACHE_DIR"] = previous


class ContentKeying(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        previous = os.environ.get("CADGEN_CACHE_DIR")
        os.environ["CADGEN_CACHE_DIR"] = os.path.join(self.tmp.name, "cache")
        self.addCleanup(
            lambda: os.environ.__setitem__("CADGEN_CACHE_DIR", previous)
            if previous is not None
            else os.environ.pop("CADGEN_CACHE_DIR", None)
        )

    def test_the_hash_memo_notices_a_content_change(self):
        # A stale hit would need an edit preserving BOTH mtime_ns and size.
        path = os.path.join(self.tmp.name, "a.step")
        Path(path).write_text("one\n", encoding="utf-8")
        first = store_paths.artifact_file_hash(path)
        Path(path).write_text("two\n", encoding="utf-8")
        self.assertNotEqual(store_paths.artifact_file_hash(path), first)

    def test_a_missing_file_hashes_to_none_rather_than_raising(self):
        self.assertIsNone(store_paths.artifact_file_hash(os.path.join(self.tmp.name, "gone.step")))

    def test_a_directory_named_like_a_step_hashes_to_none(self):
        directory = os.path.join(self.tmp.name, "dir.step")
        os.makedirs(directory)
        self.assertIsNone(store_paths.artifact_file_hash(directory))

    def test_the_unbuilt_path_is_deterministic_and_never_created(self):
        missing = os.path.join(self.tmp.name, "gone.step")
        unbuilt = store_paths.render_package_dir(missing)
        self.assertEqual(unbuilt, store_paths.render_package_dir(missing))
        self.assertTrue(os.path.basename(unbuilt).startswith("unbuilt-"))
        self.assertFalse(os.path.exists(unbuilt))

    def test_the_path_key_is_24_hex_characters(self):
        key = store_paths.artifact_path_key(os.path.join(self.tmp.name, "x.step"))
        self.assertEqual(len(key), 24)
        self.assertTrue(all(c in "0123456789abcdef" for c in key))


if __name__ == "__main__":
    unittest.main()
