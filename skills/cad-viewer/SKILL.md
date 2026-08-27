---
name: cad-viewer
description: Start CAD Viewer and return review links for explicit CAD, implicit CAD, and robot-description files. Use when visually reviewing `.step`, `.stp`, `.implicit.js`, `.implicit.mjs`, `.glb`, `.stl`, `.3mf`, `.dxf`, `.urdf`, `.srdf`, or `.sdf` files, especially when handed off from CAD, implicit-cad, URDF, SRDF, or SDF generation skills.
---

# CAD Viewer

Provenance: maintained in [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad).
Use the installed local skill files as the runtime source of truth; the
repository link is only for provenance and release review. If the user asks to
modify, debug, or iterate on CAD Viewer source itself, clone that repository and
work there — this installed skill runtime runs the Viewer, it is not where you
edit it.

Use this skill to open existing or newly generated CAD, implicit CAD,
robot-description, or DXF files in CAD Viewer and hand back live review links. The expected input is one or more explicit file paths.

## Setup

The Viewer ships inside the `cadgen` distribution — client bundle and its JS server.
The server runs on Node.js (>= 22), which must be on `PATH`. Install cadgen once:

```bash
python -m pip install -r requirements.txt
```

## Start Viewer

Start one local CAD Viewer with `cadgen viewer`. It serves the bundled Viewer client
plus the CAD API on a single fixed port (`3245`). Each instance serves ONE directory,
given by `--root` and fixed for the life of the process.

> The default port `3245` is `0xCAD` — "CAD" in hexadecimal.

```bash
cadgen viewer --root /absolute/project/models --host 127.0.0.1
```

**Always pass an absolute `--root`.** The Viewer runs from an arbitrary working
directory — usually wherever the skill happens to be installed, not the model
directory — so a relative one resolves against the wrong place. `--root` defaults to
the current directory, which is rarely what you want here.

Equivalently `python -m cadgen.cli viewer --root ... --host 127.0.0.1`, which is what
to use when `cadgen` is not on `PATH`. Both print the review URL and, with `--json`,
the `{"url", "port", "action": "start"}` line.

## URL shape

The page is the bare origin, and `file=` selects one artifact inside the served root:

```text
http://127.0.0.1:3245/?file=mechanisms/lift_table.step.py
```

The `file=` value is relative to `--root`. Nothing about the directory appears in the
URL, so the same link means different files under different instances — the root is
the server's, not the link's.

**`--root` is the workspace, not the file's folder.** The Viewer scans it
recursively, so the file browser lists every model beneath it and the user can
switch files without a new link. Pick the directory the user thinks of as their
model workspace — typically the project's `models/` directory, or the nearest
common parent of the files you were asked to review — and put the rest of the
path in `file=`. Rooting at the artifact's own deep folder
(`--root .../models/step/mechanisms`, `?file=lift_table.step.py`) opens the same model
but hides the rest of the project, which is almost never what the user wants.

If port `3245` is already in use, the launcher exits with an error rather than
rolling to another port; rerun with an explicit free port, `--port <n>`, and use
the URL it prints. In sandboxed agent environments, local binding failures such
as `EPERM`/`EACCES` can be expected; rerun with the needed permission/escalation.

Add `--json` to also print a machine-readable result as the last stdout line
beginning with `{` (`{"url": ..., "port": ..., "action": "start"}`).

`cadgen viewer list` shows every running instance with the root it serves;
`cadgen viewer stop --port <n>` ends one. To review a directory outside the current
root, start a second Viewer on another port rather than trying to redirect the first.

## Links

- Before returning any link, resolve `<directory>/<file>` and confirm it
  exists. For a **generated** model pass the generator source (`<name>.step.py`)
  — that is what the catalog itself lists, the backend resolves it directly and
  builds the render artifacts on demand, and no `.step` file needs to exist. It
  is also the only form that carries a `params` sidecar, because a same-stem
  `<name>.step.py` shadows `<name>.step` anyway. For an **imported** STEP with no
  generator, pass the `.step`/`.stp` itself. If the resolved path is missing, do
  not return the link; report the problem and point to the correct path.
- Return one Viewer URL per requested file.
- Start the Viewer once and pick one workspace root for the session. Every link is
  the same origin plus `?file=<path relative to that root>`, so all of them share one
  browsable catalog. An artifact outside that root needs a second Viewer on another
  port; a link alone cannot reach it.
- For directory-only review links, return the origin without `?file=`.
- Do not stop an existing Viewer server unless the user asks.
- If Viewer startup fails, report the failure and continue with the owning skill's non-GUI validation or artifacts.

## References

- Read `references/viewer-features.md` when you need supported file types, Viewer controls, or file-specific feature details.
