"""Grumman F-14D Super Tomcat -- full assembly.

Wings at 20 degrees, canopy closed, gear down, on the deck.  Clean airframe:
empty pylon stations, no external stores.

The airframe skin is ONE lofted solid (``f14_parts/body.py``) built from
full-width blended sections, so the glove flows into the forward fuselage, the
nacelles flow into the pancake tunnel, and the fin roots sit on a continuous
surface.  Nothing in the primary surface is filleted, because nothing there is
joined.

Assembly tree is grouped BY SYSTEM, which is also how the explode parameter
moves things.

OCCURRENCE ORDER IS BY WHAT ACTUALLY BUILDS, not by the SYSTEMS list below.
A system that is missing or that raises is skipped rather than failing the
aircraft, so it takes no occurrence number and everything after it shifts up.
Three of the thirteen produce no group today -- ``glove``, ``engines`` and
``markings`` have no module yet -- so the built aircraft is these ten, and
the pose feature refs are numbered against them:

    o1.1  airframe    the one-piece blended skin, cut and detailed
    o1.2  cockpit     tub, panels, seats, HUD, canopy, windscreen
    o1.3  wings       panels, slats, flaps, spoilers, tip lights
    o1.4  inlets      ramps, splitters, bleed slots, ducts
    o1.5  nozzles     C-D nozzles, petals, seals, actuator rings
    o1.6  empennage   fins, rudders, stabilators, ventral fins
    o1.7  aft         speed brakes, beavertail, tailhook, dump mast
    o1.8  nose_gear   leg, wheels, launch bar, doors, bay
    o1.9  main_gear   legs, wheels, brakes, doors, bays
    o1.10 details     antennas, probes, lights, wicks, vents, panels

    (no group: glove, engines, markings -- no module)

Adding any missing module RENUMBERS every occurrence after it, so
``f14d.params.js`` has to be renumbered in the same commit.  ``nozzles`` is the
worked example: it silently dropped out of the aircraft for a while because its
revolve raised ``TopoDS::Solid``, and restoring it moved five systems by one.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build123d import Compound

from cadgen import step, track

# Order here IS the occurrence order (o1.1, o1.2, ...).
SYSTEMS = [
    "airframe",
    "cockpit",
    "glove",
    "wings",
    "inlets",
    "engines",
    "nozzles",
    "empennage",
    "aft",
    "nose_gear",
    "main_gear",
    "details",
    "markings",
]


def _load(name):
    """Import a part module at MODULE IMPORT time, not inside gen_step().

    The CAD CLI restores sys.path after loading the generator, so an
    ``f14_parts.*`` import attempted inside gen_step() would fail to resolve.
    Missing or still-broken modules are skipped with a note rather than failing
    the whole aircraft, so the assembly stays renderable while individual part
    builders are still iterating.
    """
    try:
        return __import__(f"f14_parts.{name}", fromlist=["build"])
    except ModuleNotFoundError as exc:
        if name not in str(exc):
            print(f"[f14d] skip {name}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"[f14d] skip {name}: import failed: {exc}", file=sys.stderr)
        return None


_MODULES = [(name, _load(name)) for name in SYSTEMS]

# ---------------------------------------------------------------------------
# Cosmetic skin cutters are DROPPED.  Measured against this skin, subtracting
# the 41 shallow panel recesses published by `details` and `aft` did not finish
# in 15 minutes, and a full 44-cutter build ran over seven hours without
# completing; the 3 structural cutters (diverter slot, cockpit opening) cost
# 348 s and are kept.  The skin is one B-spline surface of ~4,900 control
# points, so every boolean tool forces a full-surface classification -- the cost
# is per-tool, not per-unit-of-material-removed.
#
# Nothing visual is lost.  At 19 m rendered to 1920 px, 1 px is about 10 mm, so
# a 4 mm groove is sub-pixel: panel lines read because the renderer's edge
# overlay draws feature edges, not because the groove is resolvable.
# ---------------------------------------------------------------------------
COSMETIC_CUTTER_MODULES = ("details", "aft")

for _name in COSMETIC_CUTTER_MODULES:
    _mod = sys.modules.get(f"f14_parts.{_name}")
    if _mod is not None and getattr(_mod, "SKIN_CUTTERS", None):
        print(f"[f14d] dropping {len(_mod.SKIN_CUTTERS)} cosmetic skin cutters "
              f"from {_name}", file=sys.stderr)
        _mod.SKIN_CUTTERS = []




# ---------------------------------------------------------------------------
# Exploded view (declarative pose; design: pose-framework).
#
# Two acts on ONE parameter: act 1 separates the ten systems, act 2 breaks the
# wings and aft section into their own parts; every stage is a window on the
# master ramp with a smoothstep ease, so the eye gets a sequence instead of a
# single pop. Windows below are precomposed onto the master `exploded` ramp
# (act 1 spans [0, 0.58], act 2 [0.52, 1] — they overlap on purpose).
#
# Deliberate simplifications vs the retired sidecar: the `skin_fade` toggle and
# the demo_mode/demo_phase scrub params are gone — the skin fade is always on
# (it is what keeps the internals readable) and animation scrubbing is a
# viewer affordance now, not a parameter.
#
# The o1.N refs are BY CHILD ORDER of what gen_step actually built (three of
# the thirteen SYSTEMS have no module and take no number) — adding any of the
# missing modules renumbers everything after it, and this block must be
# renumbered in the same commit.
# ---------------------------------------------------------------------------

from cadgen import pose as _pose  # noqa: E402  (light import; no kernel)

_ACT1_END = 0.58
_ACT2_START = 0.52

# system: (stage window within act 1, explode vector in mm)
_SYSTEMS_EXPLODE = {
    "airframe": ([0.00, 0.55], [-1400, 0, 5200]),
    "cockpit": ([0.10, 0.62], [-500, 0, 2500]),
    "wings": ([0.16, 0.68], [200, 0, 3300]),
    "empennage": ([0.22, 0.74], [1900, 0, 2700]),
    "nozzles": ([0.26, 0.78], [4400, 0, 300]),
    "aft": ([0.32, 0.84], [2700, 0, -600]),
    "inlets": ([0.38, 0.88], [-1000, 0, -2500]),
    "main_gear": ([0.44, 0.92], [200, 0, -2300]),
    "nose_gear": ([0.48, 0.96], [-1900, 0, -1700]),
    "details": ([0.52, 1.00], [0, 0, 1500]),
}
# subassembly: (stage window within act 2, ADDITIVE explode vector — child
# transforms compose with their group's, so these ride on the act-1 travel)
_SUBS_EXPLODE = {
    "spoilers": ([0.00, 0.42], [0, 0, 1100]),
    "slats": ([0.08, 0.52], [-1300, 0, 250]),
    "flaps": ([0.14, 0.58], [1500, 0, -450]),
    "tip_port": ([0.24, 0.66], [0, 1500, 250]),
    "tip_stbd": ([0.24, 0.66], [0, -1500, 250]),
    "sb_dorsal": ([0.30, 0.72], [200, 0, 1500]),
    "sb_ventral_port": ([0.38, 0.80], [200, 1100, -1200]),
    "sb_ventral_stbd": ([0.38, 0.80], [200, -1100, -1200]),
    "beavertail": ([0.48, 0.88], [1600, 0, 0]),
    "tailhook": ([0.56, 1.00], [800, 0, -1400]),
}
_FEATURE_REFS = {
    "airframe": ("#o1.1", "Airframe skin (one blended loft)"),
    "cockpit": ("#o1.2", "Cockpit — tub, seats, panels, canopy"),
    "wings": ("#o1.3", "Wings — panels, slats, flaps, spoilers"),
    "inlets": ("#o1.4", "Inlets — ramps, splitters, ducts"),
    "nozzles": ("#o1.5", "Nozzles — C-D petals, seals, actuators"),
    "empennage": ("#o1.6", "Empennage — fins, rudders, stabilators"),
    "aft": ("#o1.7", "Aft — speed brakes, beavertail, hook"),
    "nose_gear": ("#o1.8", "Nose gear — leg, wheels, launch bar"),
    "main_gear": ("#o1.9", "Main gear — legs, wheels, doors, bays"),
    "details": ("#o1.10", "Details — antennas, probes, lights, vents"),
    # Act-2 leaf lists are GENERATED (render/subrefs.py) — do not hand-edit.
    "slats": ("#o1.3.1.3,o1.3.1.4,o1.3.1.5,o1.3.1.6,o1.3.1.7,o1.3.1.8,o1.3.1.9,o1.3.1.10,o1.3.1.11,o1.3.1.12,o1.3.1.13,o1.3.1.14,o1.3.1.15,o1.3.2.3,o1.3.2.4,o1.3.2.5,o1.3.2.6,o1.3.2.7,o1.3.2.8,o1.3.2.9,o1.3.2.10,o1.3.2.11,o1.3.2.12,o1.3.2.13,o1.3.2.14,o1.3.2.15", "Wing slats + tracks"),
    "flaps": ("#o1.3.1.16,o1.3.1.17,o1.3.1.18,o1.3.1.19,o1.3.1.20,o1.3.2.16,o1.3.2.17,o1.3.2.18,o1.3.2.19,o1.3.2.20", "Wing flaps + track fairings"),
    "spoilers": ("#o1.3.1.21,o1.3.1.22,o1.3.1.23,o1.3.1.24,o1.3.2.21,o1.3.2.22,o1.3.2.23,o1.3.2.24", "Wing spoilers"),
    "tip_port": ("#o1.3.1.25,o1.3.1.26,o1.3.1.27", "Wingtip light housing (port)"),
    "tip_stbd": ("#o1.3.2.25,o1.3.2.26,o1.3.2.27", "Wingtip light housing (stbd)"),
    "sb_dorsal": ("#o1.7.1,o1.7.2,o1.7.3,o1.7.4,o1.7.5,o1.7.6,o1.7.7,o1.7.8,o1.7.9,o1.7.10,o1.7.11,o1.7.12,o1.7.13,o1.7.14", "Dorsal speed brake"),
    "sb_ventral_port": ("#o1.7.15,o1.7.16,o1.7.17,o1.7.18,o1.7.19,o1.7.20,o1.7.21,o1.7.22,o1.7.23,o1.7.24,o1.7.25,o1.7.26,o1.7.27,o1.7.28", "Ventral speed brake (port)"),
    "sb_ventral_stbd": ("#o1.7.29,o1.7.30,o1.7.31,o1.7.32,o1.7.33,o1.7.34,o1.7.35,o1.7.36,o1.7.37,o1.7.38,o1.7.39,o1.7.40,o1.7.41,o1.7.42", "Ventral speed brake (stbd)"),
    "beavertail": ("#o1.7.52,o1.7.53", "Beavertail access panels"),
    "tailhook": ("#o1.7.54,o1.7.55,o1.7.56,o1.7.57,o1.7.58,o1.7.59,o1.7.60,o1.7.61,o1.7.62,o1.7.63,o1.7.64,o1.7.65", "Tailhook + bay doors"),
}


def _explode_drivers() -> list:
    drivers = []
    for name, (stage, vector) in _SYSTEMS_EXPLODE.items():
        window = [stage[0] * _ACT1_END, stage[1] * _ACT1_END]
        magnitude = sum(c * c for c in vector) ** 0.5
        drivers.append({"kind": "translate", "feature": name, "param": "exploded",
                        "direction": vector, "distance": magnitude,
                        "window": window, "easing": "smoothstep"})
    act2_span = 1 - _ACT2_START
    for name, (stage, vector) in _SUBS_EXPLODE.items():
        window = [_ACT2_START + stage[0] * act2_span, _ACT2_START + stage[1] * act2_span]
        magnitude = sum(c * c for c in vector) ** 0.5
        drivers.append({"kind": "translate", "feature": name, "param": "exploded",
                        "direction": vector, "distance": magnitude,
                        "window": window, "easing": "smoothstep"})
    # The skin reaches minimum opacity well before it finishes travelling, so
    # the internals are readable while it is still clearing them; edges stay a
    # little more present than the surface.
    drivers.append({"kind": "style", "target": "airframe", "param": "exploded",
                    "window": [0, 0.45], "easing": "smoothstep",
                    "style": {"opacity": {"from": 1, "to": 0.22},
                              "edgeOpacity": {"from": 1, "to": 0.52}}})
    return drivers


POSE = _pose(
    params={
        "exploded": {
            "type": "number", "label": "Exploded view", "default": 0,
            "min": 0, "max": 1, "step": 0.005,
            "description": "Staged separation of all ten systems. The skin fades "
                           "as it lifts so the internals stay visible underneath it.",
        },
    },
    features={
        name: {"ref": ref, "label": label} for name, (ref, label) in _FEATURE_REFS.items()
    },
    drivers=_explode_drivers(),
    animations={
        "teardown": {
            "label": "Staged teardown",
            "description": "Out and back: apart system by system, hold, reassemble.",
            # 60 s: a published frame of this 2,392-record assembly costs far
            # more than a display frame, so the clip is stretched to keep the
            # per-frame delta small at the paced-down playback rate.
            "duration": 60, "loop": True,
            "tracks": [{"param": "exploded", "keys": [
                {"t": 0, "value": 0},
                {"t": 0.5, "value": 1, "easing": "sine"},
                {"t": 1, "value": 0, "easing": "sine"},
            ]}],
        },
    },
)


@step(kind="assembly", pose=POSE)
def f14d():
    # Report the walk through the systems. This phase is ~85% of the build (10 minutes of a
    # 12-minute run, measured), and without this it is the one stretch that says nothing at
    # all -- the viewer and the CLI both sat on "Building geometry" for its whole duration.
    #
    # The systems are counted AFTER dropping the ones that failed to import, so the
    # denominator is work that will actually run. Note the units are nowhere near equal:
    # `airframe` alone is over half the phase (see the cutter note above), so 1/13 sits for
    # minutes and the tail ticks past quickly. The count is true, not linear.
    buildable = [(name, module) for name, module in _MODULES if module is not None]
    groups = []
    for name, module in track(buildable, label=lambda entry: entry[0]):
        try:
            groups.append(module.build())
        except Exception as exc:  # noqa: BLE001
            print(f"[f14d] skip {name}: build failed: {exc}", file=sys.stderr)
    if not groups:
        raise RuntimeError("no F-14 part modules built")
    return Compound(children=groups, label="f14d_super_tomcat")
