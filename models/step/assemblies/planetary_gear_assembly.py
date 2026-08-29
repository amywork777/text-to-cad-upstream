from __future__ import annotations
from cadgen import step
from math import cos, pi, sin, tau

from cadgen import build123d as bd


# Units: millimeters.
# Origin: sun/ring center on the carrier axis.
# XY: gear plane. +Z: gear and pin axes.

GEAR_THICKNESS = 8.0
GEAR_BOTTOM_Z = 0.0

SUN_TEETH = 24
SUN_PITCH_DIAMETER = 48.0
SUN_ROOT_DIAMETER = 42.0
SUN_OUTSIDE_DIAMETER = 54.0
SUN_BORE_DIAMETER = 10.0

PLANET_TEETH = 18
PLANET_PITCH_DIAMETER = 36.0
PLANET_ROOT_DIAMETER = 31.0
PLANET_OUTSIDE_DIAMETER = 41.0
PLANET_CENTER_RADIUS = 42.0
PLANET_COUNT = 3
PLANET_BORE_DIAMETER = 6.8

EXTERNAL_TOOTH_ROOT_SPAN_FRACTION = 0.42
EXTERNAL_TOOTH_TIP_SPAN_FRACTION = 0.18


def _srgb_channel_to_linear(channel: int) -> float:
    value = channel / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _srgb_color(hex_color: str) -> bd.Color:
    value = hex_color.removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"Expected #rrggbb color, got {hex_color!r}")
    return bd.Color(
        _srgb_channel_to_linear(int(value[0:2], 16)),
        _srgb_channel_to_linear(int(value[2:4], 16)),
        _srgb_channel_to_linear(int(value[4:6], 16)),
        1.0,
    )


# Match the docs app's dark-mode hero render source colors.
PLANET_COLORS = (
    _srgb_color("#61d4f6"),
    _srgb_color("#a6ea90"),
    _srgb_color("#ed9ee5"),
)

RING_TEETH = 60
RING_INTERNAL_PITCH_DIAMETER = 120.0
RING_INTERNAL_ROOT_DIAMETER = 126.0
RING_INTERNAL_TIP_DIAMETER = 115.0
RING_OUTSIDE_DIAMETER = 140.0
RING_TOOTH_ROOT_SPAN_FRACTION = 0.68
RING_TOOTH_TIP_SPAN_FRACTION = 0.34
RING_COLOR = _srgb_color("#c5adef")
SUN_COLOR = _srgb_color("#fdce76")
CARRIER_COLOR = _srgb_color("#bfcec8")
PIN_COLOR = _srgb_color("#818993")

CARRIER_DIAMETER = 105.0
CARRIER_BOTTOM_Z = -5.0
CARRIER_TOP_Z = -1.0
CARRIER_THICKNESS = CARRIER_TOP_Z - CARRIER_BOTTOM_Z

PIN_DIAMETER = 6.0
PIN_HEIGHT = 14.0
PIN_BOTTOM_Z = -5.0
PIN_CARRIER_CLEARANCE_DIAMETER = 6.4


def _polar_point(radius: float, angle: float) -> tuple[float, float]:
    return (radius * cos(angle), radius * sin(angle))


def _trapezoid_tooth_profile(
    *,
    teeth: int,
    root_radius: float,
    tip_radius: float,
    phase: float,
    root_span_fraction: float = 0.72,
    tip_span_fraction: float = 0.38,
) -> list[tuple[float, float]]:
    """Return a closed-profile point loop with straight-sided schematic teeth."""
    pitch_angle = tau / teeth
    points: list[tuple[float, float]] = []

    for tooth_index in range(teeth):
        center_angle = phase + tooth_index * pitch_angle
        points.extend(
            (
                _polar_point(root_radius, center_angle - root_span_fraction * pitch_angle / 2.0),
                _polar_point(tip_radius, center_angle - tip_span_fraction * pitch_angle / 2.0),
                _polar_point(tip_radius, center_angle + tip_span_fraction * pitch_angle / 2.0),
                _polar_point(root_radius, center_angle + root_span_fraction * pitch_angle / 2.0),
            )
        )

    return points


