# The package is the document: FreeCAD-style persistence + gen-always-writes-STEP

Status: EXECUTING 2026-08-27. Branch `claude/incremental-generation`.
Builds on `design/surface-rendering.md` (surf-only packages) and
`design/production-architecture.md` (op memo / scope caches).

## Principle (what FreeCAD gets right)

Never re-derive the document through an interchange format. FreeCAD's
`.FCStd` is a zip of per-object NATIVE binary B-reps plus a tree XML; save
and load are verbatim shape dumps, so its file round trip is IDENTITY —
no parsing, no healing, no reparametrization. STEP is paid for only at the
import/export boundary. Our measured contrast: BinTools blobs read at
native speed and preserve cids by construction; a STEP round trip of
moonwatch costs ~60 s to read back and rewrites every component's
representation.

## Target architecture

One package per STEP FILE (not per entry) is the document of record:

```
__cadgen__/models/<name>.step/
  assembly.json            # tree, transforms, provenance, colors, mates
  components/<cid>.brep    # EXACT shape, BinTools (the FreeCAD .brp)
  components/<cid>.surf    # render view (client tessellation)
```

- `<cid>.brep` is byte-for-byte the location-stripped BREP payload that
  computed the cid — the build already holds these bytes; emission is a
  write, not a computation.
- Everything needing exact geometry reads blobs: STEP assembly, STL/3MF
  export, inspect measure/booleans. `gen_step()` runs ONLY when sources
  changed (closure freshness) — never to satisfy a reader.
- The shared store carries `<cid>.brep` beside `<cid>.surf` (bare cid).

## Pipelines and the handoff

GENERATION (gen CLI + daemon; the only place Python sources execute):
  `<name>.step.py` --closure-freshness--> gen_step() shapes
      --> package (brep + surf + descriptor) --> assemble STEP from package
      --> `<name>.step`
- `scripts/gen` input is a Python source, output is ALWAYS the STEP file.
  `--write` is DELETED (hard migration, no shim). `-o` names the STEP.
- STEP assembly reads blobs + descriptor (occurrence transforms, labels,
  colors, mates) into XCAF and writes; no generator execution.
- Unchanged sources: the export record short-circuits the whole run.

RENDER (viewer + snapshot; never executes Python):
  `<name>.step` --stepHash-freshness--> package --> pixels
- The viewer renders STEP entries from the step-keyed package. A package
  missing/stale relative to the FILE hash is (re)built by IMPORTING the
  file — the boundary path, same as any vendor STEP.
- A `.step.py` entry in the viewer resolves to its OUTPUT's package; the
  build affordances (Update button, parameter edits) DELEGATE to the
  generation pipeline as a black box and then re-render. Render code
  contains no generation logic.

## Freshness (two gates, one per pipeline)

- gen-side: source closure hash (unchanged from production-architecture).
- render-side: descriptor.stepHash vs the file on disk. A generated STEP
  carries its hash in the descriptor at assembly time; hand-editing the
  file demotes it to the imported path.

## Why edits stay fast

An edit touches: changed scopes (gen) -> changed components' brep+surf
writes (~ms each) -> STEP reassembly (size-linear, the only whole-model
cost; ~6-8 s at moonwatch's 115 MB, sub-second for typical models) ->
viewer re-fetches only new cids. Nothing else in the system re-derives.
