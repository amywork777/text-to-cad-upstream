"""Studio (studio-base): a model never stays older than its script without a build asked for (``studio_fresh``)."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cad_server.viewer import studio_fresh


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StaleModelTest(unittest.TestCase):
    def setUp(self) -> None:
        studio_fresh.forget()
        self.folder = Path(tempfile.mkdtemp())
        self.script = self.folder / "part.py"
        self.script.write_text("HEIGHT = 10.0\n", encoding="utf-8")
        # The engine's build read the script as it was then (v1): its fingerprint is those bytes.
        self.model = {"version": "v1", "source": {"script": str(self.script), "fingerprint": _digest("HEIGHT = 10.0\n")}}
        self.built: list[Path] = []

    def held(self, ident: str):
        return self.model, "", ""

    def refresh(self) -> bool:
        return studio_fresh.refresh("id-1", held=self.held, build=self.built.append)

    def test_a_script_changed_since_its_build_is_built_again_once_for_those_bytes(self) -> None:
        with mock.patch.dict(os.environ, {"CAD_STUDIO_ENGINE": "1"}):
            self.assertFalse(self.refresh(), "a script as its build read it builds nothing")
            self.script.write_text("HEIGHT = 15.0\n", encoding="utf-8")  # an agent's edit, no build of its own
            self.assertTrue(self.refresh())
            self.assertFalse(self.refresh(), "the same bytes are asked for once, however often the page waits")
            self.assertEqual(self.built, [self.script])
            # The build landed (v2 read the new bytes): nothing more to ask.
            self.model = {"version": "v2", "source": {"script": str(self.script), "fingerprint": _digest("HEIGHT = 15.0\n")}}
            self.assertFalse(self.refresh())
            # Changed again: asked again.
            self.script.write_text("HEIGHT = 20.0\n", encoding="utf-8")
            self.assertTrue(self.refresh())
            self.assertEqual(self.built, [self.script, self.script])

    def test_only_studios_engine_builds_and_nothing_is_asked_of_a_model_with_no_script(self) -> None:
        self.script.write_text("HEIGHT = 15.0\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"CAD_STUDIO_ENGINE": ""}):
            self.assertFalse(self.refresh(), "Jake's viewer builds when its agent runs the part")
        with mock.patch.dict(os.environ, {"CAD_STUDIO_ENGINE": "1"}):
            self.model = {"version": "v1", "source": {}}
            self.assertFalse(self.refresh())
            self.model = None
            self.assertFalse(self.refresh())
            self.assertEqual(self.built, [])

    def test_a_failure_here_never_fails_the_pages_wait(self) -> None:
        def broken(_ident: str):
            raise RuntimeError("no engine")

        with mock.patch.dict(os.environ, {"CAD_STUDIO_ENGINE": "1"}):
            self.assertFalse(studio_fresh.refresh("id-1", held=broken, build=self.built.append))


if __name__ == "__main__":
    unittest.main()
