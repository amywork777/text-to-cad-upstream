"""Custom features (``cad.build123d.feature``): a function of the project's own declared one feature
of the design tree, as Onshape's FeatureScript declares one.

The declaration is checked on its own here, without the tracer; the tree is read through the edit
service end to end, as ``test_edit`` reads it.
"""

from __future__ import annotations

import shutil
import unittest

from tests.python.packages.cad.test_edit import project
from tests.python.packages.cad.test_edit import setUpModule as _engine_of_its_own


def setUpModule():
    _engine_of_its_own()


class Declaration(unittest.TestCase):
    def test_a_call_is_a_plain_call_its_parameters_checked_first(self):
        from cad.build123d import Count, FeatureError, Length, feature

        made = []

        @feature("Bolt Circle", diameter=Length(min=0), count=Count(min=1))
        def bolt_circle(body, diameter, count, depth=5):
            made.append((body, diameter, count, depth))
            return body + 1

        self.assertEqual(bolt_circle(1, 60, count=6), 2)
        self.assertEqual(made, [(1, 60, 6, 5)])
        for args, words in (((1, -1, 6), "Bolt Circle: diameter must be at least 0 (was -1)"),
                            ((1, 60, 0), "Bolt Circle: count must be at least 1 (was 0)"),
                            ((1, 60, 2.5), "Bolt Circle: count must be a whole number (was 2.5)"),
                            ((1, "60", 2), "Bolt Circle: diameter must be a number (was '60')")):
            with self.subTest(args=args), self.assertRaises(FeatureError) as raised:
                bolt_circle(*args)
            self.assertEqual(str(raised.exception), words)
        # Refused before it ran: nothing was made.
        self.assertEqual(len(made), 1)

    def test_a_spec_for_a_parameter_the_function_lacks_is_refused(self):
        from cad.build123d import Length, feature

        with self.assertRaises(TypeError):
            feature(width=Length())(lambda body, depth: body)

    def test_the_active_call_is_the_outermost(self):
        from cad.build123d import _features
        from cad.build123d import feature

        seen = []

        @feature()
        def inner(x):
            seen.append(_features.active().definition.name)
            return x

        @feature("Outer Thing")
        def outer(x):
            return inner(x)

        self.assertIsNone(_features.active())
        outer(1)
        inner(2)
        self.assertEqual(seen, ["Outer Thing", "Inner"])
        self.assertIsNone(_features.active())

    def test_a_library_describes_its_own_features_in_order_with_their_defaults_and_groups(self):
        import types

        from cad.build123d import Angle, Bool, Count, Enum, feature
        from cad.build123d._features import library

        module = types.ModuleType("parts_library")
        source = (
            "from cad.build123d import Angle, Bool, Count, Enum, feature\n"
            "@feature('Spokes', collapsed=('Options',), count=Count(min=1), twist=Angle(label='Twist'),\n"
            "         style=Enum({'round': 'Round', 'flat': 'Flat'}, group='Options'), mirrored=Bool(group='Options'))\n"
            "def spokes(body, count, twist=0, style='round', mirrored=False):\n"
            "    \"\"\"Spokes from hub to rim.\"\"\"\n"
            "    return body\n"
        )
        exec(compile(source, "parts_library.py", "exec"), module.__dict__)

        @feature("Elsewhere", count=Count())
        def elsewhere(body, count):
            return body

        module.elsewhere = elsewhere  # imported from another module: not this library's
        module.plain = lambda body: body
        self.assertEqual(library(module), [{
            "name": "Spokes",
            "function": "parts_library.spokes",
            "doc": "Spokes from hub to rim.",
            "params": [
                {"name": "count", "kind": "count", "label": "Count", "min": 1, "max": None, "group": None},
                {"name": "twist", "kind": "angle", "label": "Twist", "min": None, "max": None, "group": None, "default": 0},
                {"name": "style", "kind": "enum", "label": "Style", "min": None, "max": None, "group": "Options",
                 "choices": [{"value": "round", "label": "Round"}, {"value": "flat", "label": "Flat"}], "default": "round"},
                {"name": "mirrored", "kind": "bool", "label": "Mirrored", "min": None, "max": None, "group": "Options",
                 "default": False},
            ],
            "collapsed": ["Options"],
        }])

    def test_switches_choices_and_picks_are_checked_and_name_the_parameter(self):
        from build123d import Box

        from cad.build123d import Bool, Edges, Enum, Faces, FeatureError, feature

        @feature("Lip", side=Enum(["inside", "outside"]), rounded=Bool(), faces=Faces(max=1), edges=Edges())
        def lip(body, faces=None, edges=None, side="inside", rounded=False):
            return body

        box = Box(10, 10, 10)
        self.assertIs(lip(box, faces=box.faces()[0], edges=box.edges()[:2]), box)
        for kwargs, param, words in (
                ({"faces": box.faces()[0], "edges": box.edges(), "side": "across"}, "side",
                 "Lip: side must be one of 'inside', 'outside' (was 'across')"),
                ({"faces": box.faces()[0], "edges": box.edges(), "rounded": 1}, "rounded", "Lip: rounded must be True or False (was 1)"),
                ({"faces": box.faces()[:2], "edges": box.edges()}, "faces", "Lip: faces takes at most 1 faces (was 2)"),
                ({"faces": box.faces()[0], "edges": box.faces()}, "edges", "Lip: edges must be edges of the body (was ShapeList)"),
                ({"faces": box.faces()[0], "edges": []}, "edges", "Lip: edges needs at least one of the body's edges")):
            with self.subTest(param=param), self.assertRaises(FeatureError) as raised:
                lip(box, **kwargs)
            self.assertEqual((str(raised.exception), raised.exception.feature, raised.exception.param), (words, "Lip", param))

    def test_a_declaration_that_cannot_be_a_feature_is_refused(self):
        from cad.build123d import Enum, Length, feature

        # The body as a parameter, a group no parameter is in, an enum with no choices.
        for make in (lambda: feature(body=Length())(lambda body: body),
                     lambda: feature(collapsed=("Advanced",), depth=Length())(lambda body, depth: body),
                     lambda: Enum([])):
            with self.assertRaises(TypeError):
                make()


