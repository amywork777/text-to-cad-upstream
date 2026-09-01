"""Artifact operations for a STATIC visualization tool.

The viewer's render path runs no generators: it renders what exists. Generation
and export belong to model scripts and the CLIs. The one build-shaped thing the
viewer does is importing a raw FOREIGN ``.step`` — making its render package
current in the shared store, which is exactly the cache action — and that goes
through ``compile_client``, which calls cadgen's compile entry point in a
private worker.

cadgen remains a SOFT dependency: absent, viewing is unaffected and imports fail
with one actionable message. Nothing in this module imports it.
"""

from __future__ import annotations

import os

from .artifact_status import (
    ARTIFACT_STATE,
    artifact_status as compute_artifact_status,
    owns_artifact_path,
    owns_step_path,
    resolve_artifact_verdict,
)
from .build_progress import ProgressRegistry, build_progress_snapshot
from .compile_client import CompileClient, cadgen_unavailable_message
from .store_paths import render_package_dir

__all__ = ["CLI_BUILD_HINT", "CadgenOps", "create_cadgen_ops"]

CLI_BUILD_HINT = (
    "The viewer is a static visualization tool and does not run generators. "
    "Build this model by running its script: python <source>."
)


class CadgenOps:
    def __init__(self, root_dir: str, *, registry=None, client=None) -> None:
        self.root_dir = root_dir
        self.registry = registry if registry is not None else ProgressRegistry()
        self.client = client if client is not None else CompileClient(registry=self.registry)

    def step_import_available(self) -> bool:
        return self.client.available()

    def shutdown(self) -> None:
        self.client.shutdown()

    def _candidate(self, file_ref) -> str:
        text = str(file_ref or "")
        return text if os.path.isabs(text) else os.path.abspath(os.path.join(self.root_dir, text))

    # --- status -----------------------------------------------------------

    def artifact_status(self, file_ref) -> dict:
        if not owns_artifact_path(file_ref):
            # Not ours to have an opinion about: no candidate resolution, no
            # disk read, no kernel.
            return {"state": ARTIFACT_STATE.READY}

        candidate = self._candidate(file_ref)
        package_dir = render_package_dir(candidate)

        snapshot = build_progress_snapshot(candidate, registry=self.registry)
        if snapshot is None and self.client.in_flight(package_dir):
            # Our worker is starting up but has not reported a phase yet. An
            # indeterminate generating badge beats showing nothing, and it is
            # what the client's attach loop needs in order to have something to
            # attach TO.
            snapshot = {"writing": True, "busy": False, "runId": None, "progress": None}

        # Resolved once and threaded through both uses below.
        verdict = resolve_artifact_verdict(file_ref, self.root_dir)
        status = compute_artifact_status(
            file_ref, self.root_dir, snapshot=snapshot, verdict=verdict
        )
        if status.get("state") != ARTIFACT_STATE.NEEDS_BUILD:
            return status

        # The ONLY buildable state the viewer supports is importing a raw
        # foreign STEP. Everything else renders what exists or names the CLI.
        if verdict.get("rawStep") and not verdict.get("generated"):
            if self.step_import_available():
                offer = {
                    "state": ARTIFACT_STATE.NEEDS_BUILD,
                    "reason": status.get("reason"),
                    "stepImport": True,
                }
                if status.get("blocked"):
                    # Carried through rather than dropped: the client maps
                    # blocked to ATTACH, and losing it here would make it POST a
                    # build into a generator someone else is already occupying.
                    offer["blocked"] = True
                return offer
            return {
                "state": ARTIFACT_STATE.ERROR,
                "error": f"This STEP file has not been imported yet, and {cadgen_unavailable_message()}",
            }

        # No stale-render limbo exists under content keying: an edited file
        # resolves to a different key (needs-build above), and a resolved
        # package is by construction the render of exactly these bytes.
        return {"state": ARTIFACT_STATE.ERROR, "error": CLI_BUILD_HINT}

    # --- build ------------------------------------------------------------

    def build_artifact(self, file_ref, *, force: bool = False) -> dict:
        if not owns_artifact_path(file_ref):
            return {"ok": True, "state": ARTIFACT_STATE.READY}

        candidate = self._candidate(file_ref)
        verdict = resolve_artifact_verdict(file_ref, self.root_dir)
        if self._is_raw_step_file(candidate) and not verdict.get("generated"):
            imported = self.client.compile(candidate, force=force)
            if imported.get("ok") and imported.get("contended"):
                # A peer holds the package lock and is building it. The client
                # treats this exactly like attaching to a CLI build.
                return {"ok": True, "state": ARTIFACT_STATE.GENERATING, "contended": True}
            if imported.get("ok"):
                # The compile payload is spread LAST, so its own ok/document/
                # package/skipped/contended land on the wire and its ok wins.
                return {
                    "ok": True,
                    "state": ARTIFACT_STATE.READY,
                    "stepImport": True,
                    **imported,
                }
            return {
                "ok": False,
                "state": ARTIFACT_STATE.ERROR,
                "error": f"STEP import failed: {imported.get('error') or 'unknown error'}",
            }
        return {"ok": False, "state": ARTIFACT_STATE.ERROR, "error": CLI_BUILD_HINT}

    @staticmethod
    def _is_raw_step_file(candidate: str) -> bool:
        if not owns_step_path(candidate):
            return False
        try:
            return os.path.exists(candidate)
        except ValueError:
            return False


def create_cadgen_ops(root_dir: str, **kwargs) -> CadgenOps:
    return CadgenOps(root_dir, **kwargs)
