"""Custom features (``cad.build123d.feature``): a function of the project's own declared one feature
of the design tree, as Onshape's FeatureScript declares one.

The declaration is checked on its own here, without the tracer; the tree is read through the edit
service end to end, as ``test_edit`` reads it.
"""

from __future__ import annotations

import math
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
                {"name": "count", "kind": "count", "label": "Count", "min": 1, "max": None, "group": None, "required": True},
                {"name": "twist", "kind": "angle", "label": "Twist", "min": None, "max": None, "group": None, "required": False, "default": 0},
                {"name": "style", "kind": "enum", "label": "Style", "min": None, "max": None, "group": "Options",
                 "required": False, "choices": [{"value": "round", "label": "Round"}, {"value": "flat", "label": "Flat"}], "default": "round"},
                {"name": "mirrored", "kind": "bool", "label": "Mirrored", "min": None, "max": None, "group": "Options",
                 "required": False, "default": False},
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
        from build123d import Cylinder, PolarLocations, chamfer, fillet
        from cad.build123d import Angle, Bool, Count, Edges, Enum, Length, feature


        @feature("Bolt Circle", collapsed=("Options",), diameter=Length(min=0), count=Count(min=1, max=24),
                 hole=Length(label="Hole Diameter", min=0),
                 spread=Enum({"full": "Full circle", "half": "Half circle"}, group="Options"),
                 start=Angle(label="Start Angle", group="Options"), staggered=Bool(group="Options"))
        def bolt_circle(body, diameter, count, hole, spread="full", start=0, staggered=False, depth=20):
            \"\"\"Through holes spaced on a circle about the part's axis.\"\"\"
            full = spread == "full"
            places = PolarLocations(diameter / 2, count, start_angle=start, angular_range=360 if full else 180, endpoint=not full)
            for index, place in enumerate(places):
                small = staggered and index % 2
                body = body - place * Cylinder(hole / 2 * (0.75 if small else 1), depth)
            return body


        @feature("Edge Break", edges=Edges(), size=Length(min=0), style=Enum({"round": "Round", "chamfer": "Chamfer"}))
        def edge_break(body, edges, size=1, style="round"):
            \"\"\"Breaks sharp edges: a round or a chamfer of one size.\"\"\"
            return fillet(edges, radius=size) if style == "round" else chamfer(edges, length=size)
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

