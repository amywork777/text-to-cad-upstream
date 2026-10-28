"""Studio's project models route (``GET /__cad/models?root=``, ``cadgen/edit/models.py``): every model
of the engine's registry whose script is in the folder, by its id, never a rollback bar's body."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from cadgen.edit.models import folder_models, folders_models
from cadgen.engine.registry import Folder, Registry
from cadgen.viewer import handler as handler_module
from cadgen.viewer.http_app import create_cad_app


def _record(kind, root, home, name, built=None, parts=None):
    record = {"id": str(uuid.uuid4()), "kind": kind, "root": str(root), "home": home, "entry": name,
              "name": name, "namespace": str(root)}
    if built is not None:
        record["built"] = built
    if parts is not None:
        record["facts"] = {"parts": parts}
    return record


class FolderModels(unittest.TestCase):
    def setUp(self):
        # Under /tmp, which macOS spells /private/tmp once resolved: the registry's paths are resolved ones.
        self.tmp = Path(tempfile.mkdtemp(prefix="folder-models-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "state"
        environment = mock.patch.dict(os.environ, {"CADGEN_STATE_DIR": str(self.state)})
        environment.start()
        self.addCleanup(environment.stop)
        self.registry = Registry(Folder(self.state))
        self.project = self.tmp / "bracket"
        (self.project / "parts").mkdir(parents=True)
        (self.project / "assemblies").mkdir()
        for script in ("parts/plate.py", "assemblies/rig.py"):
            (self.project / script).write_text("", encoding="utf-8")
        resolved = Path(os.path.realpath(self.project))
        self.plate = _record("model", resolved / "parts", "plate.py", "plate", built=1761555600.5, parts=1)
        self.rig = _record("model", resolved, "assemblies/rig.py", "rig", built=1761555700.0, parts=3)
        for record in (self.plate, self.rig,
                       # CAD mode's rollback bar's body, a file opened, a model whose script is gone.
                       _record("shape", resolved / "parts", "plate.py", "plate at the rollback bar 1a2b3c4d"),
                       _record("file", resolved / "parts", "vendor.step", "vendor.step"),
                       _record("model", resolved / "parts", "gone.py", "gone")):
            self.registry.put(record)
        # Over Recents' 200 rows: models of other projects, built since.
        other = self.tmp / "other"
        other.mkdir()
        for index in range(220):
            (other / f"p{index}.py").write_text("", encoding="utf-8")
            self.registry.put(_record("model", os.path.realpath(other), f"p{index}.py", f"p{index}", built=1761556000.0 + index))

    def test_a_folder_lists_its_models_whatever_its_spelling_and_however_many_others_there_are(self):
        expected = [
            {"id": self.rig["id"], "name": "rig", "script": "assemblies/rig.py", "kind": "assembly", "updated": 1761555700.0},
            {"id": self.plate["id"], "name": "plate", "script": "parts/plate.py", "kind": "part", "updated": 1761555600.5},
        ]
        for spelled in (str(self.project), os.path.realpath(self.project), str(self.project) + "/"):
            self.assertEqual(folder_models(self.registry, spelled), {"models": expected})
        self.assertEqual(len(folder_models(self.registry, str(self.tmp / "other"))["models"]), 220)
        with self.assertRaises(ValueError):
            folder_models(self.registry, "bracket")

    def test_twenty_folders_are_read_in_one_read_of_the_registry(self):
        roots = [str(self.project), *(str(self.tmp / f"tile{index}") for index in range(19))]
        for root in roots[1:]:
            Path(root).mkdir()
        reads = []
        listing = self.registry.list
        with mock.patch.object(self.registry, "list", lambda: reads.append(1) or listing()):
            answer = folders_models(self.registry, roots)
        self.assertEqual(len(reads), 1)
        self.assertEqual(list(answer["roots"]), roots)
        self.assertEqual([model["name"] for model in answer["roots"][str(self.project)]], ["rig", "plate"])
        self.assertTrue(all(answer["roots"][root] == [] for root in roots[1:]))

    def test_the_route_answers_it(self):
        app = create_cad_app(host="127.0.0.1", port=0, start=str(self.project))
        server = handler_module.serve(app, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", f"/__cad/models?root={self.project}")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual([model["name"] for model in json.loads(response.read())["models"]], ["rig", "plate"])
        # Several folders, one request: each answered under its own spelling.
        other = self.tmp / "other"
        connection.request("GET", f"/__cad/models?root={self.project}&root={other}")
        response = connection.getresponse()
        answer = json.loads(response.read())
        self.assertEqual(sorted(answer["roots"]), sorted([str(self.project), str(other)]))
        self.assertEqual(len(answer["roots"][str(other)]), 220)
        self.assertNotIn("models", answer)
        connection.request("GET", "/__cad/models")
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        response.read()


if __name__ == "__main__":
    unittest.main()
