"""Byte-for-byte: the Python catalog against the Node catalog it replaces.

Every other test in this directory asserts something a human decided the
scanner should do. This one asserts the only thing that actually matters during
the port — that the JSON body on the wire is UNCHANGED — and it is the single
strongest checkpoint available, because it compares implementations rather than
comparing an implementation against an opinion.

It is deliberately self-disabling. Once ``server/scanner.mjs`` is deleted at the
end of the port there is nothing left to compare against, and this file skips
instead of failing. Until then it must stay green: a diff here is a client-
visible regression, whatever the other suites say.

The fixture reaches the branches a real corpus does not: descriptors that are
directories, arrays, or the wrong kind; sidecars that are arrays, empty
objects, explicit nulls or malformed; SRDF pairing that is ambiguous,
cross-directory or hidden; symlinks that loop, dangle, alias and escape; the
depth cap; and a sort corpus of punctuation, case, accents, expansions,
fullwidth digits and an astral character.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = APP_ROOT / "server"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from server.backend import LocalAssetBackend  # noqa: E402
from server.scanner import scan_cad_directory  # noqa: E402
from server.store_paths import CACHE_SCHEMA_VERSION, store_packages_dir  # noqa: E402

_JS_DUMPER = """
import path from "node:path";
import { pathToFileURL } from "node:url";
const dir = process.env.VIEWER_SERVER_DIR;
const load = (name) => import(pathToFileURL(path.join(dir, name)).href);
const [root, mode] = process.argv.slice(2);
if (mode === "raw") {
  const { scanCadDirectory } = await load("scanner.mjs");
  process.stdout.write(JSON.stringify(scanCadDirectory(root)));
} else {
  const { LocalAssetBackend } = await load("backend.mjs");
  process.stdout.write(JSON.stringify(new LocalAssetBackend(root).readCatalog()));
}
"""


def _node_is_available() -> bool:
    if not (SERVER_DIR / "scanner.mjs").is_file():
        return False
    try:
        return (
            subprocess.run(["node", "--version"], capture_output=True, check=False).returncode == 0
        )
    except (OSError, ValueError):
        return False


def _build_fixture(root: str, cache: str) -> None:
    os.makedirs(os.path.join(cache, "packages"), exist_ok=True)
    os.environ["CADGEN_CACHE_DIR"] = cache

    def write(rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if isinstance(text, bytes):
            Path(path).write_bytes(text)
        else:
            Path(path).write_text(text, encoding="utf-8")
        return path

    def package(rel, descriptor, *, raw=None, as_dir=False):
        digest = hashlib.sha256(Path(root, rel).read_bytes()).hexdigest()
        package_dir = os.path.join(store_packages_dir(), f"{digest}-v{CACHE_SCHEMA_VERSION}")
        os.makedirs(package_dir, exist_ok=True)
        Path(package_dir, "c0.surf").write_bytes(b"SURF\x00")
        target = os.path.join(package_dir, "assembly.json")
        if as_dir:
            os.makedirs(target, exist_ok=True)
            return
        Path(target).write_text(
            raw if raw is not None else json.dumps(descriptor, separators=(",", ":")),
            encoding="utf-8",
        )

    valid = {"kind": "assembly-package", "components": {"c0": {"surf": "c0.surf"}}}

    # --- descriptor variants ---------------------------------------------
    write("a_part.step", "part\n")
    package("a_part.step", valid)
    write("b_assembly.step", "assembly\n")
    package("b_assembly.step", {"kind": "assembly-package", "entryKind": "  ASSEMBLY  "})
    write("c_root.step", "root\n")
    package("c_root.step", {"kind": "assembly-package", "assembly": {"root": {"x": 1}}})
    write("d_root_string.step", "rootstr\n")
    package("d_root_string.step", {"kind": "assembly-package", "assembly": {"root": "x"}})
    write("l_dir_descriptor.step", "dird\n")
    package("l_dir_descriptor.step", None, as_dir=True)
    write("m_bad_descriptor.step", "badd\n")
    package("m_bad_descriptor.step", None, raw="{ nope")
    write("n_array_descriptor.step", "arrd\n")
    package("n_array_descriptor.step", None, raw="[1,2,3]")
    write("o_no_package.step", "nopkg\n")

    # --- sidecar variants -------------------------------------------------
    for name, sidecar in (
        ("e_kin", json.dumps({"schemaVersion": 5, "kinematics": {"joints": []}})),
        ("f_anim", json.dumps({"animation": {"text": "x"}})),
        ("g_array", "[1,2]"),
        ("h_empty_kin", json.dumps({"kinematics": {}})),
        ("i_nulls", json.dumps({"kinematics": None, "animation": None})),
        ("j_bad", "{ not json"),
        ("q_scalar", '"hello"'),
    ):
        write(f"{name}.step", f"{name}\n")
        write(f"{name}.step.json", sidecar)
        package(f"{name}.step", valid)
    # A sidecar with a WRONG descriptor kind publishes neither url.
    write("k_wrong_kind.step", "wrong\n")
    write("k_wrong_kind.step.json", json.dumps({"kinematics": {"a": 1}}))
    package("k_wrong_kind.step", {"kind": "not-a-package"})
    # Uppercase suffix: the sidecar name follows the artifact's whole name.
    write("p_upper.STP", "upper\n")
    write("p_upper.STP.json", json.dumps({"kinematics": {"j": 1}}))
    package("p_upper.STP", valid)

    # --- non-STEP assets and non-entries ---------------------------------
    for name, body in (
        ("mesh.stl", "solid x\nendsolid x\n"),
        ("empty.stl", ""),
        ("model.3mf", "3mf"),
        ("scene.glb", "glTF"),
        ("outline.dxf", "0\nSECTION\n"),
        ("world.sdf", "<sdf/>"),
        ("gyroid.implicit.js", "export default 1;"),
        ("loose.params.js", "export default 2;"),
        ("model.py", "print(1)"),
        ("secrets.json", '{"token":"x"}'),
    ):
        write(name, body)

    # --- URDF / SRDF pairing ---------------------------------------------
    write("robots/arm.urdf", '<?xml version="1.0"?><robot name="arm"><link name="l"/></robot>')
    write("robots/other.urdf", '<robot name="other"/>')
    write("robots/arm.srdf", '<?xml version="1.0"?><!-- c --><!DOCTYPE robot><robot name="arm"/>')
    write("ambig/one.urdf", '<robot name="dup"/>')
    write("ambig/two.urdf", '<robot name="dup"/>')
    write("ambig/dup.srdf", '<robot name="dup"/>')
    write("noname/x.urdf", "<robot/>")
    write("noname/x.srdf", "<robot/>")
    write("hiddenurdf/.arm.urdf", '<robot name="hid"/>')
    write("hiddenurdf/hid.srdf", '<robot name="hid"/>')
    write("split/deep/far.urdf", '<robot name="far"/>')
    write("split/far.srdf", '<robot name="far"/>')
    write("quoted/q.urdf", "<robot  name = 'q'  version=\"1\" />")
    write("quoted/q.srdf", "<robot name='q'/>")
    write("mojibake/m.urdf", b'<robot name="m\xff\xfe"/>')
    write("mojibake/m.srdf", b'<robot name="m\xff\xfe"/>')
    write("bom/b.urdf", "﻿<robot name=\"b\"/>")
    write("bom/b.srdf", "﻿<robot name=\"b\"/>")

    # --- collation and URL-encoding stress -------------------------------
    for name in (
        "_x.step", "001.stl", "1.stl", "2 x.stl", "2x.stl", "9.stl", "10.stl", "12.stl",
        "A.stl", "à.stl", "B.stl", "e.stl", "é.stl", "ünicode.stl",
        "v2.9.stl", "v2.10.stl", "v10.1.stl", "x_1.stl", "x-1.stl", "Z.stl",
        "가.stl", "日本語.stl", "a b(c)*d~e._-!'.stl",
        "1­2.stl", "ß.stl", "Ⅻ.stl", "Ａ.stl", "１.stl",
        "\U0001f642.stl",
    ):
        write(os.path.join("sortcases", name), f"content of {name}\n")

    # --- walk rules -------------------------------------------------------
    for skipped in ("dist", "build", "node_modules", "__pycache__", "coverage", "viewer", "__cadgen__"):
        write(os.path.join(skipped, "x.stl"), "skipped")
    write("Kept/kept.stl", "kept")
    write(".dotfile.step", "hidden")
    write(".hidden/secret.step", "hidden dir")
    write("sub/.git/config.stl", "git")

    # --- symlinks ---------------------------------------------------------
    base = os.path.dirname(root)
    os.makedirs(os.path.join(base, "library_real"))
    Path(base, "library_real", "part.step").write_text("lib\n", encoding="utf-8")
    os.symlink(os.path.join(base, "library_real"), os.path.join(root, "library"))
    write("looproot/model.stl", "loop model")
    os.symlink(".", os.path.join(root, "looproot", "loop"))
    os.symlink(os.path.join(base, "nonexistent.stl"), os.path.join(root, "dangling.stl"))
    os.makedirs(os.path.join(base, "outside"))
    Path(base, "outside", "secret.step").write_text("outside\n", encoding="utf-8")
    os.symlink(os.path.join(base, "outside", "secret.step"), os.path.join(root, "escape.step"))
    os.makedirs(os.path.join(root, "aliased", "real"))
    write("aliased/real/part.stl", "aliased")
    os.symlink(os.path.join(root, "aliased", "real"), os.path.join(root, "aliased", "Alink"))
    os.symlink(os.path.join(root, "aliased", "real"), os.path.join(root, "aliased", "zlink"))

    # --- depth cap --------------------------------------------------------
    current = os.path.join(root, "deep")
    for level in range(70):
        current = os.path.join(current, f"d{level}")
        os.makedirs(current)
        Path(current, f"f{level}.stl").write_text(f"level {level}\n", encoding="utf-8")


@unittest.skipUnless(
    _node_is_available(),
    "no node, or server/scanner.mjs is gone — the JS half of the port has been deleted",
)
class ByteForByteAgainstNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "root")
        cls.cache = os.path.join(cls.tmp, "cache")
        os.makedirs(cls.root)
        cls._previous_cache = os.environ.get("CADGEN_CACHE_DIR")
        _build_fixture(cls.root, cls.cache)
        cls.dumper = os.path.join(cls.tmp, "dump.mjs")
        Path(cls.dumper).write_text(_JS_DUMPER, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        if cls._previous_cache is None:
            os.environ.pop("CADGEN_CACHE_DIR", None)
        else:
            os.environ["CADGEN_CACHE_DIR"] = cls._previous_cache
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _node_json(self, mode: str) -> bytes:
        env = dict(os.environ)
        env["VIEWER_SERVER_DIR"] = str(SERVER_DIR)
        completed = subprocess.run(
            ["node", self.dumper, self.root, mode],
            capture_output=True,
            check=True,
            env=env,
        )
        return completed.stdout

    @staticmethod
    def _python_json(payload) -> bytes:
        # JSON.stringify's exact bytes: compact separators, no \\u escaping.
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _assert_identical(self, node_bytes: bytes, python_bytes: bytes) -> None:
        if node_bytes == python_bytes:
            return
        node = json.loads(node_bytes)
        python = json.loads(python_bytes)
        node_files = [e.get("file") for e in node["entries"]]
        python_files = [e.get("file") for e in python["entries"]]
        if node_files != python_files:
            self.fail(
                "entry ORDER or membership differs:\n"
                f"  only in node:   {sorted(set(node_files) - set(python_files))}\n"
                f"  only in python: {sorted(set(python_files) - set(node_files))}\n"
                f"  node order:   {node_files}\n"
                f"  python order: {python_files}"
            )
        for left, right in zip(node["entries"], python["entries"]):
            if left != right:
                self.fail(f"entry {left.get('file')!r} differs:\n  node:   {left}\n  python: {right}")
        self.fail("payloads differ outside the entry list (schemaVersion or key order)")

    def test_the_raw_catalog_is_identical(self):
        self._assert_identical(
            self._node_json("raw"), self._python_json(scan_cad_directory(self.root))
        )

    def test_the_absolutized_catalog_is_identical(self):
        self._assert_identical(
            self._node_json("abs"),
            self._python_json(LocalAssetBackend(self.root).read_catalog()),
        )

    def test_the_fixture_actually_reaches_the_interesting_branches(self):
        # A parity test over a tree that exercises nothing passes vacuously.
        entries = scan_cad_directory(self.root)["entries"]
        self.assertGreater(len(entries), 100)
        self.assertGreaterEqual(sum(1 for e in entries if e["kind"] == "assembly"), 2)
        self.assertGreaterEqual(sum(1 for e in entries if "poseUrl" in e), 4)
        self.assertGreaterEqual(sum(1 for e in entries if "sourceUrl" in e), 6)
        self.assertGreaterEqual(sum(1 for e in entries if "relations" in e), 4)
        self.assertGreaterEqual(sum(1 for e in entries if e["hash"] == ""), 4)
        self.assertTrue(any(e["file"].startswith("library/") for e in entries))
        self.assertTrue(any(e["file"].startswith("deep/") for e in entries))


if __name__ == "__main__":
    unittest.main()
