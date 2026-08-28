from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cadgen._internal.assembly_spec import find_step_path, resolve_cad_source_path
from cadgen.cad_ref_syntax import normalize_cad_path, parse_cad_tokens
from cadgen.catalog import find_source_by_cad_ref
from cadgen.selector_types import SelectorBundle


STEP_SUFFIXES = (".step", ".stp")
REGENERATE_STEP_COMMAND = "python scripts/gen"
REGENERATE_STEP_PROMPT = "Regenerate STEP artifacts with the following command using the CAD skill:"


class CadRefError(RuntimeError):
    pass


@dataclass(frozen=True)
class EntryTarget:
    cad_path: str
    selectors: tuple[str, ...] = ()

    @property
    def token(self) -> str:
        from cadgen.cad_ref_syntax import build_cad_token

        if not self.selectors:
            return build_cad_token(self.cad_path)
        return build_cad_token(self.cad_path, ",".join(self.selectors))


@dataclass(frozen=True)
class ResolvedStepTarget:
    cad_path: str
    kind: str
    source_path: Path
    step_path: Path
    # True when the caller explicitly targeted the Python generator (a `.py`
    # path), as opposed to a `.step`/`.stp` file or a logical cad path. An
    # explicit generator target must keep resolving to the generator entry even
    # when a same-stem exported `.step` file exists beside it.
    explicit_python: bool = False


@dataclass(frozen=True)
class StepTopologyArtifact:
    cad_path: str
    kind: str
    source_path: Path
    step_path: Path
    artifact_path: Path
    manifest: dict[str, object]
    selector_bundle: SelectorBundle | None = None


