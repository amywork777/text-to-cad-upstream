"""The ``cadgen`` console script — a subcommand dispatcher over the distribution's CLIs.

Every subcommand is also reachable as ``python -m cadgen.<module>``; this is the friendly
front door, not a second implementation. A subcommand's parser lives in its own module and
owns its arguments, so ``cadgen import`` and ``python -m cadgen.cli.step_import`` take the
same flags and print the same output.

**Dispatch is lazy on purpose.** Importing a CAD subcommand pulls in OCP/build123d, which
costs seconds and needs the heavy dependency set installed. ``cadgen --help`` and an
unknown command must not pay for that, so the registry stores dotted module names as
strings and imports exactly the one being run. Do not hoist these to module-level imports
when adding commands.

The CAD Viewer is NOT here: it is a standalone app (the ``cad-viewer`` skill bundles it;
a checkout runs ``viewer/server/main.mjs`` directly), and cadgen is exclusively the
programmatic generation/inspection/snapshot toolchain.
"""

from __future__ import annotations

import importlib
import os
import re
import sys

# name -> (module, "one-line help"). The module must expose ``main(argv)`` returning an
# exit code. Keep this list grouped as below and the help text under ~60 chars so
# ``cadgen --help`` stays a single readable column.
#
# Two-word names are intentional where a noun has several verbs. Dispatch joins
# argv[0:2] before argv[0], so the two-word form wins where it exists and one-word
# commands like `daemon` still work.
#
# Generation has NO CLI (design/library-first-generation.md): a model script runs
# itself — `python <model>.py` through the @step/@dxf decorators.
_COMMANDS: dict[str, tuple[str, str]] = {
    # STEP
    "import": ("cadgen.cli.step_import", "build the render package for an imported STEP/STP"),
    "step export": ("cadgen.cli.step_export", "export a built STEP package to a file"),
    "step inspect": ("cadgen.cli.step_inspect", "inspect selector references in a STEP"),
    "step snapshot": ("cadgen.cli.step_snapshot", "render a STEP or mesh to an image"),
    # DXF
    "dxf snapshot": ("cadgen.cli.dxf_snapshot", "render a DXF to an image"),
    # Robot descriptions
    "urdf validate": ("cadgen.cli.urdf_validate", "validate URDF robot descriptions"),
    "sdf validate": ("cadgen.cli.sdf_validate", "validate SDF worlds and models"),
    "srdf validate": ("cadgen.cli.srdf_validate", "validate an SRDF against its URDF"),
    # Generic / services
    "doctor": ("cadgen.cli.doctor", "print installed cadgen and verify a skill's pin"),
    "cache": ("cadgen.cli.cache", "inspect or gc the user-level caches (info/gc)"),
    "snapshot": ("cadgen.cli.snapshot", "render any supported input to an image"),
    "daemon": ("cadgen.daemon", "run the warm build daemon"),
    # The two-word entry is required, not cosmetic: dispatch matches argv[0:2] first, so
    # without it `cadgen daemon status` falls through to one-word `daemon` and the
    # supervisor treats "status" as a stray argument.
    "daemon status": ("cadgen.cli.daemon_status", "show the warm daemon's workers"),
}

# `cadgen==1.2.3` / `cadgen[snapshot]==1.2.3`, as written by
# scripts/release/pin-cadgen-requirements.sh. Only the `==` form is a pin: a bare
# `cadgen` line is the development checkout, which resolves to the editable install.
_PIN_RE = re.compile(r"^cadgen(?:\[[a-z0-9_,.-]+\])?\s*==\s*(?P<pin>[^\s;#]+)")


