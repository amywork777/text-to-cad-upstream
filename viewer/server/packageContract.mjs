// The render-package contract constants the JS status authority validates
// against, pinned to their Python producers (cadgen). The sync test
// tests/python/global/test_render_contract_sync.py asserts these literals
// match cadgen's, so a producer-side bump cannot silently leave the viewer
// approving stale packages.
export const STEP_PACKAGE_VERSION = 15; // package_freshness.STEP_PACKAGE_VERSION
export const STEP_TOPOLOGY_SCHEMA_VERSION = 2; // glb_topology.STEP_TOPOLOGY_SCHEMA_VERSION

// The source sidecar carries everything SOURCE-derived (provenance, pose,
// mates); its EXISTENCE is the generated-vs-imported marker on both freshness
// authorities. Pinned to cadgen's source_sidecar.py by the same sync test.
export const SOURCE_SIDECAR_NAME = "source.json"; // source_sidecar.SOURCE_SIDECAR_NAME
export const SOURCE_SIDECAR_SCHEMA_VERSION = 1; // source_sidecar.SOURCE_SIDECAR_SCHEMA_VERSION
