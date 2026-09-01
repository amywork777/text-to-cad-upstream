"""Structural invariants for ``server/``.

The Viewer ships alone: ``apps/viewer`` is mirrored verbatim to the standalone
``earthtojake/cad-viewer`` repo and has to work there with no access to this
monorepo. Two properties keep that true, and neither fails visibly in a
checkout where cadgen is always installed:

* The server is STDLIB-ONLY. No web framework, and nothing reached by path.
* ``cadgen`` is a SOFT dependency, imported lazily and only on the STEP-import
  path. One ``from cadgen...`` at module scope makes merely VIEWING a directory
  require a ~300MB kernel install.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = APP_ROOT / "server"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _python_sources() -> list[Path]:
    return sorted(SERVER_DIR.glob("*.py"))


def _module_scope_imports(tree: ast.Module):
    """Yield ``(node, root_module)`` for imports at module scope only."""
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                yield node, ""
            elif node.module:
                yield node, node.module.split(".")[0]
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            # Class bodies execute at import time too.
            if isinstance(node, ast.ClassDef):
                for inner in node.body:
                    if isinstance(inner, (ast.Import, ast.ImportFrom)):
                        for alias in getattr(inner, "names", []):
                            yield inner, alias.name.split(".")[0]


class SoftCadgenDependency(unittest.TestCase):
    def test_no_server_module_imports_cadgen_at_module_scope(self) -> None:
        offenders = []
        for path in _python_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node, root in _module_scope_imports(tree):
                if root == "cadgen":
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            "cadgen must be imported lazily inside the compile path, never at "
            "module scope: viewing existing models has to work without it",
        )

    def test_importing_the_server_package_does_not_pull_in_cadgen(self) -> None:
        # The strongest form of the check: actually import everything and look
        # at sys.modules. A lazy import that fires at class-definition time
        # would slip past the AST check but not this one.
        for name in ("content_types", "encoding", "handler", "http_app", "natural_sort", "response", "url_norm"):
            __import__(f"server.{name}")
        self.assertNotIn("cadgen", sys.modules)
        self.assertNotIn("OCP", sys.modules)
        self.assertNotIn("build123d", sys.modules)


class StdlibOnly(unittest.TestCase):
    ALLOWED_THIRD_PARTY: frozenset[str] = frozenset()

    def test_no_third_party_imports(self) -> None:
        stdlib = set(sys.stdlib_module_names)
        offenders = []
        for path in _python_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node, root in _module_scope_imports(tree):
                if not root or root == "server":
                    continue
                if root in stdlib or root in self.ALLOWED_THIRD_PARTY:
                    continue
                offenders.append(f"{path.name}:{node.lineno} imports {root}")
        self.assertEqual(offenders, [], "the Viewer server must stay stdlib-only")

    def test_no_sys_path_or_pythonpath_manipulation(self) -> None:
        # Reaching for a path is how a "standalone" app quietly acquires a
        # dependency on the repo it was developed in. main.py holds the ONE
        # legal insert (pinned by the next test); nothing else may touch a
        # lookup path at all. Matched on the AST, not on text: the old
        # substring scan also fired on the COMMENTS that explain the rule.
        offenders = []
        for path in _python_sources():
            if path.name == "main.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    target = ast.unparse(node.func)
                    if target.startswith("sys.path.") or "addsitedir" in target:
                        offenders.append(f"{path.name}:{node.lineno} {target}")
                elif isinstance(node, ast.Subscript) and "PYTHONPATH" in ast.unparse(node):
                    offenders.append(f"{path.name}:{node.lineno} PYTHONPATH")
        self.assertEqual(offenders, [], "the Viewer server must not manipulate any lookup path")

    def test_main_py_inserts_only_its_own_app_root(self) -> None:
        # main.py is run as a script, so `server.*` has to resolve somehow. The
        # one permitted spelling inserts its OWN directory's parent — a path
        # inside the shipped tree, which is what the skill self-containment
        # rules allow. PYTHONPATH or site.addsitedir would reach outside the
        # bundle and stay forbidden even here.
        source = (SERVER_DIR / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        inserts = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "sys.path.insert"
        ]
        self.assertEqual(len(inserts), 1, "exactly one sys.path insert is permitted")
        self.assertEqual(ast.unparse(inserts[0]), "sys.path.insert(0, _APP_ROOT)")

        assigned = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and any(ast.unparse(t) == "_APP_ROOT" for t in node.targets)
        ]
        self.assertEqual(len(assigned), 1)
        self.assertEqual(
            ast.unparse(assigned[0].value),
            "str(Path(__file__).resolve().parent.parent)",
            "_APP_ROOT must come from this file's own location, never from the "
            "environment or a repo-relative guess",
        )

        # AST, not substring: main.py's own comments NAME the forbidden calls in
        # order to forbid them, and a text scan cannot tell guidance from code.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                self.assertNotIn("addsitedir", ast.unparse(node.func))
            if isinstance(node, ast.Subscript):
                self.assertNotIn("PYTHONPATH", ast.unparse(node))


class ShippedRuntimeData(unittest.TestCase):
    def test_collation_table_ships_beside_the_code(self) -> None:
        # collation.json is RUNTIME data, not a fixture: it must land in the
        # skill bundle's server/ directory or the catalog sorts differently in
        # production than in tests.
        table = SERVER_DIR / "collation.json"
        self.assertTrue(table.is_file())
        self.assertGreater(table.stat().st_size, 100_000)

    def test_no_test_files_live_under_server(self) -> None:
        # Tests live in tests_server/ so the bundle's server/ rsync never sees
        # them and the --check tree diff needs no test excludes.
        strays = [p.name for p in SERVER_DIR.glob("test_*.py")]
        strays += [p.name for p in SERVER_DIR.glob("*_test.py")]
        self.assertEqual(strays, [])


if __name__ == "__main__":
    unittest.main()