class StepTopologyArtifactError(CadRefError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        cad_path: str,
        step_path: Path,
        artifact_path: Path,
        regenerate_command: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.cad_path = cad_path
        self.step_path = step_path
        self.artifact_path = artifact_path
        self.regenerate_command = regenerate_command

    def to_error(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "cadPath": self.cad_path,
            "stepPath": _display_path(self.step_path),
            "packagePath": _display_path(self.artifact_path),
            "regenerateCommand": self.regenerate_command,
        }


def cad_ref_error_payload(exc: CadRefError) -> dict[str, object]:
    if isinstance(exc, StepTopologyArtifactError):
        return exc.to_error()
    return {"message": str(exc)}


def cad_path_from_target(target: str) -> str:
    return entry_target_from_target(target).cad_path


def entry_target_from_target(target: str) -> EntryTarget:
    parsed_tokens = parse_cad_tokens(target)
    if parsed_tokens:
        raise CadRefError("Selector refs require an explicit STEP target argument.")
    raw_target = str(target or "").strip()
    raw_file = _raw_step_path(raw_target)
    if raw_file is not None:
        try:
            label_source = raw_file.relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            # existing STEP file outside the cwd: keep it addressable, label by name
            label_source = raw_file.name
        normalized = normalize_cad_path(label_source)
        if normalized is not None:
            return EntryTarget(normalized)
    normalized = normalize_cad_path(_cwd_relative_target(raw_target))
    if normalized is None:
        raise CadRefError(f"Invalid CAD entry target: {target}")
    return EntryTarget(normalized)


def _cwd_relative_target(raw_target: str) -> str:
    """Map an absolute filesystem target into the cwd-relative cad-path namespace.

    Logical cad paths are cwd-relative; silently stripping the leading '/' from
    an absolute path used to produce a bogus relative path ("Users/...") that
    could never resolve. Relativize against the command cwd instead, and fail
    loudly when the target lives outside it.
    """
    if not raw_target:
        return raw_target
    path = Path(raw_target).expanduser()
    # ROOTED, not is_absolute(). On Windows a path with a root and no drive ("/models/x") is
    # drive-RELATIVE, so is_absolute() is False and the guard below never ran -- the target
    # fell through and became the bogus cwd-relative cad path this function exists to prevent,
    # which is the POSIX bug it was written for, still live on the other platform. resolve()
    # anchors such a path to the current drive, which is what it means there, and the
    # relative_to() check then answers correctly for it.
    if not (path.is_absolute() or path.root):
        return raw_target
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        raise CadRefError(
            f"Absolute CAD target '{raw_target}' is outside the command cwd "
            f"'{Path.cwd().resolve()}'. Run the command from the workspace that "
            "owns the artifact, or pass a cwd-relative target path."
        ) from None


def step_path_from_target(target: str) -> Path:
    raw_step_path = _raw_step_path(str(target or "").strip())
    if raw_step_path is not None:
        return raw_step_path

    entry_target = entry_target_from_target(target)
    lookup_cad_path = _lookup_cad_path(entry_target.cad_path)
    step_path = find_step_path(lookup_cad_path)
    if step_path is not None:
        return step_path

    direct_step_path = _direct_step_path(entry_target.cad_path)
    if direct_step_path is not None:
        return direct_step_path

    raise CadRefError(f"STEP file not found for target '{target}'.")


def resolve_step_target(target: str) -> ResolvedStepTarget:
    entry_target = entry_target_from_target(target)
    cad_path = entry_target.cad_path
    explicit_python = str(target or "").strip().lower().endswith(".py")
    raw_step_path = _raw_step_path(str(target or "").strip())
    if raw_step_path is not None:
        lookup_cad_path = _lookup_cad_path(cad_path)
        source = find_source_by_cad_ref(lookup_cad_path)
        resolved_step_path = source.step_path if source is not None else None
        if source is not None and resolved_step_path is not None and resolved_step_path.resolve() == raw_step_path.resolve():
            return ResolvedStepTarget(
                cad_path=cad_path,
                kind=source.kind,
                source_path=source.source_path,
                step_path=raw_step_path,
            )
        return ResolvedStepTarget(
            cad_path=cad_path,
            kind="part",
            source_path=raw_step_path,
            step_path=raw_step_path,
        )

    lookup_cad_path = _lookup_cad_path(cad_path)
    source = find_source_by_cad_ref(lookup_cad_path)
    if source is not None and source.kind in {"part", "assembly"}:
        if source.step_path is None:
            raise CadRefError(f"STEP file not found for ref '{cad_path}'.")
        return ResolvedStepTarget(
            cad_path=cad_path,
            kind=source.kind,
            source_path=source.source_path,
            step_path=source.step_path.resolve(),
            explicit_python=explicit_python,
        )
    if source is not None:
        raise CadRefError(f"CAD target '{cad_path}' is not STEP-backed.")

    direct_step_path = _direct_step_path(cad_path)
    if direct_step_path is not None:
        return ResolvedStepTarget(
            cad_path=cad_path,
            kind="part",
            source_path=direct_step_path,
            step_path=direct_step_path,
        )

    raise CadRefError(f"CAD STEP ref not found for '{cad_path}'.")


def _direct_step_path(cad_path: str) -> Path | None:
    for suffix in STEP_SUFFIXES:
        candidate = (Path.cwd().resolve() / f"{cad_path}{suffix}").resolve()
        if candidate.is_file():
            return candidate
    return None


def _raw_step_path(target: str) -> Path | None:
    if not target:
        return None
    path = Path(target).expanduser()
    if path.suffix.lower() not in STEP_SUFFIXES:
        return None
    resolved = path.resolve() if path.is_absolute() else (Path.cwd().resolve() / path).resolve()
    return resolved if resolved.is_file() else None


def _cad_path_lookup_candidates(cad_path: str) -> tuple[str, ...]:
    return (cad_path,) if cad_path else ()


def _lookup_cad_path(cad_path: str) -> str:
    for candidate in _cad_path_lookup_candidates(cad_path):
        if resolve_cad_source_path(candidate) is not None:
            return candidate
    return cad_path


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()
