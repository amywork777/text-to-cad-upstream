"""The public verb surface, and the CLIs that mirror it (design/format-doors.md).

Three properties that only hold if something checks them:

* **The manifest.** Exactly the declared names are public on each format
  namespace, and every public verb is fully annotated — annotation is what
  makes a CLI derivable, so an unannotated parameter is a silently
  undispatchable flag.
* **Signature sync.** For every command, the parser's options ARE the
  function's parameters, modulo an explicit per-command allowlist that is
  EMPTY for mirrors. This fails on a one-sided addition in either direction,
  which doubles as shell-thinness enforcement: a CLI that grew a flag its verb
  cannot express has stopped being a shell.
* **The import budget.** A public namespace must import without the CAD stack.
  A model script pays this import before its freshness gate runs (~0.2s), and
  waking OCP there would cost seconds on every already-current model.
"""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
import unittest

from cadgen import cli
from cadgen._internal.cli_from_function import (
    JSON_FLAG_DEST,
    cli_from_function,
    function_parameters,
    parser_dests,
)

# The manifest: format namespace -> exactly the verbs it exports.
PUBLIC_SURFACE: dict[str, tuple[str, ...]] = {
    "cadgen.step": ("build",),
}

# Commands whose parser is GENERATED from the verb it calls. No allowlist is
# possible here: the parser has no independent existence.
MIRRORS: dict[str, tuple[str, str]] = {
    "step build": ("cadgen.step", "build"),
}

# Commands with a hand-written parser, and the options that parser may carry
# beyond its verb's parameters. A snapshot's camera/theme/display surface is
# exactly what disqualifies it from mirror status.
ADAPTERS: dict[str, frozenset[str]] = {}

# Commands not yet re-homed under the schema. This set only shrinks.
UNCLASSIFIED = {
    "step export",
    "step inspect",
    "step snapshot",
    "dxf snapshot",
    "urdf validate",
    "sdf validate",
    "srdf validate",
    "doctor",
    "cache",
    "snapshot",
    "daemon",
    "daemon status",
}

HEAVY = ("OCP", "build123d", "ezdxf", "shapely")


def _verb(target: tuple[str, str]):
    module, attribute = target
    return getattr(importlib.import_module(module), attribute)


class Manifest(unittest.TestCase):
    def test_each_namespace_exports_exactly_its_declared_verbs(self):
        for module_name, verbs in PUBLIC_SURFACE.items():
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertEqual(sorted(verbs), sorted(module.__all__))
                for verb in verbs:
                    self.assertTrue(callable(getattr(module, verb)))

    def test_every_public_verb_is_fully_annotated_and_derivable(self):
        for module_name, verbs in PUBLIC_SURFACE.items():
            for verb in verbs:
                with self.subTest(verb=f"{module_name}.{verb}"):
                    func = _verb((module_name, verb))
                    signature = inspect.signature(func)
                    unannotated = [
                        name
                        for name, parameter in signature.parameters.items()
                        if parameter.annotation is parameter.empty
                    ]
                    self.assertEqual([], unannotated)
                    self.assertIsNot(signature.return_annotation, signature.empty)
                    # Derivability is the property; raising here is the failure.
                    cli_from_function(func, prog="probe")

    def test_a_format_namespace_is_also_its_decorator(self):
        # `from cadgen import step` must keep declaring models: the namespace
        # module and the decorator are ONE object, so importing the verbs can
        # never shadow the authoring API.
        import cadgen

        self.assertIs(cadgen.step, importlib.import_module("cadgen.step"))
        self.assertTrue(callable(cadgen.step))

    def test_the_retired_commands_are_gone(self):
        # No backwards compatibility: `cadgen import` folded into `step build`.
        self.assertNotIn("import", cli._COMMANDS)
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("cadgen.cli.step_import")


class SignatureSync(unittest.TestCase):
    def test_every_command_is_classified(self):
        classified = set(MIRRORS) | set(ADAPTERS) | UNCLASSIFIED
        self.assertEqual(
            set(cli._COMMANDS),
            classified,
            "a new command must be declared a mirror, an adapter, or explicitly unclassified",
        )

    def test_a_mirrors_parser_is_exactly_its_signature(self):
        for command, target in MIRRORS.items():
            with self.subTest(command=command):
                module_name, _ = cli._COMMANDS[command]
                module = importlib.import_module(module_name)
                dests = set(parser_dests(module.build_parser())) - {JSON_FLAG_DEST}
                self.assertEqual(set(function_parameters(_verb(target))), dests)

    def test_an_adapters_extra_options_are_declared(self):
        for command, allowed in ADAPTERS.items():
            with self.subTest(command=command):
                module_name, _ = cli._COMMANDS[command]
                module = importlib.import_module(module_name)
                target = MIRRORS.get(command) or module.VERB
                parameters = set(function_parameters(_verb(target)))
                dests = set(parser_dests(module.build_parser())) - {JSON_FLAG_DEST}
                self.assertEqual(
                    set(), dests - parameters - set(allowed), "undeclared parser option"
                )
                self.assertEqual(
                    set(), parameters - dests - set(allowed), "parameter with no CLI option"
                )


class ImportBudget(unittest.TestCase):
    """Run in a subprocess: this one has the CAD stack loaded already."""

    def test_public_namespaces_import_without_the_cad_stack(self):
        imports = "; ".join(f"import {name}" for name in PUBLIC_SURFACE)
        code = (
            f"import sys; {imports};"
            f"print('HEAVY:' + ','.join(m for m in {HEAVY!r} if m in sys.modules))"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("HEAVY:\n", proc.stdout)

    def test_a_generated_clis_help_does_not_wake_the_cad_stack(self):
        for command in MIRRORS:
            with self.subTest(command=command):
                module_name, _ = cli._COMMANDS[command]
                code = (
                    "import sys, contextlib, io;"
                    f"import {module_name} as m;"
                    "err=io.StringIO();"
                    "contextlib.suppress(SystemExit).__enter__();"
                    "m.build_parser().format_help();"
                    f"print('HEAVY:' + ','.join(x for x in {HEAVY!r} if x in sys.modules))"
                )
                proc = subprocess.run(
                    [sys.executable, "-c", code], capture_output=True, text=True
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("HEAVY:\n", proc.stdout)


if __name__ == "__main__":
    unittest.main()