def _make_external_gear(
    *,
    label: str,
    teeth: int,
    root_diameter: float,
    outside_diameter: float,
    phase: float,
    center: tuple[float, float] = (0.0, 0.0),
    bore_diameter: float | None = None,
    color: bd.Color | None = None,
):
    with bd.BuildPart() as gear:
        with bd.BuildSketch(bd.Plane.XY):
            bd.Polygon(
                _trapezoid_tooth_profile(
                    teeth=teeth,
                    root_radius=root_diameter / 2.0,
                    tip_radius=outside_diameter / 2.0,
                    phase=phase,
                    root_span_fraction=EXTERNAL_TOOTH_ROOT_SPAN_FRACTION,
                    tip_span_fraction=EXTERNAL_TOOTH_TIP_SPAN_FRACTION,
                ),
                align=None,
            )
        bd.extrude(amount=GEAR_THICKNESS)

        if bore_diameter is not None:
            with bd.Locations(bd.Location((0.0, 0.0, -0.5))):
                bd.Cylinder(
                    radius=bore_diameter / 2.0,
                    height=GEAR_THICKNESS + 1.0,
                    align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
                    mode=bd.Mode.SUBTRACT,
                )

    part = gear.part.moved(bd.Location((center[0], center[1], GEAR_BOTTOM_Z)))
    part.label = label
    part.color = color
    return part


def _make_internal_ring_gear(*, label: str, phase: float, color: bd.Color | None = None):
    with bd.BuildPart() as ring:
        bd.Cylinder(
            radius=RING_OUTSIDE_DIAMETER / 2.0,
            height=GEAR_THICKNESS,
            align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
        )

        with bd.BuildSketch(bd.Plane.XY):
            bd.Polygon(
                _trapezoid_tooth_profile(
                    teeth=RING_TEETH,
                    root_radius=RING_INTERNAL_ROOT_DIAMETER / 2.0,
                    tip_radius=RING_INTERNAL_TIP_DIAMETER / 2.0,
                    phase=phase,
                    root_span_fraction=RING_TOOTH_ROOT_SPAN_FRACTION,
                    tip_span_fraction=RING_TOOTH_TIP_SPAN_FRACTION,
                ),
                align=None,
            )
        bd.extrude(amount=GEAR_THICKNESS, mode=bd.Mode.SUBTRACT)

    part = ring.part
    part.label = label
    part.color = color
    return part


def _make_carrier_plate():
    with bd.BuildPart() as carrier:
        with bd.Locations(bd.Location((0.0, 0.0, CARRIER_BOTTOM_Z))):
            bd.Cylinder(
                radius=CARRIER_DIAMETER / 2.0,
                height=CARRIER_THICKNESS,
                align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
            )
        for index in range(PLANET_COUNT):
            center = _polar_point(PLANET_CENTER_RADIUS, tau * index / PLANET_COUNT)
            with bd.Locations(bd.Location((center[0], center[1], CARRIER_BOTTOM_Z - 0.1))):
                bd.Cylinder(
                    radius=PIN_CARRIER_CLEARANCE_DIAMETER / 2.0,
                    height=CARRIER_THICKNESS + 0.2,
                    align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
                    mode=bd.Mode.SUBTRACT,
                )

    part = carrier.part
    part.label = "carrier_plate"
    part.color = CARRIER_COLOR
    return part


def _make_planet_pin(*, label: str, center: tuple[float, float]):
    with bd.BuildPart() as pin:
        with bd.Locations(bd.Location((center[0], center[1], PIN_BOTTOM_Z))):
            bd.Cylinder(
                radius=PIN_DIAMETER / 2.0,
                height=PIN_HEIGHT,
                align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
            )

    part = pin.part
    part.label = label
    part.color = PIN_COLOR
    return part


def _planet_center(index: int) -> tuple[float, float]:
    angle = tau * index / PLANET_COUNT
    return _polar_point(PLANET_CENTER_RADIUS, angle)




# ---------------------------------------------------------------------------
# Viewer pose (declarative; design: pose-framework). The kinematics are exact
# fixed-ring planetary ratios expressed as ratio couplings; the orbit-guide
# overlay and the playback-gated meshing pulse live in the escape hatch
# (_pose/planetary_orbit_guide.js). 3.5 sun revolutions (1260 deg) returns the
# carrier to 360 deg and every gear to an equivalent tooth phase.
# ---------------------------------------------------------------------------

