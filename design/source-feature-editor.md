# Source-backed feature editor in CAD Viewer

Status: implemented in the viewer. Target branch: `develop`. Generation dependency:
[#340](https://github.com/earthtojake/text-to-cad/pull/340).

## Goal

Give Python-backed STEP models a native, SolidWorks-style design view without
turning CAD Viewer into a second CAD runtime.

The viewer should be able to:

- show source-backed features in construction order;
- group a sketch under the operation that consumes it, such as Extrude or
  Revolve;
- show the editable dimensions on the selected feature and on the model;
- draft several dimension changes before applying them together; and
- reload the canonical artifact produced by cadgen after a successful apply.

The `.step.py` source remains the editable construction history. A STEP file
continues to represent delivered geometry, not an invented parametric history.

## Boundary with incremental generation

The editor must not own regeneration, caching, workers, or artifact selection.
Its Apply action is a client of cadgen's canonical rebuild path.

In particular, this work must not add or restore:

- a `/__cad/regenerate` development endpoint;
- a viewer-specific Python subprocess or worker pool;
- a second cache, freshness check, or source-to-artifact pipeline;
- an in-memory artifact that can disagree with the file on disk; or
- fallback logic that silently uses an old rebuild path.

Apply commits one guarded source update, then calls the viewer's existing
`POST /__cad/artifact` route with `force: true`. That public route delegates to
cadgen's canonical artifact builder; the source editor does not invoke a
generator itself. The viewer reloads only the artifact accepted by that route.
If rebuilding fails, the source update is rolled back with another guarded
write while the previous accepted artifact stays visible and the draft is
preserved for correction.

#340 can land underneath this interaction without changing the viewer-facing
contract. This work deliberately carries no temporary regeneration bridge or
duplicate cache.

## Ownership

| Concern | Owner |
| --- | --- |
| Source parsing and source spans | Viewer-local, dependency-free parser |
| Feature tree, selection, dimension UI, drafts | CAD Viewer |
| Source edit validation | Viewer-local guarded source editor |
| Geometry rebuild and incremental cache | Canonical cadgen path from #340 |
| Artifact freshness, hashes, and atomic replacement | cadgen |
| Reloading and presenting the accepted artifact | CAD Viewer |

Hardcore, Emdash, Codeg, and other host applications are consumers of this
viewer contract. Their conversation, project, agent, and Electron code does
not belong in this repository.

## Proposed interaction

### Design tree

For a Python-backed STEP, the existing STEP tree gains two representations:

- **Design** — source-backed sketches, primitives, and operations in authored
  order;
- **Geometry** — the existing bodies, faces, and edges from the STEP artifact.

Design is shown first when source features are available. Imported STEP files
show Geometry only.

Feature names use familiar CAD language (`Sketch1`, `Boss-Extrude1`,
`Revolve1`, `Fillet1`) while retaining a stable source identifier. Expanding a
feature reveals its editable dimensions. Selecting it highlights the matching
region and shows its dimensions on the model.

### Editing

Selecting a source-backed sketch exposes an `Edit Sketch` action. Entering it
temporarily reuses the existing 3D viewport rather than opening another panel
or replacing Geometry:

1. The viewer captures the exact camera, projection, zoom, selection, display,
   and visibility state of the current 3D view.
2. It snaps normal to the authored sketch plane, ghosts the accepted solid,
   and draws the profile, dimension lines, labels, and anchors directly on the
   model. The existing Geometry tree remains intact.
3. Dimension inputs update that overlay immediately while the source and
   canonical artifact remain unchanged.
4. `Return to 3D` restores the captured view while retaining drafts; `Cancel`
   or Escape restores it and discards drafts.
5. Apply validates every proposed source span against the source hash captured
   when editing began.
6. One guarded source patch is committed atomically.
7. The viewer requests a forced rebuild through the existing canonical
   artifact route.
8. On success, the viewer reloads the accepted canonical artifact and clears
   the draft.
9. On failure or stale source, the current artifact remains visible, the
   source patch is rolled back, and the draft is preserved for correction.

Static `Plane.XY`, `Plane.XZ`, `Plane.YZ`, `Plane.ZX`, and `Plane.ZY` sketches,
plane offsets, custom static planes, and nested `Locations` are projected in
their authored coordinate systems. Face-derived or otherwise dynamic planes
remain dimension-editable in the tree, but the viewer disables viewport sketch
mode rather than pretending it knows the plane.

Only numeric literals or explicitly declared editable parameters should be
changed surgically. Expressions, shared variables, or ambiguous spans require
opening Source rather than guessing.

## Data contract

The source-feature description should be independent of React and contain no
geometry objects:

```json
{
  "sourcePath": "models/bracket.step.py",
  "sourceHash": "sha256:…",
  "features": [
    {
      "id": "source:sketch-1/extrude-1",
      "kind": "extrude",
      "label": "Boss-Extrude1",
      "sourceSpan": [120, 248],
      "parameters": [
        {
          "id": "amount",
          "label": "Depth",
          "value": 6,
          "unit": "mm",
          "sourceSpan": [232, 233]
        }
      ]
    }
  ]
}
```

An edit request carries the captured `sourceHash`, the intended replacements,
and the artifact identity. Cadgen rejects stale hashes and overlapping or
out-of-range spans before writing anything.

The source update returns the accepted source hash. The artifact route returns
the canonical artifact status and metadata already consumed by the viewer. It
must not return session-only geometry for the viewer to treat as authoritative.

## Delivery sequence

1. Add and test dependency-free, viewer-local source-feature parsing.
2. Add the native Design/Geometry tree and selection/highlight behavior.
3. Add shared draft state and on-model dimension editing without Apply.
4. Connect Apply to the existing canonical artifact route; let #340 improve
   the implementation behind that stable contract.
5. Acceptance-test edit, stale-source rejection, failed rebuild recovery,
   restart, and canonical artifact reload.

## Explicit non-goals

- Hardcore's chat, project, and output-workspace UI.
- Emdash or Codeg agent/session infrastructure.
- The Hardcore Electron application.
- Generated car, castle, bridge, or other acceptance-test artifacts.
- A replacement cache, daemon, worker, or regeneration bridge.
