"""Which documents a build's progress and outcome reach (``Models.paths``): those of its script,
whichever worker last built them, so a rebuild on a fresh worker clears a failure as it starts."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.python.support.paths import add_sources

add_sources()

from cad_server.engine.models import Models  # noqa: E402


def record(script: str, name: str, worker: object) -> dict:
    return {"worker": worker, "source": {"script": script, "name": name}}


class BuildDocuments(unittest.TestCase):
    def setUp(self) -> None:
        self.bracket = str(Path("/work/bracket.py").resolve())
        self.retired = SimpleNamespace(label=self.bracket)
        self.fresh = SimpleNamespace(label=self.bracket)
        self.other = SimpleNamespace(label=str(Path("/work/hinge.py").resolve()))
        self.models = SimpleNamespace(lock=threading.Lock(), records={
            "bracket": record(self.bracket, "bracket", self.retired),
            "bracket-b": record(self.bracket, "bracket_b", self.retired),
            "hinge": record(str(Path("/work/hinge.py").resolve()), "bracket", self.other),
        })

    def paths(self, worker: object, model: str | None = None) -> list[str]:
        return Models.paths(self.models, worker, model)

    def test_a_fresh_worker_reaches_the_documents_of_its_script(self) -> None:
        self.assertEqual(self.paths(self.fresh, "bracket.py::bracket"), ["bracket"])

    def test_another_script_with_a_model_of_that_name_is_not_reached(self) -> None:
        self.assertEqual(self.paths(self.other, "hinge.py::bracket"), ["hinge"])

    def test_the_worker_that_built_it_still_reaches_it(self) -> None:
        self.assertEqual(self.paths(self.retired, "bracket.py::bracket_b"), ["bracket-b"])

    def test_no_model_named_is_every_document_of_the_script(self) -> None:
        self.assertEqual(sorted(self.paths(self.fresh)), ["bracket", "bracket-b"])


if __name__ == "__main__":
    unittest.main()
