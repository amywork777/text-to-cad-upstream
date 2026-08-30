"""The public ``snapshot`` verb, once, for every format namespace that has one.

``cadgen.step.snapshot(...)``, ``cadgen.stl.snapshot(...)`` and the rest differ in
exactly one thing — which input kinds they accept — so they are one function
bound to different kinds rather than several copies of a fifteen-parameter
signature agreeing (design/format-doors.md).

Snapshot is an ADAPTER, not a mirror: the camera/theme/display surface is not
derivable from a signature, so the CLI keeps its hand-written parser and the
signature-sync policy test checks the declared option surface instead. What this
module adds is the missing third of the triple — the FUNCTION. `build` and
`validate` have had one since the schema landed; snapshot was reachable only
through argv, so nothing in Python could render without shelling out.

Import discipline: nothing here may pull in OCP/build123d, or the snapshot
machinery itself, at module scope. A model script imports ``cadgen.step`` before
its freshness gate runs, and this module rides along.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from cadgen.results import SnapshotResult


def snapshot_door(door: str) -> Callable[..., SnapshotResult]:
    """The ``snapshot`` verb for one format door, accepting only its own kinds."""

    def snapshot(
        target: Path | None = None,
        out: Path | None = None,
        *,
        job: Path | None = None,
        mode: str = "view",
        camera: object = None,
        theme: object = None,
        display: object = None,
        width: int | None = None,
        height: int | None = None,
        size_profile: str = "",
        params: object = None,
        focus: Sequence[str] | None = None,
        hide: Sequence[str] | None = None,
        view_labels: bool = False,
        debug: bool = False,
    ) -> SnapshotResult:
        """Render TARGET and report the files written.

        An explicit OUT is written exactly there and is cleared first, so a
        failed render leaves no file at all; a directory gets a generated
        timestamped name inside it. Rendering is a read: nothing about the model
        changes, though a STEP input whose render package is missing builds one.

        target: the model to render. Omitted, JOB supplies the input(s).
        out: destination image path, or a directory to generate a name in.
        job: a render-job JSON file — one job, an array of them, or
            {"jobs": [...]}. When given it wins: target/out are ignored, and
            a missing job file raises FileNotFoundError.
        mode: view (default), section, or list.
        camera: a preset, an "azimuth:elevation" pair, or a camera object.
        theme: a saved theme name, a theme-settings object, or a path to a
            theme JSON file. Defaults to the `snapshot` theme.
        display: a display mode name, a display-settings object, or a path to a
            display JSON file. STEP inputs only.
        width: output width in pixels, overriding the size profile.
        height: output height in pixels, overriding the size profile.
        size_profile: simple, diagnostic, labeled, assembly, presentation,
            or contact-sheet.
        params: pose parameter values for the model's @step(pose=...) block.
        focus: occurrence refs to render alone. STEP inputs only.
        hide: occurrence refs to leave out. STEP inputs only.
        view_labels: burn the camera/view label into the image.
        debug: report how each input's artifact resolved.
        """
        # Imported here rather than at module scope: `cadgen.step` is on a model
        # script's pre-gate path, and the snapshot CLI drags in the catalog,
        # selector lookup and STEP targets.
        import io

        from cadgen.cli.snapshot import DOOR_KINDS
        from cadgen.snapshot_cli import SnapshotOptions, run_snapshot

        options = SnapshotOptions(
            job=str(job) if job else "",
            input=str(target) if target else "",
            output=str(out) if out else "",
            mode=mode,
            width=width,
            height=height,
            size_profile=size_profile,
            view_labels=view_labels,
            debug=debug,
        )
        # `None` is "not given" for each of these, which is not the same as the
        # default: the CLI distinguishes them through the `<name>_specified`
        # flags, and a theme passed as its own default value must still count as
        # a choice (it changes the size profile).
        if theme is not None:
            options.theme, options.theme_specified = theme, True
        if display is not None:
            options.display, options.display_specified = display, True
        if camera is not None:
            options.camera, options.camera_specified = camera, True
        if params is not None:
            options.params, options.params_specified = params, True
        if focus:
            options.focus = [str(value) for value in focus]
        if hide:
            options.hide = [str(value) for value in hide]
        if options.focus and options.hide:
            raise ValueError("focus and hide cannot be used in the same snapshot")
        # An empty non-tty stream: the CLI reads a JSON packet off stdin when it
        # was given neither --job nor --input, and a library caller has no stdin
        # to offer. Reading nothing lands on the same "requires job or target"
        # error rather than blocking on a terminal.
        return run_snapshot(options, kinds=DOOR_KINDS[door], stdin=io.StringIO())

    return snapshot
