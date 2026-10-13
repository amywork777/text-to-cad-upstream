"""The job's teaching errors and the small validators every parser shares (job, tools, operations).

A :class:`CamJobError` is a job that cannot run, said in one plain sentence that names what to add or change and,
for a closed vocabulary, the allowed set (law 9). ``cadgen cam plan`` turns it into ``ok: false`` with one error
finding of type ``job``; nothing is written. Stdlib only.
"""

from __future__ import annotations

import difflib
import math
from collections.abc import Iterable

__all__ = ["CamJobError", "check_keys", "choice", "read_number"]


class CamJobError(ValueError):
    """A job that cannot run: malformed, an unknown key or value, a missing tool, a face that does not exist, an
    operation the machine cannot do. The message is the whole answer."""


def _suggest(value: str, allowed: Iterable[str]) -> str:
    close = difflib.get_close_matches(value, list(allowed), n=1)
    return f" (did you mean '{close[0]}'?)" if close else ""


def check_keys(raw: dict, allowed: Iterable[str], where: str, *, hint: str = "") -> None:
    """Refuse any key outside ``allowed``, naming the allowed set."""
    allowed = tuple(allowed)
    for key in raw:
        if key not in allowed:
            what = f" for {hint}" if hint else ""
            raise CamJobError(f"{where}: unknown key '{key}'{_suggest(str(key), allowed)}; the keys{what} are "
                              f"{', '.join(allowed)}")


def choice(value: object, allowed: Iterable[str], where: str) -> str:
    """``value`` when it is one of ``allowed``, else the teaching error naming them."""
    allowed = tuple(allowed)
    if not isinstance(value, str) or value not in allowed:
        shown = "nothing" if value is None else repr(value) if not isinstance(value, str) else f"'{value}'"
        suggestion = _suggest(value, allowed) if isinstance(value, str) else ""
        raise CamJobError(f"{where} is {shown}{suggestion}; use one of {', '.join(allowed)}")
    return value


def read_number(raw: dict, key: str, where: str, *, default=None, minimum: float | None = None,
                maximum: float | None = None, inclusive: bool = False):
    """``raw[key]`` as a float. Absent: ``default`` as given. Present: a finite number, more than 0 (or at least
    ``minimum`` when one is given), at most ``maximum``."""
    if key not in raw:
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CamJobError(f"{where}.{key} must be a number, not {value!r}")
    value = float(value)
    if minimum is None:
        if value <= 0 and not inclusive:
            raise CamJobError(f"{where}.{key} must be more than 0, not {value:g}")
    elif value < minimum:
        raise CamJobError(f"{where}.{key} must be at least {minimum:g}, not {value:g}")
    if maximum is not None and value > maximum:
        raise CamJobError(f"{where}.{key} must be at most {maximum:g}, not {value:g}")
    return value


def number_list(value: object, where: str, *, length: int | tuple[int, ...], positive: bool = False) -> tuple[float, ...]:
    """A list of ``length`` finite numbers (one of several lengths when a tuple is given)."""
    lengths = (length,) if isinstance(length, int) else length
    if not isinstance(value, (list, tuple)) or len(value) not in lengths or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value):
        raise CamJobError(f"{where} must be a list of {' or '.join(str(n) for n in lengths)} numbers, not {value!r}")
    out = tuple(float(v) for v in value)
    if positive and any(v <= 0 for v in out):
        raise CamJobError(f"{where} must hold numbers more than 0, not {value!r}")
    return out