from cadgen import pose as _pose

_CARRIER_RATIO = SUN_TEETH / (SUN_TEETH + RING_TEETH)          # 24/84
_PLANET_RATIO = -(SUN_TEETH / PLANET_TEETH) * (1 - _CARRIER_RATIO)
_FULL_MESH_CYCLE_DEG = 1260
_Z = [0, 0, 1]
_PLANET_RADIALS = {
    "planet1": [1.0, 0.0, 0.0],
    "planet2": [-0.5, 0.8660254, 0.0],
    "planet3": [-0.5, -0.8660254, 0.0],
}
_PIN_RADIALS = {"pin1": _PLANET_RADIALS["planet1"], "pin2": _PLANET_RADIALS["planet2"], "pin3": _PLANET_RADIALS["planet3"]}


def _planetary_pose():
    features = {
        "carrier": {"ref": "#o1.1.1", "label": "Carrier plate"},
        "ring": {"ref": "#o1.2.1", "label": "Ring gear"},
        "sun": {"ref": "#o1.3.1", "label": "Sun gear"},
        "planet1": {"ref": "#o1.4.1", "label": "Planet gear 1"},
        "pin1": {"ref": "#o1.5.1", "label": "Planet pin 1"},
        "planet2": {"ref": "#o1.6.1", "label": "Planet gear 2"},
        "pin2": {"ref": "#o1.7.1", "label": "Planet pin 2"},
        "planet3": {"ref": "#o1.8.1", "label": "Planet gear 3"},
        "pin3": {"ref": "#o1.9.1", "label": "Planet pin 3"},
    }
    joints = [
        {"id": "sun_spin", "feature": "sun", "kind": "rotate", "axis": _Z, "origin": [0, 0, 0]},
        {"id": "carrier_rot", "feature": "carrier", "kind": "rotate", "axis": _Z, "origin": [0, 0, 0]},
    ]
    drivers = [
        {"kind": "joint", "joint": "sun_spin", "param": "drive"},
        {"kind": "ratio", "joint": "carrier_rot", "source": "sun_spin", "ratio": _CARRIER_RATIO},
    ]
    for index, (planet, radial) in enumerate(_PLANET_RADIALS.items(), start=1):
        center = [radial[0] * PLANET_CENTER_RADIUS, radial[1] * PLANET_CENTER_RADIUS, 0]
        joints += [
            # Chain (leaf last): spin about own center, radial explode, carrier orbit.
            {"id": f"{planet}_explode", "feature": planet, "kind": "translate", "axis": radial, "parent": "carrier_rot"},
            {"id": f"{planet}_spin", "feature": planet, "kind": "rotate", "axis": _Z, "origin": center, "parent": f"{planet}_explode"},
        ]
        drivers += [
            {"kind": "joint", "joint": f"{planet}_explode", "param": "explode", "scale": 16},
            {"kind": "ratio", "joint": f"{planet}_spin", "source": "sun_spin", "ratio": _PLANET_RATIO},
        ]
    for pin, radial in _PIN_RADIALS.items():
        joints.append({"id": f"{pin}_explode", "feature": pin, "kind": "translate", "axis": radial, "parent": "carrier_rot"})
        drivers.append({"kind": "joint", "joint": f"{pin}_explode", "param": "explode", "scale": 16})
    drivers += [
        # Axial separation rides OUTSIDE the joint chains (world-space lifts).
        {"kind": "translate", "feature": "sun", "param": "explode", "direction": [0, 0, 1], "distance": 7},
        {"kind": "translate", "features": ["carrier", "pin1", "pin2", "pin3"], "param": "explode", "direction": [0, 0, -1], "distance": 4},
        {"kind": "visible", "target": "ring", "param": "ringVisible"},
        {"kind": "style", "target": "ring", "param": "viewMode",
         "palettes": {"cutaway": {"ring": {"opacity": 0.22, "edgeOpacity": 0.38}}}},
        {"kind": "style", "target": "carrier", "param": "viewMode",
         "palettes": {"carrier": {"carrier": {"emissive": "#14532d", "emissiveIntensity": 0.2}}}},
        {"kind": "style", "targets": ["sun", "planet1", "planet2", "planet3"], "param": "highlightMeshing",
         "palettes": {"true": {
             "sun": {"emissive": "#7c2d12", "emissiveIntensity": 0.32},
             "planet1": {"emissive": "#075985", "emissiveIntensity": 0.22},
             "planet2": {"emissive": "#075985", "emissiveIntensity": 0.22},
             "planet3": {"emissive": "#075985", "emissiveIntensity": 0.22},
         }}},
    ]
    return _pose(
        params={
            "drive": {"type": "number", "label": "Drive", "description": "Sun gear input angle across one closed mesh cycle.",
                      "default": 0, "min": 0, "max": _FULL_MESH_CYCLE_DEG, "step": 1, "unit": "deg"},
            "explode": {"type": "number", "label": "Explode", "default": 0, "min": 0, "max": 1, "step": 0.01},
            "ringVisible": {"type": "boolean", "label": "Ring gear", "default": True},
            "orbitGuides": {"type": "boolean", "label": "Orbit guide", "default": False},
            "highlightMeshing": {"type": "boolean", "label": "Mesh highlight", "default": False},
            "viewMode": {"type": "select", "label": "View", "default": "mesh",
                         "options": [{"value": "mesh", "label": "Mesh study"},
                                     {"value": "cutaway", "label": "Cutaway"},
                                     {"value": "carrier", "label": "Carrier focus"}]},
        },
        features=features,
        joints=joints,
        drivers=drivers,
        animations={
            "meshCycle": {"label": "Mesh cycle", "duration": 6, "loop": True, "tracks": [
                {"param": "drive", "keys": [{"t": 0, "value": 0}, {"t": 1, "value": _FULL_MESH_CYCLE_DEG}]},
            ]},
            "inspectExplode": {"label": "Explode inspect", "duration": 5, "loop": True, "tracks": [
                {"param": "drive", "keys": [{"t": 0, "value": 0}, {"t": 1, "value": _FULL_MESH_CYCLE_DEG}]},
                {"param": "explode", "keys": [{"t": 0, "value": 0}, {"t": 0.5, "value": 1, "easing": "sine"}, {"t": 1, "value": 0, "easing": "sine"}]},
            ]},
        },
        module="_pose/planetary_orbit_guide.js",
    )


