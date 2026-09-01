"""The launcher contract: launch is unconditional (roll + keyed reuse, ``--new``
escape), explicit ``--port`` stays strict, and the stdout lines agents parse.

Ported from ``main.test.mjs``, and deliberately still SUBPROCESS tests rather
than in-process ones. The subject here IS the process: stdout flushing on a
server that never exits, the exit codes, signal shutdown, and the registry file
another process reads. Calling ``main()`` in-process would test none of that and
would silently pass the buffering bug that hangs the real launch.

Every launch redirects TMPDIR so the registry is private — the real one is
shared with the viewer the developer is using, and reuse and reaping are both
destructive. ``VIEWER_DISABLE_NATIVE_REVEAL`` is set for the same reason a
headless run must never pop a file manager.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
MAIN = APP_ROOT / "server" / "main.py"


class LauncherFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.registry_home = os.path.join(self._tmp.name, "reg")
        os.makedirs(self.registry_home)
        self._children: list[subprocess.Popen] = []
        self.addCleanup(self._teardown)

    def _teardown(self) -> None:
        for child in self._children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            for pipe in (child.stdout, child.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()
        self._tmp.cleanup()

    def env(self, **overrides) -> dict:
        env = dict(os.environ)
        env.update(
            {
                "TMPDIR": self.registry_home,
                "TEMP": self.registry_home,
                "TMP": self.registry_home,
                "VIEWER_DISABLE_NATIVE_REVEAL": "1",
                # A launch must not inherit the developer's INIT_CWD and serve
                # somewhere the test never named.
                "INIT_CWD": self._tmp.name,
            }
        )
        env.update(overrides)
        return env

    def make_dist(self) -> str:
        dist = tempfile.mkdtemp(dir=self._tmp.name, prefix="cad-dist-")
        Path(dist, "index.html").write_text("<html>viewer</html>", encoding="utf-8")
        return dist

    def make_root(self) -> str:
        return tempfile.mkdtemp(dir=self._tmp.name, prefix="cad-root-")

    def launch(self, args: list[str], **env_overrides) -> subprocess.Popen:
        child = subprocess.Popen(
            [sys.executable, str(MAIN), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env(**env_overrides),
        )
        self._children.append(child)
        return child

    def run_to_exit(self, args: list[str], timeout: float = 30.0, **env_overrides):
        child = self.launch(args, **env_overrides)
        stdout, stderr = child.communicate(timeout=timeout)
        return child.returncode, stdout, stderr

    def wait_for_url_line(self, child: subprocess.Popen, timeout: float = 30.0) -> str:
        """Read stdout until the URL line appears.

        Reading LINE BY LINE off a live process is the point: the launcher must
        flush, because Python block-buffers a non-TTY stdout and this process
        never exits to flush on close.
        """
        deadline = time.monotonic() + timeout
        lines = []
        while time.monotonic() < deadline:
            if child.poll() is not None and child.stdout.closed:
                break
            line = child.stdout.readline()
            if not line:
                if child.poll() is not None:
                    break
                continue
            lines.append(line)
            if line.startswith("{"):
                return "".join(lines)
        self.fail(f"no JSON line before timeout; got: {''.join(lines)!r} stderr={child.stderr.read()!r}")
        return ""

    @staticmethod
    def json_line(stdout: str) -> dict:
        for line in stdout.split("\n"):
            if line.startswith("{"):
                return json.loads(line)
        raise AssertionError(f"no JSON line in: {stdout!r}")


class ExplicitPort(LauncherFixture):
    def test_prints_the_url_contract_and_a_second_explicit_start_refuses(self) -> None:
        dist = self.make_dist()
        root = self.make_root()
        # Below the roll base, so it can never collide with a rolled instance.
        port = 3201
        child = self.launch(["--root", root, "--dist", dist, "--port", str(port), "--json"])
        stdout = self.wait_for_url_line(child)

        self.assertIn(f"Starting CAD Viewer at http://127.0.0.1:{port}/ (serving ", stdout)
        self.assertIn(f"CAD Viewer URL: http://127.0.0.1:{port}/", stdout)
        self.assertEqual(
            self.json_line(stdout),
            {"url": f"http://127.0.0.1:{port}/", "port": port, "action": "started"},
        )

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/__cad/server", timeout=5) as response:
            info = json.loads(response.read())
        self.assertEqual(info["app"], "cad-viewer")
        self.assertEqual(info["port"], port, "serverInfo must name the port actually bound")
        self.assertEqual(info["pid"], child.pid, "the registry probe compares this pid")

        # An explicit port is a demand: refuse when taken, never roll, never reuse.
        code, _, stderr = self.run_to_exit(["--root", root, "--dist", dist, "--port", str(port)])
        self.assertEqual(code, 1)
        self.assertRegex(stderr, r"already")

    def test_the_json_line_is_compact(self) -> None:
        # The launch smoke test greps for the literal '"action":"started"'.
        # Python's default json.dumps separators would break it.
        dist = self.make_dist()
        child = self.launch(["--root", self.make_root(), "--dist", dist, "--port", "3202", "--json"])
        stdout = self.wait_for_url_line(child)
        line = next(line for line in stdout.split("\n") if line.startswith("{"))
        self.assertIn('"action":"started"', line)
        self.assertIn('"port":3202', line)
        self.assertNotIn(", ", line)


class RollAndReuse(LauncherFixture):
    def test_default_launch_rolls_and_a_second_root_rolls_past_the_first(self) -> None:
        dist = self.make_dist()
        first = self.launch(["--root", self.make_root(), "--dist", dist, "--json"])
        a = self.json_line(self.wait_for_url_line(first))
        self.assertEqual(a["action"], "started")
        self.assertGreaterEqual(a["port"], 3245, "rolled port must be >= the base")

        # Different root, no reuse match -> its own instance on another port.
        second = self.launch(["--root", self.make_root(), "--dist", dist, "--json"])
        b = self.json_line(self.wait_for_url_line(second))
        self.assertEqual(b["action"], "started")
        self.assertNotEqual(b["port"], a["port"], "an occupied candidate is rolled past, not refused")

    def test_same_root_reuses_and_new_forces_a_fresh_instance(self) -> None:
        dist = self.make_dist()
        root = self.make_root()
        first = self.launch(["--root", root, "--dist", dist, "--json"])
        a = self.json_line(self.wait_for_url_line(first))

        # Reuse: same realpath(root) x version -> the existing URL, exit 0, no
        # spawn. Note NO --dist: the dist check happens after the reuse lookup.
        code, stdout, _ = self.run_to_exit(["--root", root, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(
            self.json_line(stdout), {"url": a["url"], "port": a["port"], "action": "reused"}
        )
        self.assertRegex(stdout, r"Reusing CAD Viewer at ")

        # Reuse must also work through a symlinked spelling of the same root.
        alias_parent = tempfile.mkdtemp(dir=self._tmp.name, prefix="cad-alias-")
        alias = os.path.join(alias_parent, "link")
        os.symlink(root, alias)
        code, stdout, _ = self.run_to_exit(["--root", alias, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(self.json_line(stdout)["action"], "reused")

        # --new bypasses the lookup and starts a second instance.
        fresh = self.launch(["--root", root, "--dist", dist, "--json", "--new"])
        c = self.json_line(self.wait_for_url_line(fresh))
        self.assertEqual(c["action"], "started")
        self.assertNotEqual(c["port"], a["port"])

    def test_a_no_registry_instance_is_never_reused(self) -> None:
        # The dev backend runs --no-registry precisely so a later real launch on
        # the same root starts fresh instead of handing back a Vite proxy target.
        dist = self.make_dist()
        root = self.make_root()
        dev = self.launch(["--root", root, "--dist", dist, "--json", "--ephemeral", "--no-registry"])
        a = self.json_line(self.wait_for_url_line(dev))
        self.assertEqual(a["action"], "started")

        code, stdout, _ = self.run_to_exit(["list", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.strip()), [], "a --no-registry instance must not be listed")

        real = self.launch(["--root", root, "--dist", dist, "--json"])
        b = self.json_line(self.wait_for_url_line(real))
        self.assertEqual(b["action"], "started", "must start fresh, not reuse the dev backend")
        self.assertNotEqual(b["port"], a["port"])

    def test_ephemeral_binds_a_free_port_and_reports_it(self) -> None:
        # --ephemeral exists because `--port 0` means STRICT 3245 (Number(0) is
        # falsy but still sets portExplicit), so it could not be overloaded.
        dist = self.make_dist()
        child = self.launch(["--root", self.make_root(), "--dist", dist, "--json", "--ephemeral"])
        payload = self.json_line(self.wait_for_url_line(child))
        self.assertGreater(payload["port"], 0)
        self.assertIn(f":{payload['port']}/", payload["url"])
        with urllib.request.urlopen(f"http://127.0.0.1:{payload['port']}/__cad/server", timeout=5) as r:
            self.assertEqual(json.loads(r.read())["port"], payload["port"])


class Refusals(LauncherFixture):
    def test_a_missing_root_refuses_before_binding(self) -> None:
        dist = self.make_dist()
        code, _, stderr = self.run_to_exit(
            ["--root", "/nonexistent-root-xyz", "--dist", dist, "--port", "3999"]
        )
        self.assertEqual(code, 1)
        self.assertRegex(stderr, r"root is not a directory")

    def test_dist_resolution_falls_back_and_then_gives_up(self) -> None:
        # Tested at the function rather than through a launch, because the
        # fallback candidate is the app's own dist/ — present in a checkout
        # after a build, so a subprocess could not reach the refusal.
        if str(APP_ROOT) not in sys.path:
            sys.path.insert(0, str(APP_ROOT))
        from server import main as main_module

        dist = self.make_dist()
        self.assertEqual(main_module.resolve_dist_dir(dist), os.path.abspath(dist))
        empty = self.make_root()  # a directory with no index.html
        self.assertEqual(
            main_module.resolve_dist_dir(empty),
            os.path.abspath(os.path.join(main_module.VIEWER_ROOT, "dist"))
            if os.path.exists(os.path.join(main_module.VIEWER_ROOT, "dist", "index.html"))
            else "",
            "an explicit --dist without index.html falls through to the app's own dist",
        )


class ListAndStop(LauncherFixture):
    def test_list_reports_a_running_instance_and_stop_terminates_it(self) -> None:
        dist = self.make_dist()
        root = self.make_root()
        child = self.launch(["--root", root, "--dist", dist, "--json"])
        started = self.json_line(self.wait_for_url_line(child))
        port = started["port"]

        code, stdout, _ = self.run_to_exit(["list"])
        self.assertEqual(code, 0)
        self.assertIn("1 CAD Viewer running:", stdout)
        # The launch smoke test greps for this exact two-space-separated token.
        self.assertIn(f"port {port}", stdout)
        self.assertIn(f"serving  {root}", stdout)

        code, stdout, _ = self.run_to_exit(["list", "--json"])
        entries = json.loads(stdout.strip())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["port"], port)
        self.assertEqual(entries[0]["pid"], child.pid)

        code, stdout, _ = self.run_to_exit(["stop", "--port", str(port)])
        self.assertEqual(code, 0)
        self.assertIn("Stopped CAD Viewer", stdout)
        self.assertIsNotNone(child.poll(), "the server process must have exited")

        code, stdout, _ = self.run_to_exit(["list"])
        self.assertIn("No CAD Viewer is running.", stdout)

    def test_stop_without_a_selector_exits_2(self) -> None:
        code, _, stderr = self.run_to_exit(["stop"])
        self.assertEqual(code, 2)
        self.assertIn("Specify which viewer to stop", stderr)

    def test_stop_for_an_unknown_port_exits_1(self) -> None:
        code, _, stderr = self.run_to_exit(["stop", "--port", "3987"])
        self.assertEqual(code, 1)
        self.assertIn("No running CAD Viewer for port 3987.", stderr)

    def test_list_with_no_instances(self) -> None:
        code, stdout, _ = self.run_to_exit(["list"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "No CAD Viewer is running.\n")


class ArgumentGrammar(unittest.TestCase):
    """The parse rules, in-process — no launch needed to pin argument handling."""

    @classmethod
    def setUpClass(cls) -> None:
        if str(APP_ROOT) not in sys.path:
            sys.path.insert(0, str(APP_ROOT))
        from server import main as main_module

        cls.parse_args = staticmethod(main_module.parse_args)
        cls.main_module = main_module

    def test_unknown_arguments_are_tolerated(self) -> None:
        # This is why the launcher cannot use argparse: argparse errors here.
        args = self.parse_args(["--root", "/x", "--totally-unknown", "value", "--json"])
        self.assertEqual(args["root"], "/x")
        self.assertTrue(args["json"])

    def test_port_zero_and_garbage_both_mean_strict_default(self) -> None:
        # `Number(x) || default` keeps the default while still setting
        # portExplicit. Asymmetric and unpinned by any client, but reproducing
        # it exactly costs two lines and diverging costs a silent behaviour
        # change. --ephemeral is the spelling for "any free port".
        for value in ("0", "abc", ""):
            args = self.parse_args(["--port", value])
            self.assertEqual(args["port"], 3245, value)
            self.assertTrue(args["port_explicit"], value)

    def test_an_out_of_range_port_falls_back_to_the_non_strict_default(self) -> None:
        for value in ("70000", "-1"):
            args = self.parse_args(["--port", value])
            self.assertEqual(args["port"], 3245, value)
            self.assertFalse(args["port_explicit"], value)

    def test_a_valueless_trailing_port_does_not_crash(self) -> None:
        args = self.parse_args(["--port"])
        self.assertEqual(args["port"], 3245)
        self.assertTrue(args["port_explicit"])

    def test_repeated_flags_take_the_last_value(self) -> None:
        self.assertEqual(self.parse_args(["--root", "/a", "--root", "/b"])["root"], "/b")

    def test_explicit_root_is_taken_verbatim_even_inside_the_viewer_app(self) -> None:
        # The viewer-app refusal is a footgun guard on the CWD fallback, never a
        # boundary: an explicit --root is accepted without complaint.
        resolved = self.main_module.resolve_directory_root(root=str(APP_ROOT))
        self.assertEqual(resolved, str(APP_ROOT))

    def test_the_cwd_fallback_refuses_the_viewer_app_itself(self) -> None:
        resolved = self.main_module.resolve_directory_root(
            root="", env={"INIT_CWD": str(APP_ROOT)}, cwd=str(APP_ROOT.parent)
        )
        self.assertNotEqual(resolved, str(APP_ROOT))


if __name__ == "__main__":
    unittest.main()
