"""The analysis protocol: the registry, study dispatch, the check kinds, the CLI lines and the skill's docs.

Registry and parse tests are stdlib only. The golden test writes a cantilever STEP into a temporary directory and
solves it twice.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.python.support.fea_fixtures import (
    box_step, box_volume, class_directory, ends, glb_attribute_names, heavy_at_import, needs_fea, read_glb, sidecar,
    solve, value_error,
)

from cadgen._internal.fea.analyses import ANALYSIS_NAMES, REGISTRY, get_analysis


class Registry(unittest.TestCase):
    def test_static_is_the_one_analysis(self):
        self.assertEqual(ANALYSIS_NAMES, ("static",))
        self.assertEqual((REGISTRY["static"].tier, REGISTRY["static"].word), (1, "Strength"))

    def test_an_unknown_name_lists_every_name(self):
        message = value_error(self, get_analysis, "modal")
        self.assertIn("'modal' is not an analysis cadgen knows; use one of static", message)

    def test_static_is_built_and_stdlib_only_at_import(self):
        static = get_analysis("static")
        self.assertEqual((static.name, static.tier, static.word), ("static", 1, "Strength"))
        self.assertIs(get_analysis("static"), static)
        # The analysis and the check kinds load without numpy, scipy, netgen or OCP: a malformed study fails before
        # any of them is imported.
        self.assertEqual(heavy_at_import(REGISTRY["static"].module, "cadgen._internal.fea.analyses.kinds"), "")


BASE = {"material": "steel", "fixtures": [{"faces": ["face 1"]}], "loads": [{"faces": ["face 2"], "type": "force", "vector_N": [1, 0, 0]}]}


@needs_fea
class StudyDispatch(unittest.TestCase):
    """The ``analysis`` key and the common keys: stdlib only, before any heavy import."""

    def test_no_analysis_is_static_and_says_the_same(self):
        from cadgen._internal.fea.study import CHECK_KINDS, VIEW_FIELDS, parse_study

        bare, named = parse_study(BASE), parse_study({**BASE, "analysis": "static"})
        self.assertEqual((bare.analysis, named.analysis), ("static", "static"))
        self.assertEqual((bare.fixtures, bare.loads, bare.inputs), (named.fixtures, named.loads, named.inputs))
        self.assertEqual(bare.inputs.anchor_refs, ("face 1",))
        self.assertTrue(bare.inputs.requires_anchor)
        self.assertEqual((CHECK_KINDS, VIEW_FIELDS), (("stress", "displacement"), ("von_mises", "displacement")))

    def test_an_unknown_analysis_is_a_plain_error(self):
        from cadgen._internal.fea.study import parse_study

        for name, fragment in (("modal", "is not an analysis cadgen knows; use one of static"),
                               (3, "expected the analysis's name")):
            with self.subTest(name=name):
                self.assertIn(fragment, value_error(self, parse_study, {**BASE, "analysis": name}))

    def test_unknown_keys_name_the_analysis_and_what_it_takes(self):
        from cadgen._internal.fea.study import parse_study

        self.assertIn("unknown keys ['modes']; static studies take analysis, material, fixtures, loads",
                      value_error(self, parse_study, {**BASE, "modes": 6}))

    def test_a_check_static_does_not_make_is_refused(self):
        from cadgen._internal.fea.study import parse_study

        self.assertIn("is not a check this cadgen makes; use one of ['stress', 'displacement']",
                      value_error(self, parse_study, {**BASE, "view": {"checks": [{"kind": "frequency", "min_Hz": 60}]}}))
        self.assertIn("'mode' is not one of ['field', 'deformation', 'load_scale', 'threshold']",
                      value_error(self, parse_study, {**BASE, "view": {"controls": [{"drives": "mode"}]}}))

    def test_static_refuses_linear_elements_as_before(self):
        from cadgen._internal.fea.study import parse_study

        self.assertIn("only quadratic (order 2) elements are supported", value_error(self, parse_study, {**BASE, "mesh": {"order": 1}}))

    def test_fit_is_no_key(self):
        from cadgen._internal.fea.study import parse_study

        self.assertIn("unknown keys ['fit']", value_error(self, parse_study, {**BASE, "fit": {"allow": []}}))

    def test_body_loads_have_no_faces_and_need_a_density(self):
        from cadgen._internal.fea.study import parse_study

        study = parse_study({**BASE, "loads": [{"type": "gravity", "vector_g": [0, 0, -1]}, {"type": "acceleration", "vector_g": [5, 0, 0]}]})
        self.assertEqual([load.type for load in study.body_loads], ["gravity", "acceleration"])
        self.assertEqual(study.surface_loads, ())
        self.assertEqual(study.face_refs, ("face 1",))
        self.assertEqual(study.inputs.body_accelerations, [(0.0, 0.0, -9806.65), (-5 * 9806.65, -0.0, -0.0)])
        cases = [
            ({"loads": [{"type": "gravity"}]}, "loads[0].vector_g: gravity as [x, y, z] in g"),
            ({"loads": [{"type": "gravity", "vector_g": [0, 0, 0]}]}, "loads[0].vector_g: the gravity is zero"),
            ({"loads": [{"type": "gravity", "vector_g": [0, 0, -1], "faces": ["face 2"]}]}, "acts on the whole part"),
            ({"material": {"E_MPa": 1000, "nu": 0.3, "yield_MPa": 10}, "loads": [{"type": "acceleration", "vector_g": [1, 0, 0]}]},
             "static studies need the density"),
        ]
        for change, fragment in cases:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, value_error(self, parse_study, {**BASE, **change}))


class CheckKinds(unittest.TestCase):
    def test_every_kind_parses_its_own_keys(self):
        from cadgen._internal.fea.analyses.kinds import CHECK_SPECS

        self.assertEqual(list(CHECK_SPECS), ["stress", "displacement", "frequency", "buckling", "temperature", "acceleration",
                                             "fatigue", "pressure_drop", "velocity", "plastic_strain", "contact_pressure",
                                             "creep_strain", "ply_failure", "electric_field", "bolt_load", "joint_separation",
                                             "joint_slip", "mach", "sound_level", "mass_saved", "fracture",
                                             "crack_life", "voltage", "critical_speed", "stability",
                                             "fill_level", "wall_pressure"])
        parse = {kind: spec.parse for kind, spec in CHECK_SPECS.items()}
        self.assertEqual(parse["frequency"]({"kind": "frequency", "min_Hz": 60, "mode": 2}, "c"), {"kind": "frequency", "min_Hz": 60.0, "mode": 2})
        self.assertEqual(parse["frequency"]({"kind": "frequency", "avoid_Hz": [110, 130]}, "c")["avoid_Hz"], [110.0, 130.0])
        self.assertEqual(parse["buckling"]({"kind": "buckling"}, "c"), {"kind": "buckling", "margin": 3.0})
        self.assertEqual(parse["fatigue"]({"kind": "fatigue", "cycles": 1e6}, "c"), {"kind": "fatigue", "cycles": 1e6, "margin": 1.5})
        self.assertEqual(parse["temperature"]({"kind": "temperature", "max_C": 85, "faces": ["face 7"], "label": "Chip"}, "c"),
                         {"kind": "temperature", "max_C": 85.0, "faces": ["face 7"], "label": "Chip"})
        self.assertEqual(CHECK_SPECS["buckling"].scaling, "inverse")
        self.assertEqual(CHECK_SPECS["frequency"].default_label, "Vibration")

    def test_the_errors_name_the_field(self):
        from cadgen._internal.fea.analyses.kinds import CHECK_SPECS

        cases = [
            ("frequency", {"kind": "frequency", "min_Hz": 60, "avoid_Hz": [1, 2]}, "exactly one"),
            ("frequency", {"kind": "frequency", "avoid_Hz": [130, 110]}, "c.avoid_Hz: low (130) must be below high (110)"),
            ("frequency", {"kind": "frequency", "avoid_Hz": [1, 2], "mode": 1}, "c.mode: a band check looks at every mode"),
            ("buckling", {"kind": "buckling", "margin": 0.5}, "c.margin: a buckling margin below 1"),
            ("temperature", {"kind": "temperature"}, "c.max_C"),
            ("acceleration", {"kind": "acceleration", "limit_g": -1}, "c.limit_g: must be > 0"),
            ("velocity", {"kind": "velocity", "limit_Pa": 1}, "c: unknown keys ['limit_Pa']; a velocity check takes"),
        ]
        for kind, entry, fragment in cases:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, value_error(self, CHECK_SPECS[kind].parse, entry, "c"))

    @needs_fea
    def test_field_max_over_takes_the_faces_nodes_or_every_node(self):
        import numpy as np

        from cadgen._internal.fea.analyses.kinds import field_max_over
        from cadgen._internal.fea.mesh import FaceFingerprint

        boundary = np.array([[0, 1, 2], [2, 3, 4]])
        faces = {1: FaceFingerprint("face 1", 1, 1.0, (0, 0, 0)), 2: FaceFingerprint("face 2", 2, 1.0, (0, 0, 0))}
        values = np.array([0.0, 1.0, 2.0, 5.0, 3.0, 9.0])
        common = dict(boundary=boundary, boundary_ordinal=np.array([1, 2]), locations=np.arange(18.0).reshape(6, 3),
                      face_ref=faces, ordinal_of={"a": 1, "b": 2}, where="view.checks[1]")
        on_one = field_max_over(values, ("a",), **common)
        self.assertEqual((on_one.node, on_one.value, on_one.ref, on_one.faces, on_one.at), (2, 2.0, "face 1", ("face 1",), (6.0, 7.0, 8.0)))
        self.assertEqual(field_max_over(values, (), **common).node, 5)
        self.assertIsNone(field_max_over(values, (), **common).ref)


class CliLines(unittest.TestCase):
    def _result(self, **changes):
        from cadgen.results import FeaResult

        fields = {"summary": {"safety_factor": 2.5}, "mesh": {"elements": 10}, **changes}
        return FeaResult(ok=True, document=Path("p.step"), occurrence="part", glb=Path("p.glb"), sidecar=Path("p.json"), **fields)

    def test_a_unitless_check_reads_with_single_spaces(self):
        check = {"label": "Fatigue life", "value": 1.317, "limit": 1.5, "unit": "", "ratio": 0.759, "status": "close"}
        stress = {"label": "Strength", "value": 77.1, "limit": 250.0, "unit": "MPa", "ratio": 0.31, "status": "passes"}
        lines = self._result(summary={"safety_factor": 2.5, "checks": [check, stress]}).human_lines()
        self.assertIn("check 'Fatigue life': 1.317 against a 1.5 limit, 0.76× it, close", lines)
        self.assertIn("check 'Strength': 77.1 MPa against a 250 MPa limit, 0.31× it, passes", lines)

    def test_a_check_far_under_its_limit_says_under_1_percent_not_0_00_times(self):
        def stress(value, ratio):
            return {"label": "Strength", "value": value, "limit": 250.0, "unit": "MPa", "ratio": ratio, "status": "passes"}

        lines = self._result(summary={"safety_factor": 2.5, "checks": [stress(0.0053, 2.12e-05), stress(2.5, 0.01)]}).human_lines()
        self.assertIn("check 'Strength': 0.0053 MPa against a 250 MPa limit, under 1% of it, passes", lines)
        self.assertIn("check 'Strength': 2.5 MPa against a 250 MPa limit, 0.01× it, passes", lines)
        self.assertFalse(any("0.00×" in line for line in lines))

def _cantilever(directory: Path) -> Path:
    return box_step(directory, "cantilever", (40.0, 4.0, 4.0), "x")


@needs_fea
class MeshOptions(unittest.TestCase):
    """mesh.py's ``order`` and ``size_field``: linear tets end to end, and local sizes that refine."""

    @classmethod
    def setUpClass(cls):
        from cadgen._internal.fea.document import read_document

        cls.directory = class_directory(cls)
        cls.step = _cantilever(cls.directory)
        cls.fixed, cls.loaded = ends(cls.step)
        cls.occurrence = next(iter(read_document(cls.step).leaves()))

    def test_a_size_field_refines_where_it_says(self):
        import numpy as np

        from cadgen._internal.fea.mesh import mesh_occurrence

        plain = mesh_occurrence(self.occurrence, max_h=2.0)
        ordinal = int(self.loaded.rsplit(" ", 1)[1])
        by_face = mesh_occurrence(self.occurrence, max_h=2.0, size_field={"faces": {ordinal: 0.5}})
        by_point = mesh_occurrence(self.occurrence, max_h=2.0, size_field={"points": [[20.0, 0.0, 0.0, 0.5]], "radius_mm": 1.0})
        for refined in (by_face, by_point):
            self.assertGreater(len(refined.tets), 1.5 * len(plain.tets))
        # The fine face's triangles are small; the far end's keep the global size.
        def mean_edge(volume, face):
            corners = volume.nodes[volume.boundary[volume.boundary_ordinal == face][:, :3]]
            return float(np.linalg.norm(corners[:, 1] - corners[:, 0], axis=1).mean())
        self.assertLess(mean_edge(by_face, ordinal), 0.8)
        self.assertGreater(mean_edge(by_face, int(self.fixed.rsplit(" ", 1)[1])), 1.2)


