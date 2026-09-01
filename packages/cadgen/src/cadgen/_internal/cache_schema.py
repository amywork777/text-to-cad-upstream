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
in ``apps/viewer/server/store_paths.py``, pinned against this literal by
``tests/python/global/test_render_contract_sync.py`` so a one-sided bump
cannot ship.
"""

CACHE_SCHEMA_VERSION = 16
