// The render-package contract constants the JS status authority validates
// against, pinned to their Python producers (cadgen). The sync test
// tests/python/global/test_render_contract_sync.py asserts these literals
// match cadgen's, so a producer-side bump cannot silently leave the viewer
// approving stale packages.
export const STEP_PACKAGE_VERSION = 15; // package_freshness.STEP_PACKAGE_VERSION
export const STEP_TOPOLOGY_SCHEMA_VERSION = 2; // glb_topology.STEP_TOPOLOGY_SCHEMA_VERSION
