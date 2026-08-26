# Source-backed feature editor in CAD Viewer

Status: proposed. Target branch: `develop`. Generation dependency:
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

Once #340 lands, Apply should send one validated source edit request through
the same public rebuild entry point used by the CLI and viewer artifact flow.
The response must identify the canonical on-disk artifact and its source and
artifact hashes. The viewer then reloads that artifact. Failed generation must
leave the previous artifact visible and must not write the draft source.

Until that entry point is available, the feature editor can ship only in a
read-only or draft-only state. It must not carry a temporary regeneration
bridge that becomes a second production path.

## Ownership

| Concern | Owner |
| --- | --- |
| Source parsing and source spans | Reusable cadgen/source-feature module |
| Feature tree, selection, dimension UI, drafts | CAD Viewer |
| Source edit validation | Shared source-feature module |
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

Double-clicking a feature or one of its dimensions enters an explicit edit
mode. Edits remain drafts until Apply:

1. The selected feature stays highlighted and unrelated geometry is ghosted.
2. The viewer shows the relevant sketch plane or dimension anchors on the
   model.
3. Inputs and on-model handles update the same draft state.
4. Apply validates every proposed source span against the source hash captured
   when editing began.
5. One source patch is sent to cadgen's canonical rebuild entry point.
6. On success, the viewer reloads the returned canonical artifact and clears
   the draft.
7. On failure or stale source, the current artifact remains visible and the
   draft is preserved for correction.

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

The rebuild result must return the accepted source hash, canonical artifact
path, artifact hash, and validation outcome. It must not return session-only
geometry for the viewer to treat as authoritative.

## Delivery sequence

1. Extract and test source-feature parsing as a reusable, read-only module.
2. Add the native Design/Geometry tree and selection/highlight behavior.
3. Add shared draft state and on-model dimension editing without Apply.
4. After #340 exposes the canonical rebuild entry point, connect Apply to it.
5. Acceptance-test edit, stale-source rejection, failed rebuild recovery,
   restart, and canonical artifact reload.

## Explicit non-goals

- Hardcore's chat, project, and output-workspace UI.
- Emdash or Codeg agent/session infrastructure.
- The Hardcore Electron application.
- Generated car, castle, bridge, or other acceptance-test artifacts.
- A replacement cache, daemon, worker, or regeneration bridge.