FLANGE = {
    "flange_features.py": """
        from build123d import Cylinder, PolarLocations
        from cad.build123d import Count, Length, feature


        @feature("Bolt Circle", diameter=Length(min=0), count=Count(min=1), hole=Length(label="Hole Diameter", min=0))
        def bolt_circle(body, diameter, count, hole, depth=20):
            for place in PolarLocations(diameter / 2, count):
                body = body - place * Cylinder(hole / 2, depth)
            return body
    """,
    "flange.py": """
        from build123d import Cylinder
        from cad import model
        from flange_features import bolt_circle

        BOLT_CIRCLE = 60


        @model
        def flange():
            body = Cylinder(40, 8)
            body = bolt_circle(body, diameter=BOLT_CIRCLE, count=6, hole=6.6)
            return body
    """,
}


class InTheTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cad.edit import service as edit

        cls.service = edit.EditService(build=False)

    @classmethod
    def tearDownClass(cls):
        cls.service.close()

    def setUp(self):
        self.root = project(FLANGE)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.file = str(self.root / "flange.step")

    def row(self, state):
        return next(row for row in state["rows"] if row.get("custom"))

    def test_a_call_reads_as_one_feature_by_its_name_with_its_parameters_as_inputs(self):
        state = self.service.state(self.file)
        self.assertTrue(state["ok"], state.get("error"))
        kinds = [feature["kind"] for feature in state["features"] if feature["kind"] != "Sketch"]
        # Six holes cut in the feature's loop are one row, not six cuts.
        self.assertEqual(kinds, ["Boss-Extrude", "Bolt Circle"])
        bolts = next(feature for feature in state["features"] if feature["kind"] == "Bolt Circle")
        self.assertEqual(bolts["custom"], {"name": "Bolt Circle", "function": "flange_features.bolt_circle"})
        self.assertEqual(bolts["count"], 1)
        row = self.row(state)
        self.assertEqual([(item["label"], item["formula"], item["unit"]) for item in row["inputs"]],
                         [("Diameter", "BOLT_CIRCLE", "mm"), ("Count", "6", ""), ("Hole Diameter", "6.6", "mm")])
        # Edit Feature opens Edit Parameters on them, not a box for what the feature made inside.
        self.assertEqual(bolts["edit"]["command"], "sizes")

    def test_an_input_changes_the_number_where_it_is_written(self):
        state = self.service.state(self.file)
        row = self.row(state)
        count = [item["label"] for item in row["inputs"]].index("Count")
        changed = self.service.change({"file": self.file, "input": {"row": row["key"], "index": count}, "text": "8",
                                       "files": state["files"]})
        self.assertTrue(changed["ok"], changed.get("error"))
        self.assertIn("count=8, hole=6.6", (self.root / "flange.py").read_text(encoding="utf-8"))
        diameter = [item["label"] for item in row["inputs"]].index("Diameter")
        changed = self.service.change({"file": self.file, "input": {"row": row["key"], "index": diameter}, "text": "64",
                                       "files": changed["files"]})
        self.assertTrue(changed["ok"], changed.get("error"))
        self.assertIn("BOLT_CIRCLE = 64\n", (self.root / "flange.py").read_text(encoding="utf-8"))

    def test_a_value_its_spec_refuses_stops_the_build_with_the_feature_s_words(self):
        flange = self.root / "flange.py"
        flange.write_text(flange.read_text(encoding="utf-8").replace("count=6", "count=0"), encoding="utf-8")
        bad = self.service.state(self.file)
        self.assertFalse(bad["ok"])
        self.assertIn("Bolt Circle: count must be at least 1 (was 0)", bad["error"])


if __name__ == "__main__":
    unittest.main()
