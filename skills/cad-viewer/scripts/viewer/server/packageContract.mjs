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

// The source sidecar carries everything SOURCE-derived (provenance, pose with
// inline escape-hatch source, mates); it sits BESIDE THE MODEL
// (<name>.step.source.json) and its EXISTENCE is the generated-vs-imported
// marker on both freshness authorities. Pinned to cadgen's source_sidecar.py
// by the same sync test.
export const SOURCE_SIDECAR_SUFFIX = ".source.json"; // source_sidecar.SOURCE_SIDECAR_SUFFIX
export const SOURCE_SIDECAR_SCHEMA_VERSION = 2; // source_sidecar.SOURCE_SIDECAR_SCHEMA_VERSION