def read_requirements_pin(requirements_path) -> str | None:
    """The exact ``cadgen==<version>`` a requirements.txt pins, or ``None``.

    ``None`` covers the non-cases uniformly: file absent/unreadable, or cadgen named
    unpinned — which is exactly the development checkout, whose editable install has no
    release version to match. Callers decide what a mismatch means (``cadgen doctor``
    reports it; :func:`enforce_requirements_pin` exits). String comparison rather than
    PEP 440 on purpose: pins are written mechanically as exact ``==`` by
    scripts/release/pin-cadgen-requirements.sh.
    """
    try:
        with open(requirements_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    return next(
        (match.group("pin") for match in map(_PIN_RE.match, (line.strip() for line in lines)) if match),
        None,
    )


def enforce_requirements_pin(requirements_path) -> None:
    """Fail fast when a published skill's pinned cadgen is not the installed one.

    A skill is published with `cadgen==<release>` in its requirements.txt, but nothing
    makes pip re-resolve it on a machine that already has some other cadgen — the skill
    then runs against a runtime it was never tested against and fails far from the
    cause. The per-verb skill shims that used to call this on every invocation are
    gone (skills are instruction-only over the ``cadgen`` front door); ``cadgen
    doctor`` is the user-facing check now, and this remains the enforcing primitive.

    Silent (the common cases) when :func:`read_requirements_pin` finds nothing to
    enforce, or the pin matches. Exits 3 otherwise — the same code as "cadgen is not
    installed", since both mean the same fix.
    """
    pin = read_requirements_pin(requirements_path)
    if pin is None:
        return

    from cadgen import __version__ as installed

    if pin == installed:
        return
    sys.stderr.write(
        f"This skill is pinned to cadgen=={pin} but cadgen {installed} is installed.\n"
        "From the skill directory run:\n"
        "  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(3)


# Commands the warm daemon can serve, mapped to its tool names. The daemon exists to
# avoid paying the multi-second OCP/build123d import per invocation, so the handoff has to
# happen BEFORE the command's module is imported -- which is why it lives here in dispatch
# rather than inside each command. It served only the skill launchers until now, so
# skill-shim launchers were an order of magnitude faster than the front door for no reason.
_DAEMON_TOOLS = {
    "step export": "export",
    "import": "import",
    "step inspect": "inspect",
    "step snapshot": "snapshot",
}

# Drawing packages are content-addressed and ezdxf's object ordering depends on hash
# randomization, so a DXF build has to be byte-deterministic. PYTHONHASHSEED is read
# at interpreter start; warm daemon workers always carry PYTHONHASHSEED=0, and a
# directly-run @dxf model that lands in-process re-execs through the decorator's
# daemon handoff or accepts the seed of the invoking interpreter (the runner pins
# ordering-sensitive writes itself).
_HASH_SEED_COMMANDS: set[str] = set()


# subprocess rather than os.execv, for the reason #245 hit in the dxf launcher: on Windows
# execv hands the argument VECTOR to the C runtime, which re-joins it into a command line
# without quoting, so an interpreter path containing a space -- C:\Program Files\... --
# arrives as two arguments and the child tries to run the tail as a script. subprocess
# applies Windows quoting rules, and nothing is lost on POSIX because execv never replaced
# the process on Windows anyway. argv[0] is the console script or __main__.py; either runs
# under python.
def _rerun_with_stable_hash_seed() -> int:
    """Re-run this command once with the seed pinned, and return its exit code."""
    import subprocess

    os.environ["PYTHONHASHSEED"] = "0"
    return subprocess.run([sys.executable, *sys.argv], check=False).returncode


def _run_via_daemon(tool: str, rest: list[str], prog: str) -> int | None:
    """Exit code when the daemon handled it, None to run in this process.

    CADGEN_DAEMON_CHILD is set in the process the daemon serves from, so this cannot
    recurse. A daemon that is not installed or not running just falls through.
    """
    # Warm by default; CADGEN_DAEMON=0 opts out. There are two gates on this path -- this
    # one and the client's -- and only changing the client's left the default a no-op,
    # which a live check caught rather than any test.
    if os.environ.get("CADGEN_DAEMON") == "0" or os.environ.get("CADGEN_DAEMON_CHILD"):
        return None
    try:
        from cadgen.daemon.client import run_via_daemon
    except ModuleNotFoundError:
        return None
    return run_via_daemon(tool, rest, os.getcwd(), prog=prog)


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

    # Both of these must happen before the command's module is imported.
    # The daemon first: its workers already have a stable hash seed, so a served dxf
    # build skips the re-run entirely. Only a build that will actually run in THIS
    # process needs the interpreter restart.
    daemon_tool = _DAEMON_TOOLS.get(command)
    if daemon_tool is not None:
        exit_code = _run_via_daemon(daemon_tool, rest, f"cadgen {command}")
        if exit_code is not None:
            return exit_code
    if command in _HASH_SEED_COMMANDS and os.environ.get("PYTHONHASHSEED") != "0":
        return _rerun_with_stable_hash_seed()

    module_name, _ = entry
    module = importlib.import_module(module_name)

    # Tell the parser which front door it was reached through, so `cadgen step gen --help`
    # says "cadgen step gen" — every entrypoint is a cadgen verb now.
    # Not every command has a parser to name (the daemon owns its own), hence
    # the signature check rather than a blanket keyword.
    import inspect  # only the dispatcher needs it; every skill shim imports this
                    # module just for enforce_requirements_pin and should not pay for it.

    if "prog" in inspect.signature(module.main).parameters:
        return int(module.main(rest, prog=f"cadgen {command}") or 0)
    return int(module.main(rest) or 0)

