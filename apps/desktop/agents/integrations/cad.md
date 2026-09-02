# CAD integration

Hardcore is a thread-first desktop shell for the Text-to-CAD toolchain. It keeps the existing
Electron, ACP, Claude, and Codex foundations while treating accepted STEP files as first-class
artifacts. It does not introduce a second agent runtime or attempt to become a full manual CAD
editor.

## Current release boundary

Hardcore's production Text-to-CAD pin remains fixed while Jake's 0.5 release branch is changing.
Do not advance the vendor pin until an official 0.5 tag is available and the packaged-app acceptance
gate passes against that exact tag. Compatibility work belongs behind the CAD adapter so a release
upgrade is one controlled change rather than scattered path checks.

Run the existing setup and checks from the repository root:

```bash
pnpm cad:setup
pnpm cad:check
pnpm cad:test
```

The setup provisions the supported provider CLIs, complete CAD skills, and one pinned local Python
runtime. Keep skill folders intact: their scripts, references, packages, and viewer assets are part
of the capability and cannot be replaced by copying only `SKILL.md`.

## Product model

The thread is the entry point. A user opens a project folder and can run many independent threads in
parallel, like Codex or Cursor. A thread may create or edit any relevant STEP, drawing, assembly,
analysis, document, or supporting file in that folder. It is not permanently owned by one model and
does not require a custom engineering-project hierarchy, conversation taxonomy, or geometry-edit
lease.

The primary layout is:

```text
projects and threads | active conversation | artifacts and viewer
```

Artifact tabs belong to the selected thread. Opening an existing CAD file should open its canonical
STEP directly in the artifact area; users should not need to create or select a model-specific chat
first. Advanced file browsing remains available through the desktop's ordinary project-file UI, not
a duplicate file tree injected into the embedded viewer.

## Canonical artifact lifecycle

The accepted on-disk STEP file and its recorded hash are canonical model state. A Python recipe is an
optional linked source file that can rebuild the STEP; it is not the artifact shown in the 3D tab and
it must never overwrite the STEP merely because a project or app restarted.

Every geometry-changing turn follows the same lifecycle:

1. Hash and back up the currently accepted STEP and linked editable source.
2. Let the selected agent edit files and explicitly rebuild when requested.
3. Validate the resulting STEP independently of the agent's completion message.
4. Accept and reload only the validated on-disk artifact.
5. Restore the previous accepted files after failure, interruption, or invalid geometry.

Opening, restart recovery, and ordinary validation are read-only. They inspect and hash the STEP;
they never run source with a force or rebuild option. Stop must terminate the agent and descendant
processes before recovery is evaluated.

## 0.5 compatibility seam

Keep these evolving Text-to-CAD contracts in one adapter:

- Viewer location and startup command.
- Cadgen command names and generation arguments.
- Explicit persisted source-to-STEP association and the bounded pinned-0.4 fallback.
- Accepted-artifact, hash, and package lookup.
- Bundled skill and runtime locations.

The adapter should select behavior from explicit capability/version detection. Do not infer a
generated model from a cache-directory name or an unestablished adjacent metadata file. Do not
special-case the moving 0.5 branch throughout renderer or main-process code.

## Native feature-tree contract

The viewer should eventually render source-backed design history itself instead of receiving an
injected DOM tree. Hardcore owns edit authorization, source updates, rebuild, validation, rollback,
and artifact acceptance. The portable payload is the versioned `designHistory` descriptor in
`src/core/features/cad/api/cad-design-history-descriptor.ts`.

The descriptor binds history to both `sourceHash` and `stepHash`, carries exact source spans, numeric
editability, sketch planes/transforms/dimensions when known, and exact cadgen/viewer selector
references. Its feature IDs are deterministic but explicitly revision-local: consumers must not use
them to correlate construction features after either bound hash changes. Cross-revision identity
requires authored IDs from cadgen and a later contract version.

The exported `cadDesignHistoryApi` and runtime schema are the JSON boundary for viewer and
host-process handoffs. All external payloads must pass that schema; the checked-in v1 fixture is the
portable compatibility example. The current source parser adapts into this shape as a migration
bridge. It leaves selector references empty when it cannot prove identity; fuzzy labels and STEP face
order are not stable references. Principal-plane transforms follow build123d normals, including
positive XZ offsets moving in the negative Y direction.

In the native viewer, keep two ideas separate:

- **Design**: authored operations, sketches, and editable numerical dimensions.
- **Geometry**: exact STEP bodies, components, faces, edges, and vertices.

An edit request returns through a host callback. The viewer never writes source or accepts geometry
on its own.

## Acceptance gate

Before changing the production Text-to-CAD pin, verify the installed Electron application rather
than only a source checkout:

1. Start Claude and Codex sessions and confirm bundled skills are available automatically.
2. Generate a STEP and open the accepted artifact.
3. Change a numeric dimension, rebuild, validate, and reload it.
4. Restart the app and confirm the same STEP hash and viewport artifact return without regeneration.
5. Produce an invalid edit and confirm the last accepted artifact is restored.
6. Open an imported STEP with no editable source.
7. Exercise an explicitly linked source/STEP pair and an imported STEP with no source link.
8. Run at least two CAD threads concurrently and confirm independent status, processes, and viewers.
9. Package the app and repeat a smoke generation without relying on a developer checkout.

Only after that gate passes should the exact released tag become the production vendor pin.
