"""Declarative pose authoring: ``@step(pose=cadgen.pose(...))``.

The ONE way a model declares view/pose parameters, kinematics, and animations
(design: pose-framework). The block is validated here at decoration time, is
serialized into the render package descriptor (``assembly.json`` → ``pose``)
at build time, and is executed by the generic articulation runtime in cadjs —
no per-model JavaScript. Genuinely computational behavior (IK solvers, scene
overlays) goes in the optional ``module=`` escape hatch: a JS file beside the
model source, copied content-addressed into the package at build.

The vocabulary is deliberately CLOSED. Every driver kind below was derived
from the real sidecar corpus; anything else belongs in the escape hatch, not
in a new kind. Unknown kinds and unknown fields are hard errors so a typo can
never silently do nothing.

This module must import light (no OCP): it runs at decoration time in the
~0.2s pre-gate window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = ["pose", "PoseDef", "POSE_SCHEMA_VERSION"]

POSE_SCHEMA_VERSION = 1

_PARAM_TYPES = {"number", "boolean", "enum", "select", "color", "string", "button"}
_PARAM_FIELDS = {
    "type", "label", "description", "unit", "min", "max", "step", "default", "options",
}
_FEATURE_FIELDS = {"ref", "names", "label", "description", "axis", "origin", "partIds"}
_JOINT_FIELDS = {"id", "feature", "kind", "axis", "origin", "parent"}
_JOINT_KINDS = {"rotate", "translate"}
_EASINGS = {"linear", "smoothstep", "sine", "easeIn", "easeOut", "easeInOut"}

_DRIVER_FIELDS: dict[str, set[str]] = {
    "joint": {"kind", "joint", "param", "scale", "offset", "window", "easing"},
    "ratio": {"kind", "joint", "source", "ratio", "offset"},
    "translate": {
        "kind", "feature", "features", "param", "direction", "distance", "window", "easing",
    },
    "visible": {"kind", "target", "targets", "param", "value", "invert"},
    "style": {"kind", "target", "targets", "param", "style", "palettes", "window", "easing"},
    "scale": {"kind", "target", "param", "from", "to", "origin", "window", "easing"},
}


def _fail(message: str) -> None:
    raise ValueError(f"pose: {message}")


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{what} must be a dict, got {type(value).__name__}")
    return value


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{what} must be a number, got {value!r}")
    return float(value)


def _vector3(value: Any, what: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        _fail(f"{what} must be a 3-vector [x, y, z], got {value!r}")
    return [_number(component, what) for component in value]


def _identifier(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        _fail(f"{what} must be a non-empty string")
    return text


def _check_fields(raw: Mapping[str, Any], allowed: set[str], what: str) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        _fail(
            f"{what} has unknown field(s): {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(allowed))})"
        )


def _normalize_window_easing(raw: Mapping[str, Any], what: str, out: dict[str, Any]) -> None:
    if "window" in raw and raw["window"] is not None:
        window = raw["window"]
        if not isinstance(window, Sequence) or len(window) != 2:
            _fail(f"{what} window must be [start, end]")
        start, end = (_number(window[0], f"{what} window"), _number(window[1], f"{what} window"))
        if not end > start:
            _fail(f"{what} window must have end > start, got [{start}, {end}]")
        out["window"] = [start, end]
    if "easing" in raw and raw["easing"] is not None:
        easing = str(raw["easing"])
        if easing not in _EASINGS:
            _fail(f"{what} easing {easing!r} is not one of {', '.join(sorted(_EASINGS))}")
        out["easing"] = easing


def _normalize_params(raw: Any) -> dict[str, dict[str, Any]]:
    params: dict[str, dict[str, Any]] = {}
    for param_id, raw_def in _require_mapping(raw or {}, "params").items():
        identifier = _identifier(param_id, "param id")
        definition = dict(_require_mapping(raw_def, f"param {identifier!r}"))
        _check_fields(definition, _PARAM_FIELDS, f"param {identifier!r}")
        param_type = str(definition.get("type", "number"))
        if param_type not in _PARAM_TYPES:
            _fail(f"param {identifier!r} type {param_type!r} is not one of {', '.join(sorted(_PARAM_TYPES))}")
        if param_type == "select":
            param_type = "enum"
        definition["type"] = param_type
        if param_type == "enum":
            options = definition.get("options")
            if not isinstance(options, Sequence) or not options:
                _fail(f"param {identifier!r} is an enum and must declare non-empty options")
        params[identifier] = definition
    return params


def _normalize_features(raw: Any) -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}
    for feature_id, raw_def in _require_mapping(raw or {}, "features").items():
        identifier = _identifier(feature_id, "feature id")
        definition = dict(_require_mapping(raw_def, f"feature {identifier!r}"))
        _check_fields(definition, _FEATURE_FIELDS, f"feature {identifier!r}")
        names = definition.get("names")
        if isinstance(names, str):
            definition["names"] = [names]
        if not definition.get("ref") and not definition.get("names"):
            _fail(f"feature {identifier!r} must declare 'ref' and/or 'names' to bind occurrences")
        if "axis" in definition and definition["axis"] is not None:
            definition["axis"] = _vector3(definition["axis"], f"feature {identifier!r} axis")
        if "origin" in definition and definition["origin"] is not None:
            definition["origin"] = _vector3(definition["origin"], f"feature {identifier!r} origin")
        features[identifier] = definition
    return features


def _normalize_joints(raw: Any, features: Mapping[str, Any]) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        _fail("joints must be a list (declaration order is evaluation order)")
    joints: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    joint_features: set[str] = set()
    for index, raw_joint in enumerate(raw):
        what = f"joints[{index}]"
        joint = dict(_require_mapping(raw_joint, what))
        _check_fields(joint, _JOINT_FIELDS, what)
        joint_id = _identifier(joint.get("id"), f"{what} id")
        if joint_id in seen_ids:
            _fail(f"duplicate joint id {joint_id!r}")
        seen_ids.add(joint_id)
        feature = _identifier(joint.get("feature"), f"joint {joint_id!r} feature")
        if feature not in features:
            _fail(f"joint {joint_id!r} references unknown feature {feature!r}")
        if feature in joint_features:
            _fail(f"feature {feature!r} has more than one joint; one joint per feature")
        joint_features.add(feature)
        kind = str(joint.get("kind", "rotate"))
        if kind not in _JOINT_KINDS:
            _fail(f"joint {joint_id!r} kind {kind!r} is not one of {', '.join(sorted(_JOINT_KINDS))}")
        normalized: dict[str, Any] = {
            "id": joint_id,
            "feature": feature,
            "kind": kind,
            "axis": _vector3(joint.get("axis", [0, 0, 1]), f"joint {joint_id!r} axis"),
        }
        if joint.get("origin") is not None:
            normalized["origin"] = _vector3(joint["origin"], f"joint {joint_id!r} origin")
        parent = joint.get("parent")
        if parent is not None:
            parent_id = _identifier(parent, f"joint {joint_id!r} parent")
            if parent_id not in seen_ids:
                _fail(
                    f"joint {joint_id!r} parent {parent_id!r} must be declared earlier "
                    "(declaration order is evaluation order)"
                )
            normalized["parent"] = parent_id
        joints.append(normalized)
    return joints


def _feature_targets(raw: Mapping[str, Any], what: str, features: Mapping[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in ("feature", "features", "target", "targets"):
        value = raw.get(key)
        if value is None:
            continue
        for item in [value] if isinstance(value, str) else list(value):
            targets.append(_identifier(item, f"{what} {key}"))
    if not targets:
        _fail(f"{what} must name a target feature")
    for target in targets:
        # "*" targets every part; a "#..." ref string targets directly. Anything
        # else must be a declared feature so typos fail at decoration time.
        if target != "*" and not target.startswith("#") and target not in features:
            _fail(f"{what} targets unknown feature {target!r}")
    return targets


def _require_param(raw: Mapping[str, Any], what: str, params: Mapping[str, Any]) -> str:
    param = _identifier(raw.get("param"), f"{what} param")
    if param not in params:
        _fail(f"{what} references unknown param {param!r}")
    return param


def _normalize_style_values(raw: Any, what: str) -> dict[str, Any]:
    style = dict(_require_mapping(raw, what))
    for prop, value in style.items():
        if isinstance(value, Mapping):
            unknown = sorted(set(value) - {"from", "to"})
            if unknown:
                _fail(f"{what} {prop} range supports only from/to, got {', '.join(unknown)}")
            style[prop] = {
                "from": _number(value.get("from", 0), f"{what} {prop}.from"),
                "to": _number(value.get("to", 0), f"{what} {prop}.to"),
            }
    return style


def _normalize_drivers(
    raw: Any,
    *,
    params: Mapping[str, Any],
    features: Mapping[str, Any],
    joints: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if raw is None:
        return []
    joint_ids = [joint["id"] for joint in joints]
    driven: set[str] = set()
    drivers: list[dict[str, Any]] = []
    for index, raw_driver in enumerate(raw):
        what = f"drivers[{index}]"
        driver = dict(_require_mapping(raw_driver, what))
        kind = str(driver.get("kind", "")).strip()
        if kind not in _DRIVER_FIELDS:
            _fail(
                f"{what} kind {kind!r} is not in the closed vocabulary "
                f"({', '.join(sorted(_DRIVER_FIELDS))}); computational behavior "
                "belongs in the module= escape hatch"
            )
        _check_fields(driver, _DRIVER_FIELDS[kind], f"{what} ({kind})")
        normalized: dict[str, Any] = {"kind": kind}
        if kind == "joint":
            joint_id = _identifier(driver.get("joint"), f"{what} joint")
            if joint_id not in joint_ids:
                _fail(f"{what} references unknown joint {joint_id!r}")
            if joint_id in driven:
                _fail(f"joint {joint_id!r} is driven more than once")
            driven.add(joint_id)
            normalized["joint"] = joint_id
            normalized["param"] = _require_param(driver, what, params)
            normalized["scale"] = _number(driver.get("scale", 1.0), f"{what} scale")
            normalized["offset"] = _number(driver.get("offset", 0.0), f"{what} offset")
            _normalize_window_easing(driver, what, normalized)
        elif kind == "ratio":
            joint_id = _identifier(driver.get("joint"), f"{what} joint")
            source_id = _identifier(driver.get("source"), f"{what} source")
            if joint_id not in joint_ids:
                _fail(f"{what} references unknown joint {joint_id!r}")
            if source_id not in joint_ids:
                _fail(f"{what} references unknown source joint {source_id!r}")
            if joint_ids.index(source_id) >= joint_ids.index(joint_id):
                _fail(
                    f"{what} source {source_id!r} must be declared before joint "
                    f"{joint_id!r} (joints evaluate in declaration order)"
                )
            if joint_id in driven:
                _fail(f"joint {joint_id!r} is driven more than once")
            driven.add(joint_id)
            normalized["joint"] = joint_id
            normalized["source"] = source_id
            normalized["ratio"] = _number(driver.get("ratio", 1.0), f"{what} ratio")
            normalized["offset"] = _number(driver.get("offset", 0.0), f"{what} offset")
        elif kind == "translate":
            normalized["features"] = _feature_targets(driver, what, features)
            normalized["param"] = _require_param(driver, what, params)
            direction = driver.get("direction", "radial")
            if isinstance(direction, str):
                if direction != "radial":
                    _fail(f"{what} direction must be a 3-vector or 'radial', got {direction!r}")
                normalized["direction"] = "radial"
            else:
                normalized["direction"] = _vector3(direction, f"{what} direction")
            normalized["distance"] = _number(driver.get("distance", 1.0), f"{what} distance")
            _normalize_window_easing(driver, what, normalized)
        elif kind == "visible":
            normalized["targets"] = _feature_targets(driver, what, features)
            normalized["param"] = _require_param(driver, what, params)
            if "value" in driver and driver["value"] is not None:
                normalized["value"] = driver["value"]
            if driver.get("invert"):
                normalized["invert"] = True
        elif kind == "style":
            normalized["targets"] = _feature_targets(driver, what, features)
            has_style = driver.get("style") is not None
            has_palettes = driver.get("palettes") is not None
            if has_style == has_palettes:
                _fail(f"{what} must declare exactly one of 'style' or 'palettes'")
            if has_style:
                normalized["style"] = _normalize_style_values(driver["style"], f"{what} style")
                ranged = any(isinstance(v, Mapping) for v in normalized["style"].values())
                if "param" in driver and driver["param"] is not None:
                    normalized["param"] = _require_param(driver, what, params)
                elif ranged:
                    _fail(f"{what} has from/to style ranges and therefore needs a param")
                _normalize_window_easing(driver, what, normalized)
            else:
                normalized["param"] = _require_param(driver, what, params)
                palettes = _require_mapping(driver["palettes"], f"{what} palettes")
                normalized["palettes"] = {
                    str(option): {
                        _identifier(target, f"{what} palette target"): _normalize_style_values(
                            styles, f"{what} palettes[{option}]"
                        )
                        for target, styles in _require_mapping(
                            palette, f"{what} palettes[{option}]"
                        ).items()
                    }
                    for option, palette in palettes.items()
                }
        elif kind == "scale":
            normalized["targets"] = _feature_targets(driver, what, features)
            normalized["param"] = _require_param(driver, what, params)
            normalized["from"] = _number(driver.get("from", 1.0), f"{what} from")
            normalized["to"] = _number(driver.get("to", 1.0), f"{what} to")
            if driver.get("origin") is not None:
                normalized["origin"] = _vector3(driver["origin"], f"{what} origin")
            _normalize_window_easing(driver, what, normalized)
        drivers.append(normalized)
    return drivers


def _normalize_animations(raw: Any, params: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    animations: dict[str, dict[str, Any]] = {}
    for animation_id, raw_def in _require_mapping(raw or {}, "animations").items():
        identifier = _identifier(animation_id, "animation id")
        what = f"animation {identifier!r}"
        definition = dict(_require_mapping(raw_def, what))
        _check_fields(definition, {"label", "description", "duration", "loop", "tracks"}, what)
        duration = _number(definition.get("duration", 1.0), f"{what} duration")
        if duration <= 0:
            _fail(f"{what} duration must be > 0")
        tracks_raw = definition.get("tracks")
        if not isinstance(tracks_raw, Sequence) or not tracks_raw:
            _fail(f"{what} must declare a non-empty tracks list")
        tracks: list[dict[str, Any]] = []
        for track_index, raw_track in enumerate(tracks_raw):
            track_what = f"{what} tracks[{track_index}]"
            track = dict(_require_mapping(raw_track, track_what))
            _check_fields(track, {"param", "keys"}, track_what)
            param = _require_param(track, track_what, params)
            keys_raw = track.get("keys")
            if not isinstance(keys_raw, Sequence) or not keys_raw:
                _fail(f"{track_what} must declare a non-empty keys list")
            keys: list[dict[str, Any]] = []
            last_t = -1.0
            for key_index, raw_key in enumerate(keys_raw):
                key_what = f"{track_what} keys[{key_index}]"
                key = dict(_require_mapping(raw_key, key_what))
                _check_fields(key, {"t", "value", "easing"}, key_what)
                t = _number(key.get("t", 0.0), f"{key_what} t")
                if not 0.0 <= t <= 1.0:
                    _fail(f"{key_what} t must be within [0, 1], got {t}")
                if t <= last_t:
                    _fail(f"{track_what} keys must have strictly ascending t")
                last_t = t
                if "value" not in key:
                    _fail(f"{key_what} must declare a value")
                normalized_key: dict[str, Any] = {"t": t, "value": key["value"]}
                if key.get("easing") is not None:
                    easing = str(key["easing"])
                    if easing not in _EASINGS:
                        _fail(
                            f"{key_what} easing {easing!r} is not one of "
                            f"{', '.join(sorted(_EASINGS))}"
                        )
                    normalized_key["easing"] = easing
                keys.append(normalized_key)
            tracks.append({"param": param, "keys": keys})
        normalized: dict[str, Any] = {
            "label": str(definition.get("label", identifier)),
            "duration": duration,
            "loop": definition.get("loop", True) is not False,
            "tracks": tracks,
        }
        if definition.get("description"):
            normalized["description"] = str(definition["description"])
        animations[identifier] = normalized
    return animations


@dataclass(frozen=True)
class PoseDef:
    """A validated pose declaration. ``block`` is the JSON-ready descriptor
    payload (without the resolved escape-hatch ref — the build stamps that);
    ``module`` is the authored hatch path, script-relative, or None."""

    block: dict[str, Any]
    module: str | None


def pose(
    *,
    params: Mapping[str, Any] | None = None,
    features: Mapping[str, Any] | None = None,
    joints: Sequence[Mapping[str, Any]] | None = None,
    drivers: Sequence[Mapping[str, Any]] | None = None,
    animations: Mapping[str, Any] | None = None,
    module: str | None = None,
) -> PoseDef:
    """Validate and normalize a declarative pose block (see module docstring).

    Raises ``ValueError`` naming the offending element on any deviation from
    the closed vocabulary — a pose typo must fail the build, never silently
    do nothing at render time.
    """
    normalized_params = _normalize_params(params)
    normalized_features = _normalize_features(features)
    normalized_joints = _normalize_joints(joints, normalized_features)
    normalized_drivers = _normalize_drivers(
        drivers,
        params=normalized_params,
        features=normalized_features,
        joints=normalized_joints,
    )
    normalized_animations = _normalize_animations(animations, normalized_params)
    if not normalized_params and not normalized_drivers and not normalized_animations:
        _fail("declares nothing — provide params, drivers, or animations (or drop pose=)")
    module_path = None
    if module is not None:
        module_path = str(module).strip()
        if not module_path.endswith(".js"):
            _fail(f"module must be a .js file path, got {module_path!r}")
    block: dict[str, Any] = {"schemaVersion": POSE_SCHEMA_VERSION}
    if normalized_params:
        block["params"] = normalized_params
    if normalized_features:
        block["features"] = normalized_features
    if normalized_joints:
        block["joints"] = normalized_joints
    if normalized_drivers:
        block["drivers"] = normalized_drivers
    if normalized_animations:
        block["animations"] = normalized_animations
    return PoseDef(block=block, module=module_path)
