"""The dependency-direction and ships-alone laws, held by test rather than prose.

Boundary law (packages/README.md and each package's README): apps import
packages; packages never import apps; cadgen-js is framework-free — no
React, no app or workflow state. Ships-alone law: cadgen (the built PyPI
distribution) and the CAD Viewer (mirrored unchanged to the standalone
earthtojake/cad-viewer repo) each work in isolation outside this repo, so
their markdown must not refer to anything outside the package. Prose
drifts; this does not.
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


# The ships-alone law. Two shipped surfaces leave this repo whole:
#   - packages/cadgen builds into the PyPI wheel (README.md is its long
#     description; cadgen-js arrives already bundled under _runtime/).
#   - apps/viewer mirrors UNCHANGED into the standalone earthtojake/cad-viewer
#     repo (its own packages/cadgen-js symlink dereferences into a vendored
#     copy; nothing rewrites paths on the way out).
# A repo-relative path in either one's markdown ships broken. Each root
# forbids the path families that only mean something inside this repo; a
# package may name its own files, its bundled/vendored dependencies, and the
# concepts of its dependencies — never the repo's layout.
_MD_BOUNDARY = r"(?<![\w./@-])"
_MD_ISOLATION_ROOTS: dict[str, tuple[str, ...]] = {
    # cadgen ships with no repo around it at all: nothing repo-relative.
    "packages/cadgen": (
        r"apps/",
        r"packages/",
        r"skills/",
        r"models/",
        r"tests/",
        r"scripts/",
        r"requirements-dev",
        r"AGENTS\.md",
        r"CONTRIBUTING\.md",
        r"\.github/",
    ),
    # The viewer owns scripts/, skills/smui/, and a vendored
    # packages/cadgen-js — those stay legal; the repo's families do not.
    "apps/viewer": (
        r"apps/",
        r"packages/cadgen(?!-js)",
        r"skills/(?!smui)",
        r"models/",
        r"tests/",
        r"scripts/(?:bundle|dev|test|release|install|viewer|github-workflows)/",
        r"requirements-dev",
        r"AGENTS\.md",
        r"CONTRIBUTING\.md",
        r"\.github/",
    ),
}
_MD_SKIPPED_DIRS = {"node_modules", "dist", "dist-verify", ".vite", "tmp", "__pycache__"}
_URL_RE = re.compile(r"https?://\S+")


def _markdown_files(root: Path):
    for path in sorted(root.rglob("*.md")):
        if _MD_SKIPPED_DIRS.intersection(path.parts):
            continue
        yield path


class PackagedMarkdownShipsAlone(unittest.TestCase):
    """Shipped markdown must read true outside this repo."""

    def test_no_repo_relative_references(self) -> None:
        offenders: list[str] = []
        for root_rel, families in _MD_ISOLATION_ROOTS.items():
            root = repo_path(root_rel)
            pattern = re.compile(_MD_BOUNDARY + "(?:" + "|".join(families) + ")")
            for path in _markdown_files(root):
                text = path.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(text.splitlines(), 1):
                    scannable = _URL_RE.sub("", line)
                    match = pattern.search(scannable)
                    if match:
                        rel = path.relative_to(repo_path("."))
                        offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(
            offenders,
            [],
            "Ships-alone law: cadgen installs from PyPI and apps/viewer "
            "mirrors unchanged into earthtojake/cad-viewer, so their markdown "
            "must be true and actionable with this repo gone. Name the "
            "bundled thing ('the cadgen-js runtime bundled at build time'), "
            "not the repo path to its source; move repo-development guidance "
            "to CONTRIBUTING.md; delete what serves neither audience.\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
