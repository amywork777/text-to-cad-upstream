"""Render-artifact operations — the CAD Viewer's ONE Python touchpoint.

The viewer is a pure-JS app (``viewer/server``). Everything it cannot answer
from the filesystem alone funnels through this stdlib-only CLI:

    python -m cadgen.render_ops status --file <ref> --root <dir>
    python -m cadgen.render_ops build  --file <ref> --root <dir> [--force]
    python -m cadgen.render_ops export --file <ref> --root <dir> --format <f> --out <path>
    python -m cadgen.render_ops probe

Each prints ONE JSON line on stdout. ``status`` answers the artifact state
machine (ready | needs-build | generating | error) — the freshness validators
here are the render-side authority and share their digests, schema versions,
bake hashes and lock protocol with the PRODUCER's own gates, so the two can
never disagree about staleness. ``build``/``export`` dispatch the heavy
OCP work to the shared warm daemon pool when available, else a cold
subprocess; OCP is never imported into this process.

Freshness is a PURE descriptor read (descriptor + payload existence + schema
version + bake hash; a generated entry re-hashes its recorded source closure,
an imported entry compares the digest its format's spec-table row names) — no
OCP. Importing this module pulls in only stdlib-only cadgen internals
(``cadgen.coordination``, ``cadgen._internal.source_hash``), pinned by
tests/python/packages/cadgen/test_coordination_is_stdlib_only.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from cadgen._internal.dxf_output import dxf_output_current
from cadgen._internal.implicit_package import (
    IMPLICIT_DESCRIPTOR_NAME,
    IMPLICIT_PACKAGE_KIND,
    IMPLICIT_PACKAGE_SCHEMA_VERSION,
    IMPLICIT_SUFFIXES,
    implicit_bake_settings,
)
from cadgen._internal.package_freshness import (
    STEP_PACKAGE_VERSION,
    bake_hash_matches,
    canonical_bake_hash,
    schema_version_matches,
)
from cadgen._internal.source_hash import closure_hash_matches
from cadgen.catalog import render_package_dir as _catalog_render_package_dir

ARTIFACT_STATE_READY = "ready"
ARTIFACT_STATE_NEEDS_BUILD = "needs-build"
ARTIFACT_STATE_GENERATING = "generating"
ARTIFACT_STATE_ERROR = "error"

# Every freshness code a build can fix. Not STEP-specific: one set spanning every
# artifact-managed format, because the client asks one question ("can this be
# built?") of one state machine.
BUILDABLE_ARTIFACT_CODES = frozenset([
    "missing_glb", "missing_step_topology", "missing_edge_topology",
    "missing_surface_edge_attributes", "missing_selector_topology",
    "missing_source_path", "missing_step_hash", "stale_step_artifact",
    "unsupported_step_topology",
    # Generated-drawing output codes (same buildable semantics): the .dxf IS the
    # product now, so freshness is the output record, not a package.
    "missing_dxf_output", "stale_dxf_output",
    # Implicit render package codes.
    "missing_implicit_artifact", "stale_implicit_artifact", "unsupported_implicit_artifact",
])

DXF_GENERATOR_SUFFIX = ".dxf.py"
IMPLICIT_CAD_EXTENSIONS = tuple(IMPLICIT_SUFFIXES)

_STEP_ENTRY_RE = re.compile(r"\.(step|stp)(\.py)?$", re.IGNORECASE)
# Generated drawings only: an imported .dxf renders natively (the client parses
# the file itself — design/standalone-viewer.md Phase A), so it needs no build
# and is deliberately NOT owned.
_DXF_ENTRY_RE = re.compile(r"\.dxf\.py$", re.IGNORECASE)

_STEP_EXPORT_FORMAT_SUFFIX = {"step": "step", "stl": "stl", "3mf": "3mf", "glb": "glb"}
_IMPLICIT_EXPORT_FORMATS = ("stl", "glb", "3mf")

# How long a build may wait for a peer's generation lock before reporting the
# peer's run instead. Long enough that an UNCONTENDED acquire never trips it,
# short enough that a request cannot park the shared warm worker.
_ARTIFACT_LOCK_TIMEOUT_SECONDS = 0.5


# --- path helpers -------------------------------------------------------------------
def render_package_dir(entry_path: str) -> str:
    """The render package directory for an entry file, resolved.

    Delegates to cadgen.catalog so the viewer-facing gate and the producer key
    packages identically (a symlinked entry must take the same lock sentinel on
    both sides)."""
    return str(_catalog_render_package_dir(Path(entry_path)))


def path_is_inside(file_path: str, root_path: str) -> bool:
    relative = os.path.relpath(os.path.abspath(file_path), os.path.abspath(root_path))
    return relative == "" or (
        relative != ".."
        and not relative.startswith(".." + os.sep)
        and not os.path.isabs(relative)
    )


def normalized_file_ref(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if "\0" in raw:
        raise ValueError("File path contains an invalid null byte")
    if os.path.isabs(raw):
        return os.path.abspath(raw).replace(os.sep, "/")
    return raw.lstrip("/")


def is_dxf_generator_path(file_path: str) -> bool:
    return str(file_path or "").lower().endswith(DXF_GENERATOR_SUFFIX)


def path_is_implicit_cad_source(value: str = "") -> bool:
    pathname = re.split(r"[?#]", str(value or ""), maxsplit=1)[0].lower()
    return any(pathname.endswith(ext) for ext in IMPLICIT_CAD_EXTENSIONS)


def _file_stats(file_path: str):
    try:
        st = os.stat(file_path)
    except OSError:
        return None
    return st if os.path.isfile(file_path) else None


def _sha256_file(file_path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_has_python_generator(file_path: str, generator_name: str) -> bool:
    if not generator_name:
        return False
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return re.search(r"\b" + re.escape(generator_name) + r"\s*\(", handle.read()) is not None
    except OSError:
        return False


# --- ownership ----------------------------------------------------------------------
def owns_step_path(file_path: str) -> bool:
    return bool(_STEP_ENTRY_RE.search(str(file_path or "")))


def owns_dxf_path(file_path: str) -> bool:
    return bool(_DXF_ENTRY_RE.search(str(file_path or "")))


def owns_implicit_path(file_path: str) -> bool:
    lowered = str(file_path or "").lower()
    return any(lowered.endswith(suffix) for suffix in IMPLICIT_SUFFIXES)


def owns_path(file_path: str) -> bool:
    return owns_step_path(file_path) or owns_dxf_path(file_path) or owns_implicit_path(file_path)


# Catalog-entry adapters, kept because three non-viewer test suites (and the
# drawing/portability gates) ask ownership of an entry dict.
def owns_step_entry(entry) -> bool:
    return bool(entry) and owns_step_path(str(entry.get("file") or ""))


def owns_dxf_entry(entry) -> bool:
    return bool(entry) and owns_dxf_path(str(entry.get("file") or ""))


def owns_implicit_entry(entry) -> bool:
    return bool(entry) and owns_implicit_path(str(entry.get("file") or ""))


def owns_entry(entry) -> bool:
    return owns_step_entry(entry) or owns_dxf_entry(entry) or owns_implicit_entry(entry)


# --- pure freshness validation (shared by every package format) ----------------------
# Per-format descriptor names, package kinds, payload refs, schema versions, digest field
# names, bake ownership, and error codes. The validation ALGORITHM is identical for all;
# only this table differs. Anything format-specific belongs HERE, not in a branch inside
# the validator and not as a field alias: `stepHash` is load-bearing at a dozen cadgen
# sites beyond the render descriptor, so newer formats name their digest `sourceDigest`
# and the table says which.
_STEP_PACKAGE = {
    "descriptor": "assembly.json",
    "package_kind": "assembly-package",
    "schema_version": STEP_PACKAGE_VERSION,
    "source_digest_field": "stepHash",
    "missing_digest": "missing_step_hash",
    # STEP bakes no settings: components are exact geometry; the producer compares
    # mesh tolerances separately.
    "bake_settings": None,
    "missing": "missing_glb",
    "unreadable": "missing_step_topology",
    "unsupported": "unsupported_step_topology",
    "stale": "stale_step_artifact",
}
_IMPLICIT_PACKAGE = {
    "descriptor": IMPLICIT_DESCRIPTOR_NAME,
    "package_kind": IMPLICIT_PACKAGE_KIND,
    "schema_version": IMPLICIT_PACKAGE_SCHEMA_VERSION,
    "source_digest_field": "sourceDigest",
    "missing_digest": "stale_implicit_artifact",
    # The bake IS the artifact: model.glb froze one resolution, one cell cap and the
    # mesher's geometry contract at the model's default parameter values.
    "bake_settings": implicit_bake_settings,
    "missing": "missing_implicit_artifact",
    "unreadable": "missing_implicit_artifact",
    "unsupported": "unsupported_implicit_artifact",
    "stale": "stale_implicit_artifact",
}


def _step_payload_refs(descriptor):
    """Every component artifact the assembly descriptor claims (the exact-surface
    ``.surf`` — design/surface-rendering.md R5)."""
    components = descriptor.get("components") if isinstance(descriptor.get("components"), dict) else {}
    return [str((component or {}).get("surf") or "").strip() for component in components.values()]


def _implicit_payload_refs(descriptor):
    """The one payload an implicit package has: the baked mesh."""
    return [str(descriptor.get("glb") or "").strip()]


def _validate_render_package(spec, source_path, payload_refs, model_folder):
    """Return (ok, code) — ok=True when fresh, else (False, <error_code>).

    One algorithm for every format: the package dir and descriptor must exist, declare
    the expected kind and EXACTLY the current ``packageSchemaVersion``, every payload
    file the descriptor names must be on disk, its ``bakeHash`` must match the format's
    current bake settings, and then freshness is decided by provenance —

    * generated (``sourceKind: python``): the recorded source closure must still hash
      unchanged (the SAME content digest cadgen's CLI gate uses, so the two never
      disagree). A descriptor recording no usable closure is STALE: it cannot be shown
      to be current, and a rebuild is cheap and self-correcting.
    * imported: the on-disk file must still hash to the digest the spec table names
      (``stepHash`` for STEP). This FAILS CLOSED — a descriptor recording no digest for
      a source file that exists reports needs-build, matching cadgen's producer gate.
    """
    package_dir = render_package_dir(source_path)
    if not os.path.isdir(package_dir):
        return (False, spec["missing"])
    descriptor_path = os.path.join(package_dir, spec["descriptor"])
    try:
        with open(descriptor_path, "r", encoding="utf-8") as handle:
            descriptor = json.load(handle)
    except (OSError, ValueError):
        return (False, spec["unreadable"])
    if not isinstance(descriptor, dict) or descriptor.get("kind") != spec["package_kind"]:
        return (False, spec["unsupported"])
    # Strict equality, no tolerant reader: the schema version is this stack's single
    # invalidation channel (bump it and every package of that kind rebuilds, lazily,
    # on reopen) in place of per-field compatibility branches.
    if not schema_version_matches(descriptor, spec["schema_version"]):
        return (False, spec["unsupported"])
    for ref in payload_refs(descriptor):
        if not ref or not os.path.isfile(os.path.join(package_dir, ref)):
            return (False, spec["missing"])
    bake_settings = spec["bake_settings"]
    # A kind that bakes NOTHING (STEP) must still be checked: a descriptor that
    # records a bakeHash anyway is claiming a payload it never wrote.
    if not bake_hash_matches(
        descriptor, canonical_bake_hash(bake_settings() if bake_settings else None)
    ):
        return (False, spec["stale"])
    if str(descriptor.get("sourceKind", "step")).strip().lower() == "python":
        if not os.path.isfile(source_path):
            return (False, "missing_source_path")
        closure = descriptor.get("sourceClosureFiles")
        if not isinstance(closure, list) or not closure:
            return (False, spec["stale"])
        if not closure_hash_matches(
            descriptor.get("sourceClosureHash"), closure, base=Path(model_folder)
        ):
            return (False, spec["stale"])
        return (True, None)
    recorded_digest = str(descriptor.get(spec["source_digest_field"], "")).strip()
    if _file_stats(source_path):
        # Fail closed. A descriptor with no digest for a source file that is right there
        # cannot be shown to be current.
        if not recorded_digest:
            return (False, spec["missing_digest"])
        current = _sha256_file(source_path)
        if current and recorded_digest != current:
            return (False, spec["stale"])
    return (True, None)


def validate_step_freshness(repo_root, source_path):
    """ok=True (fresh/ready) or (False, code). source_path is the entry's step path
    (the `.step.py` for a generated model, the `.step` for an imported one)."""
    del repo_root  # closure paths resolve against the model folder, not the repo root
    return _validate_render_package(
        _STEP_PACKAGE, source_path, _step_payload_refs, os.path.dirname(os.path.abspath(source_path))
    )


def validate_dxf_freshness(repo_root, source_path):
    """ok=True (fresh/ready) or (False, code). source_path is the `.dxf.py`
    generator; its product is the sibling `.dxf` the viewer parses directly.
    Freshness is the output record — the SAME gate the CLI's no-op path uses
    (cadgen._internal.dxf_output), so the two authorities cannot disagree."""
    del repo_root
    source_path = Path(source_path)
    if not os.path.isfile(source_path):
        return (False, "missing_source_path")
    sibling = source_path.with_name(source_path.name[: -len(".py")])
    if not sibling.is_file():
        return (False, "missing_dxf_output")
    if not dxf_output_current(source_path, sibling):
        return (False, "stale_dxf_output")
    return (True, None)


def validate_implicit_freshness(repo_root, source_path):
    """ok=True (fresh/ready) or (False, code). source_path is the `.implicit.js` model."""
    del repo_root
    return _validate_render_package(
        _IMPLICIT_PACKAGE, source_path, _implicit_payload_refs, os.path.dirname(os.path.abspath(source_path))
    )


# --- generation state (ONE implementation, shared with the producer) -----------------
def generation_snapshot(package_dir: str):
    """Non-blocking view of what is happening to ``package_dir`` right now.

    Returns a ``cadgen.coordination.Snapshot``: ``state`` is idle/writing/busy, decided
    by the KERNEL rather than by any written file, so a crashed or killed build reads as
    idle with no stale window. ``progress`` is attached only when the record on disk
    belongs to the run currently holding the lock.
    """
    from cadgen.coordination import snapshot

    return snapshot(package_dir)


# --- source resolution ----------------------------------------------------------------
def _source_candidates_for_file_ref(file_ref, root_path):
    normalized = normalized_file_ref(file_ref)
    if not normalized:
        return "", []
    if os.path.isabs(normalized):
        candidates = [os.path.abspath(normalized), os.path.abspath(os.path.join(root_path, normalized.lstrip("/")))]
    else:
        candidates = [os.path.abspath(os.path.join(root_path, normalized))]
    seen = []
    existing = []
    for c in candidates:
        if c in seen:
            continue
        seen.append(c)
        inside = c == root_path or path_is_inside(c, root_path)
        if inside and os.path.exists(c):
            existing.append(c)
    return normalized, existing


def _same_stem_python_generator_path(step_path):
    ext = os.path.splitext(step_path)[1].lower()
    if ext not in (".step", ".stp"):
        return ""
    candidate = os.path.join(os.path.dirname(step_path), os.path.basename(step_path) + ".py")
    return candidate if _file_has_python_generator(candidate, "gen_step") else ""


def resolve_step_source(file_ref, root_path):
    normalized, candidates = _source_candidates_for_file_ref(file_ref, root_path)
    if not normalized:
        raise ValueError("Missing STEP file")
    for c in candidates:
        ext = os.path.splitext(c)[1].lower()
        if ext == ".py":
            stem = os.path.basename(c)[: -len(".py")]
            step_base = stem if re.search(r"\.(step|stp)$", stem, re.IGNORECASE) else stem + ".step"
            return {"stepPath": os.path.join(os.path.dirname(c), step_base), "sourcePath": c, "skipStepWrite": True}
        if ext not in (".step", ".stp"):
            raise ValueError("Only STEP/STP sources or same-stem Python generators can generate STEP topology artifacts")
        # A same-stem `<name>.step.py` generator OWNS the entry even when an exported
        # `<name>.step` sits beside it: only the generator can declare the model's
        # `params` sidecar, and resolving it here keys the build, the freshness check
        # and the STEP export on one source.
        generator = _same_stem_python_generator_path(c)
        if generator:
            return {"stepPath": c, "sourcePath": generator, "skipStepWrite": True}
        return {"stepPath": c, "sourcePath": "", "skipStepWrite": False}
    raise ValueError(f"STEP file not found: {normalized}")


def resolve_dxf_source(file_ref, root_path):
    normalized, candidates = _source_candidates_for_file_ref(file_ref, root_path)
    if not normalized:
        raise ValueError("Missing DXF file")
    for c in candidates:
        if not is_dxf_generator_path(c):
            raise ValueError(
                "Only .dxf.py drawing generators are artifact-managed; an imported "
                ".dxf renders directly and needs no build"
            )
        return {"sourcePath": c}
    raise ValueError(f"DXF source not found: {normalized}")


def resolve_implicit_source(file_ref, root_path):
    normalized, candidates = _source_candidates_for_file_ref(file_ref, root_path)
    if not normalized:
        raise ValueError("Missing implicit CAD file")
    for c in candidates:
        if not path_is_implicit_cad_source(c):
            raise ValueError("Only .implicit.js models can generate implicit CAD render artifacts")
        return {"sourcePath": c}
    raise ValueError(f"Implicit CAD source not found: {normalized}")


# --- cadgen bridge (warm daemon pool, cold subprocess fallback) -----------------------
_CAD_BACKEND_PROBE = (
    "import OCP\n"
    "import build123d\n"
    "import cadgen.step_artifact_cli\n"
)
_CAD_BACKEND_PROBE_TIMEOUT_SECONDS = 30


def probe_cadgen_runtime(repo_root: str) -> dict:
    """Validate the current interpreter in an isolated child process, keeping OCP out
    of this one."""
    env = dict(os.environ)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CAD_BACKEND_PROBE],
            cwd=repo_root if repo_root and os.path.isdir(repo_root) else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=_CAD_BACKEND_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "python": sys.executable,
            "error": f"CAD backend validation timed out after {_CAD_BACKEND_PROBE_TIMEOUT_SECONDS}s.",
        }
    except OSError as exc:
        return {"ok": False, "python": sys.executable, "error": str(exc)}
    if proc.returncode == 0:
        return {"ok": True, "python": sys.executable, "error": ""}
    detail = (proc.stderr or proc.stdout or f"probe exited with code {proc.returncode}").strip()
    if len(detail) > 4000:
        detail = detail[-4000:]
    return {"ok": False, "python": sys.executable, "error": detail}


def _warm_enabled() -> bool:
    """VIEWER_CAD_WORKER=0 forces the cold path (tests and debugging use it)."""
    return str(os.environ.get("VIEWER_CAD_WORKER", "1")).strip() not in {"0", "false", "no", ""}


def run_cadgen(module: str, args, repo_root: str) -> dict:
    """Run a cadgen build/export op and return its payload dict (``{ok:false,error}``
    on failure). Prefers the shared warm pool in cadgen.daemon — a terminal build and a
    viewer build reuse the same warm processes — falling back to a cold subprocess
    whenever the pool is unavailable, at capacity, or switched off."""
    if _warm_enabled():
        from cadgen.daemon import client as daemon_client

        payload = daemon_client.invoke(module, args, repo_root)
        if payload is not None:
            return payload
    return run_cadgen_cold(module, args, repo_root)


def run_cadgen_cold(module: str, args, repo_root: str) -> dict:
    """Run `python -m <module> <args>` in a fresh subprocess and return the last stdout
    JSON line as a dict, or {ok:false,error} on failure."""
    env = dict(os.environ)
    # Byte-deterministic artifacts (drawing packages are content-addressed): ezdxf's
    # object ordering depends on Python hash randomization.
    env.setdefault("PYTHONHASHSEED", "0")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", module, *args],
            cwd=repo_root, env=env, capture_output=True, text=True,
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    for line in reversed(proc.stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except ValueError:
                break
    message = (proc.stderr or proc.stdout or f"cadgen {module} exited with code {proc.returncode}").strip()
    return {"ok": False, "exitCode": proc.returncode, "error": message}


# --- the format table -----------------------------------------------------------------
# One record per render-package format, matched in order. The table is TOTAL by
# construction: it RAISES when no predicate matches instead of falling through to STEP.
# A half-wired format that silently answered as STEP would validate an assembly.json
# that does not exist, report `ready` for the missing-source code, and never build.
def _artifact_format(file_path: str):
    formats = (
        (owns_dxf_path, {
            "validate": validate_dxf_freshness,
            "resolve_source": lambda file_ref, root: resolve_dxf_source(file_ref, root)["sourcePath"],
            "build": _build_dxf_artifact,
        }),
        (owns_implicit_path, {
            "validate": validate_implicit_freshness,
            "resolve_source": lambda file_ref, root: resolve_implicit_source(file_ref, root)["sourcePath"],
            "build": _build_implicit_artifact,
        }),
        (owns_step_path, {
            "validate": validate_step_freshness,
            "resolve_source": lambda file_ref, root: (
                (lambda r: r.get("sourcePath") or r["stepPath"])(resolve_step_source(file_ref, root))
            ),
            "build": _build_step_artifact,
        }),
    )
    for owns, record in formats:
        if owns(file_path):
            return record
    raise ValueError(f"No render-artifact format owns this entry: {file_path or '(unknown)'}")


# --- status ---------------------------------------------------------------------------
def artifact_status(file_ref: str, root_path: str) -> dict:
    """The /__cad/artifact GET state machine, minus catalog concerns (the JS server
    owns the catalog and attaches the entry's asset ref itself)."""
    normalized = normalized_file_ref(file_ref)
    if not owns_path(normalized):
        return {"state": ARTIFACT_STATE_READY}
    fmt = _artifact_format(normalized)
    try:
        artifact_source = fmt["resolve_source"](file_ref, root_path)
    except ValueError as exc:
        return {"state": ARTIFACT_STATE_ERROR, "error": str(exc)}
    snap = generation_snapshot(render_package_dir(artifact_source))
    if snap.writing:
        # The LOCK decides the state; the record only says how far along it is. runId
        # lets the client tell one run from the next, so its bar resets on a handoff
        # instead of jumping backwards.
        status = {"state": ARTIFACT_STATE_GENERATING}
        if snap.run_id:
            status["runId"] = snap.run_id
        if snap.progress is not None:
            status["progress"] = snap.progress
        return status
    ok, code = fmt["validate"](root_path, artifact_source)
    if ok:
        # A busy GENERATOR (an export running this model's gen_step) does not hide a
        # renderable model — nothing is rewriting the package, so what is on disk is
        # still valid. Annotated so the client can say why a build is unavailable.
        status = {"state": ARTIFACT_STATE_READY}
        if snap.busy:
            status["busy"] = True
            if snap.run_id:
                status["runId"] = snap.run_id
            if snap.progress is not None:
                status["progress"] = snap.progress
        return status
    if code in BUILDABLE_ARTIFACT_CODES:
        status = {"state": ARTIFACT_STATE_NEEDS_BUILD, "reason": code}
        if snap.busy:
            # Stale AND the generator is occupied. A build would not block on it — the
            # two take different sentinels — it would run the same generator a second
            # time, concurrently, for nothing. Telling the client to wait is an
            # efficiency call, not deadlock avoidance.
            status["blocked"] = True
        return status
    return {"state": ARTIFACT_STATE_ERROR, "reason": code, "error": code}


# --- build ----------------------------------------------------------------------------
def _run_artifact_build(module, args, root_path, *, force, error_label):
    full_args = ["--repo-root", root_path, *args]
    if force:
        full_args += ["--force"]
    # NEVER wait out a peer inside a build: this request may run in the ONE serial warm
    # worker, so a build parked on another process's lock stops every OTHER model's
    # build and export for as long as the peer runs.
    full_args += ["--lock-timeout", str(_ARTIFACT_LOCK_TIMEOUT_SECONDS)]
    if os.environ.get("VIEWER_STEP_ARTIFACT_VERBOSE") == "1":
        full_args += ["--verbose"]
    result = run_cadgen(module, full_args, root_path)
    if result.get("contended"):
        # A peer holds the lock. Nothing failed and nothing was built: the caller
        # reports the peer's run so the client attaches to its progress.
        return {"ok": True, "contended": True, "error": "", "result": result}
    error = "" if result.get("ok") else str(result.get("error") or error_label)
    return {"ok": bool(result.get("ok")), "error": error, "result": result}


def _build_step_artifact(file_ref, force, root_path):
    resolved = resolve_step_source(file_ref, root_path)
    step_path = resolved["stepPath"]
    ext = os.path.splitext(step_path)[1].lower()
    has_step = ext in (".step", ".stp") and os.path.isfile(step_path)
    generator = resolved.get("sourcePath") or ""
    has_generator = bool(generator) and os.path.isfile(generator)
    if not has_step and not has_generator:
        raise ValueError(
            "CAD Viewer regenerates render artifacts only for existing STEP/STP files "
            "or their same-stem Python generators."
        )
    args = ["--step", step_path]
    if has_generator:
        args += ["--source-path", generator]
    result = _run_artifact_build(
        "cadgen.step_artifact_cli", args, root_path,
        force=force, error_label="STEP render artifact build failed",
    )
    return {**result, "stepPath": step_path}


def _build_dxf_artifact(file_ref, force, root_path):
    resolved = resolve_dxf_source(file_ref, root_path)
    source_path = resolved["sourcePath"]
    sibling = source_path[: -len(".py")]
    args = ["--source-path", source_path, "--out", sibling]
    result = _run_artifact_build(
        "cadgen.dxf_export_target", args, root_path,
        force=force, error_label="DXF generation failed",
    )
    return {**result, "sourcePath": source_path}


def _build_implicit_artifact(file_ref, force, root_path):
    resolved = resolve_implicit_source(file_ref, root_path)
    source_path = resolved["sourcePath"]
    result = _run_artifact_build(
        "cadgen.implicit_artifact", ["--source-path", source_path], root_path,
        force=force, error_label="Implicit CAD render artifact build failed",
    )
    return {**result, "sourcePath": source_path}


def resolve_artifact(file_ref: str, root_path: str, *, force: bool = False) -> dict:
    """The /__cad/artifact POST: ensure the entry's render package is fresh, building
    it when it is not. A POST NEVER BLOCKS ON A PEER: when another run holds the
    generation lock this reports `generating` immediately so the client attaches to the
    peer's live progress instead of queuing a duplicate rebuild."""
    normalized = normalized_file_ref(file_ref)
    if not owns_path(normalized):
        return {"ok": True, "state": ARTIFACT_STATE_READY}
    fmt = _artifact_format(normalized)
    try:
        artifact_source = fmt["resolve_source"](file_ref, root_path)
    except ValueError as exc:
        return {"ok": False, "state": ARTIFACT_STATE_ERROR, "error": str(exc)}
    # The FAST PATH, not the guarantee: a peer can take the lock immediately after this
    # snapshot, and force= skips it entirely. The guarantee is the bounded
    # --lock-timeout in _run_artifact_build, whose contended result lands on the same
    # answer below.
    snap = generation_snapshot(render_package_dir(artifact_source))
    if not force and snap.writing:
        result = {"ok": True, "state": ARTIFACT_STATE_GENERATING}
        if snap.run_id:
            result["runId"] = snap.run_id
        return result
    built = fmt["build"](file_ref, force, root_path)
    if built.get("contended"):
        result = {"ok": True, "state": ARTIFACT_STATE_GENERATING}
        live = generation_snapshot(render_package_dir(artifact_source))
        if live.run_id:
            result["runId"] = live.run_id
        return result
    if built["ok"]:
        return {"ok": True, "state": ARTIFACT_STATE_READY}
    return {"ok": False, "state": ARTIFACT_STATE_ERROR, "error": built["error"]}


# --- export ---------------------------------------------------------------------------
def generate_export(file_ref: str, root_path: str, fmt: str, out_path: str) -> dict:
    """Write one export to ``out_path``. Destination choice (native Save dialog,
    fallback-beside-source) is the JS server's job; by the time this runs the
    destination is decided."""
    normalized_format = str(fmt or "").strip().lower().lstrip(".")
    normalized_ref = normalized_file_ref(file_ref)
    out_path = os.path.abspath(out_path)
    if is_dxf_generator_path(normalized_ref):
        if normalized_format != "dxf":
            raise ValueError(f"Unsupported export format for a DXF drawing: {fmt}")
        resolved = resolve_dxf_source(file_ref, root_path)
        args = ["--repo-root", root_path, "--source-path", resolved["sourcePath"], "--out", out_path]
        result = run_cadgen("cadgen.dxf_export_target", args, root_path)
    elif path_is_implicit_cad_source(normalized_ref):
        if normalized_format not in _IMPLICIT_EXPORT_FORMATS:
            raise ValueError(f"Unsupported implicit CAD export format: {fmt or '(missing)'}")
        resolved = resolve_implicit_source(file_ref, root_path)
        args = [
            "--repo-root", root_path,
            "--source-path", resolved["sourcePath"],
            "--format", normalized_format,
            "--out", out_path,
        ]
        result = run_cadgen("cadgen.implicit_export", args, root_path)
    else:
        if normalized_format not in _STEP_EXPORT_FORMAT_SUFFIX:
            raise ValueError(f"Unsupported export format: {fmt}")
        resolved = resolve_step_source(file_ref, root_path)
        step_path = resolved["stepPath"]
        if not (step_path == root_path or path_is_inside(step_path, root_path)):
            raise ValueError("Requested file is outside the active CAD Viewer root")
        args = ["--repo-root", root_path, "--step", step_path, "--format", normalized_format, "--out", out_path]
        if resolved["sourcePath"]:
            args += ["--source-path", resolved["sourcePath"]]
        result = run_cadgen("cadgen.step_export_target", args, root_path)
    if not result.get("ok"):
        return {"ok": False, "error": str(result.get("error") or "Export failed")}
    written = os.path.abspath(result.get("path") or out_path)
    return {
        "ok": True,
        "path": written,
        "filename": result.get("filename") or os.path.basename(written),
        "format": normalized_format,
    }


# --- CLI ------------------------------------------------------------------------------
def _emit(payload) -> int:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cadgen.render_ops",
        description="Render-artifact status/build/export ops for the CAD Viewer's JS server",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    for name in ("status", "build", "export"):
        p = sub.add_parser(name)
        p.add_argument("--file", required=True)
        p.add_argument("--root", required=True)
        if name == "build":
            p.add_argument("--force", action="store_true")
        if name == "export":
            p.add_argument("--format", required=True)
            p.add_argument("--out", required=True)
    sub.add_parser("probe")
    args = parser.parse_args(argv)

    if args.op == "probe":
        return _emit(probe_cadgen_runtime(os.getcwd()))
    root_path = os.path.abspath(args.root)
    if not os.path.isdir(root_path):
        return _emit({"ok": False, "state": ARTIFACT_STATE_ERROR, "error": f"root is not a directory: {root_path}"})
    try:
        if args.op == "status":
            return _emit(artifact_status(args.file, root_path))
        if args.op == "build":
            return _emit(resolve_artifact(args.file, root_path, force=bool(args.force)))
        return _emit(generate_export(args.file, root_path, args.format, args.out))
    except ValueError as exc:
        return _emit({"ok": False, "state": ARTIFACT_STATE_ERROR, "error": str(exc)})


if __name__ == "__main__":
    raise SystemExit(main())
