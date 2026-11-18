"""A GSL model as the graph of its names (``cad.omega._graph``): read from the source alone, no compiler run."""

from __future__ import annotations

import unittest

from cad.omega._graph import graph

# The skill's bracket (`omega-gsl.md`, "Write a model"), with a slider of its own.
BRACKET = """@scene(120)

// A bracket: an upright standing on a plate, blended, with a 2 mm skin and a gyroid infill.
@range(1, 4) wall = 2;
plate = boxCentered([0, 0, 3], [80, 40, 6]);
upright = boxCentered([-35, 0, 28], [6, 32, 44]);
solid = unionRound(plate, upright, 6);
skin = max(solid, -(solid + wall));

g = sin(p.x * 0.5) * cos(p.y * 0.5) + sin(p.y * 0.5) * cos(p.z * 0.5) + sin(p.z * 0.5) * cos(p.x * 0.5);
infill = max(abs(g) - 0.4, solid + 1);

return min(skin, infill);
"""

# A function with several outputs (`metal.aluminum` returns a material and a colour) and properties of the
# shape: its gradient read (`plate.dp`, a property read like a function), a swizzle of that, and its
# material and colour set.
PROPERTIES = """@scene(120)
@range(3, 12) t = 6.0;
plate = boxCentered([0, 0, t / 2], [80, 40, t]);
up = plate.dp.z;
lean = max(plate, 0.5 - up, plate.dp.x);
mat, col = metal.aluminum();
lean.material = mat;
lean.color = col;
return lean;
"""


class Graph(unittest.TestCase):
    def test_each_name_is_a_node_made_from_the_names_its_expression_uses(self):
        made = graph(BRACKET)
        self.assertEqual([(node["id"], node["kind"], node["op"], node["line"]) for node in made["nodes"]], [
            ("wall", "input", "number", 4), ("plate", "block", "boxCentered", 5), ("upright", "block", "boxCentered", 6),
            ("solid", "block", "unionRound", 7), ("skin", "block", "max", 8), ("g", "block", "expression", 10),
            ("infill", "block", "max", 11), ("return", "output", "return", 13)])
        self.assertEqual(made["nodes"][0]["range"], [1.0, 4.0])
        # `p.x` is the point's, never a node; `solid` is used twice in skin, one edge.
        self.assertEqual(made["edges"], [["plate", "solid"], ["upright", "solid"], ["solid", "skin"], ["wall", "skin"],
                                         ["g", "infill"], ["solid", "infill"], ["skin", "return"], ["infill", "return"]])

    def test_a_name_given_min_and_max_is_an_input(self):
        # The field route's own fixture (`test_field_route.py`).
        made = graph("@scene(40)\nr = 8.0;\nr.min = 2.0;\nr.max = 15.0;\nball = length(p) - r;\nreturn ball;\n")
        self.assertEqual([(node["id"], node["kind"], node.get("range")) for node in made["nodes"]],
                         [("r", "input", [2.0, 15.0]), ("ball", "block", None), ("return", "output", None)])
        self.assertEqual(made["edges"], [["r", "ball"], ["ball", "return"]])

    def test_brackets_and_comments_do_not_split_a_statement_and_what_is_not_read_is_left_out(self):
        made = graph("a = f(1; // not the end\n 2);\nb = a + 1;\nsomething odd here;\nreturn b, a;\n")
        self.assertEqual([node["id"] for node in made["nodes"]], ["a", "b", "return"])
        self.assertEqual(made["nodes"][0]["op"], "f")
        self.assertEqual(made["nodes"][1]["op"], "expression")
        self.assertEqual(made["edges"], [["a", "b"], ["b", "return"], ["a", "return"]])

    def test_a_call_with_several_outputs_is_one_node_with_a_port_per_output(self):
        made = graph(PROPERTIES)
        call = next(node for node in made["nodes"] if node["id"] == "mat, col")
        self.assertEqual((call["kind"], call["op"], call["outputs"], call["line"]), ("block", "metal.aluminum", ["mat", "col"], 6))
        # Each name used is wired from its own output: the edge's third element.
        self.assertIn(["mat, col", "lean.material =", "mat"], made["edges"])
        self.assertIn(["mat, col", "lean.color =", "col"], made["edges"])
        self.assertFalse([edge for edge in made["edges"] if edge[0] in ("mat", "col")])

    def test_a_property_is_a_node_of_its_own_off_the_value_it_is_of(self):
        made = graph(PROPERTIES)
        self.assertEqual([(node["id"], node["kind"]) for node in made["nodes"]], [
            ("t", "input"), ("plate", "block"), ("plate.dp", "property"), ("up", "block"), ("lean", "block"),
            ("mat, col", "block"), ("lean.material =", "property"), ("lean.color =", "property"), ("return", "output")])
        read = made["nodes"][2]
        self.assertEqual((read["op"], read["of"], read.get("set")), ("dp", "plate", None))
        self.assertEqual({key: made["nodes"][7][key] for key in ("op", "of", "set")}, {"op": "color", "of": "lean", "set": True})
        # The gradient is read twice (`up`, and in `lean` itself), one node; `lean` uses `plate` itself as well.
        self.assertEqual(made["edges"], [
            ["t", "plate"], ["plate", "plate.dp"], ["plate.dp", "up"], ["plate", "lean"], ["up", "lean"], ["plate.dp", "lean"],
            ["lean", "lean.material ="], ["mat, col", "lean.material =", "mat"], ["lean", "lean.color ="],
            ["mat, col", "lean.color =", "col"], ["lean", "return"]])


if __name__ == "__main__":
    unittest.main()
