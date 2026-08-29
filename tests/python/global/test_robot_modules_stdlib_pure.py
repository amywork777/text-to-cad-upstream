"""The URDF/SRDF/SDF family in cadgen must stay stdlib-pure.

These modules are deliberately extraction-ready: robot-description validation is a
text/XML problem, not a CAD-kernel problem, and keeping the family free of
OCP/build123d/numpy is what preserves the option of breaking it back out of cadgen
(or running it in an environment without the heavy dependency set). A heavy import
added in passing would silently destroy that property — every suite would still
pass, because the test environment has the kernel installed.

Static check over the AST (not an import-time sys.modules probe) so an offending
import is caught even when it is lazy, conditional, or function-local.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CADGEN_SRC = REPO_ROOT / "packages" / "cadgen" / "src" / "cadgen"

FAMILY = [
    "urdf_source.py",
    "srdf_source.py",
    "srdf_validation.py",
    "sdf_source.py",
    "sdf_validation.py",
    "sdf_external.py",
    "findings.py",
    "xml_common.py",
    "cli/urdf_validate.py",
    "cli/srdf_validate.py",
    "cli/sdf_validate.py",
]

# Heavy roots that would break extraction-readiness. `cadgen` itself is allowed only
# for the family's own light members (findings, xml_common, and each other).
FORBIDDEN_ROOTS = {"OCP", "build123d", "numpy", "ocp_tessellate", "ezdxf", "playwright"}
ALLOWED_CADGEN = {
    "cadgen.findings",
    "cadgen.xml_common",
    "cadgen.urdf_source",
    "cadgen.srdf_source",
    "cadgen.srdf_validation",
    "cadgen.sdf_source",
    "cadgen.sdf_validation",
    "cadgen.sdf_external",
    "cadgen.cli_logging",
    "cadgen.cli",  # report_cli_error / shared CLI plumbing, itself lazy
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


class RobotModulesStdlibPure(unittest.TestCase):
    def test_family_files_exist(self) -> None:
        missing = [rel for rel in FAMILY if not (CADGEN_SRC / rel).is_file()]
        self.assertEqual(missing, [], "family member moved or deleted — update FAMILY")

    def test_no_heavy_imports_anywhere_in_the_family(self) -> None:
        offenders: list[str] = []
        for rel in FAMILY:
            for module in sorted(_imports(CADGEN_SRC / rel)):
                root = module.split(".")[0]
                if root in FORBIDDEN_ROOTS:
                    offenders.append(f"{rel}: {module}")
                elif root == "cadgen" and module not in ALLOWED_CADGEN:
                    offenders.append(f"{rel}: {module} (not in the allowed light set)")
        self.assertEqual(
            offenders,
            [],
            "the robot-description family must stay stdlib-pure (extraction-ready); "
            "move heavy work out or extend ALLOWED_CADGEN only for light modules",
        )


if __name__ == "__main__":
    unittest.main()
