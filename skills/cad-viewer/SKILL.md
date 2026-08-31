---
name: cad-viewer
description: Start CAD Viewer and return review links for CAD and robot-description files. Use when visually reviewing `.step`, `.stp`, `.glb`, `.stl`, `.3mf`, `.dxf`, `.urdf`, `.srdf`, or `.sdf` files, especially when handed off from CAD, URDF, SRDF, or SDF generation skills.
---

# CAD Viewer

Provenance: maintained in [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad).
Use the installed local skill files as the runtime source of truth; the
repository link is only for provenance and release review. If the user asks to
modify, debug, or iterate on CAD Viewer source itself, clone the standalone
[earthtojake/cad-viewer](https://github.com/earthtojake/cad-viewer) repository
and work there — this installed skill runtime runs the Viewer, it is not where
you edit it.

Use this skill to open existing or newly generated CAD,
robot-description, or DXF files in CAD Viewer and hand back live review links. The expected input is one or more explicit file paths.

## Setup

The Viewer ships INSIDE THIS SKILL, under `scripts/viewer/` — the prebuilt
client bundle plus its dependency-free JS server. There is nothing to install
for VIEWING: the one requirement is Node.js (>= 22) on `PATH`. Importing a raw
foreign STEP additionally needs cadgen (the CAD skill's requirements install
it); without cadgen, imports answer with an install hint and viewing is
unaffected.

## Start Viewer

Launching is unconditional: the command below always ends with the URL of a
live Viewer for the given root. If one is already running for that directory at
this Viewer version, its URL is returned (`"action": "reused"`); otherwise a
new server starts on the first free port from `3245` upward
(`"action": "started"`). Never pick or reason about ports — read the URL the
command prints. Each instance serves ONE directory, given by `--root` and fixed
for the life of the process.

> The base port `3245` is `0xCAD` — "CAD" in hexadecimal.

```bash
node scripts/viewer/server/main.mjs --root /absolute/project/models --host 127.0.0.1 --json
```

(Relative to this skill directory; use the absolute path to `main.mjs` when
running from elsewhere. `npm --prefix scripts/viewer run start -- --root ...`
is equivalent, but npm is not required.)

**Always pass an absolute `--root`.** The Viewer runs from an arbitrary working
directory — usually wherever the skill happens to be installed, not the model
directory — so a relative one resolves against the wrong place. `--root` defaults to
the current directory, which is rarely what you want here.

Flags: `--json` prints the machine-readable last stdout line
(`{"url", "port", "action": "started"|"reused"}`) — always pass it and take the
URL from there. `--new` forces a fresh instance instead of reusing. `--open`
opens the URL in the platform browser (for humans; leave it off in agent
flows). An explicit `--port <n>` is strict — "this port or fail" — and disables
both reuse and rolling.

## URL shape

The page is the bare origin, and `file=` selects one artifact inside the served root:

```text
http://127.0.0.1:3245/?file=mechanisms/lift_table.step
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
(`--root .../models/step/mechanisms`, `?file=lift_table.step`) opens the same model
but hides the rest of the project, which is almost never what the user wants.

Port collisions are not your problem: the launcher rolls to a free port and the
URL it prints is the truth. In sandboxed agent environments, local binding
failures such as `EPERM`/`EACCES` can still occur; rerun with the needed
permission/escalation.

`node scripts/viewer/server/main.mjs list` shows every running instance with the
root it serves; `node scripts/viewer/server/main.mjs stop --port <n>` ends one.
To review a directory outside the current root, just launch again with that
root — reuse-or-start makes the second launch cheap and correct.

## Generation is the CAD skill's job; imports spawn cadgen

The Viewer is a static visualization tool: it renders artifacts that already
exist. Generated models must be built first by running their model script (see
the CAD skill); the Viewer will not build them.

Raw `.step`/`.stp` files ARE importable from the Viewer: an unimported STEP
reports `needs-build` and the in-Viewer import writes the standard render
package. This needs a runnable cadgen (`CADGEN_PYTHON`, a `cadgen` on PATH, or
a `.venv` in the served root); absent cadgen the Viewer says exactly that and
keeps viewing. When an agent is doing the work there is nothing to run first:
every cadgen door makes the package it needs on demand, so just use the file
and return the link.

## Links

- Before returning any link, resolve `<directory>/<file>` and confirm it
  exists. Pass the `.step`/`.stp` artifact itself — generated and imported
  alike (the catalog lists artifacts; generated-ness is package provenance,
  shown as the model script in the UI). A generated model's render artifacts
  must already be built (run the model script, `python <model>.py`); the
  Viewer will not build them on open. If the resolved path is missing, do not
  return the link; report the problem and point to the correct path.
- Return one Viewer URL per requested file.
- Start the Viewer once and pick one workspace root for the session. Every link is
  the same origin plus `?file=<path relative to that root>`, so all of them share one
  browsable catalog. An artifact outside that root needs its own Viewer — launch
  again with that root (reuse-or-start makes this idempotent); a link alone cannot
  reach it.
- For directory-only review links, return the origin without `?file=`.
- Do not stop an existing Viewer server unless the user asks.
- If Viewer startup fails, report the failure and continue with the owning skill's non-GUI validation or artifacts.

## References

- Read `references/viewer-features.md` when you need supported file types, Viewer controls, or file-specific feature details.
