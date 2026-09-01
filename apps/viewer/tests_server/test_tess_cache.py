"""The shared tessellation cache: name validation, store I/O, and TESB framing.

Ports ``tessCache.test.mjs``. The container test does not read the format by
eye — it hands the Python encoder's bytes to the AUTHORITATIVE decoder in
``packages/cadgen-js``, which is where the format lives. A hand-written
assertion about offsets would pass just as happily against a subtly wrong
encoder, and the client would then silently fall back to one round trip per
component for the life of the page.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from server.tess_cache import (  # noqa: E402
    TESS_CACHE_ROUTE_PREFIX,
    read_tess_cache_batch,
    read_tess_cache_entry,
    tess_cache_key_from_route_path,
    tessellation_cache_dir,
    write_tess_cache_entry,
)

REPO_ROOT = APP_ROOT.parent.parent
CADGEN_JS_CODEC = REPO_ROOT / "packages" / "cadgen-js" / "src" / "lib" / "surf" / "tessellationCache.js"
GOOD_KEY = "c0ffee-t1-l1.500000e-3-a3.500000e-1"


class TessCacheTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Blank every root the resolver consults, not just the one this
        # platform reads: setting HOME alone leaves the sandbox a no-op on
        # Windows and lets the tests write into the runner's real cache.
        self._saved = {
            name: os.environ.get(name)
            for name in (
                "CADGEN_CACHE_DIR",
                "XDG_CACHE_HOME",
                "LOCALAPPDATA",
                "HOME",
                "USERPROFILE",
                "CADGEN_MESH_CACHE",
            )
        }
        self.addCleanup(self._restore)
        for name in self._saved:
            os.environ.pop(name, None)
        os.environ["HOME"] = self.tmp.name
        os.environ["USERPROFILE"] = self.tmp.name
        os.environ["CADGEN_CACHE_DIR"] = os.path.join(self.tmp.name, "cache")

    def _restore(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def route(self, name: str) -> str:
        return f"{TESS_CACHE_ROUTE_PREFIX}{name}"


class NameValidation(TessCacheTestCase):
    def test_the_canonical_key_is_accepted(self):
        self.assertEqual(tess_cache_key_from_route_path(self.route(f"{GOOD_KEY}.tess")), GOOD_KEY)

    def test_traversal_separators_hidden_names_and_spaces_are_refused(self):
        # The cache lives OUTSIDE every served root, so containment cannot help
        # here: this pattern is the whole defence.
        for name in (
            "../escape.tess",
            "sub/dir.tess",
            "%2e%2e%2fescape.tess",
            "..%2Fescape.tess",
            ".hidden.tess",
            "noext",
            "",
            "a b.tess",
            "a..b.tess",
            "batch",
        ):
            with self.subTest(name=name):
                self.assertIsNone(tess_cache_key_from_route_path(self.route(name)))

    def test_a_malformed_percent_escape_is_a_refusal_not_a_crash(self):
        for name in ("%zz.tess", "%.tess", "%2.tess", "%C0%AF.tess", "%ED%A0%80.tess"):
            with self.subTest(name=name):
                self.assertIsNone(tess_cache_key_from_route_path(self.route(name)))

    def test_a_trailing_newline_does_not_sneak_past_the_anchor(self):
        # Python's `$` also matches before a trailing newline; JavaScript's does
        # not. fullmatch is what keeps the two the same.
        self.assertIsNone(tess_cache_key_from_route_path(self.route("a.tess%0A")))


class StoreRoundTrip(TessCacheTestCase):
    def test_write_then_read_returns_the_exact_bytes(self):
        payload = b"\x00\x01binary\xff"
        self.assertEqual(write_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"), payload), 204)
        status, body = read_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"))
        self.assertEqual(status, 200)
        self.assertEqual(body, payload)

    def test_a_miss_is_404_and_a_refused_name_is_403(self):
        self.assertEqual(read_tess_cache_entry(self.route("absent-t1.tess"))[0], 404)
        self.assertEqual(read_tess_cache_entry(self.route("../escape.tess"))[0], 403)
        self.assertEqual(write_tess_cache_entry(self.route("../escape.tess"), b"x"), 403)

    def test_an_empty_body_is_accepted_and_dropped(self):
        self.assertEqual(write_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"), b""), 204)
        self.assertEqual(read_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"))[0], 404)

    def test_the_write_leaves_no_temp_file_behind(self):
        write_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"), b"payload")
        names = os.listdir(tessellation_cache_dir())
        self.assertEqual(names, [f"{GOOD_KEY}.tess"])

    def test_disabling_the_cache_turns_off_both_directions_and_creates_no_directory(self):
        os.environ["CADGEN_MESH_CACHE"] = "0"
        self.assertEqual(write_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"), b"x"), 204)
        self.assertEqual(read_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"))[0], 404)
        self.assertFalse(os.path.exists(tessellation_cache_dir()))

    def test_the_enable_flag_is_read_per_call(self):
        write_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"), b"payload")
        os.environ["CADGEN_MESH_CACHE"] = "0"
        self.assertEqual(read_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"))[0], 404)
        os.environ.pop("CADGEN_MESH_CACHE")
        self.assertEqual(read_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"))[0], 200)


class BatchRequests(TessCacheTestCase):
    def test_a_malformed_request_is_none_so_the_route_can_answer_400(self):
        for body in (b"not json", b"[]", b'{"names":"x"}', b"{}", b'{"names":null}'):
            with self.subTest(body=body):
                self.assertIsNone(read_tess_cache_batch(body))

    def test_more_than_the_cap_is_refused(self):
        self.assertIsNone(read_tess_cache_batch(json.dumps({"names": ["a.tess"] * 4097}).encode()))
        self.assertIsNotNone(read_tess_cache_batch(json.dumps({"names": []}).encode()))


@unittest.skipUnless(shutil.which("node") and CADGEN_JS_CODEC.is_file(), "needs node + cadgen-js")
class BatchFramingMatchesTheAuthoritativeCodec(TessCacheTestCase):
    """The Python encoder's bytes must decode with the JS decoder that owns the format."""

    def decode_with_node(self, container: bytes):
        script = f"""
        import {{ decodeTessellationCacheBatch }} from {json.dumps(str(CADGEN_JS_CODEC))};
        const bytes = Uint8Array.from(JSON.parse(process.argv[1]));
        const entries = decodeTessellationCacheBatch(bytes);
        process.stdout.write(JSON.stringify(
          entries === null ? null : entries.map((e) => (e === null ? null : Array.from(e)))));
        """
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script, "--", json.dumps(list(container))],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_hit_miss_and_refusal_decode_in_order(self):
        write_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"), b"AAA")
        container = read_tess_cache_batch(
            json.dumps(
                {"names": [f"{GOOD_KEY}.tess", "absent-t1.tess", "../escape.tess"]}
            ).encode()
        )
        # A refused name and a miss are per-entry MISSES, never errors: one bad
        # key must not cost an assembly its whole round trip.
        self.assertEqual(self.decode_with_node(container), [[65, 65, 65], None, None])

    def test_unaligned_payloads_round_trip(self):
        # 1, 2 and 3 mod 4 all exercise the padding; a decoder that advances by
        # the raw length instead of the aligned one desynchronises after the
        # first such entry.
        names = []
        for size in (1, 2, 3, 4, 5):
            key = f"pad{size}-t1-l1-a1"
            write_tess_cache_entry(self.route(f"{key}.tess"), bytes(range(size)))
            names.append(f"{key}.tess")
        container = read_tess_cache_batch(json.dumps({"names": names}).encode())
        self.assertEqual(
            self.decode_with_node(container), [list(range(size)) for size in (1, 2, 3, 4, 5)]
        )

    def test_a_non_string_name_is_a_miss_and_keeps_the_container_valid(self):
        write_tess_cache_entry(self.route(f"{GOOD_KEY}.tess"), b"Z")
        container = read_tess_cache_batch(
            json.dumps({"names": [17, f"{GOOD_KEY}.tess", None]}).encode()
        )
        self.assertEqual(self.decode_with_node(container), [None, [90], None])

    def test_an_empty_request_still_produces_a_valid_container(self):
        container = read_tess_cache_batch(json.dumps({"names": []}).encode())
        self.assertEqual(len(container), 12)
        self.assertEqual(self.decode_with_node(container), [])


if __name__ == "__main__":
    unittest.main()
