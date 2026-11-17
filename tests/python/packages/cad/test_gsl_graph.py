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


if __name__ == "__main__":
    unittest.main()
