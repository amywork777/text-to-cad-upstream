// The render-contract constants the viewer mirrors from cadgen, pinned by
// tests/python/global/test_render_contract_sync.py so a one-sided bump cannot
// ship.
//
// CACHE_SCHEMA_VERSION is the ONE cache-scheme number (cadgen/_internal/
// cache_schema.py): it salts every store package key (<hash>-v<N>), so a bump
// orphans old artifacts BY NAME and everything regenerates on demand. No
// artifact records a version inside itself — a package that resolves at all
// is current-scheme by construction.
export const CACHE_SCHEMA_VERSION = 17; // cache_schema.CACHE_SCHEMA_VERSION

// The source sidecar carries the model's DECLARATIONS — the resolved kinematics
// block, the copied animation text, the declared mesh exports — beside the model
// at <name>.step.json. It is written only when there is something to declare, so
// its existence proves a document is generated but its absence proves nothing;
// see RECORDS_DIR_NAME below for the marker that actually decides.
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

// The RECORDS tier — where a build's provenance actually lives at schema 5.
//
// The sidecar above is written only when the model DECLARES something worth
// carrying (kinematics, animation, mesh exports), so a plain generated model
// has no sidecar at all and its existence answers only half of
// generated-vs-imported. Every generated build, plain or not, writes a
// provenance record at <cache>/records/<artifactPathKey>.source.json, so THAT
// is the marker the freshness authorities consult; the sidecar's presence is
// only ever a fast yes.
//
// Evictable by design (cadgen cache gc sweeps it): a missing record must
// degrade to "imported", never to an error. Losing one costs a rebuild, which
// re-records it.
export const RECORDS_DIR_NAME = "records"; // cache_paths.records_dir
export const PROVENANCE_RECORD_SUFFIX = ".source.json"; // source_sidecar._provenance_record_path
export const ARTIFACT_PATH_KEY_LENGTH = 24; // catalog.artifact_path_key (sha256 hexdigest[:24])
