"""Complete movement: base (plate/train/escapement/balance) + keyless and
motion works + chronograph works, all authored in the shared MOVEMENT local
frame (see _spec.py), so composition is identity — no re-posing here.
"""

from pathlib import Path

from build123d import Compound

from cadgen.compose import child_entry

_HERE = Path(__file__).resolve().parent

# Composed through cadgen's traced child seam (see moonwatch.step.py): each
# sub-entry is a cached scope keyed by its own source closure.
_BASE = child_entry(_HERE / "movement_base.step.py")
_KEYLESS = child_entry(_HERE / "keyless_works.step.py")
_CHRONO = (
    child_entry(_HERE / "chrono_works.step.py")
    if (_HERE / "chrono_works.step.py").exists()
    else None
)


def gen_step():
    children = []

    base = _BASE.gen_step()
    base.label = "movement_base"
    children.append(base)

    keyless = _KEYLESS.gen_step()
    keyless.label = "keyless_works"
    children.append(keyless)

    if _CHRONO is not None:
        chrono = _CHRONO.gen_step()
        chrono.label = "chronograph_works"
        children.append(chrono)

    return Compound(children=children, label="movement")
