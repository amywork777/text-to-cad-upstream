"""The ONE cache-scheme number.

``CACHE_SCHEMA_VERSION`` is the store generation: it salts every render
package's directory key (``<sha256(document)>-v<N>``, ``cadgen.catalog``)
and the component cids inside packages. Bumping it is the whole migration
story — old-generation artifacts simply stop resolving (orphaned BY NAME,
swept by ``cadgen cache gc``) and everything regenerates on demand at the
new key. Nothing is ever migrated in place, and no artifact records a
version inside itself: a package that resolves at all IS current-scheme by
construction.

Bump it whenever anything about a package's meaning or payloads changes:
the descriptor shape, the ``.surf`` container (``SURF_VERSION``), the
embedded topology tables, component serialization — one number, one
signal, one regeneration.

Stdlib-only on purpose: the viewer's JS mirror is ``CACHE_SCHEMA_VERSION``
in ``apps/viewer/server/packageContract.mjs``, pinned against this literal by
``tests/python/global/test_render_contract_sync.py`` so a one-sided bump
cannot ship.
"""

# 17: the descriptor's ``mesh`` section is gone. A render package stores
# surfaces, not triangles, so the deflection numbers it recorded described a
# mesher this package no longer contains, and the adaptive ``resolution``
# beside them was the input to a decision the descriptor already records the
# output of (``edgeRendering.visibilityClasses``).
CACHE_SCHEMA_VERSION = 17
