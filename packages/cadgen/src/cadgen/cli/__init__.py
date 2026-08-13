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
import sys

# name -> (module, "one-line help"). The module must expose ``main(argv)`` returning an
# exit code. Keep this list alphabetical within groups and the help text under ~60 chars
# so ``cadgen --help`` stays a single readable column.
_COMMANDS: dict[str, tuple[str, str]] = {
    "viewer": ("cadgen.viewer.start_viewer", "start the CAD Viewer on a local directory"),
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

    command, rest = argv[0], argv[1:]
    entry = _COMMANDS.get(command)
    if entry is None:
        sys.stderr.write(f"cadgen: unknown command {command!r}\n\n" + _usage())
        return 2

    module_name, _ = entry
    module = importlib.import_module(module_name)
    return int(module.main(rest) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