class SkillDocs(unittest.TestCase):
    """The skill says what the registry says: every registered analysis runs today, in both of its tables, and nothing
    the rebuild removed (the fit ladder, a downloaded or built-in solver, the other analyses' pages) is still taught."""

    SKILL = Path(__file__).resolve().parents[4] / "skills" / "fea"

    def _rows(self, path: Path, heading: str) -> list[list[str]]:
        import re

        text = path.read_text(encoding="utf-8")
        section = text.split(heading, 1)[1]
        section = re.split(r"\n#{2,3} ", section, maxsplit=1)[0]
        lines = [line for line in section.splitlines() if line.startswith("|") and "---" not in line]
        return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[1:]]  # past the header

    def _pages(self) -> list[Path]:
        return [self.SKILL / "SKILL.md", *sorted((self.SKILL / "references").glob("*.md"))]

    def test_every_registered_analysis_has_a_runs_today_row_in_both_tables(self):
        import re

        # SKILL.md's "Choose the analysis": the analysis is the first `name` of its second column.
        status_of: dict[str, list[str]] = {}
        for cells in self._rows(self.SKILL / "SKILL.md", "## Choose the analysis"):
            if len(cells) < 5:
                continue
            found = re.match(r"`([a-z_]+)`", cells[1])
            if found:
                status_of.setdefault(found.group(1), []).append(cells[3])
        self.assertEqual(sorted(status_of), sorted(REGISTRY), "one row (or more) per registered analysis, no other")
        for name, statuses in status_of.items():
            with self.subTest(table="SKILL.md", analysis=name):
                self.assertTrue(all(status.startswith("**Runs today**") for status in statuses), statuses)

        # study-file.md's `analysis` table: one row per registered name, its word and its status.
        table = {}
        for cells in self._rows(self.SKILL / "references" / "study-file.md", "## `analysis`"):
            found = re.fullmatch(r"`([a-z_]+)`", cells[0])
            if found and len(cells) >= 4:
                table[found.group(1)] = (cells[1], cells[2])
        self.assertEqual(sorted(table), sorted(REGISTRY))
        for name, (word, status) in table.items():
            with self.subTest(table="study-file.md", analysis=name):
                self.assertEqual(word, REGISTRY[name].word)
                self.assertTrue(status.startswith("runs today"), status)

    def test_nothing_removed_is_still_taught(self):
        from cadgen._internal.fea.study import COMMON_KEYS

        self.assertNotIn("fit", COMMON_KEYS)
        stale = (
            "`fit`", "fit.allow", "adapted:", "ladder", "linear_elements", "local_refine", "defeature", "idealise",
            "built-in solver", "downloads it once", "downloading the CalculiX", "CADGEN_CCX=0", "scikit-fem", "pyamg",
            "Gauss-point peak is", "always higher", "Lite limits",
        )
        for path in self._pages():
            text = " ".join(path.read_text(encoding="utf-8").split())
            for phrase in stale:
                with self.subTest(page=path.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_the_setup_names_the_mesher_and_the_installed_solver(self):
        from cadgen._internal.fea.calculix import CCX_ENV, MINIMUM, install_hint

        text = " ".join((self.SKILL / "SKILL.md").read_text(encoding="utf-8").split())
        setup = text.split("## Setup", 1)[1].split("## Workflow", 1)[0]
        self.assertIn(f"`{CCX_ENV}`", setup)
        self.assertIn(f"{MINIMUM[0]}.{MINIMUM[1]} or newer", setup)
        self.assertIn("conda install -c conda-forge calculix", install_hint())
        self.assertIn("conda install -c conda-forge calculix", setup)
        self.assertIn("calculix-ccx", setup)
        self.assertIn("netgen", setup)
        self.assertIn("downloads nothing", setup)

    def test_the_nodal_peak_is_the_one_documented_as_usually_higher(self):
        for path in (self.SKILL / "SKILL.md", self.SKILL / "references" / "linear-static.md"):
            text = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(page=path.name):
                self.assertIn("usually the higher of the two", text)

    def test_the_skill_is_a_router_and_links_each_reference_page_once_from_its_table(self):
        import re

        text = (self.SKILL / "SKILL.md").read_text(encoding="utf-8")
        description = re.search(r"^description: (.*)$", text, re.M).group(1)
        self.assertLess(len(description), 1024)
        # A router: it names kinds of question in plain words, never an analysis by its key.
        self.assertFalse([name for name in REGISTRY if f"`{name}`" in description or name in description.split()])
        self.assertNotIn("—", description)
        section = text.split("## Choose the analysis", 1)[1]
        section = re.split(r"\n#{2,3} ", section, maxsplit=1)[0]
        linked = re.findall(r"\]\(references/([a-z0-9-]+\.md)", section)
        general = {"materials.md", "study-file.md", "planned-next.md"}
        pages = sorted(path.name for path in (self.SKILL / "references").glob("*.md") if path.name not in general)
        self.assertEqual(sorted(linked), pages, "each analysis page is linked exactly once from the table")
        for page in general:
            self.assertIn(f"references/{page}", text)

    def test_every_relative_link_lands_on_a_page_and_its_heading(self):
        import re

        def anchor(heading: str) -> str:
            slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
            return slug.replace(" ", "-")

        anchors = {}
        for path in self._pages():
            headings = re.findall(r"^#{1,6} (.+)$", path.read_text(encoding="utf-8"), re.M)
            anchors[path.resolve()] = {anchor(heading) for heading in headings}
        for path in self._pages():
            for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
                if re.match(r"[a-z]+:", target):
                    continue
                page, _, fragment = target.partition("#")
                resolved = (path.parent / page).resolve() if page else path.resolve()
                with self.subTest(page=path.name, link=target):
                    self.assertIn(resolved, anchors, "links to a page the skill does not ship")
                    if fragment:
                        self.assertIn(fragment, anchors[resolved])


class PrivateNames(unittest.TestCase):
    """No fea module reaches into another's private names: each shares what others use under a public name."""

    def test_no_module_imports_or_reads_another_modules_private_name(self):
        import ast

        root = Path(__file__).resolve().parents[4] / "packages" / "cadgen" / "src" / "cadgen" / "_internal" / "fea"
        found = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            own = "cadgen._internal." + ".".join(path.relative_to(root.parent).with_suffix("").parts)
            modules = {}  # a name bound to a cadgen module in this file -> that module
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cadgen"):
                    for alias in node.names:
                        if alias.name.startswith("_") and not alias.name.startswith("__") and node.module != own:
                            found.append(f"{path.name}:{node.lineno} from {node.module} import {alias.name}")
                        modules[alias.asname or alias.name] = f"{node.module}.{alias.name}"
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("cadgen"):
                            modules[alias.asname or alias.name.split(".")[0]] = alias.name
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__")
                        and isinstance(node.value, ast.Name) and node.value.id in modules):
                    found.append(f"{path.name}:{node.lineno} {node.value.id}.{node.attr}")
        self.assertEqual(found, [])


