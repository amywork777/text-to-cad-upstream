# Hardcore

Hardcore is a CAD-first desktop workspace for turning engineering intent into editable,
revisioned models with Claude or Codex.

![Hardcore CAD workspace](artifacts/screenshots/hardcore-opendesign-studio-pattern.jpg)

## Product model

- An engineering project owns parts, assemblies, drawings, materials, and project discussions.
- Each CAD model owns its files, revisions, feature tree, parameters, and multiple focused chats.
- Exactly one model chat can edit geometry at a time; the others share current model context without
  competing writes.
- The on-disk artifact revision and hash are the canonical model state.
- Source, History, Drawing, Instructions, and Analysis are workspace modes—not extra side panels.

## Current MVP

- Text-to-CAD generation and follow-up revision through Claude or Codex
- Embedded STEP viewer with model tree, inspection tools, and CAD-themed controls
- Editable source and parameter controls for generator-backed models
- Revision-safe reload and persistence
- Model-scoped conversations with explicit edit authority
- Project files, material assignments, and component/BOM material context
- Pinned local CAD runtime provisioning

## Development

Prerequisites are provisioned through the pinned pnpm and Node configuration in the repository.

```bash
pnpm install
pnpm run doctor
pnpm run dev
```

Run the complete local quality gate with:

```bash
pnpm run check
```

## Privacy

Hardcore is local-first. App state, engineering files, and conversation metadata are stored on the
machine. Claude and Codex may send prompts and selected context to their respective providers.
Telemetry is optional and can be disabled in Settings or with:

```bash
TELEMETRY_ENABLED=false
```

## License

Licensed under the [Apache-2.0 license](LICENSE.md).
