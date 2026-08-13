"""The ``cadgen`` console script — a subcommand dispatcher over the distribution's CLIs.

Every subcommand is also reachable as ``python -m cadgen.<module>``; this is the friendly
front door, not a second implementation. A subcommand's parser lives in its own module and
owns its arguments, so ``cadgen viewer --port 3245`` and ``python -m cadgen.viewer --port
3245`` take the same flags and print the same output.

**Dispatch is lazy on purpose.** Importing a CAD subcommand pulls in OCP/build123d, which
costs seconds and needs the heavy dependency set installed. ``cadgen --help``, an unknown
command, and ``cadgen viewer`` must not pay for that, so the registry stores dotted module
names as strings and imports exactly the one being run. Do not hoist these to module-level
imports when adding commands.
"""

from __future__ import annotations

import importlib
import inspect
import sys

# name -> (module, "one-line help"). The module must expose ``main(argv)`` returning an
# exit code. Keep this list grouped as below and the help text under ~60 chars so
# ``cadgen --help`` stays a single readable column.
#
# Two-word names are intentional: `step gen` and `dxf gen` are different commands with
# different parsers, and flattening them to one `gen` would force a --kind flag that
# neither parser wants. Dispatch joins argv[0:2] before argv[0], so the two-word form wins
# where it exists and `cadgen viewer` still works as one word.
_COMMANDS: dict[str, tuple[str, str]] = {
    # STEP
    "step gen": ("cadgen.cli.step_gen", "build STEP targets from .step.py generators"),
    "step artifact": ("cadgen.cli.step_artifact", "build a STEP's GLB/topology artifact"),
    "step export": ("cadgen.cli.step_export", "export a built STEP package to a file"),
    "step inspect": ("cadgen.cli.step_inspect", "inspect selector references in a STEP"),
    "step snapshot": ("cadgen.cli.step_snapshot", "render a STEP or mesh to an image"),
    # DXF
    "dxf gen": ("cadgen.cli.dxf_gen", "build DXF targets from .dxf.py generators"),
    "dxf artifact": ("cadgen.cli.dxf_artifact", "build a DXF's drawing package"),
    "dxf snapshot": ("cadgen.cli.dxf_snapshot", "render a DXF to an image"),
    # Implicit
    "implicit gen": ("cadgen.cli.implicit_gen", "build implicit CAD targets"),
    "implicit export": ("cadgen.cli.implicit_export_js", "export an implicit model (via Node)"),
    "implicit snapshot": ("cadgen.cli.implicit_snapshot", "render an implicit model"),
    # Generic / services
    "snapshot": ("cadgen.cli.snapshot", "render any supported input to an image"),
    "viewer": ("cadgen.viewer.start_viewer", "start the CAD Viewer on a local directory"),
    "daemon": ("cadgen.daemon", "run the warm build daemon"),
}

_USAGE_HEAD = "usage: cadgen <command> [args...]\n\ncommands:\n"
_USAGE_TAIL = (
    "\nRun 'cadgen <command> --help' for a command's own options.\n"
    "Each command is also available as 'python -m <module>'.\n"
)


def _usage() -> str:
    width = max((len(name) for name in _COMMANDS), default=0)
    lines = [f"  {name.ljust(width)}  {help_text}" for name, (_, help_text) in sorted(_COMMANDS.items())]
    return _USAGE_HEAD + "\n".join(lines) + "\n" + _USAGE_TAIL


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in {"-h", "--help", "help"}:
        sys.stdout.write(_usage())
        return 0

    if argv[0] in {"-V", "--version"}:
        from cadgen import __version__

        sys.stdout.write(f"cadgen {__version__}\n")
        return 0

    # Longest match first, so `step gen` beats a hypothetical `step`.
    command, rest = " ".join(argv[:2]), argv[2:]
    entry = _COMMANDS.get(command)
    if entry is None:
        command, rest = argv[0], argv[1:]
        entry = _COMMANDS.get(command)
    if entry is None:
        sys.stderr.write(f"cadgen: unknown command {command!r}\n\n" + _usage())
        return 2

    module_name, _ = entry
    module = importlib.import_module(module_name)

    # Tell the parser which front door it was reached through, so `cadgen step gen --help`
    # says "cadgen step gen" and the skill's own `scripts/gen` still says "scripts/gen".
    # Not every command has a parser to name (the viewer and daemon own their own), hence
    # the signature check rather than a blanket keyword.
    if "prog" in inspect.signature(module.main).parameters:
        return int(module.main(rest, prog=f"cadgen {command}") or 0)
    return int(module.main(rest) or 0)

