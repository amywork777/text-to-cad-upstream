"""Full watch assembly: case + dial/hands + bracelet (+ movement when its
entry lands). Children are generated siblings, path-loaded per the skill's
child-dependency rule; each child already authors its parts in the WATCH
frame (see _spec.py), so placements are identity — except the movement,
which is cased via the documented flip about X + MOVT_Z_OFFSET lift.
"""

from pathlib import Path

from build123d import Color, Compound, Cylinder, Location, Pos

import _materials
import _spec as S
from cadgen.compose import child_entry

_HERE = Path(__file__).resolve().parent

# Composed through cadgen's traced child seam: each child's gen_step() is a
# cached SCOPE keyed by its source closure, so an edit that does not reach a
# child's files skips that child's Python and kernel work entirely. The seam
# owns the child's sys.path context, so sibling-helper imports resolve
# regardless of the working directory.
_CASE = child_entry(_HERE / "case.step.py")
_DIAL = child_entry(_HERE / "dial.step.py")
_BRACELET = child_entry(_HERE / "bracelet.step.py")
_MOVEMENT = child_entry(_HERE / "movement.step.py") if (_HERE / "movement.step.py").exists() else None


def gen_step():
    children = []

    case = _CASE.gen_step()
    case.label = "case"
    children.append(case)

    dial = _DIAL.gen_step()
    dial.label = "dial_and_hands"
    children.append(dial)

    bracelet = _BRACELET.gen_step()
    bracelet.label = "bracelet"
    children.append(bracelet)

    if _MOVEMENT is not None:
        movement = _MOVEMENT.gen_step()
        movement.label = "movement"
        # cased: local (x, y, z) -> watch (x, -y, MOVT_Z_OFFSET - z)
        movement.locate(
            Location((0, 0, S.MOVT_Z_OFFSET), (1, 0, 0), 180) * movement.location
        )
        children.append(movement)

        # movement ring: fills the annulus between the movement OD and the
        # case interior so the caseback window shows metal, not void.
        # align=(None,None,None) leaves the cylinder base at the origin, so
        # Pos sets the ring's bottom; the cut over/under-shoots to avoid
        # coplanar-face booleans. Cased movement spans watch z 0.96..7.7.
        ring = Pos(0, 0, 1.0) * Cylinder(
            15.6, 6.7, align=(None, None, None)
        ) - Pos(0, 0, 0.9) * Cylinder(
            S.MOVEMENT_DIAMETER / 2 + 0.05, 7.0, align=(None, None, None)
        )
        ring.color = Color(*S.STEEL_DARK)
        ring.label = "movement_ring"
        children.append(ring)

    compound = Compound(children=children, label="moonwatch")
    _materials.apply(compound)
    return {"shape": compound, "params": "moonwatch.params.js"}