@step(kind="assembly", pose=_planetary_pose())
def planetary_gear_assembly():
    """Return a labeled simplified planetary gear assembly in millimeters."""
    sun_pitch_angle = tau / SUN_TEETH
    ring_pitch_angle = tau / RING_TEETH

    parts = [
        _make_carrier_plate(),
        _make_internal_ring_gear(
            label="ring_gear_60_internal_teeth",
            phase=-ring_pitch_angle / 2.0,
            color=RING_COLOR,
        ),
        _make_external_gear(
            label="sun_gear_24_teeth",
            teeth=SUN_TEETH,
            root_diameter=SUN_ROOT_DIAMETER,
            outside_diameter=SUN_OUTSIDE_DIAMETER,
            phase=-sun_pitch_angle / 2.0,
            bore_diameter=SUN_BORE_DIAMETER,
            color=SUN_COLOR,
        ),
    ]

    for index in range(PLANET_COUNT):
        planet_angle = tau * index / PLANET_COUNT
        center = _planet_center(index)
        parts.append(
            _make_external_gear(
                label=f"planet_gear_{index + 1}_18_teeth",
                teeth=PLANET_TEETH,
                root_diameter=PLANET_ROOT_DIAMETER,
                outside_diameter=PLANET_OUTSIDE_DIAMETER,
                phase=planet_angle,
                center=center,
                bore_diameter=PLANET_BORE_DIAMETER,
                color=PLANET_COLORS[index],
            )
        )
        parts.append(_make_planet_pin(label=f"planet_pin_{index + 1}", center=center))

    assembly = bd.Compound(
        obj=parts,
        children=parts,
        label="simplified_planetary_gear_assembly",
    )
    return assembly