@needs_fea
class Golden(unittest.TestCase):
    """Static moved, not rewritten: a study with and without ``"analysis": "static"`` writes the same GLB, byte for byte,
    with von Mises beside the displacement as before."""

    def test_naming_static_changes_no_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            step = _cantilever(directory)
            fixed, loaded = ends(step)
            study = {"material": "steel", "fixtures": [{"faces": [fixed]}], "mesh": {"size_mm": 2.0},
                     "loads": [{"faces": [loaded], "type": "force", "vector_N": [0, 0, -20]}],
                     "view": {"checks": [{"kind": "stress"}, {"kind": "displacement", "limit_mm": 1, "faces": [loaded]}]}}
            bare = solve(step, directory / "bare.glb", study)
            named = solve(step, directory / "named.glb", {"analysis": "static", **study})
            self.assertEqual(bare.glb.read_bytes(), named.glb.read_bytes())
            self.assertEqual(glb_attribute_names(named.glb), ["POSITION", "NORMAL", "COLOR_0", "_VON_MISES", "_DISPLACEMENT", "_FACE"])
            extras = read_glb(named.glb)[0]["meshes"][0]["extras"]
            self.assertNotIn("analysis", extras)
            self.assertEqual([f["attribute"] for f in extras["fields"]], ["_VON_MISES", "_DISPLACEMENT"])
            self.assertEqual(set(extras["fields"][0]), {"attribute", "name", "units", "min", "max", "attribute_scale"})
            first, second = sidecar(bare), sidecar(named)
            for written in (first, second):
                written.pop("study")
                written.pop("timings")
                written["files"].pop("glb")
            self.assertEqual(first, second)
            self.assertNotIn("analysis", second)
            self.assertEqual(named.analysis, "static")


