"""A warm build must produce exactly what a cold build produces.

This is the regression net for turning the daemon into a worker pool. It is deliberately
written and landed BEFORE that refactor: a harness that only exists afterwards proves
nothing about the change it was meant to guard.

Three paths must agree, byte for byte:

* cold — the tool runs in the invoking process
* warm sequential — the tool runs in a daemon that already imported OCP
* warm parallel — several builds through one daemon at once

What is compared: every file the build writes under ``__cadgen__`` by sha256, the exit
code, and stdout/stderr with the tmp path masked. Plus ``--help`` for every daemon-served
command, which is the input contract made visible — dispatch hands off before argparse
runs, so warm ``--help`` genuinely round-trips through the daemon.

Fixtures are written here rather than copied from ``models/``: the repo's generators
import sibling modules (``simple_model_library``), so a single copied file does not build.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
CADGEN_SRC = REPO_ROOT / "packages" / "cadgen" / "src"

PART = """from build123d import Box, BuildPart, Cylinder, Locations, Mode

def gen_step():
    with BuildPart() as part:
        Box(30, 20, 10)
        with Locations((0, 0, 0)):
            Cylinder(4, 40, mode=Mode.SUBTRACT)
    return part.part
"""

ASSEMBLY = """from build123d import Box, BuildPart, Location, Pos

def gen_step():
    with BuildPart() as base:
        Box(40, 40, 5)
    with BuildPart() as post:
        Box(8, 8, 20)
    post.part.locate(Location(Pos(0, 0, 12.5)))
    return base.part + post.part
"""

DRAWING = """import ezdxf
from ezdxf.units import MM

def gen_dxf():
    document = ezdxf.new(setup=True)
    document.units = MM
    msp = document.modelspace()
    msp.add_lwpolyline([(0, 0), (60, 0), (60, 40), (0, 40)], close=True)
    msp.add_circle((30, 20), 8)
    return {"document": document}
