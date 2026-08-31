// The render-contract constants the viewer mirrors from cadgen, pinned by
// tests/python/global/test_render_contract_sync.py so a one-sided bump cannot
// ship.
//
// CACHE_SCHEMA_VERSION is the ONE cache-scheme number (cadgen/_internal/
// cache_schema.py): it salts every store package key (<hash>-v<N>), so a bump
// orphans old artifacts BY NAME and everything regenerates on demand. No
// artifact records a version inside itself — a package that resolves at all
// is current-scheme by construction.
export const CACHE_SCHEMA_VERSION = 16; // cache_schema.CACHE_SCHEMA_VERSION

// The source sidecar carries everything SOURCE-derived (provenance, the
// resolved kinematics block, the copied animation text, and the model's
// declared mesh exports); it sits BESIDE THE MODEL (<name>.step.json) and its
// EXISTENCE is the generated-vs-imported marker on both freshness authorities.
// Pinned to cadgen's source_sidecar.py by the same sync test.
//
// APPENDED to the artifact's whole name: `part.step` -> `part.step.json`.
// Never test a path with endsWith(SOURCE_SIDECAR_SUFFIX) alone — it is `.json`,
// which every unrelated JSON file also ends with. Build the path from the
// artifact (sourceSidecarPath), or match the artifact suffix too.
export const SOURCE_SIDECAR_SUFFIX = ".json"; // source_sidecar.SOURCE_SIDECAR_SUFFIX

// The sidecar names a CAD artifact carries: `<artifact>.step.json`. This is the
// safe membership test where a path is all you have.
export const SOURCE_SIDECAR_NAMES = [".step.json", ".stp.json"];
export const SOURCE_SIDECAR_SCHEMA_VERSION = 5; // source_sidecar.SOURCE_SIDECAR_SCHEMA_VERSION (5: declarations-only — provenance moved to the records tier)
