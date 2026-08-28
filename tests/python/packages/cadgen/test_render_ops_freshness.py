"""render_ops: ownership, format dispatch, and the kernel lock snapshot.

Freshness VERDICTS moved to the single JS authority
(viewer/server/artifactStatus.mjs, tested in artifactStatus.test.mjs); what
remains here is what Python still owns: which entries are artifact-managed,
which producer builds each format, and the flock-backed generation snapshot
(idle/writing/busy) that no other runtime can probe.
"""

import ast
import inspect
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from cadgen.coordination import lock as lock_mod  # noqa: E402
from cadgen import render_ops as artifact  # noqa: E402

from cadgen._internal.dxf_output import record_dxf_output  # noqa: E402
from cadgen._internal import implicit_package as _implicit_package  # noqa: E402
from cadgen._internal.implicit_package import (  # noqa: E402
    IMPLICIT_PACKAGE_SCHEMA_VERSION,
    implicit_bake_settings,
)
from cadgen._internal.package_freshness import (  # noqa: E402
    STEP_PACKAGE_VERSION as _STEP_SCHEMA_VERSION,
    canonical_bake_hash,
)
from cadgen._internal.source_hash import closure_for_files  # noqa: E402


def _dump(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _closure_for(source, base):
    return closure_for_files(pathlib.Path(source), [pathlib.Path(source)], base=pathlib.Path(base))

_IMPLICIT_SCHEMA_VERSION = IMPLICIT_PACKAGE_SCHEMA_VERSION

# Sentinel for "write no such key at all", distinct from "write an empty one".
_OMIT = object()


def _write_package(
    root,
    step_name,
    *,
    source_kind="step",
    step_hash=None,
    components=None,
    schema_version=_STEP_SCHEMA_VERSION,
    bake_hash=None,
):
    """Create <root>/<step_name> + its __cadgen__/models/<step_name> package."""
    step_path = os.path.join(root, step_name)
    with open(step_path, "wb") as h:
        h.write(b"ISO-10303-21;\nfake step\n")
    with open(step_path, "rb") as h:
        actual_hash = hashlib.sha256(h.read()).hexdigest()
    pkg = os.path.join(root, "__cadgen__", "models", step_name)
    comp_dir = os.path.join(pkg, "components")
    os.makedirs(comp_dir, exist_ok=True)
    comps = {}
    for cid in (components if components is not None else ["c0"]):
        rel = f"components/{cid}.surf"
        with open(os.path.join(pkg, rel), "wb") as h:
            h.write(b"glTF\x02\x00\x00\x00")
        comps[cid] = {"surf": rel}
    descriptor = {
        "kind": "assembly-package",
        "sourceKind": source_kind,
        "components": comps,
    }
    if schema_version is not None:
        descriptor["packageSchemaVersion"] = schema_version
    if step_hash is not _OMIT:
        descriptor["stepHash"] = step_hash if step_hash is not None else actual_hash
    if bake_hash is not None:
        descriptor["bakeHash"] = bake_hash
    with open(os.path.join(pkg, "assembly.json"), "w") as h:
        json.dump(descriptor, h)
    return step_path, pkg


class OwnsEntry(unittest.TestCase):
    def test_step_and_generated_step_py_are_owned(self):
        self.assertTrue(artifact.owns_entry({"file": "/x/a.step"}))
        self.assertTrue(artifact.owns_entry({"file": "/x/a.STP"}))
        # Generated models are owned too — they get the needs-build/build flow so a
        # not-yet-built .step.py is listed and built on demand.
        self.assertTrue(artifact.owns_entry({"file": "/x/a.step.py"}))
        self.assertTrue(artifact.owns_entry({"file": "/x/a.STP.py"}))
        self.assertFalse(artifact.owns_entry({"file": "/x/a.stl"}))
        self.assertFalse(artifact.owns_entry({"file": "/x/lib.py"}))  # plain .py is not a model
        self.assertFalse(artifact.owns_entry(None))


@unittest.skipUnless(
    lock_mod.locking_available(),
    "no kernel locking backend here, so there is no state for the snapshot to report",
)
class GenerationLock(unittest.TestCase):
    """The snapshot reports what the kernel says. There is no pid, heartbeat, or age to
    fake, so these drive REAL lock states — including from a separate process, which is
    the case that actually matters.

    Held through coordination.lock rather than raw fcntl. The lock has two backends and
    the snapshot is supposed to read either; calling flock directly meant this whole class
    skipped on Windows, leaving the msvcrt backend's contribution to the viewer's "is a
    build running" answer untested on the only platform where it is used.
    """

    def _lock_for(self, package_dir):
        from cadgen.coordination.paths import write_lock_path

        return str(write_lock_path(package_dir))

    def test_unheld_lock_is_idle(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            open(self._lock_for(pkg), "wb").close()
            self.assertEqual("idle", artifact.generation_snapshot(pkg).state)

    def test_never_built_artifact_is_idle(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                "idle", artifact.generation_snapshot(os.path.join(d, "never-built.step")).state
            )

    def test_reading_status_does_not_create_the_sentinel(self):
        """The old probe opened the sentinel "a+b", so merely asking for status
        materialised a lock file for an artifact that had never been built."""
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            artifact.generation_snapshot(pkg)
            self.assertFalse(os.path.exists(self._lock_for(pkg)))

    def test_empty_path_is_idle(self):
        self.assertEqual("idle", artifact.generation_snapshot("").state)

    def test_held_lock_reads_as_writing(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            with lock_mod.exclusive(self._lock_for(pkg)):
                self.assertEqual("writing", artifact.generation_snapshot(pkg).state)
            self.assertEqual("idle", artifact.generation_snapshot(pkg).state)

    def test_concurrent_readers_do_not_see_a_phantom_build(self):
        """flock conflicts per open file description, so the previous LOCK_EX probe
        conflicted with OTHER PROBES: two status reads racing over an idle, fresh model
        made one of them report a build in flight (~6% with four threads)."""
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            open(self._lock_for(pkg), "wb").close()
            seen = []
            guard = threading.Lock()

            def worker():
                hits = sum(
                    1 for _ in range(1500) if artifact.generation_snapshot(pkg).state != "idle"
                )
                with guard:
                    seen.append(hits)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(0, sum(seen))

    def test_lock_held_by_another_process_is_writing(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            lp = self._lock_for(pkg)
            ready = os.path.join(d, "ready")
            # Holds it the way a real builder does, so this exercises whichever backend
            # the platform actually ships rather than a POSIX-only call.
            code = (
                "import time\n"
                "from cadgen.coordination import lock\n"
                f"with lock.exclusive({lp!r}):\n"
                f"    open({ready!r},'wb').close()\n"
                "    time.sleep(30)\n"
            )
            proc = subprocess.Popen([sys.executable, "-c", code])
            try:
                for _ in range(200):
                    if os.path.exists(ready):
                        break
                    time.sleep(0.02)
                self.assertTrue(os.path.exists(ready), "helper never acquired the lock")
                self.assertEqual("writing", artifact.generation_snapshot(pkg).state)
                # SIGKILL: no unwind, no cleanup handler. The kernel must still release.
                proc.kill()
                proc.wait(timeout=10)
                for _ in range(200):
                    if artifact.generation_snapshot(pkg).state == "idle":
                        break
                    time.sleep(0.02)
                self.assertEqual(
                    "idle",
                    artifact.generation_snapshot(pkg).state,
                    "a killed builder must leave no stale lock",
                )
            finally:
                if proc.poll() is None:
                    proc.kill()

    def test_a_dead_runs_record_is_not_shown_as_live_progress(self):
        """A SIGKILLed build leaves a non-terminal record on disk forever. Attributing it
        to whoever holds the lock NEXT is what made the viewer render "Meshing components
        31/50" for a run that had meshed nothing, then jump backwards."""
        from cadgen.coordination import record as record_mod
        from cadgen.coordination.paths import status_path

        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "x.step")
            record_mod.write_record(
                status_path(pkg),
                record_mod.build_record(
                    run_id="deadbeef",
                    kind="step-package",
                    intent="write",
                    started_at_ms=0.0,
                    outcome=None,
                    progress={"phase": "components", "done": 31, "total": 50, "ratio": 0.77},
                ),
            )
            with lock_mod.exclusive(self._lock_for(pkg)):
                snap = artifact.generation_snapshot(pkg)
            self.assertEqual("writing", snap.state)
            self.assertIsNone(snap.progress)


def _reference_closure_hash(root, relative_files):
    """Independent re-derivation of the closure digest cadgen records.

    Deliberately NOT calling cadgen source_hash helpers: a fixture built by the module
    under test could not catch a bug in that module's digest construction. Parity
    with the real cadgen implementation is pinned separately in
    tests/python/global/test_viewer_cadgen_mirror.py.
    """
    pairs = []
    for rel in relative_files:
        path = os.path.join(root, rel)
        with open(path, "rb") as handle:
            raw = handle.read()
        if rel.endswith(".py"):
            file_hash = "ast1:" + hashlib.sha256(
                ast.dump(ast.parse(raw)).encode("utf-8")
            ).hexdigest()
        else:
            file_hash = hashlib.sha256(raw).hexdigest()
        pairs.append((rel, file_hash))
    digest = hashlib.sha256()
    for rel, file_hash in sorted(pairs):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _write_generated_package(
    root,
    py_name,
    *,
    closure_extra=None,
    with_package=True,
    closure_hash=True,
    schema_version=_STEP_SCHEMA_VERSION,
    bake_hash=None,
):
    """A gen_step generator + optionally its generated package
    (sourceKind=python), keyed by the STEP name like cadgen writes it
    (widget.step.py -> __cadgen__/models/widget.step)."""
    py_path = os.path.join(root, py_name)
    with open(py_path, "w") as h:
        h.write("def gen_step():\n    return None\n")
    for rel in (closure_extra or []):
        with open(os.path.join(root, rel), "w") as h:
            h.write("# closure dep\n")
    if not with_package:
        return py_path, None
    package_key = py_name[:-3] if py_name.endswith((".step.py", ".stp.py")) else py_name
    pkg = os.path.join(root, "__cadgen__", "models", package_key)
    os.makedirs(os.path.join(pkg, "components"), exist_ok=True)
    with open(os.path.join(pkg, "components", "c0.surf"), "wb") as h:
        h.write(b"glTF\x02\x00\x00\x00")
    closure_files = [py_name] + list(closure_extra or [])
    descriptor = {
        "kind": "assembly-package",
        "sourceKind": "python",
        "sourcePath": py_name,
        "sourceClosureFiles": closure_files,
        "components": {"c0": {"surf": "components/c0.surf"}},
    }
    if schema_version is not None:
        descriptor["packageSchemaVersion"] = schema_version
    if bake_hash is not None:
        descriptor["bakeHash"] = bake_hash
    if closure_hash:
        descriptor["sourceClosureHash"] = _reference_closure_hash(root, closure_files)
    with open(os.path.join(pkg, "assembly.json"), "w") as h:
        json.dump(descriptor, h)
    return py_path, pkg


class OwnsDxfEntry(unittest.TestCase):
    def test_only_generators_are_owned(self):
        self.assertTrue(artifact.owns_entry({"file": "/x/outline.dxf.py"}))
        self.assertTrue(artifact.owns_dxf_entry({"file": "/x/outline.DXF.PY"}))
        # An imported .dxf renders natively — the client parses the file itself —
        # so it needs no build and is deliberately NOT owned.
        self.assertFalse(artifact.owns_entry({"file": "/x/outline.dxf"}))
        self.assertFalse(artifact.owns_dxf_entry({"file": "/x/OUTLINE.DXF"}))
        self.assertFalse(artifact.owns_dxf_entry({"file": "/x/a.step.py"}))
        self.assertFalse(artifact.owns_dxf_entry({"file": "/x/notes.dxf.txt"}))
        self.assertFalse(artifact.owns_dxf_entry(None))


class OwnsImplicitEntry(unittest.TestCase):
    def test_implicit_sources_are_owned(self):
        self.assertTrue(artifact.owns_entry({"file": "/x/gyroid.implicit.js"}))
        self.assertTrue(artifact.owns_implicit_entry({"file": "/x/gyroid.implicit.mjs"}))
        self.assertTrue(artifact.owns_implicit_entry({"file": "/x/Gyroid.IMPLICIT.JS"}))
        self.assertFalse(artifact.owns_implicit_entry({"file": "/x/params.js"}))
        self.assertFalse(artifact.owns_implicit_entry({"file": "/x/a.step"}))
        self.assertFalse(artifact.owns_implicit_entry(None))

    def test_the_owned_suffixes_come_from_the_producer(self):
        # Imported, not hand-copied: the set of sources the viewer asks to build cannot
        # drift from the set the builder accepts.
        self.assertEqual(artifact.IMPLICIT_SUFFIXES, _implicit_package.IMPLICIT_SUFFIXES)


class ArtifactFormatDispatchIsTotal(unittest.TestCase):
    """`_artifact_format` must be a total predicate->record table, not an if/else that falls
    through to STEP. A half-wired format answering as STEP would validate an assembly.json
    that does not exist, report `ready` for the missing-source code, and never build."""

    def test_each_owned_kind_selects_its_own_producer(self):
        cases = {
            "/x/outline.dxf.py": "_build_dxf_artifact",
            "/x/gyroid.implicit.js": "_build_implicit_artifact",
            "/x/part.step": "_build_step_artifact",
            "/x/part.step.py": "_build_step_artifact",
        }
        for file_ref, build_name in cases.items():
            with self.subTest(file=file_ref):
                fmt = artifact._artifact_format(file_ref)
                self.assertEqual(fmt["build"].__name__, build_name)

    def test_an_unowned_entry_raises_instead_of_answering_as_step(self):
        for entry in ({"file": "/x/mesh.stl"}, {"file": "/x/toolpath.gcode"}, {"file": "/x/vendor.dxf"}, None):
            with self.subTest(entry=entry):
                self.assertFalse(artifact.owns_entry(entry))
                with self.assertRaises(ValueError):
                    artifact._artifact_format(str((entry or {}).get("file") or ""))

    def test_every_producer_the_backend_shells_out_to_is_worker_dispatchable(self):
        # The warm worker keeps its own module allowlist; a producer missing from it fails at
        # RUNTIME with "Unknown cadgen module for worker", which no unit test of either side
        # alone would catch. The worker lives in cadgen.daemon now -- one pool serves both
        # the CLI and the viewer -- but the allowlist and this guarantee moved with it.
        from cadgen.daemon import worker

        dispatch = worker._module_dispatch()
        for module in (
            "cadgen.step_artifact_cli",
            "cadgen.dxf_export_target",
            "cadgen.implicit_artifact",
            "cadgen.step_export_target",
            "cadgen.implicit_export",
        ):
            with self.subTest(module=module):
                self.assertIn(module, dispatch)
                # The worker calls run(args) on every one.
                self.assertIn("argv", inspect.signature(dispatch[module]).parameters)


if __name__ == "__main__":
    unittest.main()