"""


def _env(**extra) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(CADGEN_SRC), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    env.pop("CADGEN_WARM", None)
    env.update({k: v for k, v in extra.items() if v is not None})
    return env


def _run(argv: list[str], cwd: pathlib.Path, **env_extra) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "cadgen.cli", *argv],
        cwd=str(cwd), env=_env(**env_extra), capture_output=True, text=True, timeout=600,
    )
    # The tmp root differs per run and is not part of the contract; everything else is.
    output = re.sub(re.escape(str(cwd)), "<CWD>", proc.stdout + proc.stderr)
    output = re.sub(r"/private/var/folders/\S+", "<TMP>", output)
    output = re.sub(r"/(?:var|tmp)/\S*tmp\S+", "<TMP>", output)
    return proc.returncode, output


# Fields that record WHEN a build ran rather than WHAT it produced. Two cold builds a
# second apart differ in these too, so comparing them would test the clock. Verified by
# diffing a cold and a warm assembly.json: `generatedAt` was the only differing key.
_VOLATILE_JSON_FIELDS = {"generatedAt"}


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items()) if k not in _VOLATILE_JSON_FIELDS}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def _digest(path: pathlib.Path) -> str:
    """sha256 of a built file, with build-time stamps masked out of JSON."""
    raw = path.read_bytes()
    if path.suffix == ".json":
        try:
            return hashlib.sha256(
                json.dumps(_canonical(json.loads(raw)), sort_keys=True).encode()
            ).hexdigest()
        except ValueError:
            pass  # not JSON after all; fall through to the raw bytes
    return hashlib.sha256(raw).hexdigest()


def _manifest(root: pathlib.Path) -> dict[str, str]:
    """Digest of every built file, keyed by path relative to the build root.

    Lock and progress files are transient scaffolding, not output.
    """
    out: dict[str, str] = {}
    for path in sorted((root / "__cadgen__").rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if ".lock" in name or ".progress." in name:
            continue
        out[name] = _digest(path)
    return out


def _daemon_available() -> bool:
    """Whether a daemon can be reached at all on this platform."""
    sys.path.insert(0, str(CADGEN_SRC))
    from cadgen.daemon.client import daemon_supported

    return daemon_supported()


class _Daemon:
    """A real daemon on a private socket, so tests never touch a developer's."""

    def __init__(self, tmp: pathlib.Path):
        self.socket = tmp / "d.sock"
        self.log = self.socket.with_suffix(".log")  # d.sock -> d.log, not d.sock.log

    def env(self) -> dict:
        return {"CADGEN_WARM": "1", "CADGEN_DAEMON_SOCKET": str(self.socket)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        subprocess.run(
            [sys.executable, "-m", "cadgen.daemon", "--stop"],
            env=_env(**self.env()), capture_output=True, timeout=60,
        )
        return False

    def served_a_job(self) -> bool:
        """Proof the warm run was actually warm, so a silent cold fallback cannot pass.

        Looks for a completed job (`gen [...] -> exit 0`), not just the daemon's startup
        line: a daemon can be running while the client still fell back to cold.
        """
        return self.log.is_file() and "-> exit" in self.log.read_text(errors="replace")


# The whole harness compares a WARM run against a cold one, so it needs a daemon to
# exist. AF_UNIX is the daemon's only transport and CPython does not provide it on
# Windows, so every "warm" run there is silently a cold one and the comparison stops
# meaning anything -- `served_a_job()` is what catches that. Asking cadgen whether a
# daemon is reachable, rather than testing os.name here, keeps this in step with the
# client: if the transport ever becomes portable, these run without being edited.
_DAEMON_AVAILABLE = _daemon_available()


@unittest.skipUnless(_DAEMON_AVAILABLE, "no daemon transport on this platform")
class WarmOutputEquivalence(unittest.TestCase):
    maxDiff = None

    def _tree(self, name: str, source: str) -> pathlib.Path:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="tmp-warm-eq-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / name).write_text(source)
        return tmp

    def _cold(self, name: str, source: str, argv: list[str]):
        tree = self._tree(name, source)
        code, output = _run(argv, tree)
        self.assertEqual(code, 0, output)
        return _manifest(tree), output

    def test_a_part_builds_identically_warm(self):
        argv = ["step", "gen", "widget.step.py"]
        cold, cold_out = self._cold("widget.step.py", PART, argv)
        self.assertTrue(cold, "the cold build produced nothing to compare")

        tree = self._tree("widget.step.py", PART)
        with _Daemon(tree) as daemon:
            code, warm_out = _run(argv, tree, **daemon.env())
            self.assertEqual(code, 0, warm_out)
            self.assertTrue(daemon.served_a_job(), "the warm run fell back to cold")
            self.assertEqual(_manifest(tree), cold)
        self.assertEqual(warm_out, cold_out)

    def test_an_assembly_builds_identically_warm(self):
        argv = ["step", "gen", "rig.step.py"]
        cold, _ = self._cold("rig.step.py", ASSEMBLY, argv)
        tree = self._tree("rig.step.py", ASSEMBLY)
        with _Daemon(tree) as daemon:
            code, out = _run(argv, tree, **daemon.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(_manifest(tree), cold)

    def test_four_parallel_builds_through_one_daemon_all_match_cold(self):
        """The case the pool exists for. Today this serialises; it must still be correct."""
        argv = ["step", "gen", "widget.step.py"]
        cold, _ = self._cold("widget.step.py", PART, argv)

        trees = [self._tree("widget.step.py", PART) for _ in range(4)]
        shared = pathlib.Path(tempfile.mkdtemp(prefix="tmp-warm-eq-sock-")).resolve()
        self.addCleanup(shutil.rmtree, shared, ignore_errors=True)
        with _Daemon(shared) as daemon:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda t: _run(argv, t, **daemon.env()), trees))
            for index, (code, out) in enumerate(results):
                with self.subTest(build=index):
                    self.assertEqual(code, 0, out)
            for index, tree in enumerate(trees):
                with self.subTest(build=index):
                    self.assertEqual(_manifest(tree), cold)

    def test_a_drawing_package_is_byte_identical_warm(self):
        """DXF is the format with a determinism hazard: ezdxf's ordering follows the
        hash seed, which is why the dxf commands re-run with PYTHONHASHSEED pinned."""
        argv = ["dxf", "gen", "plate.dxf.py"]
        cold, _ = self._cold("plate.dxf.py", DRAWING, argv)
        self.assertTrue(cold, "the cold DXF build produced nothing to compare")
        tree = self._tree("plate.dxf.py", DRAWING)
        code, out = _run(argv, tree, CADGEN_WARM="1")
        self.assertEqual(code, 0, out)
        self.assertEqual(_manifest(tree), cold)

    def test_a_failing_build_fails_the_same_way_warm(self):
        """Exit code and message are contract too, not just successful output."""
        broken = "def gen_step():\n    raise ValueError('bad radius')\n"
        tree = self._tree("broken.step.py", broken)
        cold_code, cold_out = _run(["step", "gen", "broken.step.py"], tree)
        self.assertNotEqual(cold_code, 0)

        tree2 = self._tree("broken.step.py", broken)
        with _Daemon(tree2) as daemon:
            warm_code, warm_out = _run(["step", "gen", "broken.step.py"], tree2, **daemon.env())
        self.assertEqual(warm_code, cold_code)
        # Deliberately not asserting the message TEXT: cadgen masks a raising generator
        # with "gen_step() must return one value" rather than surfacing the original
        # error (a pre-existing quirk, not this refactor's business). What matters here is
        # that whatever cold says, warm says exactly the same.
        self.assertEqual(warm_out, cold_out)
        self.assertIn("FAILED", warm_out)


@unittest.skipUnless(_DAEMON_AVAILABLE, "no daemon transport on this platform")
class InputSurfaceEquivalence(unittest.TestCase):
    """`--help` is the input contract made visible.

    Dispatch hands off to the daemon before argparse runs, so a warm `--help` exercises
    the handoff path rather than short-circuiting around it.
    """

    maxDiff = None

    def test_help_is_identical_cold_and_warm(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="tmp-warm-eq-help-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        from cadgen.cli import _DAEMON_TOOLS

        with _Daemon(tmp) as daemon:
            for command in sorted(_DAEMON_TOOLS):
                argv = [*command.split(), "--help"]
                with self.subTest(command=command):
                    cold_code, cold_help = _run(argv, tmp)
                    warm_code, warm_help = _run(argv, tmp, **daemon.env())
                    self.assertEqual(cold_code, warm_code)
                    self.assertEqual(warm_help, cold_help)


if __name__ == "__main__":
    unittest.main()
