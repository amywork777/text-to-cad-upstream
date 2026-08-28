"""Shared CAD artifact generation runtime."""

from typing import TYPE_CHECKING

__all__ = [
    "__version__",
    "AssemblyHelper",
    "srgb",
    "MateRelation",
    "MateTarget",
    "compound_from_instances",
    "import_step",
    "load_step_scene",
    "located_shape",
    "occurrence_selector_id",
    "scene_occurrence_shape",
    "ensure_step_topology_artifact",
    "label_text",
    "label_shape",
    "report",
    "target",
    "track",
]


def __getattr__(name: str):
    if name == "ensure_step_topology_artifact":
        from cadgen.step_topology_artifact import ensure_step_topology_artifact

        return ensure_step_topology_artifact
    if name in {"AssemblyHelper", "MateRelation", "MateTarget", "label_shape", "label_text", "target"}:
        from cadgen.assembly import AssemblyHelper, MateRelation, MateTarget, label_shape, label_text, target

        return {
            "AssemblyHelper": AssemblyHelper,
            "MateRelation": MateRelation,
            "MateTarget": MateTarget,
            "label_text": label_text,
            "label_shape": label_shape,
            "target": target,
        }[name]
    if name in {"import_step", "load_step_scene", "located_shape", "occurrence_selector_id", "scene_occurrence_shape"}:
        from cadgen.step_scene import (
            import_step,
            load_step_scene,
            located_shape,
            occurrence_selector_id,
            scene_occurrence_shape,
        )

        return {
            "import_step": import_step,
            "load_step_scene": load_step_scene,
            "located_shape": located_shape,
            "occurrence_selector_id": occurrence_selector_id,
            "scene_occurrence_shape": scene_occurrence_shape,
        }[name]
    if name in {"srgb", "srgb_to_linear", "linear_to_srgb"}:
        from cadgen import color

        return getattr(color, name)
    if name == "compound_from_instances":
        from cadgen.instances import compound_from_instances

        return compound_from_instances
    if name in {"report", "track"}:
        from cadgen.progress import report, track

        return {"report": report, "track": track}[name]
    if name == "__version__":
        return _resolve_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    # Mirrors the lazy __getattr__ above so type checkers and editors see the root exports
    # without importing OCP. Every name here must have a branch there. develop's version of
    # this block pulled two names from the api alias module, which this branch deletes --
    # they come from their real modules now.
    from cadgen.assembly import AssemblyHelper, MateRelation, MateTarget, label_shape, label_text, target
    from cadgen.color import linear_to_srgb, srgb, srgb_to_linear
    from cadgen.instances import compound_from_instances
    from cadgen.progress import report, track
    from cadgen.step_scene import (
        import_step,
        load_step_scene,
        located_shape,
        occurrence_selector_id,
        scene_occurrence_shape,
    )
    from cadgen.step_topology_artifact import ensure_step_topology_artifact


def _resolve_version() -> str:
    """The installed distribution version, falling back to pyproject in a source tree.

    Installed metadata is the authority: it is what a consumer actually has, and it is
    what the skill shims compare their pinned requirement against. A bare source checkout
    has no metadata, so fall back to the pyproject this file ships beside — release
    tooling stamps it from the canonical VERSION, so the two never disagree.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("cadgen")
    except PackageNotFoundError:
        pass

    import pathlib
    import tomllib

    pyproject = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            return str(tomllib.load(handle)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0+unknown"