# The flange's top outer edge, as the viewer reads a pick of it.
TOP_RIM = {"selector": "e1", "type": "circle", "center": [0.0, 0.0, 4.0], "size": 2 * math.pi * 40}


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
        # The project's custom code trusted, as the person does at its prompt (`Trust`, below).
        from cad.edit import trust

        self.assertTrue(trust.grant(self.root, trust.gate(self.root)["trust"]["digest"])["ok"])

    def row(self, state, name="Bolt Circle"):
        return next(row for row in state["rows"] if (row.get("custom") or {}).get("name") == name)

    def command(self, state, function, inputs=None, picks=None, row=None):
        spec = {"command": "custom", "function": function, "inputs": inputs or {}, "picks": picks or {}}
        if row:
            spec["replace"] = {"row": row}
        return self.service.change({"file": self.file, "command": spec, "files": state["files"]})

    def test_a_call_reads_as_one_feature_by_its_name_with_its_parameters_as_inputs(self):
        state = self.service.state(self.file)
        self.assertTrue(state["ok"], state.get("error"))
        kinds = [feature["kind"] for feature in state["features"] if feature["kind"] != "Sketch"]
        # Six holes cut in the feature's loop are one row, not six cuts.
        self.assertEqual(kinds, ["Boss-Extrude", "Bolt Circle"])
        bolts = next(feature for feature in state["features"] if feature["kind"] == "Bolt Circle")
        self.assertEqual((bolts["custom"]["name"], bolts["custom"]["function"]), ("Bolt Circle", "flange_features.bolt_circle"))
        self.assertEqual(bolts["count"], 1)
        row = self.row(state)
        self.assertEqual([(item["label"], item["formula"], item["unit"]) for item in row["inputs"]],
                         [("Diameter", "BOLT_CIRCLE", "mm"), ("Count", "6", ""), ("Hole Diameter", "6.6", "mm")])
        # Edit Feature opens the feature's own dialog, not a box for what the feature made inside.
        self.assertEqual(bolts["edit"], {"command": "custom", "function": "flange_features.bolt_circle", "row": row["key"]})

    def test_its_dialog_reads_every_parameter_with_its_value_its_code_and_its_group(self):
        state = self.service.state(self.file)
        params = self.row(state)["custom"]["params"]
        self.assertEqual([(each["name"], each["kind"], each["label"], each["group"], each["value"], each["code"], each["input"])
                          for each in params],
                         [("diameter", "length", "Diameter", None, "60", "BOLT_CIRCLE", 0),
                          ("count", "count", "Count", None, "6", "6", 1),
                          ("hole", "length", "Hole Diameter", None, "6.6", "6.6", 2),
                          ("spread", "enum", "Spread", "Options", "full", None, None),
                          ("start", "angle", "Start Angle", "Options", "0", None, None),
                          ("staggered", "bool", "Staggered", "Options", False, None, None)])
        self.assertEqual(self.row(state)["custom"]["collapsed"], ["Options"])
        # The toolbar's Custom group: every feature the project's files declare, where it is imported from.
        self.assertEqual([(each["name"], each["module"], each["file"]) for each in state["customFeatures"]],
                         [("Bolt Circle", "flange_features", "flange_features.py"), ("Edge Break", "flange_features", "flange_features.py")])

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

    def test_edit_feature_writes_the_call_again_keeping_what_was_not_changed(self):
        state = self.service.state(self.file)
        reply = self.command(state, "flange_features.bolt_circle", {"count": "8", "spread": "half", "staggered": True},
                             row=self.row(state)["key"])
        self.assertTrue(reply["ok"], reply.get("error"))
        # A size written by name stays that name; the switch and the choice are written as values.
        self.assertIn("    body = bolt_circle(body, diameter=BOLT_CIRCLE, count=8, hole=6.6, spread='half', staggered=True)\n",
                      (self.root / "flange.py").read_text(encoding="utf-8"))
        params = {each["name"]: each["value"] for each in self.row(reply)["custom"]["params"]}
        self.assertEqual((params["count"], params["spread"], params["staggered"]), ("8", "half", True))
        self.assertEqual((reply["change"]["feature"], reply["change"]["edited"]), ("Bolt Circle", True))
        # What the agent is told: each value changed, a choice by its label and a switch on or off.
        self.assertEqual([(each["label"], each["display"]) for each in reply["change"]["inputs"]],
                         [("Count", "8"), ("Spread", "half circle"), ("Staggered", "on")])

    def test_a_feature_from_the_toolbar_is_a_new_call_imported_and_its_edges_picked_on_the_model(self):
        state = self.service.state(self.file)
        reply = self.command(state, "flange_features.edge_break", {"size": "1", "style": "chamfer"}, picks={"edges": [TOP_RIM]})
        self.assertTrue(reply["ok"], reply.get("error"))
        text = (self.root / "flange.py").read_text(encoding="utf-8")
        # Imported beside what the file imports; its edges written by where they are; a default left out.
        self.assertIn("from flange_features import bolt_circle\nfrom flange_features import edge_break\n", text)
        line = next(each.strip() for each in text.splitlines() if "edge_break(" in each and "import" not in each)
        self.assertTrue(line.startswith("body = edge_break(body, edges=body.edges()"), line)
        self.assertTrue(line.endswith(", style='chamfer')"), line)
        self.assertNotIn("size=", line)
        made = self.row(reply, "Edge Break")
        self.assertEqual({each["name"]: each["value"] for each in made["custom"]["params"]}, {"edges": 1, "size": "1", "style": "chamfer"})

    def test_a_required_pick_left_out_is_asked_for(self):
        state = self.service.state(self.file)
        reply = self.command(state, "flange_features.edge_break", {"size": "1"})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"], "Select edges on the model for Edges.")

    def test_a_value_its_spec_refuses_is_the_dialog_s_headline_and_names_its_parameter(self):
        state = self.service.state(self.file)
        before = (self.root / "flange.py").read_text(encoding="utf-8")
        reply = self.command(state, "flange_features.bolt_circle", {"count": "0"}, row=self.row(state)["key"])
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"], "Bolt Circle: count must be at least 1 (was 0). Nothing changed.")
        self.assertEqual(reply["featureError"], {"message": "Bolt Circle: count must be at least 1 (was 0)", "feature": "Bolt Circle",
                                                 "param": "count"})
        self.assertEqual((self.root / "flange.py").read_text(encoding="utf-8"), before)
        # A size changed on the model says the same words first, its traceback under them.
        count = [item["label"] for item in self.row(state)["inputs"]].index("Count")
        sized = self.service.change({"file": self.file, "input": {"row": self.row(state)["key"], "index": count}, "text": "0",
                                     "files": state["files"]})
        self.assertFalse(sized["ok"])
        self.assertTrue(sized["error"].startswith("Bolt Circle: count must be at least 1 (was 0)\n\nTraceback"), sized["error"][:200])
        self.assertEqual(sized["featureError"]["param"], "count")

    def test_a_script_that_stops_on_a_feature_says_its_words_first(self):
        flange = self.root / "flange.py"
        flange.write_text(flange.read_text(encoding="utf-8").replace("count=6", "count=0"), encoding="utf-8")
        bad = self.service.state(self.file)
        self.assertFalse(bad["ok"])
        self.assertTrue(bad["error"].startswith("Bolt Circle: count must be at least 1 (was 0)\n\nTraceback"), bad["error"][:200])
        self.assertEqual(bad["featureError"]["param"], "count")


