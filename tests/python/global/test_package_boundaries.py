"""The dependency-direction law, held by test rather than prose.

Boundary law (packages/README.md and each package's README): apps import
packages; packages never import apps; cadgen-js is framework-free — no
React, no app or workflow state. Prose drifts; this does not.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.python.support.paths import repo_path

CADGEN_JS_SRC = repo_path("packages/cadgen-js/src")
CADGEN_JS_BIN = repo_path("packages/cadgen-js/bin")
CADGEN_SRC = repo_path("packages/cadgen/src")

_IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*(?:import\s[^;]*?from\s+["']([^"']+)["']|import\s+["']([^"']+)["']|require\(\s*["']([^"']+)["']\s*\))""",
)


def _js_files(*roots: Path):
    for root in roots:
        if not root.is_dir():
            continue
        for suffix in ("*.js", "*.mjs"):
            for path in root.rglob(suffix):
                if "node_modules" in path.parts:
                    continue
                yield path


def _import_specifiers(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    found = []
    for match in _IMPORT_RE.finditer(text):
        specifier = next(group for group in match.groups() if group)
        found.append(specifier)
    return found


class CadgenJsIsFrameworkFree(unittest.TestCase):
    def test_no_react_and_no_app_imports(self) -> None:
        offenders: list[str] = []
        for path in _js_files(CADGEN_JS_SRC, CADGEN_JS_BIN):
            for specifier in _import_specifiers(path):
                lowered = specifier.lower()
                if lowered == "react" or lowered.startswith("react/") or lowered.startswith("react-"):
                    offenders.append(f"{path}: {specifier}")
                if "apps/" in specifier.replace("\\", "/"):
                    offenders.append(f"{path}: {specifier}")
        self.assertEqual(
            offenders,
            [],
            "cadgen-js is framework-free shared code (its README, Boundary "
            "laws): no React, nothing from apps/. Move app-flavored code "
            "into the app that owns it.",
        )


class PackagesNeverImportApps(unittest.TestCase):
    def test_no_python_reference_into_apps(self) -> None:
        offenders: list[str] = []
        for path in CADGEN_SRC.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if re.search(r"""["'](?:\.\./)*apps/""", stripped):
                    offenders.append(f"{path}:{lineno}: {stripped[:80]}")
        self.assertEqual(
            offenders,
            [],
            "packages never reach into apps/ (dependency-direction law): the "
            "distribution must build and run with the apps deleted.",
        )

    def test_no_js_import_into_apps(self) -> None:
        offenders: list[str] = []
        for path in _js_files(CADGEN_JS_SRC, CADGEN_JS_BIN):
            for specifier in _import_specifiers(path):
                if specifier.replace("\\", "/").startswith(("../../apps", "../../../apps")):
                    offenders.append(f"{path}: {specifier}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
