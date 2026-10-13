"""What the ``cadgen.cam`` verbs do, end to end: :func:`list_features` and :func:`plan_job`."""

from __future__ import annotations

from pathlib import Path

from cadgen._internal.cam.checks.base import finding
from cadgen._internal.cam.job_errors import CamJobError
from cadgen.results import CamFeaturesResult

__all__ = ["list_features"]


def job_finding(message: str) -> dict:
    """A job that cannot run, as the one error finding its result carries."""
    return finding("job", "error", "job", message, "the job was refused before anything was planned; nothing was "
                   "written. Change the job (or the --occurrence) as the summary says and plan again")


def list_features(target: Path, *, occurrence: str | None = None) -> CamFeaturesResult:
    from cadgen._internal.cam.features import read_features
    from cadgen._internal.cam.part import read_part

    try:
        part = read_part(Path(target), occurrence=occurrence)
    except CamJobError as exc:
        return CamFeaturesResult(ok=False, document=Path(target), findings=(job_finding(str(exc)),))
    reading = read_features(part)
    low, high = part.bbox
    bbox = {"min": [round(float(v), 4) + 0.0 for v in low], "max": [round(float(v), 4) + 0.0 for v in high],
            "size": [round(float(b - a), 4) + 0.0 for a, b in zip(low, high)]}
    return CamFeaturesResult(ok=True, document=Path(target), occurrence=part.occurrence, bbox_mm=bbox,
                             faces=tuple(reading["faces"]), holes=tuple(reading["holes"]),
                             floors=tuple(reading["floors"]), profiles=tuple(reading["profiles"]))