class Trust(unittest.TestCase):
    """A project's custom features are code it carries: none of the project runs in edit mode until the person
    trusts that code as it is (``cad.edit.trust``), as a document's macros do not run as it opens."""

    @classmethod
    def setUpClass(cls):
        from cad.edit import service as edit

        cls.service = edit.EditService(build=False)

    @classmethod
    def tearDownClass(cls):
        cls.service.close()

    def setUp(self):
        # A part script that would leave a mark if it ran: the gate is judged by what it did not do.
        self.root = project({**FLANGE, "flange.py": FLANGE["flange.py"].replace(
            "BOLT_CIRCLE = 60",
            "BOLT_CIRCLE = 60\n        from pathlib import Path as _P\n        _P(__file__).with_name('ran').write_text('yes')")})
        self.addCleanup(shutil.rmtree, self.root, True)
        self.file = str(self.root / "flange.step")

    def test_an_untrusted_project_runs_none_of_its_code_and_says_which_features_it_carries(self):
        state = self.service.state(self.file)
        self.assertEqual((state["ok"], state["reason"]), (False, "untrusted"))
        self.assertEqual(state["trust"]["files"], [{"file": "flange_features.py", "features": ["Bolt Circle", "Edge Break"]}])
        self.assertFalse(state["trust"]["changed"])
        self.assertIn("custom code features", state["error"])
        # Nothing of it ran: not the part script, not its features; nor does a change, or a face's question.
        self.assertFalse((self.root / "ran").exists())
        changed = self.service.change({"file": self.file, "literal": {"id": "x", "value": "1"}})
        self.assertEqual(changed["reason"], "untrusted")
        self.assertEqual(self.service.face_feature({"file": self.file, "face": 1})["reason"], "untrusted")
        self.assertFalse((self.root / "ran").exists())

    def test_trust_and_run_reads_the_part_and_is_remembered_until_the_code_changes(self):
        digest = self.service.state(self.file)["trust"]["digest"]
        trusted = self.service.change({"file": self.file, "trust": {"digest": digest}})
        self.assertTrue(trusted["ok"], trusted.get("error"))
        self.assertTrue(any((row.get("custom") or {}).get("name") == "Bolt Circle" for row in trusted["rows"]))
        self.assertTrue((self.root / "ran").exists())
        # Remembered: the next read runs it without asking.
        self.assertTrue(self.service.state(self.file)["ok"])
        # The feature's code changed: asked again, said as a change, and the old digest no longer trusts it.
        features = self.root / "flange_features.py"
        features.write_text(features.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        again = self.service.state(self.file)
        self.assertEqual(again["reason"], "untrusted")
        self.assertTrue(again["trust"]["changed"])
        stale = self.service.change({"file": self.file, "trust": {"digest": digest}})
        self.assertEqual(stale["reason"], "untrusted")
        self.assertIn("changed since you were asked", stale["error"])

    def test_a_project_without_custom_features_and_cadgen_s_own_are_never_asked_about(self):
        from cad.edit import trust
        from tests.python.packages.cad.test_edit import PLATE

        plain = project(PLATE)
        self.addCleanup(shutil.rmtree, plain, True)
        self.assertIsNone(trust.gate(plain))
        self.assertEqual(trust.custom_code(plain), [])

    def test_a_feature_is_found_by_reading_the_file_under_any_name_it_is_imported_as(self):
        from cad.edit.trust import _features_in

        self.assertEqual(_features_in("from cad.build123d import feature as f\n@f('Rim')\ndef rim(body):\n  return body\n"), ["Rim"])
        self.assertEqual(_features_in("import cad.build123d as b\n@b.feature()\ndef boss(body):\n  return body\n"), ["boss"])
        self.assertEqual(_features_in("from cad import build123d\n@build123d.feature\ndef web(body):\n  return body\n"), ["web"])
        # A decorator of the same name from elsewhere is not one, and a file that does not parse declares none.
        self.assertEqual(_features_in("from mylib import feature\n@feature()\ndef rim(body):\n  return body\n"), [])
        self.assertEqual(_features_in("def (:"), [])

    def test_trust_is_kept_in_the_user_s_state_never_in_the_project(self):
        from cad.edit import trust

        trust.grant(self.root, trust.gate(self.root)["trust"]["digest"])
        self.assertFalse(str(trust.store_path().resolve()).startswith(str(self.root.resolve())))
        self.assertTrue(trust.store_path().is_file())


if __name__ == "__main__":
    unittest.main()
