#!/usr/bin/env node
/**
 * The implicit CAD export CLI, as a builder cadgen can spawn.
 *
 * cadgen's `implicit_export.py` used to run an unbundled script, which cost more than it
 * looked: an unbundled entry needs its whole dependency GRAPH at runtime, so every skill
 * that exported an implicit model had to vendor the runtime beside it, and the child had to
 * be started with a resolve hook and a NODE_PATH so bare specifiers would resolve.
 *
 * Sitting in `packages/cadjs/bin` beside the other builders, it is esbuild-bundled into one
 * self-contained file, exactly like `implicit-artifact.mjs`.
 */
import "../scripts/implicit-export-cli.mjs";
