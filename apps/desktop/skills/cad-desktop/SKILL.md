---
name: cad-desktop
description: How to work with CAD inside Hardcore, the Text-to-CAD desktop app. Use whenever you run inside Hardcore (this skill is only installed there) and a task creates, changes, or reviews `.step`, `.stp`, `.dxf`, `.urdf`, `.srdf`, or `.sdf` files. Replaces the cad-viewer hand-off: the desktop shows models itself.
---

# CAD in Hardcore

You are running inside Hardcore, the Text-to-CAD desktop app. The person you
are working with sees this chat on the left and a CAD Viewer on the right,
served from the same workspace you are writing into. The viewer is already
running; you never start one.

## What the desktop does for you

- When your turn ends, every new or changed model artifact under the workspace
  (`.step`, `.stp`, `.dxf`, `.urdf`, `.srdf`, `.sdf`, `.glb`, `.stl`, `.3mf`) is
  found and opened in the viewer beside the chat, or announced with an Open
  action when a model is already open. You do not have to do anything for a
  model to be seen.
- A model tab has a 3D view, a Source view for the `.step.py` that generated
  it (with Save and Rebuild), and a Drawing action that produces an SVG, DXF,
  and PDF engineering drawing from the current STEP revision.
- Files you reference by workspace-relative path in a message become links
  that open the file in the desktop: a STEP opens in the viewer, a PNG or a PDF
  opens in a preview, source opens in the editor.
- Review renders you make with `cadgen step snapshot` are previewed when
  clicked and can be attached inline in your reply.

## What this replaces

The `cad` skill asks you to hand finished files to `$cad-viewer`. Inside
Hardcore that hand-off is satisfied by naming the file: the desktop opens it.
Therefore:

- Do not run the `cad-viewer` skill and do not start `server/main.py` or any
  viewer server. A second server races the desktop's own and its links die
  when your session ends.
- Do not post `http://127.0.0.1:<port>/?file=...` links or "Open in CAD
  Viewer" links. Refer to the file by its workspace-relative path instead,
  for example `models/bracket.step`.
- Do not report `$cad-viewer` as unavailable. It is intentionally absent here.

## How to finish a CAD turn here

1. Build and validate exactly as the `cad` skill says (`python model.step.py`,
   `cadgen step inspect validate`, `interfere`, `align`, `measure`).
2. Render the review snapshots you would normally render; write them under
   `models/review/` so they sit next to the model.
3. In the final message, list the files by path, state the validation that
   ran and its results, and describe what the person should look at in the
   viewer (which face, which pose, which clip). The viewer already shows the
   model; your words guide the eye.
4. If the model has an animation clip, say so: the viewer plays clips with its
   Play control.

## Things the person can do that you cannot

- Rotate, section, and measure in the viewer.
- Edit the `.step.py` in the Source view and rebuild without you.
- Create an engineering drawing from the model tab.

Mention these when they are the faster path, instead of doing them yourself.
