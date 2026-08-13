"""What `from cadgen import ...` offers, and what it costs.

Two properties that are easy to break together. Every name in ``__all__`` must actually
resolve -- the lazy ``__getattr__`` dispatches on hand-written name sets, so adding a name
to ``__all__`` and forgetting the branch advertises an AttributeError. And importing the
package must stay cheap: the whole point of the lazy dispatch is that `import cadgen`
does not pay for OCP, which costs seconds and is useless to a caller who only wanted
`__version__`.
"""

import subprocess
import sys
import unittest

import cadgen

HEAVY = ("OCP", "build123d")


class RootExports(unittest.TestCase):
    def test_every_advertised_name_resolves(self):
        unresolvable = [name for name in cadgen.__all__ if not hasattr(cadgen, name)]
        self.assertEqual([], unresolvable, "in __all__ but not handled by __getattr__")

    def test_the_generator_facing_helpers_are_at_the_root(self):
        """A generator should not need a submodule path for these.

        `import_step` in particular is the cached build123d drop-in and the most
        generator-facing thing cadgen owns; it used to require
        `from cadgen.step_scene import import_step` while `AssemblyHelper` sat at the root.
        """
        for name in (
            "AssemblyHelper", "target", "track", "report",
            "import_step", "load_step_scene", "located_shape",
            "occurrence_selector_id", "scene_occurrence_shape",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(cadgen, name))

    def test_importing_cadgen_does_not_import_the_cad_stack(self):
        """Run in a subprocess: this one almost certainly has OCP loaded already."""
        code = (
            "import sys, cadgen;"
            f"print('HEAVY:' + ','.join(m for m in {HEAVY!r} if m in sys.modules))"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        marked = [ln for ln in proc.stdout.splitlines() if ln.startswith("HEAVY:")]
        self.assertEqual(["HEAVY:"], marked, "importing cadgen pulled in the CAD stack")


if __name__ == "__main__":
    unittest.main()
