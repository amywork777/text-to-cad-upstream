#!/usr/bin/env node
/**
 * The implicit CAD export CLI, as a builder cadgen can spawn.
 *
 * cadgen's `implicit_export.py` used to run `packages/implicitjs/scripts/export.mjs`
 * directly. That was the one Node entry left unbundled, and it cost more than it looked:
 * an unbundled script needs its whole dependency GRAPH at runtime, so every skill that
 * exported an implicit model had to vendor all of implicitjs beside it, and the child had
 * to be started with a resolve hook and a NODE_PATH so bare specifiers would resolve.
 *
 * Sitting in `packages/cadjs/bin` beside the other builders, it is esbuild-bundled into
 * one self-contained file per skill runtime, exactly like `implicit-artifact.mjs`. The
 * import below is what esbuild inlines; in the source checkout it resolves through
 * implicitjs's exports map instead. The CLI itself still lives in implicitjs, which also
 * runs it as its own `npm run export` -- one implementation, two entry points.
 *
 * cadjs importing implicitjs is the allowed direction (AGENTS.md); implicitjs must never
 * import cadjs.
 */
import "implicitjs/cli/export";
